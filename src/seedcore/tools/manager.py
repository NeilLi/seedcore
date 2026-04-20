#!/usr/bin/env python
# seedcore/tools/manager.py

from __future__ import annotations
from typing import Dict, Any, Optional, Protocol, List, TYPE_CHECKING, Callable, Mapping
import asyncio
import inspect
import time
import hashlib
import json
from datetime import datetime, timezone
import uuid

from seedcore.integrations.rust_kernel import (
    enforce_execution_token_with_rust,
    verify_execution_token_with_rust,
)
from seedcore.models.governed_mutation import (
    GovernedMutationContract,
    MutationEffectClass,
    MutationReplayMode,
)
from seedcore.services.governed_mutation_service import (
    GovernedMutationError,
    governed_mutation_wrapper,
)
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
    from seedcore.memory.semantic_memory import SemanticMemoryService

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.tools.manager")
logger = ensure_serve_logger("seedcore.tools.manager", level="DEBUG")

# ============================================================
# Tool Protocol
# ============================================================


class Tool(Protocol):
    async def execute(self, **kwargs: Any) -> Any: ...

    def schema(self) -> Dict[str, Any]: ...

    def governance_contract(self) -> Optional[GovernedMutationContract]: ...


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
    3. Memory: Semantic / holon tools (memory.holon.*) via :class:`SemanticMemoryService`
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
        semantic_memory: Optional["SemanticMemoryService"] = None,
        holon_fabric: Optional["HolonFabric"] = None,
        rbac_provider: Optional[Any] = None,
        skill_store: Optional["SkillStoreProtocol"] = None,
        enable_tracing: bool = True,
        mcp_client: Optional["MCPServiceClient"] = None,
        cognitive_client: Optional["CognitiveServiceClient"] = None,
        ml_client: Optional["MLServiceClient"] = None,
    ):
        """Prefer ``semantic_memory=`` when the process already owns a runtime facade;
        ``holon_fabric=`` remains for legacy call sites and is wrapped automatically.
        """
        # Internal tool registry
        self._tools: Dict[str, Tool] = {}
        self._tool_contracts: Dict[str, GovernedMutationContract] = {}
        self._lock = asyncio.Lock()  # Lock for tool registry operations

        # Separate lock for metrics to reduce contention
        # Metrics are updated frequently during execution, so we use a separate lock
        self._metrics_lock = asyncio.Lock()

        # Service dependencies
        self.mw_manager = mw_manager
        from seedcore.memory.semantic_memory import SemanticMemoryService as _SMS

        if semantic_memory is not None:
            self.semantic_memory = semantic_memory
            self.holon_fabric = semantic_memory.holon_fabric
        elif holon_fabric is not None:
            self.holon_fabric = holon_fabric
            self.semantic_memory = _SMS(holon_fabric)
        else:
            self.holon_fabric = None
            self.semantic_memory = None
        # Deprecated: kept for backward compatibility
        self.ltm_manager = None
        self._mcp_client = mcp_client
        # Lazy MCP tool schema index: refreshed on list_tools(); reused by get_tool_schema().
        self._mcp_tools_index: Optional[Dict[str, Dict[str, Any]]] = None
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
        self._digital_twin_service = None
        self._custody_graph_service = None
        self._db_session_factory = None

        logger.info("🔧 ToolManager initialized (v2.1+)")

    # ============================================================
    # Registration APIs
    # ============================================================

    async def register(self, name: str, tool: Tool) -> None:
        contract = self._contract_from_tool(name=name, tool=tool)
        self._enforce_contract_registration_rules(name=name, contract=contract)
        async with self._lock:
            if name in self._tools:
                logger.warning(f"⚠️ Tool overwritten: {name}")
            self._tools[name] = tool
            if contract is not None:
                self._tool_contracts[name] = contract
            else:
                self._tool_contracts.pop(name, None)
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
        contract = self._contract_from_tool(name=name, tool=tool)
        self._enforce_contract_registration_rules(name=name, contract=contract)
        async with self._lock:
            if name in self._tools:
                logger.warning(f"⚠️ Overwriting internal tool: {name}")
            self._tools[name] = tool
            if contract is not None:
                self._tool_contracts[name] = contract
            else:
                self._tool_contracts.pop(name, None)
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
                self._tool_contracts.pop(name, None)
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

    def _legacy_mutating_tool_name(self, name: str) -> bool:
        """
        Transitional detector for known mutating paths during contract rollout.
        """
        if name.startswith("custody.ledger."):
            return True
        if (
            name.startswith("reachy.")
            or name == "tuya.send_command"
            or name.startswith("actuator.")
            or name.startswith("robot.")
        ):
            return True
        if name in {
            "memory.mw.write",
            "memory.holon.store",
            "memory.ltm.store",
            "memory.graph.write",
        }:
            return True
        if name.startswith("finance.") or name.startswith("transaction.") or name.startswith("payment."):
            return True
        return False

    def _contract_from_tool(
        self,
        *,
        name: str,
        tool: Tool,
    ) -> Optional[GovernedMutationContract]:
        contract_obj: Any = None
        try:
            if hasattr(tool, "governance_contract"):
                contract_obj = tool.governance_contract()
        except Exception as exc:
            raise ValueError(f"tool governance contract resolution failed for '{name}': {exc}") from exc

        if contract_obj is not None:
            return contract_obj if isinstance(contract_obj, GovernedMutationContract) else GovernedMutationContract.model_validate(contract_obj)

        # Schema-level metadata fallback for tools that cannot implement governance_contract().
        try:
            schema = tool.schema()
        except Exception:
            return None
        raw = schema.get("x_governed_mutation_contract")
        if raw is None:
            return None
        return GovernedMutationContract.model_validate(raw)

    def _enforce_contract_registration_rules(
        self,
        *,
        name: str,
        contract: Optional[GovernedMutationContract],
    ) -> None:
        if self._legacy_mutating_tool_name(name):
            if contract is None or not contract.is_mutating():
                raise ValueError(
                    f"Mutating tool '{name}' must declare a valid GovernedMutationContract."
                )

    async def _runtime_contract_for_tool(self, name: str) -> Optional[GovernedMutationContract]:
        async with self._lock:
            contract = self._tool_contracts.get(name)
        if contract is not None:
            return contract

        # Built-in governed runtime paths (not internal tool registrations).
        if name == "custody.ledger.record":
            return GovernedMutationContract(
                effect_class=MutationEffectClass.DIGITAL_STATE,
                requires_execution_token=True,
                requires_policy_receipt=False,
                requires_signed_receipt=True,
                snapshot_binding_required=False,
                replay_mode=MutationReplayMode.HASH_STABLE,
            )
        if name == "custody.ledger.list":
            return GovernedMutationContract(
                effect_class=MutationEffectClass.READ_ONLY,
                requires_execution_token=False,
                requires_policy_receipt=False,
                requires_signed_receipt=False,
                snapshot_binding_required=False,
                replay_mode=MutationReplayMode.NONE,
            )
        if name in {"memory.mw.write", "memory.holon.store", "memory.ltm.store", "memory.graph.write"}:
            return GovernedMutationContract(
                effect_class=MutationEffectClass.DIGITAL_STATE,
                requires_execution_token=True,
                requires_policy_receipt=False,
                requires_signed_receipt=False,
                snapshot_binding_required=False,
                replay_mode=MutationReplayMode.HASH_STABLE,
            )
        if name.startswith("finance.") or name.startswith("transaction.") or name.startswith("payment."):
            return GovernedMutationContract(
                effect_class=MutationEffectClass.FINANCIAL_STATE,
                requires_execution_token=True,
                requires_policy_receipt=True,
                requires_signed_receipt=True,
                snapshot_binding_required=True,
                replay_mode=MutationReplayMode.BYTE_STABLE,
            )
        return None

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
        """Execute semantic memory (Holon) tools via :class:`SemanticMemoryService`.

        Supports canonical ``memory.holon.*`` tools and legacy
        ``memory.ltm.*`` aliases.
        """
        if not self.semantic_memory:
            raise ToolError(name, "Semantic memory not configured")
        try:
            from seedcore.memory.contracts import SemanticSearchQuery

            method = name.split(".", 2)[-1]
            # Map legacy LTM method names to HolonFabric operations
            if method == "query":
                holon_id = args.get("holon_id")
                if not holon_id:
                    raise ToolError(name, "Missing holon_id parameter")
                try:
                    holon = await self.semantic_memory.get_holon(holon_id)
                    if not holon:
                        return None
                    if hasattr(holon, "model_dump"):
                        return holon.model_dump()
                    return holon.dict()
                except Exception:
                    return None
            elif method == "search":
                # Vector similarity search
                embedding = args.get("embedding")
                limit = args.get("limit", 5)
                if not embedding:
                    raise ToolError(name, "Missing embedding parameter")

                q = SemanticSearchQuery(
                    embedding=list(embedding),
                    scopes=["global"],
                    limit=int(limit),
                )
                rows = await self.semantic_memory.search(q)
                out = []
                for r in rows:
                    d = (
                        r.model_dump()
                        if hasattr(r, "model_dump")
                        else r.dict()  # type: ignore[union-attr]
                    )
                    d["id"] = d.get("holon_id", "")
                    out.append(d)
                return out
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
                await self.semantic_memory.upsert_holon(holon)
                return True
            elif method == "relationships":
                holon_id = args.get("holon_id")
                if not holon_id:
                    raise ToolError(name, "Missing holon_id parameter")
                rels = await self.semantic_memory.list_relationships(holon_id)
                out = []
                for r in rels:
                    d = r.model_dump() if hasattr(r, "model_dump") else r.dict()
                    d.setdefault("summary", d.get("neighbor_summary", ""))
                    d.setdefault("uuid", d.get("neighbor_id"))
                    out.append(d)
                return out
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
        contract = await self._runtime_contract_for_tool(name)
        is_governed_mutation = bool(contract and contract.is_mutating())
        requires_execution_token = bool(
            contract and contract.is_mutating() and contract.requires_execution_token and self._requires_execution_token(name)
        )

        if self._legacy_mutating_tool_name(name) and contract is None:
            raise ToolError(name, "missing_governed_mutation_contract")

        # RBAC
        if self.rbac_provider:
            try:
                allowed = await self.rbac_provider.allowed(agent_id, name)
                if not allowed:
                    raise ToolError(name, "rbac_denied")
            except ToolError:
                raise
            except Exception as exc:
                if is_governed_mutation:
                    raise ToolError(name, f"rbac_denied:provider_error:{type(exc).__name__}", exc)
                logger.debug("RBAC check skipped or failed")

        try:
            # 0. Built-in custody ledger tools
            if name.startswith("custody.ledger."):
                if requires_execution_token:
                    self._validate_execution_token(name, governance_ctx, tool_args=safe_args)
                if contract and contract.requires_policy_receipt:
                    self._validate_policy_receipt(name, governance_ctx)
                return await self._execute_custody(
                    name,
                    safe_args,
                    agent_id,
                    governance_ctx=governance_ctx,
                )

            # 0.5 Governance gate for governed mutations
            if requires_execution_token:
                self._validate_execution_token(name, governance_ctx, tool_args=safe_args)
                if isinstance(governance_ctx, dict):
                    token = governance_ctx.get("execution_token")
                    if isinstance(token, dict):
                        # Governed control-plane artifacts are authoritative and override
                        # caller-supplied copies before the tool boundary.
                        safe_args["execution_token"] = dict(token)
                    execution_context = self._resolve_execution_context(governance_ctx)
                    if isinstance(execution_context, dict):
                        safe_args["execution_context"] = dict(execution_context)
            if contract and contract.is_mutating() and contract.requires_policy_receipt:
                self._validate_policy_receipt(name, governance_ctx)

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

            response = await self._mcp_client.call_tool_async(
                tool_name=name,
                arguments=safe_args,
            )
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
        Deprecated compatibility hook for legacy call sites/tests.
        Contract-aware callers should use `_runtime_contract_for_tool`.
        """
        contract = self._tool_contracts.get(name)
        if contract is not None:
            return bool(contract.requires_execution_token and contract.is_mutating())
        if self._legacy_mutating_tool_name(name):
            # During rollout we conservatively require tokens for known mutating paths.
            return True
        return False

    def _validate_policy_receipt(self, tool_name: str, governance_ctx: Any) -> None:
        if not isinstance(governance_ctx, dict):
            raise ToolError(tool_name, "missing_policy_receipt")
        policy_receipt = governance_ctx.get("policy_receipt")
        if not isinstance(policy_receipt, dict):
            raise ToolError(tool_name, "missing_policy_receipt")
        if not policy_receipt.get("receipt_id"):
            raise ToolError(tool_name, "invalid_policy_receipt")

    def _validate_snapshot_binding(self, tool_name: str, governance_ctx: Any) -> None:
        if not isinstance(governance_ctx, dict):
            raise ToolError(tool_name, "missing_snapshot_binding")
        action_intent = governance_ctx.get("action_intent")
        resource = action_intent.get("resource") if isinstance(action_intent, dict) and isinstance(action_intent.get("resource"), dict) else {}
        if isinstance(resource.get("snapshot_id"), int):
            return
        policy_case = governance_ctx.get("policy_case")
        twin_snapshot = (
            policy_case.get("relevant_twin_snapshot")
            if isinstance(policy_case, dict) and isinstance(policy_case.get("relevant_twin_snapshot"), dict)
            else {}
        )
        if isinstance(twin_snapshot.get("snapshot_id"), int):
            return
        raise ToolError(tool_name, "missing_snapshot_binding")

    def _validate_execution_token(
        self,
        tool_name: str,
        governance_ctx: Any,
        *,
        tool_args: Mapping[str, Any] | None = None,
    ) -> None:
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
        if not isinstance(signature, dict):
            raise ToolError(tool_name, "invalid_execution_token")

        rust_verify = verify_execution_token_with_rust(
            token,
            now=datetime.now(timezone.utc),
        )
        if not bool(rust_verify.get("verified")):
            error_code = str(rust_verify.get("error_code") or "verification_failed")
            if error_code == "token_expired":
                raise ToolError(tool_name, "execution_token_expired")
            raise ToolError(tool_name, f"invalid_execution_token:{error_code}")

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
        expected_pairs: Dict[str, Any] = {
            "action_type": action.get("type"),
            "target_zone": resource.get("target_zone"),
            "asset_id": resource.get("asset_id"),
            "principal_agent_id": principal.get("agent_id"),
            "source_registration_id": resource.get("source_registration_id"),
            "registration_decision_id": resource.get("registration_decision_id"),
        }
        action_params = action.get("parameters", {})
        expected_pairs["endpoint_id"] = (
            action_params.get("endpoint_id")
            if isinstance(action_params, dict)
            else None
        )
        expected_pairs["payload_hash"] = self._execution_payload_hash(tool_args)
        request_context = {
            key: expected_pairs.get(key) if expected_pairs.get(key) is not None else constraints.get(key)
            for key in (
                "action_type",
                "target_zone",
                "asset_id",
                "principal_agent_id",
                "source_registration_id",
                "registration_decision_id",
                "endpoint_id",
                "payload_hash",
            )
        }
        execution_context = self._resolve_execution_context(governance_ctx)
        if isinstance(execution_context, dict) and execution_context:
            request_context["execution_preconditions"] = dict(execution_context)
        rust_enforcement = enforce_execution_token_with_rust(
            token,
            request_context,
            now=datetime.now(timezone.utc),
        )
        if not bool(rust_enforcement.get("allowed")):
            error_code = str(rust_enforcement.get("error_code") or "constraint_mismatch")
            raise ToolError(tool_name, f"execution_token_constraint_mismatch:{error_code}")

    def _execution_payload_hash(self, tool_args: Mapping[str, Any] | None) -> str | None:
        if not isinstance(tool_args, Mapping):
            return None
        payload = {
            str(key): value
            for key, value in tool_args.items()
            if key not in {"execution_token", "execution_context"}
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def _resolve_execution_context(self, governance_ctx: Any) -> Dict[str, Any] | None:
        if not isinstance(governance_ctx, Mapping):
            return None

        execution_context = governance_ctx.get("execution_context")
        if isinstance(execution_context, Mapping) and execution_context:
            return dict(execution_context)

        token = governance_ctx.get("execution_token")
        if isinstance(token, Mapping):
            token_preconditions = token.get("execution_preconditions")
            if isinstance(token_preconditions, Mapping) and token_preconditions:
                return dict(token_preconditions)

        policy_receipt = governance_ctx.get("policy_receipt")
        if isinstance(policy_receipt, Mapping):
            receipt_preconditions = policy_receipt.get("execution_preconditions")
            if isinstance(receipt_preconditions, Mapping) and receipt_preconditions:
                return dict(receipt_preconditions)
            advisory = policy_receipt.get("advisory")
            if isinstance(advisory, Mapping):
                advisory_preconditions = advisory.get("execution_preconditions")
                if isinstance(advisory_preconditions, Mapping) and advisory_preconditions:
                    return dict(advisory_preconditions)

        return None

    def _normalize_audit_task_id(self, task_id: Any) -> str:
        raw = str(task_id)
        try:
            return str(uuid.UUID(raw))
        except Exception:
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"seedcore-task:{raw}"))

    async def _previous_mutation_receipt_chain_or_raise(
        self,
        *,
        tool_name: str,
        task_id: str,
    ) -> tuple[Optional[str], Optional[int]]:
        session_factory = self._get_db_session_factory()
        dao = self._get_governance_audit_dao()
        if session_factory is None or dao is None:
            raise ToolError(tool_name, "mutation_receipt_chain_store_unavailable")

        try:
            async with session_factory() as session:
                latest = await dao.get_latest_for_task(session, task_id=task_id)
        except Exception as exc:
            raise ToolError(tool_name, "mutation_receipt_chain_lookup_failed", exc) from exc

        if not isinstance(latest, dict):
            return None, None
        evidence_bundle = latest.get("evidence_bundle")
        if not isinstance(evidence_bundle, dict):
            return None, None
        previous_receipt = evidence_bundle.get("mutation_receipt")
        if previous_receipt is None:
            return None, None
        if not isinstance(previous_receipt, dict):
            raise ToolError(tool_name, "invalid_previous_mutation_receipt")
        previous_hash = previous_receipt.get("payload_hash")
        previous_counter = previous_receipt.get("receipt_counter")
        if previous_hash is not None and (not isinstance(previous_hash, str) or not previous_hash.strip()):
            raise ToolError(tool_name, "invalid_previous_mutation_receipt")
        if previous_counter is not None and not isinstance(previous_counter, int):
            raise ToolError(tool_name, "invalid_previous_mutation_receipt")
        return (
            str(previous_hash) if isinstance(previous_hash, str) else None,
            int(previous_counter) if isinstance(previous_counter, int) else None,
        )

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
            contract = await self._runtime_contract_for_tool(name)
            if contract is None:
                raise ToolError(name, "missing_governed_mutation_contract")
            record = dict(entry)
            record.setdefault("entry_id", str(uuid.uuid4()))
            record.setdefault("recorded_at", datetime.now(timezone.utc).isoformat())
            if agent_id and not record.get("agent_id"):
                record["agent_id"] = agent_id
            action_intent = (
                governance_ctx.get("action_intent")
                if isinstance(governance_ctx, dict) and isinstance(governance_ctx.get("action_intent"), dict)
                else {}
            )
            execution_token = (
                governance_ctx.get("execution_token")
                if isinstance(governance_ctx, dict) and isinstance(governance_ctx.get("execution_token"), dict)
                else {}
            )
            resource = (
                action_intent.get("resource")
                if isinstance(action_intent.get("resource"), dict)
                else {}
            )
            snapshot_id = (
                int(resource.get("snapshot_id"))
                if isinstance(resource.get("snapshot_id"), int)
                else None
            )
            audit_task_id = self._normalize_audit_task_id(record.get("task_id"))
            mutation_state: Dict[str, Any] = {}

            async def _mutation_operation() -> Dict[str, Any]:
                async with self._custody_lock:
                    self._custody_ledger.append(record)
                try:
                    custody_sync_local = await self._sync_asset_custody_state(record, governance_ctx)
                except ToolError:
                    raise
                except Exception:
                    custody_sync_local = None
                    logger.warning(
                        "Asset custody state sync failed after ledger record",
                        exc_info=True,
                    )
                graph_projection_local = await self._persist_custody_graph_projection(
                    record,
                    governance_ctx,
                    custody_sync=custody_sync_local,
                )
                execution_twin_update_local = await self._persist_digital_twin_stage(
                    record,
                    governance_ctx,
                    event_type="action_executed",
                    phase="execution",
                    authority_source="governed_execution_receipt",
                    change_reason="execution_completed",
                )
                transition_twin_update_local = await self._persist_digital_twin_stage(
                    record,
                    governance_ctx,
                    event_type="transition_recorded",
                    phase="transition",
                    authority_source="governed_transition_receipt",
                    change_reason="custody_transition_recorded",
                    extra_context={
                        "transition_event": (
                            graph_projection_local.get("transition_event")
                            if isinstance(graph_projection_local.get("transition_event"), dict)
                            else {}
                        ),
                    },
                )
                settlement_local = await self._settle_digital_twin_state(record, governance_ctx)
                mutation_state.update(
                    {
                        "custody_transition": graph_projection_local,
                        "twin_execution": execution_twin_update_local,
                        "twin_transition": transition_twin_update_local,
                        "twin_settlement": settlement_local,
                    }
                )
                return {"entry_id": record["entry_id"], **mutation_state}

            async def _rbac_check() -> None:
                if self.rbac_provider is None:
                    return
                try:
                    allowed = await self.rbac_provider.allowed(agent_id, name)
                except Exception as exc:
                    raise GovernedMutationError("rbac_denied", str(exc)) from exc
                if not allowed:
                    raise GovernedMutationError("rbac_denied")

            async def _load_previous_chain() -> tuple[Optional[str], Optional[int]]:
                return await self._previous_mutation_receipt_chain_or_raise(
                    tool_name=name,
                    task_id=audit_task_id,
                )

            async def _append_audit(evidence_bundle: Dict[str, Any]) -> Optional[Dict[str, Any]]:
                record["evidence_bundle"] = evidence_bundle
                persisted_local = await self._persist_governance_audit_record(
                    record,
                    governance_ctx,
                    strict=True,
                )
                return {
                    "persisted": persisted_local,
                    "entry_id": record.get("entry_id"),
                    "input_hash": record.get("input_hash"),
                    "evidence_hash": record.get("evidence_hash"),
                }

            try:
                governed_result = await governed_mutation_wrapper.execute(
                    entrypoint_id=name,
                    contract=contract,
                    payload_for_hash={
                        "entry": dict(record),
                        "action_intent": action_intent,
                    },
                    mutation_operation=_mutation_operation,
                    receipt_kind=f"tool.{name}",
                    actor_ref=str(record.get("agent_id")) if record.get("agent_id") is not None else None,
                    target_ref=(
                        str(resource.get("asset_id"))
                        if resource.get("asset_id") is not None
                        else f"task:{record.get('task_id')}"
                    ),
                    intent_id=(
                        str(action_intent.get("intent_id"))
                        if action_intent.get("intent_id") is not None
                        else None
                    ),
                    token_id=(
                        str(execution_token.get("token_id"))
                        if execution_token.get("token_id") is not None
                        else None
                    ),
                    policy_receipt_id=(
                        str(governance_ctx.get("policy_receipt", {}).get("policy_receipt_id"))
                        if isinstance(governance_ctx, dict)
                        and isinstance(governance_ctx.get("policy_receipt"), dict)
                        and governance_ctx.get("policy_receipt", {}).get("policy_receipt_id") is not None
                        else None
                    ),
                    snapshot_id=snapshot_id,
                    rbac_check=_rbac_check,
                    execution_token_check=lambda: self._validate_execution_token(
                        name,
                        governance_ctx,
                        tool_args={"entry": dict(record)},
                    ),
                    policy_receipt_check=lambda: self._validate_policy_receipt(name, governance_ctx),
                    snapshot_binding_check=lambda: self._validate_snapshot_binding(name, governance_ctx),
                    load_previous_receipt_chain=_load_previous_chain,
                    append_audit_record=_append_audit,
                    evidence_bundle_base=(
                        record.get("evidence_bundle")
                        if isinstance(record.get("evidence_bundle"), dict)
                        else {}
                    ),
                )
            except GovernedMutationError as exc:
                raise ToolError(name, exc.code)

            if isinstance(governed_result.mutation_receipt, dict):
                record["mutation_receipt"] = governed_result.mutation_receipt
                evidence_bundle = (
                    dict(record.get("evidence_bundle"))
                    if isinstance(record.get("evidence_bundle"), dict)
                    else {}
                )
                evidence_bundle["mutation_receipt"] = governed_result.mutation_receipt
                record["evidence_bundle"] = evidence_bundle

            return {
                "ok": True,
                "entry_id": record["entry_id"],
                "persisted": bool(
                    isinstance(governed_result.audit_result, dict)
                    and governed_result.audit_result.get("persisted")
                ),
                "mutation_receipt": (
                    record.get("mutation_receipt")
                    if isinstance(record.get("mutation_receipt"), dict)
                    else None
                ),
                "custody_transition": mutation_state.get("custody_transition"),
                "twin_execution": mutation_state.get("twin_execution"),
                "twin_transition": mutation_state.get("twin_transition"),
                "twin_settlement": mutation_state.get("twin_settlement"),
            }

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
        *,
        strict: bool = False,
    ) -> bool:
        if not isinstance(governance_ctx, dict):
            if strict:
                raise ToolError("custody.ledger.record", "missing_governance_context")
            return False
        action_intent = governance_ctx.get("action_intent", {})
        if not isinstance(action_intent, dict) or not action_intent.get("intent_id"):
            if strict:
                raise ToolError("custody.ledger.record", "missing_action_intent")
            return False
        task_id = record.get("task_id")
        if task_id is None:
            if strict:
                raise ToolError("custody.ledger.record", "missing_task_id")
            return False
        audit_task_id = self._normalize_audit_task_id(task_id)

        session_factory = self._get_db_session_factory()
        dao = self._get_governance_audit_dao()
        if session_factory is None or dao is None:
            if strict:
                raise ToolError("custody.ledger.record", "governance_audit_unavailable")
            return False

        execution_token = governance_ctx.get("execution_token", {})
        policy_decision = governance_ctx.get("policy_decision", {})
        policy_case = governance_ctx.get("policy_case", {})
        policy_receipt = governance_ctx.get("policy_receipt", {})
        evidence_bundle = record.get("evidence_bundle")

        async with session_factory() as session:
            async with session.begin():
                persisted = await dao.append_record(
                    session,
                    task_id=audit_task_id,
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
                    policy_receipt=policy_receipt if isinstance(policy_receipt, dict) else {},
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

    def _get_digital_twin_service(self):
        if self._digital_twin_service is None:
            try:
                from seedcore.coordinator.dao import DigitalTwinDAO
                from seedcore.services.digital_twin_service import DigitalTwinService

                session_factory = self._get_db_session_factory()
                if session_factory is None:
                    return None
                self._digital_twin_service = DigitalTwinService(
                    session_factory=session_factory,
                    dao=DigitalTwinDAO(),
                )
            except Exception:
                return None
        return self._digital_twin_service

    def _get_custody_graph_service(self):
        if self._custody_graph_service is None:
            try:
                from seedcore.services.custody_graph_service import CustodyGraphService

                self._custody_graph_service = CustodyGraphService()
            except Exception:
                return None
        return self._custody_graph_service

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
    ) -> Optional[Dict[str, Any]]:
        session_factory = self._get_db_session_factory()
        dao = self._get_asset_custody_state_dao()
        if session_factory is None or dao is None:
            return None

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
                    return None
                await dao.upsert_snapshot(session, **update)
        return update

    async def _persist_custody_graph_projection(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
        *,
        custody_sync: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not isinstance(governance_ctx, dict):
            return {"ok": False, "reason": "missing_governance_ctx"}
        service = self._get_custody_graph_service()
        session_factory = self._get_db_session_factory()
        if service is None or session_factory is None:
            return {"ok": False, "reason": "custody_graph_service_unavailable"}
        try:
            async with session_factory() as session:
                async with session.begin():
                    result = await service.record_governed_transition(
                        session,
                        record=record,
                        governance_ctx=governance_ctx,
                        custody_update=custody_sync,
                    )
            if result is None:
                return {"ok": False, "reason": "transition_not_materialized"}
            return {"ok": True, **result}
        except Exception as exc:
            logger.warning(
                "Custody graph projection failed for task %s",
                record.get("task_id"),
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc)}

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
        telemetry_refs = evidence_bundle.get("telemetry_refs")
        telemetry = {}
        if isinstance(telemetry_refs, list):
            for item in telemetry_refs:
                if isinstance(item, dict) and isinstance(item.get("inline"), dict):
                    telemetry = dict(item["inline"])
                    break
        if not telemetry and isinstance(evidence_bundle.get("telemetry_snapshot"), dict):
            telemetry = dict(evidence_bundle["telemetry_snapshot"])
        evidence_inputs = (
            evidence_bundle.get("evidence_inputs")
            if isinstance(evidence_bundle.get("evidence_inputs"), dict)
            else {}
        )
        execution_summary = (
            evidence_inputs.get("execution_summary")
            if isinstance(evidence_inputs.get("execution_summary"), dict)
            else {}
        )
        transition_receipts = (
            evidence_inputs.get("transition_receipts")
            if isinstance(evidence_inputs.get("transition_receipts"), list)
            else []
        )
        transition_receipt = next((item for item in transition_receipts if isinstance(item, dict)), None)
        if transition_receipt is None:
            execution_receipt = (
                evidence_bundle.get("execution_receipt")
                if isinstance(evidence_bundle.get("execution_receipt"), dict)
                else {}
            )
            if isinstance(execution_receipt.get("transition_receipt"), dict):
                transition_receipt = dict(execution_receipt["transition_receipt"])
            if not execution_summary and execution_receipt:
                execution_summary = {
                    "actuator_endpoint": execution_receipt.get("actuator_endpoint"),
                    "execution_token_id": execution_token.get("token_id"),
                    "intent_id": action_intent.get("intent_id"),
                }
        zone_checks = (
            telemetry.get("zone_checks")
            if isinstance(telemetry.get("zone_checks"), dict)
            else {}
        )
        actuator_endpoint = execution_summary.get("actuator_endpoint")
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
        receipt_counter: Optional[int] = None
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
                expected_previous_receipt_hash=(
                    prior_state.get("last_receipt_hash")
                    if isinstance(prior_state, dict)
                    else None
                ),
                expected_min_receipt_counter=(
                    int(prior_state.get("last_receipt_counter"))
                    if isinstance(prior_state, dict) and prior_state.get("last_receipt_counter") is not None
                    else None
                ),
            )
            if transition_error is not None:
                raise ToolError(
                    "custody.ledger.record",
                    f"invalid_transition_receipt:{transition_error}",
                )
            receipt_hash = transition_receipt.get("payload_hash")
            if not isinstance(receipt_hash, str) or not receipt_hash:
                raise ToolError("custody.ledger.record", "invalid_transition_receipt:missing_payload_hash")
            receipt_nonce = transition_receipt.get("receipt_nonce")
            trust_proof = transition_receipt.get("trust_proof") if isinstance(transition_receipt.get("trust_proof"), dict) else {}
            replay_proof = trust_proof.get("replay") if isinstance(trust_proof.get("replay"), dict) else {}
            if replay_proof.get("receipt_counter") is not None:
                receipt_counter = int(replay_proof.get("receipt_counter"))
            endpoint_id = (
                str(transition_receipt.get("endpoint_id"))
                if transition_receipt.get("endpoint_id") is not None
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
            previous_counter = (
                int(prior_state.get("last_receipt_counter") or 0)
                if isinstance(prior_state, dict)
                else 0
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
            if receipt_counter is not None and previous_counter and receipt_counter <= previous_counter:
                raise ToolError("custody.ledger.record", "replayed_transition_counter")
            previous_seq = (
                int(prior_state.get("last_transition_seq") or 0)
                if isinstance(prior_state, dict)
                else 0
            )
            transition_seq = previous_seq + 1
            authority_source = "governed_transition_receipt"

        current_zone = (
            (transition_receipt.get("to_zone") if isinstance(transition_receipt, dict) else None)
            or (transition_receipt.get("target_zone") if isinstance(transition_receipt, dict) else None)
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
            "last_receipt_counter": receipt_counter,
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

    async def _settle_digital_twin_state(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
    ) -> Dict[str, Any]:
        if not isinstance(governance_ctx, dict):
            return {"ok": False, "reason": "missing_governance_ctx"}
        service = self._get_digital_twin_service()
        if service is None:
            return {"ok": False, "reason": "digital_twin_service_unavailable"}

        policy_case = (
            governance_ctx.get("policy_case")
            if isinstance(governance_ctx.get("policy_case"), dict)
            else {}
        )
        relevant_twin_snapshot = (
            policy_case.get("relevant_twin_snapshot")
            if isinstance(policy_case.get("relevant_twin_snapshot"), dict)
            else {}
        )
        action_intent = (
            governance_ctx.get("action_intent")
            if isinstance(governance_ctx.get("action_intent"), dict)
            else {}
        )
        if not relevant_twin_snapshot or not action_intent:
            return {"ok": False, "reason": "missing_twin_snapshot"}

        try:
            result = await service.settle_from_evidence_bundle(
                relevant_twin_snapshot=relevant_twin_snapshot,
                task_id=(
                    str(record.get("task_id"))
                    if record.get("task_id") is not None
                    else None
                ),
                intent_id=(
                    str(action_intent.get("intent_id"))
                    if action_intent.get("intent_id") is not None
                    else None
                ),
                policy_receipt=(
                    governance_ctx.get("policy_receipt")
                    if isinstance(governance_ctx.get("policy_receipt"), dict)
                    else {}
                ),
                execution_token=(
                    governance_ctx.get("execution_token")
                    if isinstance(governance_ctx.get("execution_token"), dict)
                    else {}
                ),
                evidence_summary=(
                    policy_case.get("evidence_summary")
                    if isinstance(policy_case.get("evidence_summary"), dict)
                    else {}
                ),
                evidence_bundle=(
                    record.get("evidence_bundle")
                    if isinstance(record.get("evidence_bundle"), dict)
                    else {}
                ),
            )
            return {"ok": True, **result}
        except Exception as exc:
            logger.warning(
                "Digital twin settlement failed for task %s",
                record.get("task_id"),
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc)}

    async def _persist_digital_twin_stage(
        self,
        record: Dict[str, Any],
        governance_ctx: Any,
        *,
        event_type: str,
        phase: str,
        authority_source: str,
        change_reason: str,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not isinstance(governance_ctx, dict):
            return {"ok": False, "reason": "missing_governance_ctx"}
        service = self._get_digital_twin_service()
        if service is None:
            return {"ok": False, "reason": "digital_twin_service_unavailable"}

        policy_case = (
            governance_ctx.get("policy_case")
            if isinstance(governance_ctx.get("policy_case"), dict)
            else {}
        )
        relevant_twin_snapshot = (
            policy_case.get("relevant_twin_snapshot")
            if isinstance(policy_case.get("relevant_twin_snapshot"), dict)
            else {}
        )
        action_intent = (
            governance_ctx.get("action_intent")
            if isinstance(governance_ctx.get("action_intent"), dict)
            else {}
        )
        if not relevant_twin_snapshot or not action_intent:
            return {"ok": False, "reason": "missing_twin_snapshot"}

        context = {
            "phase": phase,
            "event_type": event_type,
            "policy_receipt": (
                governance_ctx.get("policy_receipt")
                if isinstance(governance_ctx.get("policy_receipt"), dict)
                else {}
            ),
            "execution_token": (
                governance_ctx.get("execution_token")
                if isinstance(governance_ctx.get("execution_token"), dict)
                else {}
            ),
            "evidence_summary": (
                policy_case.get("evidence_summary")
                if isinstance(policy_case.get("evidence_summary"), dict)
                else {}
            ),
            "evidence_bundle": (
                record.get("evidence_bundle")
                if isinstance(record.get("evidence_bundle"), dict)
                else {}
            ),
        }
        if extra_context:
            context.update(extra_context)
        try:
            result = await service.persist_relevant_twins(
                relevant_twin_snapshot=relevant_twin_snapshot,
                task_id=(
                    str(record.get("task_id"))
                    if record.get("task_id") is not None
                    else None
                ),
                intent_id=(
                    str(action_intent.get("intent_id"))
                    if action_intent.get("intent_id") is not None
                    else None
                ),
                authority_source=authority_source,
                change_reason=change_reason,
                transition_context=context,
            )
            return {"ok": True, **result}
        except Exception as exc:
            logger.warning(
                "Digital twin stage persistence failed for task %s event=%s",
                record.get("task_id"),
                event_type,
                exc_info=True,
            )
            return {"ok": False, "reason": str(exc)}

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

    async def _resolve_mcp_tool_schemas_by_name(
        self, *, force_refresh: bool = False
    ) -> Dict[str, Dict[str, Any]]:
        """
        Fetch MCP tool schemas once (cached) unless force_refresh=True (used by list_tools).
        """
        if not self._mcp_client:
            return {}
        if not force_refresh and self._mcp_tools_index is not None:
            return self._mcp_tools_index
        try:
            resp = await self._mcp_client.list_tools_async()
            if resp.get("error"):
                logger.error("MCP tools/list returned error: %s", resp.get("error"))
                # Do not overwrite a previously good cache on transient failures.
                # If no cache exists yet, return empty so callers can retry later.
                return self._mcp_tools_index or {}
            idx: Dict[str, Dict[str, Any]] = {}
            for sch in resp.get("tools", []):
                n = sch.get("name")
                if n:
                    idx[n] = sch
            self._mcp_tools_index = idx
            return idx
        except Exception as e:
            logger.error(f"Failed to fetch MCP tool list: {e}")
            # Preserve existing cache; otherwise return empty and allow next call to retry.
            return self._mcp_tools_index or {}

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

        # External tools (always refresh index so full listings stay current)
        if self._mcp_client:
            mcp_by_name = await self._resolve_mcp_tool_schemas_by_name(force_refresh=True)
            for name, sch in mcp_by_name.items():
                if name not in out:
                    out[name] = sch

        if self.mw_manager:
            from .memory_tools import MwReadTool, MwWriteTool, MwHotItemsTool

            for tool in (
                MwReadTool(self.mw_manager),
                MwWriteTool(self.mw_manager),
                MwHotItemsTool(self.mw_manager),
            ):
                schema = tool.schema()
                out.setdefault(schema["name"], schema)

        if self.semantic_memory:
            from .memory_tools import (
                LtmQueryTool,
                LtmSearchTool,
                LtmStoreTool,
                LtmRelationshipsTool,
            )

            for tool in (
                LtmQueryTool(semantic_memory=self.semantic_memory),
                LtmSearchTool(semantic_memory=self.semantic_memory),
                LtmStoreTool(semantic_memory=self.semantic_memory),
                LtmRelationshipsTool(semantic_memory=self.semantic_memory),
            ):
                schema = tool.schema()
                out.setdefault(schema["name"], schema)

        return out

    async def _schema_for_memory_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Resolve a single memory-facade tool schema without building the full catalog."""
        if self.mw_manager:
            from .memory_tools import MwReadTool, MwWriteTool, MwHotItemsTool

            for factory in (
                MwReadTool,
                MwWriteTool,
                MwHotItemsTool,
            ):
                try:
                    sch = factory(self.mw_manager).schema()
                    if sch.get("name") == name:
                        return sch
                except Exception:
                    continue

        if self.semantic_memory:
            from .memory_tools import (
                LtmQueryTool,
                LtmSearchTool,
                LtmStoreTool,
                LtmRelationshipsTool,
            )

            for factory in (
                LtmQueryTool,
                LtmSearchTool,
                LtmStoreTool,
                LtmRelationshipsTool,
            ):
                try:
                    sch = factory(semantic_memory=self.semantic_memory).schema()
                    if sch.get("name") == name:
                        return sch
                except Exception:
                    continue

        return None

    async def get_tool_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Resolve one tool schema without merging the full internal+MCP catalog on each call.
        Precedence matches list_tools: internal, MCP, then memory facades (setdefault order).
        """
        async with self._lock:
            tool = self._tools.get(name)
        if tool:
            try:
                return tool.schema()
            except Exception:
                pass

        if self._mcp_client:
            mcp_map = await self._resolve_mcp_tool_schemas_by_name(force_refresh=False)
            sch = mcp_map.get(name)
            if sch is not None:
                return sch

        return await self._schema_for_memory_tool(name)

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
