#!/usr/bin/env python
# seedcore/tools/query_tools.py
"""
Query Tools for general queries, knowledge finding, and collaborative tasks.
These tools handle task-specific logic that was previously embedded in RayAgent.
"""

from __future__ import annotations
from typing import Dict, Any, Optional, Tuple
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
        self, description: str, task_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a general query.

        Args:
            description: The query description
            task_data: Optional task metadata

        Returns:
            Query result dictionary
        """
        task_data = task_data or {}
        profile = self._determine_profile(description, task_data)
        decision_kind = (
            DecisionKind.COGNITIVE if profile == "deep" else DecisionKind.FAST_PATH
        )

        # Check for cognitive service availability
        if not self._cog_available or not self._cog:
            logger.error(
                f"🚫 {self.agent_id}: cognitive service unavailable. Can't run {profile} reasoning for query='{description[:80]}'"
            )
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "result": {
                    "query_type": "cognitive_query_unserved",
                    "degraded_mode": True,
                    "reason": "central cognitive service unavailable",
                    "description": description,
                    "intended_profile": profile,
                },
                "mem_hits": 0,
                "used_cognitive_service": False,
                "cognitive_profile": profile,
            }

        # In-flight request deduplication
        task_id = task_data.get("task_id") or task_data.get("id")
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
            logger.info(
                f"🧠 Agent {self.agent_id} using cognitive service (decision_kind={decision_kind.value}, complex={profile == 'deep'})"
            )
            params = task_data.get("params", {}) or {}

            async def _cog_call():
                input_data = {
                    "problem_statement": str(description or ""),
                    "constraints": params.get("constraints") or {},
                    "available_tools": params.get("available_tools") or {},
                }
                meta = {
                    "task_id": task_id,
                    "requested_profile": profile,
                    "agent_capabilities": self._get_agent_capabilities(),
                }
                return await self._cog.execute_async(
                    agent_id=self.agent_id,
                    cog_type=CognitiveType.PROBLEM_SOLVING,
                    decision_kind=decision_kind,
                    input_data=input_data,
                    meta=meta,
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
                    f"✅ Agent {self.agent_id} cognitive service completed with profile={profile}"
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
                f"⚠️ Agent {self.agent_id} cognitive service returned unusable response (profile={profile}), falling back"
            )
        except Exception as e:
            import traceback

            logger.warning(
                f"⚠️ Agent {self.agent_id} cognitive service call failed (profile={profile}): {e}"
            )
            logger.debug("Traceback:\n%s", traceback.format_exc())

        # Fallback Error
        err_blob = {
            "query_type": "cognitive_query_failed",
            "description": description,
            "intended_profile": profile,
            "error": "cognitive service failure or unusable response",
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
) -> None:
    """
    Register all query tools with the ToolManager.

    This function uses ToolManager's internal dependencies (mw_manager, ltm_manager, mcp_client)
    and only requires agent-specific context functions.

    Args:
        tool_manager: The ToolManager instance to register with (must have mw_manager, ltm_manager, mcp_client)
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
    # Note: mw_manager and ltm_manager come from ToolManager to avoid duplication
    mw_manager = tool_manager.mw_manager
    ltm_manager = tool_manager.ltm_manager

    # Note: cognitive_client is different from mcp_client (MCP service vs Cognitive service)
    # For now, we use mcp_client, but this may need to be updated if ToolManager
    # should store cognitive_client separately. Since cognitive_client is agent-specific
    # (from agent.cog.client), it may remain as a parameter.
    # TODO: Consider adding cognitive_client to ToolManager if it should be shared
    cognitive_client = tool_manager._mcp_client

    # Register FindKnowledgeTool first (it's a dependency)
    find_knowledge_tool = FindKnowledgeTool(mw_manager, ltm_manager, agent_id)
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
        ltm_manager,
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
