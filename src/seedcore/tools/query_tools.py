#!/usr/bin/env python
# seedcore/tools/query_tools.py
"""
Query Tools for general queries, knowledge finding, and collaborative tasks.
These tools handle task-specific logic that was previously embedded in PersistentAgent.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple, List
import logging
import asyncio

from ..models.cognitive import CognitiveType, DecisionKind
from .query.reason_about_failure import ReasonAboutFailureTool
from .query.make_decision import MakeDecisionTool
from .query.synthesize_memory import SynthesizeMemoryTool
from .query.assess_capabilities import AssessCapabilitiesTool
from .query.collaborative_task import CollaborativeTaskTool
from .query.find_knowledge import FindKnowledgeTool

logger = logging.getLogger(__name__)


class GeneralQueryTool:
    """
    Tool for handling general queries via the Cognitive Service.
    Determines the required profile (fast/deep) based on task heuristics,
    calls the central cognitive service, and normalizes the response.
    """

    def __init__(
        self,
        cognitive_client: Any,
        agent_id: str,
        get_agent_capabilities: callable,
        in_flight_tracker: Optional[Dict[str, asyncio.Task]] = None,
        in_flight_lock: Optional[asyncio.Lock] = None,
    ):
        """
        Initialize the GeneralQueryTool.

        Args:
            cognitive_client: CognitiveServiceClient instance
            agent_id: ID of the agent using this tool
            get_agent_capabilities: Function that returns agent capabilities summary string
            in_flight_tracker: Optional dict for tracking in-flight requests (for deduplication)
            in_flight_lock: Optional lock for in_flight_tracker access
        """
        self._cog = cognitive_client
        self._cog_available = cognitive_client is not None
        self.agent_id = agent_id
        self._get_agent_capabilities = get_agent_capabilities
        self._cog_inflight = in_flight_tracker or {}
        self._cog_inflight_lock = in_flight_lock or asyncio.Lock()

    @property
    def name(self) -> str:
        return "general_query"

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Handles general queries by routing them to the Cognitive Service with appropriate profile (fast/deep).",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "The query description or problem statement.",
                    },
                    "task_data": {
                        "type": "object",
                        "description": "Additional task metadata including params, task_id, etc.",
                    },
                },
                "required": ["description"],
            },
        }

    def _extract_formatted(self, payload: Dict[str, Any], description: str) -> str:
        """Extract formatted response from cognitive service payload."""
        formatted = payload.get("formatted_response")
        if not formatted:
            steps = payload.get("solution_steps")
            if isinstance(steps, list) and steps:
                first_step = steps[0]
                if isinstance(first_step, dict):
                    formatted = first_step.get("description")
        if not formatted:
            formatted = f"Cognitive analysis: {description}"
        return formatted

    def _normalize_cog_v2_response(
        self, cog_response: Dict[str, Any]
    ) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """Normalize cognitive service response."""
        if not isinstance(cog_response, dict):
            return None
        if not cog_response.get("success"):
            return None
        payload = cog_response.get("result") or cog_response.get("payload")
        if not isinstance(payload, dict):
            return None
        metadata = cog_response.get("metadata") or cog_response.get("meta") or {}
        return payload, metadata

    def _determine_profile(self, description: str, task_data: Dict[str, Any]) -> str:
        """Determine cognitive profile (fast/deep) based on heuristics."""
        description_lower = description.lower()
        params = task_data.get("params", {}) or {}
        needs_ml_fallback = params.get("needs_ml_fallback", False)

        if isinstance(params.get("confidence"), dict):
            confidence = params["confidence"].get("overall_confidence", 1.0)
        else:
            confidence = (
                params.get("confidence", 1.0)
                if isinstance(params.get("confidence"), (int, float))
                else 1.0
            )

        criticality = params.get("criticality", task_data.get("criticality", 0.5))
        drift_score = task_data.get("drift_score", 0.0)
        explicit_profile = params.get("cognitive_profile")

        if explicit_profile in ("fast", "deep"):
            return explicit_profile

        is_complex = (
            needs_ml_fallback
            or confidence < 0.5
            or criticality > 0.6
            or drift_score > 0.6
            or len(description.split()) > 15
            or any(
                word in description_lower
                for word in [
                    "complex",
                    "analysis",
                    "decompose",
                    "plan",
                    "strategy",
                    "reasoning",
                    "root cause",
                    "diagnose",
                    "mitigation",
                    "architecture",
                    "design a plan",
                ]
            )
            or task_data.get("force_decomposition")
        )

        return "deep" if is_complex else "fast"

    async def execute(
        self, 
        description: str, 
        task_data: Optional[Dict[str, Any]] = None,
        # NEW: Allow passing explicit conversation history
        conversation_history: Optional[List[Dict[str, str]]] = None 
    ) -> Dict[str, Any]:
        """
        Execute a general query or chat conversation.

        Args:
            description: The query description or chat message
            task_data: Optional task metadata
            conversation_history: Optional conversation history for chat mode
                Format: [{"role": "user"|"assistant", "content": "..."}, ...]

        Returns:
            Query result dictionary
        """
        task_data = task_data or {}
        params = task_data.get("params", {}) or {}

        # 1. Detect Interaction Mode (Is this a chat or a query?)
        # Check if the upstream router flagged this as an 'interaction'
        interaction_mode = params.get("interaction", {}).get("mode")
        is_conversational = (
            interaction_mode == "agent_tunnel" 
            or conversation_history is not None
            or params.get("is_chat", False)
        )

        # 2. Select Strategy based on Mode
        if is_conversational:
            # --- FAST PATH: Chat ---
            profile = "fast"  # Chat is almost always fast/latency-sensitive
            cog_type = CognitiveType.CHAT  # New Type
            decision_kind = DecisionKind.FAST_PATH
            
            # Disable deep heuristics for chat unless explicitly requested
            if params.get("force_deep_reasoning"):
                profile = "deep"
                decision_kind = DecisionKind.COGNITIVE
        else:
            # --- SLOW PATH: Problem Solving (Existing Logic) ---
            profile = self._determine_profile(description, task_data)
            cog_type = CognitiveType.PROBLEM_SOLVING
            decision_kind = (
                DecisionKind.COGNITIVE if profile == "deep" else DecisionKind.FAST_PATH
            )

        # Check for cognitive service availability
        if not self._cog_available or not self._cog:
            mode_label = "chat" if is_conversational else "query"
            logger.error(
                f"🚫 {self.agent_id}: cognitive service unavailable. Can't run {mode_label} (profile={profile}) for '{description[:80]}'"
            )
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "result": {
                    "query_type": "cognitive_query_unserved" if not is_conversational else "chat_unserved",
                    "degraded_mode": True,
                    "reason": "central cognitive service unavailable",
                    "description": description,
                    "intended_profile": profile,
                    "mode": mode_label,
                },
                "mem_hits": 0,
                "used_cognitive_service": False,
                "cognitive_profile": profile,
            }

        # In-flight request deduplication
        task_id = task_data.get("task_id") or task_data.get("id")
        # Include conversation history in key for chat mode to avoid deduplication across different contexts
        if is_conversational and conversation_history:
            history_hash = hash(str(conversation_history)) % 10000
            request_key = task_id if task_id else f"chat:{description[:80]}:{history_hash}:{profile}"
        else:
            request_key = task_id if task_id else f"{description[:100]}:{profile}"

        async with self._cog_inflight_lock:
            if request_key in self._cog_inflight:
                existing_task = self._cog_inflight[request_key]
                if not existing_task.done():
                    logger.info(
                        f"🔄 Agent {self.agent_id} deduplicating cognitive request for {request_key[:50]}... "
                        f"(waiting for existing call to complete)"
                    )
                    try:
                        existing_response = await existing_task
                        normalized = self._normalize_cog_v2_response(existing_response)
                        if normalized:
                            payload, metadata = normalized
                            # Determine if this was a chat or query based on payload structure
                            is_chat_response = "response" in payload and "message" not in payload.get("query_type", "")
                            
                            if is_chat_response:
                                result = {
                                    "query_type": "agent_chat",
                                    "message": description,
                                    "response": payload.get("response", ""),
                                    "confidence": payload.get("confidence") or payload.get("confidence_score", 0.0),
                                    "meta": metadata,
                                    "profile_used": profile,
                                }
                            else:
                                result = {
                                    "query_type": (
                                        "complex_cognitive_query"
                                        if profile == "deep"
                                        else "fast_cognitive_query"
                                    ),
                                    "query": description,
                                    "thought_process": payload.get("thought", ""),
                                    "plan": payload.get("solution_steps", []),
                                    "formatted": self._extract_formatted(payload, description),
                                    "description": description,
                                    "meta": metadata,
                                    "profile_used": profile,
                                }
                            logger.info(
                                f"✅ Agent {self.agent_id} reused result from in-flight cognitive request (deduplicated)"
                            )
                            return {
                                "agent_id": self.agent_id,
                                "task_processed": True,
                                "success": True,
                                "quality": 0.9 if profile == "deep" else 0.8,
                                "result": result,
                                "mem_hits": 1,
                                "used_cognitive_service": True,
                                "cognitive_profile": profile,
                            }
                    except Exception as e:
                        logger.debug(
                            f"Error waiting for in-flight request: {e}, making new call"
                        )
                    finally:
                        self._cog_inflight.pop(request_key, None)

        # Cognitive Service Call
        try:
            mode_label = "chat" if is_conversational else "query"
            logger.info(
                f"🧠 Agent {self.agent_id} using cognitive service (mode={mode_label}, decision_kind={decision_kind.value}, profile={profile})"
            )

            async def _cog_call():
                # Construct TaskPayload-compatible dict from task_data
                task_dict = dict(task_data)
                task_dict.setdefault("description", description or "")
                task_dict.setdefault("type", task_data.get("type") or ("chat" if is_conversational else "general_query"))
                task_dict.setdefault("task_id", task_id or f"{mode_label}_{hash(description)}")
                
                # Prepare Params
                task_params = dict(params)
                
                if is_conversational:
                    # CHAT PAYLOAD: Focus on history and persona
                    task_params["chat"] = {
                        "message": description,
                        "history": conversation_history or [],  # Pass the full context!
                        "agent_persona": self._get_agent_capabilities(),
                        "style": "concise_conversational"
                    }
                    # Hint to Core: Skip RAG for simple chat to save time
                    # BUT: If deep reasoning is forced, we likely need RAG context
                    # So only skip retrieval if NOT forcing deep reasoning
                    if not params.get("force_rag") and not params.get("force_deep_reasoning"):
                        task_dict["skip_retrieval"] = True
                    
                    # Also set message at top level for ChatSignature
                    task_dict["message"] = description
                    if conversation_history:
                        task_dict["conversation_history"] = conversation_history
                else:
                    # SOLVER PAYLOAD: Focus on problem definition
                    if "constraints" not in task_params:
                        task_params["constraints"] = {}
                    if "available_tools" not in task_params:
                        task_params["available_tools"] = {}
                    
                    task_params["query"] = {
                        "problem_statement": str(description or ""),
                        "requested_profile": profile,
                        "agent_capabilities": self._get_agent_capabilities(),
                    }
                
                task_dict["params"] = task_params
                
                return await self._cog.execute_async(
                    agent_id=self.agent_id,
                    cog_type=cog_type,  # Uses CHAT or PROBLEM_SOLVING
                    decision_kind=decision_kind,
                    task=task_dict,
                )

            cog_task = asyncio.create_task(_cog_call())
            async with self._cog_inflight_lock:
                self._cog_inflight[request_key] = cog_task

            try:
                cog_response = await cog_task
            finally:
                async with self._cog_inflight_lock:
                    self._cog_inflight.pop(request_key, None)

            normalized = self._normalize_cog_v2_response(cog_response)
            if normalized:
                payload, metadata = normalized
                
                # Handle chat vs query response formatting
                if is_conversational:
                    # CHAT RESPONSE: Extract response and confidence
                    result = {
                        "query_type": "agent_chat",
                        "message": description,
                        "response": payload.get("response", ""),
                        "confidence": payload.get("confidence") or payload.get("confidence_score", 0.0),
                        "conversation_history": conversation_history or [],
                        "meta": metadata,
                        "profile_used": profile,
                    }
                else:
                    # QUERY RESPONSE: Extract thought process and plan
                    result = {
                        "query_type": (
                            "complex_cognitive_query"
                            if profile == "deep"
                            else "fast_cognitive_query"
                        ),
                        "query": description,
                        "thought_process": payload.get("thought", ""),
                        "plan": payload.get("solution_steps", []),
                        "formatted": self._extract_formatted(payload, description),
                        "description": description,
                        "meta": metadata,
                        "profile_used": profile,
                    }
                
                logger.info(
                    f"✅ Agent {self.agent_id} cognitive service completed (mode={mode_label}, profile={profile})"
                )
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 0.9 if profile == "deep" else 0.8,
                    "result": result,
                    "mem_hits": 1,
                    "used_cognitive_service": True,
                    "cognitive_profile": profile,
                }

            logger.warning(
                f"⚠️ Agent {self.agent_id} cognitive service returned unusable response (mode={mode_label}, profile={profile}), falling back"
            )
        except Exception as e:
            import traceback

            logger.warning(
                f"⚠️ Agent {self.agent_id} cognitive service call failed (mode={mode_label}, profile={profile}): {e}"
            )
            logger.debug("Traceback:\n%s", traceback.format_exc())

        # Fallback Error
        err_blob = {
            "query_type": "cognitive_query_failed" if not is_conversational else "chat_failed",
            "description": description,
            "intended_profile": profile,
            "error": "cognitive service failure or unusable response",
            "mode": mode_label,
        }
        return {
            "agent_id": self.agent_id,
            "task_processed": True,
            "success": False,
            "quality": 0.0,
            "result": err_blob,
            "mem_hits": 0,
            "used_cognitive_service": True,
            "cognitive_profile": profile,
        }


# ============================================================
# Registration
# ============================================================

async def register_query_tools(
    tool_manager: Any,
    *,
    agent_id: str,
    get_agent_capabilities: callable,
    get_energy_slice: callable,
    get_memory_context: Optional[callable] = None,
    normalize_cog_resp: Optional[callable] = None,
    get_energy_state: Optional[callable] = None,
    update_energy_state: Optional[callable] = None,
    get_performance_data: Optional[callable] = None,
    get_agent_capabilities_dict: Optional[callable] = None,
    mfb_client: Optional[Any] = None,
    in_flight_tracker: Optional[Dict[str, asyncio.Task]] = None,
    in_flight_lock: Optional[asyncio.Lock] = None,
    cognitive_client: Optional[Any] = None,  # Optional explicit cognitive client override
) -> None:
    """
    Register all query tools with the ToolManager.

    This function uses ToolManager's internal dependencies (mw_manager, holon_fabric, mcp_client)
    and only requires agent-specific context functions.

    Args:
        tool_manager: The ToolManager instance to register with (must have mw_manager, holon_fabric, mcp_client)
        agent_id: ID of the agent using these tools
        get_agent_capabilities: Function that returns agent capabilities summary string
        get_energy_slice: Function that returns current energy slice value
        get_memory_context: Optional function that returns memory context dict
        normalize_cog_resp: Optional function that normalizes cognitive responses
        get_energy_state: Optional function that returns energy state
        update_energy_state: Optional function that updates energy state
        get_performance_data: Optional function that returns performance data
        get_agent_capabilities_dict: Optional function that returns capabilities dict
        mfb_client: Optional FlashbulbClient instance
        in_flight_tracker: Optional dict for tracking in-flight requests (falls back to empty dict if None)
        in_flight_lock: Optional lock for in_flight_tracker access (falls back to new lock if None)
    """
    # Extract dependencies from ToolManager (single source of truth)
    # Note: mw_manager and holon_fabric come from ToolManager to avoid duplication
    mw_manager = tool_manager.mw_manager
    holon_fabric = tool_manager.holon_fabric

    # Use cognitive_client: explicit parameter > ToolManager.cognitive_client > None
    # cognitive_client is different from mcp_client (Cognitive service vs MCP service)
    # ToolManager stores cognitive_client separately from _mcp_client
    if cognitive_client is None:
        cognitive_client = getattr(tool_manager, "cognitive_client", None)
    
    if cognitive_client is None:
        logger.warning(
            f"⚠️ Agent {agent_id}: No cognitive_client available. "
            "GeneralQueryTool will operate in degraded mode (no cognitive service calls)."
        )

    # Register FindKnowledgeTool first (it's a dependency)
    find_knowledge_tool = FindKnowledgeTool(mw_manager, holon_fabric, agent_id)
    await tool_manager.register("knowledge.find", find_knowledge_tool)

    # Register GeneralQueryTool
    general_query_tool = GeneralQueryTool(
        cognitive_client,
        agent_id,
        get_agent_capabilities,
        in_flight_tracker,
        in_flight_lock,
    )
    await tool_manager.register("general_query", general_query_tool)

    # Register CollaborativeTaskTool (depends on FindKnowledgeTool)
    collaborative_task_tool = CollaborativeTaskTool(
        find_knowledge_tool,
        mw_manager,
        holon_fabric,
        agent_id,
        get_energy_slice,
    )
    await tool_manager.register("task.collaborative", collaborative_task_tool)

    # Register cognitive reasoning tools if dependencies are provided
    if cognitive_client and normalize_cog_resp:
        if mfb_client and get_memory_context and get_energy_state and update_energy_state:
            reason_about_failure_tool = ReasonAboutFailureTool(
                cognitive_client,
                mfb_client,
                agent_id,
                get_memory_context,
                normalize_cog_resp,
                get_energy_state,
                update_energy_state,
            )
            await tool_manager.register("cognitive.reason_about_failure", reason_about_failure_tool)

        if get_memory_context:
            make_decision_tool = MakeDecisionTool(
                cognitive_client,
                agent_id,
                get_memory_context,
                normalize_cog_resp,
            )
            await tool_manager.register("cognitive.make_decision", make_decision_tool)

        synthesize_memory_tool = SynthesizeMemoryTool(
            cognitive_client,
            agent_id,
            normalize_cog_resp,
        )
        await tool_manager.register("cognitive.synthesize_memory", synthesize_memory_tool)

        if get_performance_data and get_agent_capabilities_dict:
            assess_capabilities_tool = AssessCapabilitiesTool(
                cognitive_client,
                agent_id,
                get_performance_data,
                get_agent_capabilities_dict,
                normalize_cog_resp,
            )
            await tool_manager.register("cognitive.assess_capabilities", assess_capabilities_tool)

    logger.info(f"Registered query tools for agent {agent_id}")
