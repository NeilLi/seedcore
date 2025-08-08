from typing import Dict, Any

import time
import ray
from fastapi import APIRouter, HTTPException, Request

from ...organs.organism_manager import organism_manager


router = APIRouter()


def _get_manager_from_request(request: Request):
    org = getattr(request.app.state, "organism", None)
    return org if org is not None else organism_manager


@router.get("/organism/status")
async def get_organism_status(request: Request) -> Dict[str, Any]:
    try:
        org = _get_manager_from_request(request)
        if not getattr(org, "is_initialized", lambda: False)():
            return {"success": False, "error": "Organism not initialized"}

        status = await org.get_organism_status()
        return {"success": True, "data": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/organism/execute/{organ_id}")
async def execute_task_on_organ(organ_id: str, request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        # Use global singleton to execute tasks; app state is set during startup
        if not organism_manager.is_initialized():
            return {"success": False, "error": "Organism not initialized"}

        task_data = request.get("task_data", {})
        result = await organism_manager.execute_task_on_organ(organ_id, task_data)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/execute/random")
async def execute_task_on_random_organ(request: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not organism_manager.is_initialized():
            return {"success": False, "error": "Organism not initialized"}

        task_data = request.get("task_data", {})
        result = await organism_manager.execute_task_on_random_organ(task_data)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/organism/summary")
async def get_organism_summary(request: Request) -> Dict[str, Any]:
    try:
        org = _get_manager_from_request(request)
        if not getattr(org, "is_initialized", lambda: False)():
            return {"success": False, "error": "Organism not initialized"}

        summary = {
            "initialized": org.is_initialized(),
            "organ_count": org.get_organ_count(),
            "total_agent_count": org.get_total_agent_count(),
            "organs": {}
        }

        # Get detailed organ info via Ray actor handles
        for organ_id in org.organs.keys():
            organ_handle = org.get_organ_handle(organ_id)
            if organ_handle:
                try:
                    status = await organ_handle.get_status.remote()
                    summary["organs"][organ_id] = status
                except Exception as e:  # pragma: no cover - best effort
                    summary["organs"][organ_id] = {"error": str(e)}

        return {"success": True, "summary": summary}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/initialize")
async def initialize_organism(request: Request) -> Dict[str, Any]:
    try:
        # Always use global manager; server startup also assigns it to app.state
        if organism_manager.is_initialized():
            # Ensure app state reflects global manager
            setattr(request.app.state, "organism", organism_manager)
            return {"success": True, "message": "Organism already initialized"}

        await organism_manager.initialize_organism()
        setattr(request.app.state, "organism", organism_manager)
        return {"success": True, "message": "Organism initialized successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.post("/organism/shutdown")
async def shutdown_organism(request: Request) -> Dict[str, Any]:
    try:
        org = _get_manager_from_request(request)
        if not getattr(org, "is_initialized", lambda: False)():
            return {"success": False, "error": "Organism not initialized"}

        org.shutdown_organism()
        return {"success": True, "message": "Organism shutdown successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}


