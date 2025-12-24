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
        
        # Schedule async tool registration if using local fallback
        # This ensures Tuya tools are registered even if tool_handler wasn't injected
        self._tool_registration_task: Optional[asyncio.Task] = None

    # -------------------------------------------------------------------------
    # Tool Handler Initialization (Override BaseAgent)
    # -------------------------------------------------------------------------
    
    async def _ensure_tool_handler(self):
        """
        Override BaseAgent's _ensure_tool_handler to register orchestration tools
        (Tuya + command_queue) when using local fallback ToolManager.
        
        This ensures OrchestrationAgent always has access to device control tools
        even when no shared ToolManager was injected.
        """
        # Call parent to create ToolManager if needed
        await super()._ensure_tool_handler()
        
        # If we're using a local fallback ToolManager, register orchestration tools
        if self.tool_handler is not None and not isinstance(self.tool_handler, list):
            # Single ToolManager instance (local fallback)
            logger.info(
                "[%s] Registering orchestration tools in local ToolManager...",
                self.agent_id
            )
            await self._register_orchestration_tools(self.tool_handler)
        elif isinstance(self.tool_handler, list) and self.tool_handler:
            # Sharded mode - register in all shards
            logger.info(
                "[%s] Registering orchestration tools in %d ToolManager shards...",
                self.agent_id,
                len(self.tool_handler)
            )
            for shard in self.tool_handler:
                if hasattr(shard, "register_tuya_tools"):
                    await shard.register_tuya_tools.remote()
    
    async def _register_orchestration_tools(self, tool_manager: Any) -> None:
        """
        Register orchestration-specific tools in a ToolManager instance.
        
        This includes:
        - Tuya tools (if Tuya is enabled)
        - Command queue tools (if implemented)
        - Any other orchestration-specific tools
        """
        try:
            # Register Tuya tools if enabled
            from seedcore.organs.organism_core import register_tuya_tools
            
            tuya_registered = await register_tuya_tools(tool_manager)
            if tuya_registered:
                logger.info(
                    "[%s] ✅ Tuya tools registered in local ToolManager",
                    self.agent_id
                )
            
            # TODO: Register command_queue.enqueue tool when implemented
            # For now, we'll use tuya.send_command directly for device commands
            
        except Exception as e:
            logger.warning(
                "[%s] Failed to register orchestration tools: %s",
                self.agent_id,
                e,
                exc_info=True
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
        # Log immediately when method is called (before any processing)
        task_type_raw = None
        task_id_raw = None
        try:
            if isinstance(task, dict):
                task_type_raw = task.get("type")
                task_id_raw = task.get("task_id")
            else:
                task_type_raw = getattr(task, "type", None)
                task_id_raw = getattr(task, "task_id", None)
        except Exception:
            pass
        
        logger.info(
            "[%s] 📥 execute_task ENTRY - task_type=%s, task_id=%s, task_class=%s",
            self.agent_id,
            task_type_raw or "unknown",
            task_id_raw or "unknown",
            type(task).__name__
        )
        
        try:
            tv = self._coerce_task_view(task)
            
            # Extract task type from multiple sources (prioritize actual type field)
            ttype_raw = None
            if isinstance(task, dict):
                # For dicts, check dict access first
                ttype_raw = task.get("type") or None
            else:
                # For objects, use getattr
                ttype_raw = getattr(task, "type", None)
            
            # Only fall back to prompt if type is missing
            if not ttype_raw:
                ttype_raw = tv.prompt or ""
            
            ttype = (ttype_raw or "").lower().strip()
            
            logger.info(
                "[%s] Task type detected: '%s' (raw: '%s', from_prompt=%s)",
                self.agent_id,
                ttype,
                ttype_raw,
                ttype_raw == tv.prompt if tv.prompt else False
            )
            
            
            # Handle "action" type tasks - convert to device_command if they have device params
            if ttype == "action":
                payload = self._task_payload_dict(task)
                params = payload.get("params", {})
                # Check if this is a device action (has device/room/action params)
                if isinstance(params, dict) and (params.get("device") or params.get("room") or params.get("action")):
                    logger.info(
                        "[%s] Converting 'action' task to orchestration.device_command (has device params)",
                        self.agent_id
                    )
                    # Convert to device command format
                    commands = [{
                        "command_id": tv.task_id,
                        "action": params.get("action"),
                        "device": params.get("device"),
                        "room": params.get("room"),
                        "domain": params.get("domain"),
                        **{k: v for k, v in params.items() if k not in ["action", "device", "room", "domain", "interaction", "_router"]}
                    }]
                    result = await self._handle_enqueue_commands(tv, commands)
                    logger.info(
                        "[%s] ✅ execute_task completed: action->device_command, task_id=%s, success=%s",
                        self.agent_id,
                        tv.task_id,
                        result.get("success", False)
                    )
                    return result
            
            # Check task type matches
            if ttype in ("orchestration.tick", "orchestration_tick"):
                logger.info(
                    "[%s] Handling orchestration.tick task",
                    self.agent_id
                )
                res = await self.control_tick()
                result = {
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
                logger.info(
                    "[%s] ✅ execute_task completed: orchestration.tick, task_id=%s",
                    self.agent_id,
                    tv.task_id
                )
                return result

            if ttype in ("orchestration.enqueue_commands", "orchestration.device_command"):
                logger.info(
                    "[%s] Handling orchestration.enqueue_commands/device_command task",
                    self.agent_id
                )
                payload = self._task_payload_dict(task)
                commands = payload.get("commands") or payload.get("command") or []
                if isinstance(commands, dict):
                    commands = [commands]
                result = await self._handle_enqueue_commands(tv, commands)
                logger.info(
                    "[%s] ✅ execute_task completed: orchestration.enqueue_commands, task_id=%s, success=%s",
                    self.agent_id,
                    tv.task_id,
                    result.get("success", False)
                )
                return result

            if ttype in ("orchestration.robot_task",):
                logger.info(
                    "[%s] Handling orchestration.robot_task",
                    self.agent_id
                )
                payload = self._task_payload_dict(task)
                result = await self._handle_robot_task(tv, payload)
                logger.info(
                    "[%s] ✅ execute_task completed: orchestration.robot_task, task_id=%s, success=%s",
                    self.agent_id,
                    tv.task_id,
                    result.get("success", False)
                )
                return result

            if ttype in ("orchestration.energy_optimize",):
                logger.info(
                    "[%s] Handling orchestration.energy_optimize task",
                    self.agent_id
                )
                payload = self._task_payload_dict(task)
                result = await self._handle_energy_optimize(tv, payload)
                logger.info(
                    "[%s] ✅ execute_task completed: orchestration.energy_optimize, task_id=%s, success=%s",
                    self.agent_id,
                    tv.task_id,
                    result.get("success", False)
                )
                return result

            # reject all other tasks (guest-facing, unknown, etc.)
            logger.warning(
                "[%s] ❌ Task rejected: type '%s' not supported by OrchestrationAgent. "
                "Supported types: orchestration.tick, orchestration.enqueue_commands, "
                "orchestration.device_command, orchestration.robot_task, orchestration.energy_optimize",
                self.agent_id,
                ttype
            )
            rejection_result = self._reject_result(
                tv,
                reason="agent_is_orchestrator",
                started_ts=self._utc_now_iso(),
                started_monotonic=time.perf_counter(),
            )
            logger.warning(
                "[%s] ✅ execute_task completed: REJECTED, task_id=%s, reason=agent_is_orchestrator, result=%s",
                self.agent_id,
                tv.task_id,
                rejection_result
            )
            return rejection_result
            
        except Exception as e:
            logger.error(
                "[%s] ❌ Exception in execute_task: %s",
                self.agent_id,
                e,
                exc_info=True
            )
            # Return error result instead of raising to prevent agent crash
            try:
                tv = self._coerce_task_view(task) if 'tv' not in locals() else tv
                task_id = getattr(tv, "task_id", "unknown") if 'tv' in locals() else "unknown"
            except Exception:
                task_id = "unknown"
            
            error_result = {
                "agent_id": self.agent_id,
                "task_id": task_id,
                "success": False,
                "error": str(e),
                "meta": {
                    "exec": {
                        "kind": "error",
                        "started_at": self._utc_now_iso(),
                    }
                },
            }
            logger.error(
                "[%s] ✅ execute_task completed: EXCEPTION, task_id=%s, error_result=%s",
                self.agent_id,
                task_id,
                error_result
            )
            return error_result

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
        
        Note: Device commands (domain="device") should use Tuya tools when available.
        This method delegates to command_queue.enqueue which routes to appropriate
        vendor tools (e.g., tuya.send_command) based on device type.
        """
        # Check Tuya capability for device commands
        has_tuya = await self._has_tuya_capability()
        logger.info(
            "[%s] Handling %d command(s) for task %s (Tuya capability: %s)",
            self.agent_id,
            len(commands),
            tv.task_id,
            has_tuya
        )
        
        results: List[Dict[str, Any]] = []
        for cmd in commands:
            cmd_id = str(cmd.get("command_id") or cmd.get("id") or "")
            if not cmd_id:
                logger.warning(
                    "[%s] Command missing command_id, skipping",
                    self.agent_id
                )
                results.append({"ok": False, "reason": "missing_command_id"})
                continue

            # Check if this is a device command that might use Tuya
            cmd_domain = cmd.get("domain", "").lower()
            cmd_type = cmd.get("type", "").lower()
            is_device_cmd = cmd_domain == "device" or "device" in cmd_type or "tuya" in cmd_type

            # Dedup to prevent self-loop storms
            if await self._seen_recently(cmd_id):
                results.append({"ok": True, "command_id": cmd_id, "dedup": True})
                continue

            # Safety gate (optional)
            if self.safety_mode and not await self._safety_check(cmd):
                logger.warning(
                    "[%s] Command %s failed safety check",
                    self.agent_id,
                    cmd_id
                )
                results.append(
                    {"ok": False, "command_id": cmd_id, "reason": "safety_check_failed"}
                )
                continue

            # Limit inflight
            async with self._inflight_sem:
                # Handle device commands directly via Tuya if available
                if is_device_cmd and has_tuya:
                    # Try to execute via Tuya directly
                    # device_id can come from cmd.device_id (explicit) or cmd.device (device name/ID)
                    device_id = cmd.get("device_id") or cmd.get("device") or None
                    action = cmd.get("action")
                    room = cmd.get("room")
                    
                    if device_id and action:
                        # Convert action to Tuya command format
                        # Map common actions to Tuya DP codes
                        tuya_commands = []
                        action_lower = str(action).lower()
                        
                        if action_lower in ("on", "turn_on", "enable", "open"):
                            # Common Tuya DP codes for power/switch
                            # Try switch_led first (common for lights), fallback to switch
                            tuya_commands.append({"code": "switch_led", "value": True})
                        elif action_lower in ("off", "turn_off", "disable", "close"):
                            tuya_commands.append({"code": "switch_led", "value": False})
                        elif action_lower.startswith("set_"):
                            # Handle set_* actions - extract value if possible
                            # For now, default to True
                            tuya_commands.append({"code": action_lower.replace("set_", ""), "value": True})
                        else:
                            # Try to use action as DP code directly
                            tuya_commands.append({"code": str(action), "value": True})
                        
                        logger.info(
                            "[%s] Executing device command via Tuya: device_id=%s, room=%s, action=%s, tuya_commands=%s",
                            self.agent_id,
                            device_id,
                            room,
                            action,
                            tuya_commands
                        )
                        
                        try:
                            resp = await self._safe_tool_write(
                                "tuya.send_command",
                                {
                                    "device_id": str(device_id),
                                    "commands": tuya_commands
                                }
                            )
                            # Check for success in various response formats
                            ok = False
                            if resp:
                                ok = (
                                    resp.get("ok") is True
                                    or resp.get("success") is True
                                    or (isinstance(resp.get("tuya_response"), dict) and resp.get("tuya_response", {}).get("success") is True)
                                )
                            
                            logger.info(
                                "[%s] Tuya command result: ok=%s, device_id=%s, resp_keys=%s",
                                self.agent_id,
                                ok,
                                device_id,
                                list(resp.keys()) if isinstance(resp, dict) else "non-dict"
                            )
                            results.append({"ok": ok, "command_id": cmd_id, "resp": resp, "method": "tuya_direct"})
                        except Exception as tuya_error:
                            logger.warning(
                                "[%s] Tuya command execution failed: device_id=%s, error=%s",
                                self.agent_id,
                                device_id,
                                tuya_error,
                                exc_info=True
                            )
                            results.append({"ok": False, "command_id": cmd_id, "error": str(tuya_error), "method": "tuya_direct"})
                    else:
                        logger.warning(
                            "[%s] Device command missing required fields: device_id=%s, action=%s, cmd_keys=%s",
                            self.agent_id,
                            device_id,
                            action,
                            list(cmd.keys()) if isinstance(cmd, dict) else "non-dict"
                        )
                        results.append({
                            "ok": False,
                            "command_id": cmd_id,
                            "reason": "missing_device_id_or_action",
                            "has_device_id": bool(device_id),
                            "has_action": bool(action)
                        })
                else:
                    # Fallback: log that command_queue.enqueue doesn't exist
                    logger.warning(
                        "[%s] Command %s cannot be executed: command_queue.enqueue tool not available. "
                        "is_device_cmd=%s, has_tuya=%s. Consider using tuya.send_command directly.",
                        self.agent_id,
                        cmd_id,
                        is_device_cmd,
                        has_tuya
                    )
                    results.append({
                        "ok": False,
                        "command_id": cmd_id,
                        "reason": "command_queue_tool_not_available",
                        "suggestion": "use_tuya_send_command_directly" if has_tuya else "register_command_queue_tool"
                    })

                # Mark seen regardless to suppress tight loops; TTL is short
                await self._mark_seen(cmd_id)

        # Calculate actual success: at least one command must succeed
        # If all commands failed or were skipped, the overall operation failed
        successful_commands = [r for r in results if r.get("ok") is True]
        failed_commands = [r for r in results if r.get("ok") is False]
        skipped_commands = [r for r in results if r.get("dedup") is True]
        
        overall_success = len(successful_commands) > 0
        
        logger.info(
            "[%s] Command execution summary: total=%d, successful=%d, failed=%d, skipped=%d, overall_success=%s",
            self.agent_id,
            len(results),
            len(successful_commands),
            len(failed_commands),
            len(skipped_commands),
            overall_success
        )
        
        if not overall_success and len(failed_commands) > 0:
            # Log reasons for failures
            failure_reasons = [r.get("reason") or r.get("error") for r in failed_commands]
            logger.warning(
                "[%s] All commands failed. Reasons: %s",
                self.agent_id,
                failure_reasons
            )

        return {
            "agent_id": self.agent_id,
            "task_id": tv.task_id,
            "success": overall_success,
            "result": {
                "enqueued": results,
                "count": len(results),
                "successful_count": len(successful_commands),
                "failed_count": len(failed_commands),
                "skipped_count": len(skipped_commands),
            },
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
    # Capability & Vendor Checks
    # -------------------------------------------------------------------------

    async def _has_tuya_capability(self) -> bool:
        """
        Check if Tuya device vendor capability is available.
        
        This enables graceful degradation when Tuya is disabled or unavailable.
        Agents can check this before attempting device operations.
        
        Returns:
            True if Tuya capability is available, False otherwise
        """
        try:
            # Ensure tool_handler is initialized (lazy initialization)
            if not hasattr(self, "tool_handler") or self.tool_handler is None:
                try:
                    await self._ensure_tool_handler()
                except Exception as init_error:
                    logger.warning(
                        "[%s] Tuya capability check: tool_handler initialization failed: %s",
                        self.agent_id,
                        init_error
                    )
                    return False
            
            tool_handler = getattr(self, "tool_handler", None)
            if not tool_handler:
                return False
            
            # Handle both ToolManager instance and ToolManagerShard list
            if isinstance(tool_handler, list):
                # Sharded mode - check first shard (all shards should have same capabilities)
                if tool_handler and hasattr(tool_handler[0], "has_capability"):
                    result = await tool_handler[0].has_capability.remote("device.vendor.tuya")
                    return bool(result)
            elif hasattr(tool_handler, "has_capability"):
                # Single ToolManager instance
                result = await tool_handler.has_capability("device.vendor.tuya")
                return bool(result)
            
            # Fallback: check if tool exists
            if hasattr(tool_handler, "has"):
                has_tool = await tool_handler.has("tuya.send_command")
                return bool(has_tool)
            
            return False
        except Exception as e:
            logger.warning(
                "[%s] Tuya capability check failed: %s",
                self.agent_id,
                e
            )
            return False

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
            
            # Use BaseAgent's use_tool method which handles tool_handler initialization
            try:
                result = await asyncio.wait_for(
                    self.use_tool(name, args),
                    timeout=self.read_timeout_s
                )
                return result
            except asyncio.TimeoutError:
                raise  # Re-raise to be caught by outer handler
            except Exception as tool_error:
                logger.warning(
                    "[%s] Tool read execution error: %s, error=%s",
                    self.agent_id,
                    name,
                    tool_error
                )
                return None
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] Tool read timeout: %s (timeout=%.1fs)",
                self.agent_id,
                name,
                self.read_timeout_s
            )
            return None
        except Exception as e:
            logger.warning(
                "[%s] Tool read exception: %s, error=%s",
                self.agent_id,
                name,
                e
            )
            return None

    async def _safe_tool_write(
        self, name: str, args: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        try:
            if not self._authorize(name, args):
                return None
            
            # Use BaseAgent's use_tool method which handles tool_handler initialization
            try:
                result = await asyncio.wait_for(
                    self.use_tool(name, args),
                    timeout=self.write_timeout_s
                )
                return result
            except asyncio.TimeoutError:
                raise  # Re-raise to be caught by outer handler
            except Exception as tool_error:
                logger.warning(
                    "[%s] Tool write execution error: %s, error=%s",
                    self.agent_id,
                    name,
                    tool_error
                )
                return None
        except asyncio.TimeoutError:
            logger.warning(
                "[%s] Tool write timeout: %s (timeout=%.1fs)",
                self.agent_id,
                name,
                self.write_timeout_s
            )
            return None
        except Exception as e:
            logger.warning(
                "[%s] Tool write exception: %s, error=%s",
                self.agent_id,
                name,
                e
            )
            return None

    def _authorize(self, tool_name: str, context: Dict[str, Any]) -> bool:
        """
        RBAC authorization wrapper with enhanced logging.
        
        Orchestration tools (command_queue.*, robots.*, energy.*, devices.*, telemetry.*)
        are exempt from RBAC checks since they are core orchestration capabilities.
        """
        # Orchestration tools are core capabilities - exempt from RBAC checks
        # These tools are essential for the OrchestrationAgent's function
        orchestration_tool_prefixes = (
            "command_queue.",
            "robots.",
            "energy.",
            "devices.",
            "telemetry.",
            "tuya.",
        )
        # Check if tool matches any orchestration prefix
        matched_prefix = None
        for prefix in orchestration_tool_prefixes:
            if tool_name.startswith(prefix):
                matched_prefix = prefix
                break
        
        if matched_prefix:
            logger.info(
                "[%s] ✅ Orchestration tool '%s' exempt from RBAC (matches prefix '%s')",
                self.agent_id,
                tool_name,
                matched_prefix
            )
            return True
        
        try:
            dec = self.authorize_tool(
                tool_name=tool_name,
                cost_usd=0.0,
                context={"agent_id": self.agent_id, **(context or {})},
            )
            if not dec.allowed:
                logger.warning(
                    "[%s] Tool authorization denied: %s, reason=%s",
                    self.agent_id,
                    tool_name,
                    dec.reason or "unknown"
                )
            return bool(dec.allowed)
        except Exception as e:
            logger.warning(
                "[%s] Tool authorization exception: %s, error=%s",
                self.agent_id,
                tool_name,
                e
            )
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
