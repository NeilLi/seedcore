# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""Default SemanticMemory service over HolonFabric (callers should not touch fabric.vec/graph)."""
from __future__ import annotations

import logging
from typing import Any, List, Optional

import numpy as np

from seedcore.models.holon import Holon, HolonScope

from .contracts import (
    HolonRelation,
    MemoryHealth,
    MemorySubsystemStatus,
    SemanticMemoryStats,
    SemanticSearchQuery,
    SemanticSearchResult,
)
from .holon_fabric import HolonFabric

logger = logging.getLogger(__name__)


def _holon_to_search_result(h: Holon) -> SemanticSearchResult:
    dump = h.model_dump() if hasattr(h, "model_dump") else h.dict()
    return SemanticSearchResult(
        holon_id=str(dump.get("id", "")),
        summary=str(dump.get("summary", "")),
        type=str(dump.get("type", "fact")),
        scope=str(dump.get("scope", "global")),
        content=dict(dump.get("content") or {}),
        confidence=float(dump.get("confidence", 1.0)),
    )


class SemanticMemoryService:
    """Advisory semantic store: use for retrieval and promotion, not PDP authority."""

    def __init__(self, fabric: HolonFabric) -> None:
        self._fabric = fabric

    @property
    def holon_fabric(self) -> HolonFabric:
        """Compatibility escape hatch; prefer this service's methods."""
        return self._fabric

    async def upsert_holon(self, holon: Holon) -> None:
        await self._fabric.insert_holon(holon)

    async def get_holon(self, holon_id: str) -> Optional[Holon]:
        return await self._fabric.get_holon(holon_id)

    async def search(self, query: SemanticSearchQuery) -> List[SemanticSearchResult]:
        def _parse_scope(label: str) -> HolonScope:
            key = str(label).strip().lower()
            mapping = {
                "global": HolonScope.GLOBAL,
                "organ": HolonScope.ORGAN,
                "entity": HolonScope.ENTITY,
                "ephemeral": HolonScope.EPHEMERAL,
            }
            return mapping.get(key, HolonScope.GLOBAL)

        scopes = []
        for s in query.scopes:
            scopes.append(_parse_scope(s))
        if not scopes:
            scopes = [HolonScope.GLOBAL]
        emb = np.asarray(query.embedding, dtype=np.float32)
        holons = await self._fabric.query_context(
            query_vec=emb,
            scopes=scopes,
            organ_id=query.organ_id,
            entity_ids=query.entity_ids,
            limit=query.limit,
            hydrate_neighbors=query.hydrate_neighbors,
            neighbor_limit=query.neighbor_limit,
        )
        out: List[SemanticSearchResult] = []
        for h in holons:
            sr = _holon_to_search_result(h)
            out.append(sr)
        return out

    async def list_relationships(
        self, holon_id: str, *, limit: int = 50
    ) -> List[HolonRelation]:
        return await self._fabric.list_relationships(holon_id, limit=limit)

    async def delete_holon(self, holon_id: str) -> None:
        await self._fabric.delete_holon(holon_id)

    async def stats_snapshot(self) -> SemanticMemoryStats:
        try:
            stats = await self._fabric.get_stats()
            return SemanticMemoryStats(
                health=MemoryHealth(
                    status=MemorySubsystemStatus.ENABLED, reason=None
                ),
                total_holons=int(stats.get("total_holons", 0)),
                total_relationships=int(stats.get("total_relationships", 0)),
                bytes_used=int(stats.get("bytes_used", 0)),
                extras={k: v for k, v in stats.items() if k not in ("total_holons", "total_relationships", "bytes_used")},
            )
        except Exception as e:
            logger.warning("Semantic stats_snapshot degraded: %s", e)
            return SemanticMemoryStats(
                health=MemoryHealth(
                    status=MemorySubsystemStatus.DEGRADED, reason=str(e)
                )
            )
