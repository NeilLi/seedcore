"""
HAL Bridge Service
==================
Exposes physical robot hardware as a SeedCore-compatible microservice.
Bridges the gap between K8s Organs and the Reachy Mini SDK.
"""

import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel

# Internal SeedCore HAL imports
from ..drivers.reachy_mini import ReachyMiniDriver
from ..adapters.reachy_adapter import ReachyAdapter
from ..interfaces import RobotState

# Configure logging for the Hackathon dashboard
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hal.service")

# --- Registry & Hardware Identity ---
# Unique ID for this specific physical robot instance
HARDWARE_UUID = os.getenv("HARDWARE_UUID", str(uuid.uuid4()))
ROBOT_HOST = os.getenv("ROBOT_HOST", "localhost")

# Global driver instance
driver = ReachyMiniDriver(config={
    "host": ROBOT_HOST,
    "energy": 65,  # Default from UI
    "warmth": 80   # Default from UI
})

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup registration and shutdown cleanup."""
    logger.info(f"HAL: Initializing bridge for Robot {HARDWARE_UUID}...")
    
    # 1. Connect to Hardware
    if driver.connect():
        # 2. Register Liveness in SeedCore Database (Simulated via API call)
        # In a full setup, this would be a POST to the agent_registry
        logger.info(f"HAL: Robot {HARDWARE_UUID} is ONLINE at {ROBOT_HOST}")
    else:
        logger.error("HAL: Failed to connect to physical hardware.")
        
    yield
    
    # 3. Graceful Shutdown
    driver.disconnect()
    logger.info("HAL: Bridge shutdown complete.")

app = FastAPI(title="SeedCore HAL Bridge", lifespan=lifespan)

# --- Request Schemas ---

class ActuationRequest(BaseModel):
    pose_type: str = "head"
    target: Dict[str, Any]
    energy_override: Optional[int] = None
    warmth_override: Optional[int] = None
    instant: bool = False

# --- API Endpoints ---

@app.get("/status")
async def get_status():
    """Returns the current 'Pulse' of the robot."""
    return {
        "hardware_uuid": HARDWARE_UUID,
        "state": driver.state.value,
        "proprioception": driver.get_proprioception().__dict__ if driver.state == RobotState.CONNECTED else None
    }

@app.post("/actuate")
async def actuate(request: ActuationRequest):
    """
    Standardized entry point for SeedCore 'tool_calls'.
    Translates JSON to SDK commands via the ReachyAdapter.
    """
    if driver.state != RobotState.CONNECTED:
        raise HTTPException(status_code=503, detail="Robot not connected")

    # 1. Apply overrides from the TaskPayload if present
    if request.energy_override:
        driver.config["energy"] = request.energy_override
    if request.warmth_override:
        driver.config["warmth"] = request.warmth_override

    # 2. Move
    try:
        if request.instant:
            # High-frequency VLA path (20Hz)
            driver.move_instant(request.target)
        else:
            # Smooth 'Dream' path based on UI sliders
            driver.move_smooth(request.target)
            
        return {"status": "accepted", "robot_state": driver.state.value}
    except Exception as e:
        logger.error(f"Actuation Error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/vision/frame")
async def get_frame():
    """Provides latest frame for the 'Multimodal' envelope."""
    frame = driver.get_latest_frame()
    if frame is None:
        raise HTTPException(status_code=404, detail="Camera stream unavailable")
    # In production, return as StreamingResponse (JPEG/WebP)
    return {"message": "Frame captured", "shape": frame.shape}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)