#!/usr/bin/env python3
"""
DedupBehavior: Manages idempotency cache.

This behavior prevents duplicate command execution by tracking
recently seen command IDs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class DedupBehavior(AgentBehavior):
    """
    Manages idempotency cache to prevent duplicate executions.
    
    Configuration:
        ttl_s: Time-to-live for dedup entries in seconds (default: 60.0)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._ttl_s = float(self.get_config("ttl_s", 60.0))
        self._seen: Dict[str, float] = {}  # {key: monotonic_deadline}
        self._seen_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize dedup cache."""
        logger.debug(
            f"[{self.agent.agent_id}] DedupBehavior initialized (ttl_s={self._ttl_s})"
        )
        self._initialized = True

    async def seen_recently(self, key: str) -> bool:
        """
        Check if key was seen recently.
        
        Args:
            key: Key to check (e.g., command_id)
            
        Returns:
            True if key was seen within TTL, False otherwise
        """
        if not self.is_enabled():
            return False

        now = time.monotonic()
        async with self._seen_lock:
            # Purge expired entries
            expired = [k for k, dl in self._seen.items() if dl <= now]
            for k in expired:
                self._seen.pop(k, None)

            return key in self._seen

    async def mark_seen(self, key: str) -> None:
        """
        Mark key as seen (add to cache with TTL).
        
        Args:
            key: Key to mark (e.g., command_id)
        """
        if not self.is_enabled():
            return

        async with self._seen_lock:
            self._seen[key] = time.monotonic() + self._ttl_s

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check for duplicate tasks before execution.
        
        Extracts command_id or task_id and checks if seen recently.
        """
        if not self.is_enabled():
            return None

        # Extract key from task (command_id, job_id, or task_id)
        key = (
            task_dict.get("command_id")
            or task_dict.get("job_id")
            or task_dict.get("task_id")
            or task_dict.get("id")
            or None
        )

        if not key:
            return None  # No key to check

        key_str = str(key)
        if await self.seen_recently(key_str):
            # Task is duplicate
            logger.info(
                f"[{self.agent.agent_id}] Task {key_str} is duplicate (dedup cache hit)"
            )
            # Return a dedup result (BaseAgent will handle this)
            from seedcore.models.result_schema import make_envelope

            dedup_result = make_envelope(
                task_id=key_str,
                success=True,
                payload={"agent_id": self.agent.agent_id, "dedup": True, "key": key_str},
                error=None,
                error_type=None,
                retry=False,
                decision_kind=None,
                meta={"exec": {"kind": "dedup"}},
                path="agent",
            )

            # Raise special exception that BaseAgent can catch
            raise TaskDedupedError(dedup_result)

        # Mark as seen (will be executed)
        await self.mark_seen(key_str)
        return None  # No modification needed

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        async with self._seen_lock:
            self._seen.clear()
        logger.debug(f"[{self.agent.agent_id}] DedupBehavior shutdown")


class TaskDedupedError(Exception):
    """Exception raised when a task is deduplicated."""
    
    def __init__(self, dedup_result: Dict[str, Any]):
        self.dedup_result = dedup_result
        super().__init__(f"Task deduplicated: {dedup_result.get('task_id', 'unknown')}")
