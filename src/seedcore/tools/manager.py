#!/usr/bin/env python
#seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List
import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# ============================================================
# Tool Protocol
# ============================================================

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

# ============================================================
# Errors
# ============================================================

class ToolError(Exception):
    """Custom exception for tool execution failures."""
    def __init__(self, tool_name: str, reason: str, original_exc: Optional[Exception] = None):
        self.tool_name = tool_name
        self.reason = reason
        self.original_exc = original_exc
        super().__init__(f"ToolError({tool_name}): {reason}")

# ============================================================
# Enhanced ToolManager
# ============================================================

class ToolManager:
    """
    Enhanced tool manager for SeedCore v2.

    New capabilities:
      • Namespaced tool registry (iot.read, memory.mw.read, memory.ltm.query, robot.move, train.skill)
      • Special memory-backed tools (MwManager + LongTermMemoryManager)
      • Call observability + metrics + tracing
      • Tool suggestions for agent learning
      • RBAC hooks (optional)
      • Async-safe dynamic registration
      • Self-improving tools (reflection-based feedback)
    """

    def __init__(
        self,
        *,
        mw_manager: Optional[Any] = None,
        ltm_manager: Optional[Any] = None,
        rbac_provider: Optional[Any] = None,
        enable_tracing: bool = True,
    ):
        self._tools: Dict[str, Tool] = {}
        self._lock = asyncio.Lock()

        # Memory integrations
        self.mw_manager = mw_manager
        self.ltm_manager = ltm_manager

        # Optional RBAC gateway
        self.rbac_provider = rbac_provider

        # Execution tracing
        self.enable_tracing = enable_tracing
        
        # Metrics
        self._call_count: Dict[str, int] = {}
        self._fail_count: Dict[str, int] = {}
        self._latency_hist: Dict[str, List[float]] = {}

        logger.info("🔧 ToolManager ready with memory integration")

    # ============================================================
    # Registration
    # ============================================================

    async def register(self, name: str, tool: Tool) -> None:
        """
        Register a namespaced tool (e.g., iot.read, robot.move).
        
        This method is async-safe.
        """
        async with self._lock:
            if name in self._tools:
                logger.warning(f"Tool overwritten: {name}")
            self._tools[name] = tool
            logger.info(f"Tool registered: {name}")

    async def unregister(self, name: str) -> None:
        """Safely unregister a tool."""
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"Tool removed: {name}")
            else:
                logger.warning(f"Attempted to unregister non-existent tool: {name}")

    async def has(self, name: str) -> bool:
        """Check if a tool is registered (async-safe)."""
        async with self._lock:
            return name in self._tools

    # ============================================================
    # Execution
    # ============================================================

    async def execute(self, name: str, args: Dict[str, Any], agent_id: Optional[str] = None) -> Any:
        """
        Execute a tool with robust error handling, RBAC, and metrics.
        
        Args:
            name: Tool name (e.g., "iot.read", "memory.mw.read")
            args: Tool arguments as a dictionary
            agent_id: Optional agent identifier for RBAC and tracing
        
        Raises:
            ToolError: If the tool is not found, RBAC denied, or fails during execution.
        """
        tool = self._tools.get(name)  # No lock needed for a simple read
        
        if tool is None:
            raise ToolError(tool_name=name, reason="tool_not_found")

        # Optional RBAC check
        if self.rbac_provider:
            try:
                # Assume rbac_provider has an async 'allowed' method
                if hasattr(self.rbac_provider, 'allowed'):
                    allowed = await self.rbac_provider.allowed(agent_id, name)
                    if not allowed:
                        raise ToolError(tool_name=name, reason="rbac_denied")
            except AttributeError:
                # Fallback: if rbac_provider doesn't have 'allowed', skip RBAC
                logger.debug("RBAC provider missing 'allowed' method, skipping RBAC check")

        start = time.perf_counter()

        try:
            # Pass args as kwargs for easier Pydantic-like validation
            result = await tool.execute(**args)
        except asyncio.TimeoutError:
            logger.warning(f"Tool execution timed out: {name}")
            self._fail_count[name] = self._fail_count.get(name, 0) + 1
            raise ToolError(tool_name=name, reason="timeout")
        except Exception as e:
            logger.error(f"Tool '{name}' failed for agent {agent_id}: {e}", exc_info=True)
            self._fail_count[name] = self._fail_count.get(name, 0) + 1
            raise ToolError(tool_name=name, reason=str(e), original_exc=e)

        # Metrics
        elapsed = time.perf_counter() - start
        self._call_count[name] = self._call_count.get(name, 0) + 1
        self._latency_hist.setdefault(name, []).append(elapsed)

        if self.enable_tracing:
            logger.info(f"📡 Tool call: {name} by {agent_id} ({elapsed:.3f}s)")

        # Tool may return "learning hints" via _reflection key
        if isinstance(result, dict) and result.get("_reflection"):
            await self._process_tool_reflection(agent_id, name, result["_reflection"])

        return result

    # ============================================================
    # Tool Reflection (Agents learn how to use tools better)
    # ============================================================

    async def _process_tool_reflection(self, agent_id: Optional[str], tool_name: str, reflection: Dict[str, Any]):
        """
        Tools can self-report:
            • skill deltas ("improve planning by +0.03")
            • warnings ("agent misused device API")
            • suggestions ("use hvac.set_mode before hvac.adjust_temp")
        
        This enables adaptive tool learning where tools teach agents
        how to use them better.
        """
        logger.info(f"🧠 Tool reflection from {tool_name} for agent {agent_id}: {reflection}")

        # TODO: integrate with agent skill store
        # e.g., self.skill_store.update(agent_id, reflection)
        # (This can be implemented when skill store is available)

    # ============================================================
    # Introspection
    # ============================================================

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

    def stats(self) -> Dict[str, Any]:
        """
        Return execution metrics for observability.
        
        Returns:
            Dictionary with call counts, failure counts, and latency histograms
        """
        return {
            "call_count": dict(self._call_count),
            "fail_count": dict(self._fail_count),
            "latency_ms": {
                name: [x * 1000 for x in hist[-50:]]  # last 50 samples in milliseconds
                for name, hist in self._latency_hist.items()
            }
        }