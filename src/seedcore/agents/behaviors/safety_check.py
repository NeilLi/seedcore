#!/usr/bin/env python3
"""
SafetyCheckBehavior: Performs safety validation.

This behavior performs safety checks on commands/tasks before execution.
Used by orchestration agents to prevent dangerous operations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class SafetyCheckBehavior(AgentBehavior):
    """
    Performs safety validation on tasks/commands.
    
    Configuration:
        enabled: Whether safety checks are enabled (default: True)
        deny_patterns: List of patterns to deny (e.g., ["unlock_all", "disable_alarm"])
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._deny_patterns: list[str] = []
        self._enabled = self.get_config("enabled", True)

    async def initialize(self) -> None:
        """Initialize safety check with deny patterns."""
        deny_patterns = self.get_config("deny_patterns", [])
        if isinstance(deny_patterns, list):
            self._deny_patterns = [str(p).lower() for p in deny_patterns]
        elif isinstance(deny_patterns, str):
            self._deny_patterns = [deny_patterns.lower()]
        else:
            self._deny_patterns = []

        # Default deny patterns if none provided
        if not self._deny_patterns:
            self._deny_patterns = ["unlock_all", "disable_alarm"]

        logger.debug(
            f"[{self.agent.agent_id}] SafetyCheckBehavior initialized "
            f"(enabled={self._enabled}, deny_patterns={self._deny_patterns})"
        )
        self._initialized = True

    async def check(self, obj: Dict[str, Any]) -> bool:
        """
        Perform safety check on object.
        
        Args:
            obj: Object to check (task, command, etc.)
            
        Returns:
            True if safe, False if unsafe
        """
        if not self.is_enabled():
            return True  # Safety checks disabled = allow all

        try:
            action = str(obj.get("action") or obj.get("kind") or "").lower()
            if not action:
                return True  # No action = safe

            # Check against deny patterns
            for pattern in self._deny_patterns:
                if pattern in action:
                    logger.warning(
                        f"[{self.agent.agent_id}] Safety check failed: "
                        f"action '{action}' matches deny pattern '{pattern}'"
                    )
                    return False

            return True
        except Exception as e:
            logger.warning(
                f"[{self.agent.agent_id}] Safety check exception: {e}",
                exc_info=True,
            )
            return False  # Fail closed on error

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Perform safety check before task execution.
        """
        if not self.is_enabled():
            return None

        # Extract payload/params for safety check
        payload = task_dict.get("params", {}) or {}
        if isinstance(payload, dict):
            commands = payload.get("commands") or payload.get("command") or []
            if isinstance(commands, dict):
                commands = [commands]
            elif not isinstance(commands, list):
                commands = []

            # Check each command
            for cmd in commands:
                if isinstance(cmd, dict):
                    if not await self.check(cmd):
                        # Safety check failed
                        task_id = (
                            task_dict.get("task_id")
                            or task_dict.get("id")
                            or "unknown"
                        )

                        from seedcore.models.result_schema import make_envelope

                        safety_result = make_envelope(
                            task_id=str(task_id),
                            success=False,
                            payload={"agent_id": self.agent.agent_id},
                            error="Safety check failed",
                            error_type="safety_check_failed",
                            retry=False,
                            decision_kind=None,
                            meta={"exec": {"kind": "safety_check_reject"}},
                            path="agent",
                        )

                        raise SafetyCheckFailedError(safety_result)

        return None  # No modification needed

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self._deny_patterns.clear()
        logger.debug(f"[{self.agent.agent_id}] SafetyCheckBehavior shutdown")


class SafetyCheckFailedError(Exception):
    """Exception raised when a safety check fails."""
    
    def __init__(self, safety_result: Dict[str, Any]):
        self.safety_result = safety_result
        super().__init__(f"Safety check failed: {safety_result.get('error', 'unknown')}")
