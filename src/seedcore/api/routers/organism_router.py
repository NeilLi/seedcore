from typing import Dict, Any

import time
import ray
from fastapi import APIRouter, HTTPException, Request

# REMOVED: Local OrganismManager import - this is now handled by the Coordinator actor
# from ...organs.organism_manager import organism_manager


router = APIRouter()


# REMOVED: _get_manager_from_request function - this is no longer needed since we don't hold OrganismManager locally

async def _get_coordinator_actor():
    """Get the detached Coordinator actor that manages the OrganismManager."""
    try:
        import os
        # Use the correct namespace from environment variables
        ray_namespace = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        coord = ray.get_actor("seedcore_coordinator", namespace=ray_namespace)
        return coord
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Coordinator actor not available: {str(e)}")


@router.get("/organism/status")
async def get_organism_status(request: Request) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        # Use a simple task to get organism status via Coordinator
        status_task = {
            "type": "get_organism_status",
            "params": {},
            "description": "Get organism status",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(status_task)
        if result.get("success"):
            return {"success": True, "data": result.get("result", {})}
        else:
            return {"success": False, "error": result.get("error", "Failed to get organism status")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/organism/execute/{organ_id}")
async def execute_task_on_organ(organ_id: str, request: Request, task_request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        task_data = task_request.get("task_data", {})
        task = {
            "type": "execute_on_organ",
            "params": {
                "organ_id": organ_id,
                "task_data": task_data
            },
            "description": f"Execute task on organ {organ_id}",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(task)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/execute/random")
async def execute_task_on_random_organ(request: Request, task_request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        task_data = task_request.get("task_data", {})
        task = {
            "type": "execute_on_random_organ",
            "params": {
                "task_data": task_data
            },
            "description": "Execute task on random organ",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(task)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/organism/summary")
async def get_organism_summary(request: Request) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        # Use a task to get organism summary via Coordinator
        summary_task = {
            "type": "get_organism_summary",
            "params": {},
            "description": "Get organism summary",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(summary_task)
        if result.get("success"):
            return {"success": True, "summary": result.get("result", {})}
        else:
            return {"success": False, "error": result.get("error", "Failed to get organism summary")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/initialize")
async def initialize_organism(request: Request) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        # Use a task to initialize organism via Coordinator
        init_task = {
            "type": "initialize_organism",
            "params": {},
            "description": "Initialize organism",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(init_task)
        if result.get("success"):
            return {"success": True, "message": "Organism initialized successfully"}
        else:
            return {"success": False, "error": result.get("error", "Failed to initialize organism")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/shutdown")
async def shutdown_organism(request: Request) -> Dict[str, Any]:
    try:
        coord = await _get_coordinator_actor()
        
        # Use a task to shutdown organism via Coordinator
        shutdown_task = {
            "type": "shutdown_organism",
            "params": {},
            "description": "Shutdown organism",
            "domain": None,
            "drift_score": 0.0
        }
        
        result = await coord.handle.remote(shutdown_task)
        if result.get("success"):
            return {"success": True, "message": "Organism shutdown successfully"}
        else:
            return {"success": False, "error": result.get("error", "Failed to shutdown organism")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- NEW: Coordinator Health Check Endpoint ---
@router.get("/coordinator/health")
async def coordinator_health():
    """Check the health of the Coordinator actor."""
    try:
        coord = await _get_coordinator_actor()
        
        # Use async await instead of ray.get() for better FastAPI responsiveness
        ping_ref = coord.ping.remote()
        ping_result = await ping_ref
        
        if ping_result == "pong":
            return {
                "status": "healthy",
                "coordinator": "available",
                "message": "Coordinator actor is responsive"
            }
        else:
            return {
                "status": "degraded",
                "coordinator": "unresponsive",
                "message": f"Coordinator ping returned unexpected result: {ping_result}"
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "coordinator": "unavailable",
            "message": f"Coordinator actor not available: {str(e)}"
        }


