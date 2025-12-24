# seedcore/agents/environment_agent.py
# ------------------------------------------------------------
# Environment Intelligence Agent (EIA)
#
# Purpose:
#   • Continuous situational awareness & world modeling
#   • Anomaly detection, safety monitoring, forecasting
#   • Emits signals, alerts, and policy hints
#
# Design:
#   • Inherits BaseAgent
#   • Runs a hardened background loop (self-triggered)
#   • Never executes guest-facing tasks
#   • Has internal circuit breaker
# ------------------------------------------------------------

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

try:
    import ray  # pyright: ignore[reportMissingImports]
except ImportError:
    ray = None  # type: ignore

from .base import BaseAgent
from .roles.specialization import Specialization
from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.agents.environment_agent")
logger = ensure_serve_logger("seedcore.agents.environment_agent", level="DEBUG")

@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class EnvironmentIntelligenceAgent(BaseAgent):
    """
    Hardened agent for environment / world modeling / anomaly detection.
    Runs a self-loop and never handles guest-facing tasks.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        interval_s: float = 10.0,
        max_consecutive_errors: int = 3,
        safety_mode: bool = True,
        specialization: Specialization = Specialization.ANOMALY_DETECTOR,
        **kwargs: Any,
    ):
        super().__init__(
            agent_id=agent_id,
            specialization=specialization,
            **kwargs,
        )

        self.interval_s = float(interval_s)
        self.max_consecutive_errors = int(max_consecutive_errors)
        self.safety_mode = bool(safety_mode)

        self._loop_task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self._err_streak = 0

        logger.info(
            "🌍 EnvironmentAgent %s initialized (interval=%.1fs, safety=%s, spec=%s)",
            self.agent_id,
            self.interval_s,
            self.safety_mode,
            self.specialization.value,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start environment sensing loop."""
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_evt.clear()
        self._loop_task = asyncio.create_task(
            self._sense_loop(), name=f"env-{self.agent_id}"
        )
        logger.info("🟢 EnvironmentAgent %s loop started", self.agent_id)

    async def stop(self) -> None:
        """Stop environment sensing loop."""
        self._stop_evt.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(
                    self._loop_task, timeout=self.interval_s + 2.0
                )
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        logger.info("🛑 EnvironmentAgent %s loop stopped", self.agent_id)

    # ------------------------------------------------------------------
    # Core sensing loop
    # ------------------------------------------------------------------

    async def _sense_loop(self) -> None:
        """
        Hardened self-loop:
          • Never throws
          • Trips internal circuit on repeated failure
          • Records low-salience success
        """
        while not self._stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                await self.sense_environment()
                self._err_streak = 0
            except Exception as e:
                self._err_streak += 1
                logger.warning(
                    "EnvironmentAgent %s error (streak=%d): %s",
                    self.agent_id,
                    self._err_streak,
                    e,
                    exc_info=True,
                )

                if self._err_streak >= self.max_consecutive_errors:
                    logger.error(
                        "🚨 EnvironmentAgent %s tripping circuit breaker",
                        self.agent_id,
                    )
                    break  # exit loop permanently

            finally:
                # Record as low-salience background activity
                try:
                    self.state.record_task_outcome(
                        success=True,
                        quality=0.9,
                        salience=0.1,
                        duration_s=time.perf_counter() - t0,
                        capability_observed=None,
                    )
                except Exception:
                    pass

            elapsed = time.perf_counter() - t0
            await asyncio.wait(
                [self._stop_evt.wait()],
                timeout=max(0.0, self.interval_s - elapsed),
            )

    # ------------------------------------------------------------------
    # Environment logic (override in subclasses)
    # ------------------------------------------------------------------

    async def sense_environment(self) -> Dict[str, Any]:
        """
        Override in concrete agents:
          • ENVIRONMENT_MODEL
          • ANOMALY_DETECTOR
          • FORECASTER
          • SAFETY_MONITOR
        """
        raise NotImplementedError(
            "sense_environment() must be implemented by subclass"
        )

    # ------------------------------------------------------------------
    # Task handling (explicitly locked down)
    # ------------------------------------------------------------------

    async def execute_task(self, task) -> Dict[str, Any]:
        """
        Environment agents do NOT execute guest-facing tasks.
        Only accept env-scoped maintenance tasks.
        """
        tv = self._coerce_task_view(task)
        ttype = (
            getattr(task, "type", None)
            or (task.get("type") if isinstance(task, dict) else None)
            or ""
        ).lower()

        if ttype in ("env.tick", "environment.tick"):
            res = await self.sense_environment()
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": True,
                "result": res,
                "meta": {"exec": {"kind": "env.tick"}},
            }

        return self._reject_result(
            tv,
            reason="environment_agent_non_guest",
            started_ts=self._utc_now_iso(),
            started_monotonic=time.perf_counter(),
        )
