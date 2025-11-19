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

import ray  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models import TaskPayload
from seedcore.models.task import TaskType

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
        """
        # Scoring configuration (tunable weights)
        self.config = {
            "load_weight": 1000,
            "availability_weight": 100,
            "penalty_weight": 1000,
            "deadline_boost": 50,
            "priority_boost": 20,
            **(config or {})
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
        
        # Runtime cache for active Ray actor handles (short TTL)
        # Stores: logical_id -> (ActorHandle, cached_timestamp)
        self._instance_cache: Dict[str, Tuple[Any, float]] = {}
        self._cache_ttl = 3.0  # seconds
        self._lock = asyncio.Lock()
        
        # Rate-limited logging for cache misses (prevent log spam)
        self._last_cache_miss_log: Dict[str, float] = {}
        self._cache_miss_log_interval = 5.0  # seconds between log messages per logical_id
        
        # Load sensible defaults
        self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """
        Load default routing rules from TaskType -> dispatcher key.

        These are the canonical, "sane default" routes. They can be
        overridden by config or policy at runtime.
        """
        # -----------------------------
        # Graph / KG tasks → GraphDispatcher
        # -----------------------------
        graph_target = "graph_dispatcher"

        graph_tasks = (
            TaskType.GRAPH_EMBED,
            TaskType.GRAPH_RAG_QUERY,
            TaskType.GRAPH_FACT_EMBED,
            TaskType.GRAPH_FACT_QUERY,
            TaskType.NIM_TASK_EMBED,
            TaskType.GRAPH_SYNC_NODES,
        )
        for task_type in graph_tasks:
            self.rules_by_task[task_type] = graph_target

        # -----------------------------
        # General / queue tasks → QueueDispatcher
        # -----------------------------
        queue_target = "queue_dispatcher"

        general_tasks = (
            TaskType.PING,
            TaskType.HEALTH_CHECK,
            TaskType.GENERAL_QUERY,
            TaskType.TEST_QUERY,
            TaskType.FACT_SEARCH,
        )
        for task_type in general_tasks:
            self.rules_by_task[task_type] = queue_target

        # -----------------------------
        # Execution / actuation tasks
        # -----------------------------
        # For now, EXECUTE also goes through the QueueDispatcher, which can then
        # fan out to an actuator organ / device controller. If you later add an
        # explicit ActuatorDispatcher, just change `actuator_target` here.
        actuator_target = queue_target
        self.rules_by_task[TaskType.EXECUTE] = actuator_target

        # -----------------------------
        # Fallback for unknown tasks
        # -----------------------------
        # Anything we can't classify should still be handled in a predictable way.
        self.rules_by_task[TaskType.UNKNOWN_TASK] = queue_target

    
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
            "updated_at": time.time()
        }
    
    def get_agent_metrics(self, logical_id: str) -> Optional[Dict[str, Any]]:
        """Get current metrics for an agent."""
        return self.agent_metrics.get(logical_id)
    
    # --- (F) Ultra-Fast LRU Cache ---
    
    @lru_cache(maxsize=512)
    def _cached_route_key(self, tt: Optional[str], dm: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
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
        """Set a routing rule."""
        tt = self._normalize(task_type)
        dm = self._normalize(domain)
        if tt is None:
            return
        if dm:
            self.rules_by_domain[(tt, dm)] = logical_id
        else:
            self.rules_by_task[tt] = logical_id
    
    def remove_rule(self, task_type: str, domain: Optional[str] = None):
        """Remove a routing rule."""
        tt = self._normalize(task_type)
        dm = self._normalize(domain)
        if tt is None:
            return
        if dm:
            self.rules_by_domain.pop((tt, dm), None)
        else:
            self.rules_by_task.pop(tt, None)
    
    def get_rules(self) -> Dict[str, Any]:
        """Get current routing rules."""
        return {
            "rules_by_task": self.rules_by_task.copy(),
            "rules_by_domain": {
                f"{k[0]}/{k[1]}": v for k, v in self.rules_by_domain.items()
            }
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
                    await asyncio.to_thread(lambda: ray.get(handle.ping.remote(), timeout=1.0))
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
                        await asyncio.to_thread(lambda: ray.get(handle.ping.remote(), timeout=1.0))
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
                await asyncio.to_thread(lambda: ray.get(handle.ping.remote(), timeout=1.0))

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
                    logical_id,
                    f"Failed resolving Ray actor '{logical_id}': {e}"
                )
                return None
    
    # --- TaskPayload Decomposition ---
    
    def extract_router_inputs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Decompose canonical router envelope from TaskPayload (params.routing + params.risk).
        
        Extracts:
            - required_specialization
            - desired_skills
            - tool_calls
            - hints (priority, deadlines, capacity hints)
            - endpoint clues (IoT, robots, humans)
            - risk.is_high_stakes
        
        Args:
            params: TaskPayload.params dictionary containing routing and risk information
        
        Returns:
            Dictionary of extracted routing inputs for use in resolve()
        """
        routing = (params or {}).get("routing", {})
        risk = (params or {}).get("risk", {})
        
        # Extract specialization + skills
        required_specialization = routing.get("required_specialization")
        desired_skills = routing.get("desired_skills", {})
        
        # Interpret tool_calls for endpoint/device routing
        tool_calls = routing.get("tool_calls", [])
        inferred_endpoint = None
        inferred_capability = None
        
        for tc in tool_calls:
            # Handle both dict and ToolCallPayload objects
            if isinstance(tc, dict):
                name = tc.get("name", "")
            else:
                # Assume it's a ToolCallPayload-like object
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
        
        # Extract hints (priority, capability/limits)
        hints = routing.get("hints", {})
        priority = hints.get("priority")
        deadline_at = hints.get("deadline_at")
        min_capability = hints.get("min_capability")
        max_mem_util = hints.get("max_mem_util")
        
        # Extract high-stakes info (must be routing aware!)
        is_high_stakes = risk.get("is_high_stakes", False)
        
        return {
            "required_specialization": required_specialization,
            "desired_skills": desired_skills,
            "tool_calls": tool_calls,
            "priority": priority,
            "deadline_at": deadline_at,
            "min_capability": min_capability,
            "max_mem_util": max_mem_util,
            "inferred_endpoint": inferred_endpoint,
            "capability": inferred_capability,
            "is_high_stakes": is_high_stakes,
        }
    
    # --- Enhanced Candidate Selection ---
    
    def _score_candidate(
        self, 
        metrics: Dict[str, Any], 
        routing_hints: Optional[Dict[str, Any]] = None
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
        self, 
        candidates: List[str], 
        routing_hints: Optional[Dict[str, Any]] = None
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
        input_meta: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[str], str]:
        """
        Clean, simplified routing pipeline.
        
        Priority Order:
        0. High-stakes override
        1. Preferred logical_id
        2. Domain-specific routing (task_type + domain)
        3. Specialization domain routing ("specialization:xxx")
        4. Tenant/org domain routing ("tenant:xxx")
        5. Task-type rule (rules_by_task)
        6. Candidate group selection + _pick_best_candidate()
        7. Category defaults
        8. Ultimate fallback
        
        Args:
            task_type: Task type identifier
            domain: Optional domain identifier (supports special prefixes)
            preferred_logical_id: Preferred logical ID (highest priority)
            input_meta: Optional metadata dict. Can be:
                - Direct routing metadata (specialization, tenant, etc.)
                - OR dict with "raw_params" key containing TaskPayload.params
                  (will be automatically decomposed via extract_router_inputs())
        
        Returns:
            Tuple of (logical_id, resolved_from) where resolved_from indicates the resolution path
        """
        # Normalize keys
        tt, dm = self._cached_route_key(
            self._normalize(task_type),
            self._normalize(domain)
        )
        if not tt:
            return None, "error"
        
        # If params were given via dispatcher → extract canonical inputs
        if input_meta and "raw_params" in input_meta:
            input_meta = self.extract_router_inputs(input_meta["raw_params"])
        
        input_meta = input_meta or {}
        
        logger.debug(
            f"[Router] Resolving task_type={task_type}, domain={domain}, "
            f"preferred={preferred_logical_id}, meta={input_meta}"
        )
        
        # -----------------------------------------------------------
        # Stage 0: High-stakes override
        # -----------------------------------------------------------
        if input_meta.get("is_high_stakes"):
            override_id = self.rules_by_task.get("high_stakes_organ")
            if override_id:
                inst = await self._get_active_instance(override_id)
                if inst:
                    logger.info(f"[Router] High-stakes override: routing to {override_id}")
                    return override_id, "high-stakes"
        
        # -----------------------------------------------------------
        # Stage 1: Preferred logical_id
        # -----------------------------------------------------------
        if preferred_logical_id:
            inst = await self._get_active_instance(preferred_logical_id)
            if inst:
                return preferred_logical_id, "preferred"
        
        # -----------------------------------------------------------
        # Stage 2: Domain-specific rule (task_type + domain)
        # -----------------------------------------------------------
        if dm and (tt, dm) in self.rules_by_domain:
            lid = self.rules_by_domain[(tt, dm)]
            inst = await self._get_active_instance(lid)
            if inst:
                return lid, "domain"
        
        # -----------------------------------------------------------
        # Stage 3: Specialization rule ("specialization:xxx")
        # -----------------------------------------------------------
        specialization = (
            input_meta.get("specialization")
            or (dm.split("specialization:", 1)[1] if dm and dm.startswith("specialization:") else None)
        )
        if specialization:
            key = (tt, f"specialization:{specialization}")
            if key in self.rules_by_domain:
                lid = self.rules_by_domain[key]
                inst = await self._get_active_instance(lid)
                if inst:
                    return lid, "specialization"
        
        # -----------------------------------------------------------
        # Stage 4: Tenant/org rule ("tenant:xxx")
        # -----------------------------------------------------------
        tenant = (
            input_meta.get("tenant")
            or (dm.split("tenant:", 1)[1] if dm and dm.startswith("tenant:") else None)
        )
        if tenant:
            key = (tt, f"tenant:{tenant}")
            if key in self.rules_by_domain:
                lid = self.rules_by_domain[key]
                inst = await self._get_active_instance(lid)
                if inst:
                    return lid, "tenant"
        
        # -----------------------------------------------------------
        # Stage 5: Task-type rule
        # -----------------------------------------------------------
        if tt in self.rules_by_task:
            lid = self.rules_by_task[tt]
            inst = await self._get_active_instance(lid)
            if inst:
                return lid, "task"
        
        # -----------------------------------------------------------
        # Stage 6: Candidate list + _pick_best_candidate()
        # -----------------------------------------------------------
        candidates = self.logical_groups.get(tt, [])
        if candidates:
            selected = await self._pick_best_candidate(candidates, routing_hints=input_meta)
            if selected:
                return selected, "candidate-selection"
        
        # -----------------------------------------------------------
        # Stage 7: Category defaults (utility / graph / actuator)
        # -----------------------------------------------------------
        if tt in ["general_query", "health_check", "fact_search", "fact_store",
                  "artifact_manage", "capability_manage", "memory_cell_manage",
                  "model_manage", "policy_manage", "service_manage", "skill_manage"]:
            lid = "utility_organ_1"
        elif tt == "execute":
            lid = "actuator_organ_1"
        elif tt in ["graph_embed", "graph_rag_query",
                    "graph_sync_nodes", "graph_fact_embed", "graph_fact_query"]:
            lid = "graph_dispatcher"
        else:
            lid = "utility_organ_1"
        
        inst = await self._get_active_instance(lid)
        if inst:
            return lid, "default"
        
        # -----------------------------------------------------------
        # Stage 8: Ultimate fallback
        # -----------------------------------------------------------
        return lid, "fallback"
    
    async def route_only(
        self,
        payload: Any  # TaskPayload
    ) -> RouterDecision:
        """
        Pure routing. Returns RouterDecision.
        
        This is the canonical API for Dispatcher, Coordinator,
        and external IoT/human/robot services.
        
        Used when callers need routing decisions but not immediate execution.
        
        Args:
            payload: TaskPayload instance with routing and risk information
        
        Returns:
            RouterDecision with agent_id, organ_id, reason, and is_high_stakes flag
        """
        # Extract routing inputs from TaskPayload
        task_dict = payload.model_dump() if hasattr(payload, 'model_dump') else payload
        params = task_dict.get("params", {})
        
        # Extract routing inputs
        routing_inputs = self.extract_router_inputs(params)
        
        # Get task type and domain
        task_type = task_dict.get("type") or "unknown_task"
        domain = task_dict.get("domain")
        
        # Resolve to logical_id (organ_id)
        logical_id, resolved_from = await self.resolve(
            task_type=task_type,
            domain=domain,
            input_meta=routing_inputs
        )
        
        if not logical_id:
            # Fallback to default organ (meta_control_organ is the first organ in config)
            logical_id = "meta_control_organ"
            resolved_from = "fallback"
        
        # Determine organ_id (logical_id is the organ)
        organ_id = logical_id
        
        # Determine agent_id
        # If organism is available, query the organ for available agents
        agent_id = None
        if self.organism and hasattr(self.organism, 'organs'):
            organ_handle = self.organism.organs.get(organ_id)
            if organ_handle:
                try:
                    # Try to get an agent from the organ
                    # Use specialization if available
                    required_spec = routing_inputs.get("required_specialization")
                    if required_spec:
                        # Query organ for agent by specialization
                        try:
                            import ray  # type: ignore
                            pick_result_ref = organ_handle.pick_agent_by_specialization.remote(required_spec)
                            agent_id, _ = await asyncio.to_thread(ray.get, pick_result_ref)
                        except ImportError:
                            logger.debug("Ray not available, cannot query organ for agent")
                    else:
                        # Pick random agent from organ
                        try:
                            import ray  # type: ignore
                            pick_result_ref = organ_handle.pick_random_agent.remote()
                            agent_id, _ = await asyncio.to_thread(ray.get, pick_result_ref)
                        except ImportError:
                            logger.debug("Ray not available, cannot query organ for agent")
                except Exception as e:
                    logger.debug(f"Failed to query organ for agent: {e}")
        
        # Fallback: generate agent_id if not found
        if not agent_id:
            # Use AgentIDFactory if available, otherwise generate simple ID
            agent_id = self.new_agent_id(organ_id)
        
        # Check if high-stakes
        is_high_stakes = routing_inputs.get("is_high_stakes", False)
        
        # Embed router's high-stakes decision into payload for execution
        # This ensures execution honors routing's decision (single source of truth)
        # Convert payload to dict if needed for embedding
        if hasattr(payload, 'model_dump'):
            # TaskPayload object - convert to dict, embed, then update
            task_dict = payload.model_dump()
            task_dict.setdefault("params", {})
            task_dict["params"].setdefault("_router_metadata", {})["is_high_stakes"] = is_high_stakes
            # Update the original payload if it's mutable
            if isinstance(payload.params, dict):
                payload.params.setdefault("_router_metadata", {})["is_high_stakes"] = is_high_stakes
        else:
            # Dict payload - embed directly
            task_dict = payload
            task_dict.setdefault("params", {})
            task_dict["params"].setdefault("_router_metadata", {})["is_high_stakes"] = is_high_stakes
        
        return RouterDecision(
            agent_id=agent_id,
            organ_id=organ_id,
            reason=resolved_from,
            is_high_stakes=is_high_stakes
        )
    
    async def route_and_execute(
        self,
        payload: Any  # TaskPayload or dict
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
                logger.warning("[route_and_execute] Falling back to naive TaskPayload construction")
                payload = TaskPayload(
                    task_id=str(payload.get("task_id") or payload.get("id") or uuid.uuid4()),
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
            payload_dict["params"].setdefault("_router_metadata", {})["is_high_stakes"] = decision.is_high_stakes
            
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
    
    def explain(
        self,
        task_type: str,
        domain: Optional[str] = None,
        input_meta: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """
        Return step-by-step routing steps that would be attempted in order.
        
        Useful for debugging and UI dashboards. This is a synchronous method
        that shows the routing logic without actually executing async resolution.
        
        Args:
            task_type: Task type identifier
            domain: Optional domain identifier
            input_meta: Optional metadata dict
        
        Returns:
            List of routing stage descriptions in order of evaluation
        """
        steps = []
        tt = self._normalize(task_type)
        dm = self._normalize(domain)
        input_meta = input_meta or {}
        
        if not tt:
            return ["ERROR: Invalid task_type"]
        
        # Check if we need to extract from raw_params
        if input_meta and "raw_params" in input_meta:
            input_meta = self.extract_router_inputs(input_meta["raw_params"])
        
        steps.append("0. High-stakes override (if params.risk.is_high_stakes)")
        steps.append("1. Preferred logical_id (if provided)")
        
        # Stage 2: Domain-specific rule
        if dm and (tt, dm) in self.rules_by_domain:
            logical_id = self.rules_by_domain[(tt, dm)]
            steps.append(f"2. Domain-specific rule: ({tt}, {dm}) -> {logical_id}")
        else:
            steps.append(f"2. Domain-specific rule: ({tt}, {dm}) -> NOT FOUND")
        
        # Stage 3: Tenant domain
        tenant = input_meta.get("tenant") or (dm.split("tenant:", 1)[1] if dm and dm.startswith("tenant:") else None)
        if tenant:
            tenant_key = self._normalize(tenant)
            tenant_domain_key = (tt, f"tenant:{tenant_key}")
            lid = self.rules_by_domain.get(tenant_domain_key)
            steps.append(f"3. Tenant/org domain: '{tenant}' -> {lid or 'NOT FOUND'}")
        else:
            steps.append("3. Tenant/org domain: (not applicable)")
        
        # Stage 4: Task-type rule
        if tt in self.rules_by_task:
            logical_id = self.rules_by_task[tt]
            steps.append(f"4. Task-type rule: '{tt}' -> {logical_id}")
        else:
            steps.append(f"4. Task-type rule: '{tt}' -> NOT FOUND")
        
        # Stage 5: Category defaults
        if tt in ["general_query", "health_check", "fact_search", "fact_store",
                 "artifact_manage", "capability_manage", "memory_cell_manage",
                 "model_manage", "policy_manage", "service_manage", "skill_manage"]:
            steps.append("5. Category defaults: utility_organ_1")
        elif tt == "execute":
            steps.append("5. Category defaults: actuator_organ_1")
        elif tt in ["graph_embed", "graph_rag_query",
                   "graph_sync_nodes", "graph_fact_embed", "graph_fact_query"]:
            steps.append("5. Category defaults: graph_dispatcher")
        else:
            steps.append("5. Category defaults: utility_organ_1 (ultimate fallback)")
        
        steps.append("6. Ultimate fallback: utility_organ_1")
        
        return steps

