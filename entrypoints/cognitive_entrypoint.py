#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore
entrypoints/cognitive_entrypoint.py

This service runs the cognitive core and related reasoning services
as a separate Ray Serve deployment, independent of the main API.
This entrypoint is designed to be deployed by a driver script.
"""
from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.CognitiveCore")

import os
import sys
import time
import traceback
from typing import Dict, Any, Optional

import ray
from ray import serve
from fastapi import FastAPI
from seedcore.utils.ray_utils import ensure_ray_initialized
from pydantic import BaseModel

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Import cognitive core components
from seedcore.agents.cognitive_core import (
    CognitiveCore,
    CognitiveContext,
    CognitiveTaskType,
    initialize_cognitive_core,
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

class CognitiveResponse(BaseModel):
    success: bool
    agent_id: str
    result: Dict[str, Any]
    error: Optional[str] = None

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Cognitive Service", version="1.0.0")

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
        "resources": {"cognitive_node": 0.001},
    },
)
@serve.ingress(app)
class CognitiveService:
    def __init__(self):
        # This is the core of the pattern:
        # Initialize the cognitive_core ONCE when the replica is created.
        # The model is now "warm" and ready for fast inference.
        print("🚀 Initializing warm cognitive_core for new replica...")
        self.cognitive_core: CognitiveCore = initialize_cognitive_core()
        print("✅ Cognitive_core is warm and ready.")

    # --- All API endpoints are now methods of this class ---

    @app.get("/health")
    async def health(self):
        """Health check endpoint."""
        return {
            "status": "healthy", 
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
        }

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
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.FAILURE_ANALYSIS,
                input_data=request.incident_context or {}
            )
            result = self.cognitive_core(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

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
            result = self.cognitive_core(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

    @app.post("/make-decision", response_model=CognitiveResponse)
    async def make_decision(self, request: CognitiveRequest):
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.DECISION_MAKING,
                input_data={
                    "decision_context": request.decision_context or {},
                    "historical_data": request.historical_data or {}
                }
            )
            result = self.cognitive_core(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))

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
            result = self.cognitive_core(context)
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
            result = self.cognitive_core(context)
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
            result = self.cognitive_core(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
        except Exception as e:
            return CognitiveResponse(success=False, agent_id=request.agent_id, result={}, error=str(e))


# --- Main Entrypoint ---
# At module level so Ray Serve YAML can import directly
cognitive_app = CognitiveService.bind()

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
    return CognitiveService.bind()

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