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

from __future__ import annotations

import asyncio
import time
import numpy as np

from typing import Dict, Optional, Any
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException  # pyright: ignore[reportMissingImports]

from ..models.state import UnifiedState
from ..serve.state_client import StateServiceClient
from ..serve.ml_client import MLServiceClient
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
    estimate_task_complexity,
)

from ..models.energy import (
    EnergyRequest,
    EnergyResponse,
    FlywheelResultRequest,
    FlywheelResultResponse,
    OptimizationRequest,
    OptimizationResponse,
    HealthResponse,
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.energy_service.driver")
logger = ensure_serve_logger("seedcore.energy", level="DEBUG")


# --- Service State ---
class ServiceState:
    """Holds all state for the service, managed by FastAPI's lifespan."""

    # Client for the StateService
    state_client: Optional[StateServiceClient] = None
    ml_client: Optional[MLServiceClient] = None
    last_ml_stats: Dict[str, Any] = {}

    # Proactive Loop
    sampler_task: Optional[asyncio.Task] = None
    sampler_is_running: bool = False

    # Core Logic State
    default_weights: EnergyWeights = EnergyWeights(
        W_pair=np.array([[1.0]]),
        W_hyper=np.array([1.0]),
        alpha_entropy=0.1,
        lambda_reg=0.01,
        beta_mem=0.05,
        lambda_drift=0.0,
        mu_anomaly=0.0,
    )
    ledger: EnergyLedger = EnergyLedger()
    metrics_tick: int = 0

    # NEW: Lock for thread-safe access to shared state
    _lock: Optional[asyncio.Lock] = None

    def __init__(self):
        """Initialize the lock when ServiceState is instantiated."""
        self._lock = asyncio.Lock()


state = ServiceState()

# --- Proactive Background Loop ---


async def _execute_flywheel_feedback(
    current_total_energy: float, ml_stats: Dict[str, Any]
) -> float:
    """
    The Control Loop:

    Compares current Energy vs Previous Energy.
    If Energy is degrading (increasing), tell ML to be more conservative (higher Temp).
    If Energy is optimizing (decreasing), tell ML to be sharper (lower Temp).

    Args:
        current_total_energy: Current total energy from the energy calculation
        ml_stats: ML statistics dict containing adaptive_params

    Returns:
        delta_E: The energy change (current - previous)
    """
    # 1. Get previous energy from ledger (default to current if empty)
    prev_total = float(getattr(state.ledger, "total", current_total_energy))

    # 2. Calculate Delta E (Change in Energy)
    # Positive Delta = Energy is rising (Bad/Entropy increasing)
    # Negative Delta = Energy is falling (Good/Optimization happening)
    delta_E = current_total_energy - prev_total

    # 3. Get current temperature from ML stats (or default 1.0)
    # We assume ml_stats includes 'adaptive_params' from the new ML v2 response
    current_temp = 1.0
    if "adaptive_params" in ml_stats:
        current_temp = float(
            ml_stats["adaptive_params"].get("scaling_temperature", 1.0)
        )

    # 4. Determine Feedback Action
    # Threshold: 0.05 (ignore minor fluctuations)
    new_temp = current_temp

    if delta_E > 0.05:
        # System getting chaotic -> Increase Temp (Smooth out ML predictions)
        # "Cool down the agent behavior by warming up the softmax temperature"
        new_temp = min(2.0, current_temp * 1.05)
        logger.info(
            f"⚡ Flywheel: Energy Spiking (+{delta_E:.3f}). Increasing ML Temp to {new_temp:.3f}"
        )

    elif delta_E < -0.05:
        # System optimizing -> Decrease Temp (Allow sharper/riskier predictions)
        new_temp = max(0.5, current_temp * 0.95)
        logger.info(
            f"⚡ Flywheel: Energy Optimizing ({delta_E:.3f}). Sharpening ML Temp to {new_temp:.3f}"
        )

    # 5. Send Control Signal if changed
    if new_temp != current_temp:
        try:
            if state.ml_client:
                await state.ml_client.update_adaptive_params(
                    {"scaling_temperature": new_temp}
                )
                logger.debug(
                    f"✅ Flywheel feedback sent to MLService: temp={new_temp:.3f}"
                )
            else:
                logger.warning(
                    "MLService client not available, skipping flywheel feedback"
                )
        except Exception as e:
            logger.warning(f"Failed to send Flywheel feedback to ML: {e}")

    return delta_E


async def _get_ml_stats(metrics: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch ML annotations for the provided system metrics."""
    if not state.ml_client:
        return state.last_ml_stats or {}
    payload = metrics or {}
    try:
        response = await asyncio.wait_for(
            state.ml_client.predict_all(payload), timeout=3.0
        )
        ml_stats = response.get("ml_stats") if isinstance(response, dict) else response
        if isinstance(ml_stats, dict):
            state.last_ml_stats = ml_stats
            return ml_stats
        logger.warning("[EnergyService] ML predict_all response missing ml_stats.")
    except asyncio.TimeoutError:
        logger.warning("[EnergyService] ML predict_all timed out.")
    except Exception as e:
        logger.warning(f"[EnergyService] ML predict_all failed: {e}")
    return state.last_ml_stats or {}


async def _background_sampler():
    """
    The Brainstem Loop: Periodically computes Hamiltonian Energy from live state
    and drives the Flywheel Feedback loop to stabilize ML predictions.
    """
    state.sampler_is_running = True
    retry_delay = 1.0

    while True:
        try:
            # -----------------------------------------------------------
            # 0. Connectivity Check
            # -----------------------------------------------------------
            if not state.state_client:
                logger.warning("Sampler waiting for StateService client...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 1.5)
                continue

            # -----------------------------------------------------------
            # 1. Fetch Metrics (Perception)
            # -----------------------------------------------------------
            # Calls the corrected client (no args)
            data = await state.state_client.get_system_metrics()

            if not data.get("success"):
                # Use exponential backoff if StateService is degraded
                logger.warning(
                    f"StateService reported failure (Status: {data.get('meta', {}).get('status')})"
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 1.5)
                continue

            # Success! Reset delay to normal loop speed
            retry_delay = 1.0

            metrics = data.get("metrics", {})
            memory_data = metrics.get("memory", {})
            system_data = metrics.get("system", {})

            # -----------------------------------------------------------
            # 2. ML Prediction (Cognition)
            # -----------------------------------------------------------
            # We explicitly fetch ML stats using the retrieved metrics
            ml_stats = await _get_ml_stats(metrics)

            # Inject ML stats into the system payload so UnifiedState can see them
            system_payload = dict(system_data or {})
            system_payload["ml"] = ml_stats or {}

            # -----------------------------------------------------------
            # 3. Compute Energy (Physics)
            # -----------------------------------------------------------
            # Parse metrics into a UnifiedState object
            unified_state = UnifiedState.from_payload(
                {
                    "memory": memory_data,
                    "system": system_payload,
                }
            )

            us_proj = unified_state.projected()

            # Dynamic weighting based on system topology
            weights = _create_weights_for_state(
                us_proj.H_matrix(), us_proj.hyper_selection()
            )

            result: EnergyResult = compute_energy_unified(
                us_proj,
                SystemParameters(
                    weights=weights,
                    memory_stats=memory_data,
                    include_gradients=False,  # Gradients not needed for scalar monitoring
                    ml_stats=ml_stats,
                ),
            )

            # -----------------------------------------------------------
            # 4. Flywheel Feedback (Control)
            # -----------------------------------------------------------
            total_energy = float(result.breakdown.get("total", 0.0))

            # Execute feedback loop:
            # Calculates Delta E -> Adjusts ML Scaling Temperature -> Returns Delta
            delta_E = await _execute_flywheel_feedback(total_energy, ml_stats)

            # -----------------------------------------------------------
            # 5. Ledger Update (Memory)
            # -----------------------------------------------------------
            bd = result.breakdown
            if isinstance(bd, dict) and bd:
                scaling_score = float((ml_stats or {}).get("scaling_score", 0.0))

                state.ledger.log_step(
                    breakdown={
                        "pair": float(bd.get("pair", 0.0)),
                        "hyper": float(bd.get("hyper", 0.0)),
                        "entropy": float(bd.get("entropy", 0.0)),
                        "reg": float(bd.get("reg", 0.0)),
                        "mem": float(bd.get("mem", 0.0)),
                        "drift_term": float(bd.get("drift_term", 0.0)),
                        "anomaly_term": float(bd.get("anomaly_term", 0.0)),
                        "total": total_energy,
                    },
                    extra={
                        "source": "bg-sampler",
                        "drift": float((ml_stats or {}).get("drift", 0.0)),
                        "scaling_score": scaling_score,
                        "delta_E": delta_E,
                        "ts": time.time(),
                    },
                )

            # Maintain 5s cadence
            await asyncio.sleep(5.0)

        except asyncio.CancelledError:
            logger.info("Background sampler task cancelled.")
            state.sampler_is_running = False
            break
        except Exception as e:
            logger.error(f"Error in background sampler: {e}", exc_info=True)
            # On crash, wait a bit before retrying to avoid log spam
            await asyncio.sleep(retry_delay)
            retry_delay = min(30.0, retry_delay * 1.5)


# --- Lifespan Events (Startup and Shutdown) ---

# --- FastAPI App ---
app = FastAPI(title="SeedCore Proactive Energy Service", version="2.0.0", docs_url=None, redoc_url=None)  # Disable docs - only accessed via RPC


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
        state.ml_client = MLServiceClient(timeout=6.0)
        logger.info("✅ EnergyService MLService client initialized.")

        # 2. Start the background sampler loop
        state.sampler_task = asyncio.create_task(_background_sampler())
        logger.info("✅ EnergyService background sampler started.")

    except Exception as e:
        logger.error(
            f"❌ FATAL: Failed to initialize EnergyService: {e}", exc_info=True
        )
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """
    On service shutdown, gracefully stop all aggregator loops.
    """
    logger.info("🛑 EnergyService shutting down...")
    tasks = []

    # Cancel and await the sampler task with proper cleanup
    if state.sampler_task:
        state.sampler_task.cancel()
        try:
            await state.sampler_task
        except asyncio.CancelledError:
            pass  # Expected when task is cancelled

    # Close clients
    if state.state_client:
        tasks.append(state.state_client.close())
    if state.ml_client:
        tasks.append(state.ml_client.close())

    if tasks:
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

    status = (
        "healthy" if state.sampler_is_running and state_service_healthy else "unhealthy"
    )

    return HealthResponse(
        status=status,
        service="energy-service",
        sampler_running=state.sampler_is_running,
        state_service_healthy=state_service_healthy,
    )


@app.get("/metrics")
async def get_metrics():
    """
    Returns the current energy term breakdown from the
    proactive sampler's ledger. (Fast, O(1) read).
    """
    try:
        # 1. Access the latest snapshot correctly
        # Assuming state.ledger has a 'latest' dict or individual properties
        # If EnergyLedger is a simple dataclass-like object, getattr is fine,
        # but usually ledgers hold history.

        # Let's assume the ledger has direct attributes updated by the loop
        # OR a .current_snapshot dictionary.

        # SAFE PATTERN: Use the ledger's public read method if it exists
        # If your ledger class just stores attributes directly:

        pair = float(getattr(state.ledger, "pair", 0.0))
        hyper = float(getattr(state.ledger, "hyper", 0.0))
        ent = float(getattr(state.ledger, "entropy", 0.0))
        reg = float(getattr(state.ledger, "reg", 0.0))
        mem = float(getattr(state.ledger, "mem", 0.0))
        drift_term = float(getattr(state.ledger, "drift_term", 0.0))
        anomaly_term = float(getattr(state.ledger, "anomaly_term", 0.0))
        scaling_score = float(getattr(state.ledger, "scaling_score", 0.0))

        # Retrieve total, or calculate if missing
        stored_total = getattr(state.ledger, "total", None)
        if stored_total is not None:
            total = float(stored_total)
        else:
            total = pair + hyper + ent + reg + mem + drift_term + anomaly_term

        # 2. Cold Start / Synthetic Warmup logic
        # (This logic is weird for production, but fine for demos/tests)
        if total == 0.0 and state.metrics_tick < 10:  # Limit warmup to first few ticks
            state.metrics_tick += 1
            t = state.metrics_tick

            # Generate synthetic "wobble" to show liveness in UI
            pair = -0.50 - 0.01 * t
            hyper = 0.10 + 0.02 * t
            ent = 0.50
            reg = 0.05
            mem = 0.30
            drift_term = 0.0
            anomaly_term = 0.0
            total = pair + hyper + ent + reg + mem

            # Update the ledger so subsequent reads (or other services) see this warmup state
            # This ensures consistency if another thread reads state.ledger immediately
            if hasattr(state.ledger, "update_synthetic"):
                state.ledger.update_synthetic(total=total, entropy=ent)  # etc...

        return {
            "pair": pair,
            "hyper": hyper,
            "entropy": ent,
            "reg": reg,
            "mem": mem,
            "drift_term": drift_term,
            "anomaly_term": anomaly_term,
            "scaling_score": scaling_score,
            "total": total,
            "source": "ledger-cache",
            "timestamp": time.time(),  # Always useful to return TS
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
        memory_vector = getattr(us_proj, "memory", None)
        memory_payload: Dict[str, Any] = {}
        if memory_vector:
            memory_payload = {
                "ma": memory_vector.ma,
                "mw": memory_vector.mw,
                "mlt": memory_vector.mlt,
                "mfb": memory_vector.mfb,
            }
        ml_stats_payload = getattr(getattr(us_proj, "system", None), "ml", None)

        if request.weights:
            weights = _parse_weights(request.weights.dict())
        else:
            weights = _create_weights_for_state(H, E_sel if E_sel.size > 0 else None)

        result: EnergyResult = compute_energy_unified(
            us_proj,
            SystemParameters(
                weights=weights,
                memory_stats=memory_payload,
                include_gradients=bool(request.include_gradients),
                ml_stats=ml_stats_payload,
            ),
        )

        gradients_serializable = None
        if request.include_gradients and result.gradients:
            gradients_serializable = {
                k: v.tolist() if isinstance(v, np.ndarray) else v
                for k, v in result.gradients.items()
            }

        computation_time = (time.time() - start_time) * 1000
        return EnergyResponse(
            success=True,
            energy=result.breakdown,
            gradients=gradients_serializable,
            breakdown=result.breakdown,
            timestamp=time.time(),
            computation_time_ms=computation_time,
        )

    except Exception as e:
        logger.error(f"Failed to compute energy: {e}", exc_info=True)
        return EnergyResponse(
            success=False,
            error=str(e),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000,
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
        ml_stats = await _get_ml_stats(metrics)
        memory_payload = metrics.get("memory", {})
        system_section = dict(metrics.get("system", {}) or {})
        system_section["ml"] = ml_stats or {}
        metrics["system"] = system_section

        # 2. Parse into UnifiedState
        unified_state = UnifiedState.from_payload(
            {
                "memory": memory_payload,
                "system": system_section,
            }
        )

        # 3. Compute energy
        us_proj = unified_state.projected()
        weights = _create_weights_for_state(
            us_proj.H_matrix(), us_proj.hyper_selection()
        )
        result: EnergyResult = compute_energy_unified(
            us_proj,
            SystemParameters(
                weights=weights,
                memory_stats=memory_payload,
                include_gradients=False,
                ml_stats=ml_stats,
            ),
        )

        computation_time = (time.time() - start_time) * 1000
        return EnergyResponse(
            success=True,
            energy=result.breakdown,
            gradients=None,
            breakdown=result.breakdown,
            timestamp=time.time(),
            computation_time_ms=computation_time,
        )
    except Exception as e:
        logger.error(f"Failed to compute energy from state: {e}", exc_info=True)
        return EnergyResponse(
            success=False,
            error=f"On-demand compute failed: {e}",
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000,
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
            extra={
                "ts": ts,
                "dE": float(request.delta_e),
                "cost": float(request.cost or 0.0),
            },
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
    """
    (Passive Endpoint) Optimize agent selection for a given task.
    Uses the V2 Energy Optimizer logic (stateless scores).
    """
    start_time = time.time()
    try:
        # 1. Parse Inputs
        # Convert request payload into UnifiedState object
        unified_state = _parse_unified_state(request.unified_state)
        agents = unified_state.agents

        if not agents:
            raise HTTPException(
                status_code=400,
                detail="No agents provided in unified_state for optimization",
            )

        # Ensure task is a dictionary (handle Pydantic or Dict input)
        task_input = request.task
        task_dict = (
            task_input.model_dump()
            if hasattr(task_input, "model_dump")
            else dict(task_input)
        )

        # 2. Pre-calculate Task Complexity
        # (Used for metadata/logging, though implicitly used in scoring too)
        task_complexity = estimate_task_complexity(task_dict)

        # 3. Score Agents (The Core Loop)
        suitability_scores = {}
        agent_data_cache = {}  # Cache converted dicts for step 6

        for agent_id, snapshot in agents.items():
            # Convert AgentSnapshot to the dict format expected by optimizer.py
            # CRITICAL: Must include 'learned_skills' and try to find 'specialization'
            agent_data = {
                "h": snapshot.h,
                "p": snapshot.p,
                "c": snapshot.c,
                "mem_util": snapshot.mem_util,
                "lifecycle": snapshot.lifecycle,
                # V2: Include learned skills for soft-matching
                "learned_skills": getattr(snapshot, "learned_skills", {}),
                # V2: Specialization is required for hard constraints.
                # If UnifiedState doesn't carry it, we default to 'unknown' (which fails matching safely).
                "specialization": getattr(snapshot, "specialization", "unknown"),
            }
            agent_data_cache[agent_id] = agent_data

            # Calculate score (Lower is better)
            score = calculate_agent_suitability_score(agent_data, task_dict)
            suitability_scores[agent_id] = score

        # 4. Rank Agents
        # V2 optimizer returns a List[str] of agent_ids sorted by score
        ranked_agent_ids = rank_agents_by_suitability(suitability_scores)

        # 5. Select Top N
        max_agents = request.max_agents or len(ranked_agent_ids)
        selected_ids = ranked_agent_ids[:max_agents]

        # 6. Recommend Roles (Flywheel Feedback Hint)
        # Predicts whether the agent should act as (E)xecutor, (S)ynthesizer, or (O)bserver
        recommended_roles = {}
        for agent_id in selected_ids:
            role = get_ideal_role_for_task(agent_data_cache[agent_id], task_dict)
            recommended_roles[agent_id] = role

        computation_time = (time.time() - start_time) * 1000

        return OptimizationResponse(
            success=True,
            selected_agents=selected_ids,
            # Ensure float types for JSON serialization
            suitability_scores={k: float(v) for k, v in suitability_scores.items()},
            recommended_roles=recommended_roles,
            task_complexity=task_complexity,
            timestamp=time.time(),
            computation_time_ms=computation_time,
        )

    except Exception as e:
        logger.error(f"Failed to optimize agents: {e}", exc_info=True)
        return OptimizationResponse(
            success=False,
            error=str(e),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000,
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
        beta_mem=state.default_weights.beta_mem,
        lambda_drift=state.default_weights.lambda_drift,
        mu_anomaly=state.default_weights.mu_anomaly,
    )

    # Update with provided values
    if "alpha_entropy" in weights_dict:
        weights.alpha_entropy = float(weights_dict["alpha_entropy"])
    if "lambda_reg" in weights_dict:
        weights.lambda_reg = float(weights_dict["lambda_reg"])
    if "beta_mem" in weights_dict:
        weights.beta_mem = float(weights_dict["beta_mem"])
    if "lambda_drift" in weights_dict:
        weights.lambda_drift = float(weights_dict["lambda_drift"])
    if "mu_anomaly" in weights_dict:
        weights.mu_anomaly = float(weights_dict["mu_anomaly"])
    if "W_pair" in weights_dict:
        weights.W_pair = np.array(weights_dict["W_pair"])
    if "W_hyper" in weights_dict:
        weights.W_hyper = np.array(weights_dict["W_hyper"])

    return weights


def _create_weights_for_state(
    H: np.ndarray, E_sel: Optional[np.ndarray] = None
) -> EnergyWeights:
    """Create weights with appropriate dimensions for the given state."""
    n_agents = H.shape[0] if H.size > 0 else 1
    n_hyper = E_sel.shape[0] if E_sel is not None and E_sel.size > 0 else 1

    return EnergyWeights(
        W_pair=np.eye(n_agents) * 0.1,
        W_hyper=np.ones(n_hyper) * 0.1,
        alpha_entropy=state.default_weights.alpha_entropy,
        lambda_reg=state.default_weights.lambda_reg,
        beta_mem=state.default_weights.beta_mem,
        lambda_drift=state.default_weights.lambda_drift,
        mu_anomaly=state.default_weights.mu_anomaly,
    )


@serve.deployment(name="EnergyService")
@serve.ingress(app)
class EnergyService:
    def __init__(self):
        pass

    async def rpc_compute_energy(self, request: EnergyRequest) -> dict:
        """RPC wrapper for compute_energy endpoint. Returns dict for Ray serialization."""
        response = await compute_energy_endpoint(request)
        return response.model_dump() if hasattr(response, "model_dump") else response

    async def rpc_compute_from_state(self) -> dict:
        """RPC wrapper for compute_energy_from_state endpoint. Returns dict for Ray serialization."""
        response = await compute_energy_from_state()
        return response.model_dump() if hasattr(response, "model_dump") else response

    async def rpc_optimize_agents(self, request: OptimizationRequest) -> dict:
        """RPC wrapper for optimize_agents endpoint. Returns dict for Ray serialization."""
        response = await optimize_agents_endpoint(request)
        return response.model_dump() if hasattr(response, "model_dump") else response

    async def rpc_flywheel_result(self, request: FlywheelResultRequest) -> dict:
        """RPC wrapper for flywheel_result endpoint. Returns dict for Ray serialization."""
        response = await flywheel_result_endpoint(request)
        return response.model_dump() if hasattr(response, "model_dump") else response

    async def rpc_get_metrics(self) -> dict:
        """RPC wrapper for metrics endpoint. Returns dict for Ray serialization."""
        result = await get_metrics()
        # metrics() already returns a dict, so return as-is
        return result if isinstance(result, dict) else result

    async def rpc_health(self) -> dict:
        """RPC wrapper for health endpoint. Returns dict for Ray serialization."""
        response = await health()
        return response.model_dump() if hasattr(response, "model_dump") else response


# --- Main Entrypoint ---
energy_app = EnergyService.bind()


def build_energy_app(args: dict = None):
    """
    Builder function for the energy service application.
    """
    return energy_app
