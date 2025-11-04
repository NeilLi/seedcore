#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore
entrypoints/cognitive_entrypoint.py

This service runs the cognitive core and related reasoning services
as a separate Ray Serve deployment, independent of the main API.
This entrypoint is designed to be deployed by a driver script.
"""

import os
import sys
import time
import asyncio
import traceback
import logging
from typing import Dict, Any, Optional

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')
sys.path.insert(0, '/app/docker')

# CRITICAL: Import DSP patch BEFORE any other imports that might trigger DSP
# This prevents permission errors when DSP tries to create log files
import dsp_patch

import ray
from ray import serve
from fastapi import FastAPI
from pydantic import BaseModel

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.CognitiveCore")
logger = logging.getLogger("seedcore.CognitiveCore")

from seedcore.utils.ray_utils import ensure_ray_initialized

# Import cognitive service components
from seedcore.services.cognitive_service import (
    CognitiveService,
    initialize_cognitive_service,
)
from seedcore.cognitive.cognitive_core import (
    CognitiveContext,
    CognitiveTaskType,
)
from seedcore.models.result_schema import (
    create_cognitive_result,
    create_escalated_result,
    create_error_result,
    ResultKind,
    TaskResult,
)

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- Request/Response Models ---
class CognitiveRequest(BaseModel):
    agent_id: str
    incident_context: Dict[str, Any] = None
    task_description: str = None
    decision_context: Dict[str, Any] = None
    historical_data: Dict[str, Any] = None
    problem_statement: str = None
    constraints: Dict[str, Any] = None
    available_tools: Dict[str, Any] = None
    memory_fragments: list = None
    synthesis_goal: str = None
    performance_data: Dict[str, Any] = None
    current_capabilities: Optional[Any] = None  # Can be str or Dict[str, Any] - flexible for cognitive client
    target_capabilities: Dict[str, Any] = None
    knowledge_context: Optional[Dict[str, Any]] = None
    profile: Optional[str] = None  # "fast" | "deep" - profile hint from cognitive client
    depth: Optional[str] = None  # Legacy alias for profile (maps to profile)
    context: Optional[Dict[str, Any]] = None  # Router context passthrough
    task_id: Optional[str] = None  # Task ID for tracking
    correlation_id: Optional[str] = None  # Correlation ID for tracing
    proto_plan: Optional[Dict[str, Any]] = None  # Proto plan hint from upstream
    prior_result: Optional[Dict[str, Any]] = None  # Prior result from upstream
    return_taskresult: Optional[bool] = False  # Key switch: if True, return TaskResult envelope (for routers)
    caller: Optional[str] = None  # Caller identifier (e.g., "router" or "agent")
    llm_provider_override: Optional[str] = None  # Optional provider override (e.g., "anthropic")
    llm_model_override: Optional[str] = None  # Optional model override (e.g., "claude-3-5-sonnet")
    providers: Optional[list] = None  # Multi-provider pool hint
    meta: Optional[Dict[str, Any]] = None  # Extra metadata from cognitive client

class CognitiveResponse(BaseModel):
    success: bool
    agent_id: str
    result: Dict[str, Any]
    error: Optional[str] = None

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Cognitive Service", version="1.0.0")
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Ray Serve Deployment: Replica-Warm Isolation Pattern
# --------------------------------------------------------------------------
@serve.deployment(
    name="CognitiveService",
    num_replicas=int(os.getenv("COG_SVC_REPLICAS", "1")),
    max_ongoing_requests=32,  # one request per replica at a time
    ray_actor_options={
        # "num_cpus": float(os.getenv("COG_SVC_NUM_CPUS", "0.5")),  # allow 0.5 etc.
        # "num_gpus": float(os.getenv("COG_SVC_NUM_GPUS", "0.5")),
        # Pin replicas to the head node resource set by RAY_OVERRIDE_RESOURCES
        "num_cpus": 0.5,
        "resources": {"head_node": 0.001},
    },
)
@serve.ingress(app)
class CognitiveServeService:
    def __init__(self):
        # This is the core of the pattern:
        # Initialize the cognitive_service ONCE when the replica is created.
        # The service is now "warm" and ready for fast inference.
        print("🚀 Initializing warm cognitive_service for new replica...")
        self.cognitive_service: CognitiveService = initialize_cognitive_service()
        print("✅ Cognitive_service is warm and ready.")

    # --- All API endpoints are now methods of this class ---

    @app.get("/health")
    async def health(self):
        """Health check endpoint."""
        health_status = self.cognitive_service.health_check()
        health_status.update({
            "service": "cognitive-warm-replica",
            "route_prefix": "/cognitive",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "endpoints": {
                "health": "/health",
                "info": "/info",
                "cognitive": [
                    "/reason-about-failure",
                    "/plan-task", 
                    "/plan",
                    "/plan_taskresult",
                    "/make-decision",
                    "/solve-problem",
                    "/synthesize-memory",
                    "/assess-capabilities"
                ]
            }
        })
        return health_status

    @app.get("/")
    async def root(self):
        """Root endpoint with structured health info."""
        return {
            "status": "healthy",
            "service": "cognitive-warm-replica",
            "message": "SeedCore Cognitive Service is running with the replica-warm isolation pattern"
        }

    @app.get("/info")
    async def info(self):
        """Service information endpoint."""
        return {
            "service": "cognitive-warm-replica",
            "route_prefix": "/cognitive",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "deployment": {
                "name": "CognitiveService",
                "replicas": int(os.getenv("COG_SVC_REPLICAS", "1")),
                "max_ongoing_requests": 32
            },
            "resources": {
                "num_cpus": float(os.getenv("COG_SVC_NUM_CPUS", "1")),
                "num_gpus": float(os.getenv("COG_SVC_NUM_GPUS", "0")),
                "pinned_to": "head_node"
            }
        }

    async def ping(self) -> str:
        """Health check method to verify the deployment is responsive."""
        return "pong"

    @app.post("/reason-about-failure", response_model=CognitiveResponse)
    async def reason_about_failure(self, request: CognitiveRequest):
        logger.info(f"Received reason-about-failure request for agent {request.agent_id}")
        start_time = time.time()
        try:
            # Safely handle knowledge_context - normalize to empty dict if None
            kc = request.knowledge_context or {}
            facts = kc.get("facts") or []
            summary = kc.get("facts_summary") or ""
            
            # Prepare input data with knowledge context if available
            input_data = request.incident_context or {}
            if facts or summary:
                input_data.update({
                    "relevant_facts": facts,
                    "facts_summary": summary,
                    "retrieval_metadata": kc.get("metadata", {})
                })
            
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.FAILURE_ANALYSIS,
                input_data=input_data
            )
            logger.info(f"Created cognitive context for agent {request.agent_id}, calling cognitive_service")
            result = self.cognitive_service.forward_cognitive_task(context)
            processing_time = time.time() - start_time
            logger.info(f"Completed reason-about-failure for agent {request.agent_id} in {processing_time:.2f}s")
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            processing_time = time.time() - start_time
            logger.exception(f"Error in reason-about-failure for agent {request.agent_id} after {processing_time:.2f}s: {e}")
            return CognitiveResponse(
                success=False, 
                agent_id=request.agent_id, 
                result={
                    "thought": "Unable to analyze failure due to service error",
                    "proposed_solution": "Fix request parsing / input validation", 
                    "confidence_score": 0.0
                }, 
                error=str(e)
            )

    @app.post("/plan-task", response_model=CognitiveResponse)
    async def plan_task(self, request: CognitiveRequest):
        """
        Legacy plan-task endpoint (backward compatibility).
        Supports same parameters as /plan endpoint for consistency.
        """
        try:
            # Handle current_capabilities - can be str or dict from client
            agent_capabilities = {}
            if request.current_capabilities:
                if isinstance(request.current_capabilities, str):
                    if request.current_capabilities.strip():
                        agent_capabilities = {"description": request.current_capabilities}
                elif isinstance(request.current_capabilities, dict):
                    agent_capabilities = request.current_capabilities
            
            # Prepare input data with all supported parameters
            input_data = {
                "task_description": request.task_description,
                "agent_capabilities": agent_capabilities,
                "available_resources": request.available_tools or {}
            }
            
            # Include provider/model overrides if provided
            if request.llm_provider_override:
                input_data["llm_provider_override"] = request.llm_provider_override
            if request.llm_model_override:
                input_data["llm_model_override"] = request.llm_model_override
            if request.providers:
                input_data["providers"] = request.providers
            if request.meta:
                input_data["meta"] = request.meta
            
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data=input_data
            )
            
            # Check if request has profile hint for DEEP profile
            # Note: Profile is metadata for LLM selection, routing decision is "planner"
            use_deep = False
            # First check explicit profile parameter from cognitive client
            if request.profile and request.profile.lower() == "deep":
                use_deep = True
                logger.info(f"🧠 /plan-task: Using DEEP profile (planner path) per request.profile='deep'")
            # Also infer from task description complexity
            elif request.task_description:
                complex_keywords = ['complex', 'analysis', 'decompose', 'plan', 'strategy', 'reasoning', 'hgnn', 'hypergraph']
                desc_lower = request.task_description.lower()
                if any(keyword in desc_lower for keyword in complex_keywords):
                    use_deep = True
                    logger.info(f"🧠 Detected complex query, using DEEP profile (planner path): {request.task_description[:50]}...")
            
            # Return immediate minimal response and run actual planning in background
            # profile_label is metadata, not routing decision (routing is "planner")
            profile_label = "deep" if use_deep else "fast"
            minimal_payload = {
                "thought_process": f"{profile_label.capitalize()} path: returning immediate minimal plan.",
                "step_by_step_plan": [
                    {
                        "step": 1,
                        "action": "Generate a concise summary addressing the user request.",
                    }
                ],
                "estimated_complexity": 3.0 if not use_deep else 5.0,
                "risk_assessment": "Low risk; detailed planning can be deferred.",
                "formatted_response": (
                    request.task_description or "Task acknowledged; preparing a concise plan."
                ),
                "meta": {"profile_used": profile_label, "immediate": True},
            }
            # Fire-and-forget actual planning in the background
            try:
                asyncio.create_task(self._run_plan_async(context, use_deep))
            except Exception as e:
                logger.debug(f"Failed to schedule background plan-task: {e}")
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=minimal_payload)
        except Exception as e:
            logger.exception(f"Error in /plan-task endpoint for agent {request.agent_id}: {e}")
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/plan", response_model=CognitiveResponse)
    async def plan(self, request: CognitiveRequest):
        """
        Plan endpoint for agents - returns CognitiveResponse.
        For routers, use /plan_taskresult endpoint instead.
        """
        try:
            # --- 0) Normalize request -------------------------------------------------
            # Map legacy 'depth' to 'profile' if necessary
            profile = (request.profile or request.depth or "fast").lower()
            if profile not in ("fast", "deep"):
                profile = "fast"

            # Handle current_capabilities (str or dict)
            agent_capabilities = {}
            if request.current_capabilities:
                if isinstance(request.current_capabilities, str):
                    s = request.current_capabilities.strip()
                    if s:
                        agent_capabilities = {"description": s}
                elif isinstance(request.current_capabilities, dict):
                    agent_capabilities = request.current_capabilities

            # Build input_data for cognitive core
            input_data = {
                "task_description": request.task_description,
                "agent_capabilities": agent_capabilities,
                "available_resources": request.available_tools or {},
            }
            if request.llm_provider_override:
                input_data["llm_provider_override"] = request.llm_provider_override
            if request.llm_model_override:
                input_data["llm_model_override"] = request.llm_model_override
            if request.providers:
                input_data["providers"] = request.providers
            if request.meta:
                input_data["meta"] = request.meta

            # Router context passthrough (optional, for future use)
            context_dict = request.context or {}
            if request.task_id:
                context_dict["task_id"] = request.task_id
            if request.correlation_id:
                context_dict["correlation_id"] = request.correlation_id
            if request.proto_plan is not None:
                context_dict["proto_plan"] = request.proto_plan
            if request.prior_result is not None:
                context_dict["prior_result"] = request.prior_result

            # Merge router context into input_data for cognitive core
            if context_dict:
                input_data["router_context"] = context_dict

            ctx = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data=input_data,
            )

            # --- 1) Profile selection ----
            use_deep = (profile == "deep")
            profile_label = "deep" if use_deep else "fast"
            logger.info(
                f"/plan: Using profile={profile_label} for agent {request.agent_id}"
            )

            # --- 2) Immediate/minimal response path (non-blocking) -------------------
            def _minimal_payload():
                return {
                    "thought_process": f"{profile_label.capitalize()} path: returning immediate minimal plan.",
                    "step_by_step_plan": [{"step": 1, "action": "Generate a concise summary addressing the user request."}],
                    "estimated_complexity": 5.0 if use_deep else 3.0,
                    "risk_assessment": "Low risk; detailed planning can be deferred.",
                    "formatted_response": request.task_description or "Task acknowledged; preparing a concise plan.",
                    "meta": {"profile_used": profile_label, "immediate": True},
                }

            immediate_fast = (os.getenv("COG_FAST_IMMEDIATE", "1") in ("1", "true", "True"))
            immediate_deep = (os.getenv("COG_DEEP_IMMEDIATE", "1") in ("1", "true", "True"))

            if (not use_deep and immediate_fast) or (use_deep and immediate_deep):
                try:
                    asyncio.create_task(self._run_plan_async(ctx, use_deep))
                except Exception as e:
                    logger.debug(f"Failed to schedule background plan task: {e}")

                minimal = _minimal_payload()
                return CognitiveResponse(success=True, agent_id=request.agent_id, result=minimal)

            # --- 3) Normal path: also return immediately, do work in background ------
            try:
                asyncio.create_task(self._run_plan_async(ctx, use_deep))
            except Exception as e:
                logger.debug(f"Failed to schedule background plan task: {e}")

            minimal = _minimal_payload()
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=minimal)

        except Exception as e:
            logger.exception(f"Error in /plan endpoint for agent {request.agent_id}: {e}")
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/plan_taskresult", response_model=TaskResult)
    async def plan_taskresult(self, request: CognitiveRequest):
        """
        Plan endpoint for routers - returns TaskResult envelope.
        This endpoint is specifically designed for router calls that need TaskResult structure.
        """
        try:
            # --- 0) Normalize request -------------------------------------------------
            # Map legacy 'depth' to 'profile' if necessary
            profile = (request.profile or request.depth or "fast").lower()
            if profile not in ("fast", "deep"):
                profile = "fast"

            # Handle current_capabilities (str or dict)
            agent_capabilities = {}
            if request.current_capabilities:
                if isinstance(request.current_capabilities, str):
                    s = request.current_capabilities.strip()
                    if s:
                        agent_capabilities = {"description": s}
                elif isinstance(request.current_capabilities, dict):
                    agent_capabilities = request.current_capabilities

            # Build input_data for cognitive core
            input_data = {
                "task_description": request.task_description,
                "agent_capabilities": agent_capabilities,
                "available_resources": request.available_tools or {},
            }
            if request.llm_provider_override:
                input_data["llm_provider_override"] = request.llm_provider_override
            if request.llm_model_override:
                input_data["llm_model_override"] = request.llm_model_override
            if request.providers:
                input_data["providers"] = request.providers
            if request.meta:
                input_data["meta"] = request.meta

            # Router context passthrough
            context_dict = request.context or {}
            if request.task_id:
                context_dict["task_id"] = request.task_id
            if request.correlation_id:
                context_dict["correlation_id"] = request.correlation_id
            if request.proto_plan is not None:
                context_dict["proto_plan"] = request.proto_plan
            if request.prior_result is not None:
                context_dict["prior_result"] = request.prior_result

            # Merge router context into input_data for cognitive core
            if context_dict:
                input_data["router_context"] = context_dict

            ctx = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data=input_data,
            )

            # --- 1) Profile selection ----
            use_deep = (profile == "deep")
            profile_label = "deep" if use_deep else "fast"
            logger.info(
                f"/plan_taskresult: Using profile={profile_label} for router call "
                f"(task_id={context_dict.get('task_id')})"
            )

            # --- 2) Immediate/minimal response path (non-blocking) -------------------
            def _minimal_payload():
                return {
                    "thought_process": f"{profile_label.capitalize()} path: returning immediate minimal plan.",
                    "step_by_step_plan": [{"step": 1, "action": "Generate a concise summary addressing the user request."}],
                    "estimated_complexity": 5.0 if use_deep else 3.0,
                    "risk_assessment": "Low risk; detailed planning can be deferred.",
                    "formatted_response": request.task_description or "Task acknowledged; preparing a concise plan.",
                    "meta": {"profile_used": profile_label, "immediate": True},
                }

            immediate_fast = (os.getenv("COG_FAST_IMMEDIATE", "1") in ("1", "true", "True"))
            immediate_deep = (os.getenv("COG_DEEP_IMMEDIATE", "1") in ("1", "true", "True"))

            if (not use_deep and immediate_fast) or (use_deep and immediate_deep):
                try:
                    asyncio.create_task(self._run_plan_async(ctx, use_deep))
                except Exception as e:
                    logger.debug(f"Failed to schedule background plan task: {e}")

                minimal = _minimal_payload()
                
                # Return TaskResult envelope
                tr = create_cognitive_result(
                    agent_id=request.agent_id or "router",
                    task_type="planner",
                    result=minimal,
                    confidence_score=None,
                    profile_used=profile_label,
                    immediate=True,
                    caller=request.caller or "router",
                )
                # Ensure metadata carries through IDs/context if present
                tr.metadata.update({
                    "path": "cognitive_reasoning",
                    "task_id": context_dict.get("task_id"),
                    "correlation_id": context_dict.get("correlation_id"),
                })
                return tr

            # --- 3) Normal path: also return immediately, do work in background ------
            try:
                asyncio.create_task(self._run_plan_async(ctx, use_deep))
            except Exception as e:
                logger.debug(f"Failed to schedule background plan task: {e}")

            minimal = _minimal_payload()
            
            # Return TaskResult envelope
            tr = create_cognitive_result(
                agent_id=request.agent_id or "router",
                task_type="planner",
                result=minimal,
                confidence_score=None,
                profile_used=profile_label,
                immediate=True,
                caller=request.caller or "router",
            )
            tr.metadata.update({
                "path": "cognitive_reasoning",
                "task_id": context_dict.get("task_id"),
                "correlation_id": context_dict.get("correlation_id"),
            })
            return tr

        except Exception as e:
            logger.exception(f"Error in /plan_taskresult endpoint for agent {request.agent_id}: {e}")
            # Return unified TaskResult error for routers
            tr = create_error_result(
                error=str(e),
                error_type="cognitive_plan_exception",
                original_type=ResultKind.COGNITIVE.value,
                caller=request.caller or "router",
            )
            return tr

    async def _run_plan_async(self, context: CognitiveContext, use_deep: bool) -> None:
        """
        Run single planning in the background without blocking the HTTP response.
        
        NOTE: This performs SINGLE planning with the selected LLM profile (FAST or DEEP).
        It does NOT perform multi-plan/escalation (HGNN decomposition).
        Multi-plan is only triggered by router escalation paths, not by profile="deep" requests.
        """
        try:
            # forward_cognitive_task with use_deep selects LLM profile for single planning
            # use_deep=True → uses deep LLM (e.g., OpenAI) for single plan
            # use_deep=False → uses fast LLM (e.g., Anthropic) for single plan
            result = self.cognitive_service.forward_cognitive_task(context, use_deep=use_deep)
            logger.debug(
                f"Background single plan completed for agent {context.agent_id}, "
                f"use_deep={use_deep} (profile={'deep' if use_deep else 'fast'})"
            )
        except Exception as e:
            logger.exception(
                f"Background plan task failed for agent {context.agent_id}, use_deep={use_deep}: {e}"
            )
            # Note: This is a fire-and-forget task, so we don't propagate the error.
            # The immediate response has already been sent to the client.

    async def _run_solve_problem_async(self, context: CognitiveContext) -> None:
        """Run problem solving in the background without blocking the HTTP response."""
        try:
            result = self.cognitive_service.forward_cognitive_task(context)
            logger.debug(f"Background solve_problem task completed for agent {context.agent_id}")
        except Exception as e:
            logger.exception(
                f"Background solve_problem task failed for agent {context.agent_id}: {e}"
            )
            # Note: This is a fire-and-forget task, so we don't propagate the error.
            # The immediate response has already been sent to the client.

    @app.post("/plan-with-escalation", response_model=CognitiveResponse)
    async def plan_with_escalation(self, request: CognitiveRequest):
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data={
                    "task_description": request.task_description,
                    "agent_capabilities": request.current_capabilities or {},
                    "available_resources": request.available_tools or {}
                }
            )
            
            # Return immediate minimal response and run actual escalation planning in background
            minimal_payload = {
                "thought_process": "Escalation path: returning immediate minimal plan.",
                "step_by_step_plan": [
                    {
                        "step": 1,
                        "action": "Analyze escalation requirements and prepare detailed plan.",
                    }
                ],
                "estimated_complexity": 5.0,
                "risk_assessment": "Escalation planning in progress; detailed analysis deferred.",
                "formatted_response": (
                    request.task_description or "Escalation task acknowledged; preparing escalation plan."
                ),
                    "meta": {"profile_used": "deep", "immediate": True, "escalation": True, "routing": "planner"},
            }
            
            # Fire-and-forget actual escalation planning in the background
            try:
                asyncio.create_task(self._run_plan_with_escalation_async(context))
            except Exception as e:
                logger.debug(f"Failed to schedule background plan-with-escalation task: {e}")
                
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=minimal_payload)
        except Exception as e:
            logger.exception(f"Error in /plan-with-escalation endpoint for agent {request.agent_id}: {e}")
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    async def _run_plan_with_escalation_async(self, context: CognitiveContext) -> None:
        """Run escalation planning in the background without blocking the HTTP response."""
        try:
            result = self.cognitive_service.plan_with_escalation(context)
            logger.debug(f"Background plan-with-escalation task completed for agent {context.agent_id}")
        except Exception as e:
            logger.exception(
                f"Background plan-with-escalation task failed for agent {context.agent_id}: {e}"
            )
            # Note: This is a fire-and-forget task, so we don't propagate the error.
            # The immediate response has already been sent to the client.

    @app.post("/make-decision", response_model=CognitiveResponse)
    async def make_decision(self, request: CognitiveRequest):
        logger.info(f"Received make-decision request for agent {request.agent_id}")
        start_time = time.time()
        try:
            # Safely handle knowledge_context - normalize to empty dict if None
            kc = request.knowledge_context or {}
            facts = kc.get("facts") or []
            summary = kc.get("facts_summary") or ""
            
            # Prepare input data with knowledge context if available
            input_data = {
                "decision_context": request.decision_context or {},
                "historical_data": request.historical_data or {}
            }
            if facts or summary:
                input_data.update({
                    "relevant_facts": facts,
                    "facts_summary": summary,
                    "retrieval_metadata": kc.get("metadata", {})
                })
            
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.DECISION_MAKING,
                input_data=input_data
            )
            logger.info(f"Created cognitive context for agent {request.agent_id}, calling cognitive_service")
            result = self.cognitive_service.forward_cognitive_task(context)
            processing_time = time.time() - start_time
            logger.info(f"Completed make-decision for agent {request.agent_id} in {processing_time:.2f}s")
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            processing_time = time.time() - start_time
            logger.exception(f"Error in make-decision for agent {request.agent_id} after {processing_time:.2f}s: {e}")
            return CognitiveResponse(
                success=False, 
                agent_id=request.agent_id, 
                result={
                    "action": "hold",
                    "reason": "Unable to make decision due to service error",
                    "confidence": 0.0
                }, 
                error=str(e)
            )

    async def solve_problem(self, agent_id: str, problem_statement: str, constraints: dict | None = None, available_tools: dict | None = None, task_id: str | None = None, **kwargs):
        """
        Main entry point for HGNN problem solving and task decomposition.
        
        Args:
            agent_id: ID of the agent
            problem_statement: Description of the problem
            constraints: Optional constraints
            available_tools: Optional available tools
            task_id: Optional task ID for tracing
            **kwargs: Additional keyword arguments (ignored for compatibility)
            
        Returns:
            CognitiveResponse with reasoning results (immediate minimal response, actual planning runs async)
        """
        try:
            # Log task_id for tracing if present
            if task_id:
                logger.info(f"[solve_problem] task_id={task_id}")
                
            context = CognitiveContext(
                agent_id=agent_id,
                task_type=CognitiveTaskType.PROBLEM_SOLVING,
                input_data={
                    "problem_statement": problem_statement,
                    "constraints": constraints or {},
                    "available_tools": available_tools or {}
                }
            )
            
            # Return immediate minimal response and run actual planning in background
            minimal_payload = {
                "solution_approach": "HGNN problem solving initiated",
                "solution_steps": [
                    {
                        "step": 1,
                        "action": "Analyze problem statement and constraints",
                    },
                    {
                        "step": 2,
                        "action": "Decompose into sub-tasks",
                    },
                    {
                        "step": 3,
                        "action": "Execute decomposition plan",
                    }
                ],
                "success_metrics": ["completion", "quality"],
                "meta": {"task_type": "problem_solving", "immediate": True},
            }
            
            # Fire-and-forget actual problem solving in the background
            try:
                asyncio.create_task(self._run_solve_problem_async(context))
            except Exception as e:
                logger.debug(f"Failed to schedule background solve_problem task: {e}")
                
            return CognitiveResponse(success=True, agent_id=agent_id, result=minimal_payload)
        except Exception as e:
            logger.exception(f"Error in solve_problem for agent {agent_id}: {e}")
            return CognitiveResponse(success=False, agent_id=agent_id, result={}, error=str(e))

    @app.post("/solve-problem", response_model=CognitiveResponse)
    async def solve_problem_http(self, request: CognitiveRequest):
        """HTTP endpoint for solve-problem that delegates to the direct method."""
        try:
            return await self.solve_problem(
                agent_id=request.agent_id,
                problem_statement=request.problem_statement or "",
                constraints=request.constraints,
                available_tools=request.available_tools
            )
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/synthesize-memory", response_model=CognitiveResponse)
    async def synthesize_memory(self, request: CognitiveRequest):
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
                input_data={
                    "memory_fragments": request.memory_fragments or [],
                    "synthesis_goal": request.synthesis_goal
                }
            )
            result = self.cognitive_service.forward_cognitive_task(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/assess-capabilities", response_model=CognitiveResponse)
    async def assess_capabilities(self, request: CognitiveRequest):
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
                input_data={
                    "performance_data": request.performance_data or {},
                    "current_capabilities": request.current_capabilities or {},
                    "target_capabilities": request.target_capabilities or {}
                }
            )
            result = self.cognitive_service.forward_cognitive_task(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/test-deep-profile", response_model=CognitiveResponse)
    async def test_deep_profile(self, request: CognitiveRequest):
        """
        Test endpoint that explicitly uses DEEP profile (planner path, OpenAI) to verify token logging.
        """
        logger.info("🧪 Testing DEEP profile (OpenAI) to verify token logging...")
        try:
            context = CognitiveContext(
                agent_id=request.agent_id or "test-agent",
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data={
                    "task_description": request.task_description or "Test task to verify OpenAI token usage",
                    "agent_capabilities": request.current_capabilities or {},
                    "available_resources": request.available_tools or {}
                }
            )
            # Explicitly use DEEP profile (OpenAI)
            result = self.cognitive_service.forward_cognitive_task(context, use_deep=True)
            logger.info("✅ DEEP profile test completed - check logs above for token usage")
            return CognitiveResponse(success=True, agent_id=request.agent_id or "test-agent", result=result)
        except Exception as e:
            logger.exception(f"❌ DEEP profile test failed: {e}")
            return CognitiveResponse(success=False, agent_id=request.agent_id or "test-agent", result={}, error=str(e))


# --- Main Entrypoint ---
# At module level so Ray Serve YAML can import directly
cognitive_app = CognitiveServeService.bind()

def build_cognitive_app(args: dict = None):
    """
    Builder function for the cognitive service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    return CognitiveServeService.bind()

def main():
    print("🚀 Starting deployment driver for Cognitive Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            print("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            cognitive_app,
            name="cognitive",
            route_prefix="/cognitive"
        )
        print("✅ Cognitive service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        print("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()