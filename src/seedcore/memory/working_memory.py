# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""MwManager adapter implementing the WorkingMemory contract."""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Optional

from .contracts import MemoryHealth, MemorySubsystemStatus, WorkingMemoryStats
from .mw_manager import MwManager

logger = logging.getLogger(__name__)


class MwWorkingMemoryAdapter:
    """Wraps MwManager with the unified WorkingMemory protocol."""

    def __init__(self, mw: MwManager) -> None:
        self._mw = mw

    async def get(self, key: str, *, is_global: bool = False) -> Any:
        return await self._mw.get_item_async(key, is_global=is_global)

    def put(self, key: str, value: Any, ttl_s: Optional[int] = None) -> None:
        self._mw.set_item(key, value, ttl_s=ttl_s)

    def put_global_typed(
        self,
        kind: str,
        scope: str,
        item_id: str,
        value: Any,
        ttl_s: Optional[int] = None,
    ) -> None:
        self._mw.set_global_item_typed(kind, scope, item_id, value, ttl_s=ttl_s)

    async def delete(self, key: str, *, is_global: bool = False) -> None:
        if is_global:
            await self._mw.del_global_key(key)
        else:
            self._mw.delete_organ_item(key)

    async def append_episode(
        self,
        *,
        agent_id: str,
        episode: Any,
        ttl_s: Optional[int] = None,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return await self._mw.append_episode_async(
            agent_id=agent_id,
            episode=episode,
            ttl_s=ttl_s,
            max_items=max_items,
        )

    async def get_recent_episode(
        self, *, organ_id: Optional[str], agent_id: str, k: int = 10
    ) -> List[Dict[str, Any]]:
        result = self._mw.get_recent_episode(
            organ_id=organ_id, agent_id=agent_id, k=k
        )
        if inspect.isawaitable(result):
            result = await result
        return result or []

    def set_negative_cache(
        self, kind: str, scope: str, item_id: str, ttl_s: int = 30
    ) -> None:
        self._mw.set_negative_cache(kind, scope, item_id, ttl_s=ttl_s)

    async def check_negative_cache(
        self, kind: str, scope: str, item_id: str
    ) -> bool:
        return await self._mw.check_negative_cache(kind, scope, item_id)

    async def try_set_inflight(self, key: str, ttl_s: int = 5) -> bool:
        return await self._mw.try_set_inflight(key, ttl_s=ttl_s)

    async def clear_inflight(self, key: str) -> None:
        await self._mw.del_global_key(key)

    async def stats_snapshot(self) -> WorkingMemoryStats:
        try:
            fn = getattr(self._mw, "get_telemetry_async", self._mw.get_telemetry)
            if inspect.iscoroutinefunction(fn):
                telemetry = await fn()
            else:
                telemetry = fn()
            total = int(telemetry.get("total_requests", 0))
            hits = int(telemetry.get("hits", 0))
            misses = int(telemetry.get("misses", 0))
            hit_ratio = float(telemetry.get("hit_ratio", 0.0))
            return WorkingMemoryStats(
                health=MemoryHealth(status=MemorySubsystemStatus.ENABLED),
                total_requests=total,
                hits=hits,
                misses=misses,
                hit_ratio=hit_ratio,
                l0_hits=int(telemetry.get("l0_hits", 0)),
                l1_hits=int(telemetry.get("l1_hits", 0)),
                l2_hits=int(telemetry.get("l2_hits", 0)),
                task_hit_ratio=float(telemetry.get("task_hit_ratio", 0.0)),
                extras={k: v for k, v in telemetry.items() if k not in ("total_requests", "hits", "misses", "hit_ratio")},
            )
        except Exception as e:
            logger.warning("Working memory stats_snapshot degraded: %s", e)
            return WorkingMemoryStats(
                health=MemoryHealth(
                    status=MemorySubsystemStatus.DEGRADED, reason=str(e)
                )
            )
