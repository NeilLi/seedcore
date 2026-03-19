from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional

from seedcore.coordinator.core.governance import (
    build_twin_snapshot,
    merge_authoritative_twins,
)
from seedcore.coordinator.dao import DigitalTwinDAO
from seedcore.models.action_intent import (
    TwinAuthorityStatus,
    TwinGovernedState,
    TwinSnapshot,
)

logger = logging.getLogger(__name__)


class DigitalTwinService:
    """
    Authoritative digital twin service backed by persisted current-state + version history.

    Runtime resolution order:
    1. Baseline twin shape (for deterministic key coverage).
    2. Persisted authoritative twin snapshot by (twin_type, twin_id).
    3. Live authoritative overlays (state service truth) on sensitive fields.
    """

    def __init__(self, session_factory: Any, dao: Optional[DigitalTwinDAO] = None) -> None:
        self._session_factory = session_factory
        self._dao = dao or DigitalTwinDAO()

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
            persisted_row = persisted_refs.get((baseline.twin_type, baseline.twin_id))
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
                    baseline.twin_type,
                    baseline.twin_id,
                    exc_info=True,
                )

        merged = merge_authoritative_twins(
            resolved_twins,
            dict(authoritative_state or {}),
        )
        return {
            key: value.model_dump(mode="json")
            for key, value in merged.items()
        }

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
        phase = str(context.get("phase") or "policy_time").strip().lower()
        if phase == "settlement":
            verified, reason = self._verify_settlement_node(context=context)
            if not verified:
                logger.warning(
                    "Digital twin settlement rejected for task=%s intent=%s: %s",
                    task_id,
                    intent_id,
                    reason,
                )
                return {"updated": 0, "version_bumped": 0, "rejected_reason": reason}

        updated = 0
        version_bumped = 0
        try:
            async with self._session_factory() as session:
                begin_ctx = session.begin()
                if asyncio.iscoroutine(begin_ctx):
                    begin_ctx = await begin_ctx
                if begin_ctx is not None:
                    async with begin_ctx:
                        for key, value in dict(relevant_twin_snapshot).items():
                            snapshot = self._coerce_twin_snapshot(key, value)
                            snapshot = self._apply_universal_state_machine(
                                snapshot,
                                transition_context=context,
                            )
                            outcome = await self._dao.upsert_snapshot(
                                session,
                                twin_snapshot=snapshot.model_dump(mode="json"),
                                authority_source=authority_source,
                                source_task_id=task_id,
                                source_intent_id=intent_id,
                                change_reason=change_reason,
                            )
                            updated += 1
                            if outcome.get("changed"):
                                version_bumped += 1
                else:
                    for key, value in dict(relevant_twin_snapshot).items():
                        snapshot = self._coerce_twin_snapshot(key, value)
                        snapshot = self._apply_universal_state_machine(
                            snapshot,
                            transition_context=context,
                        )
                        outcome = await self._dao.upsert_snapshot(
                            session,
                            twin_snapshot=snapshot.model_dump(mode="json"),
                            authority_source=authority_source,
                            source_task_id=task_id,
                            source_intent_id=intent_id,
                            change_reason=change_reason,
                        )
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

    async def get_authoritative_twin(
        self,
        *,
        twin_type: str,
        twin_id: str,
    ) -> Optional[Dict[str, Any]]:
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
            logger.warning(
                "Failed to read authoritative digital twin %s:%s",
                twin_type,
                twin_id,
                exc_info=True,
            )
            return None

    async def get_twin_history(
        self,
        *,
        twin_type: str,
        twin_id: str,
        limit: int = 50,
    ) -> list[Dict[str, Any]]:
        if not self._session_factory:
            return []
        try:
            async with self._session_factory() as session:
                return await self._dao.list_history(
                    session,
                    twin_type=twin_type,
                    twin_id=twin_id,
                    limit=limit,
                )
        except Exception:
            logger.warning(
                "Failed to read digital twin history for %s:%s",
                twin_type,
                twin_id,
                exc_info=True,
            )
            return []

    async def get_twin_ancestry(
        self,
        *,
        twin_type: str,
        twin_id: str,
        max_depth: int = 16,
    ) -> list[Dict[str, Any]]:
        lineage: list[Dict[str, Any]] = []
        current_type = str(twin_type)
        current_id = str(twin_id)

        for _ in range(max(1, int(max_depth))):
            row = await self.get_authoritative_twin(
                twin_type=current_type,
                twin_id=current_id,
            )
            if not row:
                break
            lineage.append(row)
            snapshot = row.get("snapshot") if isinstance(row.get("snapshot"), dict) else {}
            parent_twin_id = snapshot.get("parent_twin_id")
            if not isinstance(parent_twin_id, str) or not parent_twin_id.strip():
                break
            parent_twin_id = parent_twin_id.strip()
            if ":" in parent_twin_id:
                current_type = parent_twin_id.split(":", 1)[0]
                current_id = parent_twin_id
            else:
                current_id = parent_twin_id

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
        twin_refs = [
            (snapshot.twin_type, snapshot.twin_id)
            for snapshot in baseline_twins.values()
        ]
        if not twin_refs:
            return {}
        try:
            async with self._session_factory() as session:
                return await self._dao.get_authoritative_snapshots(
                    session,
                    twin_refs=twin_refs,
                )
        except Exception:
            logger.warning("Failed to read persisted digital twin state", exc_info=True)
            return {}

    def _coerce_twin_snapshot(self, key: str, value: Any) -> TwinSnapshot:
        if isinstance(value, TwinSnapshot):
            return value
        if isinstance(value, dict):
            payload = dict(value)
            payload.setdefault("twin_type", str(payload.get("twin_type") or key))
            payload.setdefault("twin_id", str(payload.get("twin_id") or key))
            return TwinSnapshot(**payload)
        return TwinSnapshot(twin_type=key, twin_id=str(value))

    def _apply_universal_state_machine(
        self,
        snapshot: TwinSnapshot,
        *,
        transition_context: Optional[Mapping[str, Any]],
    ) -> TwinSnapshot:
        context = dict(transition_context or {})
        phase = str(context.get("phase") or "policy_time").strip().lower()
        node_id = self._resolve_settlement_node_id(context=context)

        inferred_target = self._infer_target_state(snapshot=snapshot, context=context)
        current = snapshot.governed_state
        if inferred_target is None or inferred_target == current:
            inferred_target = current

        allowed = {
            TwinGovernedState.UNVERIFIED: {TwinGovernedState.CERTIFIED},
            TwinGovernedState.CERTIFIED: {TwinGovernedState.IN_TRANSIT},
            TwinGovernedState.IN_TRANSIT: {TwinGovernedState.DELIVERED},
            TwinGovernedState.DELIVERED: {TwinGovernedState.IN_TRANSIT},
        }
        if inferred_target != current and inferred_target not in allowed.get(current, set()):
            snapshot.pending_exceptions = list(snapshot.pending_exceptions or [])
            snapshot.pending_exceptions.append(
                f"invalid_state_transition:{current.value}->{inferred_target.value}"
            )
            inferred_target = current

        snapshot.governed_state = inferred_target
        snapshot.custody = dict(snapshot.custody or {})
        if phase == "policy_time" and inferred_target in {
            TwinGovernedState.CERTIFIED,
            TwinGovernedState.IN_TRANSIT,
        }:
            snapshot.authority_status = TwinAuthorityStatus.PENDING
            snapshot.custody["pending_authority"] = True
        elif phase == "settlement":
            snapshot.authority_status = TwinAuthorityStatus.AUTHORITATIVE
            snapshot.custody["pending_authority"] = False
            if node_id:
                snapshot.custody["authoritative_node_id"] = node_id
        return snapshot

    def _infer_target_state(
        self,
        *,
        snapshot: TwinSnapshot,
        context: Mapping[str, Any],
    ) -> TwinGovernedState | None:
        evidence_bundle = (
            context.get("evidence_bundle")
            if isinstance(context.get("evidence_bundle"), Mapping)
            else {}
        )
        policy_receipt = (
            context.get("policy_receipt")
            if isinstance(context.get("policy_receipt"), Mapping)
            else {}
        )
        execution_token = (
            context.get("execution_token")
            if isinstance(context.get("execution_token"), Mapping)
            else {}
        )
        evidence_summary = (
            context.get("evidence_summary")
            if isinstance(context.get("evidence_summary"), Mapping)
            else {}
        )

        has_delivery_receipt = bool(
            (evidence_bundle.get("execution_receipt") or {}).get("transition_receipt")
            if isinstance(evidence_bundle.get("execution_receipt"), Mapping)
            else False
        )
        if has_delivery_receipt:
            return TwinGovernedState.DELIVERED

        has_certification = bool(policy_receipt) and bool(
            evidence_bundle.get("asset_fingerprint")
            or evidence_summary.get("asset_fingerprint")
        )
        if has_certification:
            return TwinGovernedState.CERTIFIED

        has_movement_authorization = bool(execution_token) or bool(
            (policy_receipt.get("execution_token") if isinstance(policy_receipt, Mapping) else {})
        )
        if has_movement_authorization and snapshot.twin_type in {"asset", "product", "batch", "transaction"}:
            return TwinGovernedState.IN_TRANSIT

        return None

    def _verify_settlement_node(self, *, context: Mapping[str, Any]) -> tuple[bool, str]:
        evidence_bundle = (
            context.get("evidence_bundle")
            if isinstance(context.get("evidence_bundle"), Mapping)
            else {}
        )
        execution_receipt = (
            evidence_bundle.get("execution_receipt")
            if isinstance(evidence_bundle.get("execution_receipt"), Mapping)
            else {}
        )
        bundle_node_id = evidence_bundle.get("node_id")
        receipt_node_id = execution_receipt.get("node_id")
        execution_token = (
            context.get("execution_token")
            if isinstance(context.get("execution_token"), Mapping)
            else {}
        )
        constraints = (
            execution_token.get("constraints")
            if isinstance(execution_token.get("constraints"), Mapping)
            else {}
        )
        expected_node_id = constraints.get("endpoint_id")

        resolved_node = self._resolve_settlement_node_id(context=context)
        if not resolved_node:
            return False, "missing_node_id"
        if bundle_node_id and receipt_node_id and str(bundle_node_id) != str(receipt_node_id):
            return False, "node_id_mismatch_bundle_vs_receipt"
        if expected_node_id and str(expected_node_id) != str(resolved_node):
            return False, "node_id_mismatch_expected_endpoint"
        return True, "ok"

    def _resolve_settlement_node_id(self, *, context: Mapping[str, Any]) -> Optional[str]:
        evidence_bundle = (
            context.get("evidence_bundle")
            if isinstance(context.get("evidence_bundle"), Mapping)
            else {}
        )
        execution_receipt = (
            evidence_bundle.get("execution_receipt")
            if isinstance(evidence_bundle.get("execution_receipt"), Mapping)
            else {}
        )
        for candidate in (
            evidence_bundle.get("node_id"),
            execution_receipt.get("node_id"),
        ):
            if candidate is None:
                continue
            node_id = str(candidate).strip()
            if node_id:
                return node_id
        return None
