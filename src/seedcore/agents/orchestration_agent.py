# seedcore/agents/orchestration_agent.py
# -----------------------------------------------------------------------------
# Orchestration Agent — Device & Robot coordination / energy optimization
#
# • Class name defines "kind" (no organ_kind needed)
# • Inherits BaseAgent for RBAC/state/private memory/advertising
# • Optional background control loop (start/stop)
# • Executes only orchestration-scoped tasks; rejects guest-facing tasks
# • Uses ToolManager tools for device/robot/energy operations
# • Adds idempotency + defensive timeouts to avoid self-loop storms
# -----------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, List

try:
    import ray  # pyright: ignore[reportMissingImports]
except ImportError:
    ray = None  # type: ignore

from .base import BaseAgent
from .roles.specialization import Specialization

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.agents.orchestration_agent")
logger = ensure_serve_logger("seedcore.agents.orchestration_agent", level="DEBUG")

# Conditional decorator: use ray.remote if available, otherwise no-op
if ray is not None:
    OrchestrationAgentDecorator = ray.remote  # type: ignore
else:

    def OrchestrationAgentDecorator(cls):
        return cls


@dataclass
class CommandResult:
    ok: bool
    command_id: str
    reason: str = ""
    meta: Optional[Dict[str, Any]] = None


