#!/usr/bin/env python3
"""
Energy Service - Proactive Standalone Ray Serve Application

This service provides energy calculations and optimization for the SeedCore system.
It runs a proactive background loop to:
1. Fetch the latest pre-computed state from the StateService.
2. Calculate the system's current energy breakdown.
3. Store these calculations in a local EnergyLedger.

It serves energy metrics from this ledger (fast, cached) and also provides
endpoints for on-demand calculations (slower, passive).
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
import numpy as np
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]

from ..models.state import UnifiedState
from ..serve.state_client import StateServiceClient
from ..ops.energy.calculator import (
    compute_energy_unified,
    SystemParameters,
    EnergyResult,
)
from ..ops.energy.weights import EnergyWeights
from ..ops.energy.ledger import EnergyLedger
from ..ops.energy.optimizer import (
    calculate_agent_suitability_score,
    rank_agents_by_suitability,
    get_ideal_role_for_task,
    estimate_task_complexity
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger
setup_logging(app_name="seedcore.energy_service.driver")
logger = ensure_serve_logger("seedcore.energy", level="DEBUG")

# --- Request/Response Models ---
# (Pydantic models like EnergyRequest, EnergyResponse, etc. are unchanged)
# ... (all Pydantic models from your original file go here) ...
# --- (Keep all Pydantic models as-is) ---
class AgentSnapshotPayload(BaseModel):
    h: List[float]
    p: Dict[str, float]
    c: float
    mem_util: float
    lifecycle: str

class OrganStatePayload(BaseModel):
    h: List[float]
    P: List[List[float]]
    v_pso: Optional[List[float]] = None

class SystemStatePayload(BaseModel):
    h_hgnn: Optional[List[float]] = None
    E_patterns: Optional[List[float]] = None
    w_mode: Optional[List[float]] = None

class MemoryVectorPayload(BaseModel):
    ma: Dict[str, Any] = {}
    mw: Dict[str, Any] = {}
    mlt: Dict[str, Any] = {}
    mfb: Dict[str, Any] = {}

class UnifiedStatePayload(BaseModel):
    agents: Dict[str, AgentSnapshotPayload]
    organs: Dict[str, OrganStatePayload]
    system: SystemStatePayload
    memory: MemoryVectorPayload

class EnergyWeightsPayload(BaseModel):
    alpha_entropy: Optional[float] = None
    lambda_reg: Optional[float] = None
    beta_mem: Optional[float] = None
    W_pair: Optional[List[List[float]]] = None
    W_hyper: Optional[List[float]] = None

class EnergyRequest(BaseModel):
    unified_state: UnifiedStatePayload
    weights: Optional[EnergyWeightsPayload] = None
    include_gradients: bool = False
    include_breakdown: bool = True

class EnergyResponse(BaseModel):
    success: bool
    energy: Optional[Dict[str, float]] = None
    gradients: Optional[Dict[str, Any]] = None
    breakdown: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float

class FlywheelResultRequest(BaseModel):
    delta_e: float
    breakdown: Optional[Dict[str, float]] = None
    cost: Optional[float] = 0.0
    scope: Optional[str] = "cluster"
    scope_id: Optional[str] = "-"
    p_fast: Optional[float] = 0.9
    drift: Optional[float] = 0.0
    beta_mem: Optional[float] = None

class FlywheelResultResponse(BaseModel):
    success: bool
    updated_weights: Dict[str, float]
    ledger_ok: bool
    balance_after: Optional[float] = None
    timestamp: float

class OptimizationRequest(BaseModel):
    unified_state: Dict[str, Any]
    task: Dict[str, Any]
    weights: Optional[Dict[str, float]] = None
    max_agents: Optional[int] = None

class OptimizationResponse(BaseModel):
    success: bool
    selected_agents: Optional[List[str]] = None
    suitability_scores: Optional[Dict[str, float]] = None
    recommended_roles: Optional[Dict[str, str]] = None
    task_complexity: Optional[float] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float

class HealthResponse(BaseModel):
    status: str
    service: str
    sampler_running: bool
    state_service_healthy: bool
    error: Optional[str] = None


# --- FastAPI App ---
app = FastAPI(title="SeedCore Proactive Energy Service", version="2.0.0")

# --- Service State ---
class ServiceState:
    """Holds all state for the service, managed by FastAPI's lifespan."""
    
    # Client for the StateService
    state_client: Optional[StateServiceClient] = None
    
    # Proactive Loop
    sampler_task: Optional[asyncio.Task] = None
    sampler_is_running: bool = False

    # Core Logic State
    default_weights: EnergyWeights = EnergyWeights(
        W_pair=np.array([[1.0]]),
        W_hyper=np.array([1.0]),
        alpha_entropy=0.1,
        lambda_reg=0.01,
        beta_mem=0.05
    )
    ledger: EnergyLedger = EnergyLedger()
    metrics_tick: int = 0

