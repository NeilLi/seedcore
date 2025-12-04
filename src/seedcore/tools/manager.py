#!/usr/bin/env python
# seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List, TYPE_CHECKING, Callable
import asyncio
import logging
import time

from seedcore.serve.ml_client import MLServiceClient

if TYPE_CHECKING:
    from seedcore.agents.roles import SkillStoreProtocol
    from seedcore.serve.mcp_client import MCPServiceClient
    from seedcore.serve.cognitive_client import CognitiveServiceClient
    from seedcore.memory.mw_manager import MwManager
    from seedcore.memory.holon_fabric import HolonFabric

logger = logging.getLogger(__name__)

# ============================================================
# Tool Protocol
# ============================================================


class Tool(Protocol):
    async def execute(self, **kwargs: Any) -> Any: ...

    def schema(self) -> Dict[str, Any]: ...


# ============================================================
# Errors
# ============================================================


class ToolError(Exception):
    def __init__(
        self, tool_name: str, reason: str, original_exc: Optional[Exception] = None
    ):
        self.tool_name = tool_name
        self.reason = reason
        self.original_exc = original_exc
        super().__init__(f"ToolError({tool_name}): {reason}")


# ============================================================
# Enhanced ToolManager (v2.1)
# ============================================================


class ToolManager:
    """
    Core unified tool router for SeedCore v2.1.

    Execution priority:
    1. Internal registered Python tools (including query tools from query_tools.py:
       general_query, knowledge.find, task.collaborative, cognitive.*)
    2. Memory: MW tools (memory.mw.*)
    3. Memory: HolonFabric tools (memory.holon.*)
    4. Cognitive service tools (cog.* or reason.*)
    5. External MCP service tools

    Query tools are registered via register_query_tools() and handled as internal tools.
    They provide high-level abstractions for general queries, knowledge finding, and
    collaborative task execution.

    Thread Safety:
    This class is designed to be shared across multiple agents concurrently. All shared
    state (tool registry, metrics) is protected by asyncio.Lock() to ensure thread-safe
    access. The ToolManager instance can be safely passed to multiple agents running
    in parallel (e.g., via Ray actors).

    Concurrency Model:
    - Tool registry operations (_tools dict): Protected by _lock
    - Metrics updates (_call_count, _fail_count, _latency_hist): Protected by _metrics_lock
    - Separate locks reduce contention between tool lookups and metrics updates
    """

    def __init__(
        self,
        *,
        mw_manager: Optional["MwManager"] = None,
        holon_fabric: Optional["HolonFabric"] = None,
        rbac_provider: Optional[Any] = None,
        skill_store: Optional["SkillStoreProtocol"] = None,
        enable_tracing: bool = True,
        mcp_client: Optional["MCPServiceClient"] = None,
        cognitive_client: Optional["CognitiveServiceClient"] = None,
        ml_client: Optional["MLServiceClient"] = None,
    ):
        # Internal tool registry
        self._tools: Dict[str, Tool] = {}
        self._lock = asyncio.Lock()  # Lock for tool registry operations

        # Separate lock for metrics to reduce contention
        # Metrics are updated frequently during execution, so we use a separate lock
        self._metrics_lock = asyncio.Lock()

        # Service dependencies
        self.mw_manager = mw_manager
        self.holon_fabric = holon_fabric
        # Deprecated: kept for backward compatibility
        self.ltm_manager = None
        self._mcp_client = mcp_client
        self.cognitive_client = cognitive_client
        self.ml_client = ml_client
        self.rbac_provider = rbac_provider
        self.skill_store = skill_store
        self.enable_tracing = enable_tracing

        # Metrics (thread-safe access required for concurrent agent execution)
        self._call_count: Dict[str, int] = {}
        self._fail_count: Dict[str, int] = {}
        self._latency_hist: Dict[str, List[float]] = {}
        self._last_error: Dict[str, str] = {}  # Track last error per tool for debugging

        logger.info("🔧 ToolManager initialized (v2.1+)")

    # ============================================================
    # Registration APIs
    # ============================================================

    async def register(self, name: str, tool: Tool) -> None:
        async with self._lock:
            if name in self._tools:
                logger.warning(f"⚠️ Tool overwritten: {name}")
            self._tools[name] = tool
        logger.info(f"Tool registered: {name}")

    async def register_internal(self, tool: Tool) -> None:
        """
        Register an internal tool (thread-safe).

        Note: Changed to async to use proper locking. Callers should await this.
        """
        schema = tool.schema()
        name = schema.get("name")
        if not name:
            logger.error("Tool schema missing 'name' field.")
            return
        async with self._lock:
            if name in self._tools:
                logger.warning(f"⚠️ Overwriting internal tool: {name}")
            self._tools[name] = tool
        logger.debug(f"Registered internal tool: {name}")

    async def register_namespace(self, prefix: str, builder: Callable[[], Tool]):
        """
        Helper: register all tools from a namespace automatically.
        Tools must expose schema with name starting with prefix.
        """
        tool = builder()
        schema = tool.schema()
        name = schema.get("name")
        if not name or not name.startswith(prefix):
            raise ValueError(
                f"Invalid namespace tool: expected prefix '{prefix}', got '{name}'"
            )
        await self.register(name, tool)

    async def unregister(self, name: str) -> bool:
        async with self._lock:
            if name in self._tools:
                del self._tools[name]
                return True
            return False

    async def has(self, name: str) -> bool:
        async with self._lock:
            return name in self._tools

    # ============================================================
    # Memory Tool Routing
    # ============================================================

    async def _execute_mw(self, name: str, args: Dict[str, Any], agent_id: str):
        if not self.mw_manager:
            raise ToolError(name, "MW manager not configured")
        try:
            method = name.split(".", 2)[-1]
            handler = getattr(self.mw_manager, method, None)
            if not handler:
                raise ToolError(name, f"Unknown MW method '{method}'")
            return await handler(**args)
        except Exception as e:
            raise ToolError(name, "MW execute failed", e)

    async def _execute_holon(self, name: str, args: Dict[str, Any], agent_id: str):
        """Execute HolonFabric operations.

        Note: LongTermMemoryManager is deprecated. Use HolonFabric instead.
        This method provides backward compatibility for memory.ltm.* tool calls.
        """
        if not self.holon_fabric:
            raise ToolError(name, "HolonFabric not configured")
        try:
            method = name.split(".", 2)[-1]
            # Map legacy LTM method names to HolonFabric operations
            if method == "query":
                # Query by ID - use graph store to find node, then retrieve from vector store
                holon_id = args.get("holon_id")
                if not holon_id:
                    raise ToolError(name, "Missing holon_id parameter")
                # Try to get from graph store first
                try:
                    neighbors = await self.holon_fabric.graph.get_neighbors(
                        holon_id, limit=1
                    )
                    if neighbors:
                        # Found in graph, construct a basic Holon from metadata
                        node_data = (
                            neighbors[0] if isinstance(neighbors, list) else neighbors
                        )
                        props = node_data.get("props", {})
                        return {
                            "id": holon_id,
                            "type": props.get("type", "fact"),
                            "scope": props.get("scope", "global"),
                            "summary": node_data.get("summary", ""),
                            "content": props,
                        }
                except Exception:
                    pass
                # Fallback: return None if not found
                return None
            elif method == "search":
                # Vector similarity search
                embedding = args.get("embedding")
                limit = args.get("limit", 5)
                if not embedding:
                    raise ToolError(name, "Missing embedding parameter")
                import numpy as np

                query_vec = np.array(embedding, dtype=np.float32)
                # Use GLOBAL scope by default, can be extended with scopes parameter
                from seedcore.models.holon import HolonScope

                holons = await self.holon_fabric.query_context(
                    query_vec=query_vec, scopes=[HolonScope.GLOBAL], limit=limit
                )
                # Convert Holon objects to dicts for backward compatibility
                return [h.dict() if hasattr(h, "dict") else h for h in holons]
            elif method == "store":
                # Insert holon
                holon_data = args.get("holon_data")
                if not holon_data:
                    raise ToolError(name, "Missing holon_data parameter")
                # Convert legacy holon_data format to Holon object
                from seedcore.models.holon import Holon, HolonType, HolonScope

                vector_data = holon_data.get("vector", {})
                graph_data = holon_data.get("graph", {})

                holon = Holon(
                    id=vector_data.get("id", graph_data.get("src_uuid")),
                    type=HolonType.FACT,  # Default type
                    scope=HolonScope.GLOBAL,  # Default scope
                    content=vector_data.get("meta", {}),
                    summary=vector_data.get("meta", {}).get("summary", ""),
                    embedding=vector_data.get("embedding", []),
                    links=[graph_data] if graph_data else [],
                )
                await self.holon_fabric.insert_holon(holon)
                return True
            elif method == "relationships":
                # Get relationships
                holon_id = args.get("holon_id")
                if not holon_id:
                    raise ToolError(name, "Missing holon_id parameter")
                neighbors = await self.holon_fabric.graph.get_neighbors(holon_id)
                return neighbors
            else:
                raise ToolError(name, f"Unknown HolonFabric method '{method}'")
        except Exception as e:
            raise ToolError(name, "HolonFabric execute failed", e)

    # ============================================================
    # Cognitive routing
    # ============================================================

    async def call_cognitive(self, method: str, **kwargs):
        if not self.cognitive_client:
            raise ToolError(method, "No cognitive client available")
        try:
            func = getattr(self.cognitive_client, method)
            return await func(**kwargs)
        except Exception as e:
            raise ToolError(method, "Cognitive service failed", e)

    # ============================================================
    # Execution Pipeline
    # ============================================================

    async def execute(
        self, name: str, args: Dict[str, Any], agent_id: Optional[str] = None
    ) -> Any:
        """
        Full routing logic:
        1. Internal tools (including query tools: general_query, knowledge.find, task.collaborative, cognitive.*)
        2. Memory MW (memory.mw.*)
        3. Memory LTM (memory.ltm.*)
        4. Cognitive service (cog.*, reason.*)
        5. External MCP
        """

        # Detect query tool patterns for better logging
        is_query_tool = name in (
            "general_query",
            "knowledge.find",
            "task.collaborative",
        ) or name.startswith("cognitive.")

        logger.debug(
            f"ToolManager executing: {name}{' [query tool]' if is_query_tool else ''}"
        )
        start = time.perf_counter()
        failed = False

        # RBAC (optional)
        if self.rbac_provider:
            try:
                allowed = await self.rbac_provider.allowed(agent_id, name)
                if not allowed:
                    raise ToolError(name, "rbac_denied")
            except Exception:
                logger.debug("RBAC check skipped or failed")

        try:
            # 1. Internal tools (includes all query tools registered via register_query_tools)
            # Query tools are registered as internal tools with names like:
            # - general_query
            # - knowledge.find
            # - task.collaborative
            # - cognitive.reason_about_failure
            # - cognitive.make_decision
            # - cognitive.synthesize_memory
            # - cognitive.assess_capabilities
            # Thread-safe read: acquire lock briefly to get tool reference
            # Note: Tool could theoretically be unregistered between this check and execution,
            # but this is acceptable behavior - we execute if the tool exists at the start of execution.
            # For stricter guarantees, we could use a refcount system, but that adds complexity.
            async with self._lock:
                tool = self._tools.get(name)

            if tool:
                if is_query_tool:
                    logger.debug(f"Executing query tool: {name}")
                return await tool.execute(**args)

            # 2. MW tools
            if name.startswith("memory.mw."):
                return await self._execute_mw(name, args, agent_id)

            # 3. HolonFabric tools (replaces legacy LTM tools)
            if name.startswith("memory.ltm.") or name.startswith("memory.holon."):
                return await self._execute_holon(name, args, agent_id)

            # 4. Cognitive service tools (direct cognitive service calls)
            # Note: cognitive.* query tools are handled above as internal tools
            # This handles direct cognitive service calls with cog.* or reason.* prefixes
            if name.startswith("cog.") or name.startswith("reason."):
                method = name.split(".", 1)[-1]
                return await self.call_cognitive(method, **args)

            # 5. External MCP fallback
            if not self._mcp_client:
                raise ToolError(name, "tool_not_found")

            response = await self._mcp_client.call_tool_async(name, args)
            if response.get("error"):
                raise ToolError(name, response["error"]["message"])
            return response.get("result")

        except Exception as e:
            failed = True
            error_msg = str(e)
            if is_query_tool:
                logger.warning(f"Query tool {name} failed: {e}", exc_info=True)

            # Store error message before re-raising
            async with self._metrics_lock:
                self._last_error[name] = error_msg

            if not isinstance(e, ToolError):
                raise ToolError(name, error_msg, e)
            raise
        finally:
            elapsed = time.perf_counter() - start
            # Thread-safe metrics update: protect concurrent access from multiple agents
            async with self._metrics_lock:
                self._call_count[name] = self._call_count.get(name, 0) + 1
                if failed:
                    self._fail_count[name] = self._fail_count.get(name, 0) + 1
                # Limit latency history size to prevent unbounded growth
                if name not in self._latency_hist:
                    self._latency_hist[name] = []
                self._latency_hist[name].append(elapsed)
                # Keep only last 1000 samples per tool
                if len(self._latency_hist[name]) > 1000:
                    self._latency_hist[name] = self._latency_hist[name][-1000:]

            if self.enable_tracing:
                tool_type = "query" if is_query_tool else "tool"
                logger.info(f"📡 ToolManager {tool_type} call: {name} ({elapsed:.3f}s)")

    # ============================================================
    # Tool Reflection (Agents learn how to use tools better)
    # ============================================================

    async def _process_tool_reflection(
        self, agent_id: Optional[str], tool_name: str, reflection: Dict[str, Any]
    ):
        """
        Process tool-generated learning signals.

        Tools can emit reflection payloads like:
            { "skill": "planning", "delta": +0.03 }
        """

        logger.info(
            f"🧠 Tool reflection from {tool_name} for agent {agent_id}: {reflection}"
        )

        # Cannot learn without both store + agent
        if not self.skill_store or not agent_id:
            return

        skill = reflection.get("skill")
        delta = reflection.get("delta")

        if not skill or delta is None:
            return  # Not a skill update reflection

        try:
            delta = float(delta)

            # === Load current deltas ===
            current_deltas = await self.skill_store.load(agent_id)
            if current_deltas is None:
                current_deltas = {}

            # === Apply delta (additive update) ===
            new_value = current_deltas.get(skill, 0.0) + delta
            current_deltas[skill] = float(new_value)

            # === Persist updated deltas ===
            await self.skill_store.save(
                agent_id,
                current_deltas,
                metadata={
                    "source": "tool_reflection",
                    "tool": tool_name,
                    "skill": skill,
                    "delta": delta,
                    "timestamp": time.time(),
                },
            )

        except Exception as e:
            logger.warning(
                f"Failed to apply skill delta from {tool_name}: {e}", exc_info=True
            )

    # ============================================================
    # Introspection
    # ============================================================

    async def list_tools(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}

        # Internal tools - thread-safe copy of tool list
        async with self._lock:
            # Create a snapshot of tools to avoid holding lock during schema() calls
            tools = list(self._tools.values())

        # Process tools outside the lock (schema() calls may be slow)
        for tool in tools:
            try:
                schema = tool.schema()
                name = schema.get("name")
                if name:
                    out[name] = schema
            except Exception:
                continue

        # External tools
        if self._mcp_client:
            try:
                resp = await self._mcp_client.list_tools_async()
                for sch in resp.get("tools", []):
                    name = sch.get("name")
                    if name and name not in out:
                        out[name] = sch
            except Exception as e:
                logger.error(f"Failed to fetch MCP tool list: {e}")

        # Memory router virtual tools?
        # Could list them here later.

        return out

    async def get_tool_schema(self, name: str) -> Optional[Dict[str, Any]]:
        tools = await self.list_tools()
        return tools.get(name)

    async def stats(self) -> Dict[str, Any]:
        """
        Return execution metrics for observability (thread-safe).

        Returns:
            Dictionary with call counts, failure counts, latency histograms, and last errors
        """
        # Thread-safe read of metrics
        async with self._metrics_lock:
            return {
                "call_count": dict(self._call_count),
                "fail_count": dict(self._fail_count),
                "last_error": dict(
                    self._last_error
                ),  # Last error per tool for debugging
                "latency_ms": {
                    name: [
                        x * 1000 for x in hist[-50:]
                    ]  # last 50 samples in milliseconds
                    for name, hist in self._latency_hist.items()
                },
            }
