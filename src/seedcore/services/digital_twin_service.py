from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, TYPE_CHECKING

from seedcore.coordinator.core.governance import build_twin_snapshot, merge_authoritative_twins
from seedcore.coordinator.dao import DigitalTwinDAO, DigitalTwinEventJournalDAO
from seedcore.models.action_intent import TwinRevisionStage, TwinSnapshot
from seedcore.ops.evidence.verification import verify_evidence_bundle_result

if TYPE_CHECKING:
    from seedcore.models.result_verifier_outcome import ResultVerifierOutcome

logger = logging.getLogger(__name__)

# Fail-closed verdicts when the RESULT_VERIFIER gate cannot read authoritative twin state.
RESULT_VERIFIER_GATE_FAILURE_REASONS: dict[str, str] = {
    "result_verifier_gate_session_unavailable": (
        "Authoritative digital twin session factory is unavailable; "
        "RESULT_VERIFIER gate cannot be evaluated and fails closed."
    ),
    "result_verifier_gate_lookup_failed": (
        "Authoritative digital twin snapshot lookup failed; "
        "RESULT_VERIFIER gate fails closed."
    ),
    "result_verifier_gate_service_unavailable": (
        "Digital twin service is unavailable; RESULT_VERIFIER gate fails closed."
    ),
    "result_verifier_gate_unavailable": (
        "Digital twin service does not expose evaluate_result_verifier_gate; "
        "RESULT_VERIFIER gate fails closed."
    ),
    "result_verifier_gate_eval_failed": (
        "RESULT_VERIFIER gate evaluation raised an error; fails closed."
    ),
    "result_verifier_gate_invalid_verdict": (
        "RESULT_VERIFIER gate returned an invalid verdict; fails closed."
    ),
}


def build_result_verifier_gate_failure_verdict(*, reason_code: str, checked_refs: int) -> Dict[str, Any]:
    """Return a blocked verdict when the gate cannot prove a clean authoritative state (RCT fail-closed)."""
    return {
        "blocked": True,
        "reason_code": reason_code,
        "reason": RESULT_VERIFIER_GATE_FAILURE_REASONS.get(
            reason_code,
            "RESULT_VERIFIER gate failed closed due to an unresolved infrastructure condition.",
        ),
        "checked_refs": checked_refs,
    }


TWIN_UPDATE_POLICY: dict[str, set[str]] = {
    "policy_created": {"owner", "assistant", "asset", "batch", "product", "edge", "transaction"},
    "intent_bound": {"owner", "assistant", "asset", "batch", "product", "edge", "transaction"},
    "token_issued": {"owner", "assistant", "asset", "batch", "product", "transaction"},
    "action_executed": {"asset", "batch", "product", "edge", "transaction"},
    "transition_recorded": {"asset", "batch", "transaction"},
    "evidence_settled": {"asset", "batch", "product", "edge", "transaction"},
    "dispute_opened": {"owner", "assistant", "asset", "batch", "product", "edge", "transaction"},
    "dispute_resolved": {"owner", "assistant", "asset", "batch", "product", "edge", "transaction"},
    "registration_confirmed": {"asset", "batch", "product"},
    "registration_quarantined": {"asset", "batch", "product"},
    "verification_passed": {"asset", "batch", "transaction", "edge", "product"},
    "verification_quarantined": {"asset", "batch", "transaction"},
    "verification_failed": {"asset", "batch", "transaction"},
}


