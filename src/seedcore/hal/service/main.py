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
import hmac
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List

from fastapi import FastAPI, Header, HTTPException
from ..custody.forensic_sealer import ForensicSealer
from ..custody.transition_receipts import build_transition_receipt
from pydantic import BaseModel, Field
from ...database import get_redis_client
from ...integrations.rust_kernel import (
    enforce_execution_token_with_rust,
    map_token_error_for_hal,
    verify_execution_token_with_rust,
)

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
EXECUTION_TOKEN_REVOCATION_PREFIX = os.getenv(
    "SEEDCORE_EXECUTION_TOKEN_CRL_PREFIX",
    "seedcore:execution_token:revoked:",
)
EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY = os.getenv(
    "SEEDCORE_EXECUTION_TOKEN_CRL_CUTOFF_KEY",
    "seedcore:execution_token:revoked_before",
)
DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS = 300

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

class ForensicSealRequest(BaseModel):
    event_id: str
    platform_state: str
    trajectory_hash: Optional[str] = None
    policy_hash: str
    auth_token: str
    from_zone: str
    to_zone: str
    transition_receipt: Optional[Dict[str, Any]] = None
    actuator_telemetry: Dict[str, Any] = Field(default_factory=dict)
    media_hash_references: List[Dict[str, Any]] = Field(default_factory=list)

class ActuationRequest(BaseModel):
    pose_type: str = "head"
    target: Dict[str, Any] = {}
    energy_override: Optional[int] = None
    warmth_override: Optional[int] = None
    instant: bool = False
    behavior_name: Optional[str] = None
    behavior_params: Dict[str, Any] = {}
    execution_token: Optional[Dict[str, Any]] = None


class RevokeExecutionTokenRequest(BaseModel):
    token_id: str
    ttl_seconds: Optional[int] = None
    reason: Optional[str] = None


class EmergencyStopRequest(BaseModel):
    issued_before: Optional[str] = None
    reason: Optional[str] = None

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

@app.post("/forensic-seal")
async def forensic_seal(request: ForensicSealRequest):
    """
    Generates a cryptographically sealed Honey Digital Twin custody event.
    Captures edge telemetry synchronously to prevent timing divergence.
    """
    try:
        _validate_hashed_media_references(request.media_hash_references)

        # 1. Initialize the edge sealer with an attestable endpoint identity.
        sealer = ForensicSealer(device_identity=_derive_sealer_identity())

        # 2. Capture HAL telemetry only (no remote fetch/interpretation of social/video content)
        environmental_data: Dict[str, float] = {}
        actuator_telemetry = dict(request.actuator_telemetry or {})
        if driver and driver.state in (RobotState.CONNECTED, RobotState.MOVING):
            try:
                proprioception = driver.get_proprioception().__dict__
                for key, value in proprioception.items():
                    if isinstance(key, str) and isinstance(value, (int, float)):
                        environmental_data[key] = float(value)
            except Exception:
                logger.debug("forensic_seal: failed to capture driver proprioception", exc_info=True)

        # Merge explicit request environmental telemetry (request wins)
        explicit_env = (
            actuator_telemetry.get("environmental_telemetry")
            if isinstance(actuator_telemetry.get("environmental_telemetry"), dict)
            else {}
        )
        for key, value in explicit_env.items():
            if isinstance(key, str) and isinstance(value, (int, float)):
                environmental_data[key] = float(value)

        # 3. Seal pilot event from HAL/actuator telemetry + transition receipt + hashed media refs
        custody_event = sealer.seal_custody_event_pilot(
            event_id=request.event_id,
            platform_state=request.platform_state,
            policy_hash=request.policy_hash,
            auth_token=request.auth_token,
            from_zone=request.from_zone,
            to_zone=request.to_zone,
            transition_receipt=request.transition_receipt,
            actuator_telemetry=actuator_telemetry,
            media_hash_references=list(request.media_hash_references or []),
            trajectory_hash=request.trajectory_hash,
            environmental_data=environmental_data,
        )

        return custody_event.model_dump(by_alias=True)
    except Exception as e:
        logger.error(f"Failed to seal forensic event: {e}", exc_info=True)
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
            token_error = _validate_execution_token(request.execution_token, driver)
            if token_error is not None:
                raise HTTPException(
                    status_code=403,
                    detail=f"Execution blocked: {token_error}",
                )

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
        transition_receipt = _build_actuation_transition_receipt(
            execution_token=request.execution_token,
            actuator_endpoint=actuator_endpoint,
            actuator_result_hash=result_hash,
        )
        final_state = driver.state.value
        logger.info("actuate: Motion completed successfully, final_state=%s", final_state)
        return {
            "status": "accepted",
            "actuator_ack": True,
            "actuator_endpoint": actuator_endpoint,
            "result_hash": result_hash,
            "execution_token_id": (request.execution_token or {}).get("token_id"),
            "robot_state": final_state,
            "transition_receipt": transition_receipt,
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


@app.post("/admin/execution-tokens/revoke")
async def revoke_execution_token(
    request: RevokeExecutionTokenRequest,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)
    ttl_seconds = request.ttl_seconds or _execution_token_crl_ttl_seconds()
    if not request.token_id.strip():
        raise HTTPException(status_code=400, detail="token_id is required")

    try:
        stored = _store_revoked_execution_token(
            token_id=request.token_id.strip(),
            ttl_seconds=ttl_seconds,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "revoked",
        "token_id": request.token_id.strip(),
        "ttl_seconds": ttl_seconds,
        "stored": stored,
        "reason": request.reason,
    }


@app.post("/admin/execution-tokens/e-stop")
async def emergency_stop_execution_tokens(
    request: EmergencyStopRequest,
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)

    issued_before = _parse_optional_iso8601(request.issued_before) or datetime.now(timezone.utc)

    try:
        _set_execution_token_revocation_cutoff(issued_before)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if driver is not None:
        try:
            driver.emergency_stop()
        except Exception as exc:
            logger.warning("HAL driver emergency_stop failed during E-Stop: %s", exc)

    return {
        "status": "emergency_stopped",
        "issued_before": issued_before.isoformat(),
        "reason": request.reason,
        "driver_state": driver.state.value if driver is not None else None,
    }


@app.delete("/admin/execution-tokens/e-stop")
async def clear_emergency_stop_execution_tokens(
    x_admin_token: str | None = Header(default=None),
):
    _require_admin_token(x_admin_token)

    try:
        cleared = _clear_execution_token_revocation_cutoff()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "status": "emergency_stop_cleared",
        "cleared": cleared,
    }

