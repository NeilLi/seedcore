from fastapi import APIRouter
from fastapi.responses import JSONResponse
import logging
from ...utils.ray_utils import is_ray_available
from ...utils.ray_connector import connect, wait_for_ray_ready

router = APIRouter()
logger = logging.getLogger(__name__)

def _readiness_check():
    reasons = []

    # 1) Ray must be connected
    if not is_ray_available():
        reasons.append("ray:not_connected")

    # 2) REMOVED: OrganismManager check - this is now handled by the Coordinator actor
    # The API should not bootstrap or hold a live OrganismManager

    return reasons

@router.get("/readyz", include_in_schema=False)
async def readyz():
    # Try to self-heal readiness quickly
    if not is_ray_available():
        try:
            # 1) Connect to Ray if needed
            if not is_ray_available():
                connect()  # idempotent
                if not wait_for_ray_ready(max_wait_seconds=5):  # Shorter timeout for /readyz
                    pass  # Continue with status check
        except Exception as e:
            logger.warning(f"Self-heal attempt in /readyz failed: {e}")

    ray_ok = is_ray_available()
    # REMOVED: organism_ok check - this is now handled by the Coordinator actor
    status = 200 if ray_ok else 503
    return JSONResponse(
        {"ray_ok": ray_ok, "organism_ok": "coordinator_managed"}, 
        status_code=status
    )

@router.head("/readyz", include_in_schema=False)
async def readyz_head():
    reasons = _readiness_check()
    return JSONResponse(status_code=200 if not reasons else 503, content=None)
