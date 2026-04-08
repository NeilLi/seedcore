# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""Optional incident (flashbulb) memory behind a single contract."""
from __future__ import annotations

import asyncio
import inspect
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from .contracts import IncidentMemoryStats, MemoryHealth, MemorySubsystemStatus

logger = logging.getLogger(__name__)


class InMemoryIncidentBackend:
    """Process-local store when no SQL flashbulb backend is configured."""

    def __init__(self) -> None:
        self._rows: Dict[str, Dict[str, Any]] = {}

    def record(self, event_data: Dict[str, Any], salience_score: float) -> str:
        iid = str(uuid.uuid4())
        self._rows[iid] = {
            "incident_id": iid,
            "salience_score": salience_score,
            "event_data": dict(event_data),
        }
        return iid

    def get(self, incident_id: str) -> Optional[Dict[str, Any]]:
        return self._rows.get(incident_id)

    def list(self, limit: int) -> List[Dict[str, Any]]:
        return list(self._rows.values())[:limit]


class IncidentMemoryService:
    """High-salience incidents; optional DB hook via record_fn/get_fn/list_fn."""

    def __init__(
        self,
        *,
        backend: Optional[InMemoryIncidentBackend] = None,
        record_fn: Optional[Callable[..., Any]] = None,
        get_fn: Optional[Callable[..., Any]] = None,
        list_fn: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._mem = backend or InMemoryIncidentBackend()
        self._record_fn = record_fn
        self._get_fn = get_fn
        self._list_fn = list_fn

    async def record_incident(
        self, event_data: Dict[str, Any], salience_score: float
    ) -> str:
        if self._record_fn is not None:
            result = self._record_fn(event_data, salience_score)
            if inspect.isawaitable(result):
                return await result  # type: ignore[return-value]
            return str(result)
        return await asyncio.to_thread(
            self._mem.record, event_data, salience_score
        )

    async def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        if self._get_fn is not None:
            result = self._get_fn(incident_id)
            if inspect.isawaitable(result):
                return await result  # type: ignore[return-value]
            return result  # type: ignore[return-value]
        return await asyncio.to_thread(self._mem.get, incident_id)

    async def list_incidents(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        if self._list_fn is not None:
            result = self._list_fn(limit=limit)
            if inspect.isawaitable(result):
                return await result  # type: ignore[return-value]
            return list(result)  # type: ignore[return-value]
        return await asyncio.to_thread(self._mem.list, limit)

    async def stats_snapshot(self) -> IncidentMemoryStats:
        try:
            rows = await self.list_incidents(limit=10_000)
            return IncidentMemoryStats(
                health=MemoryHealth(status=MemorySubsystemStatus.ENABLED),
                incidents_recorded=len(rows),
            )
        except Exception as e:
            logger.warning("Incident stats_snapshot degraded: %s", e)
            return IncidentMemoryStats(
                health=MemoryHealth(
                    status=MemorySubsystemStatus.UNAVAILABLE, reason=str(e)
                )
            )