class DigitalTwinService:
    def __init__(
        self,
        session_factory: Any,
        dao: Optional[DigitalTwinDAO] = None,
        event_dao: Optional[DigitalTwinEventJournalDAO] = None,
        incident_memory: Any = None,
    ) -> None:
        self._session_factory = session_factory
        self._dao = dao or DigitalTwinDAO()
        self._event_dao = event_dao or DigitalTwinEventJournalDAO()
        self._incident_memory = incident_memory

    async def resolve_relevant_twins(
        self,
        task: Mapping[str, Any] | Dict[str, Any],
        *,
        authoritative_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        baseline_twins = build_twin_snapshot(task)
        resolved_twins = {
            key: TwinSnapshot(**snapshot.model_dump(mode="json"))
            for key, snapshot in baseline_twins.items()
        }
        persisted_refs = await self._load_persisted_refs(baseline_twins)
        for key, baseline in baseline_twins.items():
            persisted_row = persisted_refs.get((baseline.twin_kind, baseline.twin_id))
            if not persisted_row:
                continue
            persisted_snapshot = persisted_row.get("snapshot")
            if not isinstance(persisted_snapshot, dict):
                continue
            try:
                resolved_twins[key] = self._coerce_twin_snapshot(key, persisted_snapshot)
            except Exception:
                logger.debug(
                    "Ignoring invalid persisted digital twin snapshot for %s:%s",
                    baseline.twin_kind,
                    baseline.twin_id,
                    exc_info=True,
                )
        merged = merge_authoritative_twins(resolved_twins, dict(authoritative_state or {}))
        return {key: value.model_dump(mode="json") for key, value in merged.items()}

    async def persist_relevant_twins(
        self,
        *,
        relevant_twin_snapshot: Mapping[str, Any],
        task_id: Optional[str],
        intent_id: Optional[str],
        authority_source: str = "coordinator.pdp",
        change_reason: str = "policy_case_resolution",
        transition_context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not relevant_twin_snapshot or not self._session_factory:
            return {"updated": 0, "version_bumped": 0}
        try:
            async with self._session_factory() as session:
                begin_ctx = session.begin()
                if asyncio.iscoroutine(begin_ctx):
                    begin_ctx = await begin_ctx
                async with begin_ctx:
                    return await self.persist_relevant_twins_in_session(
                        session,
                        relevant_twin_snapshot=relevant_twin_snapshot,
                        task_id=task_id,
                        intent_id=intent_id,
                        authority_source=authority_source,
                        change_reason=change_reason,
                        transition_context=transition_context,
                    )
        except Exception:
            logger.warning(
                "Failed to persist digital twin state for task=%s intent=%s",
                task_id,
                intent_id,
                exc_info=True,
            )
            return {"updated": 0, "version_bumped": 0}

    async def persist_relevant_twins_in_session(
        self,
        session,
        *,
        relevant_twin_snapshot: Mapping[str, Any],
        task_id: Optional[str],
        intent_id: Optional[str],
        authority_source: str = "coordinator.pdp",
        change_reason: str = "policy_case_resolution",
        transition_context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not relevant_twin_snapshot:
            return {"updated": 0, "version_bumped": 0}
        context = dict(transition_context or {})
        event_type = self._resolve_event_type(context)
        if event_type == "evidence_settled":
            settlement_verification = await self._verify_settlement(
                context=context,
                task_id=task_id,
                intent_id=intent_id,
                relevant_twin_snapshot=relevant_twin_snapshot,
            )
            if not settlement_verification["verified"]:
                return {
                    "updated": 0,
                    "version_bumped": 0,
                    "rejected_reason": settlement_verification["reason"],
                    "verification": settlement_verification,
                }

        updated = 0
        version_bumped = 0
        for key, value in dict(relevant_twin_snapshot).items():
            snapshot = self._coerce_twin_snapshot(key, value)
            snapshot = self._apply_update_policy(snapshot=snapshot, context=context)
            outcome = await self._dao.upsert_snapshot(
                session,
                twin_snapshot=snapshot.model_dump(mode="json"),
                authority_source=authority_source,
                source_task_id=task_id,
                source_intent_id=intent_id,
                change_reason=change_reason,
            )
            try:
                await self._event_dao.append_event(
                    session,
                    twin_kind=snapshot.twin_kind,
                    twin_id=snapshot.twin_id,
                    event_type=event_type,
                    revision_stage=snapshot.revision_stage.value,
                    lifecycle_state=snapshot.lifecycle_state,
                    task_id=task_id,
                    intent_id=intent_id,
                    payload={
                        "snapshot": snapshot.model_dump(mode="json"),
                        "context": context,
                    },
                )
            except Exception:
                logger.debug("Twin event journal append skipped", exc_info=True)
            updated += 1
            if outcome.get("changed"):
                version_bumped += 1
        return {"updated": updated, "version_bumped": version_bumped}

    async def load_authoritative_snapshots(
        self,
        session,
        *,
        twin_refs: list[tuple[str, str]],
    ) -> Dict[str, Dict[str, Any]]:
        getter = getattr(self._dao, "get_authoritative_snapshots", None)
        if getter is None:
            return {}
        rows = await getter(session, twin_refs=twin_refs)
        snapshots: Dict[str, Dict[str, Any]] = {}
        for (twin_type, _twin_id), row in rows.items():
            snapshot = row.get("snapshot")
            if isinstance(snapshot, dict):
                snapshots[twin_type] = dict(snapshot)
        return snapshots

    async def get_authoritative_twin(self, *, twin_type: str, twin_id: str) -> Optional[Dict[str, Any]]:
        if not self._session_factory:
            return None
        try:
            async with self._session_factory() as session:
                return await self._dao.get_authoritative_snapshot(
                    session,
                    twin_type=twin_type,
                    twin_id=twin_id,
                )
        except Exception:
            logger.warning("Failed to read authoritative digital twin %s:%s", twin_type, twin_id, exc_info=True)
            return None

    async def get_twin_history(self, *, twin_type: str, twin_id: str, limit: int = 50) -> list[Dict[str, Any]]:
        if not self._session_factory:
            return []
        try:
            async with self._session_factory() as session:
                return await self._dao.list_history(session, twin_type=twin_type, twin_id=twin_id, limit=limit)
        except Exception:
            logger.warning("Failed to read digital twin history for %s:%s", twin_type, twin_id, exc_info=True)
            return []

    async def verify_local_ledger_projection(
        self,
        *,
        twin_type: str,
        twin_id: str,
        limit: int = 500,
        session: Any = None,
    ) -> Dict[str, Any]:
        normalized_type = str(twin_type).strip()
        normalized_id = str(twin_id).strip()
        if not normalized_type or not normalized_id:
            return {"verified": False, "reason": "missing_twin_ref"}

        if session is not None:
            authoritative_row = await self._dao.get_authoritative_snapshot(
                session,
                twin_type=normalized_type,
                twin_id=normalized_id,
            )
            journal_rows = await self._event_dao.list_events(
                session,
                twin_type=normalized_type,
                twin_id=normalized_id,
                limit=limit,
            )
        else:
            if not self._session_factory:
                return {"verified": False, "reason": "session_factory_unavailable"}
            try:
                async with self._session_factory() as query_session:
                    authoritative_row = await self._dao.get_authoritative_snapshot(
                        query_session,
                        twin_type=normalized_type,
                        twin_id=normalized_id,
                    )
                    journal_rows = await self._event_dao.list_events(
                        query_session,
                        twin_type=normalized_type,
                        twin_id=normalized_id,
                        limit=limit,
                    )
            except Exception:
                logger.warning(
                    "Failed to verify local ledger projection for %s:%s",
                    normalized_type,
                    normalized_id,
                    exc_info=True,
                )
                return {"verified": False, "reason": "ledger_lookup_failed"}

        if authoritative_row is None:
            return {"verified": False, "reason": "authoritative_snapshot_missing"}
        if not journal_rows:
            return {"verified": False, "reason": "event_journal_missing"}

        chronological_rows = list(reversed(journal_rows))
        replayed_snapshot: Optional[Dict[str, Any]] = None
        last_event_type: Optional[str] = None
        for row in chronological_rows:
            payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
            payload_snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), Mapping) else None
            if payload_snapshot is None:
                return {
                    "verified": False,
                    "reason": "journal_snapshot_missing",
                    "event_id": str(row.get("id") or ""),
                }
            replayed_snapshot = self._coerce_twin_snapshot(
                normalized_type,
                dict(payload_snapshot),
            ).model_dump(mode="json")
            last_event_type = str(row.get("event_type") or "") or last_event_type

        authoritative_snapshot = authoritative_row.get("snapshot")
        if not isinstance(authoritative_snapshot, dict):
            return {"verified": False, "reason": "authoritative_snapshot_invalid"}

        normalized_authoritative = self._coerce_twin_snapshot(
            normalized_type,
            authoritative_snapshot,
        ).model_dump(mode="json")
        projection_matches = self._canonicalize_snapshot(replayed_snapshot or {}) == self._canonicalize_snapshot(
            normalized_authoritative
        )
        return {
            "verified": projection_matches,
            "projection_matches": projection_matches,
            "twin_type": normalized_type,
            "twin_id": normalized_id,
            "event_count": len(chronological_rows),
            "last_event_type": last_event_type,
            "state_version": authoritative_row.get("state_version"),
            "authoritative_snapshot": normalized_authoritative,
            "replayed_snapshot": replayed_snapshot,
        }

    async def get_twin_ancestry(self, *, twin_type: str, twin_id: str, max_depth: int = 16) -> list[Dict[str, Any]]:
        lineage: list[Dict[str, Any]] = []
        current_type = str(twin_type)
        current_id = str(twin_id)
        for _ in range(max(1, int(max_depth))):
            row = await self.get_authoritative_twin(twin_type=current_type, twin_id=current_id)
            if not row:
                break
            lineage.append(row)
            snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
            lineage_refs = snapshot.get("lineage_refs") if isinstance(snapshot.get("lineage_refs"), list) else []
            parent = next((str(item) for item in lineage_refs if isinstance(item, str) and item.strip()), None)
            if not parent:
                fallback_parent = snapshot.get("parent_twin_id")
                if isinstance(fallback_parent, str) and fallback_parent.strip():
                    parent = fallback_parent.strip()
            if not parent:
                break
            current_id = parent
            current_type = parent.split(":", 1)[0] if ":" in parent else current_type
        return lineage

    async def evaluate_result_verifier_gate(
        self,
        *,
        twin_refs: list[tuple[str, str]],
        session: Any = None,
    ) -> Dict[str, Any]:
        """Return fail-closed gate verdict from authoritative verifier lockout state."""
        normalized_refs = [
            (str(twin_type).strip(), str(twin_id).strip())
            for twin_type, twin_id in twin_refs
            if str(twin_type).strip() and str(twin_id).strip()
        ]
        if not normalized_refs:
            return {"blocked": False, "checked_refs": 0}

        try:
            if session is not None:
                rows = await self._dao.get_authoritative_snapshots(session, twin_refs=normalized_refs)
            else:
                if not self._session_factory:
                    return build_result_verifier_gate_failure_verdict(
                        reason_code="result_verifier_gate_session_unavailable",
                        checked_refs=len(normalized_refs),
                    )
                async with self._session_factory() as query_session:
                    rows = await self._dao.get_authoritative_snapshots(query_session, twin_refs=normalized_refs)
        except Exception:
            logger.warning("Failed to resolve RESULT_VERIFIER gate snapshots", exc_info=True)
            return build_result_verifier_gate_failure_verdict(
                reason_code="result_verifier_gate_lookup_failed",
                checked_refs=len(normalized_refs),
            )

        for twin_type, twin_id in normalized_refs:
            row = rows.get((twin_type, twin_id))
            snapshot = row.get("snapshot") if isinstance(row, dict) else None
            verdict = self._result_verifier_gate_from_snapshot(
                twin_type=twin_type,
                twin_id=twin_id,
                snapshot=snapshot if isinstance(snapshot, dict) else {},
            )
            if verdict.get("blocked"):
                verdict["checked_refs"] = len(normalized_refs)
                return verdict

        return {"blocked": False, "checked_refs": len(normalized_refs)}

    async def settle_from_evidence_bundle(
        self,
        *,
        relevant_twin_snapshot: Mapping[str, Any],
        task_id: Optional[str],
        intent_id: Optional[str],
        policy_receipt: Mapping[str, Any] | None = None,
        execution_token: Mapping[str, Any] | None = None,
        evidence_summary: Mapping[str, Any] | None = None,
        evidence_bundle: Mapping[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return await self.persist_relevant_twins(
            relevant_twin_snapshot=relevant_twin_snapshot,
            task_id=task_id,
            intent_id=intent_id,
            authority_source="governed_transition_receipt",
            change_reason="execution_settlement",
            transition_context={
                "phase": "settlement",
                "event_type": "evidence_settled",
                "policy_receipt": dict(policy_receipt or {}),
                "execution_token": dict(execution_token or {}),
                "evidence_summary": dict(evidence_summary or {}),
                "evidence_bundle": dict(evidence_bundle or {}),
            },
        )

    async def apply_result_verifier_outcome(
        self,
        outcome: "ResultVerifierOutcome",
        *,
        task_id: Optional[str],
        intent_id: Optional[str],
        session: Any = None,
    ) -> Dict[str, Any]:
        """Authoritative fail-closed twin/custody mutation after RESULT_VERIFIER (RCT v1)."""
        event_type = str(outcome.twin_event_type or "").strip()
        if not event_type:
            return {"updated": 0, "reason": "no_twin_event"}
        asset_ref = str(outcome.asset_id or "").strip()
        if not asset_ref:
            return {"updated": 0, "reason": "missing_asset_id"}
        twin_id = asset_ref if asset_ref.startswith("asset:") else f"asset:{asset_ref}"
        raw_id = twin_id.split(":", 1)[1] if ":" in twin_id else twin_id

        existing = await self._get_authoritative_twin_row(
            twin_type="asset",
            twin_id=twin_id,
            session=session,
        )
        base_snapshot = self._build_result_verifier_subject_snapshot(
            twin_type="asset",
            twin_id=twin_id,
            raw_subject_id=raw_id,
            existing_row=existing,
        )
        ctx = self._build_result_verifier_context(outcome=outcome, event_type=event_type)

        relevant = {"asset": base_snapshot}
        if session is not None:
            return await self.persist_relevant_twins_in_session(
                session,
                relevant_twin_snapshot=relevant,
                task_id=task_id,
                intent_id=intent_id,
                authority_source="result_verifier",
                change_reason="result_verifier_enforcement",
                transition_context=ctx,
            )
        return await self.persist_relevant_twins(
            relevant_twin_snapshot=relevant,
            task_id=task_id,
            intent_id=intent_id,
            authority_source="result_verifier",
            change_reason="result_verifier_enforcement",
            transition_context=ctx,
        )

    async def apply_result_verifier_outcome_fallback(
        self,
        outcome: "ResultVerifierOutcome",
        *,
        task_id: Optional[str],
        intent_id: Optional[str],
        session: Any = None,
    ) -> Dict[str, Any]:
        """Fail-closed fallback when RESULT_VERIFIER cannot resolve an asset twin."""
        event_type = str(outcome.twin_event_type or "").strip()
        if event_type not in {"verification_failed", "verification_quarantined"}:
            return {"updated": 0, "reason": "fallback_not_required"}
        intent_ref = str(intent_id or "").strip()
        if not intent_ref:
            return {"updated": 0, "reason": "missing_subject_for_fail_closed"}
        twin_id = intent_ref if intent_ref.startswith("transaction:") else f"transaction:{intent_ref}"
        raw_id = twin_id.split(":", 1)[1] if ":" in twin_id else twin_id

        existing = await self._get_authoritative_twin_row(
            twin_type="transaction",
            twin_id=twin_id,
            session=session,
        )
        base_snapshot = self._build_result_verifier_subject_snapshot(
            twin_type="transaction",
            twin_id=twin_id,
            raw_subject_id=raw_id,
            existing_row=existing,
        )
        ctx = self._build_result_verifier_context(outcome=outcome, event_type=event_type)
        relevant = {"transaction": base_snapshot}

        if session is not None:
            return await self.persist_relevant_twins_in_session(
                session,
                relevant_twin_snapshot=relevant,
                task_id=task_id,
                intent_id=intent_ref,
                authority_source="result_verifier",
                change_reason="result_verifier_enforcement",
                transition_context=ctx,
            )
        return await self.persist_relevant_twins(
            relevant_twin_snapshot=relevant,
            task_id=task_id,
            intent_id=intent_ref,
            authority_source="result_verifier",
            change_reason="result_verifier_enforcement",
            transition_context=ctx,
        )

    async def _get_authoritative_twin_row(
        self,
        *,
        twin_type: str,
        twin_id: str,
        session: Any = None,
    ) -> Optional[Dict[str, Any]]:
        if session is not None:
            return await self._dao.get_authoritative_snapshot(
                session,
                twin_type=twin_type,
                twin_id=twin_id,
            )
        return await self.get_authoritative_twin(twin_type=twin_type, twin_id=twin_id)

    def _build_result_verifier_subject_snapshot(
        self,
        *,
        twin_type: str,
        twin_id: str,
        raw_subject_id: str,
        existing_row: Optional[Mapping[str, Any]],
    ) -> Dict[str, Any]:
        if existing_row and isinstance(existing_row.get("snapshot"), dict):
            base_snapshot = dict(existing_row["snapshot"])
            base_snapshot.setdefault("twin_kind", twin_type)
            base_snapshot.setdefault("twin_id", twin_id)
            base_snapshot.setdefault("custody", {})
            base_snapshot.setdefault("identity", {})
        else:
            if twin_type == "transaction":
                base_snapshot = {
                    "twin_kind": "transaction",
                    "twin_id": twin_id,
                    "lifecycle_state": "PREPARED",
                    "revision_stage": TwinRevisionStage.AUTHORITATIVE.value,
                    "identity": {"intent_id": raw_subject_id},
                    "custody": {"intent_id": raw_subject_id, "pending_authority": False},
                    "delegation": {},
                    "risk": {},
                    "telemetry": {},
                    "evidence_refs": [],
                    "governance": {},
                }
            else:
                base_snapshot = {
                    "twin_kind": "asset",
                    "twin_id": twin_id,
                    "lifecycle_state": "REGISTERED",
                    "revision_stage": TwinRevisionStage.AUTHORITATIVE.value,
                    "identity": {"asset_id": raw_subject_id},
                    "custody": {"asset_id": raw_subject_id, "pending_authority": False},
                    "delegation": {},
                    "risk": {},
                    "telemetry": {},
                    "evidence_refs": [],
                    "governance": {},
                }
        if twin_type == "transaction":
            base_snapshot["identity"].setdefault("intent_id", raw_subject_id)
            base_snapshot["custody"].setdefault("intent_id", raw_subject_id)
        else:
            base_snapshot["identity"].setdefault("asset_id", raw_subject_id)
            base_snapshot["custody"].setdefault("asset_id", raw_subject_id)
        return base_snapshot

    def _build_result_verifier_context(
        self,
        *,
        outcome: "ResultVerifierOutcome",
        event_type: str,
    ) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "phase": "result_verifier",
            "event_type": event_type,
        }
        if outcome.verified:
            ctx["verification_passed_at"] = datetime.now(timezone.utc).isoformat()
            return ctx
        lock_payload = {
            "failure_code": outcome.failure_code,
            "failure_class": outcome.failure_class,
            "issues": list(outcome.issues or [])[:32],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        ctx["result_verifier_lockout"] = lock_payload
        return ctx

    async def _load_persisted_refs(
        self,
        baseline_twins: Mapping[str, TwinSnapshot],
    ) -> Dict[tuple[str, str], Dict[str, Any]]:
        if not self._session_factory:
            return {}
        twin_refs = [(snapshot.twin_kind, snapshot.twin_id) for snapshot in baseline_twins.values()]
        if not twin_refs:
            return {}
        try:
            async with self._session_factory() as session:
                return await self._dao.get_authoritative_snapshots(session, twin_refs=twin_refs)
        except Exception:
            logger.warning("Failed to read persisted digital twin state", exc_info=True)
            return {}

    def _coerce_twin_snapshot(self, key: str, value: Any) -> TwinSnapshot:
        if isinstance(value, TwinSnapshot):
            return value
        if isinstance(value, dict):
            payload = dict(value)
            payload.setdefault("twin_kind", str(payload.get("twin_kind") or payload.get("twin_type") or key))
            payload.setdefault("twin_id", str(payload.get("twin_id") or key))
            if "governed_state" in payload and "lifecycle_state" not in payload:
                payload["lifecycle_state"] = str(payload.get("governed_state"))
            if "authority_status" in payload and "revision_stage" not in payload:
                payload["revision_stage"] = (
                    TwinRevisionStage.AUTHORITATIVE.value
                    if str(payload.get("authority_status")).upper() == TwinRevisionStage.AUTHORITATIVE.value
                    else TwinRevisionStage.PENDING.value
                )
            return TwinSnapshot(**payload)
        return TwinSnapshot(twin_kind=key, twin_id=str(value))

    def _resolve_event_type(self, context: Mapping[str, Any]) -> str:
        explicit = context.get("event_type")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        phase = str(context.get("phase") or "policy_time").strip().lower()
        if phase == "settlement":
            return "evidence_settled"
        if phase == "execution":
            return "action_executed"
        if phase == "transition":
            return "transition_recorded"
        return "policy_created"

    def _apply_update_policy(self, *, snapshot: TwinSnapshot, context: Mapping[str, Any]) -> TwinSnapshot:
        event_type = self._resolve_event_type(context)
        if snapshot.twin_kind not in TWIN_UPDATE_POLICY.get(event_type, set()):
            return snapshot

        inferred_state = self._infer_lifecycle_state(snapshot=snapshot, context=context)
        if inferred_state is not None:
            snapshot.lifecycle_state = inferred_state

        if event_type in {"policy_created", "intent_bound", "token_issued"}:
            snapshot.revision_stage = TwinRevisionStage.PENDING
            snapshot.custody["pending_authority"] = True
        elif event_type == "action_executed":
            snapshot.revision_stage = TwinRevisionStage.EXECUTED
            snapshot.custody["pending_authority"] = True
        elif event_type == "transition_recorded":
            snapshot.revision_stage = TwinRevisionStage.EXECUTED
            snapshot.custody["pending_authority"] = True
            transition_event = (
                context.get("transition_event")
                if isinstance(context.get("transition_event"), Mapping)
                else {}
            )
            if transition_event.get("transition_event_id"):
                snapshot.custody["transition_event_id"] = transition_event.get("transition_event_id")
        elif event_type == "evidence_settled":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            node_id = self._resolve_settlement_node_id(context=context)
            if node_id:
                snapshot.custody["authoritative_node_id"] = node_id
        elif event_type == "dispute_opened":
            governance_state = dict(snapshot.governance or {})
            governance_state.setdefault("pre_dispute_lifecycle_state", snapshot.lifecycle_state)
            snapshot.governance = governance_state
            snapshot.revision_stage = TwinRevisionStage.DISPUTED
            snapshot.custody["pending_authority"] = False
        elif event_type == "dispute_resolved":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            restored = (
                context.get("resolved_lifecycle_state")
                or snapshot.governance.get("pre_dispute_lifecycle_state")
            )
            if isinstance(restored, str) and restored.strip():
                snapshot.lifecycle_state = restored.strip()
        elif event_type in {"registration_confirmed", "registration_quarantined"}:
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
        elif event_type == "verification_failed":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            snapshot.custody["quarantined"] = True
            snapshot.custody["is_quarantined"] = True
            snapshot.custody["authority_source"] = "result_verifier"
            gov = dict(snapshot.governance or {})
            lockouts = list(gov.get("lockouts") or [])
            if "result_verifier_lockout" not in lockouts:
                lockouts.append("result_verifier_lockout")
            gov["lockouts"] = lockouts
            gov["result_verifier_lockout"] = dict(context.get("result_verifier_lockout") or {})
            snapshot.governance = gov
        elif event_type == "verification_quarantined":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            snapshot.custody["quarantined"] = True
            snapshot.custody["is_quarantined"] = True
            snapshot.custody["authority_source"] = "result_verifier"
            gov = dict(snapshot.governance or {})
            lockouts = list(gov.get("lockouts") or [])
            if "result_verifier_lockout" not in lockouts:
                lockouts.append("result_verifier_lockout")
            gov["lockouts"] = lockouts
            gov["result_verifier_lockout"] = dict(context.get("result_verifier_lockout") or {})
            snapshot.governance = gov
        elif event_type == "verification_passed":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            gov = dict(snapshot.governance or {})
            gov["verification_passed_at"] = context.get("verification_passed_at")
            snapshot.governance = gov

        snapshot.evidence_refs = self._collect_evidence_refs(snapshot=snapshot, context=context)
        governance_state = dict(snapshot.governance or {})
        governance_state["last_event_type"] = event_type
        snapshot.governance = governance_state
        return snapshot

    def _infer_lifecycle_state(self, *, snapshot: TwinSnapshot, context: Mapping[str, Any]) -> str | None:
        evidence_bundle = context.get("evidence_bundle") if isinstance(context.get("evidence_bundle"), Mapping) else {}
        evidence_inputs = (
            evidence_bundle.get("evidence_inputs")
            if isinstance(evidence_bundle.get("evidence_inputs"), Mapping)
            else {}
        )
        transition_receipts = (
            evidence_inputs.get("transition_receipts")
            if isinstance(evidence_inputs.get("transition_receipts"), list)
            else []
        )
        event_type = self._resolve_event_type(context)
        if event_type == "dispute_opened":
            return "DISPUTED"
        if event_type == "registration_quarantined" and snapshot.twin_kind in {"asset", "batch"}:
            return "QUARANTINED"
        if event_type == "verification_failed" and snapshot.twin_kind in {"asset", "batch", "transaction"}:
            return "VERIFICATION_FAILED"
        if event_type == "verification_quarantined" and snapshot.twin_kind in {"asset", "batch", "transaction"}:
            return "QUARANTINED"
        if event_type == "registration_confirmed" and snapshot.twin_kind in {"asset", "batch", "product"}:
            return "REGISTERED"
        if event_type == "transition_recorded" and snapshot.twin_kind in {"asset", "batch", "transaction"}:
            return "IN_TRANSIT"
        if transition_receipts and snapshot.twin_kind in {"asset", "transaction"}:
            return "DELIVERED"
        if transition_receipts and snapshot.twin_kind == "batch":
            return "IN_TRANSIT"
        if context.get("evidence_summary") and snapshot.twin_kind in {"asset", "transaction"}:
            return "CERTIFIED"
        if context.get("evidence_summary") and snapshot.twin_kind in {"batch", "product"}:
            return "CERTIFIED"
        execution_token = context.get("execution_token") if isinstance(context.get("execution_token"), Mapping) else {}
        if execution_token and snapshot.twin_kind in {"asset", "batch", "product", "transaction"}:
            return "IN_TRANSIT"
        if snapshot.twin_kind == "edge" and context.get("phase") == "execution":
            return "ACTUATED"
        return None

    def _collect_evidence_refs(self, *, snapshot: TwinSnapshot, context: Mapping[str, Any]) -> list[str]:
        refs: list[str] = list(snapshot.evidence_refs or [])
        policy_receipt = context.get("policy_receipt") if isinstance(context.get("policy_receipt"), Mapping) else {}
        if isinstance(policy_receipt.get("policy_receipt_id"), str):
            refs.append(policy_receipt["policy_receipt_id"])
        evidence_bundle = context.get("evidence_bundle") if isinstance(context.get("evidence_bundle"), Mapping) else {}
        if isinstance(evidence_bundle.get("evidence_bundle_id"), str):
            refs.append(evidence_bundle["evidence_bundle_id"])
        evidence_inputs = evidence_bundle.get("evidence_inputs") if isinstance(evidence_bundle.get("evidence_inputs"), Mapping) else {}
        transition_receipts = evidence_inputs.get("transition_receipts") if isinstance(evidence_inputs.get("transition_receipts"), list) else []
        for item in transition_receipts:
            if isinstance(item, Mapping) and isinstance(item.get("transition_receipt_id"), str):
                refs.append(item["transition_receipt_id"])
        return sorted(set(refs))

    async def _verify_settlement(
        self,
        *,
        context: Mapping[str, Any],
        task_id: Optional[str],
        intent_id: Optional[str],
        relevant_twin_snapshot: Mapping[str, Any],
    ) -> Dict[str, Any]:
        evidence_bundle = context.get("evidence_bundle") if isinstance(context.get("evidence_bundle"), Mapping) else {}
        bundle_verification = verify_evidence_bundle_result(evidence_bundle)
        if bundle_verification.get("verified") is not True:
            reason = str(bundle_verification.get("error") or "evidence_bundle_verification_failed")
            await self._record_settlement_rejection_incident(
                reason=reason,
                context=context,
                task_id=task_id,
                intent_id=intent_id,
                relevant_twin_snapshot=relevant_twin_snapshot,
                bundle_verification=bundle_verification,
            )
            return {
                "verified": False,
                "reason": reason,
                "bundle_verification": bundle_verification,
            }

        verified, reason = self._verify_settlement_node(context=context)
        if not verified:
            await self._record_settlement_rejection_incident(
                reason=reason,
                context=context,
                task_id=task_id,
                intent_id=intent_id,
                relevant_twin_snapshot=relevant_twin_snapshot,
                bundle_verification=bundle_verification,
            )
            return {
                "verified": False,
                "reason": reason,
                "bundle_verification": bundle_verification,
            }

        return {
            "verified": True,
            "reason": "ok",
            "bundle_verification": bundle_verification,
            "resolved_node_id": self._resolve_settlement_node_id(context=context),
        }

    def _verify_settlement_node(self, *, context: Mapping[str, Any]) -> tuple[bool, str]:
        execution_token = context.get("execution_token") if isinstance(context.get("execution_token"), Mapping) else {}
        constraints = execution_token.get("constraints") if isinstance(execution_token.get("constraints"), Mapping) else {}
        expected_node_id = constraints.get("endpoint_id")
        resolved_node = self._resolve_settlement_node_id(context=context)
        if not resolved_node:
            return False, "missing_node_id"
        if expected_node_id and str(expected_node_id) != str(resolved_node):
            return False, "node_id_mismatch_expected_endpoint"
        return True, "ok"

    def _resolve_settlement_node_id(self, *, context: Mapping[str, Any]) -> Optional[str]:
        evidence_bundle = context.get("evidence_bundle") if isinstance(context.get("evidence_bundle"), Mapping) else {}
        evidence_inputs = evidence_bundle.get("evidence_inputs") if isinstance(evidence_bundle.get("evidence_inputs"), Mapping) else {}
        execution_summary = evidence_inputs.get("execution_summary") if isinstance(evidence_inputs.get("execution_summary"), Mapping) else {}
        for candidate in (
            evidence_bundle.get("node_id"),
            execution_summary.get("node_id"),
            (
                evidence_bundle.get("execution_receipt", {}).get("node_id")
                if isinstance(evidence_bundle.get("execution_receipt"), Mapping)
                else None
            ),
        ):
            if candidate is None:
                continue
            node_id = str(candidate).strip()
            if node_id:
                return node_id
        return None

    async def _record_settlement_rejection_incident(
        self,
        *,
        reason: str,
        context: Mapping[str, Any],
        task_id: Optional[str],
        intent_id: Optional[str],
        relevant_twin_snapshot: Mapping[str, Any],
        bundle_verification: Mapping[str, Any],
    ) -> None:
        incident_memory = self._resolve_incident_memory_service()
        if incident_memory is None:
            return
        execution_token = context.get("execution_token") if isinstance(context.get("execution_token"), Mapping) else {}
        constraints = execution_token.get("constraints") if isinstance(execution_token.get("constraints"), Mapping) else {}
        evidence_bundle = context.get("evidence_bundle") if isinstance(context.get("evidence_bundle"), Mapping) else {}
        twin_refs = []
        for key, value in dict(relevant_twin_snapshot or {}).items():
            if not isinstance(value, Mapping):
                continue
            twin_kind = str(value.get("twin_kind") or key).strip()
            twin_id = str(value.get("twin_id") or "").strip()
            if twin_kind and twin_id:
                twin_refs.append({"twin_kind": twin_kind, "twin_id": twin_id})
        try:
            await incident_memory.record_incident(
                {
                    "category": "digital_twin_settlement_rejected",
                    "reason": str(reason),
                    "task_id": task_id,
                    "intent_id": intent_id,
                    "event_type": self._resolve_event_type(context),
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "expected_endpoint_id": constraints.get("endpoint_id"),
                    "resolved_node_id": self._resolve_settlement_node_id(context=context),
                    "evidence_bundle_id": evidence_bundle.get("evidence_bundle_id"),
                    "bundle_verification": dict(bundle_verification),
                    "twin_refs": twin_refs,
                },
                salience_score=0.95,
            )
        except Exception:
            logger.warning("Failed to record settlement rejection incident", exc_info=True)

    def _resolve_incident_memory_service(self) -> Any:
        candidate = self._incident_memory
        if candidate is None:
            return None
        if hasattr(candidate, "record_incident"):
            return candidate
        incident = getattr(candidate, "incident", None)
        if incident is not None and hasattr(incident, "record_incident"):
            return incident
        return None

    def _canonicalize_snapshot(self, snapshot: Mapping[str, Any]) -> str:
        return json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def _result_verifier_gate_from_snapshot(
        self,
        *,
        twin_type: str,
        twin_id: str,
        snapshot: Mapping[str, Any],
    ) -> Dict[str, Any]:
        lifecycle_state = str(snapshot.get("lifecycle_state") or "").strip().upper()
        governance = snapshot.get("governance") if isinstance(snapshot.get("governance"), Mapping) else {}
        lockouts = [
            str(item).strip()
            for item in list(governance.get("lockouts") or [])
            if str(item).strip()
        ]
        has_result_verifier_lockout = (
            "result_verifier_lockout" in lockouts
            or bool(governance.get("result_verifier_lockout"))
        )
        last_event_type = str(governance.get("last_event_type") or "").strip().lower()

        reason_code: Optional[str] = None
        if lifecycle_state == "VERIFICATION_FAILED" or last_event_type == "verification_failed":
            reason_code = "result_verifier_verification_failed"
        elif last_event_type == "verification_quarantined":
            reason_code = "result_verifier_quarantined"
        elif lifecycle_state == "QUARANTINED" and has_result_verifier_lockout:
            reason_code = "result_verifier_quarantined"
        elif has_result_verifier_lockout:
            reason_code = "result_verifier_lockout"

        if reason_code is None:
            return {"blocked": False}

        return {
            "blocked": True,
            "reason_code": reason_code,
            "reason": (
                f"Authoritative RESULT_VERIFIER gate blocked downstream transaction for "
                f"{twin_type}:{twin_id} ({reason_code})."
            ),
            "twin_type": twin_type,
            "twin_id": twin_id,
        }