def _requires_token(active_driver: BaseRobotDriver) -> bool:
    return HAL_REQUIRE_EXECUTION_TOKEN or isinstance(active_driver, RobotSimExecutionDriver)


def _is_valid_execution_token(
    token: Optional[Dict[str, Any]],
    active_driver: Optional[BaseRobotDriver] = None,
) -> bool:
    return _validate_execution_token(token, active_driver) is None


def _validate_execution_token(
    token: Optional[Dict[str, Any]],
    active_driver: Optional[BaseRobotDriver] = None,
) -> Optional[str]:
    if not isinstance(token, dict):
        return "invalid ExecutionToken"

    token_id = token.get("token_id")
    valid_until_raw = token.get("valid_until")
    intent_id = token.get("intent_id")
    issued_at = token.get("issued_at")
    contract_version = token.get("contract_version")
    signature = token.get("signature")
    artifact_hash = token.get("artifact_hash")
    constraints = token.get("constraints")

    if not token_id or not isinstance(valid_until_raw, str):
        return "invalid ExecutionToken"
    if not isinstance(intent_id, str) or not intent_id.strip():
        return "invalid ExecutionToken"
    if not isinstance(issued_at, str) or not issued_at.strip():
        return "invalid ExecutionToken"
    if not isinstance(contract_version, str) or not contract_version.strip():
        return "invalid ExecutionToken"
    if not isinstance(signature, dict):
        return "invalid ExecutionToken"
    if not isinstance(artifact_hash, dict):
        return "invalid ExecutionToken"
    if not isinstance(constraints, dict):
        return "invalid ExecutionToken"

    try:
        ts = datetime.fromisoformat(valid_until_raw.replace("Z", "+00:00"))
        issued_at_ts = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
    except ValueError:
        return "invalid ExecutionToken"

    ts = ts.astimezone(timezone.utc)
    issued_at_ts = issued_at_ts.astimezone(timezone.utc)
    if ts <= issued_at_ts:
        return "invalid ExecutionToken"
    revocation_error = _validate_execution_token_revocation(
        token_id=str(token_id),
        issued_at=issued_at_ts,
    )
    if revocation_error is not None:
        return revocation_error
    if ts <= datetime.now(timezone.utc):
        return "expired ExecutionToken"
    rust_verify = verify_execution_token_with_rust(
        token,
        now=datetime.now(timezone.utc),
    )
    if not bool(rust_verify.get("verified")):
        return map_token_error_for_hal(rust_verify.get("error_code"))

    constraint_error = _validate_execution_token_constraints(
        token=token,
        constraints=constraints,
        active_driver=active_driver,
    )
    if constraint_error is not None:
        return constraint_error

    return None

