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

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- Request/Response Models (Unchanged) ---
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
    current_capabilities: Dict[str, Any] = None
    target_capabilities: Dict[str, Any] = None
    knowledge_context: Optional[Dict[str, Any]] = None

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
            result = self.cognitive_service.forward_cognitive_task(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

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
            result = self.cognitive_service.plan_with_escalation(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

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
            CognitiveResponse with reasoning results
        """
        try:
            # Log task_id for tracing if present
            if task_id:
                print(f"[solve_problem] task_id={task_id}")
                
            context = CognitiveContext(
                agent_id=agent_id,
                task_type=CognitiveTaskType.PROBLEM_SOLVING,
                input_data={
                    "problem_statement": problem_statement,
                    "constraints": constraints or {},
                    "available_tools": available_tools or {}
                }
            )
            result = self.cognitive_service.forward_cognitive_task(context)
            return CognitiveResponse(success=True, agent_id=agent_id, result=result)
        except Exception as e:
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