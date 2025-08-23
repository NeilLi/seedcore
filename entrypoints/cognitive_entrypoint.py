#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore
docker/cognitive_serve_entrypoint.py

This service runs the cognitive core and related reasoning services
as a separate Ray Serve deployment, independent of the main API.
This entrypoint is designed to be deployed by a driver script.
"""

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
    max_ongoing_requests=1,  # one request per replica at a time
    ray_actor_options={
        "num_cpus": float(os.getenv("COG_SVC_NUM_CPUS", "1")),  # allow 0.5 etc.
        "num_gpus": float(os.getenv("COG_SVC_NUM_GPUS", "0")),
        # Pin replicas to the head node resource set by RAY_OVERRIDE_RESOURCES
        "resources": {"head_node": 0.001},
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
        return {"status": "healthy", "service": "cognitive-warm-replica"}

    @app.get("/")
    async def root(self):
        """Root endpoint."""
        return {"message": "SeedCore Cognitive Service is running with the replica-warm isolation pattern"}

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

    @app.post("/solve-problem", response_model=CognitiveResponse)
    async def solve_problem(self, request: CognitiveRequest):
        try:
            context = CognitiveContext(
                agent_id=request.agent_id,
                task_type=CognitiveTaskType.PROBLEM_SOLVING,
                input_data={
                    "problem_statement": request.problem_statement,
                    "constraints": request.constraints or {},
                    "available_tools": request.available_tools or {}
                }
            )
            result = self.cognitive_core(context)
            return CognitiveResponse(success=True, agent_id=request.agent_id, result=result)
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
def main():
    """Main entrypoint for the cognitive serve service."""
    print("🚀 Starting deployment driver for Cognitive Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            print("❌ Failed to initialize Ray connection")
            sys.exit(1)

        # The application is defined by binding the deployment class
        cognitive_app = CognitiveService.bind()

        # Deploy the application with a unique name and route prefix
        serve.run(
            cognitive_app,
            name="cognitive",
            route_prefix="/cognitive"
        )
        print("✅ Cognitive service application is running.")
        print("🔄 Press Ctrl+C to stop the driver and undeploy the application.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    except Exception as e:
        print(f"❌ Deployment driver error: {e}")
        traceback.print_exc()
        sys.exit(1)
    finally:
        serve.shutdown()
        print("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()