state = ServiceState()

# --- Proactive Background Loop ---

async def _background_sampler():
    """Periodically compute energy from live state and log to ledger."""
    state.sampler_is_running = True
    while True:
        try:
            if not state.state_client:
                logger.warning("Sampler waiting for StateService client...")
                await asyncio.sleep(5.0)
                continue

            # 1. Fetch pre-computed metrics from StateService
            data = await state.state_client.get_system_metrics()
            if not data.get("success"):
                logger.warning("StateService reported failure, skipping sampler tick.")
                await asyncio.sleep(5.0)
                continue
                
            metrics = data.get("metrics", {})
            memory_data = metrics.get("memory", {})
            system_data = metrics.get("system", {})
            
            # 2. Parse metrics into a UnifiedState object
            # We use from_payload, which is robust to missing keys
            unified_state = UnifiedState.from_payload({
                "memory": memory_data,
                "system": system_data,
                # 'agents' and 'organs' are not needed if 'ma' and 'h_hgnn'
                # are correctly populated in the metrics.
            })
            
            # 3. Compute energy
            us_proj = unified_state.projected()
            weights = _create_weights_for_state(
                us_proj.H_matrix(), 
                us_proj.hyper_selection()
            )
            
            result: EnergyResult = compute_energy_unified(
                us_proj,
                SystemParameters(weights=weights, memory_stats={}, include_gradients=False),
            )
            
            # 4. Log to the internal ledger
            bd = result.breakdown
            if isinstance(bd, dict) and bd:
                state.ledger.log_step(breakdown={
                    "pair": float(bd.get("pair", 0.0)),
                    "hyper": float(bd.get("hyper", 0.0)),
                    "entropy": float(bd.get("entropy", 0.0)),
                    "mem": float(bd.get("mem", 0.0)),
                    "total": float(bd.get("total", 0.0)),
                }, extra={"source": "bg-sampler"})
            
            await asyncio.sleep(5.0)
            
        except asyncio.CancelledError:
            logger.info("Background sampler task cancelled.")
            state.sampler_is_running = False
            break
        except Exception as e:
            logger.error(f"Error in background sampler: {e}", exc_info=True)
            await asyncio.sleep(5.0)

# --- Lifespan Events (Startup and Shutdown) ---

@app.on_event("startup")
async def startup_event():
    """
    On service startup, initialize and start all proactive aggregators.
    """
    logger.info("🚀 EnergyService starting up...")
    try:
        # 1. Initialize StateService client
        state.state_client = StateServiceClient(timeout=8.0)
        logger.info("✅ EnergyService StateService client initialized.")
        
        # 2. Start the background sampler loop
        state.sampler_task = asyncio.create_task(_background_sampler())
        logger.info("✅ EnergyService background sampler started.")
        
    except Exception as e:
        logger.error(f"❌ FATAL: Failed to initialize EnergyService: {e}", exc_info=True)
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """
    On service shutdown, gracefully stop all aggregator loops.
    """
    logger.info("🛑 EnergyService shutting down...")
    tasks = []
    if state.sampler_task:
        state.sampler_task.cancel()
        tasks.append(state.sampler_task)
    
    if state.state_client:
        tasks.append(state.state_client.close())
        
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("✅ EnergyService shutdown complete.")

