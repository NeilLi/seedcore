from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Mapping, Optional

from seedcore.coordinator.core.governance import (
    build_twin_snapshot,
    merge_authoritative_twins,
)
from seedcore.coordinator.dao import DigitalTwinDAO
from seedcore.models.action_intent import TwinSnapshot

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
    ) -> Dict[str, Any]:
        if not relevant_twin_snapshot or not self._session_factory:
            return {"updated": 0, "version_bumped": 0}

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