def _coerce_execution_token(token: Dict[str, Any]) -> Any:
    # Kept for compatibility if used elsewhere, though not required internally now
    return token



def _execution_token_crl_ttl_seconds() -> int:
    raw = os.getenv(
        "SEEDCORE_EXECUTION_TOKEN_CRL_TTL_SECONDS",
        str(DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS),
    )
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_EXECUTION_TOKEN_CRL_TTL_SECONDS


def _require_admin_token(provided_token: Optional[str]) -> None:
    expected = os.getenv("SEEDCORE_HAL_ADMIN_TOKEN", "").strip()
    if not expected:
        return
    if not provided_token or not hmac.compare_digest(provided_token, expected):
        raise HTTPException(status_code=403, detail="invalid admin token")


def _get_required_redis_client():
    redis_client = get_redis_client()
    if redis_client is None:
        raise RuntimeError("Redis unavailable for execution token revocation")
    return redis_client


def _store_revoked_execution_token(*, token_id: str, ttl_seconds: int) -> bool:
    redis_client = _get_required_redis_client()
    key = f"{EXECUTION_TOKEN_REVOCATION_PREFIX}{token_id}"
    return bool(redis_client.setex(key, max(1, ttl_seconds), "1"))


def _set_execution_token_revocation_cutoff(issued_before: datetime) -> bool:
    redis_client = _get_required_redis_client()
    value = issued_before.astimezone(timezone.utc).isoformat()
    return bool(redis_client.set(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY, value))


def _clear_execution_token_revocation_cutoff() -> bool:
    redis_client = _get_required_redis_client()
    return bool(redis_client.delete(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY))


def _parse_optional_iso8601(value: Optional[str]) -> Optional[datetime]:
    if value is None or not value.strip():
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_execution_token_revocation(
    *,
    token_id: str,
    issued_at: datetime,
) -> Optional[str]:
    redis_client = get_redis_client()
    if redis_client is None:
        return None

    try:
        if redis_client.exists(f"{EXECUTION_TOKEN_REVOCATION_PREFIX}{token_id}"):
            return "revoked ExecutionToken"

        revoked_before = redis_client.get(EXECUTION_TOKEN_REVOCATION_CUTOFF_KEY)
        if isinstance(revoked_before, str) and revoked_before.strip():
            revoked_before_ts = datetime.fromisoformat(revoked_before.replace("Z", "+00:00"))
            if revoked_before_ts.tzinfo is None:
                revoked_before_ts = revoked_before_ts.replace(tzinfo=timezone.utc)
            if issued_at <= revoked_before_ts.astimezone(timezone.utc):
                return "revoked ExecutionToken"
    except Exception as exc:
        logger.warning("Execution token revocation check unavailable: %s", exc)

    return None


def _derive_actuator_endpoint(active_driver: BaseRobotDriver) -> str:
    endpoint = getattr(active_driver, "_endpoint_id", None)
    if isinstance(endpoint, str) and endpoint.strip():
        return endpoint
    if isinstance(active_driver, ReachySimDriver):
        return "hal://reachy-sim-grpc"
    if isinstance(active_driver, ReachyMiniDriver):
        return "hal://reachy-mini"
    return f"hal://{active_driver.__class__.__name__.lower()}"


def _derive_sealer_identity() -> str:
    if driver is not None:
        return _derive_actuator_endpoint(driver)
    normalized = str(HARDWARE_UUID).strip()
    if "://" in normalized:
        return normalized
    return f"hal://{normalized}"


