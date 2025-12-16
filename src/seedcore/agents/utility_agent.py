# seedcore/agents/ula_agent.py
# ------------------------------------------------------------
# Utility & Learning Agent (ULA)
#
# Purpose:
#   • Observe cross-system signals (agent metrics, router stats, drift)
#   • Learn simple policies (thresholds, weights) and suggest/apply updates
#   • Never executes guest-facing tasks; may accept ULA-specific “observe/tune” jobs
#
# Design:
#   • Inherits BaseAgent to reuse state, private memory, advertising, RBAC
#   • Runs an optional background observation loop (start/stop)
#   • Uses ToolManager for cross-service reads/writes (metrics, router, policy)
#   • Emits telemetry decisions; updates AgentState (capability/mem_util) conservatively
# ------------------------------------------------------------

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Dict, List, Optional

try:
    import ray  # pyright: ignore[reportMissingImports]
except ImportError:
    ray = None  # type: ignore

from .base import BaseAgent
from .roles.specialization import Specialization

logger = logging.getLogger(__name__)


# Conditional decorator: use ray.remote if available, otherwise no-op
if ray is not None:
    UtilityAgentDecorator = ray.remote  # type: ignore
else:
    def UtilityAgentDecorator(cls):
        return cls


@UtilityAgentDecorator
class UtilityAgent(BaseAgent):
    """
    ULA observes the system and tunes parameters.
    It should not execute guest-facing tasks; override execute_task accordingly.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        interval_s: float = 15.0,
        max_consecutive_errors: int = 5,
        min_samples_for_action: int = 10,
        apply_changes: bool = True,
        **kwargs: Any,
    ):
        """
        Args:
            agent_id: Stable agent identifier
            interval_s: Observation loop period
            max_consecutive_errors: Trip circuit on repeated failures
            min_samples_for_action: Require this many samples before writing policies
            apply_changes: If False, operate in dry-run (recommendations only)
            **kwargs: Forwarded to BaseAgent (role_profile, tool_manager, etc.)
        """
        super().__init__(agent_id=agent_id, specialization=Specialization.ULA, **kwargs)

        self.interval_s = float(interval_s)
        self.max_consecutive_errors = int(max_consecutive_errors)
        self.min_samples_for_action = int(min_samples_for_action)
        self.apply_changes = bool(apply_changes)

        self._loop_task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self._err_streak = 0

        logger.info(
            "✅ ULA %s initialized (interval=%.1fs, apply_changes=%s)",
            self.agent_id,
            self.interval_s,
            self.apply_changes,
        )

    # -------------------------------------------------------------------------
    # Lifecycle: optional background loop
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background observation loop."""
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_evt.clear()
        self._loop_task = asyncio.create_task(
            self._observe_loop(), name=f"ula-{self.agent_id}"
        )
        logger.info("🟢 ULA %s background loop started", self.agent_id)

    async def stop(self) -> None:
        """Stop the background observation loop."""
        self._stop_evt.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=self.interval_s + 2.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        logger.info("🛑 ULA %s background loop stopped", self.agent_id)

    async def _observe_loop(self) -> None:
        """Periodic observation + tuning."""
        while not self._stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                await self.observe_and_tune_system()
                self._err_streak = 0
            except Exception as e:
                self._err_streak += 1
                logger.warning(
                    "ULA %s iteration error (streak=%d): %s",
                    self.agent_id,
                    self._err_streak,
                    e,
                    exc_info=True,
                )
                if self._err_streak >= self.max_consecutive_errors:
                    logger.error(
                        "ULA %s tripping internal circuit after %d errors",
                        self.agent_id,
                        self._err_streak,
                    )
                    break  # leave loop
            finally:
                # Gentle EWMA capability bump (ULA “succeeds” if it runs)
                try:
                    self.state.record_task_outcome(
                        success=True,
                        quality=1.0,
                        salience=0.2,  # low salience for routine ops
                        duration_s=time.perf_counter() - t0,
                        capability_observed=None,
                    )
                except Exception:
                    pass

            # sleep remaining time
            elapsed = time.perf_counter() - t0
            await asyncio.wait(
                [self._stop_evt.wait()], timeout=max(0.0, self.interval_s - elapsed)
            )

    # -------------------------------------------------------------------------
    # Core: Observation & Tuning
    # -------------------------------------------------------------------------

    async def observe_and_tune_system(self) -> Dict[str, Any]:
        """
        Main ULA tick:
          1) Read system metrics & router/agents status
          2) Detect simple issues (backlogs, high latency, rising drift)
          3) Propose/Apply small policy nudges (weights/thresholds)
          4) Emit telemetry
        """
        # 1) Gather signals (all via tools + RBAC)
        metrics = await self._safe_tool_read(
            "metrics.read",
            {
                "keys": [
                    "queue_depth_total",
                    "queue_depth_fast",
                    "queue_depth_cog",
                    "latency_p50",
                    "latency_p95",
                    "drift_score_mean",
                    "drift_score_p90",
                    "errors_5m",
                    "throughput_1m",
                ]
            },
        )

        router_stats = await self._safe_tool_read("router.stats", {})
        agents_stat = await self._safe_tool_read("agents.list", {"with_metrics": True})
        energy = await self._safe_tool_read("energy.summary", {"window": "5m"})

        # Defensive defaults
        m = metrics or {}
        rs = router_stats or {}
        ag = agents_stat or {"agents": []}
        en = energy or {}

        # 2) Simple heuristics / detectors
        suggestions: List[Dict[str, Any]] = []

        q_fast = float(m.get("queue_depth_fast", 0))
        q_cog = float(m.get("queue_depth_cog", 0))
        p95 = float(m.get("latency_p95", 0))
        drift_p90 = float(m.get("drift_score_p90", 0.0))
        throughput = float(m.get("throughput_1m", 0.0))

        # Heuristic A: Fast-path saturated -> widen fast-path, raise concurrency
        if q_fast > 100 and p95 > 1.5:
            suggestions.append(
                {
                    "kind": "router_tuning",
                    "action": "increase_fast_concurrency",
                    "delta": +2,
                    "reason": f"q_fast={q_fast}, p95={p95}",
                }
            )

        # Heuristic B: Cognitive backlog -> increase planner lanes or threshold
        if q_cog > 30 and drift_p90 < 0.5:
            suggestions.append(
                {
                    "kind": "planner_tuning",
                    "action": "increase_planner_lanes",
                    "delta": +1,
                    "reason": f"q_cog={q_cog}, drift_p90={drift_p90}",
                }
            )

        # Heuristic C: Rising drift -> lower OCPS valve to escalate sooner
        if drift_p90 >= 0.7:
            suggestions.append(
                {
                    "kind": "ocps_valve",
                    "action": "lower_threshold",
                    "new_threshold": 0.45,
                    "reason": f"drift_p90={drift_p90}",
                }
            )

        # Heuristic D: Idle specialists -> temporarily bias router to use them more
        idle_specs = [
            a
            for a in ag.get("agents", [])
            if a.get("specialization") not in ("ULA", None)
            and float(a.get("load", 0.0)) < 0.1
        ]
        if len(idle_specs) >= 2 and throughput > 0:
            suggestions.append(
                {
                    "kind": "router_bias",
                    "action": "increase_weight_for_idle_specialists",
                    "delta": +0.05,
                    "reason": f"idle_specs={len(idle_specs)}",
                }
            )

        # 3) Apply or dry-run
        applied: List[Dict[str, Any]] = []
        for s in suggestions:
            # Skip writes if we don't have enough evidence yet
            if (rs.get("sample_count", 0) or 0) < self.min_samples_for_action:
                s["status"] = "skipped_insufficient_samples"
                applied.append(s)
                continue

            if not self.apply_changes:
                s["status"] = "dry_run"
                applied.append(s)
                continue

            # Map to policy.update calls
            sres = await self._safe_tool_write("policy.update", {"suggestion": s})
            s["status"] = "applied" if sres and sres.get("ok") else "attempted"
            s["result"] = sres
            applied.append(s)

        # 4) Emit telemetry
        await self._safe_tool_write(
            "telemetry.emit",
            {
                "agent_id": self.agent_id,
                "kind": "ula_tick",
                "metrics": m,
                "router_stats": rs,
                "energy": en,
                "suggestions": applied,
            },
        )

        # 5) Light self-update + private memory (doesn't block)
        try:
            self.update_private_memory(
                task_embed=None,
                peers=None,
                success=True,
                quality=1.0 if applied else 0.7,
                latency_s=self.interval_s,
                energy=en.get("power_avg_w"),
                delta_e=en.get("delta_j"),
            )
        except Exception:
            pass

        return {
            "metrics": m,
            "router_stats": rs,
            "agents": len(ag.get("agents", [])),
            "energy": en,
            "suggestions": applied,
        }

    # -------------------------------------------------------------------------
    # Task handling override
    # -------------------------------------------------------------------------

    async def execute_task(self, task) -> Dict[str, Any]:
        """
        ULA does not execute guest-facing tasks. It accepts only ULA-scoped tasks:
          - type: 'ula.observe' → single observe tick
          - type: 'ula.tune'    → observe + apply (force)
        Anything else is rejected.
        """
        tv = self._coerce_task_view(task)
        ttype = (
            getattr(task, "type", None)
            or tv.prompt  # sometimes callers stuff a verb in description
            or (task.get("type") if isinstance(task, dict) else None)
            or ""
        ).lower()

        if ttype in ("ula.observe", "ula_observe"):
            res = await self.observe_and_tune_system()
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": True,
                "result": res,
                "meta": {"exec": {"kind": "ula.observe"}},
            }

        if ttype in ("ula.tune", "ula_tune"):
            prev = self.apply_changes
            try:
                self.apply_changes = True
                res = await self.observe_and_tune_system()
                return {
                    "agent_id": self.agent_id,
                    "task_id": tv.task_id,
                    "success": True,
                    "result": res,
                    "meta": {"exec": {"kind": "ula.tune_forced"}},
                }
            finally:
                self.apply_changes = prev

        # Reject all other tasks
        return self._reject_result(
            tv,
            reason="agent_is_observer",
            started_ts=self._utc_now_iso(),
            started_monotonic=time.perf_counter(),
        )

    # -------------------------------------------------------------------------
    # Tool helpers with RBAC & timeouts
    # -------------------------------------------------------------------------

    async def _safe_tool_read(
        self, name: str, args: Dict[str, Any], timeout_s: float = 8.0
    ) -> Optional[Dict[str, Any]]:
        """RBAC + existence + timeout wrapper for read-like tools."""
        try:
            if not self._authorize(name, args):
                return None
            tool_manager = getattr(self, "tools", None)
            if not tool_manager:
                return None
            has_result = tool_manager.has(name)
            if inspect.isawaitable(has_result):
                has_result = await has_result
            if not has_result:
                return None
            execute_coro = tool_manager.execute(name, args)
            if inspect.isawaitable(execute_coro):
                return await asyncio.wait_for(execute_coro, timeout=timeout_s)
            return None
        except Exception:
            return None

    async def _safe_tool_write(
        self, name: str, args: Dict[str, Any], timeout_s: float = 8.0
    ) -> Optional[Dict[str, Any]]:
        """RBAC + existence + timeout wrapper for write-like tools."""
        try:
            if not self._authorize(name, args):
                return None
            tool_manager = getattr(self, "tools", None)
            if not tool_manager:
                return None
            has_result = tool_manager.has(name)
            if inspect.isawaitable(has_result):
                has_result = await has_result
            if not has_result:
                return None
            execute_coro = tool_manager.execute(name, args)
            if inspect.isawaitable(execute_coro):
                return await asyncio.wait_for(execute_coro, timeout=timeout_s)
            return None
        except Exception:
            return None

    def _authorize(self, tool_name: str, context: Dict[str, Any]) -> bool:
        """Delegate to RBAC; ULA typically has read access to metrics/router/policy."""
        try:
            dec = self.authorize_tool(
                tool_name=tool_name,
                cost_usd=0.0,
                context={"agent_id": self.agent_id, **(context or {})},
            )
            return bool(dec.allowed)
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Advertisement (inherits BaseAgent.advertise_capabilities)
    # -------------------------------------------------------------------------
    # The ULA will advertise Specialization.ULA and its (modest) materialized skills.
    # Upstream Router should never select it for guest tasks; it is selected only
    # for meta/maintenance jobs or runs its own loop.
