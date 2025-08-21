from __future__ import annotations

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
import os
from ray import serve

from ...cognitive import for_env


router = APIRouter(prefix="/cog", tags=["cognitive"])


MIN_READY = int(os.getenv("COG_MIN_READY", "1"))


@router.get("/health")
async def cognitive_health() -> Dict[str, Any]:
    """Production-grade health: reflects Ray Serve application readiness.

    Uses serve.status() to report deployment status and a configurable
    readiness threshold via COG_MIN_READY.
    """
    try:
        status = serve.status()
    except Exception:
        # Ray Serve not initialized or unreachable
        raise HTTPException(status_code=503, detail="Ray Serve status unavailable")

    # Default to cognitive_core unless overridden for staged environments
    app_name = os.getenv("COG_APP_NAME", "cognitive_core")
    app = status.applications.get(app_name)

    if not app:
        return {"status": "not_found", "app": app_name, "apps": list(status.applications.keys())}

    deployment_statuses = getattr(app, "deployment_statuses", []) or []
    running = sum(getattr(d, "num_healthy_replicas", 0) for d in deployment_statuses)
    desired = sum(getattr(d, "target_num_replicas", 0) for d in deployment_statuses)
    min_ready = max(MIN_READY, 1)

    return {
        "status": getattr(app, "status", "UNKNOWN"),
        "ready": running >= min_ready,
        "replicas": {"running": running, "desired": desired, "min_ready": min_ready},
        "app": app_name,
        "route_prefix": getattr(app, "route_prefix", "/cognitive"),
    }


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


