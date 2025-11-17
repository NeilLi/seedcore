# agents/roles/skill_vector.py
"""
SkillVector: first-class representation of agent skills.

- Tracks per-agent skill "deltas" relative to RoleProfile.default_skills.
- Provides materialization (defaults + deltas) with clamping to [0, 1].
- Supports bumping, decay, merging, and JSON-safe serialization.
- Async persistence hooks with pluggable storage (e.g., LTM).
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any


class SkillStoreProtocol:
    """
    Minimal async persistence protocol for skill vectors.
    Implementations can wrap your LongTermMemoryManager or any KV store.
    """
    async def load(self, agent_id: str) -> Optional[Dict[str, float]]:
        raise NotImplementedError

    async def save(self, agent_id: str, deltas: Dict[str, float], metadata: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError


class NullSkillStore(SkillStoreProtocol):
    """No-op store (default)."""
    async def load(self, agent_id: str) -> Optional[Dict[str, float]]:
        return None

    async def save(self, agent_id: str, deltas: Dict[str, float], metadata: Optional[Dict[str, Any]] = None) -> None:
        return None


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class SkillVector:
    """
    SkillVector holds per-agent deltas and provides utilities to combine them
    with role defaults for cognition/ML calls.

    Attributes:
        deltas: per-skill additive adjustments relative to role defaults.
        last_updated: unix timestamp when deltas last changed (for audits).
    """
    deltas: Dict[str, float] = field(default_factory=dict)
    last_updated: float = field(default_factory=time.time)

    # runtime-only fields (not persisted)
    _store: SkillStoreProtocol = field(default_factory=NullSkillStore, repr=False, compare=False)
    _persist_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)
    _debounce_task: Optional[asyncio.Task] = field(default=None, repr=False, compare=False)

    # ---- Construction / Persistence -------------------------------------------------

    @classmethod
    async def from_store(cls, agent_id: str, store: SkillStoreProtocol) -> "SkillVector":
        """Load deltas from the given store; returns empty vector if none."""
        raw = await store.load(agent_id)
        vec = cls(deltas=dict(raw or {}))
        vec._store = store
        return vec

    def bind_store(self, store: SkillStoreProtocol) -> None:
        """Attach a persistence store to this instance."""
        self._store = store

    async def persist(self, agent_id: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Persist deltas immediately (no debounce)."""
        async with self._persist_lock:
            await self._store.save(agent_id, dict(self.deltas), metadata or {"last_updated": self.last_updated})

    def persist_debounced(self, agent_id: str, delay_s: float = 2.0, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Schedule a debounced persist to avoid spamming the store after rapid bumps.
        If a task is already pending, it will be cancelled and rescheduled.
        """
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()

        async def _runner():
            try:
                await asyncio.sleep(delay_s)
                await self.persist(agent_id, metadata)
            except asyncio.CancelledError:
                # silently ignore debounce cancellations
                return

        loop = asyncio.get_event_loop()
        self._debounce_task = loop.create_task(_runner())

    # ---- Core math -----------------------------------------------------------------

    def materialize(self, defaults: Dict[str, float]) -> Dict[str, float]:
        """
        Combine defaults and deltas, clamping into [0, 1].
        Unknown skills in deltas are added directly (clamped).
        
        NOTE: This method duplicates RoleProfile.materialize_skills() logic.
        Prefer using RoleProfile.materialize_skills(self.deltas) for consistency.
        This method is kept for cases where RoleProfile is not available.
        """
        out: Dict[str, float] = {}
        for k, base in defaults.items():
            val = float(base) + float(self.deltas.get(k, 0.0))
            out[k] = _clamp01(val)
        for k, d in self.deltas.items():
            if k not in out:
                out[k] = _clamp01(float(d))
        return out

    def bump(self, skill: str, delta: float, clamp_delta: bool = True) -> float:
        """
        Increment a skill delta. If clamp_delta, each bump is limited to [-1, 1] step.
        Returns the new delta for the skill.
        """
        step = float(delta)
        if clamp_delta:
            step = -1.0 if step < -1.0 else 1.0 if step > 1.0 else step
        new_val = float(self.deltas.get(skill, 0.0)) + step
        # Keep the *delta* within a reasonable range; underlying materialization still clamps to [0,1].
        new_val = -1.0 if new_val < -1.0 else 1.0 if new_val > 1.0 else new_val
        self.deltas[skill] = new_val
        self.last_updated = time.time()
        return new_val

    def set(self, skill: str, value: float) -> float:
        """
        Set an absolute delta for a skill (not the materialized value).
        Useful for admin tools or external training signals.
        """
        v = float(value)
        v = -1.0 if v < -1.0 else 1.0 if v > 1.0 else v
        self.deltas[skill] = v
        self.last_updated = time.time()
        return v

    def decay(self, rate: float = 0.01) -> None:
        """
        Apply exponential decay to all deltas toward zero. Small positive rate recommended.
        """
        r = max(0.0, min(1.0, float(rate)))
        if r == 0.0:
            return
        for k, v in list(self.deltas.items()):
            self.deltas[k] = float(v) * (1.0 - r)
            # Snap to zero if very close
            if abs(self.deltas[k]) < 1e-6:
                self.deltas[k] = 0.0
        self.last_updated = time.time()

    def merge(self, other: "SkillVector", weight_self: float = 0.5) -> None:
        """
        Merge another vector into this one (convex combination of deltas).
        """
        w = _clamp01(weight_self)
        for k in set(self.deltas) | set(other.deltas):
            a = float(self.deltas.get(k, 0.0))
            b = float(other.deltas.get(k, 0.0))
            self.deltas[k] = a * w + b * (1.0 - w)
        self.last_updated = time.time()

    # ---- Introspection / Serialization --------------------------------------------

    def to_dict(self) -> Dict[str, float]:
        """
        Return just the deltas dictionary (skill name -> delta value).
        This is the unified representation for AgentSnapshot.learned_skills.
        
        Returns:
            Dict[str, float]: Dictionary mapping skill names to their delta values.
        """
        return dict(self.deltas)

    @classmethod
    def from_dict(cls, payload: Dict[str, float]) -> "SkillVector":
        """
        Restore SkillVector from a dictionary.
        
        Expected format: {"skill_name": delta_value, ...} (direct deltas dict)
        Optional: {"skill_name": delta_value, ..., "last_updated": timestamp}
        """
        # Extract last_updated if present, otherwise use current time
        last_updated = float(payload.get("last_updated", time.time()))
        
        # The rest of the payload should be skill deltas (exclude last_updated)
        deltas = {k: float(v) for k, v in payload.items() if k != "last_updated"}
        
        return cls(deltas=deltas, last_updated=last_updated)

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, s: str) -> "SkillVector":
        return cls.from_dict(json.loads(s))

    # ---- Convenience ----------------------------------------------------------------

    def export_for_cog(self, defaults: Dict[str, float]) -> Dict[str, float]:
        """
        Convenience for cognition/ML payloads.
        
        NOTE: This uses SkillVector.materialize() which duplicates RoleProfile.materialize_skills().
        In most cases, you should use RoleProfile.materialize_skills(self.deltas) instead.
        This method is kept for cases where RoleProfile is not available.
        """
        return self.materialize(defaults)
