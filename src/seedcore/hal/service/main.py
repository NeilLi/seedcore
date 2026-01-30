"""
HAL Bridge Service
==================
Exposes physical robot hardware or simulation as a SeedCore-compatible microservice.
Bridges the gap between K8s Organs and the Reachy Mini SDK (or simulation server).

Supports two modes:
- Physical: Uses ReachyMiniDriver for real hardware
- Simulation: Uses ReachySimDriver for gRPC simulation server
"""

import os
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Internal SeedCore HAL imports
from ..drivers.reachy_mini import ReachyMiniDriver
from ..drivers.reachy_sim import ReachySimDriver
from ..interfaces import RobotState, BaseRobotDriver

# Configure logging - ensure logs go to stdout/stderr for Kubernetes
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Explicitly use stdout/stderr
)
logger = logging.getLogger("hal.service")

# --- Registry & Hardware Identity ---
# Unique ID for this specific robot instance (physical or simulation)
HARDWARE_UUID = os.getenv("HARDWARE_UUID", str(uuid.uuid4()))

# Determine driver mode from environment
DRIVER_MODE = os.getenv("HAL_DRIVER_MODE", "physical").lower()  # "physical" or "simulation"
ROBOT_HOST = os.getenv("ROBOT_HOST", "localhost")
SIM_GRPC_ADDRESS = os.getenv("REACHY_SIM_ADDRESS", "localhost:50055")  # Default matches demo_simulator.py

