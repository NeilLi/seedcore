from typing import Dict, Any

import time
from fastapi import APIRouter, HTTPException, Request

# Import the new organism serve client
from ...serve.organism_client import get_organism_client


router = APIRouter()


async def _get_organism_client():
    """Get the organism serve client that communicates with the Serve-deployed organism."""
    try:
        client = get_organism_client()
        return client
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Organism service not available: {str(e)}")


@router.get("/organism/status")
async def get_organism_status(request: Request) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
        # Get organism status directly from the serve client
        result = await client.get_organism_status()
        if result.get("success"):
            return {"success": True, "data": result.get("status", {})}
        else:
            return {"success": False, "error": result.get("error", "Failed to get organism status")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/organism/execute/{organ_id}")
async def execute_task_on_organ(organ_id: str, request: Request, task_request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
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
        
        result = await client.handle_incoming_task(task)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/execute/random")
async def execute_task_on_random_organ(request: Request, task_request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
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
        
        result = await client.handle_incoming_task(task)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/organism/summary")
async def get_organism_summary(request: Request) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
        # Get organism summary directly from the serve client
        result = await client.get_organism_summary()
        if result.get("success"):
            return {"success": True, "summary": result.get("summary", {})}
        else:
            return {"success": False, "error": result.get("error", "Failed to get organism summary")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/initialize")
async def initialize_organism(request: Request) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
        # Initialize organism directly via the serve client
        result = await client.handle_incoming_task({
            "type": "initialize_organism",
            "params": {},
            "description": "Initialize organism",
            "domain": None,
            "drift_score": 0.0
        })
        if result.get("success"):
            return {"success": True, "message": "Organism initialized successfully"}
        else:
            return {"success": False, "error": result.get("error", "Failed to initialize organism")}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/shutdown")
async def shutdown_organism(request: Request) -> Dict[str, Any]:
    try:
        client = await _get_organism_client()
        
        # Shutdown organism directly via the serve client
        result = await client.handle_incoming_task({
            "type": "shutdown_organism",
            "params": {},
            "description": "Shutdown organism",
            "domain": None,
            "drift_score": 0.0
        })
        if result.get("success"):
            return {"success": True, "message": "Organism shutdown successfully"}
        else:
            return {"success": False, "error": result.get("error", "Failed to shutdown organism")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# --- NEW: Organism Service Health Check Endpoint ---
@router.get("/organism/health")
async def organism_health():
    """Check the health of the Organism service."""
    try:
        client = await _get_organism_client()
        
        # Check organism service health
        health_result = await client.health_check()
        
        if health_result.get("status") == "healthy":
            return {
                "status": "healthy",
                "organism": "available",
                "message": "Organism service is healthy",
                "organism_initialized": health_result.get("organism_initialized", False)
            }
        else:
            return {
                "status": "degraded",
                "organism": "unhealthy",
                "message": f"Organism service status: {health_result.get('status', 'unknown')}",
                "organism_initialized": health_result.get("organism_initialized", False)
            }
    except Exception as e:
        return {
            "status": "unhealthy",
            "organism": "unavailable",
            "message": f"Organism service not available: {str(e)}"
        }


