"""
HAL Bridge Service
==================
Exposes physical robot hardware or simulation as a SeedCore-compatible microservice.
Bridges the gap between K8s Organs and the Reachy Mini SDK (or simulation server).

Supports two modes:
- Physical: Uses ReachyMiniDriver for real hardware
- Simulation: Uses ReachySimDriver (gRPC) or RobotSimExecutionDriver (plugin framework)
"""

import hashlib
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Internal SeedCore HAL imports
from ..drivers.reachy_mini import ReachyMiniDriver
from ..drivers.reachy_sim import ReachySimDriver
from ..drivers.robot_sim_driver import RobotSimExecutionDriver
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
SIM_BACKEND = os.getenv("HAL_SIM_BACKEND", "reachy_grpc").lower()  # "reachy_grpc" | "robot_sim"
HAL_REQUIRE_EXECUTION_TOKEN = os.getenv("HAL_REQUIRE_EXECUTION_TOKEN", "false").lower() in {
    "1",
    "true",
    "yes",
}

# Global driver instance (initialized in lifespan)
driver: Optional[BaseRobotDriver] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handles startup registration and shutdown cleanup."""
    global driver
    
    logger.info(f"HAL: Initializing bridge for Robot {HARDWARE_UUID} (mode: {DRIVER_MODE})...")
    
    # 1. Initialize driver based on mode
    if DRIVER_MODE == "simulation":
        if SIM_BACKEND == "robot_sim":
            logger.info("HAL: Initializing simulation driver (robot_sim backend)")
            driver = RobotSimExecutionDriver(
                config={
                    "runtime": os.getenv("ROBOT_SIM_RUNTIME", "in_memory"),
                    "gui": os.getenv("ROBOT_SIM_GUI", "false").lower() in {"1", "true", "yes"},
                    "endpoint_id": os.getenv("ROBOT_SIM_ENDPOINT_ID", "robot_sim://pybullet_r2d2_01"),
                    "energy": 65,
                    "warmth": 80,
                }
            )
        else:
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
    if DRIVER_MODE == "simulation" and SIM_BACKEND != "robot_sim":
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
    target: Dict[str, Any] = {}
    energy_override: Optional[int] = None
    warmth_override: Optional[int] = None
    instant: bool = False
    behavior_name: Optional[str] = None
    behavior_params: Dict[str, Any] = {}
    execution_token: Optional[Dict[str, Any]] = None

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
        if isinstance(driver, (ReachySimDriver, RobotSimExecutionDriver)):
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

    logger.info(
        "actuate: Received request - pose_type=%s, instant=%s, behavior_name=%s",
        request.pose_type,
        request.instant,
        request.behavior_name,
    )

    # 1. Apply overrides from the TaskPayload if present
    if request.energy_override:
        logger.debug(f"actuate: Overriding energy to {request.energy_override}")
        driver.config["energy"] = request.energy_override
    if request.warmth_override:
        logger.debug(f"actuate: Overriding warmth to {request.warmth_override}")
        driver.config["warmth"] = request.warmth_override

    # 2. Move / Execute behavior
    try:
        if _requires_token(driver):
            if not _is_valid_execution_token(request.execution_token):
                raise HTTPException(status_code=403, detail="Execution blocked: invalid ExecutionToken")

        endpoint_response: Dict[str, Any]
        if isinstance(driver, RobotSimExecutionDriver):
            behavior_name = request.behavior_name or "actuate_pose"
            behavior_params = dict(request.behavior_params or {})
            if behavior_name == "actuate_pose":
                behavior_params.setdefault("target", request.target)
                behavior_params.setdefault("pose_type", request.pose_type)
            endpoint_response = driver.execute_behavior(
                behavior_name=behavior_name,
                behavior_params=behavior_params,
                execution_token=request.execution_token,
            )
        else:
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
            endpoint_response = {
                "status": "success",
                "behavior": "move_instant" if request.instant else "move_smooth",
                "pose_type": request.pose_type,
                "target": request.target,
            }

        actuator_endpoint = _derive_actuator_endpoint(driver)
        result_hash = _hash_result(endpoint_response)
        final_state = driver.state.value
        logger.info("actuate: Motion completed successfully, final_state=%s", final_state)
        return {
            "status": "accepted",
            "actuator_ack": True,
            "actuator_endpoint": actuator_endpoint,
            "result_hash": result_hash,
            "execution_token_id": (request.execution_token or {}).get("token_id"),
            "robot_state": final_state,
            "endpoint_response": endpoint_response,
        }
    except HTTPException:
        raise
    except PermissionError as e:
        logger.warning("Actuation blocked by governance token validation: %s", e)
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Actuation Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

def _requires_token(active_driver: BaseRobotDriver) -> bool:
    return HAL_REQUIRE_EXECUTION_TOKEN or isinstance(active_driver, RobotSimExecutionDriver)


def _is_valid_execution_token(token: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(token, dict):
        return False
    token_id = token.get("token_id")
    intent_id = token.get("intent_id")
    signature = token.get("signature")
    valid_until = token.get("valid_until")
    if not token_id or not intent_id or not signature or not isinstance(valid_until, str):
        return False
    try:
        ts = datetime.fromisoformat(valid_until.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ts.astimezone(timezone.utc) > datetime.now(timezone.utc)


def _derive_actuator_endpoint(active_driver: BaseRobotDriver) -> str:
    endpoint = getattr(active_driver, "_endpoint_id", None)
    if isinstance(endpoint, str) and endpoint.strip():
        return endpoint
    if isinstance(active_driver, ReachySimDriver):
        return "hal://reachy-sim-grpc"
    if isinstance(active_driver, ReachyMiniDriver):
        return "hal://reachy-mini"
    return f"hal://{active_driver.__class__.__name__.lower()}"


def _hash_result(result: Dict[str, Any]) -> str:
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
