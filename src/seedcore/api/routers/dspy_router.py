from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from ...cognitive.dspy_client import for_env


router = APIRouter(prefix="/cog", tags=["cognitive"])


@router.get("/health")
async def cognitive_health() -> Dict[str, Any]:
    client = for_env()
    if not client.ready(timeout_s=6.0):
        # Return serve status snapshot to aid debugging
        try:
            from ray import serve
            s = serve.status()
            return {"status": "starting", "apps": list(s.applications.keys())}
        except Exception:
            raise HTTPException(status_code=503, detail="Cognitive core is not ready")
    # Prefer async health to await Serve deployment method
    try:
        return await asyncio.wait_for(client.health_async(), timeout=8.0)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Cognitive health timed out")


@router.post("/tasks/{agent_id}/assess")
async def assess_agent(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Proxy to Ray Serve cognitive assessment."""
    client = for_env()
    if not client.ready():
        raise HTTPException(status_code=503, detail="Cognitive core not ready")
    performance = payload.get("performance_data", {})
    current_caps = payload.get("current_capabilities", {})
    target_caps = payload.get("target_capabilities", {})
    try:
        return await asyncio.wait_for(
            client.assess(agent_id, performance, current_caps, target_caps),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Cognitive assessment timed out")


@router.post("/tasks/{agent_id}/plan")
async def plan_task(agent_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    client = for_env()
    if not client.ready():
        raise HTTPException(status_code=503, detail="Cognitive core not ready")
    try:
        return await asyncio.wait_for(
            client.plan(
                agent_id,
                payload.get("task_description", ""),
                payload.get("agent_capabilities", {}),
                payload.get("available_resources", {}),
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Cognitive planning timed out")


