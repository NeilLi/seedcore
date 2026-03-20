from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional

from seedcore.coordinator.core.governance import build_twin_snapshot, merge_authoritative_twins
from seedcore.coordinator.dao import DigitalTwinDAO, DigitalTwinEventJournalDAO
from seedcore.models.action_intent import TwinRevisionStage, TwinSnapshot

logger = logging.getLogger(__name__)


TWIN_UPDATE_POLICY: dict[str, set[str]] = {
    "policy_created": {"owner", "assistant", "asset", "edge", "transaction"},
    "intent_bound": {"owner", "assistant", "asset", "edge", "transaction"},
    "token_issued": {"owner", "assistant", "asset", "transaction"},
    "action_executed": {"asset", "edge", "transaction"},
    "evidence_settled": {"asset", "edge", "transaction"},
    "dispute_opened": {"owner", "assistant", "asset", "edge", "transaction"},
}


class DigitalTwinService:
    def __init__(
        self,
        session_factory: Any,
        dao: Optional[DigitalTwinDAO] = None,
        event_dao: Optional[DigitalTwinEventJournalDAO] = None,
    ) -> None:
        self._session_factory = session_factory
        self._dao = dao or DigitalTwinDAO()
        self._event_dao = event_dao or DigitalTwinEventJournalDAO()

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
        context = dict(transition_context or {})
        event_type = self._resolve_event_type(context)
        if event_type == "evidence_settled":
            verified, reason = self._verify_settlement_node(context=context)
            if not verified:
                return {"updated": 0, "version_bumped": 0, "rejected_reason": reason}

        updated = 0
        version_bumped = 0
        try:
            async with self._session_factory() as session:
                begin_ctx = session.begin()
                if asyncio.iscoroutine(begin_ctx):
                    begin_ctx = await begin_ctx
                async with begin_ctx:
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
        except Exception:
            logger.warning(
                "Failed to persist digital twin state for task=%s intent=%s",
                task_id,
                intent_id,
                exc_info=True,
            )
            return {"updated": 0, "version_bumped": 0}
        return {"updated": updated, "version_bumped": version_bumped}

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
        elif event_type == "evidence_settled":
            snapshot.revision_stage = TwinRevisionStage.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            node_id = self._resolve_settlement_node_id(context=context)
            if node_id:
                snapshot.custody["authoritative_node_id"] = node_id
        elif event_type == "dispute_opened":
            snapshot.revision_stage = TwinRevisionStage.DISPUTED
            snapshot.custody["pending_authority"] = False

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
        if transition_receipts and snapshot.twin_kind in {"asset", "transaction"}:
            return "DELIVERED"
        if context.get("evidence_summary") and snapshot.twin_kind in {"asset", "transaction"}:
            return "CERTIFIED"
        execution_token = context.get("execution_token") if isinstance(context.get("execution_token"), Mapping) else {}
        if execution_token and snapshot.twin_kind in {"asset", "transaction"}:
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