# Global driver instance (initialized in lifespan)
driver: Optional[BaseRobotDriver] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup registration and shutdown cleanup."""
    global driver
    
    logger.info(f"HAL: Initializing bridge for Robot {HARDWARE_UUID} (mode: {DRIVER_MODE})...")
    
    # 1. Initialize driver based on mode
    if DRIVER_MODE == "simulation":
        logger.info(f"HAL: Initializing simulation driver (gRPC: {SIM_GRPC_ADDRESS})")
        driver = ReachySimDriver(config={
            "grpc_address": SIM_GRPC_ADDRESS,
            "energy": 65,  # Default from UI
            "warmth": 80   # Default from UI
        })
    else:
        logger.info(f"HAL: Initializing physical driver (host: {ROBOT_HOST})")
        driver = ReachyMiniDriver(config={
            "host": ROBOT_HOST,
            "energy": 65,  # Default from UI
            "warmth": 80   # Default from UI
        })
    
    # 2. Connect to Hardware/Simulation
    # Note: In simulation mode, the sim server is started as a background process
    # by the container entrypoint script, so we retry connection here
    logger.info(f"HAL: Attempting to connect to robot ({DRIVER_MODE} mode)...")
    if DRIVER_MODE == "simulation":
        logger.info(f"HAL: Waiting for simulation server at {SIM_GRPC_ADDRESS}...")
    
    if driver.connect():
        logger.info(f"HAL: ✅ Robot {HARDWARE_UUID} is ONLINE ({DRIVER_MODE} mode, state: {driver.state.value})")
    else:
        logger.error(f"HAL: ❌ Failed to connect ({DRIVER_MODE} mode, state: {driver.state.value})")
        if DRIVER_MODE == "simulation":
            logger.error(f"HAL: Make sure simulation server is running at {SIM_GRPC_ADDRESS}")
            logger.error(f"HAL: Check container logs for 'RobotSim gRPC server listening' message")
        
    yield
    
    # 3. Graceful Shutdown
    if driver:
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
    if not driver:
        logger.error("get_status: Driver not initialized")
        raise HTTPException(status_code=503, detail="Driver not initialized")
    
    logger.debug(f"get_status: Driver state={driver.state.value}, mode={DRIVER_MODE}")
    
    proprioception = None
    # Allow CONNECTED and MOVING states for proprioception
    if driver.state in (RobotState.CONNECTED, RobotState.MOVING):
        try:
            proprioception = driver.get_proprioception().__dict__
            logger.debug(f"get_status: Retrieved proprioception data")
        except Exception as e:
            logger.warning(f"Failed to get proprioception: {e}", exc_info=True)
    
    response = {
        "hardware_uuid": HARDWARE_UUID,
        "driver_mode": DRIVER_MODE,
        "state": driver.state.value,
        "proprioception": proprioception
    }
    logger.debug("get_status: Returning status: state=%s, has_proprioception=%s", response['state'], proprioception is not None)
    return response

@app.get("/state")
async def get_state():
    """
    Get current robot state (head, antennas, body_yaw).
    
    This endpoint provides the raw robot state for tool calls.
    """
    if not driver:
        logger.error("get_state: Driver not initialized")
        raise HTTPException(status_code=503, detail="Driver not initialized")
    
    # Allow CONNECTED and MOVING states (MOVING is valid during motion)
    if driver.state not in (RobotState.CONNECTED, RobotState.MOVING):
        logger.warning(f"get_state: Invalid driver state: {driver.state.value}")
        raise HTTPException(status_code=503, detail=f"Robot not ready (state: {driver.state.value})")
    
    try:
        logger.debug(f"get_state: Retrieving state (driver_mode={DRIVER_MODE}, state={driver.state.value})")
        # For simulation driver, use get_state() method
        if isinstance(driver, ReachySimDriver):
            state = driver.get_state()
        else:
            # For physical driver, construct state from get_current_pose
            head_pose = driver.get_current_pose("head")
            antennas_pose = driver.get_current_pose("antennas")
            body_pose = driver.get_current_pose("body")
            
            state = {
                "head": head_pose,
                "antennas": [antennas_pose.get("left", 0.0), antennas_pose.get("right", 0.0)],
                "body_yaw": body_pose.get("yaw", 0.0)
            }
        
        logger.debug(f"get_state: Returning state: {state}")
        return state
    except Exception as e:
        logger.error(f"Error getting state: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/actuate")
async def actuate(request: ActuationRequest):
    """
    Standardized entry point for SeedCore 'tool_calls'.
    Translates JSON to SDK commands via the ReachyAdapter.
    
    Supports both physical hardware and simulation drivers.
    """
    if not driver:
        logger.error("actuate: Driver not initialized")
        raise HTTPException(status_code=503, detail="Driver not initialized")
    
    # Allow CONNECTED and MOVING states (can queue commands)
    if driver.state not in (RobotState.CONNECTED, RobotState.MOVING):
        logger.warning(f"actuate: Invalid driver state: {driver.state.value}")
        raise HTTPException(status_code=503, detail=f"Robot not ready (state: {driver.state.value})")

    logger.info(f"actuate: Received request - pose_type={request.pose_type}, instant={request.instant}, target={request.target}")

    # 1. Apply overrides from the TaskPayload if present
    if request.energy_override:
        logger.debug(f"actuate: Overriding energy to {request.energy_override}")
        driver.config["energy"] = request.energy_override
    if request.warmth_override:
        logger.debug(f"actuate: Overriding warmth to {request.warmth_override}")
        driver.config["warmth"] = request.warmth_override

    # 2. Move
    try:
        if request.instant:
            # High-frequency VLA path (20Hz)
            logger.info("actuate: Executing instant motion")
            driver.move_instant(request.target, pose_type=request.pose_type)
        else:
            # Smooth 'Dream' path based on UI sliders
            logger.info("actuate: Executing smooth motion")
            success = driver.move_smooth(request.target, pose_type=request.pose_type)
            if not success:
                logger.error("actuate: Motion command rejected by driver")
                raise HTTPException(status_code=500, detail="Motion command rejected")
        
        final_state = driver.state.value
        logger.info(f"actuate: Motion completed successfully, final_state={final_state}")
        return {"status": "accepted", "robot_state": final_state}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Actuation Error: {str(e)}", exc_info=True)
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