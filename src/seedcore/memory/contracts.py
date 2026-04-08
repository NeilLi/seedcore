# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""Caller-facing memory service contracts and DTOs.

Memory reads are advisory for cognition and tools unless explicitly promoted into
a typed, freshness-aware context envelope elsewhere. Governed PDP decisions must not
depend on general-purpose memory services as an authority source.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from pydantic import BaseModel, Field


class MemorySubsystemStatus(str, Enum):
    """Explicit health for telemetry (avoid blending real and simulated stats)."""

    ENABLED = "enabled"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class MemoryHealth(BaseModel):
    status: MemorySubsystemStatus = MemorySubsystemStatus.UNAVAILABLE
    reason: Optional[str] = None


class WorkingMemoryStats(BaseModel):
    """Telemetry snapshot for cache / working memory."""

    health: MemoryHealth = Field(default_factory=MemoryHealth)
    total_requests: int = 0
    hits: int = 0
    misses: int = 0
    hit_ratio: float = 0.0
    l0_hits: int = 0
    l1_hits: int = 0
    l2_hits: int = 0
    task_hit_ratio: float = 0.0
    extras: Dict[str, Any] = Field(default_factory=dict)


class HolonRelation(BaseModel):
    """Normalized graph edge + neighbor summary (no raw Neo4j driver types)."""

    holon_id: str
    neighbor_id: str
    rel_type: str
    neighbor_type: Optional[str] = None
    neighbor_summary: Optional[str] = None
    props: Dict[str, Any] = Field(default_factory=dict)


class SemanticSearchQuery(BaseModel):
    """Vector search over semantic memory with scope hints."""

    embedding: List[float]
    scopes: List[str] = Field(default_factory=lambda: ["global"])
    organ_id: Optional[str] = None
    entity_ids: Optional[List[str]] = None
    limit: int = 10
    hydrate_neighbors: bool = False
    neighbor_limit: int = 0


class SemanticSearchResult(BaseModel):
    holon_id: str
    distance: Optional[float] = None
    summary: str = ""
    type: str = "fact"
    scope: str = "global"
    content: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0


class SemanticMemoryStats(BaseModel):
    health: MemoryHealth = Field(default_factory=MemoryHealth)
    total_holons: int = 0
    total_relationships: int = 0
    bytes_used: int = 0
    extras: Dict[str, Any] = Field(default_factory=dict)


class IncidentMemoryStats(BaseModel):
    health: MemoryHealth = Field(default_factory=MemoryHealth)
    incidents_recorded: int = 0
    extras: Dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class WorkingMemory(Protocol):
    """Short-lived cache and episodic fragments (evolution of MwManager)."""

    async def get(self, key: str, *, is_global: bool = False) -> Any: ...
    def put(self, key: str, value: Any, ttl_s: Optional[int] = None) -> None: ...
    def put_global_typed(
        self,
        kind: str,
        scope: str,
        item_id: str,
        value: Any,
        ttl_s: Optional[int] = None,
    ) -> None:
        """Write a typed global key (same contract as MwManager.set_global_item_typed)."""
        ...

    async def delete(self, key: str, *, is_global: bool = False) -> None: ...
    async def append_episode(
        self,
        *,
        agent_id: str,
        episode: Any,
        ttl_s: Optional[int] = None,
        max_items: Optional[int] = None,
    ) -> List[Dict[str, Any]]: ...
    async def get_recent_episode(
        self, *, organ_id: Optional[str], agent_id: str, k: int = 10
    ) -> List[Dict[str, Any]]: ...
    def set_negative_cache(
        self, kind: str, scope: str, item_id: str, ttl_s: int = 30
    ) -> None: ...
    async def check_negative_cache(
        self, kind: str, scope: str, item_id: str
    ) -> bool: ...
    async def try_set_inflight(self, key: str, ttl_s: int = 5) -> bool: ...
    async def clear_inflight(self, key: str) -> None: ...
    async def stats_snapshot(self) -> WorkingMemoryStats: ...


@runtime_checkable
class SemanticMemory(Protocol):
    """Scoped semantic retrieval and holon persistence (Holon-backed LTM)."""

    async def upsert_holon(self, holon: Any) -> None: ...
    async def get_holon(self, holon_id: str) -> Optional[Any]: ...
    async def search(self, query: SemanticSearchQuery) -> List[SemanticSearchResult]: ...
    async def list_relationships(
        self, holon_id: str, *, limit: int = 50
    ) -> List[HolonRelation]: ...
    async def delete_holon(self, holon_id: str) -> None: ...
    async def stats_snapshot(self) -> SemanticMemoryStats: ...


@runtime_checkable
class IncidentMemory(Protocol):
    """High-salience incidents (flashbulb evolution path)."""

    async def record_incident(
        self, event_data: Dict[str, Any], salience_score: float
    ) -> str: ...
    async def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]: ...
    async def list_incidents(self, *, limit: int = 50) -> List[Dict[str, Any]]: ...
    async def stats_snapshot(self) -> IncidentMemoryStats: ...
