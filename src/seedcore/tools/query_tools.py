# seedcore/tools/query_tools_v2.py
"""
QueryTools (TaskPayload v2)
Lightweight cognitive caller for agents.
No compatibility logic. No legacy fallbacks.
No PersistentAgent duplication.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, List
import asyncio
import json

from ..models.cognitive import CognitiveType, DecisionKind

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.tools.query_tools")
logger = ensure_serve_logger("seedcore.tools.query_tools", level="DEBUG")


def _slim_history(history: Optional[List[Any]]) -> List[Dict[str, Any]]:
    """
    Slim history to only JSON-serializable fields (role, content, name).
    Prevents circular references and non-JSON types.
    """
    slim = []
    for m in history or []:
        if not isinstance(m, dict):
            continue
        slim.append({
            "role": m.get("role"),
            "content": m.get("content"),
            "name": m.get("name"),
        })
    return slim


def _clean_interaction(interaction: Any) -> Dict[str, Any]:
    """
    Clean interaction envelope to only whitelisted fields.
    Prevents circular references from nested structures.
    """
    if not isinstance(interaction, dict):
        return {}
    # Whitelist only what we need
    return {
        "mode": interaction.get("mode"),
        "channel": interaction.get("channel"),
        "conversation_id": interaction.get("conversation_id"),
        "assigned_agent_id": interaction.get("assigned_agent_id"),
    }


class GeneralQueryTool:
    """
    Minimal, deterministic, TaskPayload v2 compliant QueryTool.
    """

    def __init__(self, cognitive_client, agent_id: str):
        self._cog = cognitive_client
        self._available = cognitive_client is not None
        self.agent_id = agent_id

        # Minimal in-flight deduplication
        self._inflight = {}
        self._lock = asyncio.Lock()

    @property
    def name(self):
        return "general_query"

    def schema(self):
        return {
            "name": self.name,
            "description": "General queries or chat through CognitiveCore (TaskPayload v2).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "task_data": {"type": "object"},
                },
                "required": ["description"],
            },
        }

    def _normalize(self, resp: Dict[str, Any]):
        if not resp or not isinstance(resp, dict):
            return None
        if not resp.get("success"):
            return None
        payload = resp.get("result") or resp.get("payload")
        if not isinstance(payload, dict):
            return None
        meta = resp.get("meta") or resp.get("metadata") or {}
        return payload, meta

    async def execute(
        self,
        description: str,
        task_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute general query tool with clean payload construction.
        
        Builds a fresh dict with whitelisted fields to avoid circular references
        and non-JSON types from the incoming task_data.
        """
        incoming = task_data or {}
        incoming_params = incoming.get("params") or {}
        
        # Extract and clean interaction (whitelist only needed fields)
        raw_interaction = incoming_params.get("interaction") or {}
        interaction = _clean_interaction(raw_interaction)
        is_chat = interaction.get("mode") == "agent_tunnel"

        # Extract and slim history (prevent circular refs and non-JSON types)
        raw_chat_env = incoming_params.get("chat") or {}
        raw_history = raw_chat_env.get("history") or []
        history = _slim_history(raw_history)

        # --------------------------------------------------------
        # 2. Choose cognitive mode
        # --------------------------------------------------------
        if is_chat:
            cog_type = CognitiveType.CHAT
            decision = DecisionKind.FAST_PATH  # always fast unless explicitly overridden
        else:
            cog_type = CognitiveType.PROBLEM_SOLVING
            decision = DecisionKind.FAST_PATH   # default
            if incoming_params.get("force_deep_reasoning"):
                decision = DecisionKind.COGNITIVE

        if not self._available:
            return {
                "success": False,
                "reason": "cognitive service unavailable",
                "result": {},
            }

        # --------------------------------------------------------
        # 3. Construct clean TaskPayload v2 envelopes (whitelist fields)
        # --------------------------------------------------------
        
        # Build fresh params dict (never reuse incoming dicts)
        params: Dict[str, Any] = {
            "interaction": interaction,
            "cognitive": {
                "agent_id": self.agent_id,
                "cog_type": cog_type.value,
                "decision_kind": decision.value,
            },
        }

        # 3A Chat mode envelope
        if is_chat:
            params["chat"] = {
                # Whitelist only needed chat fields (don't spread raw_chat_env)
                "message": description,
                "history": history,
            }
            
            clean_task: Dict[str, Any] = {
                "type": "chat",
                "message": description,
                "skip_retrieval": not incoming_params.get("force_rag"),
                "params": params,
            }
            
            # Preserve task_id if present (for deduplication)
            if "task_id" in incoming:
                clean_task["task_id"] = incoming["task_id"]

        # 3B Problem solving envelope
        else:
            # For problem_solving, cognitive service expects these fields:
            # - problem_statement (string) - will be extracted from params.query.problem_statement
            # - constraints (dict) - will be extracted from params.constraints
            # - available_tools (dict) - will be extracted from params.available_tools
            # Put them in params so they're preserved through TaskPayload normalization
            constraints = incoming_params.get("constraints") or incoming.get("constraints") or {}
            available_tools = incoming_params.get("available_tools") or incoming.get("available_tools") or {}
            
            # Put problem_statement in params.query (cognitive service will extract to top level)
            params["query"] = {
                "problem_statement": description,
            }
            
            # Put constraints and available_tools in params (cognitive service will extract to top level)
            if constraints:
                params["constraints"] = constraints
            if available_tools:
                params["available_tools"] = available_tools
            
            clean_task = {
                "type": "general_query",
                "description": description,  # Also keep at top level for fallback extraction
                "params": params,
            }
            
            # Preserve task_id if present (for deduplication)
            if "task_id" in incoming:
                clean_task["task_id"] = incoming["task_id"]

        # --------------------------------------------------------
        # 4. Preflight JSON serialization check (catch cycles early)
        # --------------------------------------------------------
        try:
            json.dumps(clean_task)
        except (ValueError, TypeError) as e:
            logger.exception(
                f"[{self.agent_id}] Task payload is not JSON-serializable: {e}. "
                f"task_type={clean_task.get('type')}, "
                f"has_params={bool(clean_task.get('params'))}, "
                f"history_len={len(history)}"
            )
            raise ValueError(f"Task payload contains circular reference or non-JSON type: {e}") from e

        # --------------------------------------------------------
        # 5. In-flight dedup
        # --------------------------------------------------------
        request_key = clean_task.get("task_id") or description[:50]

        # Check for cancellation before starting the request
        try:
            # Use asyncio.shield to protect task creation from immediate cancellation
            async with self._lock:
                if request_key in self._inflight:
                    logger.debug(
                        f"[{self.agent_id}] Found in-flight request for key={request_key}, "
                        "waiting for existing request"
                    )
                    existing_fut = self._inflight[request_key]
                    # Shield the await to prevent cancellation from propagating
                    return await asyncio.shield(existing_fut)

                logger.debug(
                    f"[{self.agent_id}] Creating new cognitive service request for key={request_key}"
                )
                fut = asyncio.create_task(self._cog.execute_async(
                    agent_id=self.agent_id,
                    cog_type=cog_type,
                    decision_kind=decision,
                    task=clean_task,
                ))
                self._inflight[request_key] = fut
                
                # Add cleanup callback to remove from in-flight when done (even if not awaited)
                def _cleanup_inflight(done_fut):
                    """Cleanup in-flight entry when task completes, even if not awaited."""
                    try:
                        # Schedule cleanup in a new task to avoid blocking
                        async def _cleanup():
                            async with self._lock:
                                # Only remove if it's still the same future (not replaced)
                                if self._inflight.get(request_key) is done_fut:
                                    self._inflight.pop(request_key, None)
                                    logger.debug(
                                        f"[{self.agent_id}] Cleaned up in-flight request for key={request_key}"
                                    )
                        # Create task but don't await - fire and forget cleanup
                        asyncio.create_task(_cleanup())
                    except Exception as e:
                        logger.debug(
                            f"[{self.agent_id}] Cleanup callback error for key={request_key}: {e}"
                        )
                
                fut.add_done_callback(_cleanup_inflight)

            # Shield the await to prevent immediate cancellation
            resp = await asyncio.shield(fut)
            logger.info(
                f"[{self.agent_id}] Cognitive service response received: "
                f"success={resp.get('success') if isinstance(resp, dict) else 'N/A'}, "
                f"has_result={bool(resp.get('result')) if isinstance(resp, dict) else False}, "
                f"has_payload={bool(resp.get('payload')) if isinstance(resp, dict) else False}, "
                f"type={type(resp).__name__}"
            )
        except asyncio.CancelledError:
            logger.warning(
                f"[{self.agent_id}] Cognitive service call was cancelled for request_key={request_key}. "
                f"Request may still be processing in the background. "
                f"Task will remain in-flight for deduplication."
            )
            # Don't remove from in-flight - let it complete in background for deduplication
            # The request will be cleaned up when it completes or on next request with same key
            # Re-raise to propagate cancellation
            raise
        except Exception as e:
            logger.error(
                f"[{self.agent_id}] Cognitive service call failed: {e}",
                exc_info=True
            )
            # Remove from in-flight on error
            async with self._lock:
                self._inflight.pop(request_key, None)
            raise
        else:
            # Success - remove from in-flight
            async with self._lock:
                self._inflight.pop(request_key, None)

        # Normalize response
        if not isinstance(resp, dict):
            logger.error(
                f"[{self.agent_id}] Invalid cognitive response type: {type(resp).__name__}, "
                f"value={str(resp)[:200]}"
            )
            return {
                "success": False,
                "reason": f"invalid response type: {type(resp).__name__}",
                "result": {},
            }
        
        normalized = self._normalize(resp)
        if not normalized:
            logger.warning(
                f"[{self.agent_id}] Failed to normalize cognitive response: "
                f"success={resp.get('success')}, "
                f"result={resp.get('result')}, "
                f"payload={resp.get('payload')}, "
                f"error={resp.get('error')}"
            )
            # Return a structured error response instead of failing
            return {
                "success": False,
                "reason": "invalid cognitive response format",
                "result": resp.get("result") or resp.get("payload") or {},
                "error": resp.get("error"),
                "metadata": resp.get("metadata") or {},
            }

        payload, meta = normalized

        # --------------------------------------------------------
        # 5. Return transformed results
        # --------------------------------------------------------
        if is_chat:
            return {
                "success": True,
                "query_type": "agent_chat",
                "message": description,
                "response": payload.get("response", ""),
                "confidence": payload.get("confidence", 0.0),
                "conversation_history": history,
                "meta": meta,
            }

        # non-chat
        # Defensive normalization: ensure solution_steps is a list
        steps = payload.get("solution_steps", [])
        if not isinstance(steps, list):
            logger.warning(
                f"[{self.agent_id}] solution_steps is not a list: type={type(steps).__name__}, "
                f"value={str(steps)[:200]}"
            )
            # Normalize: wrap single item in list, or use empty list
            steps = [steps] if steps else []
        
        return {
            "success": True,
            "query_type": "general_query",
            "query": description,
            "plan": steps,
            "thought": payload.get("thought", ""),
            "meta": meta,
        }


