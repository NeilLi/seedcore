#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore
entrypoints/cognitive_entrypoint.py

REFACTORED: This service runs the cognitive core and related reasoning services
as a separate Ray Serve deployment.

This entrypoint is now a thin, unified API wrapper around the CognitiveService.
It exposes a single /execute endpoint that accepts a CognitiveContext
and delegates all "Profile" and "Pipeline" routing to the service and core layers.
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

# CRITICAL: Import DSP patch BEFORE any other imports
from seedcore.cognitive import dsp_patch  # type: ignore

import ray
from ray import serve
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from seedcore.logging_setup import setup_logging
from seedcore.coordinator.utils import normalize_task_payloads
setup_logging(app_name="seedcore.CognitiveCore")
logger = logging.getLogger("seedcore.CognitiveCore")

from seedcore.utils.ray_utils import ensure_ray_initialized

# Import cognitive service components
from seedcore.services.cognitive_service import (
    CognitiveService,
    initialize_cognitive_service,
)
# Import the centralized, shared models
from seedcore.models.cognitive import (
    CognitiveContext,
    CognitiveType,
    DecisionKind,
)
from seedcore.models.result_schema import (
    TaskResult,
    create_error_result,
)

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- Request/Response Models ---

class CognitiveRequest(BaseModel):
    """
    The single, unified request model for the /execute endpoint.
    This directly maps to the fields needed to build a CognitiveContext.
    """
    agent_id: str
    cog_type: CognitiveType
    input_data: Dict[str, Any]
    meta: Dict[str, Any]  # Must contain 'decision_kind'
    
    # Provider overrides are passed through
    llm_provider_override: Optional[str] = None
    llm_model_override: Optional[str] = None

class CognitiveResponse(BaseModel):
    """
    The single, unified response model.
    """
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    metadata: Dict[str, Any]


# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Cognitive Service", version="2.0.0")

# --------------------------------------------------------------------------
# Ray Serve Deployment
# --------------------------------------------------------------------------
@serve.deployment(
    name="CognitiveService",
    num_replicas=int(os.getenv("COG_SVC_REPLICAS", "1")),
    max_ongoing_requests=32,
    ray_actor_options={
        "num_cpus": 0.5,
        "resources": {"head_node": 0.001},
    },
)
@serve.ingress(app)
class CognitiveServeService:
    def __init__(self):
        # Initialize the cognitive_service ONCE when the replica is created.
        logger.info("🚀 Initializing warm cognitive_service for new replica...")
        self.cognitive_service: CognitiveService = initialize_cognitive_service()
        logger.info("✅ Cognitive_service is warm and ready.")

    # --- Service & Health Endpoints ---

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
                "execute": "/execute"
            }
        })
        return health_status

    @app.get("/")
    async def root(self):
        """Root endpoint with structured health info."""
        return {
            "status": "healthy",
            "service": "cognitive-warm-replica",
            "message": "SeedCore Cognitive Service is running.",
            "documentation": "See /docs for API details.",
            "endpoint": "/execute"
        }

    @app.get("/info")
    async def info(self):
        """Service information endpoint."""
        return {
            "service": "cognitive-warm-replica",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "deployment": {
                "name": "CognitiveService",
                "replicas": int(os.getenv("COG_SVC_REPLICAS", "1")),
                "max_ongoing_requests": 32
            },
        }

    # --- THE NEW, UNIFIED COGNITIVE ENDPOINT ---

    @app.post("/execute", response_model=CognitiveResponse)
    async def execute_cognitive_task(self, request: CognitiveRequest):
        """
        The single, unified entry point for all cognitive tasks.
        
        This endpoint accepts a CognitiveContext and returns a complete,
        synchronous response. It delegates all routing logic to the
        CognitiveService (Profile Router) and CognitiveCore (Pipeline Router).
        """
        start_time = time.time()
        task_id = request.input_data.get("task_id", "N/A")
        
        try:
            # --- 1. Build the Context ---
            # The client (e.g., Coordinator) is responsible for building
            # the input_data and meta (with decision_kind). This endpoint
            # just merges and passes them through.
            
            input_data_raw = request.input_data or {}
            meta_raw = request.meta or {}
            input_data = normalize_task_payloads(dict(input_data_raw))
            meta = normalize_task_payloads(dict(meta_raw))
            input_data["meta"] = meta
            
            # Add overrides
            if request.llm_provider_override:
                input_data["llm_provider_override"] = request.llm_provider_override
            if request.llm_model_override:
                input_data["llm_model_override"] = request.llm_model_override

            input_data = normalize_task_payloads(input_data)
            meta = input_data.get("meta", meta)

            # Create the final, standard context object
            context = CognitiveContext(
                agent_id=request.agent_id,
                cog_type=request.cog_type,
                input_data=input_data
            )
            
            decision_kind = meta.get("decision_kind", "unknown")
            logger.info(
                f"/execute: Received task_id={task_id} for agent {request.agent_id}. "
                f"cog_type={request.cog_type.value}, decision_kind={decision_kind}"
            )

            # --- 2. Run the blocking call in a thread pool ---
            # This is critical: it prevents the synchronous DSPy/LLM call
            # from blocking the main server (asyncio) event loop.
            # The Coordinator *needs* this to be a blocking call
            # so it can get the 'solution_steps' back.
            result_dict = await asyncio.to_thread(
                self.cognitive_service.forward_cognitive_task,
                context
            )

            # --- 3. Format and Return the Response ---
            processing_time = (time.time() - start_time) * 1000
            logger.info(
                f"/execute: Completed task_id={task_id} for agent {request.agent_id} "
                f"in {processing_time:.2f}ms. Success={result_dict.get('success')}"
            )

            if not result_dict.get("success", False):
                # The task failed, but the API call was successful
                return CognitiveResponse(
                    success=False,
                    result=result_dict.get("result", {}),
                    error=result_dict.get("error", "Cognitive task failed"),
                    metadata=result_dict.get("metadata", {})
                )

            return CognitiveResponse(
                success=True,
                result=result_dict.get("result", {}),
                error=None,
                metadata=result_dict.get("metadata", {})
            )

        except Exception as e:
            processing_time = (time.time() - start_time) * 1000
            tb_str = traceback.format_exc()
            logger.error(
                f"FATAL /execute: Unhandled exception for task_id={task_id} "
                f"after {processing_time:.2f}ms. Error: {e}\n{tb_str}"
            )
            return CognitiveResponse(
                success=False,
                result={},
                error=f"Unhandled exception in API endpoint: {e}",
                metadata={"traceback": tb_str}
            )

    # --- Deprecated Endpoints (Optional) ---
    # You can add these back if you need to support old clients,
    # but for a "concise" refactor, we remove them.
    #
    # @app.post("/plan", deprecated=True)
    # async def plan_deprecated(self):
    #     raise HTTPException(status_code=410, detail="This endpoint is deprecated. Please use /execute.")
    #
    # @app.post("/solve-problem", deprecated=True)
    # async def solve_problem_deprecated(self):
    #     raise HTTPException(status_code=410, detail="This endpoint is deprecated. Please use /execute.")


# --- Main Entrypoint ---
cognitive_app = CognitiveServeService.bind()

def build_cognitive_app(args: dict = None):
    """Builder function for Ray Serve YAML configuration."""
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
        print(f"✅ Cognitive service is running at prefix /cognitive on {RAY_ADDR}")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        print("✅ Serve shutdown complete.")

if __name__ == "__main__":
    main()