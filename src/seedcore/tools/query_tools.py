# seedcore/tools/query_tools_v2.py
"""
QueryTools (TaskPayload v2)
Lightweight cognitive caller for agents.
No compatibility logic. No legacy fallbacks.
No PersistentAgent duplication.
"""

from __future__ import annotations
from typing import Dict, Any, Optional
import asyncio
import logging

from ..models.cognitive import CognitiveType, DecisionKind

logger = logging.getLogger(__name__)


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

        task_data = task_data or {}
        params = task_data.get("params", {}) or {}

        # --------------------------------------------------------
        # 1. Determine mode from interaction envelope (canonical)
        # --------------------------------------------------------
        interaction = params.get("interaction", {})
        is_chat = interaction.get("mode") == "agent_tunnel"

        # Read-only history (provided by PersistentAgent)
        chat_env = params.get("chat", {})
        history = chat_env.get("history") or []

        # --------------------------------------------------------
        # 2. Choose cognitive mode
        # --------------------------------------------------------
        if is_chat:
            cog_type = CognitiveType.CHAT
            decision = DecisionKind.FAST_PATH  # always fast unless explicitly overridden
        else:
            cog_type = CognitiveType.PROBLEM_SOLVING
            decision = DecisionKind.FAST_PATH   # default
            if params.get("force_deep_reasoning"):
                decision = DecisionKind.COGNITIVE

        if not self._available:
            return {
                "success": False,
                "reason": "cognitive service unavailable",
                "result": {},
            }

        # --------------------------------------------------------
        # 3. Construct TaskPayload v2 envelopes
        # --------------------------------------------------------

        # 3A Chat mode envelope
        if is_chat:
            params["chat"] = {
                **chat_env,
                "message": description,
                "history": history,
            }

            params.setdefault("interaction", interaction)

            params["cognitive"] = {
                "agent_id": self.agent_id,
                "cog_type": cog_type.value,
                "decision_kind": decision.value,
            }

            task_data["conversation_history"] = history
            task_data["type"] = "chat"
            task_data["message"] = description
            task_data["skip_retrieval"] = not params.get("force_rag")

        # 3B Problem solving envelope
        else:
            params["query"] = {
                "problem_statement": description,
            }
            params["cognitive"] = {
                "agent_id": self.agent_id,
                "cog_type": cog_type.value,
                "decision_kind": decision.value,
            }
            task_data["type"] = "general_query"

        task_data["params"] = params

        # --------------------------------------------------------
        # 4. In-flight dedup
        # --------------------------------------------------------
        request_key = task_data.get("task_id") or description[:50]

        async with self._lock:
            if request_key in self._inflight:
                return await self._inflight[request_key]

            fut = asyncio.create_task(self._cog.execute_async(
                agent_id=self.agent_id,
                cog_type=cog_type,
                decision_kind=decision,
                task=task_data,
            ))
            self._inflight[request_key] = fut

        try:
            resp = await fut
        finally:
            async with self._lock:
                self._inflight.pop(request_key, None)

        normalized = self._normalize(resp)
        if not normalized:
            return {
                "success": False,
                "reason": "invalid cognitive response",
                "result": {},
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
        return {
            "success": True,
            "query_type": "general_query",
            "query": description,
            "plan": payload.get("solution_steps", []),
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
    from .manager import Tool
    
    # Get memory managers from tool_manager
    mw_manager = getattr(tool_manager, "mw_manager", None)
    holon_fabric = getattr(tool_manager, "holon_fabric", None)
    
    # 1. Register GeneralQueryTool
    general_query_tool = GeneralQueryTool(
        cognitive_client=cognitive_client,
        agent_id=agent_id
    )
    await tool_manager.register("general_query", Tool(general_query_tool))
    
    # 2. Register MakeDecisionTool (if cognitive_client available)
    if cognitive_client:
        from .query import MakeDecisionTool
        make_decision_tool = MakeDecisionTool(
            cognitive_client=cognitive_client,
            agent_id=agent_id,
            get_memory_context=get_memory_context or (lambda: {}),
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
        )
        await tool_manager.register("cognitive.make_decision", Tool(make_decision_tool))
    
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
        await tool_manager.register("cognitive.reason_about_failure", Tool(reason_about_failure_tool))
    
    # 4. Register SynthesizeMemoryTool (if cognitive_client available)
    if cognitive_client:
        from .query import SynthesizeMemoryTool
        synthesize_memory_tool = SynthesizeMemoryTool(
            cognitive_client=cognitive_client,
            agent_id=agent_id,
            normalize_cog_resp=normalize_cog_resp or (lambda x: x),
        )
        await tool_manager.register("cognitive.synthesize_memory", Tool(synthesize_memory_tool))
    
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
        await tool_manager.register("cognitive.assess_capabilities", Tool(assess_capabilities_tool))
    
    # 6. Register FindKnowledgeTool (if memory managers available)
    if mw_manager and holon_fabric:
        from .query import FindKnowledgeTool
        find_knowledge_tool = FindKnowledgeTool(
            mw_manager=mw_manager,
            holon_fabric=holon_fabric,
            agent_id=agent_id,
        )
        await tool_manager.register("knowledge.find", Tool(find_knowledge_tool))
        
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
            await tool_manager.register("task.collaborative", Tool(collaborative_task_tool))
    
    logger.info(f"✅ Registered query tools for agent {agent_id}")