def _hash_result(result: Dict[str, Any]) -> str:
    payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_actuation_transition_receipt(
    *,
    execution_token: Optional[Dict[str, Any]],
    actuator_endpoint: str,
    actuator_result_hash: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(execution_token, dict):
        return None

    intent_id = execution_token.get("intent_id")
    token_id = execution_token.get("token_id")
    constraints = (
        execution_token.get("constraints")
        if isinstance(execution_token.get("constraints"), dict)
        else {}
    )
    if not isinstance(intent_id, str) or not intent_id.strip():
        return None
    if not isinstance(token_id, str) or not token_id.strip():
        return None

    target_zone = constraints.get("target_zone")
    from_zone = constraints.get("current_zone")
    to_zone = target_zone if isinstance(target_zone, str) and target_zone.strip() else None
    workflow_type = None
    if isinstance(constraints.get("approval_envelope_id"), str) and constraints.get("approval_envelope_id"):
        workflow_type = "custody_transfer"
    elif isinstance(constraints.get("workflow_type"), str) and constraints.get("workflow_type"):
        workflow_type = str(constraints.get("workflow_type"))

    return build_transition_receipt(
        intent_id=intent_id,
        token_id=token_id,
        actuator_endpoint=actuator_endpoint,
        hardware_uuid=HARDWARE_UUID,
        actuator_result_hash=actuator_result_hash,
        target_zone=str(target_zone) if target_zone is not None else None,
        from_zone=str(from_zone) if from_zone is not None else None,
        to_zone=to_zone,
        workflow_type=workflow_type,
        previous_receipt_hash=(
            str(constraints.get("previous_receipt_hash"))
            if constraints.get("previous_receipt_hash") is not None
            else None
        ),
        previous_receipt_counter=(
            int(constraints.get("previous_receipt_counter"))
            if constraints.get("previous_receipt_counter") is not None
            else None
        ),
    )


def _validate_hashed_media_references(media_refs: List[Dict[str, Any]]) -> None:
    if not isinstance(media_refs, list):
        raise HTTPException(
            status_code=422,
            detail="media_hash_references must be a list of hash reference objects",
        )
    forbidden_markers = (
        "youtube.com",
        "youtu.be",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "instagram.com",
        "facebook.com",
    )
    for idx, item in enumerate(media_refs):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=422,
                detail=f"media_hash_references[{idx}] must be an object",
            )
        digest = item.get("sha256") or item.get("hash") or item.get("digest")
        if not (isinstance(digest, str) and digest.strip()):
            raise HTTPException(
                status_code=422,
                detail=f"media_hash_references[{idx}] requires sha256/hash/digest",
            )
        uri = item.get("uri")
        if isinstance(uri, str) and uri.strip():
            lowered = uri.strip().lower()
            if lowered.startswith("http://") or lowered.startswith("https://"):
                if any(marker in lowered for marker in forbidden_markers):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "HAL sealer pilot does not fetch or interpret social/video URLs. "
                            "Send hashed media references only."
                        ),
                    )


def _validate_execution_token_constraints(
    *,
    token: Dict[str, Any],
    constraints: Dict[str, Any],
    active_driver: Optional[BaseRobotDriver],
) -> Optional[str]:
    if active_driver is None:
        return None

    endpoint_constraint = constraints.get("endpoint_id") or constraints.get("actuator_endpoint")
    expected_endpoint = _derive_actuator_endpoint(active_driver)
    target_zone = constraints.get("target_zone")
    configured_zones = _configured_target_zones()

    rust_request = {
        "action_type": constraints.get("action_type"),
        "target_zone": (
            next(iter(configured_zones))
            if len(configured_zones) == 1
            else target_zone
        ),
        "asset_id": constraints.get("asset_id"),
        "principal_agent_id": constraints.get("principal_agent_id"),
        "source_registration_id": constraints.get("source_registration_id"),
        "registration_decision_id": constraints.get("registration_decision_id"),
        "endpoint_id": expected_endpoint,
    }
    rust_enforcement = enforce_execution_token_with_rust(
        token,
        rust_request,
        now=datetime.now(timezone.utc),
    )
    if not bool(rust_enforcement.get("allowed")):
        return map_token_error_for_hal(rust_enforcement.get("error_code"))

    if (
        isinstance(endpoint_constraint, str)
        and endpoint_constraint.strip()
        and endpoint_constraint != expected_endpoint
    ):
        return "ExecutionToken endpoint mismatch"

    if isinstance(target_zone, str) and target_zone.strip():
        if configured_zones and target_zone not in configured_zones:
            return "ExecutionToken target zone mismatch"

    return None


def _configured_target_zones() -> set[str]:
    values: set[str] = set()
    raw_zone = os.getenv("HAL_TARGET_ZONE", "")
    if raw_zone.strip():
        values.add(raw_zone.strip())
    raw_zones = os.getenv("HAL_ALLOWED_TARGET_ZONES", "")
    if raw_zones.strip():
        values.update(
            part.strip()
            for part in raw_zones.split(",")
            if part.strip()
        )
    return values


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
    uvicorn.run(app, host="0.0.0.0", port=8003)