# --- API Endpoints ---

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    if not state.state_client:
        raise HTTPException(status_code=503, detail="Service not initialized")

    # Probe StateService
    state_service_healthy = False
    try:
        state_service_healthy = await state.state_client.is_healthy()
    except Exception as e:
        logger.warning(f"Health probe to StateService failed: {e}")
        
    status = "healthy" if state.sampler_is_running and state_service_healthy else "unhealthy"
    
    return HealthResponse(
        status=status,
        service="energy-service",
        sampler_running=state.sampler_is_running,
        state_service_healthy=state_service_healthy
    )

@app.get("/metrics")
async def metrics():
    """
    Returns the current energy term breakdown from the
    proactive sampler's ledger. (Fast, O(1) read).
    """
    try:
        pair = float(getattr(state.ledger, "pair", 0.0))
        hyper = float(getattr(state.ledger, "hyper", 0.0))
        ent = float(getattr(state.ledger, "entropy", 0.0))
        mem = float(getattr(state.ledger, "mem", 0.0))
        total = float(getattr(state.ledger, "total", pair + hyper + ent + mem))

        # Fallback for cold start
        if total == 0.0:
            state.metrics_tick += 1
            t = state.metrics_tick
            pair, hyper, ent, mem = -0.50 - 0.01 * t, 0.10 + 0.02 * t, 0.50, 0.30
            total = pair + hyper + ent + mem
            
        return {
            "pair": pair, "hyper": hyper, "entropy": ent,
            "mem": mem, "total": total, "source": "ledger-cache"
        }
    except Exception as e:
        logger.error(f"Failed to produce metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Metrics error: {e}")

@app.post("/compute-energy", response_model=EnergyResponse)
async def compute_energy_endpoint(request: EnergyRequest):
    """
    (Passive Endpoint)
    Compute energy metrics from a user-provided unified state.
    """
    start_time = time.time()
    try:
        # Parse unified state
        unified_state = _parse_unified_state(request.unified_state.dict())
        
        # ... (Rest of your original calculation logic is unchanged) ...
        us_proj = unified_state.projected()
        H = us_proj.H_matrix()
        E_sel = us_proj.hyper_selection()
        
        if request.weights:
            weights = _parse_weights(request.weights.dict())
        else:
            weights = _create_weights_for_state(H, E_sel if E_sel.size > 0 else None)
        
        result: EnergyResult = compute_energy_unified(
            us_proj,
            SystemParameters(weights=weights, memory_stats={}, include_gradients=bool(request.include_gradients)),
        )
        
        gradients_serializable = None
        if request.include_gradients and result.gradients:
            gradients_serializable = {k: v.tolist() if isinstance(v, np.ndarray) else v for k, v in result.gradients.items()}

        computation_time = (time.time() - start_time) * 1000
        return EnergyResponse(
            success=True,
            energy=result.breakdown,
            gradients=gradients_serializable,
            breakdown=result.breakdown,
            timestamp=time.time(),
            computation_time_ms=computation_time
        )
        
    except Exception as e:
        logger.error(f"Failed to compute energy: {e}", exc_info=True)
        return EnergyResponse(
            success=False,
            error=str(e),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000
        )

