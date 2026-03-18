#!/usr/bin/env python
# seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List, TYPE_CHECKING, Callable
import asyncio
import inspect
import time
import hashlib
import json
from datetime import datetime, timezone
import uuid

from seedcore.hal.custody.transition_receipts import (
    is_attestable_transition_endpoint,
    verify_transition_receipt,
)
from seedcore.serve.ml_client import MLServiceClient

if TYPE_CHECKING:
    from seedcore.agents.roles import SkillStoreProtocol
    from seedcore.serve.mcp_client import MCPServiceClient
    from seedcore.serve.cognitive_client import CognitiveServiceClient
    from seedcore.memory.mw_manager import MwManager
    from seedcore.memory.holon_fabric import HolonFabric

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.tools.manager")
logger = ensure_serve_logger("seedcore.tools.manager", level="DEBUG")

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

        # Capabilities tracking (for feature detection and graceful degradation)
        # Capabilities represent system-level features (e.g., "device.vendor.tuya")
        # Tools can check capabilities before attempting operations
        self._capabilities: set[str] = set()
        self._capabilities_lock = asyncio.Lock()

        # Metrics (thread-safe access required for concurrent agent execution)
        self._call_count: Dict[str, int] = {}
        self._fail_count: Dict[str, int] = {}
        self._latency_hist: Dict[str, List[float]] = {}
        self._last_error: Dict[str, str] = {}  # Track last error per tool for debugging

        # Custody ledger (append-only in-process store)
        self._custody_ledger: List[Dict[str, Any]] = []
        self._custody_lock = asyncio.Lock()
        self._governance_audit_dao = None
        self._asset_custody_state_dao = None
        self._db_session_factory = None

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
        """
        Check if a tool is available.
        
        Checks in order:
        1. Internal registered tools
        2. Memory tools (memory.mw.*, memory.ltm.*, memory.holon.*, memory.graph.*)
        3. Cognitive service tools (cog.*, reason.*)
        4. HAL tools (reachy.*)
        5. MCP tools (if mcp_client is available)
        """
        async with self._lock:
            # 1. Check internal tools
            if name in self._tools:
                return True
        
        # 2. Check memory tools
        if (
            name.startswith("memory.mw.")
            or name.startswith("memory.ltm.")
            or name.startswith("memory.holon.")
            or name.startswith("memory.graph.")
        ):
            return True
        
        # 3. Check cognitive service tools
        if name.startswith("cog.") or name.startswith("reason."):
            return True
        
        # 4. Check HAL tools (reachy.*)
        # These are registered as internal tools, but we check here for early validation
        if name.startswith("reachy."):
            # Check if it's registered as an internal tool
            async with self._lock:
                if name in self._tools:
                    return True
            # If not registered yet, return False (don't fall through to MCP)
            return False
        
        # 4.5. Built-in custody ledger tools
        if name.startswith("custody.ledger."):
            return name in {
                "custody.ledger.record",
                "custody.ledger.list",
            }
        
        # 5. Check MCP tools (if client is available)
        # Note: We don't actually query MCP here for performance reasons.
        # If mcp_client exists, we assume the tool might be available via MCP.
        # The actual availability will be checked during execution.
        if self._mcp_client:
            # For MCP tools, we can't know for sure without querying, but we'll allow
            # the execution to proceed and let execute() handle the actual check.
            # Common MCP tool patterns: internet.*, fs.*, etc.
            return True
        
        return False

    # ============================================================
    # Capability Management
    # ============================================================

    async def add_capability(self, capability: str) -> None:
        """
        Register a system capability (e.g., "device.vendor.tuya").
        
        Capabilities represent optional features that agents can check for
        graceful degradation when features are unavailable.
        
        Args:
            capability: Capability identifier (e.g., "device.vendor.tuya")
        """
        async with self._capabilities_lock:
            self._capabilities.add(capability)
        logger.debug(f"Capability registered: {capability}")

    async def has_capability(self, capability: str) -> bool:
        """
        Check if a capability is available.
        
        Args:
            capability: Capability identifier (e.g., "device.vendor.tuya")
        
        Returns:
            True if capability is available, False otherwise
        """
        async with self._capabilities_lock:
            return capability in self._capabilities

    async def list_capabilities(self) -> set[str]:
        """
        Get all registered capabilities.
        
        Returns:
            Set of capability identifiers
        """
        async with self._capabilities_lock:
            return self._capabilities.copy()

    # ============================================================
    # Memory Tool Routing
    # ============================================================

    async def _execute_mw(self, name: str, args: Dict[str, Any], agent_id: str):
        if not self.mw_manager:
            raise ToolError(name, "MW manager not configured")
        try:
            if name == "memory.mw.read":
                result = self.mw_manager.get_item_async(
                    args["item_id"],
                    is_global=bool(args.get("is_global", False)),
                )
                return await result if inspect.isawaitable(result) else result

            if name == "memory.mw.write":
                item_id = args["item_id"]
                value = args["value"]
                ttl_s = args.get("ttl_s")
                is_global = bool(args.get("is_global", False))

                if is_global:
                    handler = getattr(self.mw_manager, "set_global_item_async", None)
                    if callable(handler):
                        result = handler(item_id, value, ttl_s)
                        if inspect.isawaitable(result):
                            await result
                    else:
                        self.mw_manager.set_global_item(item_id, value, ttl_s)
                else:
                    handler = getattr(self.mw_manager, "set_item_async", None)
                    if callable(handler):
                        result = handler(item_id, value, ttl_s=ttl_s)
                        if inspect.isawaitable(result):
                            await result
                    else:
                        self.mw_manager.set_item(item_id, value, ttl_s=ttl_s)

                return {"status": "success", "item_id": item_id}

            if name == "memory.mw.hot_items":
                result = self.mw_manager.get_hot_items_async(args.get("top_n", 5))
                items = await result if inspect.isawaitable(result) else result
                return [{"item_id": item, "count": count} for item, count in items]

            raise ToolError(name, f"Unknown MW tool '{name}'")
        except Exception as e:
            raise ToolError(name, "MW execute failed", e)

    async def _execute_holon(self, name: str, args: Dict[str, Any], agent_id: str):
        """Execute HolonFabric operations.

        Supports canonical ``memory.holon.*`` tools and legacy
        ``memory.ltm.*`` aliases.
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
                import numpy as np  # pyright: ignore[reportMissingImports]

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
        3. Memory holon tools (memory.holon.* + legacy memory.ltm.*)
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
        safe_args = dict(args or {})
        governance_ctx = safe_args.pop("_governance", None)

        # RBAC (optional)
        if self.rbac_provider:
            try:
                allowed = await self.rbac_provider.allowed(agent_id, name)
                if not allowed:
                    raise ToolError(name, "rbac_denied")
            except Exception:
                logger.debug("RBAC check skipped or failed")

        try:
            # 0. Built-in custody ledger tools
            if name.startswith("custody.ledger."):
                if name == "custody.ledger.record":
                    self._validate_execution_token(name, governance_ctx)
                return await self._execute_custody(
                    name,
                    safe_args,
                    agent_id,
                    governance_ctx=governance_ctx,
                )

            # 0.5 Governance gate for all side-effecting tools
            if self._requires_execution_token(name):
                self._validate_execution_token(name, governance_ctx)
                if isinstance(governance_ctx, dict):
                    token = governance_ctx.get("execution_token")
                    if isinstance(token, dict) and "execution_token" not in safe_args:
                        # Forward token to endpoints for governed execution.
                        safe_args["execution_token"] = dict(token)

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
                return await tool.execute(**safe_args)

            # 2. MW tools
            if name.startswith("memory.mw."):
                return await self._execute_mw(name, safe_args, agent_id)

            # 3. HolonFabric tools (replaces legacy LTM tools)
            if (
                name.startswith("memory.ltm.")
                or name.startswith("memory.holon.")
                or name.startswith("memory.graph.")
            ):
                return await self._execute_holon(name, safe_args, agent_id)

            # 4. Cognitive service tools (direct cognitive service calls)
            # Note: cognitive.* query tools are handled above as internal tools
            # This handles direct cognitive service calls with cog.* or reason.* prefixes
            if name.startswith("cog.") or name.startswith("reason."):
                method = name.split(".", 1)[-1]
                return await self.call_cognitive(method, **safe_args)

            # 5. External MCP fallback
            if not self._mcp_client:
                raise ToolError(name, "tool_not_found")

            response = await self._mcp_client.call_tool_async(name, safe_args)
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
    # Governance / Custody
    # ============================================================

    def _requires_execution_token(self, name: str) -> bool:
        """
        Universal side-effect gate: Determine if a tool modifies physical,
        financial, or critical digital state.
        """
        # 1. Physical Actuation (Robotics, IoT)
        if (
            name.startswith("reachy.")
            or name == "tuya.send_command"
            or name.startswith("actuator.")
            or name.startswith("robot.")
        ):
            return True
            
        # 2. Persistent Memory / State Modifications
        if name in (
            "memory.mw.write",
            "memory.holon.store",
            "memory.ltm.store",
            "memory.graph.write",
        ):
            return True
            
        # 3. External integrations with material impact
        if name.startswith("finance.") or name.startswith("transaction.") or name.startswith("payment."):
            return True
            
        return False

    def _validate_execution_token(self, tool_name: str, governance_ctx: Any) -> None:
        if not isinstance(governance_ctx, dict):
            raise ToolError(tool_name, "missing_execution_token")

        token = governance_ctx.get("execution_token", {})
        if not isinstance(token, dict):
            raise ToolError(tool_name, "missing_execution_token")

        token_id = token.get("token_id")
        intent_id = token.get("intent_id")
        valid_until = token.get("valid_until")
        signature = token.get("signature")
        if not token_id or not intent_id or not valid_until or not signature:
            raise ToolError(tool_name, "invalid_execution_token")

        valid_until_ts = self._iso_to_ts(str(valid_until))
        if valid_until_ts is None:
            raise ToolError(tool_name, "invalid_execution_token")
        if valid_until_ts < datetime.now(timezone.utc).timestamp():
            raise ToolError(tool_name, "execution_token_expired")
        action_intent = governance_ctx.get("action_intent", {})
        if not isinstance(action_intent, dict):
            return
        expected_intent_id = action_intent.get("intent_id")
        if expected_intent_id and str(expected_intent_id) != str(intent_id):
            raise ToolError(tool_name, "execution_token_intent_mismatch")
        constraints = token.get("constraints", {})
        if not isinstance(constraints, dict):
            return
        principal = action_intent.get("principal", {})
        resource = action_intent.get("resource", {})
        action = action_intent.get("action", {})
        expected_pairs = {
            "action_type": action.get("type"),
            "target_zone": resource.get("target_zone"),
            "asset_id": resource.get("asset_id"),
            "principal_agent_id": principal.get("agent_id"),
            "source_registration_id": resource.get("source_registration_id"),
            "registration_decision_id": resource.get("registration_decision_id"),
        }
        for key, expected in expected_pairs.items():
            actual = constraints.get(key)
            if expected is not None and actual is not None and str(expected) != str(actual):
                raise ToolError(tool_name, f"execution_token_constraint_mismatch:{key}")

    async def _execute_custody(
        self,
        name: str,
        args: Dict[str, Any],
        agent_id: Optional[str],
        *,
        governance_ctx: Any = None,
    ):
        if name == "custody.ledger.record":
            entry = args.get("entry")
            if not isinstance(entry, dict):
                raise ToolError(name, "entry_required")
            record = dict(entry)
            record.setdefault("entry_id", str(uuid.uuid4()))
            record.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
            if agent_id and not record.get("agent_id"):
                record["agent_id"] = agent_id
            persisted = False
            try:
                persisted = await self._persist_governance_audit_record(
                    record,
                    governance_ctx,
                )
            except Exception:
                logger.warning(
                    "Governance audit persistence failed; retaining in-process ledger",
                    exc_info=True,
                )
            async with self._custody_lock:
                self._custody_ledger.append(record)
            try:
                await self._sync_asset_custody_state(record, governance_ctx)
            except ToolError:
                raise
            except Exception:
                logger.warning(
                    "Asset custody state sync failed after ledger record",
                    exc_info=True,
                )
            return {"ok": True, "entry_id": record["entry_id"], "persisted": persisted}

        if name == "custody.ledger.list":
            limit = args.get("limit", 50)
            try:
                limit = max(1, min(int(limit), 500))
            except Exception:
                limit = 50
            task_id = args.get("task_id")
            db_rows = await self._list_governance_audit_records(
                task_id=str(task_id) if task_id is not None else None,
                limit=limit,
            )
            if db_rows is not None:
                return {"ok": True, "entries": db_rows}
            async with self._custody_lock:
                rows = list(self._custody_ledger[-limit:])
            rows.reverse()
            return {"ok": True, "entries": rows}

        raise ToolError(name, "tool_not_found")

    async def _persist_governance_audit_record(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
    ) -> bool:
        if not isinstance(governance_ctx, dict):
            return False
        action_intent = governance_ctx.get("action_intent", {})
        if not isinstance(action_intent, dict) or not action_intent.get("intent_id"):
            return False
        task_id = record.get("task_id")
        if task_id is None:
            return False

        session_factory = self._get_db_session_factory()
        dao = self._get_governance_audit_dao()
        if session_factory is None or dao is None:
            return False

        execution_token = governance_ctx.get("execution_token", {})
        policy_decision = governance_ctx.get("policy_decision", {})
        policy_case = governance_ctx.get("policy_case", {})
        evidence_bundle = record.get("evidence_bundle")

        async with session_factory() as session:
            async with session.begin():
                persisted = await dao.append_record(
                    session,
                    task_id=str(task_id),
                    record_type=str(record.get("record_type") or "execution_receipt"),
                    intent_id=str(action_intent.get("intent_id")),
                    token_id=(
                        str(execution_token.get("token_id"))
                        if isinstance(execution_token, dict) and execution_token.get("token_id") is not None
                        else None
                    ),
                    policy_snapshot=(
                        str(policy_decision.get("policy_snapshot"))
                        if isinstance(policy_decision, dict) and policy_decision.get("policy_snapshot") is not None
                        else None
                    ),
                    policy_decision=policy_decision if isinstance(policy_decision, dict) else {},
                    action_intent=action_intent,
                    policy_case=policy_case if isinstance(policy_case, dict) else {},
                    evidence_bundle=evidence_bundle if isinstance(evidence_bundle, dict) else {},
                    actor_agent_id=str(record.get("agent_id")) if record.get("agent_id") is not None else None,
                    actor_organ_id=str(record.get("organ_id")) if record.get("organ_id") is not None else None,
                )
        record["entry_id"] = persisted["entry_id"]
        if persisted.get("recorded_at"):
            record["recorded_at"] = persisted["recorded_at"]
        record["input_hash"] = persisted.get("input_hash")
        record["evidence_hash"] = persisted.get("evidence_hash")
        return True

    async def _list_governance_audit_records(
        self,
        *,
        task_id: Optional[str],
        limit: int,
    ) -> Optional[List[Dict[str, Any]]]:
        session_factory = self._get_db_session_factory()
        dao = self._get_governance_audit_dao()
        if session_factory is None or dao is None or task_id is None:
            return None
        try:
            async with session_factory() as session:
                return await dao.list_for_task(session, task_id=task_id, limit=limit)
        except Exception:
            logger.warning(
                "Governance audit read failed; falling back to in-process ledger",
                exc_info=True,
            )
            return None

    def _get_governance_audit_dao(self):
        if self._governance_audit_dao is None:
            try:
                from seedcore.coordinator.dao import GovernedExecutionAuditDAO

                self._governance_audit_dao = GovernedExecutionAuditDAO()
            except Exception:
                return None
        return self._governance_audit_dao

    def _get_asset_custody_state_dao(self):
        if self._asset_custody_state_dao is None:
            try:
                from seedcore.coordinator.dao import AssetCustodyStateDAO

                self._asset_custody_state_dao = AssetCustodyStateDAO()
            except Exception:
                return None
        return self._asset_custody_state_dao

    def _get_db_session_factory(self):
        if self._db_session_factory is None:
            try:
                from seedcore.database import get_async_pg_session_factory

                self._db_session_factory = get_async_pg_session_factory()
            except Exception:
                return None
        return self._db_session_factory

    async def _sync_asset_custody_state(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
    ) -> bool:
        session_factory = self._get_db_session_factory()
        dao = self._get_asset_custody_state_dao()
        if session_factory is None or dao is None:
            return False

        async with session_factory() as session:
            async with session.begin():
                action_intent = (
                    governance_ctx.get("action_intent")
                    if isinstance(governance_ctx, dict) and isinstance(governance_ctx.get("action_intent"), dict)
                    else {}
                )
                resource = (
                    action_intent.get("resource")
                    if isinstance(action_intent.get("resource"), dict)
                    else {}
                )
                asset_id = str(resource.get("asset_id") or "").strip()
                prior_state = (
                    await dao.get_snapshot(session, asset_id=asset_id)
                    if asset_id
                    else None
                )
                update = self._build_asset_custody_update(
                    record,
                    governance_ctx,
                    prior_state=prior_state,
                )
                if update is None:
                    return False
                await dao.upsert_snapshot(session, **update)
        return True

    def _build_asset_custody_update(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
        *,
        prior_state: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(governance_ctx, dict):
            return None

        action_intent = (
            governance_ctx.get("action_intent")
            if isinstance(governance_ctx.get("action_intent"), dict)
            else {}
        )
        resource = (
            action_intent.get("resource")
            if isinstance(action_intent.get("resource"), dict)
            else {}
        )
        if not resource:
            return None

        asset_id = str(resource.get("asset_id") or "").strip()
        if not asset_id:
            return None

        execution_token = (
            governance_ctx.get("execution_token")
            if isinstance(governance_ctx.get("execution_token"), dict)
            else {}
        )
        policy_case = (
            governance_ctx.get("policy_case")
            if isinstance(governance_ctx.get("policy_case"), dict)
            else {}
        )
        twins = (
            policy_case.get("relevant_twin_snapshot")
            if isinstance(policy_case.get("relevant_twin_snapshot"), dict)
            else {}
        )
        asset_twin = twins.get("asset") if isinstance(twins.get("asset"), dict) else {}
        asset_custody = (
            asset_twin.get("custody")
            if isinstance(asset_twin.get("custody"), dict)
            else {}
        )
        evidence_bundle = (
            record.get("evidence_bundle")
            if isinstance(record.get("evidence_bundle"), dict)
            else {}
        )
        telemetry = (
            evidence_bundle.get("telemetry_snapshot")
            if isinstance(evidence_bundle.get("telemetry_snapshot"), dict)
            else (
                evidence_bundle.get("telemetry_summary")
                if isinstance(evidence_bundle.get("telemetry_summary"), dict)
                else {}
            )
        )
        execution_receipt = (
            evidence_bundle.get("execution_receipt")
            if isinstance(evidence_bundle.get("execution_receipt"), dict)
            else {}
        )
        zone_checks = (
            telemetry.get("zone_checks")
            if isinstance(telemetry.get("zone_checks"), dict)
            else {}
        )
        actuator_endpoint = execution_receipt.get("actuator_endpoint")
        transition_receipt = (
            execution_receipt.get("transition_receipt")
            if isinstance(execution_receipt.get("transition_receipt"), dict)
            else None
        )
        transition_receipt_hash = (
            execution_receipt.get("transition_receipt_hash")
            if isinstance(execution_receipt.get("transition_receipt_hash"), str)
            else None
        )
        execution_token_id = (
            str(execution_token.get("token_id"))
            if execution_token.get("token_id") is not None
            else None
        )
        intent_id = (
            str(action_intent.get("intent_id"))
            if action_intent.get("intent_id") is not None
            else None
        )

        transition_seq: Optional[int] = None
        receipt_hash: Optional[str] = None
        receipt_nonce: Optional[str] = None
        endpoint_id: Optional[str] = None
        authority_source = "governed_execution_receipt"

        if is_attestable_transition_endpoint(actuator_endpoint):
            if transition_receipt is None:
                raise ToolError("custody.ledger.record", "missing_transition_receipt")
            transition_error = verify_transition_receipt(
                transition_receipt,
                expected_intent_id=intent_id,
                expected_token_id=execution_token_id,
                expected_endpoint_id=str(actuator_endpoint),
            )
            if transition_error is not None:
                raise ToolError(
                    "custody.ledger.record",
                    f"invalid_transition_receipt:{transition_error}",
                )
            receipt_hash = transition_receipt.get("payload_hash")
            if not isinstance(receipt_hash, str) or not receipt_hash:
                raise ToolError("custody.ledger.record", "invalid_transition_receipt:missing_payload_hash")
            if transition_receipt_hash and transition_receipt_hash != self._sha256_hex(self._canonical_json(transition_receipt)):
                raise ToolError("custody.ledger.record", "transition_receipt_hash_mismatch")
            signed_transition = (
                transition_receipt.get("signed_payload")
                if isinstance(transition_receipt.get("signed_payload"), dict)
                else {}
            )
            receipt_nonce = signed_transition.get("receipt_nonce")
            endpoint_id = (
                str(signed_transition.get("endpoint_id"))
                if signed_transition.get("endpoint_id") is not None
                else str(actuator_endpoint)
            )
            previous_hash = (
                prior_state.get("last_receipt_hash")
                if isinstance(prior_state, dict)
                else None
            )
            previous_nonce = (
                prior_state.get("last_receipt_nonce")
                if isinstance(prior_state, dict)
                else None
            )
            if previous_hash and previous_hash == receipt_hash:
                raise ToolError("custody.ledger.record", "replayed_transition_receipt")
            if (
                isinstance(receipt_nonce, str)
                and receipt_nonce
                and previous_nonce
                and previous_nonce == receipt_nonce
            ):
                raise ToolError("custody.ledger.record", "replayed_transition_nonce")
            previous_seq = (
                int(prior_state.get("last_transition_seq") or 0)
                if isinstance(prior_state, dict)
                else 0
            )
            transition_seq = previous_seq + 1
            authority_source = "governed_transition_receipt"

        signed_transition_payload = (
            transition_receipt.get("signed_payload")
            if isinstance(transition_receipt, dict)
            and isinstance(transition_receipt.get("signed_payload"), dict)
            else {}
        )
        current_zone = (
            signed_transition_payload.get("to_zone")
            or signed_transition_payload.get("target_zone")
            or zone_checks.get("current_zone")
        )
        if not current_zone:
            current_zone = (
                resource.get("target_zone")
                or asset_custody.get("target_zone")
            )

        is_quarantined = asset_custody.get("quarantined")
        if is_quarantined is None:
            is_quarantined = False

        return {
            "asset_id": asset_id,
            "source_registration_id": (
                str(resource.get("source_registration_id"))
                if resource.get("source_registration_id") is not None
                else None
            ),
            "current_zone": str(current_zone) if current_zone is not None else None,
            "is_quarantined": bool(is_quarantined),
            "authority_source": authority_source,
            "last_transition_seq": transition_seq,
            "last_receipt_hash": receipt_hash,
            "last_receipt_nonce": (
                str(receipt_nonce)
                if receipt_nonce is not None
                else None
            ),
            "last_endpoint_id": endpoint_id,
            "last_task_id": (
                str(record.get("task_id"))
                if record.get("task_id") is not None
                else None
            ),
            "last_intent_id": (
                str(action_intent.get("intent_id"))
                if action_intent.get("intent_id") is not None
                else None
            ),
            "last_token_id": (
                str(execution_token.get("token_id"))
                if execution_token.get("token_id") is not None
                else None
            ),
            "updated_by": str(record.get("agent_id")) if record.get("agent_id") is not None else None,
        }

    def _canonical_json(self, payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def _sha256_hex(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _iso_to_ts(self, iso: str) -> Optional[float]:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

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

        if self.mw_manager:
            from .memory_tools import MwReadTool, MwWriteTool, MwHotItemsTool

            for tool in (
                MwReadTool(self.mw_manager),
                MwWriteTool(self.mw_manager),
                MwHotItemsTool(self.mw_manager),
            ):
                schema = tool.schema()
                out.setdefault(schema["name"], schema)

        if self.holon_fabric:
            from .memory_tools import (
                LtmQueryTool,
                LtmSearchTool,
                LtmStoreTool,
                LtmRelationshipsTool,
            )

            for tool in (
                LtmQueryTool(self.holon_fabric),
                LtmSearchTool(self.holon_fabric),
                LtmStoreTool(self.holon_fabric),
                LtmRelationshipsTool(self.holon_fabric),
            ):
                schema = tool.schema()
                out.setdefault(schema["name"], schema)

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