# ============================================================
# Register Query Tools
# ============================================================

async def register_query_tools(
    tool_manager: Any,
    cognitive_client: Any,
    agent_id: str,
    get_agent_capabilities: Optional[callable] = None,
    get_agent_capabilities_dict: Optional[callable] = None,
    get_energy_slice: Optional[callable] = None,
    get_energy_state: Optional[callable] = None,
    update_energy_state: Optional[callable] = None,
    get_performance_data: Optional[callable] = None,
    get_memory_context: Optional[callable] = None,
    get_conversation_history: Optional[callable] = None,
    in_flight_tracker: Optional[Dict] = None,
    in_flight_lock: Optional[Any] = None,
    mfb_client: Optional[Any] = None,
    normalize_cog_resp: Optional[callable] = None,
    **kwargs
) -> None:
    """
    Register all query tools with the ToolManager.
    
    Args:
        tool_manager: ToolManager instance to register tools with
        cognitive_client: CognitiveServiceClient instance
        agent_id: ID of the agent using these tools
        get_agent_capabilities: Function that returns agent capabilities summary
        get_agent_capabilities_dict: Function that returns agent capabilities dict
        get_energy_slice: Function that returns current energy slice value
        get_energy_state: Function that returns current energy state
        update_energy_state: Function that updates energy state
        get_performance_data: Function that returns performance data dict
        get_memory_context: Function that returns memory context dict
        get_conversation_history: Function that returns conversation history
        in_flight_tracker: Dict for tracking in-flight requests
        in_flight_lock: Lock for in-flight tracker
        mfb_client: FlashbulbClient instance
        normalize_cog_resp: Function that normalizes cognitive service responses
        **kwargs: Additional arguments (ignored)
    """
    # Get memory managers from tool_manager
    mw_manager = getattr(tool_manager, "mw_manager", None)
    holon_fabric = getattr(tool_manager, "holon_fabric", None)
    
    # 1. Register GeneralQueryTool
    general_query_tool = GeneralQueryTool(
        cognitive_client=cognitive_client,
        agent_id=agent_id
    )
    await tool_manager.register("general_query", general_query_tool)
    
    # 2. Register MakeDecisionTool (if cognitive_client available)
    if cognitive_client:
        from .query import MakeDecisionTool
        make_decision_tool = MakeDecisionTool(
            cognitive_client=cognitive_client,
            agent_id=agent_id,
            get_memory_context=get_memory_context or (lambda: {}),
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
        )
        await tool_manager.register("cognitive.make_decision", make_decision_tool)
    
    # 3. Register ReasonAboutFailureTool (if cognitive_client and mfb_client available)
    if cognitive_client and mfb_client:
        from .query import ReasonAboutFailureTool
        reason_about_failure_tool = ReasonAboutFailureTool(
            cognitive_client=cognitive_client,
            mfb_client=mfb_client,
            agent_id=agent_id,
            get_memory_context=get_memory_context or (lambda: {}),
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
            get_energy_state=get_energy_state or (lambda: None),
            update_energy_state=update_energy_state or (lambda x: None),
        )
        await tool_manager.register("cognitive.reason_about_failure", reason_about_failure_tool)
    
    # 4. Register SynthesizeMemoryTool (if cognitive_client available)
    if cognitive_client:
        from .query import SynthesizeMemoryTool
        synthesize_memory_tool = SynthesizeMemoryTool(
            cognitive_client=cognitive_client,
            agent_id=agent_id,
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
        )
        await tool_manager.register("cognitive.synthesize_memory", synthesize_memory_tool)
    
    # 5. Register AssessCapabilitiesTool (if cognitive_client available)
    if cognitive_client:
        from .query import AssessCapabilitiesTool
        assess_capabilities_tool = AssessCapabilitiesTool(
            cognitive_client=cognitive_client,
            agent_id=agent_id,
            get_performance_data=get_performance_data or (lambda: {}),
            get_agent_capabilities=get_agent_capabilities_dict or (lambda: {}),
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
        )
        await tool_manager.register("cognitive.assess_capabilities", assess_capabilities_tool)
    
    # 6. Register FindKnowledgeTool (if memory managers available)
    if mw_manager and holon_fabric:
        from .query import FindKnowledgeTool
        find_knowledge_tool = FindKnowledgeTool(
            mw_manager=mw_manager,
            holon_fabric=holon_fabric,
            agent_id=agent_id,
        )
        await tool_manager.register("knowledge.find", find_knowledge_tool)
        
        # 7. Register CollaborativeTaskTool (depends on FindKnowledgeTool)
        if get_energy_slice:
            from .query import CollaborativeTaskTool
            collaborative_task_tool = CollaborativeTaskTool(
                find_knowledge_tool=find_knowledge_tool,
                mw_manager=mw_manager,
                holon_fabric=holon_fabric,
                agent_id=agent_id,
                get_energy_slice=get_energy_slice,
            )
            await tool_manager.register("task.collaborative", collaborative_task_tool)
    
    logger.info(f"✅ Registered query tools for agent {agent_id}")