@app.get("/compute-energy-from-state", response_model=EnergyResponse)
async def compute_energy_from_state():
    """
    (On-Demand Endpoint)
    Fetches the *latest* metrics from StateService and computes
    energy *right now*. Slower than /metrics.
    """
    start_time = time.time()
    if not state.state_client:
        raise HTTPException(status_code=503, detail="StateService client not ready.")
        
    try:
        # 1. Fetch latest metrics from StateService
        data = await state.state_client.get_system_metrics()
        metrics = data.get("metrics", {})
        
        # 2. Parse into UnifiedState
        unified_state = UnifiedState.from_payload({
            "memory": metrics.get("memory", {}),
            "system": metrics.get("system", {}),
        })

        # 3. Compute energy
        us_proj = unified_state.projected()
        weights = _create_weights_for_state(
            us_proj.H_matrix(), 
            us_proj.hyper_selection()
        )
        result: EnergyResult = compute_energy_unified(
            us_proj,
            SystemParameters(weights=weights, memory_stats={}, include_gradients=False),
        )
        
        computation_time = (time.time() - start_time) * 1000
        return EnergyResponse(
            success=True,
            energy=result.breakdown,
            gradients=None,
            breakdown=result.breakdown,
            timestamp=time.time(),
            computation_time_ms=computation_time
        )
    except Exception as e:
        logger.error(f"Failed to compute energy from state: {e}", exc_info=True)
        return EnergyResponse(
            success=False,
            error=f"On-demand compute failed: {e}",
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000
        )

@app.post("/flywheel/result", response_model=FlywheelResultResponse)
async def flywheel_result_endpoint(request: FlywheelResultRequest):
    """
    (Passive Endpoint)
    Ingests energy results (ΔE), updates the ledger, and adapts weights.
    """
    try:
        ts = time.time()
        bd = request.breakdown or {
            "pair": float(state.ledger.pair),
            "hyper": float(state.ledger.hyper),
            "entropy": float(state.ledger.entropy),
            "total": float(state.ledger.total),
        }
        
        # Log to the shared ledger
        rec = state.ledger.log_step(
            breakdown=bd,
            extra={"ts": ts, "dE": float(request.delta_e), "cost": float(request.cost or 0.0)}
        )
        
        # Adapt the shared default weights
        if request.beta_mem is not None:
            state.default_weights.beta_mem = float(request.beta_mem)
        else:
            sign = 1.0 if request.delta_e > 0 else -1.0
            state.default_weights.beta_mem = float(
                max(0.0, min(1.0, state.default_weights.beta_mem * (1.0 + 0.02 * sign)))
            )
            
        return FlywheelResultResponse(
            success=True,
            updated_weights=state.default_weights.as_dict(),
            ledger_ok=bool(rec.get("ok", True)),
            balance_after=rec.get("balance_after"),
            timestamp=ts,
        )
    except Exception as e:
        logger.error(f"Flywheel result error: {e}", exc_info=True)
        return FlywheelResultResponse(
            success=False,
            updated_weights=state.default_weights.as_dict(),
            ledger_ok=False,
            balance_after=None,
            timestamp=time.time(),
        )

# ... (Keep /optimize-agents, /gradient, etc. as-is) ...
# ... (Their logic is purely computational and doesn't need to change) ...
# ... (Just ensure they use `state.default_weights` if needed) ...

@app.post("/optimize-agents", response_model=OptimizationResponse)
async def optimize_agents_endpoint(request: OptimizationRequest):
    """(Passive Endpoint) Optimize agent selection for a given task."""
    start_time = time.time()
    try:
        unified_state = _parse_unified_state(request.unified_state)
        task_complexity = estimate_task_complexity(request.task)
        agents = unified_state.agents
        
        if not agents:
            raise HTTPException(status_code=400, detail="No agents available for optimization")

        suitability_scores = {}
        for agent_id, agent_snapshot in agents.items():
            agent_data = {
                "h": agent_snapshot.h, "p": agent_snapshot.p, "c": agent_snapshot.c,
                "mem_util": agent_snapshot.mem_util, "lifecycle": agent_snapshot.lifecycle
            }
            score = calculate_agent_suitability_score(agent_data, request.task)
            suitability_scores[agent_id] = score
        
        ranked_agents = rank_agents_by_suitability(suitability_scores)
        max_agents = request.max_agents or len(ranked_agents)
        selected_agents = ranked_agents[:max_agents]
        
        recommended_roles = {}
        for agent_id in selected_agents:
            agent_snapshot = agents[agent_id]
            agent_data = {
                "h": agent_snapshot.h, "p": agent_snapshot.p, "c": agent_snapshot.c,
                "mem_util": agent_snapshot.mem_util, "lifecycle": agent_snapshot.lifecycle
            }
            role = get_ideal_role_for_task(agent_data, request.task)
            recommended_roles[agent_id] = role
        
        computation_time = (time.time() - start_time) * 1000
        return OptimizationResponse(
            success=True,
            selected_agents=selected_agents,
            suitability_scores=suitability_scores,
            recommended_roles=recommended_roles,
            task_complexity=task_complexity,
            timestamp=time.time(),
            computation_time_ms=computation_time
        )
    except Exception as e:
        logger.error(f"Failed to optimize agents: {e}", exc_info=True)
        return OptimizationResponse(
            success=False,
            error=str(e),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000
        )


