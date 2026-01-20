#!/usr/bin/env python3
"""
ToolRegistrationBehavior: Registers tools dynamically.

This behavior registers specific tools when the agent is initialized.
Used by orchestration agents to register Tuya tools, etc.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .base import AgentBehavior

logger = logging.getLogger(__name__)


class ToolRegistrationBehavior(AgentBehavior):
    """
    Registers tools dynamically during agent initialization.
    
    Configuration:
        tools: List of tool names to register (e.g., ["tuya.send_command"])
        register_on_init: Whether to register immediately (default: True)
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(agent, config)
        self._tools: List[str] = []
        self._register_on_init = self.get_config("register_on_init", True)

    async def initialize(self) -> None:
        """Register tools during initialization."""
        tools = self.get_config("tools", [])
        if isinstance(tools, list):
            self._tools = [str(t) for t in tools]
        elif isinstance(tools, str):
            self._tools = [tools]
        else:
            self._tools = []

        if self._register_on_init and self._tools:
            await self._register_tools()

        logger.debug(
            f"[{self.agent.agent_id}] ToolRegistrationBehavior initialized "
            f"(tools={self._tools}, register_on_init={self._register_on_init})"
        )
        self._initialized = True

    async def _register_tools(self) -> None:
        """Register tools in tool handler."""
        if not self._tools:
            return

        # Ensure tool handler is initialized
        if hasattr(self.agent, "_ensure_tool_handler"):
            try:
                await self.agent._ensure_tool_handler()
            except Exception as e:
                logger.warning(
                    f"[{self.agent.agent_id}] Failed to ensure tool handler: {e}"
                )
                return

        tool_handler = getattr(self.agent, "tool_handler", None)
        if not tool_handler:
            logger.warning(
                f"[{self.agent.agent_id}] No tool handler available for tool registration"
            )
            return

        # Handle sharded tool handler
        if isinstance(tool_handler, list):
            # Register in all shards
            for shard in tool_handler:
                for tool_name in self._tools:
                    if hasattr(shard, "register_tool"):
                        try:
                            await shard.register_tool.remote(tool_name)
                        except Exception as e:
                            logger.warning(
                                f"[{self.agent.agent_id}] Failed to register tool '{tool_name}' "
                                f"in shard: {e}"
                            )
        else:
            # Single tool handler
            for tool_name in self._tools:
                if hasattr(tool_handler, "register_tool"):
                    try:
                        await tool_handler.register_tool(tool_name)
                    except Exception as e:
                        logger.warning(
                            f"[{self.agent.agent_id}] Failed to register tool '{tool_name}': {e}"
                        )

        logger.info(
            f"[{self.agent.agent_id}] ✅ Registered {len(self._tools)} tools: {self._tools}"
        )

    async def shutdown(self) -> None:
        """Cleanup on shutdown."""
        self._tools.clear()
        logger.debug(f"[{self.agent.agent_id}] ToolRegistrationBehavior shutdown")
