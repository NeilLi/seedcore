# seedcore/agents/observer_agent.py
# -----------------------------------------------------------------------------
# Observer Agent — Proactive MW→Cache warmer for hot LTM items
#
# • Inherits BaseAgent (RBAC, state, private memory, advertise_capabilities)
# • Background loop (start/stop) executes a proactive caching pass
# • Uses ToolManager + RBAC instead of importing Ray actors directly
# • Accepts task types:
#       - "observer.proactive_cache" (single pass)
#       - "observer.observe"         (single pass; alias)
#   All other tasks are rejected.
# -----------------------------------------------------------------------------

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import time
from typing import Any, Dict, Optional

from .base import BaseAgent
from .roles.rbac import authorize_tool
from .roles.specialization import Specialization

logger = logging.getLogger(__name__)


class ObserverAgent(BaseAgent):
    """
    Monitors working-memory miss patterns and proactively warms the cache
    with full records fetched from LTM.

    This agent is infra-facing (not guest-facing). It should be scheduled by
    maintenance flows or run in the background loop.
    """

    def __init__(
        self,
        agent_id: str = "observer",
        *,
        miss_threshold: int = 2,
        interval_s: float = 2.0,
        apply_changes: bool = True,
        **kwargs: Any,
    ):
        # You can introduce a dedicated specialization like Specialization.ONLOOKER
        # if it exists in your enum. Otherwise, ULA is acceptable for infra agents.
        super().__init__(agent_id=agent_id, specialization=Specialization.OBS, **kwargs)

        self.miss_threshold = int(miss_threshold)
        self.interval_s = float(interval_s)
        self.apply_changes = bool(apply_changes)

        self._stop_evt = asyncio.Event()
        self._loop_task: Optional[asyncio.Task] = None

        logger.info(
            "✅ ObserverAgent %s created (miss_threshold=%d, interval=%.2fs, apply_changes=%s)",
            self.agent_id, self.miss_threshold, self.interval_s, self.apply_changes
        )

    # -------------------------------------------------------------------------
    # Lifecycle controls (background loop)
    # -------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._loop_task and not self._loop_task.done():
            return
        self._stop_evt.clear()
        self._loop_task = asyncio.create_task(self._monitor_loop(), name=f"observer-{self.agent_id}")
        logger.info("🟢 ObserverAgent %s loop started", self.agent_id)

    async def stop(self) -> None:
        """Stop the background monitoring loop."""
        self._stop_evt.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=self.interval_s + 2.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        logger.info("🛑 ObserverAgent %s loop stopped", self.agent_id)

    async def _monitor_loop(self) -> None:
        """Periodic monitoring loop executing proactive passes."""
        while not self._stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                await self._proactive_pass()
                # treat a clean tick as a “success” for gentle capability EWMA
                self.state.record_task_outcome(
                    success=True, quality=1.0, salience=0.15,
                    duration_s=time.perf_counter() - t0, capability_observed=None
                )
            except Exception as e:
                logger.error("ObserverAgent %s pass error: %s", self.agent_id, e, exc_info=True)
                # soft-fail; still sleep
            # keep ~interval pacing
            elapsed = time.perf_counter() - t0
            await asyncio.wait([self._stop_evt.wait()], timeout=max(0.0, self.interval_s - elapsed))

    # -------------------------------------------------------------------------
    # Core proactive logic
    # -------------------------------------------------------------------------

    async def _proactive_pass(self) -> None:
        """
        Single pass:
          1) Ask MW store for top-N missed keys (N=1 for simplicity)
          2) If hottest exceeds threshold and not in cache
          3) Fetch full item from LTM and write into cache
        """
        # 1) Read top-missed keys from working memory store
        topn = await self._safe_tool_read("mw.topn", {"n": 1})
        if not topn or not isinstance(topn, (list, tuple)) or not topn:
            return

        # Expect entries like [{"uuid": "...","misses": 7}] or [["id", 7]]
        entry = topn[0]
        if isinstance(entry, dict):
            item_id = entry.get("uuid") or entry.get("id")
            miss_count = int(entry.get("misses", 0))
        else:
            try:
                item_id, miss_count = entry[0], int(entry[1])
            except Exception:
                return

        if not item_id or miss_count <= self.miss_threshold:
            return

        logger.info("[%s] Hot item detected: %s (misses=%d)", self.agent_id, item_id, miss_count)

        # 2) Check cache
        cache_key = f"global:item:{item_id}"
        existing = await self._safe_tool_read("cache.get", {"key": cache_key})
        if existing and existing.get("value"):
            logger.info("[%s] Item %s already cached; skip", self.agent_id, item_id)
            return

        # 3) Fetch from LTM
        ltm_doc = await self._safe_tool_read("ltm.query_by_id", {"id": item_id})
        if not ltm_doc:
            logger.warning("[%s] LTM returned no data for %s", self.agent_id, item_id)
            return

        # 4) Write into cache (if writes allowed)
        if not self.apply_changes:
            logger.info("[%s] Dry-run: would cache %s", self.agent_id, item_id)
            return

        write_res = await self._safe_tool_write("cache.set", {"key": cache_key, "value": ltm_doc})
        ok = bool(write_res and write_res.get("ok"))
        if ok:
            logger.info("✅ [%s] Proactively cached %s", self.agent_id, item_id)
        else:
            logger.warning("⚠️  [%s] Failed to cache %s (resp=%s)", self.agent_id, item_id, write_res)

        # Private memory update (non-blocking)
        try:
            self.update_private_memory(
                task_embed=None,
                peers=None,
                success=ok,
                quality=1.0 if ok else 0.3,
                latency_s=None,
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # Task entry (override): one-shot observe/proactive_cache
    # -------------------------------------------------------------------------

    async def execute_task(self, task) -> Dict[str, Any]:
        """
        Supports one-shot ops:
          • type: "observer.proactive_cache" or "observer.observe" → single pass
          • otherwise → reject (infra agent)
        """
        tv = self._coerce_task_view(task)
        ttype = (getattr(task, "type", None) or
                 tv.prompt or
                 (task.get("type") if isinstance(task, dict) else None) or "").lower()

        if ttype in ("observer.proactive_cache", "observer.observe"):
            await self._proactive_pass()
            return {
                "agent_id": self.agent_id,
                "task_id": tv.task_id,
                "success": True,
                "result": {"kind": "observer.pass_executed"},
                "meta": {"exec": {"started_at": self._utc_now_iso(), "kind": ttype}},
            }

        # everything else is not applicable for this agent
        return self._reject_result(tv, reason="agent_is_observer", started_ts=self._utc_now_iso(),
                                   started_monotonic=time.perf_counter())

    # -------------------------------------------------------------------------
    # Tool wrappers (RBAC + presence + timeout)
    # -------------------------------------------------------------------------

    async def _safe_tool_read(self, name: str, args: Dict[str, Any], timeout_s: float = 8.0) -> Optional[Dict[str, Any]]:
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

    async def _safe_tool_write(self, name: str, args: Dict[str, Any], timeout_s: float = 8.0) -> Optional[Dict[str, Any]]:
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
        try:
            dec = authorize_tool(
                role_profile=self.role_profile,
                tool_name=tool_name,
                cost_usd=0.0,
                context={"agent_id": self.agent_id, **(context or {})},
            )
            return bool(dec.allow)
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Introspection helpers
    # -------------------------------------------------------------------------

    async def get_status(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "specialization": getattr(self.specialization, "value", str(self.specialization)),
            "running": bool(self._loop_task and not self._loop_task.done()),
            "miss_threshold": self.miss_threshold,
            "interval_s": self.interval_s,
            "apply_changes": self.apply_changes,
        }

    def code_hash(self) -> str:
        """Simple code hash for version tracking."""
        return hashlib.md5(__file__.encode()).hexdigest()[:8]