@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
class OrchestrationAgent(BaseAgent):
    """
    Infra-facing orchestrator for device & robot actions.

    Typical responsibilities:
      - plan device/robot actions (routing, scheduling)
      - enforce safety & idempotency constraints
      - enqueue commands to downstream executors/controllers
      - periodic control: energy optimization, health checks, backlog drain

    This agent MUST NOT handle guest-facing conversational tasks.
    """

    def __init__(
        self,
        agent_id: str,
        *,
        # Loop behavior
        interval_s: float = 5.0,
        max_consecutive_errors: int = 5,
        safety_mode: bool = True,
        # Default specialization is fine-grained "role"
        specialization: Specialization = Specialization.DEVICE_ORCHESTRATOR,
        # Idempotency / anti-storm
        dedup_ttl_s: float = 60.0,
        max_inflight_commands: int = 128,
        # Tool timeouts
        read_timeout_s: float = 6.0,
        write_timeout_s: float = 10.0,
        **kwargs: Any,
    ):
        super().__init__(agent_id=agent_id, specialization=specialization, **kwargs)

        self.interval_s = float(interval_s)
        self.max_consecutive_errors = int(max_consecutive_errors)
        self.safety_mode = bool(safety_mode)

        self.read_timeout_s = float(read_timeout_s)
        self.write_timeout_s = float(write_timeout_s)

        self.dedup_ttl_s = float(dedup_ttl_s)
        self.max_inflight_commands = int(max_inflight_commands)

        self._stop_evt = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None
        self._err_streak = 0

        # Simple local dedup cache: {command_id: monotonic_deadline}
        self._seen: Dict[str, float] = {}
        self._seen_lock = asyncio.Lock()

        # In-flight limiter (prevents runaway self-loop)
        self._inflight_sem = asyncio.Semaphore(self.max_inflight_commands)

        logger.info(
            "🧭 OrchestrationAgent %s initialized (interval=%.1fs, safety=%s, spec=%s)",
            self.agent_id,
            self.interval_s,
            self.safety_mode,
            getattr(self.specialization, "value", str(self.specialization)),
        )

    # -------------------------------------------------------------------------
    # Lifecycle controls (optional background loop)
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_evt.clear()
        self._loop_task = asyncio.create_task(
            self._control_loop(), name=f"orchestrator-{self.agent_id}"
        )
        logger.info("🟢 OrchestrationAgent %s loop started", self.agent_id)

    async def stop(self) -> None:
        self._stop_evt.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=self.interval_s + 2.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        logger.info("🛑 OrchestrationAgent %s loop stopped", self.agent_id)

    async def _control_loop(self) -> None:
        """
        Periodic, low-risk control tick. Keep it conservative:
          - health checks
          - energy optimization suggestions
          - backlog monitoring / telemetry
        """
        while not self._stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                await self.control_tick()
                self._err_streak = 0
            except Exception as e:
                self._err_streak += 1
                logger.warning(
                    "OrchestrationAgent %s tick error (streak=%d): %s",
                    self.agent_id,
                    self._err_streak,
                    e,
                    exc_info=True,
                )
                if self._err_streak >= self.max_consecutive_errors:
                    logger.error(
                        "OrchestrationAgent %s tripping internal circuit after %d errors",
                        self.agent_id,
                        self._err_streak,
                    )
                    break
            finally:
                # gentle “heartbeat success” for state EWMA
                try:
                    self.state.record_task_outcome(
                        success=True,
                        quality=0.8,
                        salience=0.1,
                        duration_s=time.perf_counter() - t0,
                        capability_observed=None,
                    )
                except Exception:
                    pass

            elapsed = time.perf_counter() - t0
            await asyncio.wait(
                [self._stop_evt.wait()], timeout=max(0.0, self.interval_s - elapsed)
            )

    async def control_tick(self) -> Dict[str, Any]:
        """
        Conservative periodic tick. Should not issue direct actuator commands unless explicitly safe.
        """
        # Examples: read-only status signals
        devices = await self._safe_tool_read("devices.status", {})
        robots = await self._safe_tool_read("robots.status", {})
        energy = await self._safe_tool_read("energy.summary", {"window": "5m"})

        # Optionally compute and emit telemetry
        await self._safe_tool_write(
            "telemetry.emit",
            {
                "agent_id": self.agent_id,
                "kind": "orchestrator_tick",
                "devices": devices,
                "robots": robots,
                "energy": energy,
                "safety_mode": self.safety_mode,
            },
        )

        return {"devices": devices, "robots": robots, "energy": energy}

    # -------------------------------------------------------------------------
    # Task entry: orchestration-scoped tasks only
    # -------------------------------------------------------------------------

    async def execute_task(self, task) -> Dict[str, Any]:
        """
        Accepts only orchestration task types (examples):
          - orchestration.enqueue_commands
          - orchestration.device_command
          - orchestration.robot_task
          - orchestration.energy_optimize
          - orchestration.tick (one-shot control_tick)

        Anything else is rejected.
        """
        tv = self._coerce_task_view(task)
        ttype = (
            getattr(task, "type", None)
            or tv.prompt
            or (task.get("type") if isinstance(task, dict) else "")
            or ""
        )
        ttype = (ttype or "").lower().strip()

        if ttype in ("orchestration.tick", "orchestration_tick"):
            res = await self.control_tick()
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": True,
                "result": res,
                "meta": {
                    "exec": {
                        "kind": "orchestration.tick",
                        "started_at": self._utc_now_iso(),
                    }
                },
            }

        if ttype in ("orchestration.enqueue_commands", "orchestration.device_command"):
            payload = self._task_payload_dict(task)
            commands = payload.get("commands") or payload.get("command") or []
            if isinstance(commands, dict):
                commands = [commands]
            return await self._handle_enqueue_commands(tv, commands)

        if ttype in ("orchestration.robot_task",):
            payload = self._task_payload_dict(task)
            return await self._handle_robot_task(tv, payload)

        if ttype in ("orchestration.energy_optimize",):
            payload = self._task_payload_dict(task)
            return await self._handle_energy_optimize(tv, payload)

        # reject all other tasks (guest-facing, unknown, etc.)
        return self._reject_result(
            tv,
            reason="agent_is_orchestrator",
            started_ts=self._utc_now_iso(),
            started_monotonic=time.perf_counter(),
        )

    def _task_payload_dict(self, task: Any) -> Dict[str, Any]:
        if isinstance(task, dict):
            return task
        try:
            return getattr(task, "data", None) or getattr(task, "__dict__", {}) or {}
        except Exception:
            return {}

    # -------------------------------------------------------------------------
    # Core handlers
    # -------------------------------------------------------------------------

    async def _handle_enqueue_commands(
        self, tv, commands: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Enqueue actuator commands durably rather than executing directly.
        This prevents half-applied actions under upstream cancellation.
        """
        results: List[Dict[str, Any]] = []
        for cmd in commands:
            cmd_id = str(cmd.get("command_id") or cmd.get("id") or "")
            if not cmd_id:
                results.append({"ok": False, "reason": "missing_command_id"})
                continue

            # Dedup to prevent self-loop storms
            if await self._seen_recently(cmd_id):
                results.append({"ok": True, "command_id": cmd_id, "dedup": True})
                continue

            # Safety gate (optional)
            if self.safety_mode and not await self._safety_check(cmd):
                results.append(
                    {"ok": False, "command_id": cmd_id, "reason": "safety_check_failed"}
                )
                continue

            # Limit inflight
            async with self._inflight_sem:
                # Durable enqueue (preferred): a downstream executor applies it
                # Tool contract example: command_queue.enqueue({command: {...}})
                resp = await self._safe_tool_write(
                    "command_queue.enqueue", {"command": cmd}
                )
                ok = bool(
                    resp and (resp.get("ok") is True or resp.get("success") is True)
                )
                results.append({"ok": ok, "command_id": cmd_id, "resp": resp})

                # Mark seen regardless to suppress tight loops; TTL is short
                await self._mark_seen(cmd_id)

        return {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "success": True,
            "result": {"enqueued": results, "count": len(results)},
            "meta": {
                "exec": {
                    "kind": "orchestration.enqueue_commands",
                    "started_at": self._utc_now_iso(),
                }
            },
        }

    async def _handle_robot_task(self, tv, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Example robot task handler: assigns a robot job via tool.
        Expect payload: {robot_id, job, job_id}
        """
        job_id = str(payload.get("job_id") or tv.task_id or "")
        if not job_id:
            return self._reject_result(
                tv,
                reason="missing_job_id",
                started_ts=self._utc_now_iso(),
                started_monotonic=time.perf_counter(),
            )

        if await self._seen_recently(job_id):
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": True,
                "result": {"dedup": True, "job_id": job_id},
                "meta": {"exec": {"kind": "orchestration.robot_task"}},
            }

        if self.safety_mode and not await self._safety_check(payload):
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": False,
                "result": {"job_id": job_id, "reason": "safety_check_failed"},
                "meta": {"exec": {"kind": "orchestration.robot_task"}},
            }

        resp = await self._safe_tool_write("robots.assign_task", payload)
        ok = bool(resp and (resp.get("ok") is True or resp.get("success") is True))

        await self._mark_seen(job_id)
        return {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "success": ok,
            "result": {"job_id": job_id, "resp": resp},
            "meta": {"exec": {"kind": "orchestration.robot_task"}},
        }

    async def _handle_energy_optimize(
        self, tv, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Example energy optimization: compute recommendation or apply policy.
        Keep conservative; prefer writing to policy/queue rather than direct actuators.
        """
        # Read context
        energy = await self._safe_tool_read(
            "energy.summary", {"window": payload.get("window", "15m")}
        )
        weather = await self._safe_tool_read("weather.read", {})  # optional tool
        occupancy = await self._safe_tool_read("occupancy.status", {})  # optional tool

        # Ask optimizer tool for recommended actions
        rec = await self._safe_tool_write(
            "energy.optimize",
            {
                "energy": energy,
                "weather": weather,
                "occupancy": occupancy,
                "constraints": payload.get("constraints", {}),
            },
        )

        # Optionally enqueue recommended control actions rather than direct apply
        enqueue = []
        if isinstance(rec, dict):
            enqueue = rec.get("recommended_commands") or []
        if enqueue:
            # best-effort enqueue
            await self._handle_enqueue_commands(
                tv, enqueue if isinstance(enqueue, list) else [enqueue]
            )

        return {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "success": True,
            "result": {"energy": energy, "recommendation": rec},
            "meta": {"exec": {"kind": "orchestration.energy_optimize"}},
        }

    # -------------------------------------------------------------------------
    # Safety + Dedup helpers
    # -------------------------------------------------------------------------

    async def _safety_check(self, obj: Dict[str, Any]) -> bool:
        """
        Minimal safety hook. You can route this to a SAFETY tool/agent later.
        For now: deny obviously dangerous ops unless explicitly allowed.
        """
        try:
            action = str(obj.get("action") or obj.get("kind") or "").lower()
            if not action:
                return True
            # Example denylist patterns (customize per your environment)
            if "unlock_all" in action:
                return False
            if "disable_alarm" in action:
                return False
            return True
        except Exception:
            return False

    async def _seen_recently(self, key: str) -> bool:
        now = time.monotonic()
        async with self._seen_lock:
            # purge expired
            expired = [k for k, dl in self._seen.items() if dl <= now]
            for k in expired:
                self._seen.pop(k, None)
            return key in self._seen

    async def _mark_seen(self, key: str) -> None:
        async with self._seen_lock:
            self._seen[key] = time.monotonic() + self.dedup_ttl_s

    # -------------------------------------------------------------------------
    # Tool wrappers (RBAC + presence + timeout)
    # -------------------------------------------------------------------------

    async def _safe_tool_read(
        self, name: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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

            coro = tool_manager.execute(name, args)
            if inspect.isawaitable(coro):
                return await asyncio.wait_for(coro, timeout=self.read_timeout_s)
            return None
        except Exception:
            return None

    async def _safe_tool_write(
        self, name: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
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

            coro = tool_manager.execute(name, args)
            if inspect.isawaitable(coro):
                return await asyncio.wait_for(coro, timeout=self.write_timeout_s)
            return None
        except Exception:
            return None

    def _authorize(self, tool_name: str, context: Dict[str, Any]) -> bool:
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
    # Introspection
    # -------------------------------------------------------------------------

    async def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "specialization": getattr(
                self.specialization, "value", str(self.specialization)
            ),
            "running": bool(self._loop_task and not self._loop_task.done()),
            "interval_s": self.interval_s,
            "safety_mode": self.safety_mode,
            "dedup_ttl_s": self.dedup_ttl_s,
            "max_inflight_commands": self.max_inflight_commands,
        }
