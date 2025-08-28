#!/usr/bin/env python3
"""
Organism Serve Entrypoint for SeedCore
entrypoints/organism_entrypoint.py

This service runs the organism manager (dispatcher + organs) as a Ray Serve deployment,
converting it from plain Ray actors to a proper Serve application with structured
request/response lifecycles, health checks, and integration with Serve's autoscaling.

This fixes the issue where tasks get locked with status=running but never complete
because they're not being processed by a Serve deployment.
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

# Import organism components
from seedcore.organs.organism_manager import OrganismManager

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- Request/Response Models ---
class OrganismRequest(BaseModel):
    task_type: str
    params: Dict[str, Any] = None
    description: str = None
    domain: str = None
    drift_score: float = None
    app_state: Dict[str, Any] = None

class OrganismResponse(BaseModel):
    success: bool
    result: Dict[str, Any]
    error: Optional[str] = None
    task_type: str = None

class OrganismStatusResponse(BaseModel):
    status: str
    organism_initialized: bool
    organism_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Organism Service", version="1.0.0")

# --------------------------------------------------------------------------
# Ray Serve Deployment: Organism Manager as Serve App
# --------------------------------------------------------------------------
@serve.deployment(
    name="OrganismManager",
    num_replicas=int(os.getenv("ORGANISM_REPLICAS", "1")),
    max_ongoing_requests=10,  # Allow multiple concurrent requests
    ray_actor_options={
        "num_cpus": float(os.getenv("ORGANISM_NUM_CPUS", "0.5")),
        "num_gpus": float(os.getenv("ORGANISM_NUM_GPUS", "0")),
        "memory": int(os.getenv("ORGANISM_MEMORY", "2147483648")),  # 2GB default
        # Pin replicas to the head node resource set by RAY_OVERRIDE_RESOURCES
        "resources": {"head_node": 0.001},
    },
)
@serve.ingress(app)
class OrganismService:
    def __init__(self):
        """
        Lightweight initialization - only create the OrganismManager instance.
        Heavy async initialization will happen in reconfigure() method.
        """
        print("🚀 Creating OrganismManager instance...")
        self.organism_manager = OrganismManager()
        self._initialized = False
        print("✅ OrganismManager instance created (will initialize in reconfigure)")

    async def reconfigure(self, config: dict = None):
        """
        Called automatically by Ray Serve after __init__ completes.
        This is the proper place for async initialization without blocking the event loop.
        """
        print("⏳ Starting async initialization in reconfigure...")
        try:
            await self.organism_manager.initialize_organism()
            self._initialized = True
            print("✅ OrganismManager initialization complete in reconfigure")
        except Exception as e:
            print(f"❌ Failed to initialize organism in reconfigure: {e}")
            self._initialized = False
            raise

    # --- Health and Status Endpoints ---

    @app.get("/health")
    async def health(self):
        """Health check endpoint."""
        return {
            "status": "healthy" if self._initialized else "initializing",
            "service": "organism-manager",
            "route_prefix": "/organism",
            "ray_namespace": RAY_NS,
            "ray_address": RAY_ADDR,
            "organism_initialized": self._initialized,
            "endpoints": {
                "health": "/health",
                "status": "/status",
                "handle_task": "/handle-task",
                "get_organism_status": "/organism-status",
                "get_organism_summary": "/organism-summary"
            }
        }

    @app.get("/status", response_model=OrganismStatusResponse)
    async def status(self):
        """Get detailed status of the organism manager."""
        try:
            if not self._initialized:
                return OrganismStatusResponse(
                    status="unhealthy",
                    organism_initialized=False,
                    error="Organism not initialized"
                )
            
            # Get organism status from the manager
            org_status = await self.organism_manager.get_organism_status()
            
            return OrganismStatusResponse(
                status="healthy",
                organism_initialized=True,
                organism_info=org_status
            )
        except Exception as e:
            return OrganismStatusResponse(
                status="unhealthy",
                organism_initialized=self._initialized,
                error=str(e)
            )

    # --- Core Task Handling Endpoint ---

    @app.post("/handle-task", response_model=OrganismResponse)
    async def handle_task(self, request: OrganismRequest):
        """
        Handle incoming tasks through the organism manager.
        This is the main endpoint that replaces the plain Ray actor task handling.
        """
        try:
            if not self._initialized:
                return OrganismResponse(
                    success=False,
                    result={},
                    error="Organism not initialized",
                    task_type=request.task_type
                )
            
            # Convert request to task format expected by OrganismManager
            task = {
                "type": request.task_type,
                "params": request.params or {},
                "description": request.description or "",
                "domain": request.domain or "general",
                "drift_score": request.drift_score or 0.0
            }
            
            # Handle the task through the organism manager
            result = await self.organism_manager.handle_incoming_task(
                task, 
                app_state=request.app_state
            )
            
            return OrganismResponse(
                success=result.get("success", True),
                result=result,
                task_type=request.task_type
            )
            
        except Exception as e:
            return OrganismResponse(
                success=False,
                result={},
                error=str(e),
                task_type=request.task_type
            )

    # --- Organism Management Endpoints ---

    @app.get("/organism-status")
    async def get_organism_status(self):
        """Get detailed status of all organs in the organism."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            status = await self.organism_manager.get_organism_status()
            return {"success": True, "status": status}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.get("/organism-summary")
    async def get_organism_summary(self):
        """Get a summary of the organism's current state."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            summary = await self.organism_manager.get_organism_summary()
            return {"success": True, "summary": summary}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/initialize-organism")
    async def initialize_organism(self):
        """Manually trigger organism initialization."""
        try:
            if self._initialized:
                return {"success": True, "message": "Organism already initialized"}
            
            await self.organism_manager.initialize_organism()
            self._initialized = True
            return {"success": True, "message": "Organism initialized successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @app.post("/shutdown-organism")
    async def shutdown_organism(self):
        """Manually trigger organism shutdown."""
        try:
            if not self._initialized:
                return {"error": "Organism not initialized"}
            
            self.organism_manager.shutdown_organism()
            self._initialized = False
            return {"success": True, "message": "Organism shutdown successfully"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- Direct Method Access for Backward Compatibility ---

    async def handle_incoming_task(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for backward compatibility with existing code.
        This allows the organism to be called directly via Serve handle.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.handle_incoming_task(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def make_decision(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for decision making.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.make_decision(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def plan_task(self, task: Dict[str, Any], app_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Direct method access for task planning.
        """
        try:
            if not self._initialized:
                return {"success": False, "error": "Organism not initialized"}
            
            return await self.organism_manager.plan_task(task, app_state)
        except Exception as e:
            return {"success": False, "error": str(e)}


# --- Main Entrypoint ---
# At module level so Ray Serve YAML can import directly
organism_app = OrganismService.bind()

def build_organism_app(args: dict = None):
    """
    Builder function for the organism service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    return OrganismService.bind()

def main():
    print("🚀 Starting deployment driver for Organism Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            print("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            organism_app,
            name="organism",
            route_prefix="/organism"
        )
        print("✅ Organism service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        print("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
