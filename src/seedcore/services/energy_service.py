#!/usr/bin/env python3
"""
Energy Service - deterministic energy and routing stress runtime for SeedCore.

The service treats StateService as the primary source of truth and only uses
ML/cognitive feedback as an optional augmentation layer. That keeps routing,
promotion guards, and energy telemetry stable even when external AI providers
are slow, strange, or unavailable.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from typing import Any, Dict, Optional

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from ray import serve  # pyright: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger, setup_logging

from ..models.energy import (
    EnergyRequest,
    EnergyResponse,
    FlywheelResultRequest,
    FlywheelResultResponse,
    HealthResponse,
    OptimizationRequest,
    OptimizationResponse,
)
from ..models.state import UnifiedState
from ..ops.energy.calculator import EnergyResult, SystemParameters, compute_energy_unified
from ..ops.energy.ledger import EnergyLedger
from ..ops.energy.optimizer import (
    calculate_agent_suitability_score,
    estimate_task_complexity,
    get_ideal_role_for_task,
    rank_agents_by_suitability,
)
from ..ops.energy.weights import EnergyWeights
from ..serve.ml_client import MLServiceClient
from ..serve.state_client import StateServiceClient

setup_logging(app_name="seedcore.energy_service.driver")
logger = ensure_serve_logger("seedcore.energy_service", level="DEBUG")

app = FastAPI(
    title="SeedCore Energy Service",
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
)

PROMOTION_LTOT_CAP = float(os.getenv("SEEDCORE_PROMOTION_LTOT_CAP", "0.98"))
BETA_ROUTER = float(os.getenv("SEEDCORE_ENERGY_BETA_ROUTER", "1.0"))
BETA_META = float(os.getenv("SEEDCORE_ENERGY_BETA_META", "0.95"))
RHO_CLIP = float(os.getenv("SEEDCORE_ENERGY_RHO", "0.95"))
SAMPLER_INTERVAL_S = float(os.getenv("SEEDCORE_ENERGY_SAMPLER_INTERVAL_S", "5.0"))
DEFAULT_SIGNAL_SOURCE = "state-heuristic"
EVENT_LOG_LIMIT = int(os.getenv("SEEDCORE_ENERGY_EVENT_LOG_LIMIT", "1000"))


class ServiceState:
    def __init__(self) -> None:
        self.state_client: Optional[StateServiceClient] = None
        self.ml_client: Optional[MLServiceClient] = None
        self.sampler_task: Optional[asyncio.Task] = None
        self.sampler_is_running: bool = False
        self.ml_feedback_enabled: bool = (
            os.getenv("ENERGY_ENABLE_ML_FEEDBACK", "false").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        self.default_weights = EnergyWeights(
            W_pair=np.array([[1.0]], dtype=np.float32),
            W_hyper=np.array([1.0], dtype=np.float32),
            alpha_entropy=0.1,
            lambda_reg=0.01,
            beta_mem=0.05,
            lambda_drift=0.05,
            mu_anomaly=0.03,
        )
        self.ledger = EnergyLedger()
        self.last_annotations: Dict[str, Any] = {}
        self.last_state_metrics: Dict[str, Any] = {}
        self.last_state_sync_ts: float = 0.0
        self.started_at: float = 0.0
        self.event_log: deque[Dict[str, Any]] = deque(maxlen=EVENT_LOG_LIMIT)
        self.router_fast_hits: int = 0
        self.router_escalations: int = 0


state = ServiceState()


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _mean_mapping(values: Dict[str, Any]) -> float:
    if not isinstance(values, dict) or not values:
        return 0.0
    parsed = []
    for value in values.values():
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            continue
    return float(sum(parsed) / len(parsed)) if parsed else 0.0


def _derive_state_annotations(metrics: Dict[str, Any]) -> Dict[str, Any]:
    memory = metrics.get("memory", {}) if isinstance(metrics, dict) else {}
    ma = memory.get("ma", {}) if isinstance(memory, dict) else {}
    mw = memory.get("mw", {}) if isinstance(memory, dict) else {}
    mlt = memory.get("mlt", {}) if isinstance(memory, dict) else {}
    mfb = memory.get("mfb", {}) if isinstance(memory, dict) else {}
    system = metrics.get("system", {}) if isinstance(metrics, dict) else {}
    ops = metrics.get("ops", {}) if isinstance(metrics, dict) else {}

    avg_capability = _clamp(ma.get("avg_capability", 0.0))
    avg_memory_util = _clamp(ma.get("avg_memory_util", 0.0))
    avg_specialization_load = _clamp(
        ops.get("avg_specialization_load", _mean_mapping(ma.get("specialization_load", {})))
    )
    hit_rate = _clamp(mw.get("hit_rate", 0.0))
    miss_rate = _clamp(mw.get("miss_rate", max(0.0, 1.0 - hit_rate)))
    eviction_rate = _clamp(mw.get("eviction_rate", 0.0))
    queue_pressure = _clamp(float(mfb.get("queue_size", 0.0)) / 1024.0 if mfb else 0.0)
    compression_ratio = float(mlt.get("compression_ratio", 1.0) or 1.0)
    topology_penalty = 0.0 if ma.get("pair_matrix_present") else 0.1

    resource_pressure = _clamp(
        avg_memory_util * 0.40 + miss_rate * 0.35 + eviction_rate * 0.25
    )
    coordination_pressure = _clamp(
        avg_specialization_load * 0.45
        + (1.0 - avg_capability) * 0.25
        + queue_pressure * 0.20
        + topology_penalty * 0.10
    )
    anomaly = _clamp(
        abs(avg_specialization_load - avg_memory_util) * 0.60
        + max(0.0, queue_pressure - 0.70) * 0.40
    )
    drift = _clamp(
        coordination_pressure * 0.50
        + resource_pressure * 0.30
        + (1.0 - avg_capability) * 0.20
    )
    scaling_score = _clamp(
        max(
            resource_pressure,
            coordination_pressure,
            _clamp(ops.get("memory_pressure", 0.0)),
        )
    )
    p_fast = _clamp(1.0 - scaling_score, 0.05, 0.99)
    r_effective = max(1.0, compression_ratio if compression_ratio >= 1.0 else 1.0 / max(compression_ratio, 1e-6))
    p_compress = _clamp(queue_pressure * 0.50 + miss_rate * 0.50)
    beta_mem_hint = _clamp(0.05 + scaling_score * 0.35 + p_compress * 0.20, 0.05, 0.95)

    return {
        "drift": drift,
        "anomaly": anomaly,
        "scaling_score": scaling_score,
        "adaptive_params": {
            "scaling_temperature": round(1.0 + scaling_score * 0.75, 4),
        },
        "coordination_pressure": coordination_pressure,
        "resource_pressure": resource_pressure,
        "p_fast": p_fast,
        "p_esc": _clamp(1.0 - p_fast),
        "beta_mem_hint": beta_mem_hint,
        "memory_stats": {
            "r_effective": r_effective,
            "p_compress": p_compress,
        },
        "patterns_available": len(system.get("E_patterns", []) or []),
        "signal_source": DEFAULT_SIGNAL_SOURCE,
    }


def _merge_annotations(
    heuristic: Dict[str, Any],
    ml_stats: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    merged = dict(heuristic)
    if not isinstance(ml_stats, dict) or not ml_stats:
        return merged

    for key in ("drift", "anomaly", "scaling_score", "p_fast", "p_esc"):
        if key in ml_stats:
            merged[key] = ml_stats[key]
    adaptive_params = dict(heuristic.get("adaptive_params", {}))
    adaptive_params.update(ml_stats.get("adaptive_params", {}) or {})
    merged["adaptive_params"] = adaptive_params
    merged["signal_source"] = "ml+state"
    return merged


async def _get_annotations(metrics: Dict[str, Any]) -> Dict[str, Any]:
    heuristic = _derive_state_annotations(metrics)
    if not state.ml_feedback_enabled or not state.ml_client:
        return heuristic

    try:
        response = await asyncio.wait_for(state.ml_client.predict_all(metrics), timeout=3.0)
        ml_stats = response.get("ml_stats") if isinstance(response, dict) else response
        return _merge_annotations(heuristic, ml_stats if isinstance(ml_stats, dict) else None)
    except asyncio.TimeoutError:
        logger.warning("ML predict_all timed out; using deterministic state annotations")
    except Exception as exc:
        logger.warning("ML predict_all failed; using deterministic state annotations: %s", exc)
    return heuristic


def _build_meta_payload() -> Dict[str, Any]:
    total_router = (state.router_fast_hits + state.router_escalations) or 1
    p_fast_observed = state.router_fast_hits / total_router
    p_esc_observed = state.router_escalations / total_router

    p_fast = _clamp(
        state.last_annotations.get("p_fast", p_fast_observed),
        0.0,
        1.0,
    )
    p_esc = _clamp(
        state.last_annotations.get("p_esc", p_esc_observed or (1.0 - p_fast)),
        0.0,
        1.0,
    )
    beta_mem = _clamp(state.default_weights.beta_mem, 0.0, 0.999)
    L_tot = min(0.999, BETA_ROUTER * max(p_fast + p_esc, 1e-6) * BETA_META * RHO_CLIP * beta_mem)

    return {
        "p_fast": p_fast,
        "p_esc": p_esc,
        "beta_router": BETA_ROUTER,
        "beta_meta": BETA_META,
        "rho": RHO_CLIP,
        "beta_mem": beta_mem,
        "L_tot": L_tot,
        "cap": PROMOTION_LTOT_CAP,
        "ok_for_promotion": L_tot < PROMOTION_LTOT_CAP,
        "signal_source": state.last_annotations.get("signal_source", DEFAULT_SIGNAL_SOURCE),
    }


async def _execute_feedback(current_total_energy: float, annotations: Dict[str, Any]) -> float:
    previous_total = float(state.ledger.total)
    delta_e = current_total_energy - previous_total

    if delta_e > 0.05:
        state.default_weights.beta_mem = _clamp(state.default_weights.beta_mem * 1.05, 0.01, 1.0)
    elif delta_e < -0.05:
        state.default_weights.beta_mem = _clamp(state.default_weights.beta_mem * 0.97, 0.01, 1.0)

    if state.ml_feedback_enabled and state.ml_client:
        try:
            adaptive = annotations.get("adaptive_params", {}) if isinstance(annotations, dict) else {}
            if adaptive:
                await state.ml_client.update_adaptive_params(adaptive)
        except Exception as exc:
            logger.warning("Failed to send adaptive params to ML service: %s", exc)

    return delta_e


def _ledger_metrics_payload() -> Dict[str, Any]:
    return {
        "pair": float(state.ledger.pair),
        "hyper": float(state.ledger.hyper),
        "entropy": float(state.ledger.entropy),
        "reg": float(state.ledger.reg),
        "mem": float(state.ledger.mem),
        "drift_term": float(state.ledger.drift_term),
        "anomaly_term": float(state.ledger.anomaly_term),
        "scaling_score": float(state.ledger.scaling_score),
        "total": float(state.ledger.total),
        "delta_e": float(state.ledger.last_delta),
        "signal_source": state.last_annotations.get("signal_source", DEFAULT_SIGNAL_SOURCE),
        "timestamp": time.time(),
        "beta_mem": float(state.default_weights.beta_mem),
        "meta": _build_meta_payload(),
    }


async def _background_sampler():
    retry_delay = 1.0
    state.sampler_is_running = True
    while True:
        try:
            if not state.state_client:
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 1.5)
                continue

            data = await state.state_client.get_system_metrics()
            if not data.get("success"):
                logger.warning("StateService returned failure: %s", data.get("error", "unknown"))
                await asyncio.sleep(retry_delay)
                retry_delay = min(30.0, retry_delay * 1.5)
                continue

            metrics = data.get("metrics", {})
            annotations = await _get_annotations(metrics)
            memory_payload = dict(metrics.get("memory", {}) or {})
            memory_payload.update(annotations.get("memory_stats", {}) or {})

            system_payload = dict(metrics.get("system", {}) or {})
            system_payload["ml"] = annotations
            unified_state = UnifiedState.from_payload(
                {
                    "memory": metrics.get("memory", {}),
                    "system": system_payload,
                }
            )

            projected = unified_state.projected()
            weights = _create_weights_for_state(
                projected.H_matrix(),
                projected.hyper_selection(),
            )
            weights.beta_mem = float(annotations.get("beta_mem_hint", state.default_weights.beta_mem))
            weights.alpha_entropy = state.default_weights.alpha_entropy
            weights.lambda_reg = state.default_weights.lambda_reg
            weights.lambda_drift = state.default_weights.lambda_drift
            weights.mu_anomaly = state.default_weights.mu_anomaly

            result: EnergyResult = compute_energy_unified(
                projected,
                SystemParameters(
                    weights=weights,
                    memory_stats=memory_payload,
                    include_gradients=False,
                    ml_stats=annotations,
                ),
            )

            total_energy = float(result.breakdown.get("total", 0.0))
            delta_e = await _execute_feedback(total_energy, annotations)
            state.ledger.log_step(
                breakdown={
                    "pair": float(result.breakdown.get("pair", 0.0)),
                    "hyper": float(result.breakdown.get("hyper", 0.0)),
                    "entropy": float(result.breakdown.get("entropy", 0.0)),
                    "reg": float(result.breakdown.get("reg", 0.0)),
                    "mem": float(result.breakdown.get("mem", 0.0)),
                    "drift_term": float(result.breakdown.get("drift_term", 0.0)),
                    "anomaly_term": float(result.breakdown.get("anomaly_term", 0.0)),
                    "total": total_energy,
                },
                extra={
                    "source": "state-sampler",
                    "ts": time.time(),
                    "delta_E": delta_e,
                    "scaling_score": float(annotations.get("scaling_score", 0.0)),
                    "signal_source": annotations.get("signal_source", DEFAULT_SIGNAL_SOURCE),
                    "scope": "cluster",
                    "scope_id": "-",
                },
            )

            state.last_annotations = annotations
            state.last_state_metrics = metrics
            state.last_state_sync_ts = time.time()
            retry_delay = 1.0
            await asyncio.sleep(SAMPLER_INTERVAL_S)
        except asyncio.CancelledError:
            state.sampler_is_running = False
            break
        except Exception as exc:
            logger.error("Energy sampler failed: %s", exc, exc_info=True)
            await asyncio.sleep(retry_delay)
            retry_delay = min(30.0, retry_delay * 1.5)


def _parse_unified_state(state_dict: Dict[str, Any]) -> UnifiedState:
    if isinstance(state_dict, UnifiedState):
        return state_dict
    if hasattr(state_dict, "model_dump"):
        state_dict = state_dict.model_dump()
    elif hasattr(state_dict, "dict"):
        state_dict = state_dict.dict()
    return UnifiedState.from_payload(state_dict)


def _parse_weights(weights_dict: Optional[Dict[str, Any]]) -> EnergyWeights:
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

    for key in (
        "alpha_entropy",
        "lambda_reg",
        "beta_mem",
        "lambda_drift",
        "mu_anomaly",
    ):
        if key in weights_dict and weights_dict[key] is not None:
            setattr(weights, key, float(weights_dict[key]))
    if "W_pair" in weights_dict and weights_dict["W_pair"] is not None:
        weights.W_pair = np.asarray(weights_dict["W_pair"], dtype=np.float32)
    if "W_hyper" in weights_dict and weights_dict["W_hyper"] is not None:
        weights.W_hyper = np.asarray(weights_dict["W_hyper"], dtype=np.float32)
    return weights


def _create_weights_for_state(
    H: np.ndarray,
    E_sel: Optional[np.ndarray] = None,
) -> EnergyWeights:
    n_agents = H.shape[0] if H.ndim == 2 and H.size > 0 else 1
    n_hyper = E_sel.shape[0] if E_sel is not None and E_sel.size > 0 else 1

    return EnergyWeights(
        W_pair=np.eye(n_agents, dtype=np.float32) * 0.1,
        W_hyper=np.ones(n_hyper, dtype=np.float32) * 0.1,
        alpha_entropy=state.default_weights.alpha_entropy,
        lambda_reg=state.default_weights.lambda_reg,
        beta_mem=state.default_weights.beta_mem,
        lambda_drift=state.default_weights.lambda_drift,
        mu_anomaly=state.default_weights.mu_anomaly,
    )


@app.on_event("startup")
async def startup_event():
    logger.info("EnergyService starting up...")
    state.started_at = time.time()
    state.state_client = StateServiceClient(timeout=8.0)
    if state.ml_feedback_enabled:
        try:
            state.ml_client = MLServiceClient(timeout=6.0)
        except Exception as exc:
            logger.warning("ML client unavailable; running deterministic-only mode: %s", exc)
            state.ml_client = None
            state.ml_feedback_enabled = False
    state.sampler_task = asyncio.create_task(_background_sampler())


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("EnergyService shutting down...")
    if state.sampler_task:
        state.sampler_task.cancel()
        try:
            await state.sampler_task
        except asyncio.CancelledError:
            pass
    if state.state_client:
        await state.state_client.close()
    if state.ml_client:
        await state.ml_client.close()


@app.get("/health", response_model=HealthResponse)
async def health():
    if not state.state_client:
        raise HTTPException(status_code=503, detail="State client not initialized")
    state_service_healthy = await state.state_client.is_healthy()
    if state.sampler_is_running and state_service_healthy:
        status = "healthy"
    elif state_service_healthy:
        status = "degraded"
    else:
        status = "unhealthy"
    return HealthResponse(
        status=status,
        service="energy-service",
        sampler_running=state.sampler_is_running,
        state_service_healthy=state_service_healthy,
        error=None if status != "unhealthy" else "StateService unavailable",
    )


@app.get("/status")
async def status():
    state_service_healthy = (
        await state.state_client.is_healthy() if state.state_client else False
    )
    return {
        "status": (
            "ready"
            if state.sampler_is_running and state_service_healthy
            else "degraded" if state_service_healthy else "unhealthy"
        ),
        "service": "energy-service",
        "sampler_running": state.sampler_is_running,
        "state_service_healthy": state_service_healthy,
        "ml_feedback_enabled": state.ml_feedback_enabled,
        "signal_source": state.last_annotations.get("signal_source", DEFAULT_SIGNAL_SOURCE),
        "last_state_sync_ts": state.last_state_sync_ts,
        "uptime_s": max(0.0, time.time() - state.started_at),
        "meta": _build_meta_payload(),
    }


@app.get("/metrics")
async def get_metrics():
    return _ledger_metrics_payload()


@app.get("/meta")
async def get_meta():
    return _build_meta_payload()


@app.post("/log")
async def log_energy_event(event: Dict[str, Any] = Body(...)):
    payload = dict(event or {})
    payload.setdefault("ts", time.time())
    state.event_log.append(payload)

    metric = str(payload.get("metric", ""))
    if metric == "router_hit":
        state.router_fast_hits += 1
    elif metric == "escalation":
        state.router_escalations += 1
    elif metric == "flywheel_result":
        delta_e = float(payload.get("delta_E", 0.0))
        beta_mem_new = payload.get("beta_mem_new")
        if beta_mem_new is not None:
            state.default_weights.beta_mem = _clamp(beta_mem_new, 0.01, 1.0)
        state.ledger.last_delta = delta_e

    return {
        "status": "success",
        "message": "Energy event logged",
        "event_count": len(state.event_log),
    }


@app.get("/logs")
async def get_energy_logs(limit: int = 100):
    safe_limit = max(1, min(int(limit), EVENT_LOG_LIMIT))
    logs = list(state.event_log)[-safe_limit:]
    return {
        "logs": logs,
        "total_count": len(state.event_log),
        "returned_count": len(logs),
    }


@app.post("/compute-energy", response_model=EnergyResponse)
async def compute_energy_endpoint(request: EnergyRequest):
    start_time = time.time()
    try:
        unified_state = _parse_unified_state(request.unified_state)
        projected = unified_state.projected()
        memory_payload = {
            "ma": projected.memory.ma,
            "mw": projected.memory.mw,
            "mlt": projected.memory.mlt,
            "mfb": projected.memory.mfb,
        }
        ml_stats_payload = getattr(getattr(projected, "system", None), "ml", None)

        weights = (
            _parse_weights(request.weights.model_dump())
            if getattr(request, "weights", None) is not None
            else _create_weights_for_state(projected.H_matrix(), projected.hyper_selection())
        )

        result: EnergyResult = compute_energy_unified(
            projected,
            SystemParameters(
                weights=weights,
                memory_stats=memory_payload,
                include_gradients=bool(request.include_gradients),
                ml_stats=ml_stats_payload,
            ),
        )

        gradients = None
        if request.include_gradients and result.gradients:
            gradients = {
                key: value.tolist() if isinstance(value, np.ndarray) else value
                for key, value in result.gradients.items()
            }

        return EnergyResponse(
            success=True,
            energy=result.breakdown,
            gradients=gradients,
            breakdown=result.breakdown,
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000.0,
        )
    except Exception as exc:
        logger.error("Failed to compute energy", exc_info=True)
        return EnergyResponse(
            success=False,
            error=str(exc),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000.0,
        )


async def _compute_energy_from_state_impl() -> EnergyResponse:
    start_time = time.time()
    if not state.state_client:
        raise HTTPException(status_code=503, detail="StateService client not ready.")

    data = await state.state_client.get_system_metrics()
    if not data.get("success"):
        return EnergyResponse(
            success=False,
            error=data.get("error", "StateService unavailable"),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000.0,
        )

    metrics = data.get("metrics", {})
    annotations = await _get_annotations(metrics)
    memory_payload = dict(metrics.get("memory", {}) or {})
    memory_payload.update(annotations.get("memory_stats", {}) or {})

    system_section = dict(metrics.get("system", {}) or {})
    system_section["ml"] = annotations
    unified_state = UnifiedState.from_payload(
        {
            "memory": metrics.get("memory", {}),
            "system": system_section,
        }
    )
    projected = unified_state.projected()
    weights = _create_weights_for_state(projected.H_matrix(), projected.hyper_selection())
    weights.beta_mem = float(annotations.get("beta_mem_hint", state.default_weights.beta_mem))

    result: EnergyResult = compute_energy_unified(
        projected,
        SystemParameters(
            weights=weights,
            memory_stats=memory_payload,
            include_gradients=False,
            ml_stats=annotations,
        ),
    )

    return EnergyResponse(
        success=True,
        energy=result.breakdown,
        gradients=None,
        breakdown=result.breakdown,
        timestamp=time.time(),
        computation_time_ms=(time.time() - start_time) * 1000.0,
    )


@app.get("/compute-energy-from-state", response_model=EnergyResponse)
async def compute_energy_from_state():
    return await _compute_energy_from_state_impl()


@app.get("/compute-from-state", response_model=EnergyResponse)
async def compute_from_state_alias():
    return await _compute_energy_from_state_impl()


@app.get("/energy-from-state", response_model=EnergyResponse)
async def energy_from_state_alias():
    return await _compute_energy_from_state_impl()


@app.post("/flywheel/result", response_model=FlywheelResultResponse)
async def flywheel_result_endpoint(request: FlywheelResultRequest):
    ts = time.time()
    breakdown = request.breakdown or _ledger_metrics_payload()
    record = state.ledger.log_step(
        breakdown={
            "pair": float(breakdown.get("pair", 0.0)),
            "hyper": float(breakdown.get("hyper", 0.0)),
            "entropy": float(breakdown.get("entropy", 0.0)),
            "reg": float(breakdown.get("reg", 0.0)),
            "mem": float(breakdown.get("mem", 0.0)),
            "drift_term": float(breakdown.get("drift_term", 0.0)),
            "anomaly_term": float(breakdown.get("anomaly_term", 0.0)),
            "total": float(breakdown.get("total", 0.0)),
        },
        extra={
            "ts": ts,
            "delta_E": float(request.delta_e),
            "cost": float(request.cost or 0.0),
            "scope": request.scope or "cluster",
            "scope_id": request.scope_id or "-",
            "signal_source": state.last_annotations.get("signal_source", DEFAULT_SIGNAL_SOURCE),
        },
    )

    if request.beta_mem is not None:
        state.default_weights.beta_mem = _clamp(request.beta_mem, 0.01, 1.0)
    elif request.delta_e > 0:
        state.default_weights.beta_mem = _clamp(state.default_weights.beta_mem * 1.02, 0.01, 1.0)
    else:
        state.default_weights.beta_mem = _clamp(state.default_weights.beta_mem * 0.99, 0.01, 1.0)

    state.event_log.append(
        {
            "metric": "flywheel_result",
            "delta_E": float(request.delta_e),
            "beta_mem_new": float(state.default_weights.beta_mem),
            "ts": ts,
        }
    )

    return FlywheelResultResponse(
        success=True,
        updated_weights=state.default_weights.as_dict(),
        ledger_ok=bool(record.get("ok", True)),
        balance_after=record.get("balance_after"),
        timestamp=ts,
    )


@app.post("/optimize-agents", response_model=OptimizationResponse)
async def optimize_agents_endpoint(request: OptimizationRequest):
    start_time = time.time()
    try:
        unified_state = _parse_unified_state(request.unified_state)
        agents = unified_state.agents
        if not agents:
            raise HTTPException(
                status_code=400,
                detail="No agents provided in unified_state for optimization",
            )

        task_input = request.task
        task_dict = (
            task_input.model_dump()
            if hasattr(task_input, "model_dump")
            else dict(task_input)
        )
        task_complexity = estimate_task_complexity(task_dict)

        suitability_scores: Dict[str, float] = {}
        agent_data_cache: Dict[str, Dict[str, Any]] = {}
        for agent_id, snapshot in agents.items():
            agent_data = {
                "h": snapshot.h,
                "p": snapshot.p,
                "c": snapshot.c,
                "mem_util": snapshot.mem_util,
                "lifecycle": snapshot.lifecycle,
                "learned_skills": getattr(snapshot, "learned_skills", {}),
                "specialization": getattr(snapshot, "specialization", "unknown"),
            }
            agent_data_cache[agent_id] = agent_data
            suitability_scores[agent_id] = calculate_agent_suitability_score(
                agent_data,
                task_dict,
            )

        ranked_agent_ids = rank_agents_by_suitability(suitability_scores)
        max_agents = request.max_agents or len(ranked_agent_ids)
        selected_ids = ranked_agent_ids[:max_agents]
        recommended_roles = {
            agent_id: get_ideal_role_for_task(agent_data_cache[agent_id], task_dict)
            for agent_id in selected_ids
        }

        return OptimizationResponse(
            success=True,
            selected_agents=selected_ids,
            suitability_scores={k: float(v) for k, v in suitability_scores.items()},
            recommended_roles=recommended_roles,
            task_complexity=task_complexity,
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000.0,
        )
    except Exception as exc:
        logger.error("Failed to optimize agents", exc_info=True)
        return OptimizationResponse(
            success=False,
            error=str(exc),
            timestamp=time.time(),
            computation_time_ms=(time.time() - start_time) * 1000.0,
        )


@serve.deployment(name="EnergyService")
@serve.ingress(app)
class EnergyService:
    async def rpc_compute_energy(self, request: EnergyRequest) -> dict:
        response = await compute_energy_endpoint(request)
        return response.model_dump()

    async def rpc_compute_from_state(self) -> dict:
        response = await compute_energy_from_state()
        return response.model_dump()

    async def rpc_optimize_agents(self, request: OptimizationRequest) -> dict:
        response = await optimize_agents_endpoint(request)
        return response.model_dump()

    async def rpc_flywheel_result(self, request: FlywheelResultRequest) -> dict:
        response = await flywheel_result_endpoint(request)
        return response.model_dump()

    async def rpc_get_metrics(self) -> dict:
        return await get_metrics()

    async def rpc_get_meta(self) -> dict:
        return await get_meta()

    async def rpc_log_event(self, event: Dict[str, Any]) -> dict:
        return await log_energy_event(event)

    async def rpc_health(self) -> dict:
        response = await health()
        return response.model_dump()

    async def rpc_status(self) -> dict:
        return await status()


energy_app = EnergyService.bind()


def build_energy_app(args: dict | None = None):
    return energy_app
