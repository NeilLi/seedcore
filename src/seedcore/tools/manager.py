#!/usr/bin/env python
#seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List, TYPE_CHECKING
import asyncio
import logging
import time

if TYPE_CHECKING:
    from seedcore.agents.roles import SkillStoreProtocol
    from seedcore.serve.mcp_client import MCPServiceClient

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

    Acts as a unified router for both internal (Python) tools
    and external (MCP service) tools.

    New capabilities:
      • Namespaced tool registry (iot.read, memory.mw.read, memory.ltm.query, robot.move, train.skill)
      • Special memory-backed tools (MwManager + LongTermMemoryManager)
      • External MCP tools integration (internet.fetch, fs.read, etc.)
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
        skill_store: Optional["SkillStoreProtocol"] = None,
        enable_tracing: bool = True,
        mcp_client: Optional["MCPServiceClient"] = None,
    ):
        # Internal tools registry (IoT, robotics, etc.)
        self._tools: Dict[str, Tool] = {}
        self._lock = asyncio.Lock()

        # External MCP service client (for internet.fetch, fs.read, etc.)
        self._mcp_client = mcp_client

        # Memory integrations
        self.mw_manager = mw_manager
        self.ltm_manager = ltm_manager

        # Optional RBAC gateway
        self.rbac_provider = rbac_provider

        # Skill store for agent learning (micro-flywheel)
        self.skill_store = skill_store

        # Execution tracing
        self.enable_tracing = enable_tracing
        
        # Metrics
        self._call_count: Dict[str, int] = {}
        self._fail_count: Dict[str, int] = {}
        self._latency_hist: Dict[str, List[float]] = {}

        if mcp_client:
            logger.info("🔧 ToolManager ready with memory integration and MCP client")
        else:
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

    def register_internal(self, tool: Tool) -> None:
        """
        Registers an internal tool (IoT, robotics) that adheres to the Tool protocol.
        
        This is a synchronous convenience method that extracts the tool name
        from the schema and registers it.
        
        Args:
            tool: A tool instance implementing the Tool protocol.
        """
        try:
            schema = tool.schema()
            tool_name = schema.get("name")
            
            if not tool_name:
                logger.error("Failed to register tool: schema missing 'name'.")
                return

            # Direct dict access (synchronous) - tools dict is thread-safe for reads
            # but we're doing a write here. In practice, this is fine for initialization.
            if tool_name in self._tools:
                logger.warning(f"Overwriting tool in registry: {tool_name}")
            
            self._tools[tool_name] = tool
            logger.debug(f"Registered internal tool: {tool_name}")
            
        except Exception as e:
            logger.error(f"Failed to register tool: {e}", exc_info=True)

    async def unregister(self, name: str) -> bool:
        """
        Safely unregister a tool.
        
        Args:
            name: Tool name to unregister
            
        Returns:
            True if tool was removed, False if it didn't exist
        """
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info(f"Tool removed: {name}")
                return True
            else:
                logger.warning(f"Attempted to unregister non-existent tool: {name}")
                return False

    async def has(self, name: str) -> bool:
        """
        Check if an internal tool is registered.
        
        Note: This only checks internal tools. External MCP tools are handled
        dynamically by execute() when needed.
        
        Args:
            name: Tool name to check
            
        Returns:
            True if tool is registered internally, False otherwise
        """
        async with self._lock:
            return name in self._tools

    # ============================================================
    # Execution
    # ============================================================

    async def execute(self, name: str, args: Dict[str, Any], agent_id: Optional[str] = None) -> Any:
        """
        Execute a tool with robust error handling, RBAC, and metrics.
        
        Automatically routes to internal tools first, then falls back to
        external MCP service if the tool is not found internally.
        
        Args:
            name: Tool name (e.g., "iot.read", "memory.mw.read", "internet.fetch")
            args: Tool arguments as a dictionary
            agent_id: Optional agent identifier for RBAC and tracing
        
        Raises:
            ToolError: If the tool is not found, RBAC denied, or fails during execution.
        """
        logger.debug(f"ToolManager executing: {name}")
        
        # Optional RBAC check (before execution) - using EAFP pattern
        if self.rbac_provider:
            try:
                allowed = await self.rbac_provider.allowed(agent_id, name)
                if not allowed:
                    raise ToolError(tool_name=name, reason="rbac_denied")
            except AttributeError:
                # RBAC provider doesn't have 'allowed' method, skip RBAC
                logger.debug("RBAC provider missing 'allowed' method, skipping RBAC check")
            except Exception:
                # Other RBAC errors are logged but don't block execution
                logger.debug("RBAC check failed, skipping", exc_info=True)

        start = time.perf_counter()
        execution_failed = False

        try:
            # --- 1. Check Internal Tools First ---
            tool = self._tools.get(name)  # No lock needed for a simple read
            
            if tool is not None:
                # Internal tool found - execute it
                result = await tool.execute(**args)
            else:
                # --- 2. Not internal? Try External MCP ---
                if not self._mcp_client:
                    raise ToolError(tool_name=name, reason="tool_not_found")
                
                # Forward to MCP service
                logger.debug(f"Routing tool '{name}' to MCP service")
                response = await self._mcp_client.call_tool_async(
                    tool_name=name,
                    arguments=args
                )
                
                # Check for a JSON-RPC level error
                if "error" in response and response["error"]:
                    err = response["error"]
                    error_msg = err.get("message", "Unknown error")
                    raise ToolError(tool_name=name, reason=f"External tool failed: {error_msg}")
                
                # Return the actual result, not the full JSON-RPC response
                result = response.get("result")
                
        except ToolError:
            # Mark as failed and re-raise
            execution_failed = True
            raise
        except asyncio.TimeoutError:
            execution_failed = True
            logger.warning(f"Tool execution timed out: {name}")
            raise ToolError(tool_name=name, reason="timeout")
        except Exception as e:
            execution_failed = True
            logger.error(f"Tool '{name}' failed for agent {agent_id}: {e}", exc_info=True)
            raise ToolError(tool_name=name, reason=str(e), original_exc=e)
        finally:
            # Centralized failure counting
            if execution_failed:
                self._fail_count[name] = self._fail_count.get(name, 0) + 1

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
        
        This is the critical "push" mechanism of the agent-skill micro-flywheel:
        tools produce learning → manager consumes learning → skill store updates agent.
        """
        logger.info(f"🧠 Tool reflection from {tool_name} for agent {agent_id}: {reflection}")

        # --- IMPLEMENTATION ---
        if not self.skill_store or not agent_id:
            return  # Cannot learn without a store or agent context

        # Check for a single skill update
        skill = reflection.get("skill")
        delta = reflection.get("delta")
        
        if skill and delta is not None:
            try:
                delta = float(delta)
                # This is the flywheel's "push"
                # Try update_skill_delta first (if implemented as extension)
                if hasattr(self.skill_store, "update_skill_delta"):
                    await self.skill_store.update_skill_delta(agent_id, skill, delta)
                elif hasattr(self.skill_store, "apply_delta"):
                    # Fallback to apply_delta if available
                    await self.skill_store.apply_delta(agent_id, skill, delta)
                else:
                    # Standard SkillStoreProtocol pattern: load, update, save
                    current_deltas = await self.skill_store.load(agent_id)
                    if current_deltas is None:
                        current_deltas = {}
                    # Apply the delta (additive update)
                    current_deltas[skill] = current_deltas.get(skill, 0.0) + delta
                    # Save the updated deltas
                    await self.skill_store.save(agent_id, current_deltas, metadata={
                        "source": "tool_reflection",
                        "tool": tool_name,
                        "skill": skill,
                        "delta": delta
                    })
            except Exception as e:
                logger.warning(f"Failed to apply skill delta from {tool_name}: {e}", exc_info=True)
        # ----------------------

    # ============================================================
    # Introspection
    # ============================================================

    async def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        Returns a merged dictionary of all available tools, both internal and external.
        
        Returns:
            Dictionary mapping tool names to their schemas.
            Internal tools take precedence over external tools in case of conflicts.
        """
        # 1. Get all internal tool schemas
        all_schemas: Dict[str, Dict[str, Any]] = {}
        
        async with self._lock:
            # Copy items to avoid modification during iteration
            tools = list(self._tools.values())
        
        for tool in tools:
            try:
                schema = tool.schema()
                name = schema.get("name")
                if name:
                    all_schemas[name] = schema
            except Exception as e:
                logger.warning(f"Failed to get schema for tool: {e}")

        # 2. Get all external tool schemas from the MCP service
        if self._mcp_client:
            try:
                mcp_response = await self._mcp_client.list_tools_async()
                
                # The MCP spec returns tools in a list under the "tools" key
                external_tools_list = mcp_response.get("tools", [])
                
                for tool_schema in external_tools_list:
                    name = tool_schema.get("name")
                    if name and name not in all_schemas:
                        all_schemas[name] = tool_schema
                    elif name:
                        logger.warning(
                            f"External tool '{name}' conflicts with internal tool. "
                            "Internal tool takes precedence."
                        )
                        
            except Exception as e:
                logger.error(f"Failed to fetch external tools from MCP service: {e}")
                # We can still return the internal tools
        
        return all_schemas

    async def get_tool_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get the schema for a single tool (internal or external).
        
        This delegates to list_tools() to get unified tool schemas.
        
        Args:
            name: Tool name to get schema for
            
        Returns:
            Tool schema if found, None otherwise
        """
        all_tools = await self.list_tools()
        return all_tools.get(name)

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