# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Router module for task routing and directory management.

This module provides routing structures and directory for mapping task types
to logical IDs with runtime registry integration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
import time
import uuid
from functools import lru_cache
from typing import Dict, Any, Optional, NamedTuple, Tuple, List, TYPE_CHECKING

from numpy import random

import ray  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models import TaskPayload

# Target namespace for Ray actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

if TYPE_CHECKING:
    from .organ import AgentIDFactory
    from seedcore.agents.roles import RoleRegistry, SkillStoreProtocol
    from seedcore.serve.cognitive_client import CognitiveServiceClient

logger = ensure_serve_logger("seedcore.router")


@dataclass
class RouterDecision:
    """Router decision result containing agent and organ selection."""

    agent_id: str
    organ_id: str
    reason: str
    is_high_stakes: bool = False


# Routing structures
class RouteEntry(NamedTuple):
    """Entry in the routing directory."""

    logical_id: str
    epoch: str
    resolved_from: str
    instance_id: Optional[str] = None
    cached_at: float = 0.0


class RouteCache:
    """Thread-safe route cache with TTL and jitter."""

    def __init__(self, ttl_s: float = 3.0, jitter_s: float = 0.5):
        self.ttl_s = ttl_s
        self.jitter_s = jitter_s
        self._cache: Dict[Tuple[str, Optional[str]], Tuple[RouteEntry, float]] = {}
        self._lock = asyncio.Lock()
        self._inflight: Dict[Tuple[str, Optional[str]], asyncio.Future] = {}

    def _expired(self, expires_at: float) -> bool:
        return time.monotonic() > expires_at

    def _expires_at(self) -> float:
        return time.monotonic() + self.ttl_s + random.uniform(0, self.jitter_s)

    def get(self, key: Tuple[str, Optional[str]]) -> Optional[RouteEntry]:
        """Get cached route entry if not expired."""
        v = self._cache.get(key)
        if not v:
            return None
        entry, expires_at = v
        if self._expired(expires_at):
            self._cache.pop(key, None)
            return None
        return entry

    def set(self, key: Tuple[str, Optional[str]], entry: RouteEntry) -> None:
        """Set cached route entry with TTL."""
        self._cache[key] = (entry, self._expires_at())

    async def singleflight(self, key: Tuple[str, Optional[str]]):
        """Ensure only one resolve for a given key at a time (prevents dogpiles).

        Yields a tuple (future, is_leader). Exactly one caller per key will
        have is_leader=True and is responsible for computing the result and
        completing the future. All others should await the future result.
        """
        async with self._lock:
            fut = self._inflight.get(key)
            is_leader = False
            if fut is None:
                fut = asyncio.get_event_loop().create_future()
                self._inflight[key] = fut
                is_leader = True
        try:
            yield fut, is_leader
        finally:
            # Only the leader clears the inflight map entry after completion
            if is_leader:
                async with self._lock:
                    self._inflight.pop(key, None)

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics for observability."""
        now = time.monotonic()
        active_entries = 0
        expired_entries = 0

        for entry, expires_at in self._cache.values():
            if now > expires_at:
                expired_entries += 1
            else:
                active_entries += 1

        return {
            "active_entries": active_entries,
            "expired_entries": expired_entries,
            "total_entries": len(self._cache),
            "inflight_requests": len(self._inflight),
            "ttl_s": self.ttl_s,
            "jitter_s": self.jitter_s,
        }


class RoutingDirectory:
    """
    Hybrid organism Routing Layer with runtime registry integration.

    Enhanced capabilities:
    - Maps task_type[/domain] -> logical_id with active instance validation
    - Multi-domain fallback strategy
    - Real-time metrics for load-aware routing
    - Ultra-fast LRU cache for high-throughput routing
    - AgentIDFactory integration for globally unique agent addressing
    """

    def __init__(
        self,
        agent_id_factory: Optional["AgentIDFactory"] = None,
        organism: Optional[Any] = None,
        cognitive_client: Optional["CognitiveServiceClient"] = None,
        role_registry: Optional["RoleRegistry"] = None,
        skill_store: Optional["SkillStoreProtocol"] = None,
        config: Optional[Dict[str, Any]] = None,
        redis_client: Optional[Any] = None,
        organ_specs: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize RoutingDirectory with optional OrganismCore dependencies.

        Args:
            agent_id_factory: Optional AgentIDFactory for generating agent IDs
            organism: Optional OrganismCore instance (for accessing organs/agents)
            cognitive_client: Optional CognitiveServiceClient (for cognitive routing)
            role_registry: Optional RoleRegistry (for specialization routing)
            skill_store: Optional SkillStoreProtocol (for skill-based routing)
            config: Optional config dict for scoring weights and routing behavior
            redis_client: Optional Redis client for sticky session storage (agent affinity)
        """
        # Scoring configuration (tunable weights)
        self.config = {
            "load_weight": 1000,
            "availability_weight": 100,
            "penalty_weight": 1000,
            "deadline_boost": 50,
            "priority_boost": 20,
            **(config or {}),
        }

        # Static routing rules
        self.rules_by_task: Dict[str, str] = {}
        self.rules_by_domain: Dict[Tuple[str, str], str] = {}

        # Candidate groups for task-type-based selection (task_type -> list of logical_ids)
        self.logical_groups: Dict[str, List[str]] = {}

        # Real-time agent metrics (load, latency, availability)
        self.agent_metrics: Dict[str, Dict[str, Any]] = {}

        # AgentIDFactory for globally unique agent addressing
        self.agent_id_factory = agent_id_factory

        # OrganismCore integration
        self.organism = organism
        self.cognitive_client = cognitive_client
        self.role_registry = role_registry
        self.skill_store = skill_store

        # Specialization → organ mapping (string-based, populated by OrganismCore)
        # Maps specialization name (string) to organ_id for _find_organ_by_spec()
        self.organ_specs = organ_specs

        # Redis client for sticky session storage (agent affinity)
        self.redis = redis_client

        # Runtime cache for active Ray actor handles (short TTL)
        # Stores: logical_id -> (ActorHandle, cached_timestamp)
        self._instance_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 3.0  # seconds
        self._lock = asyncio.Lock()

        # Rate-limited logging for cache misses (prevent log spam)
        self._last_cache_miss_log: Dict[str, float] = {}
        self._cache_miss_log_interval = (
            5.0  # seconds between log messages per logical_id
        )

        # Instantiate the cache locally
        # 3.0s TTL is a safe baseline for stable routing policies
        self.route_cache = RouteCache(ttl_s=3.0, jitter_s=0.5)

    @staticmethod
    def _normalize(x: Optional[str]) -> Optional[str]:
        """Normalize string for consistent matching."""
        return str(x).strip().lower() if x is not None else None

    # --- (A) AgentIDFactory Integration ---

    def new_agent_id(self, logical_id: str, spec: Optional[Any] = None) -> str:
        """
        Generate a new agent ID using AgentIDFactory if available.

        Args:
            logical_id: Logical ID of the organ/agent
            spec: Optional specialization (for AgentIDFactory.new())

        Returns:
            Globally unique agent ID
        """
        if self.agent_id_factory and spec:
            # AgentIDFactory expects (organ_id, spec)
            return self.agent_id_factory.new(logical_id, spec)
        # Fallback to simple UUID-based ID
        return f"{logical_id}-{uuid.uuid4().hex[:8]}"

    # --- (E) Real-Time Metrics ---

    def update_agent_metrics(self, logical_id: str, metrics: Dict[str, Any]):
        """
        Update real-time metrics for an agent.

        Expected metrics:
            - load: float (0.0-1.0, current utilization)
            - latency_ms: float (average response latency)
            - availability: float (0.0-1.0, uptime/health score)
            - capacity: int (max concurrent tasks)
            - active_tasks: int (current active tasks)
        """
        self.agent_metrics[logical_id] = {
            **self.agent_metrics.get(logical_id, {}),
            **metrics,
            "updated_at": time.time(),
        }

    def get_agent_metrics(self, logical_id: str) -> Optional[Dict[str, Any]]:
        """Get current metrics for an agent."""
        return self.agent_metrics.get(logical_id)

    # --- (F) Ultra-Fast LRU Cache ---

    @lru_cache(maxsize=512)
    def _cached_route_key(
        self, tt: Optional[str], dm: Optional[str]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        LRU-cached route key normalization for ultra-fast routing.

        NOTE: This caches only the normalized (task_type, domain) tuple.
        It does NOT cache resolution decisions, which depend on:
        - Real-time agent metrics
        - Active instance validation

        Do NOT expand caching to resolve() output without proper TTL invalidation.
        """
        return (tt, dm)

    def set_rule(self, task_type: str, logical_id: str, domain: Optional[str] = None):
        """
        Set a static routing rule (Configuration Phase).

        Used by Stage 3 (Domain) and Stage 5 (Task-Type) of the resolver.
        Note: logical_id must be a local Organ ID, not an upstream Dispatcher.
        """
        tt = self._normalize(task_type)
        dm = self._normalize(domain)

        if tt is None:
            return

        # V2 Safety Check: Prevent routing loops
        if "dispatcher" in logical_id and "organ" not in logical_id:
            logger.warning(
                f"[Router] set_rule ignored: '{logical_id}' appears to be a dispatcher. "
                "OrganismRouter should only route to local Organs."
            )
            return

        if dm:
            # Stage 3: Domain specific rule
            self.rules_by_domain[(tt, dm)] = logical_id
            logger.info(f"[Router] Rule set: {tt} + {dm} -> {logical_id}")
        else:
            # Stage 5: General Task-Type fallback
            self.rules_by_task[tt] = logical_id
            logger.info(f"[Router] Rule set: {tt} -> {logical_id}")

    def remove_rule(self, task_type: str, domain: Optional[str] = None):
        """Remove a static routing rule."""
        tt = self._normalize(task_type)
        dm = self._normalize(domain)

        if tt is None:
            return

        if dm:
            if (tt, dm) in self.rules_by_domain:
                del self.rules_by_domain[(tt, dm)]
                logger.info(f"[Router] Rule removed: {tt} + {dm}")
        else:
            if tt in self.rules_by_task:
                del self.rules_by_task[tt]
                logger.info(f"[Router] Rule removed: {tt}")

    def get_rules(self) -> Dict[str, Any]:
        """
        Get current routing table snapshot for telemetry.
        """
        return {
            "rules_by_task": self.rules_by_task.copy(),
            # Convert tuple keys to string for JSON serialization
            "rules_by_domain": {
                f"{k[0]}|{k[1]}": v for k, v in self.rules_by_domain.items()
            },
        }

    def _rate_limited_log(self, key: str, msg: str):
        """Rate-limited logging helper to prevent log spam."""
        now = time.time()
        last = self._last_cache_miss_log.get(key, 0)
        if now - last >= self._cache_miss_log_interval:
            logger.warning(msg)
            self._last_cache_miss_log[key] = now

    async def _get_active_instance(self, logical_id: str) -> Optional[Dict[str, Any]]:
        """
        Ray-native instance resolver with:
            - TTL-based handle caching
            - Single-flight protection
            - Actor liveness validation via .ping()
            - Dead-instance eviction
            - Lazy refresh strategy
        """
        now = time.time()
        cache_key = logical_id

        # -------------------------------
        # 1. Fast-path cache lookup
        # -------------------------------
        entry = self._instance_cache.get(cache_key)
        if entry:
            handle, cached_at = entry
            cache_age = now - cached_at

            if cache_age < self._cache_ttl:
                # -------------------------------
                # 1A. Validate Ray actor is alive
                # -------------------------------
                try:
                    await asyncio.to_thread(
                        lambda: ray.get(handle.ping.remote(), timeout=1.0)
                    )
                    return {
                        "logical_id": logical_id,
                        "handle": handle,
                        "cache_hit": True,
                        "cache_age_ms": cache_age * 1000,
                        "status": "alive",
                    }
                except Exception:
                    # Dead actor → evict and fall through to refresh
                    self._instance_cache.pop(cache_key, None)

        # -------------------------------
        # 2. Single-flight slow path
        # -------------------------------
        async with self._lock:
            # Double-check after acquiring lock
            entry = self._instance_cache.get(cache_key)
            if entry:
                handle, cached_at = entry
                cache_age = now - cached_at

                if cache_age < self._cache_ttl:
                    try:
                        await asyncio.to_thread(
                            lambda: ray.get(handle.ping.remote(), timeout=1.0)
                        )
                        return {
                            "logical_id": logical_id,
                            "handle": handle,
                            "cache_hit": True,
                            "cache_age_ms": cache_age * 1000,
                            "status": "alive",
                        }
                    except Exception:
                        self._instance_cache.pop(cache_key, None)

            # -------------------------------
            # 3. Resolve new Ray actor handle
            # -------------------------------
            try:
                # Use Ray's built-in actor lookup by name (with namespace)
                handle = ray.get_actor(logical_id, namespace=AGENT_NAMESPACE)

                # Validate actor responds
                await asyncio.to_thread(
                    lambda: ray.get(handle.ping.remote(), timeout=1.0)
                )

                # Cache it
                self._instance_cache[cache_key] = (handle, now)

                return {
                    "logical_id": logical_id,
                    "handle": handle,
                    "cache_hit": False,
                    "cache_age_ms": 0.0,
                    "status": "alive",
                }

            except Exception as e:
                self._rate_limited_log(
                    logical_id, f"Failed resolving Ray actor '{logical_id}': {e}"
                )
                return None

    # --- TaskPayload Decomposition ---
    def extract_router_inputs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decompose canonical router envelope from TaskPayload v2 (params.routing + params.risk).

        Extracts:
            - required_specialization (Hard Constraint)
            - specialization (Soft Hint)
            - skills (was skills)
            - tools (was tool_calls)
            - hints (priority, deadlines, ttl)
            - risk.is_high_stakes

        Args:
            params: TaskPayload.params dictionary

        Returns:
            Dictionary of extracted routing inputs for use in resolve()
        """
        routing = (params or {}).get("routing", {})
        risk = (params or {}).get("risk", {})

        # 1. Spec & Skills (V2 Naming)
        required_specialization = routing.get("required_specialization")
        specialization = routing.get("specialization")  # Soft hint added in V2

        # Support V2 'skills' with fallback to legacy 'skills'
        skills = routing.get("skills") or routing.get("skills") or {}

        # 2. Tools (V2 Naming)
        # Support V2 'tools' with fallback to legacy 'tool_calls'
        tools_list = routing.get("tools") or routing.get("tool_calls") or []

        inferred_endpoint = None
        inferred_capability = None

        for tc in tools_list:
            # Handle both dict and ToolCallPayload objects
            if isinstance(tc, dict):
                name = tc.get("name", "")
            else:
                name = getattr(tc, "name", "")

            if name.startswith("iot."):
                inferred_capability = inferred_capability or "iot_bridge"
            if name.startswith("robot."):
                inferred_capability = inferred_capability or "robotics"
            if name.startswith("human."):
                inferred_capability = inferred_capability or "human_interface"

            # Explicit endpoint mapping pattern:
            if ":" in name:
                parts = name.split(":", 1)
                if len(parts) == 2:
                    namespace, endpoint = parts
                    if namespace in ("iot", "robot", "human"):
                        inferred_endpoint = f"{namespace}:{endpoint}"

        # 3. Hints (Added ttl_seconds)
        hints = routing.get("hints", {})
        priority = hints.get("priority")
        deadline_at = hints.get("deadline_at")
        ttl_seconds = hints.get("ttl_seconds")  # Added in V2
        min_capability = hints.get("min_capability")
        max_mem_util = hints.get("max_mem_util")

        # 4. Risk (Cross-Envelope)
        is_high_stakes = risk.get("is_high_stakes", False)

        return {
            "required_specialization": required_specialization,
            "specialization": specialization,
            "skills": skills,  # Renamed from skills
            "tools": tools_list,  # Renamed from tool_calls
            "priority": priority,
            "deadline_at": deadline_at,
            "ttl_seconds": ttl_seconds,
            "min_capability": min_capability,
            "max_mem_util": max_mem_util,
            "inferred_endpoint": inferred_endpoint,
            "capability": inferred_capability,
            "is_high_stakes": is_high_stakes,
        }

    # --- Enhanced Candidate Selection ---

    def _score_candidate(
        self, metrics: Dict[str, Any], routing_hints: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Score a candidate based on metrics and routing hints.

        Lower score is better. Scoring factors:
        - Load (lower is better)
        - Latency (lower is better)
        - Availability (higher is better, subtracted from score)
        - Deadline boost (reduces score for deadline-sensitive tasks)
        - Priority boost (reduces score for high-priority tasks on low-load agents)
        - Capability penalty (increases score if below minimum)
        - Memory penalty (increases score if above maximum)

        Args:
            metrics: Agent metrics dict (load, latency_ms, availability, etc.)
            routing_hints: Optional routing hints (deadline_at, priority, min_capability, max_mem_util)

        Returns:
            Score (lower is better)
        """
        load = metrics.get("load", 0.0)
        latency_ms = metrics.get("latency_ms", 999.0)
        availability = max(0.0, min(1.0, metrics.get("availability", 1.0)))

        # ----- Configurable weights -----
        LOAD_WEIGHT = self.config.get("load_weight", 1000)
        AVAIL_WEIGHT = self.config.get("availability_weight", 100)
        PENALTY = self.config.get("penalty_weight", 1000)
        DEADLINE_BOOST = self.config.get("deadline_boost", 50)
        PRIORITY_BOOST = self.config.get("priority_boost", 20)

        # Base score
        score = load * LOAD_WEIGHT + latency_ms - (availability * AVAIL_WEIGHT)

        # Routing hints
        if routing_hints:
            if routing_hints.get("deadline_at"):
                score -= DEADLINE_BOOST

            if routing_hints.get("priority") and load < 0.4:
                score -= PRIORITY_BOOST

            min_capability = routing_hints.get("min_capability")
            if min_capability is not None:
                if metrics.get("capability_score", 0.0) < min_capability:
                    score += PENALTY

            max_mem_util = routing_hints.get("max_mem_util")
            if max_mem_util is not None:
                if metrics.get("mem_util", 0.0) > max_mem_util:
                    score += PENALTY

        return score

    async def _pick_best_candidate(
        self, candidates: List[str], routing_hints: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Pick the best candidate from a list based on metrics and availability.

        Selection criteria (in order):
        1. Availability (must be alive)
        2. Load (prefer lower load)
        3. Latency (prefer lower latency)
        """
        if not candidates:
            return None

        enriched = []
        for lid in candidates:
            # Check if instance is alive
            inst = await self._get_active_instance(lid)
            if not inst:
                continue

            # Get metrics
            metrics = self.agent_metrics.get(lid, {})
            load = metrics.get("load", 0.0)
            latency_ms = metrics.get("latency_ms", 999.0)
            # Clamp availability to [0, 1] to prevent scoring bias
            availability = max(0.0, min(1.0, metrics.get("availability", 1.0)))

            # Score candidate using helper method
            score = self._score_candidate(metrics, routing_hints)

            enriched.append((lid, score, load, latency_ms, availability))

        if not enriched:
            return None

        # Sort by score (best first)
        enriched.sort(key=lambda x: x[1])
        best_lid = enriched[0][0]

        logger.debug(
            f"[Router] Best candidate = {best_lid} "
            f"(load={enriched[0][2]:.2f}, latency={enriched[0][3]:.1f}ms, "
            f"availability={enriched[0][4]:.2f})"
        )
        return best_lid

    # --- Sticky Session Helpers ---

    async def _lookup_sticky_agent(self, conversation_id: str) -> Optional[str]:
        """
        Check if a conversation is already bound to a specific agent.

        Args:
            conversation_id: The conversation identifier

        Returns:
            Agent ID if found, None otherwise
        """
        if not self.redis:
            return None

        key = f"sticky:conv:{conversation_id}"
        try:
            # Handle both async and sync Redis clients
            if hasattr(self.redis, "get"):
                # Check if it's an async client (aioredis)
                if asyncio.iscoroutinefunction(self.redis.get):
                    agent_id = await self.redis.get(key)
                else:
                    # Sync Redis client
                    agent_id = self.redis.get(key)

                if agent_id:
                    # Decode bytes if necessary
                    if isinstance(agent_id, bytes):
                        agent_id = agent_id.decode("utf-8")
                    elif isinstance(agent_id, str):
                        pass  # Already a string
                    return str(agent_id)
        except Exception as e:
            logger.warning(f"[Router] Sticky lookup failed for {conversation_id}: {e}")

        return None

    async def _bind_sticky_agent(
        self, conversation_id: str, agent_id: str, ttl: int = 3600
    ):
        """
        Bind a conversation to an agent for a set duration (default 1 hour).

        This enables "sticky routing" - subsequent messages in the same conversation
        will be routed to the same agent, preserving context locality and KV cache.

        Args:
            conversation_id: The conversation identifier
            agent_id: The agent ID to bind to
            ttl: Time-to-live in seconds (default 3600 = 1 hour)
        """
        if not self.redis:
            return

        key = f"sticky:conv:{conversation_id}"
        try:
            # Handle both async and sync Redis clients
            if hasattr(self.redis, "set"):
                # Check if it's an async client (aioredis)
                if asyncio.iscoroutinefunction(self.redis.set):
                    await self.redis.set(key, agent_id, ex=ttl)
                else:
                    # Sync Redis client
                    self.redis.set(key, agent_id, ex=ttl)
                logger.debug(
                    "[Router] Bound conversation %s to agent %s (TTL=%ds)",
                    conversation_id,
                    agent_id,
                    ttl,
                )
        except Exception as e:
            logger.warning(
                f"[Router] Sticky bind failed for {conversation_id} -> {agent_id}: {e}"
            )

    async def resolve(
        self,
        task_type: str,
        domain: Optional[str] = None,
        preferred_logical_id: Optional[str] = None,
        input_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], str]:
        """
        SeedCore v2 Organism Router (Specialization & V2 Compliant).

        Priority Order:
        0. High-stakes override
        1. Preferred logical_id (Explicit Hint)
        2. Required Specialization (HARD V2 Constraint)
        3. Domain-specific rule (Config Map)
        4. Specialization Hint (SOFT V2 Hint)
        5. Task-type rule (Config Map)
        6. Candidate group + Skill-based scoring (Load Balancing)
        7. Fallback (Meta-Control)
        """

        # Normalize routing keys
        tt = self._normalize(task_type)
        dm = self._normalize(domain)

        # ----------------------------------------
        # 1. Define Cache Key (Based on minimum inputs needed for lookup)
        # ----------------------------------------
        cache_key = (
            input_meta.get("required_specialization"),
            input_meta.get("specialization"),
            tt,
            dm,  # Include domain for domain-specific rules
        )

        # 2. Check Cache (FAST PATH - Cache Hit)
        cached_entry = self.route_cache.get(cache_key)
        if cached_entry:
            return cached_entry.organ_id, "cache_hit"  # Returns instantly

        # 3. Cache Miss: Run complex logic using singleflight lock
        async with self.route_cache.singleflight(cache_key) as (fut, is_leader):
            if is_leader:
                # 4. LEADER: Perform the expensive lookup (Stages 0 - 6)
                final_organ_id, final_reason = await self._run_full_resolve_logic(
                    tt, dm, preferred_logical_id, input_meta
                )

                # 5. Store Result and Complete Future
                if final_organ_id:
                    entry = RouteEntry(organ_id=final_organ_id, reason=final_reason)
                    self.route_cache.set(cache_key, entry)
                    fut.set_result(entry)
                    return final_organ_id, final_reason
                else:
                    # Handle failure/fallback before caching
                    fallback_id = getattr(self, "default_organ_id", "utility_organ")
                    entry = RouteEntry(organ_id=fallback_id, reason="fallback")
                    self.route_cache.set(cache_key, entry)
                    fut.set_result(entry)
                    return fallback_id, "fallback"

            else:
                # 6. FOLLOWER: Await the leader's result
                entry = await fut
                return entry.organ_id, "cache_wait"

    # --- Full Resolve Logic Helper ---
    async def _run_full_resolve_logic(
        self,
        tt: str,
        dm: Optional[str],
        preferred_id: Optional[str],
        input_meta: Dict[str, Any],
    ) -> Tuple[Optional[str], str]:
        """
        Executes the comprehensive, multi-stage routing lookup when the cache misses.
        This function contains the core business logic of the Organism Router.
        """

        # --- Stage 0 — High-Stakes Override ---
        # Logic: If high-stakes, force to a safe/audit organ (if configured).
        if input_meta.get("is_high_stakes"):
            override_id = self.rules_by_task.get("high_stakes_organ")
            # We assume the destination is valid and let downstream handle failure.
            if override_id:
                return override_id, "high-stakes"

        # --- Stage 1 — Preferred Organ (Explicit Hint) ---
        # Logic: Coordinator or Caller explicitly asked for this Organ ID.
        if preferred_id:
            # Simple existence check (optional, but good for safety)
            if preferred_id in self.organ_handles:
                return preferred_id, "preferred"

        # --- Stage 2 — Required Specialization (HARD V2 Constraint) ---
        # Logic: TaskPayload said "Must be done by X agent."
        required_spec = input_meta.get("required_specialization")
        if required_spec:
            # Use the direct specialization map (organ_specs)
            lid = self._find_organ_by_spec(required_spec.lower())
            if lid:
                return lid, "required-specialization"
            else:
                # Note: We warn and fall through, allowing softer rules to match.
                logger.warning(
                    f"[Router] Required spec '{required_spec}' not found in any local organ."
                )

        # --- Stage 3 — Domain Rule (task_type + domain) ---
        # Logic: "All hospitality.guest tasks go to GuestCareOrgan" (Highly specific config).
        if dm:
            lid = self.rules_by_domain.get((tt, dm))
            if lid:
                return lid, "domain"

        # --- Stage 4 — Specialization Hint (SOFT V2 Hint) ---
        # Logic: "Preferably done by Generalist, but okay if not."
        soft_spec = input_meta.get("specialization")
        if soft_spec:
            lid = self._find_organ_by_spec(soft_spec.lower())
            if lid:
                return lid, "specialization-hint"

        # --- Stage 5 — Task-Type Rule (Config Map) ---
        # Logic: "All 'graph' tasks go to MemoryOrgan" (General config default).
        lid = self.rules_by_task.get(tt)
        if lid:
            return lid, "task-type-rule"

        # --- Stage 6 — Candidate Group Selection (Load Balancing) ---
        # Logic: Pick the least loaded/best-skilled organ from a pool of candidates (e.g., all QUERY handlers).
        candidates = self.logical_groups.get(tt, [])
        if candidates:
            selected = await self._pick_best_candidate(
                candidates,
                routing_hints=input_meta,
            )
            if selected:
                return selected, "candidate-selection"

        # --- Stage 7 — Hard Fallback ---
        # Default to the primary utility/system services organ.
        fallback_id = getattr(self, "default_organ_id", "utility_organ")
        return fallback_id, "fallback"

    # --- Route Only Helper ---
    async def route_only(
        self,
        payload: Any,  # TaskPayload or dict
    ) -> RouterDecision:
        """
        Pure routing logic compatible with TaskPayload v2.
        Handles 'coordinator_routed' by trusting upstream hints.
        """
        # 1. Standardization (Handle Pydantic or Dict)
        if hasattr(payload, "model_dump"):
            task_dict = payload.model_dump()
            # If payload is Pydantic, we need a mutable ref to params to update the object later
            # However, model_dump creates a copy. We will rely on returning RouterDecision
            # and letting the caller update the payload object if needed,
            # BUT we also patch the dict for the local scope.
        else:
            task_dict = payload

        params = task_dict.get("params", {})

        # 2. Extract Envelopes (V2)
        interaction = params.get("interaction", {})
        routing_in = params.get("routing", {})  # Read-Only Inbox

        # 3. Determine Interaction Mode
        mode = interaction.get(
            "mode", "coordinator_routed"
        )  # Default to coordinated if missing
        assigned_agent = interaction.get("assigned_agent_id")
        conv_id = interaction.get("conversation_id")

        organ_id = None
        resolved_from = "unknown"
        agent_id = None

        # =========================================================
        # PHASE 1: ORGAN SELECTION (Physical/Logical Organ)
        # =========================================================

        # CASE A: Explicit Agent Assignment (Tunnel Mode)
        # Router is effectively bypassed, just validate validity
        if assigned_agent and mode == "agent_tunnel":
            agent_id = assigned_agent
            # We assume the agent implies the organ (or we look it up)
            # For now, we might leave organ_id None or look it up if you have a map
            resolved_from = "tunnel_assignment"

        # CASE B: Coordinator Already Routed (Trust Upstream)
        elif mode == "coordinator_routed":
            # The Coordinator sent this here. We look for specialization hints to pick
            # the specific internal organ (if this Organism has multiple).
            req_spec = routing_in.get("required_specialization")
            pref_spec = routing_in.get("specialization")

            target_spec = req_spec or pref_spec

            if target_spec:
                # Simple lookup: Which of my organs handles this specialization?
                # Assuming self.spec_to_organ_map exists, or we iterate organs
                organ_id = self._find_organ_by_spec(target_spec)
                resolved_from = "coordinator_hint"

                if not organ_id:
                    logger.warning(
                        f"Coordinator requested spec '{target_spec}' but no local organ matches. Fallback to default."
                    )

            if not organ_id:
                # Fallback: Use default organ for this node
                organ_id = getattr(self, "default_organ_id", "utility_organ")
                resolved_from = "coordinator_fallback"

        # CASE C: Fresh Routing (e.g. IoT Event or Direct Ingress)
        else:
            # Extract routing inputs
            routing_inputs = self.extract_router_inputs(params)

            # Full semantic resolution
            task_type = task_dict.get("type") or "unknown_task"
            domain = task_dict.get("domain")

            organ_id, resolved_from = await self.resolve(
                task_type=task_type,
                domain=domain,
                input_meta=routing_inputs,  # utilizing your existing helper
            )

        # Safety Fallback
        if not organ_id:
            organ_id = "utility_organ"

        # =========================================================
        # PHASE 2: AGENT SELECTION
        # =========================================================

        # Priority 1: Check Sticky Session (Tunnel Mode Only)
        if not agent_id and mode == "agent_tunnel" and conv_id:
            sticky_agent = await self._lookup_sticky_agent(conv_id)
            if sticky_agent:
                agent_id = sticky_agent
                resolved_from = "sticky_session"

        # Priority 2: Dynamic Selection via Organ Handle
        # Priority 2: Dynamic Selection via Organ Handle
        if not agent_id:
            # 1. Lookup the Organ Actor Handle (Cached locally)
            organ_handle = self.organ_handles.get(organ_id)

            if organ_handle:
                try:
                    # 2. Extract V2 signals
                    skills = routing_in.get("skills", {})
                    # Prefer hard constraint, fallback to soft hint
                    target_spec = routing_in.get(
                        "required_specialization"
                    ) or routing_in.get("specialization")

                    # 3. Dispatch to Organ Actor
                    # Note: We assume organ_handle is a valid Ray ActorHandle
                    if target_spec:
                        # Pick by Spec (and optionally sort by skills)
                        ref = organ_handle.pick_agent_by_specialization.remote(
                            target_spec, skills
                        )
                    elif skills:
                        # Pick by Skills only
                        ref = organ_handle.pick_agent_by_skills.remote(skills)
                    else:
                        # Random / Load Balanced
                        ref = organ_handle.pick_random_agent.remote()

                    # 4. Await result via thread to prevent blocking the async loop
                    # ray.get is blocking, so we offload it
                    result = await asyncio.to_thread(ray.get, ref)

                    # 5. Handle potential tuple return (agent_id, score) vs string
                    if isinstance(result, (tuple, list)):
                        agent_id = result[0]
                    else:
                        agent_id = result

                except Exception as e:
                    # Catch RayActorError, Timeout, or logic errors
                    logger.warning(
                        f"[Router] Agent selection via Ray failed for {organ_id}: {e}"
                    )
            else:
                # If we don't have the handle, we can't route dynamically
                # (Logic will fall through to Priority 3: Factory Generation)
                logger.debug(
                    f"[Router] No handle found for organ {organ_id}, falling back to generation."
                )

            # Priority 3: Factory Generation (Fallback)
            if not agent_id:
                agent_id = self.new_agent_id(organ_id)

        # =========================================================
        # PHASE 3: STATE & METADATA WRITES
        # =========================================================

        # 1. Bind Sticky Session (Fire & Forget)
        if conv_id and agent_id and mode == "agent_tunnel":
            asyncio.create_task(self._bind_sticky_agent(conv_id, agent_id, ttl=3600))

        # 2. Populate Router Output (params._router) - WRITE ONLY
        is_high_stakes = routing_in.get("is_high_stakes", False)  # or from risk

        router_out = {
            "is_high_stakes": is_high_stakes,
            "agent_id": agent_id,
            "organ_id": organ_id,
            "reason": resolved_from,
            "routed_at": "now",  # You can add timestamp
        }

        # 3. Inject into the dict (for immediate execution usage)
        params["_router"] = router_out

        # If the payload object is mutable (passed by ref), update it too
        if hasattr(payload, "params") and isinstance(payload.params, dict):
            payload.params["_router"] = router_out

        return RouterDecision(
            agent_id=agent_id,
            organ_id=organ_id,
            reason=resolved_from,
            is_high_stakes=is_high_stakes,
        )

    def _find_organ_by_spec(self, spec: str) -> Optional[str]:
        """
        Helper: Maps a specialization string to a local Organ ID.
        Simple implementation assuming you have a config map.
        """
        # Example: self.organ_specs = {"GuestEmpathy": "organ_guestcare", ...}
        return self.organ_specs.get(spec)

    async def route_and_execute(
        self,
        payload: Any,  # TaskPayload or dict
    ) -> Dict[str, Any]:
        """
        High-level one-shot:
          1. Route task to an agent
          2. Execute via OrganismCore

        Convenience API for simple callers.
        More complex workflows should call route_only() and execute_on_agent()
        manually to keep routing & execution separable.

        Args:
            payload: TaskPayload instance or dict with routing and risk information

        Returns:
            Dict with execution result and routing metadata attached
        """
        if not self.organism:
            return {"error": "OrganismCore not available"}

        # Normalize payload to TaskPayload if needed
        if not isinstance(payload, TaskPayload):
            try:
                payload = TaskPayload.from_db(payload)
            except Exception:
                logger.warning(
                    "[route_and_execute] Falling back to naive TaskPayload construction"
                )
                payload = TaskPayload(
                    task_id=str(
                        payload.get("task_id") or payload.get("id") or uuid.uuid4()
                    ),
                    type=payload.get("type") or "unknown_task",
                    params=payload.get("params") or {},
                    description=payload.get("description") or "",
                    domain=payload.get("domain"),
                    drift_score=float(payload.get("drift_score") or 0.0),
                    required_specialization=payload.get("required_specialization"),
                )

        try:
            # Step 1: routing (pure decision)
            # Note: route_only() will embed is_high_stakes into the payload
            decision = await self.route_only(payload)

            # Ensure payload is normalized to dict for embedding
            if isinstance(payload, TaskPayload):
                payload_dict = payload.model_dump()
            else:
                payload_dict = payload

            # Embed router's high-stakes decision into payload for execution
            # This ensures execution honors routing's decision (single source of truth)
            payload_dict.setdefault("params", {})
            payload_dict["params"].setdefault("_router_metadata", {})[
                "is_high_stakes"
            ] = decision.is_high_stakes

            # Step 2: execution (pure execution)
            result = await self.organism.execute_on_agent(
                organ_id=decision.organ_id,
                agent_id=decision.agent_id,
                payload=payload_dict,
            )

            # Attach routing metadata
            result.setdefault("routing", {})
            result["routing"]["router_decision"] = {
                "agent_id": decision.agent_id,
                "organ_id": decision.organ_id,
                "reason": decision.reason,
                "is_high_stakes": decision.is_high_stakes,
            }

            return result

        except Exception as e:
            logger.error(f"[route_and_execute] Failed: {e}", exc_info=True)
            return {"error": f"Routing and execution failure: {e}"}

    def clear_cache(self):
        """Clear the instance cache and LRU cache."""
        self._instance_cache.clear()
        # Clear LRU cache
        self._cached_route_key.cache_clear()

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get comprehensive routing statistics."""
        return {
            "rules_by_task_count": len(self.rules_by_task),
            "rules_by_domain_count": len(self.rules_by_domain),
            "agent_metrics_count": len(self.agent_metrics),
            "instance_cache_size": len(self._instance_cache),
            "lru_cache_info": self._cached_route_key.cache_info()._asdict(),
        }
