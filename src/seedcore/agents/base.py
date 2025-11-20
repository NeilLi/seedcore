# src/seedcore/agents/base.py
"""
Base Agent abstraction.

This class wires together:
- Specialization & skills (seedcore.agents.roles.*)
- RBAC enforcement (tools & data scopes)
- Salience scoring via MLServiceClient (seedcore.serve.ml_client) - LOCAL scoring only
- Routing advertisement for the meta-controller (passive, not routing decisions)
- Minimal heartbeat & agent-local metrics (not system-wide)
- Example async task handler showing salience-aware flow

Architectural Principle: BaseAgent is a LOCAL REFLEX LAYER.
It reacts to tasks, executes tool calls, computes local salience, and returns local intents.
It does NOT perform global routing, cognitive reasoning, cross-agent coordination,
recovery FSM, proactive planning, policy decisions, KG writes, emergent behavior,
role selection, or democratized salience coordination.

Replace stubs (_get_agent_load_estimate, _fallback_salience_scorer, etc.) with real probes/heuristics.
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Tuple, Union

# ---- Roles / Skills / RBAC / Routing -------------------------------------------

from seedcore.models import TaskPayload
from .roles import (
    Specialization,
    RoleProfile,
    RoleRegistry,
    DEFAULT_ROLE_REGISTRY,
    SkillVector,
    SkillStoreProtocol,
    RbacEnforcer,
    build_advertisement,
)
from .state import AgentState
from .private_memory import AgentPrivateMemory, PeerEvent

if TYPE_CHECKING:
    import numpy as np
    from seedcore.models.state import AgentSnapshot
    from seedcore.tools.manager import ToolManager
    from seedcore.serve.cognitive_client import CognitiveServiceClient
    from seedcore.serve.mcp_client import MCPServiceClient

# ---- Cognition / ML ------------------------------------------------------------

try:
    from seedcore.serve.ml_client import MLServiceClient  # your async client
    from seedcore.utils.ray_utils import ML  # ML service base URL
except Exception:  # pragma: no cover
    MLServiceClient = None  # type: ignore
    ML = "http://127.0.0.1:8000/ml"  # fallback

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.agents.base", level="DEBUG")

# Ray import for actor decorator
try:
    import ray  # pyright: ignore[reportMissingImports]
except ImportError:
    ray = None  # type: ignore

# Runtime numpy import (moved from inside methods for performance)
try:
    import numpy as np
except ImportError:
    np = None  # type: ignore

# Optimize dateutil import for _iso_to_ts
try:
    from dateutil import parser as dt_parser
except ImportError:
    dt_parser = None  # type: ignore


@ray.remote  # type: ignore
class BaseAgent:
    """
    Production-ready base agent.

    Responsibilities (LOCAL ONLY):
      - Holds identity & light state (capability, mem_util)
      - Manages specialization and skills; passes them to cognition/ML
      - Enforces RBAC for tool/data access
      - Computes salience (with ML + fallback) - LOCAL scoring only
      - Advertises capabilities for routing (passive advertisement, not routing decisions)
      - Executes tasks locally with tool calls
      - Returns local intents (not global escalation signals)

    Architectural Boundaries - BaseAgent MUST NOT:
      ❌ No global routing logic (routing decisions belong to meta-controller)
      ❌ No cognitive reasoning (delegates to CognitiveServiceClient)
      ❌ No cross-agent coordination (coordination belongs to meta-controller/HGNN)
      ❌ No recovery FSM (recovery orchestration belongs to meta-controller)
      ❌ No proactive planning (planning belongs to Cognitive Core/Organs)
      ❌ No policy engine (policy enforcement is RBAC-only, policy decisions are upstream)
      ❌ No knowledge graph writes (KG operations belong to Cognitive Core)
      ❌ No emergent behavior scaffolding (emergence belongs to HGNN)
      ❌ No role selection logic (role selection belongs to meta-controller)
      ❌ No democratized salience coordination (coordination belongs to meta-controller)

    BaseAgent is a LOCAL REFLEX LAYER:
      - Reacts to incoming tasks
      - Executes tool calls with RBAC
      - Computes local salience scores
      - Returns local intents for upstream interpretation
      - Self-regulates via lifecycle (degraded mode under load)

    Extend this class for organ-specific behaviors (GEA, PEA, etc.).
    """

    # Tunables
    REQUEST_TIMEOUT_S = 5.0
    MAX_TEXT_LEN = 4096
    MAX_IN_FLIGHT_SALIENCE = 20

    def __init__(
        self,
        agent_id: str,
        *,
        tool_manager: Optional["ToolManager"] = None,
        specialization: Specialization = Specialization.GENERALIST,
        role_registry: Optional[RoleRegistry] = None,
        skill_store: Optional[SkillStoreProtocol] = None,
        cognitive_client: Optional["CognitiveServiceClient"] = None,
        mcp_client: Optional["MCPServiceClient"] = None,
        initial_capability: float = 0.5,
        initial_mem_util: float = 0.0,
        organ_id: Optional[str] = None,
    ) -> None:
        # Identity
        self.agent_id = agent_id
        self.instance_id = uuid.uuid4().hex
        self.organ_id = organ_id or "_"

        # Role registry / profile
        self._role_registry: RoleRegistry = role_registry or DEFAULT_ROLE_REGISTRY
        self.specialization: Specialization = specialization
        self.role_profile: RoleProfile = self._role_registry.get(self.specialization)

        # Tool surface
        if tool_manager is None:
            logger.warning(
                "BaseAgent %s started without ToolManager; creating dedicated instance. "
                "Prefer injecting a shared ToolManager.",
                agent_id,
            )
            # Lazy import to avoid circular dependencies
            from seedcore.tools.manager import ToolManager as _ToolManager
            # Internal-only tools by default, no MCP unless explicitly supplied
            tool_manager = _ToolManager()
        self.tools: ToolManager = tool_manager

        # Store mcp_client separately for higher-level logic
        # Only inject MCP into ToolManager if explicitly provided (opt-in)
        self.mcp_client = mcp_client
        if mcp_client and getattr(tool_manager, "_mcp_client", None) is None:
            tool_manager._mcp_client = mcp_client
        
        # Inject cognitive_client into ToolManager if provided
        # cognitive_client is for Cognitive Service (LLM/reasoning), different from MCP
        # Note: self.cognitive_client is set later (line 228), but we inject it here for ToolManager
        if cognitive_client and getattr(tool_manager, "cognitive_client", None) is None:
            tool_manager.cognitive_client = cognitive_client

        # Skills (deltas) + optional persistence
        self.skills: SkillVector = SkillVector()
        if skill_store:
            self.skills.bind_store(skill_store)

        # Light state for cognition context & routing
        self.state: AgentState = AgentState(
            c=float(initial_capability),
            mem_util=float(initial_mem_util),
        )
        
        # Initialize state.p with role probabilities from RoleProfile
        # This ensures state.p exists for role smoothing in update_state()
        self.state.p = self.role_profile.to_p_dict()

        # --- State required by AgentSnapshot (theoretical state model) ---
        # h: The agent's internal state embedding (numpy array)
        # This is the "live" version of AgentSnapshot.h
        # NOTE: _get_current_embedding() prioritizes privmem.h, so this is a fallback/override
        if np is None:
            raise ImportError("numpy is required for BaseAgent")
        
        # Initialize h from state.h if available (for consistency)
        if hasattr(self.state, "h") and self.state.h:
            try:
                self.h = self._force_128d(np.asarray(self.state.h, dtype=np.float32))
            except Exception:
                self.h = np.zeros(128, dtype=np.float32)
        else:
            self.h = np.zeros(128, dtype=np.float32)
        
        # lifecycle: The agent's current status
        # This is the "live" version of AgentSnapshot.lifecycle
        self.lifecycle: str = "initializing"
        
        # load: Operational activity load (for RL signals, scheduling, resource allocation)
        # Incremented on task start, decremented on task completion
        # Protected against overflow and negative values
        self.load: float = 0.0
        self._load_max: float = 10000.0  # Fail-safe overflow protection
        
        # Role update throttling (to prevent destabilization from frequent role changes)
        self._last_role_update_time: float = 0.0
        self._role_update_min_interval: float = 5.0  # Minimum seconds between role updates
        self._role_smoothing_alpha: float = 0.3  # EMA smoothing factor for role changes

        # Agent-private vector memory (F/S/P blocks)
        self._privmem = AgentPrivateMemory(agent_id=self.agent_id, alpha=0.1)

        # RBAC
        self._rbac = RbacEnforcer()

        # Cognition / ML
        self.cognitive_client = cognitive_client
        self._ml_client = None
        self._ml_client_lock = asyncio.Lock()
        self._salience_sema = asyncio.Semaphore(self.MAX_IN_FLIGHT_SALIENCE)

        # Heartbeat tracking
        self.last_heartbeat: Optional[float] = None

        # Set lifecycle to active after initialization
        self.lifecycle = "active"
        
        logger.info(
            "✅ BaseAgent %s (%s) online. org=%s, mcp=%s",
            self.agent_id,
            self.specialization.value,
            self.organ_id,
            "yes" if mcp_client else "no",
        )

    # ============================================================================
    # State Snapshotting (Bridge to Theoretical State Model)
    # ============================================================================

    def _force_128d(self, arr) -> "np.ndarray":
        """
        Centralized helper to ensure numpy arrays are exactly 128-dimensional.
        Handles all shape edge cases: scalars, 1D, multi-dimensional, wrong sizes.
        """
        if np is None:
            raise ImportError("numpy is required")
        
        arr = np.asarray(arr, dtype=np.float32)
        
        # Handle scalar or 0-dim
        if arr.ndim == 0:
            arr = np.zeros(128, dtype=np.float32)
        # Handle multi-dimensional arrays (flatten first)
        elif arr.ndim > 1:
            arr = arr.flatten()
        
        # Now arr is guaranteed to be 1D
        if arr.size == 0:
            arr = np.zeros(128, dtype=np.float32)
        elif arr.size < 128:
            arr = np.pad(arr, (0, 128 - arr.size), mode='constant')
        elif arr.size > 128:
            arr = arr[:128]
        
        return arr.astype(np.float32, copy=False)

    async def _get_current_embedding(self) -> "np.ndarray":
        """
        Get the agent's current state embedding (h vector).
        
        Priority order:
        1. Use privmem.get_vector() if available (most up-to-date, includes task/skill/peer/feat blocks)
        2. Fall back to self.h (maintained separately for compatibility)
        
        This avoids duplication - privmem is the source of truth for the agent's
        internal state embedding, while self.h can be updated by the controller.
        """
        if np is None:
            raise ImportError("numpy is required")
        
        # Priority 1: Use privmem embedding if available (most comprehensive)
        if hasattr(self._privmem, "get_vector"):
            try:
                privmem_h = self._privmem.get_vector()
                if privmem_h is not None and privmem_h.size > 0:
                    return self._force_128d(privmem_h)
            except Exception:
                # Fall through to self.h if privmem fails
                pass
        
        # Priority 2: Fall back to self.h (can be updated by controller)
        self.h = self._force_128d(self.h)
        return self.h

    async def get_snapshot(self) -> "AgentSnapshot":
        """
        Gathers the agent's live state and formats it into the theoretical 
        AgentSnapshot dataclass. This is the "bridge" method that connects
        the production actor to the theoretical state model.
        
        Returns:
            AgentSnapshot: The agent's current state in the format expected
                          by UnifiedState and the energy calculator.
        """
        # Import here to avoid circular dependencies
        from seedcore.models.state import AgentSnapshot
        
        # 1. Get embedding (h)
        current_h = await self._get_current_embedding()
        
        # 2. Get role probabilities (p) - convert RoleProfile to E/S/O dict
        # Use centralized mapping from RoleRegistry if available
        if hasattr(self._role_registry, "specialization_to_p_dict"):
            p_dict = self._role_registry.specialization_to_p_dict(self.specialization)
        else:
            # Fallback to RoleProfile method
            p_dict = self.role_profile.to_p_dict()
        
        # 3. Get learned skills - convert SkillVector to simple dict
        skills_dict = self.skills.to_dict()
        
        # 4. Get mem_util (already in self.state.mem_util)
        # 5. Get capacity (c) - already in self.state.c
        # 6. Get lifecycle - already in self.lifecycle
        # 7. Get load - operational activity load
        # 8. Get timestamp - when this snapshot was taken
        
        # Assemble the snapshot
        return AgentSnapshot(
            h=current_h,
            p=p_dict,
            c=self.state.c,
            mem_util=self.state.mem_util,
            lifecycle=self.lifecycle,
            learned_skills=skills_dict,
            load=self.load,
            timestamp=time.time(),
        )

    async def update_state(
        self,
        new_h: Optional["np.ndarray"] = None,
        new_p_dict: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Receives updates from the system-level controller and updates the 
        agent's live state. This implements the "feedback loop" where the
        theoretical state model (s_{t+1}) is fed back into the production actor.
        
        Args:
            new_h: Optional new state embedding to update self.h
            new_p_dict: Optional new role probabilities dict (E/S/O) to update role_profile
        """
        if new_h is not None:
            # Update the agent's internal state embedding
            self.h = self._force_128d(new_h)
            # Also update AgentState.h for compatibility
            self.state.h = self.h.tolist()

        if new_p_dict is not None:
            # Throttle role updates to prevent destabilization
            current_time = time.time()
            time_since_last_update = current_time - self._last_role_update_time
            
            if time_since_last_update < self._role_update_min_interval:
                logger.debug(
                    f"Agent {self.agent_id} role update throttled "
                    f"(last update {time_since_last_update:.2f}s ago, min interval {self._role_update_min_interval}s)"
                )
                # Still update, but with smoothing
                should_smooth = True
            else:
                should_smooth = False
                self._last_role_update_time = current_time
            
            # Validate that it's a valid E/S/O dict
            from seedcore.models.state import ROLE_KEYS
            validated_p = {}
            for key in ROLE_KEYS:
                validated_p[key] = float(new_p_dict.get(key, 0.0))
            # Normalize to ensure it's a valid probability distribution
            total = sum(validated_p.values())
            if total > 0:
                validated_p = {k: v / total for k, v in validated_p.items()}
            else:
                # Default uniform distribution
                validated_p = {k: 1.0 / len(ROLE_KEYS) for k in ROLE_KEYS}
            
            # Apply smoothing if throttled (exponential moving average)
            if should_smooth and hasattr(self.state, 'p') and self.state.p:
                current_p = self.state.p.copy()
                # Smooth each role probability
                for key in ROLE_KEYS:
                    old_val = float(current_p.get(key, 1.0 / len(ROLE_KEYS)))
                    new_val = float(validated_p.get(key, 1.0 / len(ROLE_KEYS)))
                    # EMA: smoothed = alpha * new + (1 - alpha) * old
                    validated_p[key] = (
                        self._role_smoothing_alpha * new_val +
                        (1.0 - self._role_smoothing_alpha) * old_val
                    )
                    # Enforce minimum floor to prevent roles from vanishing
                    validated_p[key] = max(validated_p[key], 0.001)
                # Renormalize after smoothing
                total = sum(validated_p.values())
                if total > 0:
                    validated_p = {k: v / total for k, v in validated_p.items()}
            
            # Update AgentState.p for compatibility
            self.state.p = validated_p.copy()
            
            # Note: We don't change the specialization or role_profile here,
            # as that would require reconstructing the RoleProfile from the p_dict.
            # The role_profile remains tied to the specialization, but the
            # actual role probabilities used in calculations come from self.state.p.
            
        logger.debug(f"Agent {self.agent_id} state updated.")

    # ============================================================================
    # Heartbeat & Context
    # ============================================================================

    async def get_heartbeat(self) -> Dict[str, Any]:
        """
        Minimal async heartbeat used by feature extraction & health probes.
        Override if you have richer telemetry.
        
        **UPDATED**: Now includes 'learned_skills' for the StateService.
        """
        await asyncio.sleep(0)
        perf = self.state.to_performance_metrics()
        try:
            pm = self._privmem.telemetry()
        except Exception:
            pm = None
            
        # --- CRITICAL ADDITION ---
        # The StateService's aggregator *requires* this
        # to build the SystemSpecializationVector.
        agent_skills = self.skills.deltas if self.skills else {}
        # -------------------------

        return {
            "status": "healthy",
            "performance_metrics": perf,
            "private_memory": pm,
            "learned_skills": agent_skills,  # <-- ADDED
            "timestamp": time.time(),
        }

    def _role_context(self) -> Dict[str, Any]:
        """
        Canonical context dict passed to cognition/ML.
        Includes specialization, materialized skills, and basic KPIs.
        
        NOTE: This uses role_profile (static specialization-based) for RBAC/routing.
        For dynamic role probabilities updated by the controller, use self.state.p.
        The role_profile represents the agent's "long-term class" while state.p
        represents "short-term behavioral adaptation" from the system controller.
        """
        mat_skills = self.role_profile.materialize_skills(self.skills.deltas)
        pm = self.state.to_performance_metrics()
        try:
            pmt = self._privmem.telemetry()
            pm_summary = {
                "alloc": pmt["allocation"],
                "norms": pmt["blocks"],
                "peers_tracked": pmt["counters"]["peers_tracked"],
            }
        except Exception:
            pm_summary = None
        
        # Include both role_profile (for RBAC/routing) and state.p (for behavioral context)
        effective_p = self.state.p if hasattr(self.state, 'p') and self.state.p else self.role_profile.to_p_dict()
        
        return {
            "agent_id": self.agent_id,
            "organ_id": self.organ_id,
            "specialization": self.specialization.value,
            "skills": mat_skills,
            "capability": pm["capability_score_c"],
            "mem_util": pm["mem_util"],
            "routing_tags": sorted(self.role_profile.routing_tags),
            "safety": dict(self.role_profile.safety_policies),
            "role_probs": effective_p,  # Include dynamic role probabilities
            "privmem": pm_summary,
        }

    # ============================================================================
    # RBAC helpers
    # ============================================================================

    def authorize_tool(
        self,
        tool_name: str,
        *,
        cost_usd: Optional[float] = None,
        autonomy: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        """Convenience wrapper around RbacEnforcer."""
        return self._rbac.authorize_tool(
            self.role_profile,
            tool_name,
            cost_usd=cost_usd,
            autonomy=autonomy,
            context=context,
        )

    def authorize_scope(self, scope_name: str, *, mode: str = "read", context: Optional[Dict[str, Any]] = None):
        return self._rbac.authorize_scope(self.role_profile, scope_name, mode=mode, context=context)

    # ============================================================================
    # Routing advertisement
    # ============================================================================

    def advertise_capabilities(self) -> Dict[str, Any]:
        """
        Build a routing advertisement payload for the meta-controller.
        
        NOTE: This is PASSIVE advertisement only. BaseAgent does NOT make routing
        decisions - it only advertises its current capabilities. The meta-controller
        uses these advertisements to make routing decisions.
        """
        mat_skills = self.role_profile.materialize_skills(self.skills.deltas)
        ad = build_advertisement(
            agent_id=self.agent_id,
            role_profile=self.role_profile,
            specialization=self.specialization,
            materialized_skills=mat_skills,
            capability=float(self.state.c),
            mem_util=float(self.state.mem_util),
            capacity_hint=None,
            health="healthy",
            latency_ms=None,
            quality_avg=self.state.rolling_quality_avg(),
            region=None,
            zone=None,
        )
        return {
            "agent_id": ad.agent_id,
            "specialization": ad.specialization.value,
            "skills": ad.skills,
            "capability": ad.capability,
            "mem_util": ad.mem_util,
            "routing_tags": sorted(ad.routing_tags),
            "capacity_hint": ad.capacity_hint,
            "health": ad.health,
            "latency_ms": ad.latency_ms,
            "quality_avg": ad.quality_avg,
            "region": ad.region,
            "zone": ad.zone,
            "last_updated_ts": ad.last_updated_ts,
        }

    def _rolling_quality_avg(self) -> Optional[float]:
        """
        Compatibility shim for legacy callers; prefer AgentState.rolling_quality_avg().
        """
        return self.state.rolling_quality_avg()

    # ============================================================================
    # Salience scoring (async) with ML + fallback
    # ============================================================================

    async def _get_ml_client(self):
        """
        Async-safe lazy init of MLServiceClient.
        
        Uses the ML base URL derived from ray_utils (SERVE_GATEWAY + /ml),
        which is independent of the cognitive client (/cognitive).
        ML and Cognitive share the gateway but have different base paths.
        """
        if self._ml_client is not None or MLServiceClient is None:
            return self._ml_client
        async with self._ml_client_lock:
            if self._ml_client is None and MLServiceClient is not None:
                # ML and Cognitive share the gateway, but have different base paths.
                # ray_utils.ML already encodes SERVE_GATEWAY + ML base path.
                client = MLServiceClient(base_url=ML)
                # Handle async constructors (some HTTP clients use async __init__)
                if inspect.isawaitable(client):
                    client = await client
                self._ml_client = client
        return self._ml_client

    async def _extract_salience_features(self, task_info: Dict[str, Any], error_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract features for salience scoring (non-blocking; resilient).
        """
        performance_metrics = {}
        try:
            hb = await asyncio.wait_for(self.get_heartbeat(), timeout=1.0)
            if isinstance(hb, dict):
                performance_metrics = hb.get("performance_metrics", {}) or {}
        except asyncio.TimeoutError:
            logger.warning("[%s] Heartbeat timeout; using defaults.", self.agent_id)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("[%s] Heartbeat error; defaults. %s", self.agent_id, e)

        # Agent-local metrics (not system-wide)
        agent_load = self._get_agent_load_estimate()
        agent_memory_usage = self._get_agent_memory_usage()
        agent_cpu_usage = self._get_agent_cpu_usage()
        agent_response_time = self._get_agent_response_time()
        agent_error_rate = self._get_agent_error_rate()

        # Extract risk value: prefer risk_score (canonical) then risk (fallback)
        risk_val = task_info.get("risk_score")
        if risk_val is None:
            risk_val = task_info.get("risk", 0.5)
        
        features = {
            # Task-related
            "task_risk": float(risk_val),
            "failure_severity": 1.0,
            "task_complexity": float(task_info.get("complexity", 0.5)),
            "user_impact": float(task_info.get("user_impact", 0.5)),
            "business_criticality": float(task_info.get("business_criticality", 0.5)),
            # Agent-related
            "agent_capability": float(performance_metrics.get("capability_score_c", self.state.c)),
            "agent_memory_util": float(performance_metrics.get("mem_util", self.state.mem_util)),
            # Agent-local metrics (renamed from system metrics)
            "agent_load": float(agent_load),
            "agent_memory_usage": float(agent_memory_usage),
            "agent_cpu_usage": float(agent_cpu_usage),
            "agent_response_time": float(agent_response_time),
            "agent_error_rate": float(agent_error_rate),
            # Error context
            "error_code": int(error_context.get("code", 500)),
            "error_type": self._classify_error_type(error_context.get("reason", "")),
        }
        return features

    async def _calculate_ml_salience_score(self, task_info: Dict[str, Any], error_context: Dict[str, Any]) -> float:
        """
        Compute salience using ML service with a robust fallback.
        """
        features = None
        async with self._salience_sema:
            try:
                features = await self._extract_salience_features(task_info, error_context)

                text_to_score = (error_context.get("reason") or "High-stakes task failure")[: self.MAX_TEXT_LEN]
                
                # Trim context to essentials (avoid sending large skill vectors, blocks, norms, peers, etc.)
                light_ctx = {
                    "agent_capability": features.get("agent_capability", self.state.c),
                    "mem_util": features.get("agent_memory_util", self.state.mem_util),
                    "role": self.specialization.value,
                }
                
                # Add task_embed_norm if available
                task_embed = task_info.get("task_embed")
                if task_embed is not None and np is not None:
                    try:
                        embed_arr = np.asarray(task_embed, dtype=np.float32)
                        task_embed_norm = float(np.linalg.norm(embed_arr))
                        light_ctx["task_embed_norm"] = task_embed_norm
                    except Exception:
                        light_ctx["task_embed_norm"] = 0.0
                else:
                    light_ctx["task_embed_norm"] = 0.0
                
                context_data = {**features, **light_ctx}

                client = await self._get_ml_client()
                if client is None:
                    raise RuntimeError("MLServiceClient unavailable")

                response = await asyncio.wait_for(
                    client.compute_salience_score(text=text_to_score, context=context_data),
                    timeout=self.REQUEST_TIMEOUT_S,
                )

                score = None
                if isinstance(response, dict):
                    score = response.get("score")
                    if score is None:
                        r = response.get("result")
                        if isinstance(r, dict):
                            score = r.get("score")
                if isinstance(score, (int, float)):
                    s = float(score)
                    if not (0.0 <= s <= 1.0):
                        logger.warning("[%s] Out-of-range salience %.3f; clamping.", self.agent_id, s)
                        s = max(0.0, min(1.0, s))
                    return s

                logger.warning("[%s] Invalid ML response; using fallback. type=%s", self.agent_id, type(response))

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("[%s] ML salience error: %s. Fallback.", self.agent_id, e, exc_info=True)

        # Fallback path (run directly, no executor needed - already protected by semaphore)
        if features is None:
            try:
                features = await self._extract_salience_features(task_info, error_context)
            except Exception:
                features = {}
        try:
            val = self._fallback_salience_scorer([features])[0]
            return max(0.0, min(1.0, float(val)))
        except Exception as e:
            logger.error("[%s] Fallback scorer failed: %s. Default=0.5", self.agent_id, e)
            return 0.5

    # ============================================================================
    # Generic task execution (routing-aware, RBAC-enforced)
    # ============================================================================

    async def execute_task(self, task) -> Dict[str, Any]:
        """
        Normalize inbound task payloads and orchestrate tool execution with RBAC.
        """
        started_ts = self._utc_now_iso()
        started_monotonic = self._now_monotonic()

        tv = self._coerce_task_view(task)

        # --- 0) Fast guardrails --------------------------------------------------
        if tv.required_specialization:
            my_spec = getattr(self.specialization, "value", self.specialization)
            if str(my_spec) != str(tv.required_specialization):
                raise ValueError(
                    f"Agent {self.agent_id} specialization {my_spec} != task requirement {tv.required_specialization}"
                )

        if tv.min_capability is not None:
            if float(getattr(self.state, "capability_score", getattr(self.state, "c", 0.0))) < float(tv.min_capability):
                return self._reject_result(
                    tv,
                    reason=f"capability<{tv.min_capability}",
                    started_ts=started_ts,
                    started_monotonic=started_monotonic,
                )

        if tv.max_mem_util is not None:
            if float(getattr(self.state, "mem_util", 0.0)) > float(tv.max_mem_util):
                return self._reject_result(
                    tv,
                    reason=f"mem_util>{tv.max_mem_util}",
                    started_ts=started_ts,
                    started_monotonic=started_monotonic,
                )

        if tv.deadline_at_iso and self._is_past_iso(tv.deadline_at_iso):
            return self._reject_result(
                tv,
                reason="deadline_expired",
                started_ts=started_ts,
                started_monotonic=started_monotonic,
            )

        if tv.ttl_seconds is not None and tv.created_at_ts:
            if self._now_ts() - tv.created_at_ts > tv.ttl_seconds:
                return self._reject_result(
                    tv,
                    reason="ttl_expired",
                    started_ts=started_ts,
                    started_monotonic=started_monotonic,
                )

        # --- 1) Skill materialization (telemetry only) ---------------------------
        try:
            mat_skills = self.role_profile.materialize_skills(getattr(self.skills, "deltas", {}))
        except Exception:
            mat_skills = {}
        skill_fit = self._score_skill_match(mat_skills, tv.desired_skills)

        # --- 2) Tool execution ---------------------------------------------------
        # Increment load counter (for activity tracking)
        self.load = min(self.load + 1.0, self._load_max)
        
        results: List[Dict[str, Any]] = []
        tool_errors: List[Dict[str, Any]] = []

        default_tool_timeout_s = float(getattr(self, "default_tool_timeout_s", 20.0))
        tool_manager = getattr(self, "tools", None)

        for call in tv.tool_calls:
            tool_name = call.get("name")
            if not tool_name:
                tool_errors.append({"tool": "?", "error": "invalid_tool_entry"})
                continue

            # (a) RBAC
            try:
                decision = self.authorize_tool(
                    tool_name,
                    cost_usd=0.0,
                    context={"task_id": tv.task_id, "agent_id": self.agent_id},
                )
                if not decision.allowed:
                    tool_errors.append({"tool": tool_name, "error": f"rbac_denied:{decision.reason or 'policy_block'}"})
                    continue
            except Exception as exc:
                tool_errors.append({"tool": tool_name, "error": f"rbac_error:{exc}"})
                continue

            # (b) Tool availability
            if not tool_manager:
                tool_errors.append({"tool": tool_name, "error": "tool_manager_missing"})
                continue

            has_attr = getattr(tool_manager, "has", None)
            if not callable(has_attr):
                tool_errors.append({"tool": tool_name, "error": "tool_manager_missing"})
                continue

            try:
                has_result = has_attr(tool_name)
                if inspect.isawaitable(has_result):
                    has_result = await has_result
                if not has_result:
                    tool_errors.append({"tool": tool_name, "error": "tool_missing"})
                    continue
            except Exception as exc:
                tool_errors.append({"tool": tool_name, "error": f"tool_has_error:{exc}"})
                continue

            # (c) Execution with timeout
            args = dict(call.get("args") or {})
            tool_timeout = float(args.pop("_timeout_s", default_tool_timeout_s))
            try:
                output = await asyncio.wait_for(tool_manager.execute(tool_name, args), timeout=tool_timeout)
                # Ensure output is JSON-serializable (handle numpy arrays, etc.)
                output = self._make_json_safe(output)
                results.append({"tool": tool_name, "ok": True, "output": output})
            except asyncio.TimeoutError:
                tool_errors.append({"tool": tool_name, "error": "timeout"})
            except asyncio.CancelledError:
                tool_errors.append({"tool": tool_name, "error": "cancelled"})
                raise
            except Exception as exc:
                tool_errors.append({"tool": tool_name, "error": str(exc)})

            self.last_heartbeat = time.time()

        # --- 3) Quality & salience ------------------------------------------------
        success = len(tool_errors) == 0
        quality = self._estimate_quality(results, tool_errors, tv)
        salience = await self._maybe_salience(tv, results, tool_errors)

        # --- 4) State & memory updates -------------------------------------------
        try:
            self.state.record_task_outcome(
                success=success,
                quality=quality,
                salience=salience,
                duration_s=self._elapsed_ms(started_monotonic) / 1000.0,
                capability_observed=None,
            )
        except Exception:
            pass

        try:
            task_embed = tv.embedding if tv.embedding is not None else None
            self.update_private_memory(
                task_embed=task_embed,
                peers=None,
                success=success,
                quality=quality,
                latency_s=self._elapsed_ms(started_monotonic) / 1000.0,
                energy=None,
                delta_e=None,
            )
        except Exception:
            pass

        # Decrement load counter (task completed)
        # Protected against negative and overflow
        self.load = max(0.0, min(self.load - 1.0, self._load_max))
        # Fail-safe: reset if somehow overflowed
        if self.load > self._load_max:
            logger.warning(f"Agent {self.agent_id} load overflow detected, resetting")
            self.load = 0.0
        
        # --- 5) Result envelope ---------------------------------------------------
        result = {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "specialization": getattr(self.specialization, "value", self.specialization),
            "skill_fit": skill_fit,
            "success": success,
            "results": results,
            "errors": tool_errors,
            "quality": quality,
            "salience": salience,
            "meta": {
                "exec": {
                    "started_at": started_ts,
                    "finished_at": self._utc_now_iso(),
                    "latency_ms": self._elapsed_ms(started_monotonic),
                    "attempt": 1,
                },
                "routing_hints": {
                    "min_capability": tv.min_capability,
                    "max_mem_util": tv.max_mem_util,
                    "priority": tv.priority,
                    "deadline_at": tv.deadline_at_iso,
                    "ttl_seconds": tv.ttl_seconds,
                },
            },
        }

        return result

    def _estimate_quality(self, results, errors, _task_view) -> float:
        """Baseline quality estimate based on tool success ratio."""
        n = len(results) + len(errors)
        if n == 0:
            # No tool calls means no failures occurred - quality is perfect
            return 1.0
        return max(0.0, min(1.0, len(results) / n))

    async def _maybe_salience(self, tv, results, errors) -> float:
        """
        Optional salience scoring via ML service.
        
        NOTE: Salience is only computed for active agents. Suspended/degraded
        agents should not escalate tasks.
        """
        # Only compute salience for active agents
        if self.lifecycle != "active":
            logger.debug(f"Agent {self.agent_id} lifecycle={self.lifecycle}, skipping salience")
            return 0.0
        
        # Skip salience for rejected tasks (no tool calls executed)
        if not results and not errors:
            logger.debug(f"Agent {self.agent_id} no tool calls executed, skipping salience")
            return 0.0
        
        try:
            # Extract real error reason from first error if available
            if errors:
                first_error = errors[0]
                reason = first_error.get("error", "unknown")
                # Map common error patterns to semantic reasons
                if "timeout" in str(reason).lower():
                    reason = "timeout"
                elif "rbac" in str(reason).lower() or "permission" in str(reason).lower():
                    reason = "authorization_failure"
                elif "validation" in str(reason).lower():
                    reason = "validation_error"
                else:
                    reason = str(reason)
            else:
                reason = "ok"
            
            # Infer risk metadata from task context
            risk = 1.0 if errors else 0.2
            complexity = min(1.0, len(tv.tool_calls) / 5.0) if tv.tool_calls else 0.0
            business_criticality = 1.0 if tv.priority > 5 else 0.3
            user_impact = min(1.0, tv.priority / 10.0) if tv.priority else 0.5
            
            # Build comprehensive task_info
            task_info = {
                "task": tv.task_id,
                "prompt": tv.prompt,
                "risk": risk,
                "complexity": complexity,
                "business_criticality": business_criticality,
                "user_impact": user_impact,
                "task_embed": tv.embedding,  # Include embedding for task_embed_norm calculation
            }
            
            # Build error_context with semantic reason
            error_context = {
                "reason": reason,
                "code": self._map_reason_to_code(reason),
            }
            
            salience = await self._calculate_ml_salience_score(task_info, error_context)
            
            # Load shedding: degrade lifecycle when overloaded
            if salience > 0.85 and self.load > 5:
                logger.warning(
                    f"Agent {self.agent_id} high salience ({salience:.2f}) and high load ({self.load:.1f}), "
                    "entering degraded mode"
                )
                self.lifecycle = "degraded"
            
            return salience
        except Exception:
            return 0.0

    def _reject_result(self, tv, reason: str, *, started_ts: str, started_monotonic: float) -> Dict[str, Any]:
        """Return a structured rejection envelope."""
        return {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "specialization": getattr(self.specialization, "value", self.specialization),
            "success": False,
            "results": [],
            "errors": [{"error": reason}],
            "quality": 0.0,
            "salience": 0.0,
            "meta": {
                "exec": {
                    "started_at": started_ts,
                    "finished_at": self._utc_now_iso(),
                    "latency_ms": self._elapsed_ms(started_monotonic),
                    "attempt": 1,
                },
                "reject_reason": reason,
            },
        }

    def _score_skill_match(self, materialized: Dict[str, float], desired: Dict[str, float]) -> float:
        """Cosine-like similarity between desired and materialized skills."""
        if not desired:
            return 0.0
        keys = [k for k in desired.keys() if k in materialized]
        if not keys:
            return 0.0
        a = [float(materialized[k]) for k in keys]
        b = [float(desired[k]) for k in keys]
        numerator = sum(x * y for x, y in zip(a, b))
        denominator = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5) or 1.0
        return max(0.0, min(1.0, numerator / denominator))
    
    def _normalize_task_payload(
        self, task: Union[TaskPayload, Dict[str, Any], Any]
    ) -> Tuple[TaskPayload, Dict[str, Any]]:
        """
        Normalize incoming task representations to TaskPayload while preserving original fields.
        Returns the TaskPayload and a merged dict that includes any extra keys from the input.
        """
        raw_dict: Dict[str, Any]
        payload: TaskPayload

        if isinstance(task, TaskPayload):
            payload = task
            raw_dict = task.model_dump()
        else:
            if hasattr(task, "model_dump"):
                try:
                    raw_dict = task.model_dump()
                except Exception:
                    raw_dict = {}
            elif hasattr(task, "to_dict"):
                try:
                    raw_dict = task.to_dict()
                except Exception:
                    raw_dict = {}
            elif isinstance(task, dict):
                raw_dict = dict(task)
            else:
                try:
                    raw_dict = dict(task)
                except Exception:
                    raw_dict = {}

            try:
                payload = TaskPayload.from_db(raw_dict)
            except Exception:
                fallback_id = raw_dict.get("task_id") or raw_dict.get("id") or uuid.uuid4().hex
                tool_calls_raw = raw_dict.get("tool_calls") or []
                payload = TaskPayload(
                    task_id=str(fallback_id),
                    type=raw_dict.get("type") or raw_dict.get("task_type") or "unknown_task",
                    params=raw_dict.get("params") or {},
                    description=raw_dict.get("description") or raw_dict.get("prompt") or "",
                    domain=raw_dict.get("domain"),
                    drift_score=float(raw_dict.get("drift_score") or 0.0),
                    required_specialization=raw_dict.get("required_specialization"),
                    desired_skills=raw_dict.get("desired_skills") or {},
                    tool_calls=tool_calls_raw,
                    min_capability=raw_dict.get("min_capability"),
                    max_mem_util=raw_dict.get("max_mem_util"),
                    priority=int(raw_dict.get("priority") or 0),
                    deadline_at=raw_dict.get("deadline_at"),
                    ttl_seconds=raw_dict.get("ttl_seconds"),
                )

        if not payload.task_id or payload.task_id in ("", "None"):
            payload = payload.copy(update={"task_id": uuid.uuid4().hex})

        normalized_dict = payload.model_dump()
        merged_dict = dict(raw_dict)

        normalized_params = dict(normalized_dict.get("params") or {})
        raw_params = dict(merged_dict.get("params") or {})
        if normalized_params:
            routing = normalized_params.get("routing")
            if routing is not None:
                raw_params["routing"] = routing
            for key, value in normalized_params.items():
                if key == "routing":
                    continue
                raw_params.setdefault(key, value)
            merged_dict["params"] = raw_params

        for key, value in normalized_dict.items():
            if key == "params":
                continue
            if key not in merged_dict or merged_dict[key] in (None, "", {}):
                merged_dict[key] = value

        merged_dict["task_id"] = payload.task_id
        merged_dict.setdefault("id", payload.task_id)

        return payload, merged_dict

    class _TaskView:
        """Lightweight normalized task representation."""

        __slots__ = (
            "task_id",
            "prompt",
            "embedding",
            "required_specialization",
            "desired_skills",
            "tool_calls",
            "min_capability",
            "max_mem_util",
            "priority",
            "deadline_at_iso",
            "ttl_seconds",
            "created_at_ts",
        )

    def _coerce_task_view(self, task) -> "_TaskView":
        """Normalize Task/TaskPayload/dict inputs into a TaskView."""
        payload, merged = self._normalize_task_payload(task)
        tv = self._TaskView()

        tv.task_id = payload.task_id
        tv.prompt = payload.description or merged.get("prompt") or ""

        meta = merged.get("meta") or {}
        tv.embedding = meta.get("embedding")

        params = merged.get("params") or {}
        routing = params.get("routing") or {}

        tv.required_specialization = payload.required_specialization or routing.get("required_specialization")
        tv.desired_skills = dict(payload.desired_skills or {}) or routing.get("desired_skills") or {}

        tool_calls: List[Dict[str, Any]] = []
        for item in payload.tool_calls or []:
            if isinstance(item, dict):
                name = item.get("name")
                if not name:
                    continue
                tool_calls.append({"name": name, "args": dict(item.get("args") or {})})
            else:
                name = getattr(item, "name", None)
                if not name:
                    continue
                tool_calls.append({"name": name, "args": dict(getattr(item, "args", {}) or {})})
        tv.tool_calls = tool_calls

        hints = routing.get("hints") or {}
        tv.min_capability = payload.min_capability if payload.min_capability is not None else hints.get("min_capability")
        tv.max_mem_util = payload.max_mem_util if payload.max_mem_util is not None else hints.get("max_mem_util")
        tv.priority = int(payload.priority or hints.get("priority", 0) or 0)
        tv.deadline_at_iso = payload.deadline_at or hints.get("deadline_at")
        tv.ttl_seconds = payload.ttl_seconds if payload.ttl_seconds is not None else hints.get("ttl_seconds")

        created_at = merged.get("created_at")
        tv.created_at_ts = None
        try:
            if isinstance(created_at, str):
                tv.created_at_ts = self._iso_to_ts(created_at)
            elif isinstance(created_at, (time.struct_time,)):
                # Handle time.struct_time
                from datetime import datetime
                tv.created_at_ts = datetime.fromtimestamp(time.mktime(created_at)).timestamp()
            elif hasattr(created_at, "timestamp") and callable(getattr(created_at, "timestamp", None)):
                # Only datetime/date objects have timestamp() method
                from datetime import datetime, date
                if isinstance(created_at, (datetime, date)):
                    ts_method = getattr(created_at, "timestamp", None)
                    if callable(ts_method):
                        tv.created_at_ts = ts_method()
        except Exception:
            tv.created_at_ts = None

        return tv

    def _make_json_safe(self, obj: Any) -> Any:
        """
        Convert non-serializable objects (numpy arrays, etc.) to JSON-safe primitives.
        This prevents serialization errors when tool outputs contain numpy arrays or other
        non-standard types.
        
        Blacklists internal attributes that may contain unserializable objects (coroutines,
        locks, Ray refs, etc.).
        """
        if np is not None:
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, np.generic):
                return obj.item()
            elif isinstance(obj, (np.integer, np.floating)):
                return float(obj)
        
        if isinstance(obj, dict):
            return {k: self._make_json_safe(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._make_json_safe(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            # Blacklist internal attributes that may be unserializable
            blacklist = {
                '__weakref__', '__slots__', '_rbac', '_privmem', '_ml_client',
                '_ml_client_lock', '_salience_sema', '_role_registry', 'tools'
            }
            # Only serialize public attributes (not starting with _)
            safe_dict = {}
            for key, value in obj.__dict__.items():
                if key not in blacklist and not (key.startswith('_') and key not in {'_ToolManager'}):
                    try:
                        safe_dict[key] = self._make_json_safe(value)
                    except Exception:
                        # Skip attributes that can't be serialized
                        continue
            return safe_dict if safe_dict else str(obj)
        else:
            # For primitives (str, int, float, bool, None), return as-is
            return obj

    def _now_monotonic(self) -> float:
        return time.perf_counter()

    def _elapsed_ms(self, start_mono: float) -> int:
        return int((time.perf_counter() - start_mono) * 1000)

    def _now_ts(self) -> float:
        return time.time()

    def _utc_now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _iso_to_ts(self, iso: str) -> Optional[float]:
        """
        Convert ISO format string to timestamp.
        Uses dateutil parser if available, falls back to datetime.fromisoformat.
        """
        if dt_parser is not None:
            try:
                return dt_parser.isoparse(iso).timestamp()
            except Exception:
                pass
        
        # Fallback to datetime.fromisoformat
        try:
            from datetime import datetime
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    def _is_past_iso(self, iso: str) -> bool:
        ts = self._iso_to_ts(iso)
        return ts is not None and ts < self._now_ts()

    # ============================================================================
    # Example task flow (async) showing salience-aware behavior
    # ============================================================================

    async def execute_high_stakes_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Demonstration of a salience-aware task lifecycle.
        Replace with your organ-specific behavior.
        """
        error_context = task_info.get("error_context") or {}
        salience = await self._calculate_ml_salience_score(task_info, error_context)

        task_embed = task_info.get("embedding")
        if isinstance(task_embed, list):
            try:
                if np is None:
                    task_embed = None
                else:
                    task_embed = np.asarray(task_embed, dtype=np.float32)
            except Exception:
                task_embed = None

        peers_raw = task_info.get("peers")
        peers = None
        if isinstance(peers_raw, list):
            peers = []
            for x in peers_raw:
                try:
                    peers.append(
                        PeerEvent(
                            peer_id=str(x.get("peer_id")),
                            outcome=int(x.get("outcome", 0)),
                            weight=float(x.get("weight", 1.0)),
                            role=x.get("role"),
                        )
                    )
                except Exception:
                    continue
            if not peers:
                peers = None

        try:
            self.update_private_memory(
                task_embed=task_embed,
                peers=peers,
                success=task_info.get("success", True),
                quality=task_info.get("quality"),
                latency_s=task_info.get("latency_s"),
            )
        except Exception:
            pass

        decision = self._decide_next_action(task_info, salience)

        # Update light KPIs
        self.state.tasks_processed += 1
        self.state.record_salience(salience)

        return {
            "agent_id": self.agent_id,
            "specialization": self.specialization.value,
            "salience": salience,
            "decision": decision,
            "h": self.get_private_vector(),
        }

    # ============================================================================
    # Decision stub (replace with real policy)
    # ============================================================================

    def _decide_next_action(self, task_info: Dict[str, Any], salience: float) -> str:
        """
        Decide next action based on salience score.
        Returns local intents only (not global escalation signals).
        The meta-controller will interpret these local intents.
        """
        if salience >= 0.85:
            return "local_flag_high_risk"
        if salience >= 0.6:
            return "local_retry"
        return "local_soft_fail"

    # ============================================================================
    # Agent-local metric stubs (override with real probes)
    # These reflect local agent state, not system-wide metrics
    # ============================================================================

    def _get_agent_load_estimate(self) -> float:
        """Agent-local load estimate (based on self.load)."""
        return min(1.0, self.load / 10.0)  # Normalize load to [0, 1]

    def _get_agent_memory_usage(self) -> float:
        """Agent-local memory usage."""
        return float(self.state.mem_util)

    def _get_agent_cpu_usage(self) -> float:
        """Agent-local CPU usage estimate (stub)."""
        return 0.2

    def _get_agent_response_time(self) -> float:
        """Agent-local response time estimate (stub)."""
        return 0.05  # seconds

    def _get_agent_error_rate(self) -> float:
        """Agent-local error rate estimate (stub)."""
        return 0.01

    # ============================================================================
    # Utility: error classification & fallback
    # ============================================================================

    def _classify_error_type(self, reason: str) -> str:
        if not reason:
            return "unknown"
        r = reason.lower()
        if "timeout" in r:
            return "timeout"
        if "permission" in r or "forbidden" in r or "unauthorized" in r:
            return "authorization"
        if "network" in r or "connection" in r:
            return "network"
        if "validation" in r or "schema" in r or "not found" in r:
            return "validation"
        return "runtime"

    def _map_reason_to_code(self, reason: str) -> int:
        """
        Map semantic error reason to HTTP-style error code.
        Used for ML salience scoring context.
        """
        if not reason or reason == "ok":
            return 200
        r = reason.lower()
        if "timeout" in r:
            return 504
        if "authorization" in r or "permission" in r or "forbidden" in r or "unauthorized" in r:
            return 403
        if "validation" in r or "schema" in r or "not found" in r:
            return 400
        if "network" in r or "connection" in r:
            return 503
        return 500

    # ============================================================================
    # Compatibility shims for legacy state access
    # ============================================================================

    @property
    def capability(self) -> float:
        return float(self.state.c)

    @capability.setter
    def capability(self, x: float) -> None:
        self.state.update_capability(x)

    @property
    def mem_util(self) -> float:
        return float(self.state.mem_util)

    @mem_util.setter
    def mem_util(self, x: float) -> None:
        self.state.update_mem_util(x)

    # --------------------------- private memory ---------------------------------

    def get_private_vector(self) -> list[float]:
        """Return the 128-d private memory vector as a list."""
        return self._privmem.get_vector_list()

    def update_private_memory(
        self,
        *,
        task_embed: Optional["np.ndarray"],
        peers: Optional[list[PeerEvent]] = None,
        success: bool = True,
        quality: Optional[float] = None,
        latency_s: Optional[float] = None,
    ) -> None:
        """
        One-shot update after a task completes. Delegates to AgentPrivateMemory.
        """
        self._privmem.update_from_agent(
            self,
            task_embed=task_embed,
            peers=peers,
            success=success,
            quality=quality,
            latency_s=latency_s,
        )

    def _fallback_salience_scorer(self, feature_batches: list[dict]) -> list[float]:
        """
        Deterministic local scorer for resilience. Replace with your heuristic/XGBoost.
        Very simple baseline: weighted sum of a few risk features, clamped to [0,1].
        
        Includes agent capability: low-capability agents produce higher salience scores
        (which may result in local_flag_high_risk intents, but BaseAgent does not escalate).
        Also includes privmem allocation as a weak signal of memory saturation.
        """
        out: list[float] = []
        for f in feature_batches:
            risk = float(f.get("task_risk", 0.5))
            sev = float(f.get("failure_severity", 1.0))
            imp = float(f.get("user_impact", 0.5))
            crit = float(f.get("business_criticality", 0.5))
            agent_load = float(f.get("agent_load", 0.0))
            agent_error_rate = float(f.get("agent_error_rate", 0.0))
            sys = 0.25 * agent_load + 0.25 * agent_error_rate
            
            # Factor in agent capability: low capability increases salience score
            # (higher salience may lead to local_flag_high_risk intent, but BaseAgent does not escalate)
            agent_capability = float(f.get("agent_capability", self.state.c))
            capability_penalty = 0.1 * (1.0 - agent_capability)  # 0.0 to 0.1
            
            # Add privmem allocation signal (weak signal for memory saturation)
            try:
                privmem_norm = self._privmem.telemetry().get("allocation") or 0.0
            except Exception:
                privmem_norm = 0.0
            
            score = 0.30 * risk + 0.25 * sev + 0.2 * imp + 0.15 * crit + 0.05 * sys + capability_penalty + 0.05 * privmem_norm
            score = max(0.0, min(1.0, score))
            out.append(score)
        return out
