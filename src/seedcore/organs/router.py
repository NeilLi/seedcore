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
from contextlib import asynccontextmanager
from dataclasses import dataclass
import os
import time
import uuid
from functools import lru_cache
from typing import Dict, Any, Optional, NamedTuple, Tuple, List, TYPE_CHECKING

from numpy import random  # pyright: ignore[reportMissingImports]

import ray  # pyright: ignore[reportMissingImports]


if TYPE_CHECKING:
    from .organism_core import OrganismCore

# Runtime import for AgentIDFactory
from .organ import AgentIDFactory

from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.organs.router")
logger = ensure_serve_logger("seedcore.organs.router", level="DEBUG")

# Target namespace for Ray actors
RAY_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


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

    @asynccontextmanager
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
    def __init__(self, organism: "OrganismCore"):
        """
        Initialize RoutingDirectory with optimized lookup paths and unified caching.

        This component acts as the 'Cerebellum' - handling high-speed coordination
        without blocking the higher cognitive functions.
        """
        # Initialize logger (CRITICAL: must be set before any logging calls)
        self.logger = logger

        # --- 1. Configuration & Safety Defaults ---
        # Ensure we don't crash if config is missing keys; set defaults for weights
        self._raw_config = organism.router_cfgs or {}
        self.config = {
            "default_timeout": self._raw_config.get("default_timeout", 5.0),
            "weights": self._raw_config.get(
                "scoring_weights", {"load": 0.4, "affinity": 0.6}
            ),
            "cache_ttl": self._raw_config.get("cache_ttl", 3.0),
        }

        self.organism = organism
        # --- 2. Dependencies (Reference Holding) ---
        self.organ_handles = organism.organs
        self.tunnel_manager = organism.tunnel_manager
        # Maps specialization string (e.g., "reasoning") -> organ_id (e.g., "reasoning_organ_01")
        self.organ_specs = organism.organ_specs or {}

        # ID Factory for generating Trace IDs/Agent IDs
        self.agent_id_factory = AgentIDFactory()

        # --- 3. Routing State Containers ---
        # Static Rules: explicit overrides (task_type -> target_id)
        self.rules_by_task: Dict[str, str] = {}

        # Domain Rules: (domain, sub_domain) -> target_id
        self.rules_by_domain: Dict[Tuple[str, str], str] = {}

        # Logical Groups: task_type -> List[agent_ids] (Pools for load balancing)
        self.logical_groups: Dict[str, List[str]] = {}

        # Metrics: Real-time telemetry (load, latency) - Updated by Heartbeat/Feedback loop
        self.agent_metrics: Dict[str, Dict[str, Any]] = {}

        # --- 4. Unified Caching Strategy ---
        # REMOVED: self._instance_cache, self._last_cache_miss_log (Redundant)
        # INSTALLED: Dedicated RouteCache with jitter to prevent thundering herd
        self.route_cache = RouteCache(ttl_s=self.config["cache_ttl"], jitter_s=0.5)

        # --- 5. Rule & Table Initialization ---
        self._initialize_routing_rules()

        # Async lock for dynamic route updates (not read operations)
        self._lock = asyncio.Lock()

    def _initialize_routing_rules(self) -> None:
        """
        Internal helper to pre-compute lookup tables and apply default
        routing logic based on available organs.
        """
        # --- 1. Pre-computation (Fast Path) ---
        # Flatten structures for O(1) lookup during high-frequency routing
        self._build_fast_lookup_tables()

        # --- 2. Default Rule Assignment (Heuristic-based) ---
        # Note: Rules follow a precedence order based on organ availability
        if "user_experience_organ" in self.organ_handles:
            self.set_rule("query", "user_experience_organ")
            self.logger.debug(
                "[Router] Default rule set: 'query' -> 'user_experience_organ' "
                "(USER_LIAISON specialization)"
            )

        # Using a separate 'if' if these are non-exclusive,
        # or 'elif' if you only want one primary default.
        if "orchestration_organ" in self.organ_handles:
            self.set_rule("action", "orchestration_organ")
            self.logger.debug(
                "[Router] Default rule set: 'action' -> 'orchestration_organ' "
                "(DEVICE_ORCHESTRATOR specialization)"
            )

    def _build_fast_lookup_tables(self) -> None:
        """
        Internal helper to flatten organism structure into high-speed lookup dicts.
        Optimizes for O(1) task-to-organ-pool resolution.
        """
        # Reset tables to ensure consistency during re-balance
        new_logical_groups: Dict[str, List[str]] = {}

        # 1. Map Organs to Task Types (Logical Groups)
        for organ_id in self.organ_handles:
            # Retrieve metadata from the Organism registry rather than the Actor itself
            # This avoids async/network overhead during table construction
            specs = self.organ_specs.get(organ_id, {})
            supported_tasks = specs.get("supported_tasks", [])

            for task_type in supported_tasks:
                if task_type not in new_logical_groups:
                    new_logical_groups[task_type] = []
                new_logical_groups[task_type].append(organ_id)

        # 2. Atomic Update of the Live Tables
        self.logical_groups = new_logical_groups

        # 3. Telemetry/Metrics Initialization
        # Pre-seed metrics for every known organ to avoid 'if key in dict' checks later
        for organ_id in self.organ_handles:
            if organ_id not in self.agent_metrics:
                self.agent_metrics[organ_id] = {
                    "load": 0.0,
                    "latency_ms": 0.0,
                    "last_seen": time.time(),
                    "status": "active",
                }

        # 4. Log multi-organ support for task types
        for task_type, organ_list in new_logical_groups.items():
            if len(organ_list) > 1:
                self.logger.debug(
                    f"[Router] Multiple organs support '{task_type}': {organ_list}"
                )

    async def get_target_handle(self, agent_id: str) -> Any:
        """
        Optimized accessor to get an execution handle (Ray Actor).
        Checks Cache -> Checks Organism Registry.
        """
        # 1. Hot Cache Hit
        cached_handle = self.route_cache.get(agent_id)
        if cached_handle:
            return cached_handle

        # 2. Cache Miss - Resolve via Organism (Complex Logic)
        # Note: In a real Ray cluster, 'getting' the handle is often just
        # resolving the name, which is fast.
        handle = await self.tunnel_manager.get_actor_handle(agent_id)

        if handle:
            # 3. Write back to cache
            self.route_cache.set(agent_id, handle)

        return handle

    @staticmethod
    def _normalize(x: Optional[str]) -> Optional[str]:
        """Normalize string for consistent matching."""
        return str(x).strip().lower() if x is not None else None

    def _find_organ_by_spec(self, spec: str) -> Optional[str]:
        """
        Find the organ ID that hosts agents with the given specialization.

        Args:
            spec: Specialization string (e.g., "generalist", "user_liaison")

        Returns:
            Organ ID if found, None otherwise
        """
        if not spec:
            return None

        # Normalize the specialization string
        spec_normalized = self._normalize(spec)
        if not spec_normalized:
            return None

        # Look up in organ_specs map (specialization -> organ_id)
        # This map is populated during agent creation in OrganismCore
        organ_id = self.organ_specs.get(spec_normalized)
        if organ_id:
            return organ_id

        # Fallback: try matching by partial name (e.g., "generalist" matches "GENERALIST")
        for spec_key, organ_id in self.organ_specs.items():
            if (
                spec_normalized in spec_key.lower()
                or spec_key.lower() in spec_normalized
            ):
                return organ_id

        return None

    # --- (A) AgentIDFactory Integration ---

    def new_agent_id(self, logical_id: str, spec: Optional[Any] = None) -> str:
        """
        Generate a new agent ID using AgentIDFactory for consistent format.
        
        This delegates to AgentIDFactory which uses the format:
        agent_{organ_id}_{specialization}_{unique12}

        Args:
            logical_id: Logical ID of the organ
            spec: Optional specialization (string or SpecializationProtocol)

        Returns:
            Agent ID in format: agent_{organ_id}_{specialization}_{unique12}
        """
        if not spec:
            # Fallback to simple UUID-based ID if no specialization
            return f"agent_{logical_id}-{uuid.uuid4().hex[:8]}"
        
        # Convert string spec to SpecializationProtocol if needed for AgentIDFactory
        if isinstance(spec, str):
            # Try to resolve to SpecializationProtocol, but if it fails, create a simple wrapper
            try:
                from seedcore.agents.roles.specialization import get_specialization
                spec_protocol = get_specialization(spec)
            except (KeyError, ImportError):
                # If specialization not found, create a simple wrapper for AgentIDFactory
                # AgentIDFactory expects SpecializationProtocol with .value attribute
                class SimpleSpec:
                    def __init__(self, value: str):
                        self.value = value
                spec_protocol = SimpleSpec(spec)
        else:
            # Already a SpecializationProtocol
            spec_protocol = spec
        
        # Use AgentIDFactory which generates consistent format: agent_{organ_id}_{specialization}_{unique12}
        if self.agent_id_factory:
            return self.agent_id_factory.new(logical_id, spec_protocol)
        
        # Fallback if factory not available (shouldn't happen, but be safe)
        unique_id = uuid.uuid4().hex[:12]
        spec_value = spec_protocol.value if hasattr(spec_protocol, 'value') else str(spec_protocol)
        spec_safe = spec_value.lower().replace("/", "_").replace(".", "_").replace("-", "_")
        return f"agent_{logical_id}_{spec_safe}_{unique_id}"

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
            logger.debug(f"[Router] Rule set: {tt} + {dm} -> {logical_id}")
        else:
            # Stage 5: General Task-Type fallback
            self.rules_by_task[tt] = logical_id
            logger.debug(f"[Router] Rule set: {tt} -> {logical_id}")

    def remove_rule(self, task_type: str, domain: Optional[str] = None):
        """Remove a static routing rule."""
        tt = self._normalize(task_type)
        dm = self._normalize(domain)

        if tt is None:
            return

        if dm:
            if (tt, dm) in self.rules_by_domain:
                del self.rules_by_domain[(tt, dm)]
                logger.debug(f"[Router] Rule removed: {tt} + {dm}")
        else:
            if tt in self.rules_by_task:
                del self.rules_by_task[tt]
                logger.debug(f"[Router] Rule removed: {tt}")

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
                handle = ray.get_actor(logical_id, namespace=RAY_NAMESPACE)

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
        # routing.tools = list of tool identifiers (RBAC/scoring)
        tools_list = routing.get("tools") or []

        normalized_tools: List[str] = []
        for item in tools_list:
            if isinstance(item, str) and item.strip():
                normalized_tools.append(item)

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
            "tools": normalized_tools,
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

    async def resolve(
        self,
        task_type: str,
        domain: Optional[str] = None,
        preferred_logical_id: Optional[str] = None,
        input_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], str]:
        """
        SeedCore v2 Organism Router (Specialization & V2 Compliant).

        Optimized for high-concurrency caching and correct specific-agent overrides.
        """
        # 1. Input Normalization & Safety
        tt = self._normalize(task_type)
        dm = self._normalize(domain)
        meta = input_meta or {}  # Safe-guard against None

        # Extract V2 signals that alter routing logic
        req_spec = meta.get("required_specialization")
        soft_spec = meta.get("specialization")
        is_high_stakes = meta.get("is_high_stakes", False)

        # ----------------------------------------
        # 2. Define Robust Cache Key
        # ----------------------------------------
        # CRITICAL FIX: Include preferred_id and high_stakes in the key.
        # Otherwise, a generic request could poison the cache for specific requests.
        cache_key = (
            tt,
            dm,
            preferred_logical_id,  # <--- Was missing
            req_spec,
            soft_spec,
            is_high_stakes,  # <--- Was missing (High stakes might route differently)
        )

        # ----------------------------------------
        # 3. Fast Path (Cache Hit)
        # ----------------------------------------
        cached_entry = self.route_cache.get(cache_key)
        if cached_entry:
            return cached_entry.logical_id, cached_entry.resolved_from

        # ----------------------------------------
        # 4. Thundering Herd Protection (Singleflight)
        # ----------------------------------------
        # "Singleflight" ensures only one coroutine computes the route for this key;
        # others wait for the result.
        async with self.route_cache.singleflight(cache_key) as (fut, is_leader):
            if is_leader:
                # --- LEADER ROLE ---
                try:
                    # Perform the expensive logic
                    organ_id, reason = await self._run_full_resolve_logic(
                        tt, dm, preferred_logical_id, meta
                    )

                    # Validate result before caching
                    if not organ_id:
                        organ_id = getattr(self, "default_organ_id", "utility_organ")
                        reason = f"{reason}_fallback"

                    # Create Entry (RouteEntry uses logical_id, not organ_id)
                    entry = RouteEntry(
                        logical_id=organ_id,
                        epoch="",
                        resolved_from=reason,
                        cached_at=time.time(),
                    )

                    # Store in Cache
                    self.route_cache.set(cache_key, entry)

                    # Notify Followers
                    fut.set_result(entry)
                    return organ_id, reason

                except Exception as e:
                    # CRITICAL: If leader crashes, we must release followers
                    # otherwise they await forever (Deadlock).
                    self.logger.error(f"[Router] Leader calculation failed: {e}")

                    # We create a temporary fallback entry just for this error burst
                    # but maybe we DON'T cache it long term?
                    # For now, return safety fallback to keep system alive.
                    fallback_entry = RouteEntry(
                        logical_id="utility_organ",
                        epoch="",
                        resolved_from="router_error_fallback",
                        cached_at=time.time(),
                    )
                    fut.set_result(fallback_entry)
                    return fallback_entry.logical_id, fallback_entry.resolved_from

            else:
                # --- FOLLOWER ROLE ---
                # Await the leader's result
                try:
                    entry = await fut
                    return entry.logical_id, entry.resolved_from
                except Exception:
                    # If the future itself breaks (rare)
                    return "utility_organ", "singleflight_error"

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

        # --- Stage 1 — Required Specialization (HARD V2 Constraint) ---
        # Logic: TaskPayload said "Must be done by X agent."
        # CRITICAL: This is a HARD constraint from the task payload and takes priority
        # over preferred organ hints, matching coordinator behavior in execute.py.
        # Per task-payload-capabilities.md: required_specialization is a HARD constraint
        # that must be honored and overrides all defaults (type-level, PKG suggestions, memory).
        required_spec = input_meta.get("required_specialization")
        if required_spec:
            # Use the direct specialization map (organ_specs)
            lid = self._find_organ_by_spec(required_spec.lower())
            if lid:
                logger.debug(
                    f"[Router] Required specialization '{required_spec}' matched to organ '{lid}' "
                    "(hard constraint, highest priority)"
                )
                return lid, "required-specialization"
            else:
                # Note: We warn and fall through, allowing softer rules to match.
                logger.warning(
                    f"[Router] Required spec '{required_spec}' not found in any local organ."
                )

        # --- Stage 2 — Preferred Organ (Explicit Hint) ---
        # Logic: Coordinator or Caller explicitly asked for this Organ ID.
        # Note: This comes AFTER required_specialization since required_specialization
        # is a HARD constraint from the task payload.
        if preferred_id:
            # Simple existence check (optional, but good for safety)
            if preferred_id in self.organ_handles:
                return preferred_id, "preferred"

        # --- Stage 3 — Domain Rule (task_type + domain) ---
        # Logic: "All hospitality.guest tasks go to GuestCareOrgan" (Highly specific config).
        if dm:
            lid = self.rules_by_domain.get((tt, dm))
            if lid:
                return lid, "domain"

        # --- Stage 4 — Specialization Hint (SOFT V2 Hint) ---
        # Logic: "Preferably done by Generalist, but okay if not."
        # Note: This is checked AFTER required_specialization (Stage 1) since it's a soft hint.
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

    async def route_only(
        self,
        payload: Any,  # TaskPayload or dict
    ) -> RouterDecision:
        """
        Pure routing logic (V2 Optimized).
        Determines Organ and Agent without executing the task.
        """
        # --- 1. Payload Normalization (Zero-Copy View) ---
        # We assume payload is either a dict or a Pydantic model.
        # We access data via a unified dict-like interface for reads.
        if hasattr(payload, "model_dump"):
            # Don't dump yet if we can avoid it, just access attributes if needed.
            # But for safety and consistency with your generic dict usage:
            task_dict = payload.model_dump()
        else:
            task_dict = payload

        # Fast extraction of V2 Envelopes
        params = task_dict.get("params", {})
        interaction = params.get("interaction", {})
        routing_in = params.get("routing", {})
        risk = params.get("risk", {})

        # Normalize registered specialization variants if possible
        if isinstance(routing_in, dict) and isinstance(params, dict):
            for key in ("required_specialization", "specialization"):
                raw_val = routing_in.get(key)
                resolved_val = self._resolve_registered_specialization(raw_val)
                if resolved_val and resolved_val != raw_val:
                    routing_in[key] = resolved_val
                    params.setdefault("routing", {})
                    params["routing"][key] = resolved_val

        # Enforce write-lock on params._router (system-managed resolution only)
        if isinstance(params, dict):
            params.pop("_router", None)
        if hasattr(payload, "params") and isinstance(payload.params, dict):
            payload.params.pop("_router", None)

        # --- 2. Initial State & Fast Paths ---
        mode = interaction.get("mode", "coordinator_routed")
        conv_id = interaction.get("conversation_id")
        assigned_agent = interaction.get("assigned_agent_id")

        organ_id: Optional[str] = None
        agent_id: Optional[str] = None
        resolved_from: str = "unknown"

        # =========================================================
        # PHASE 1: ORGAN SELECTION (The "Where")
        # =========================================================

        # Path A: Explicit Tunneling (Fastest)
        if mode == "agent_tunnel" and assigned_agent:
            agent_id = assigned_agent
            # In a tunnel, we often don't care about the organ, but let's try to map it
            # if your ID structure allows (e.g., "organ_name::agent_hash")
            resolved_from = "tunnel_assignment"

        # Path B: Coordinator Directive (Trust Upstream)
        elif mode == "coordinator_routed":
            # 1. Spec-based mapping (if provided)
            # CRITICAL: Prioritize required_specialization (HARD constraint) over specialization (soft hint)
            # This matches the coordinator behavior in execute.py where required_specialization
            # is checked first as a HARD PRIORITY before any other routing logic.
            required_spec = routing_in.get("required_specialization")
            soft_spec = routing_in.get("specialization")
            
            # Check required_specialization first (hard constraint)
            if required_spec:
                organ_id = self._find_organ_by_spec(required_spec)
                if organ_id:
                    resolved_from = "coordinator_required_specialization"
                    logger.debug(
                        f"[Router] Using required_specialization '{required_spec}' for organ routing "
                        "(hard constraint from task payload)"
                    )
            # Fall back to soft specialization hint only if required_specialization not found
            elif soft_spec:
                organ_id = self._find_organ_by_spec(soft_spec)
                if organ_id:
                    resolved_from = "coordinator_specialization_hint"
                    logger.debug(
                        f"[Router] Using specialization hint '{soft_spec}' for organ routing"
                    )

            # 2. If no spec provided, check task_type rules (e.g., "query" -> "user_experience_organ")
            if not organ_id:
                task_type = task_dict.get("type", "unknown_task")
                organ_id, resolved_from = await self.resolve(
                    task_type=task_type,
                    domain=task_dict.get("domain"),
                    input_meta=self.extract_router_inputs(params),
                )

            # 3. Final fallback if still no organ found
            if not organ_id:
                organ_id = self.config.get("default_organ_id", "utility_organ")
                resolved_from = "coordinator_fallback"

        # Path C: Fresh Routing (Semantic Resolution)
        else:
            # Full semantic analysis via existing helper
            organ_id, resolved_from = await self.resolve(
                task_type=task_dict.get("type", "unknown_task"),
                domain=task_dict.get("domain"),
                input_meta=self.extract_router_inputs(params),
            )

        # Safety Net
        organ_id = organ_id or "utility_organ"

        # =========================================================
        # PHASE 2: AGENT SELECTION (The "Who")
        # =========================================================

        # 0. Soft RBAC-aware fallback: if tools requested but spec disallows them,
        # prefer a generalist/user_liaison organ instead of spawning a specialized agent.
        if not agent_id:
            required_spec = routing_in.get("required_specialization")
            soft_spec = routing_in.get("specialization")
            tools_list = routing_in.get("tools") or []
            # Only apply for soft hints (do NOT override hard required specialization).
            if soft_spec and not required_spec and tools_list:
                if not self._tools_allowed_for_spec(soft_spec, tools_list):
                    self.logger.info(
                        f"[Router] Tools {tools_list} not allowed for specialization '{soft_spec}'. "
                        "Routing to fallback agent."
                    )
                    if "user_experience_organ" in self.organ_handles:
                        organ_id = "user_experience_organ"
                        if isinstance(params, dict):
                            params.setdefault("routing", {})
                            params["routing"]["required_specialization"] = "user_liaison"
                            params["routing"]["specialization"] = "user_liaison"
                        routing_in = {
                            **routing_in,
                            "required_specialization": "user_liaison",
                            "specialization": "user_liaison",
                        }
                        resolved_from = "rbac_soft_fallback_user_liaison"
                    elif "utility_organ" in self.organ_handles:
                        organ_id = "utility_organ"
                        if isinstance(params, dict):
                            params.setdefault("routing", {})
                            params["routing"]["required_specialization"] = "generalist"
                            params["routing"]["specialization"] = "generalist"
                        routing_in = {
                            **routing_in,
                            "required_specialization": "generalist",
                            "specialization": "generalist",
                        }
                        resolved_from = "rbac_soft_fallback_generalist"

        # 1. Sticky Session Check (Tunnel Mode)
        if not agent_id and mode == "agent_tunnel" and conv_id:
            agent_id = await self.tunnel_manager.get_assigned_agent(conv_id)
            if agent_id:
                resolved_from = "sticky_session"

        # 2. Dynamic Organ Dispatch (The Heavy Lifting)
        if not agent_id:
            # Delegate strictly to helper to keep this function clean
            agent_id = await self._select_agent_from_organ(
                organ_id=organ_id, routing_in=routing_in
            )
            if not agent_id:
                # 3. Factory Fallback (Last Resort)
                # Extract specialization from routing hints if available
                spec = routing_in.get("required_specialization") or routing_in.get(
                    "specialization"
                )
                # Guard: If specialization is unregistered, do NOT generate a new ID for it.
                # Instead, try to reuse existing GENERALIST/USER_LIAISON agents.
                if spec and not self._is_registered_specialization(spec):
                    self.logger.info(
                        f"[Router] Specialization '{spec}' is unregistered. "
                        "Skipping ID generation and attempting fallback reuse."
                    )
                    fallback_agent_id = None
                    fallback_organ_id = None

                    # Prefer generalist in utility_organ
                    if "utility_organ" in self.organ_handles:
                        fallback_organ_id = "utility_organ"
                        fallback_agent_id = await self._select_agent_from_organ(
                            organ_id=fallback_organ_id,
                            routing_in={
                                "required_specialization": "generalist",
                            },
                        )

                    # Then try user_liaison in user_experience_organ
                    if (
                        not fallback_agent_id
                        and "user_experience_organ" in self.organ_handles
                    ):
                        fallback_organ_id = "user_experience_organ"
                        fallback_agent_id = await self._select_agent_from_organ(
                            organ_id=fallback_organ_id,
                            routing_in={
                                "required_specialization": "user_liaison",
                            },
                        )

                    if fallback_agent_id:
                        agent_id = fallback_agent_id
                        organ_id = fallback_organ_id or organ_id
                        resolved_from = "unregistered_spec_fallback"
                    else:
                        # No fallback agents found; retarget to GENERALIST in utility_organ.
                        # This still avoids generating an ID for the unregistered specialization.
                        if "utility_organ" in self.organ_handles:
                            organ_id = "utility_organ"
                        spec = "generalist"
                        routing_in = {
                            **routing_in,
                            "required_specialization": spec,
                        }
                        resolved_from = "unregistered_spec_retargeted"
                # Use consistent naming format: {organ_id}_{specialization}_{index}
                # This matches static agent naming (e.g., physical_actuation_organ_safety_guard_0)
                if not agent_id:
                    agent_id = self.new_agent_id(organ_id, spec)
                    self.logger.debug(
                        f"[Router] Generated new ID {agent_id} for {organ_id} with specialization {spec}"
                    )

        # =========================================================
        # PHASE 3: RESULT COMPOSITION
        # =========================================================

        is_high_stakes = bool(risk.get("is_high_stakes", False))

        decision = RouterDecision(
            agent_id=agent_id,
            organ_id=organ_id,
            reason=resolved_from,
            is_high_stakes=is_high_stakes,
        )

        # Side-Effect: Patch the payload envelopes for downstream execution
        # (This allows the Agent to see *why* it was picked without re-calculating)
        router_out = {
            "is_high_stakes": is_high_stakes,
            "agent_id": agent_id,
            "organ_id": organ_id,
            "reason": resolved_from,
            "routed_at": self._current_timestamp(),
        }

        # If mutable Pydantic model, update it directly
        if hasattr(payload, "params") and isinstance(payload.params, dict):
            payload.params["_router"] = router_out
        elif isinstance(payload, dict):
            # Update the dict reference passed in
            if "params" not in payload:
                payload["params"] = {}
            payload["params"]["_router"] = router_out

        return decision

    # --- Helper: Decoupled Ray Interaction ---
    async def _select_agent_from_organ(
        self, organ_id: str, routing_in: dict
    ) -> Optional[str]:
        """
        Interacts with the remote Organ Actor to pick the best agent.
        Uses native async await for Ray ObjectRefs.
        """
        organ_handle = self.organ_handles.get(organ_id)
        if not organ_handle:
            return None

        try:
            # Extract criteria
            skills = routing_in.get("skills")
            spec = routing_in.get("required_specialization") or routing_in.get(
                "specialization"
            )

            # Dispatch RPC (Non-blocking)
            if spec:
                ref = organ_handle.pick_agent_by_specialization.remote(
                    spec, skills or {}
                )
            elif skills:
                ref = organ_handle.pick_agent_by_skills.remote(skills)
            else:
                ref = organ_handle.pick_random_agent.remote()

            # Native Ray Await (Yields control to event loop)
            # This is significantly faster than asyncio.to_thread(ray.get, ref)
            result = await ref

            # Normalize Result
            if isinstance(result, (tuple, list)):
                return result[0]  # (agent_id, score)
            return result

        except Exception as e:
            # We catch broadly here because a routing failure shouldn't crash the request,
            # it should just trigger the "Factory Generation" fallback in the main method.
            self.logger.warning(f"[Router] Ray dispatch failed for {organ_id}: {e}")
            return None

    def _is_registered_specialization(self, spec_str: str) -> bool:
        """
        Check if a specialization string is registered (supports alias normalization).
        """
        if not spec_str:
            return False
        try:
            from seedcore.agents.roles.specialization import SpecializationManager

            spec_manager = SpecializationManager.get_instance()
            normalized = str(spec_str).strip().lower()
            variants = [
                normalized,
                normalized.replace(".", "_"),
                normalized.replace("-", "_"),
                normalized.replace("/", "_"),
            ]
            for v in variants:
                if spec_manager.is_registered(v):
                    return True
        except Exception:
            return False
        return False

    def _resolve_registered_specialization(self, spec_str: Optional[str]) -> Optional[str]:
        """
        Resolve a specialization string to a registered variant (normalized).
        Returns the registered value or None if not registered.
        """
        if not spec_str:
            return None
        try:
            from seedcore.agents.roles.specialization import SpecializationManager

            spec_manager = SpecializationManager.get_instance()
            normalized = str(spec_str).strip().lower()
            variants = [
                normalized,
                normalized.replace(".", "_"),
                normalized.replace("-", "_"),
                normalized.replace("/", "_"),
            ]
            for v in variants:
                if spec_manager.is_registered(v):
                    return v
        except Exception:
            return None
        return None

    def _tools_allowed_for_spec(self, spec_str: str, tools: List[str]) -> bool:
        """
        Check if all requested tools are allowed for the given specialization.
        Returns True if unknown (non-blocking).
        """
        if not spec_str or not tools:
            return True
        try:
            from seedcore.agents.roles.specialization import SpecializationManager

            spec_manager = SpecializationManager.get_instance()
            spec_obj = spec_manager.get(str(spec_str).strip().lower())
            if not spec_obj or not self.organism:
                return True
            role_registry = getattr(self.organism, "role_registry", None)
            if not role_registry:
                return True
            profile = role_registry.get_safe(spec_obj)
            if not profile:
                return True
            allowed = set(getattr(profile, "allowed_tools", []) or [])
            # If allowed_tools is empty, treat as "no tools allowed".
            return all(t in allowed for t in tools)
        except Exception:
            return True

    def _current_timestamp(self):
        import time

        return str(time.time())

    async def route_and_execute(
        self,
        payload: Any,  # Union[TaskPayload, Dict]
        current_epoch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Orchestration wrapper: Routes -> Stamps Payload -> Executes.

        This ensures the Agent receives the exact context (High Stakes, Reason)
        that the Router decided upon.
        """
        if not self.organism:
            # Fast fail if core dependency is broken
            return {
                "success": False,
                "error": "OrganismCore (ExecutionEngine) not attached",
            }

        # --- 1. Payload Normalization ---
        # We need a mutable dictionary for the execution layer.
        # If it's a Pydantic model, dump it now to ensure mutable access
        # for the router injection in the next step.
        if hasattr(payload, "model_dump"):
            task_dict = payload.model_dump()
        elif isinstance(payload, dict):
            task_dict = payload
        else:
            # Legacy/Fallback construction (simplified)
            # We assume the caller knows what they are doing, but if it's a string or raw obj,
            # we wrap it safely.
            task_dict = {
                "id": str(uuid.uuid4()),
                "type": "unknown_raw",
                "params": {"raw_payload": str(payload)},
            }

        # --- 2. Routing (Decision Phase) ---
        try:
            # The route_only method (from previous optimization) will:
            # 1. Calculate the target.
            # 2. INJECT the decision into task_dict['params']['_router'].
            # We pass task_dict by reference.
            decision = await self.route_only(task_dict)

        except Exception as e:
            self.logger.error(f"[Router] Routing decision failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Routing Failure: {str(e)}",
                "stage": "routing",
            }

        # --- 3. Execution (Action Phase) ---
        try:
            # We pass the modified task_dict which now contains the routing metadata.
            # The OrganismCore sees exactly what the Router saw.
            result = await self.organism.execute_on_agent(
                organ_id=decision.organ_id,
                agent_id=decision.agent_id,
                payload=task_dict,
            )

            # --- 4. Response Enrichment ---
            # Ensure the caller knows *how* this result was achieved.
            # We attach the decision metadata to the final output.
            if isinstance(result, dict):
                result.setdefault("routing", {})
                result["routing"].update(
                    {
                        "agent_id": decision.agent_id,
                        "organ_id": decision.organ_id,
                        "reason": decision.reason,
                        "is_high_stakes": decision.is_high_stakes,
                        "router_latency": "included_in_trace",  # Optional: add timing
                    }
                )

            return result

        except Exception as e:
            self.logger.error(
                f"[Router] Execution failed on {decision.agent_id}: {e}", exc_info=True
            )
            # Return a structured error response that the API/Coordinator can parse
            return {
                "success": False,
                "error": f"Execution Failure: {str(e)}",
                "target_agent": decision.agent_id,
                "stage": "execution",
            }

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