# --- Helper Methods ---
# (These are unchanged, but we make them module-level functions)

def _parse_unified_state(state_dict: Dict[str, Any]) -> UnifiedState:
    """Parse unified state dictionary into UnifiedState object."""
    try:
        if isinstance(state_dict, UnifiedState):
            return state_dict
        if hasattr(state_dict, "dict"):
            state_dict = state_dict.dict()
        return UnifiedState.from_payload(state_dict)
    except Exception as e:
        logger.error(f"Failed to parse unified state: {e}")
        raise ValueError(f"Invalid unified state format: {e}")

def _parse_weights(weights_dict: Optional[Dict[str, Any]]) -> EnergyWeights:
    """Parse weights dictionary into EnergyWeights object."""
    if not weights_dict:
        return state.default_weights
    
    weights = EnergyWeights(
        W_pair=state.default_weights.W_pair.copy(),
        W_hyper=state.default_weights.W_hyper.copy(),
        alpha_entropy=state.default_weights.alpha_entropy,
        lambda_reg=state.default_weights.lambda_reg,
        beta_mem=state.default_weights.beta_mem
    )
    
    # Update with provided values
    if "alpha_entropy" in weights_dict: weights.alpha_entropy = float(weights_dict["alpha_entropy"])
    if "lambda_reg" in weights_dict: weights.lambda_reg = float(weights_dict["lambda_reg"])
    if "beta_mem" in weights_dict: weights.beta_mem = float(weights_dict["beta_mem"])
    if "W_pair" in weights_dict: weights.W_pair = np.array(weights_dict["W_pair"])
    if "W_hyper" in weights_dict: weights.W_hyper = np.array(weights_dict["W_hyper"])
    
    return weights

def _create_weights_for_state(H: np.ndarray, E_sel: Optional[np.ndarray] = None) -> EnergyWeights:
    """Create weights with appropriate dimensions for the given state."""
    n_agents = H.shape[0] if H.size > 0 else 1
    n_hyper = E_sel.shape[0] if E_sel is not None and E_sel.size > 0 else 1
    
    return EnergyWeights(
        W_pair=np.eye(n_agents) * 0.1,
        W_hyper=np.ones(n_hyper) * 0.1,
        alpha_entropy=state.default_weights.alpha_entropy,
        lambda_reg=state.default_weights.lambda_reg,
        beta_mem=state.default_weights.beta_mem
    )

# --- Ray Serve Deployment ---

@serve.deployment(
    name="EnergyService",
    num_replicas=1,
    max_ongoing_requests=16,
    ray_actor_options={
        "num_cpus": 0.2,
        "num_gpus": 0,
        "memory": 1073741824,  # 1GB
    },
)
@serve.ingress(app)
class EnergyService:
    """
    Ray Serve wrapper for the proactive FastAPI EnergyService.
    All logic is handled by the FastAPI app, its lifespan events,
    and its endpoints. This class is just the entrypoint for Ray Serve.
    """
    def __init__(self):
        # The FastAPI app `app` handles all logic.
        pass

# --- Main Entrypoint ---
energy_app = EnergyService.bind()

def build_energy_app(args: dict = None):
    """
    Builder function for the energy service application.
    """
    return energy_app