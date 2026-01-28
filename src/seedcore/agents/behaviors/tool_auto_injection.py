#!/usr/bin/env python3
"""
ToolAutoInjectionBehavior: Auto-adds tools for conversational tasks.

This behavior automatically adds the general_query tool to conversational
tasks that don't have explicit tools specified.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


def _sanitize_task_data_for_tool(task_data: Any) -> Dict[str, Any]:
    """
    Safely serialize task_data for tool calls, removing circular references.
    
    Only extracts task_id and params to avoid serialization issues.
    """
    if task_data is None:
        return {}

    # Case 1: Pydantic model (TaskPayload)
    if hasattr(task_data, "model_dump"):
        try:
            return task_data.model_dump(mode="json", exclude_none=False)
        except (TypeError, ValueError, AttributeError):
            try:
                return task_data.model_dump(exclude_none=False)
            except Exception:
                pass

    # Case 2: Dict
    if isinstance(task_data, dict):
        sanitized = {}
        if "task_id" in task_data:
            sanitized["task_id"] = task_data["task_id"]
        if "params" in task_data:
            params = task_data["params"]
            if isinstance(params, dict):
                sanitized["params"] = dict(params)
            else:
                sanitized["params"] = params
        return sanitized

    # Case 3: Object with __dict__
    if hasattr(task_data, "__dict__"):
        sanitized = {}
        attrs = task_data.__dict__
        if "task_id" in attrs:
            sanitized["task_id"] = attrs["task_id"]
        if "params" in attrs:
            params = attrs["params"]
            if isinstance(params, dict):
                sanitized["params"] = dict(params)
            else:
                sanitized["params"] = params
        return sanitized

    return {}


class ToolAutoInjectionBehavior(AgentBehavior):
    """
    Automatically adds general_query tool to conversational tasks.
    
    Configuration:
        auto_add_general_query: Whether to auto-add general_query tool (default: True)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._auto_add = self.get_config("auto_add_general_query", True)

    async def initialize(self) -> None:
        """Initialize tool auto-injection."""
        logger.debug(
            f"[{self.agent.agent_id}] ToolAutoInjectionBehavior initialized "
            f"(auto_add_general_query={self._auto_add})"
        )
        self._initialized = True

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Auto-add general_query tool for conversational tasks without explicit tools.
        """
        if not self.is_enabled() or not self._auto_add:
            return None

        params = task_dict.setdefault("params", {})
        routing = params.setdefault("routing", {})
        interaction = params.setdefault("interaction", {})
        chat = params.setdefault("chat", {})

        # Check for existing tools/tool calls
        existing_tools = (
            routing.get("tools")
            or params.get("tool_calls")
            or task_dict.get("tool_calls")
            or (getattr(task, "tool_calls", None) if hasattr(task, "tool_calls") else None)
            or []
        )

        # Normalize to list
        if existing_tools and not isinstance(existing_tools, list):
            existing_tools = [existing_tools] if existing_tools else []

        # Get task type
        task_type = (
            task_dict.get("type")
            or (getattr(task, "type", None) if hasattr(task, "type") else None)
            or ""
        )

        # Check if this is a conversational/query task
        is_chat_task = (
            task_type == "chat"
            or task_type == "query"
            or task_type == "general_query"
            or interaction.get("mode") == "agent_tunnel"
            or chat.get("message") is not None
            or task_dict.get("message") is not None
        )

        # Auto-add tool if needed
        if is_chat_task and not existing_tools:
            query_text = (
                chat.get("message")
                or task_dict.get("message")
                or task_dict.get("description")
                or (getattr(task, "description", None) if hasattr(task, "description") else None)
                or ""
            )

            if not query_text and task_type in ("query", "general_query", "chat"):
                query_text = task_dict.get("description") or ""

            if query_text or task_type in ("query", "general_query", "chat"):
                # Sanitize task_data to remove circular references
                sanitized_task_data = _sanitize_task_data_for_tool(task_dict)
                tool_call = {
                    "name": "general_query",
                    "args": {
                        "description": query_text or task_dict.get("description") or "",
                        "task_data": sanitized_task_data,
                    },
                }
                routing["tools"] = ["general_query"]
                task_dict["tool_calls"] = [tool_call]

                logger.debug(
                    f"[{self.agent.agent_id}] ✅ Auto-added general_query tool for {task_type} task"
                )

        return task_dict

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        logger.debug(f"[{self.agent.agent_id}] ToolAutoInjectionBehavior shutdown")
