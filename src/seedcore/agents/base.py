# src/seedcore/agents/base.py
"""
Base Agent abstraction.

This class wires together:
- Specialization & skills (seedcore.agents.roles.*)
- RBAC enforcement (tools & data scopes)
- Salience scoring via MLServiceClient (seedcore.serve.ml_client)
- Routing advertisement for the meta-controller
- Minimal heartbeat & system metrics
- Example async task handler showing salience-aware flow

Replace stubs (_get_system_load, _fallback_salience_scorer, etc.) with real probes/heuristics.
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

if TYPE_CHECKING:
    from seedcore.tools.manager import ToolManager
from .private_memory import AgentPrivateMemory, PeerEvent

if TYPE_CHECKING:
    import numpy as np

# ---- Cognition / ML ------------------------------------------------------------

try:
    from seedcore.serve.ml_client import MLServiceClient  # your async client
except Exception:  # pragma: no cover
    MLServiceClient = None  # type: ignore

from seedcore.logging_setup import ensure_serve_logger

logger = ensure_serve_logger("seedcore.agents.base", level="DEBUG")

# Ray import for actor decorator
try:
    import ray  # pyright: ignore[reportMissingImports]
except ImportError:
    ray = None  # type: ignore


@ray.remote  # type: ignore
class BaseAgent:
    """
    Production-ready base agent.

    Responsibilities:
      - Holds identity & light state (capability, mem_util)
      - Manages specialization and skills; passes them to cognition/ML
      - Enforces RBAC for tool/data access
      - Computes salience (with ML + fallback)
      - Advertises capabilities for routing

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
        cognitive_base_url: Optional[str] = None,
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
        from seedcore.tools.manager import ToolManager  # local import to avoid cycles

        if tool_manager is None:
            logger.warning(
                "BaseAgent %s started without ToolManager; creating dedicated instance. "
                "Prefer injecting a shared ToolManager.",
                agent_id,
            )
        self.tools: ToolManager = tool_manager or ToolManager()

        # Skills (deltas) + optional persistence
        self.skills: SkillVector = SkillVector()
        if skill_store:
            self.skills.bind_store(skill_store)

        # Light state for cognition context & routing
        self.state: AgentState = AgentState(
            c=float(initial_capability),
            mem_util=float(initial_mem_util),
        )

        # Agent-private vector memory (F/S/P blocks)
        self._privmem = AgentPrivateMemory(agent_id=self.agent_id, alpha=0.1)

        # RBAC
        self._rbac = RbacEnforcer()

        # Cognition / ML
        self._cog_base_url = cognitive_base_url
        self._ml_client = None
        self._ml_client_lock = asyncio.Lock()
        self._salience_sema = asyncio.Semaphore(self.MAX_IN_FLIGHT_SALIENCE)

        logger.info(
            "✅ BaseAgent %s (%s) online. org=%s",
            self.agent_id,
            self.specialization.value,
            self.organ_id,
        )

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
        return {
            "agent_id": self.agent_id,
            "organ_id": self.organ_id,
            "specialization": self.specialization.value,
            "skills": mat_skills,
            "capability": pm["capability_score_c"],
            "mem_util": pm["mem_util"],
            "routing_tags": sorted(self.role_profile.routing_tags),
            "safety": dict(self.role_profile.safety_policies),
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
        Async-safe lazy init of MLServiceClient. You can inject or subclass to customize.
        """
        if self._ml_client is not None or MLServiceClient is None:
            return self._ml_client
        async with self._ml_client_lock:
            if self._ml_client is None and MLServiceClient is not None:
                self._ml_client = MLServiceClient(base_url=self._cog_base_url)
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

        system_load = self._get_system_load()
        memory_usage = self._get_memory_usage()
        cpu_usage = self._get_cpu_usage()
        response_time = self._get_response_time()
        error_rate = self._get_error_rate()

        features = {
            # Task-related
            "task_risk": float(task_info.get("risk", 0.5)),
            "failure_severity": 1.0,
            "task_complexity": float(task_info.get("complexity", 0.5)),
            "user_impact": float(task_info.get("user_impact", 0.5)),
            "business_criticality": float(task_info.get("business_criticality", 0.5)),
            # Agent-related
            "agent_capability": float(performance_metrics.get("capability_score_c", self.state.c)),
            "agent_memory_util": float(performance_metrics.get("mem_util", self.state.mem_util)),
            # System-related
            "system_load": float(system_load),
            "memory_usage": float(memory_usage),
            "cpu_usage": float(cpu_usage),
            "response_time": float(response_time),
            "error_rate": float(error_rate),
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
                role_ctx = self._role_context()
                context_data = {**features, **role_ctx}

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

        # Fallback path
        if features is None:
            try:
                features = await self._extract_salience_features(task_info, error_context)
            except Exception:
                features = {}
        loop = asyncio.get_running_loop()
        try:
            val = await loop.run_in_executor(None, lambda: self._fallback_salience_scorer([features])[0])
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
            return 0.0
        return max(0.0, min(1.0, len(results) / n))

    async def _maybe_salience(self, tv, results, errors) -> float:
        """Optional salience scoring via ML service."""
        try:
            ctx_reason = "task_error" if errors else "task_ok"
            return await self._calculate_ml_salience_score(
                task_info={"task": tv.task_id, "prompt": tv.prompt},
                error_context={"reason": ctx_reason, "detail": str(errors[:1])},
            )
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
            elif created_at:
                ts_method = getattr(created_at, "timestamp", None)
                if callable(ts_method):
                    tv.created_at_ts = ts_method()
        except Exception:
            tv.created_at_ts = None

        return tv

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
        try:
            from datetime import datetime
            from dateutil import parser

            return parser.isoparse(iso).timestamp()
        except Exception:
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
                import numpy as np

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
        if salience >= 0.85:
            return "escalate_and_notify"
        if salience >= 0.6:
            return "priority_recovery"
        return "standard_retry"

    # ============================================================================
    # System metric stubs (override with real probes)
    # ============================================================================

    def _get_system_load(self) -> float:
        return 0.2

    def _get_memory_usage(self) -> float:
        return float(self.state.mem_util)

    def _get_cpu_usage(self) -> float:
        return 0.2

    def _get_response_time(self) -> float:
        return 0.05  # seconds

    def _get_error_rate(self) -> float:
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
        if "validation" in r or "schema" in r:
            return "validation"
        return "runtime"

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
        """
        out: list[float] = []
        for f in feature_batches:
            risk = float(f.get("task_risk", 0.5))
            sev = float(f.get("failure_severity", 1.0))
            imp = float(f.get("user_impact", 0.5))
            crit = float(f.get("business_criticality", 0.5))
            sys = 0.25 * float(f.get("system_load", 0.0)) + 0.25 * float(f.get("error_rate", 0.0))
            score = 0.35 * risk + 0.25 * sev + 0.2 * imp + 0.15 * crit + 0.05 * sys
            score = max(0.0, min(1.0, score))
            out.append(score)
        return out
