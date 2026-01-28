#!/usr/bin/env python3
"""
BackgroundLoopBehavior: Runs periodic background tasks.

This behavior manages a background loop that executes a method periodically.
Used by environment agents, observer agents, and orchestration agents.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class BackgroundLoopBehavior(AgentBehavior):
    """
    Manages a background loop that executes a method periodically.
    
    Configuration:
        interval_s: Interval between executions in seconds (default: 10.0)
        method: Method name to call on agent (default: "control_tick")
        max_errors: Maximum consecutive errors before stopping (default: 3)
        auto_start: Whether to start loop automatically (default: True)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._interval_s = float(self.get_config("interval_s", 10.0))
        self._method_name = str(self.get_config("method", "control_tick"))
        self._max_errors = int(self.get_config("max_errors", 3))
        self._auto_start = self.get_config("auto_start", True)

        self._loop_task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self._err_streak = 0
        self._method: Optional[Callable] = None

    async def initialize(self) -> None:
        """Initialize background loop and find method to call."""
        # Find method on agent
        self._method = getattr(self.agent, self._method_name, None)
        if not self._method:
            logger.warning(
                f"[{self.agent.agent_id}] BackgroundLoopBehavior: method '{self._method_name}' "
                f"not found on agent. Loop will not run."
            )
            return

        if not callable(self._method):
            logger.warning(
                f"[{self.agent.agent_id}] BackgroundLoopBehavior: '{self._method_name}' "
                f"is not callable. Loop will not run."
            )
            self._method = None
            return

        logger.debug(
            f"[{self.agent.agent_id}] BackgroundLoopBehavior initialized "
            f"(method={self._method_name}, interval={self._interval_s}s, "
            f"max_errors={self._max_errors}, auto_start={self._auto_start})"
        )
        self._initialized = True

        if self._auto_start and self._method:
            await self.start()

    async def start(self) -> None:
        """Start the background loop."""
        if self._loop_task and not self._loop_task.done():
            logger.debug(f"[{self.agent.agent_id}] Background loop already running")
            return

        if not self._method:
            logger.warning(
                f"[{self.agent.agent_id}] Cannot start background loop: method not found"
            )
            return

        self._stop_evt.clear()
        self._err_streak = 0
        self._loop_task = asyncio.create_task(
            self._run_loop(), name=f"bg-loop-{self.agent.agent_id}"
        )
        logger.info(
            f"🟢 [{self.agent.agent_id}] Background loop started "
            f"(method={self._method_name}, interval={self._interval_s}s)"
        )

    async def stop(self) -> None:
        """Stop the background loop."""
        self._stop_evt.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(
                    self._loop_task, timeout=self._interval_s + 2.0
                )
            except asyncio.TimeoutError:
                self._loop_task.cancel()
        logger.info(f"🛑 [{self.agent.agent_id}] Background loop stopped")

    async def _run_loop(self) -> None:
        """Main loop that executes method periodically."""
        while not self._stop_evt.is_set():
            t0 = time.perf_counter()
            try:
                # Call the method (supports both sync and async)
                if asyncio.iscoroutinefunction(self._method):
                    await self._method()
                else:
                    self._method()

                self._err_streak = 0
            except Exception as e:
                self._err_streak += 1
                logger.warning(
                    f"[{self.agent.agent_id}] Background loop error "
                    f"(streak={self._err_streak}): {e}",
                    exc_info=True,
                )

                if self._err_streak >= self._max_errors:
                    logger.error(
                        f"🚨 [{self.agent.agent_id}] Background loop tripping circuit breaker "
                        f"after {self._err_streak} errors"
                    )
                    break  # Exit loop permanently

            finally:
                # Record as low-salience background activity
                try:
                    if hasattr(self.agent, "state"):
                        self.agent.state.record_task_outcome(
                            success=True,
                            quality=0.9,
                            salience=0.1,
                            duration_s=time.perf_counter() - t0,
                            capability_observed=None,
                        )
                except Exception:
                    pass

            # Wait for next interval
            elapsed = time.perf_counter() - t0
            remaining_time = max(0.0, self._interval_s - elapsed)
            if remaining_time > 0:
                try:
                    await asyncio.wait_for(
                        self._stop_evt.wait(),
                        timeout=remaining_time
                    )
                except asyncio.TimeoutError:
                    pass  # Timeout expired, continue loop

    async def shutdown(self) -> None:
        """Stop loop and cleanup on shutdown."""
        await self.stop()
        self._method = None
        logger.debug(f"[{self.agent.agent_id}] BackgroundLoopBehavior shutdown")
