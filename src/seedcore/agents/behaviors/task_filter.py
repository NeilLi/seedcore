#!/usr/bin/env python3
"""
TaskFilterBehavior: Filters tasks by type/pattern.

This behavior rejects tasks that don't match allowed types, enabling
infrastructure-facing agents to reject guest-facing tasks.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import AgentBehavior
from seedcore.models.result_schema import make_envelope

logger = logging.getLogger(__name__)


class TaskFilterBehavior(AgentBehavior):
    """
    Filters tasks by type/pattern.
    
    Configuration:
        allowed_types: List of allowed task types (e.g., ["env.tick", "environment.tick"])
        reject_reason: Reason string for rejected tasks (default: "task_type_not_allowed")
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._allowed_types: List[str] = []
        self._reject_reason = self.get_config("reject_reason", "task_type_not_allowed")

    async def initialize(self) -> None:
        """Initialize task filter with allowed types."""
        allowed_types = self.get_config("allowed_types", [])
        if isinstance(allowed_types, list):
            self._allowed_types = [str(t).lower() for t in allowed_types]
        elif isinstance(allowed_types, str):
            self._allowed_types = [allowed_types.lower()]
        else:
            self._allowed_types = []

        logger.debug(
            f"[{self.agent.agent_id}] TaskFilterBehavior initialized "
            f"(allowed_types={self._allowed_types})"
        )
        self._initialized = True

    def _extract_task_type(self, task: Any) -> str:
        """Extract task type from task object or dict."""
        if isinstance(task, dict):
            return str(task.get("type", "")).lower()
        return str(getattr(task, "type", "")).lower()

    def _is_allowed(self, task_type: str) -> bool:
        """Check if task type is allowed."""
        if not self._allowed_types:
            # No filter configured = allow all
            return True
        return task_type.lower() in self._allowed_types

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Filter task before execution.
        
        Returns:
            None if task should be rejected (will raise rejection result)
            task_dict if task is allowed
        """
        if not self.is_enabled() or not self._allowed_types:
            return None  # No filtering

        task_type = self._extract_task_type(task)
        if not self._is_allowed(task_type):
            # Reject task
            task_id = (
                task_dict.get("task_id")
                or task_dict.get("id")
                or getattr(task, "task_id", None)
                or getattr(task, "id", None)
                or "unknown"
            )

            logger.warning(
                f"[{self.agent.agent_id}] Task rejected by TaskFilterBehavior: "
                f"type='{task_type}' not in allowed_types={self._allowed_types}"
            )

            # Create rejection result
            rejection_result = make_envelope(
                task_id=str(task_id),
                success=False,
                payload={"agent_id": self.agent.agent_id},
                error=f"Task type '{task_type}' not allowed for this agent",
                error_type=self._reject_reason,
                retry=False,
                decision_kind=None,
                meta={"exec": {"kind": "task_filter_reject", "task_type": task_type}},
                path="agent",
            )

            # Raise as a special exception that BaseAgent can catch
            raise TaskRejectedError(rejection_result)

        return None  # Task allowed, no modification needed

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self._allowed_types.clear()
        logger.debug(f"[{self.agent.agent_id}] TaskFilterBehavior shutdown")


class TaskRejectedError(Exception):
    """Exception raised when a task is rejected by TaskFilterBehavior."""
    
    def __init__(self, rejection_result: Dict[str, Any]):
        self.rejection_result = rejection_result
        super().__init__(f"Task rejected: {rejection_result.get('error', 'unknown')}")
