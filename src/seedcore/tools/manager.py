#!/usr/bin/env python
#seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List
import asyncio
import logging

logger = logging.getLogger(__name__)

class Tool(Protocol):
    """
    Protocol for an executable tool.

    Tools must be async and expose a schema for observability.
    """
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool's core logic with provided arguments."""
        ...

    def schema(self) -> Dict[str, Any]:
        """
        Return an OpenAPI-like schema of the tool's arguments.
        
        Example:
            return {
                "name": "iot.read",
                "description": "Reads the state from an IoT device.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "device_id": {"type": "string", "description": "The ID of the device to read."},
                        "sensor": {"type": "string", "description": "The specific sensor to query."},
                    },
                    "required": ["device_id"],
                }
            }
        """
        ...

class ToolError(Exception):
    """Custom exception for tool execution failures."""
    def __init__(self, tool_name: str, reason: str, original_exc: Optional[Exception] = None):
        self.tool_name = tool_name
        self.reason = reason
        self.original_exc = original_exc
        super().__init__(f"ToolError({tool_name}): {reason}")


class ToolManager:
    """
    Manages the lifecycle and execution of registered tools.
    
    This class is async-safe and provides RBAC-aware execution.
    """
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._lock = asyncio.Lock()  # For safe dynamic registration

    async def register(self, name: str, tool: Tool) -> None:
        """
        Safely register a new tool instance.
        
        This method is async-safe.
        """
        async with self._lock:
            if name in self._tools:
                logger.warning(f"Tool {name} is being overwritten.")
            self._tools[name] = tool
            logger.info(f"Tool registered: {name}")

    async def unregister(self, name: str) -> None:
        """Safely unregister a tool."""
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"Tool unregistered: {name}")
            else:
                logger.warning(f"Attempted to unregister non-existent tool: {name}")

    async def has(self, name: str) -> bool:
        """Check if a tool is registered (async-safe)."""
        async with self._lock:
            return name in self._tools

    async def execute(self, name: str, args: Dict[str, Any]) -> Any:
        """
        Execute a tool with robust error handling.
        
        Raises:
            ToolError: If the tool is not found or fails during execution.
        """
        tool = self._tools.get(name) # No lock needed for a simple read
        
        if tool is None:
            raise ToolError(tool_name=name, reason="tool_not_found")
        
        try:
            # Pass args as kwargs for easier Pydantic-like validation
            return await tool.execute(**args)
        except asyncio.TimeoutError:
            logger.warning(f"Tool execution timed out: {name}")
            raise ToolError(tool_name=name, reason="timeout")
        except Exception as e:
            logger.error(f"Tool execution failed: {name} with args {args}. Error: {e}", exc_info=True)
            raise ToolError(tool_name=name, reason=str(e), original_exc=e)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Return a manifest of all registered tools and their schemas.
        """
        async with self._lock:
            # Copy items to avoid modification during iteration
            tools = list(self._tools.values())
            
        manifest = []
        for tool in tools:
            try:
                manifest.append(tool.schema())
            except Exception as e:
                logger.warning(f"Failed to get schema for tool: {e}")
        return manifest

    async def get_tool_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the schema for a single tool."""
        tool = self._tools.get(name)
        if tool:
            try:
                return tool.schema()
            except Exception as e:
                logger.warning(f"Failed to get schema for tool {name}: {e}")
        return None