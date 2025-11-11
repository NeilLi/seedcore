# agents/roles/routing.py
"""
Routing & capability advertisement for the meta-controller.

This module provides:
- AgentAdvertisement: canonical capability snapshot for routing decisions
- Router: in-memory registry + scoring-based selection across agents

Scoring heuristics (simple, extensible):
- Role match: specialization and/or required tags
- Skill match: cosine-like overlap between requested skills and advertised skills
- Capacity: prefer lower mem_util (more headroom)
- Capability: prefer higher capability
- Health/latency: prefer healthy and low-latency agents

You can replace/extend the scoring strategy without changing agent code.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .specialization import Specialization, RoleProfile, RoleRegistry


# ---------- Advertisement ---------------------------------------------------------


@dataclass
class AgentAdvertisement:
    """
    Canonical snapshot for meta-controller routing.

    Required:
      - agent_id: unique logical agent identifier
      - specialization: Specialization enum
      - skills: materialized skills {name: 0..1}
      - capability: scalar capability (0..1)
      - mem_util: memory utilization (0..1), higher = more loaded

    Optional:
      - routing_tags: set of tags for task matching
      - capacity_hint: override for queue capacity (0..1 free headroom)
      - health: human-readable health state
      - latency_ms: moving average of response latency
      - quality_avg: rolling average quality (0..1)
      - region/zone: placement hints (strings)
    """
    agent_id: str
    specialization: Specialization
    skills: Dict[str, float]
    capability: float
    mem_util: float

    routing_tags: Set[str] = field(default_factory=set)
    capacity_hint: Optional[float] = None
    health: str = "healthy"
    latency_ms: Optional[float] = None
    quality_avg: Optional[float] = None
    region: Optional[str] = None
    zone: Optional[str] = None
    last_updated_ts: float = field(default_factory=time.time)

    def free_capacity(self) -> float:
        """
        A naive headroom metric. If capacity_hint is provided, prefer it.
        Otherwise interpret mem_util as usage and invert.
        """
        if self.capacity_hint is not None:
            return max(0.0, min(1.0, float(self.capacity_hint)))
        return max(0.0, min(1.0, 1.0 - float(self.mem_util)))


# ---------- Router ---------------------------------------------------------------


class Router:
    """
    In-memory router that selects best-matching agents for incoming tasks.

    Public methods:
      - register/refresh: add or update an advertisement
      - remove: delete an agent from consideration
      - select_best / select_topk: pick candidates based on request spec
    """

    def __init__(self, registry: RoleRegistry) -> None:
        self._registry = registry
        self._ads: Dict[str, AgentAdvertisement] = {}

        # Tunables for scoring—safe defaults. Adjust per deployment.
        self._w_role = 2.0        # weight for role/tag match
        self._w_skill = 1.5       # weight for skill similarity
        self._w_capacity = 1.2    # weight for free capacity
        self._w_capability = 1.0  # weight for base capability
        self._w_quality = 0.8     # weight for historical quality
        self._w_latency = 0.6     # weight for low latency

    # ---- Registry ops -----------------------------------------------------------

    def register(self, ad: AgentAdvertisement) -> None:
        self._ads[ad.agent_id] = ad

    def refresh(self, ad: AgentAdvertisement) -> None:
        self.register(ad)

    def remove(self, agent_id: str) -> None:
        self._ads.pop(agent_id, None)

    def all_ads(self) -> List[AgentAdvertisement]:
        return list(self._ads.values())

    # ---- Selection --------------------------------------------------------------

    def select_best(
        self,
        *,
        required_role: Optional[Specialization] = None,
        required_tags: Optional[Iterable[str]] = None,
        desired_skills: Optional[Dict[str, float]] = None,
        region: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> Optional[AgentAdvertisement]:
        res = self.select_topk(
            k=1,
            required_role=required_role,
            required_tags=required_tags,
            desired_skills=desired_skills,
            region=region,
            zone=zone,
        )
        return res[0] if res else None

    def select_topk(
        self,
        k: int,
        *,
        required_role: Optional[Specialization] = None,
        required_tags: Optional[Iterable[str]] = None,
        desired_skills: Optional[Dict[str, float]] = None,
        region: Optional[str] = None,
        zone: Optional[str] = None,
    ) -> List[AgentAdvertisement]:
        """
        Return top-k agents ranked by a composite score.
        """
        req_tags = set(required_tags or [])
        candidates = [ad for ad in self._ads.values() if self._eligible(ad, required_role, req_tags, region, zone)]
        if not candidates:
            return []

        desired_skills = desired_skills or {}

        ranked = sorted(
            candidates,
            key=lambda ad: self._score(ad, req_tags, desired_skills),
            reverse=True,
        )
        return ranked[: max(1, int(k))]

    # ---- Internals: eligibility & scoring --------------------------------------

    def _eligible(
        self,
        ad: AgentAdvertisement,
        required_role: Optional[Specialization],
        req_tags: Set[str],
        region: Optional[str],
        zone: Optional[str],
    ) -> bool:
        # Health gate
        if ad.health not in ("healthy", "degraded"):
            return False
        # Role gate
        if required_role and ad.specialization != required_role:
            return False
        # Tag gate
        if req_tags and not req_tags.issubset(ad.routing_tags):
            return False
        # Placement gates (optional)
        if region and ad.region and ad.region != region:
            return False
        if zone and ad.zone and ad.zone != zone:
            return False
        return True

    def _score(self, ad: AgentAdvertisement, req_tags: Set[str], desired_skills: Dict[str, float]) -> float:
        s = 0.0

        # Role/tag alignment (binary for tags; role is already gated in eligibility)
        if req_tags:
            tag_overlap = len(req_tags.intersection(ad.routing_tags)) / max(1, len(req_tags))
            s += self._w_role * tag_overlap
        else:
            # small bias for having any routing tags
            s += self._w_role * (0.1 if ad.routing_tags else 0.0)

        # Skill similarity (cosine-like on shared keys)
        s += self._w_skill * _skill_similarity(ad.skills, desired_skills)

        # Free capacity & capability
        s += self._w_capacity * ad.free_capacity()
        s += self._w_capability * _clamp01(ad.capability)

        # Historical quality (optional)
        if ad.quality_avg is not None:
            s += self._w_quality * _clamp01(ad.quality_avg)

        # Latency penalty (prefer lower latency)
        if ad.latency_ms is not None and ad.latency_ms > 0:
            # Map latency to 0..1 score: 0 at 2s+, ~1 near 0ms.
            lat_score = max(0.0, min(1.0, 1.0 - (ad.latency_ms / 2000.0)))
            s += self._w_latency * lat_score

        return s


# ---------- Helpers --------------------------------------------------------------


def build_advertisement(
    *,
    agent_id: str,
    role_profile: RoleProfile,
    specialization: Specialization,
    materialized_skills: Dict[str, float],
    capability: float,
    mem_util: float,
    routing_tags: Optional[Iterable[str]] = None,
    capacity_hint: Optional[float] = None,
    health: str = "healthy",
    latency_ms: Optional[float] = None,
    quality_avg: Optional[float] = None,
    region: Optional[str] = None,
    zone: Optional[str] = None,
) -> AgentAdvertisement:
    """
    Convenience builder that pulls routing tags from the RoleProfile if not provided.
    """
    tags = set(routing_tags) if routing_tags is not None else set(role_profile.routing_tags or set())
    return AgentAdvertisement(
        agent_id=agent_id,
        specialization=specialization,
        skills=dict(materialized_skills),
        capability=float(capability),
        mem_util=float(mem_util),
        routing_tags=tags,
        capacity_hint=capacity_hint,
        health=health,
        latency_ms=latency_ms,
        quality_avg=quality_avg,
        region=region,
        zone=zone,
    )


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _skill_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """
    Cosine-like similarity over shared skill keys. Returns 0..1.
    """
    if not a or not b:
        return 0.0
    keys = set(a.keys()) | set(b.keys())
    # simple dot / (norms + epsilon)
    dot = sum(float(a.get(k, 0.0)) * float(b.get(k, 0.0)) for k in keys)
    na = math.sqrt(sum(float(a.get(k, 0.0)) ** 2 for k in keys))
    nb = math.sqrt(sum(float(b.get(k, 0.0)) ** 2 for k in keys))
    if na == 0.0 or nb == 0.0:
        return 0.0
    sim = dot / (na * nb)
    # clamp defensive
    return max(0.0, min(1.0, float(sim)))
