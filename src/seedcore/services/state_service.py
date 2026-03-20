#!/usr/bin/env python3
"""
State Service - architecture-facing operational state for SeedCore.

This service aggregates deterministic system state from agents, memory, and
optional topology/pattern sources. It intentionally avoids dependence on
LLM/cognitive services for its core value so coordinator, routing, and energy
flows can keep working when AI providers are noisy or unavailable.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

import numpy as np
from fastapi import Body, FastAPI, HTTPException
from fastapi import Response as FastAPIResponse
from ray import serve  # pyright: ignore[reportMissingImports]
from sqlalchemy import select  # pyright: ignore[reportMissingImports]

from seedcore.database import get_async_pg_session_factory
from seedcore.graph.agent_repository import AgentGraphRepository
from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.models.asset_custody import AssetCustodyState
from seedcore.models.source_registration import SourceRegistration, SourceRegistrationStatus
from seedcore.ops.state.agent_aggregator import AgentAggregator
from seedcore.ops.state.memory_aggregator import MemoryAggregator
from seedcore.ops.state.system_aggregator import SystemAggregator
from seedcore.serve.organism_client import get_organism_service_handle

from ..models.state import (
    MemoryVector,
    Response as StateEnvelope,
    SystemState,
    UnifiedState,
)

setup_logging(app_name="seedcore.state_service.driver")
logger = ensure_serve_logger("seedcore.state_service", level="DEBUG")

app = FastAPI(
    title="SeedCore State Service",
    version="3.0.0",
    docs_url=None,
    redoc_url=None,
)

DEFAULT_W_MODE = np.array([0.4, 0.3, 0.3], dtype=np.float32)


class ServiceState:
    def __init__(self) -> None:
        self.agent_aggregator: Optional[AgentAggregator] = None
        self.memory_aggregator: Optional[MemoryAggregator] = None
        self.system_aggregator: Optional[SystemAggregator] = None
        self.pg_session_factory = None
        self.w_mode: np.ndarray = DEFAULT_W_MODE.copy()
        self.started_at: float = 0.0


state = ServiceState()


def _numpy_to_python(obj: Any) -> Any:
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_numpy_to_python(i) for i in obj]
    return obj


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _average_mapping(values: Dict[str, Any]) -> float:
    if not isinstance(values, dict) or not values:
        return 0.0
    numeric = []
    for value in values.values():
        try:
            numeric.append(float(value))
        except (TypeError, ValueError):
            continue
    return float(sum(numeric) / len(numeric)) if numeric else 0.0


def _serialize_memory(memory_vector: MemoryVector) -> Dict[str, Any]:
    return {
        "ma": memory_vector.ma,
        "mw": memory_vector.mw,
        "mlt": memory_vector.mlt,
        "mfb": memory_vector.mfb,
        "util_scalar": memory_vector.utilization_scalar(),
    }


def _build_operational_summary(
    agent_metrics: Dict[str, Any],
    memory_stats: Dict[str, Any],
    e_patterns: Any,
) -> Dict[str, Any]:
    ma = agent_metrics or {}
    mw = memory_stats.get("mw", {}) if isinstance(memory_stats, dict) else {}
    mlt = memory_stats.get("mlt", {}) if isinstance(memory_stats, dict) else {}
    mfb = memory_stats.get("mfb", {}) if isinstance(memory_stats, dict) else {}

    avg_capability = _clamp(ma.get("avg_capability", 0.0))
    avg_memory_util = _clamp(ma.get("avg_memory_util", 0.0))
    avg_specialization_load = _clamp(
        _average_mapping(ma.get("specialization_load", {}))
    )
    hit_rate = _clamp(mw.get("hit_rate", 0.0))
    miss_rate = _clamp(mw.get("miss_rate", max(0.0, 1.0 - hit_rate)))
    eviction_rate = _clamp(mw.get("eviction_rate", 0.0))
    queue_pressure = _clamp(
        float(mfb.get("queue_size", 0.0)) / 1024.0 if mfb else 0.0
    )
    ltm_status = str(mlt.get("status", "unknown"))
    topology_ready = bool(ma.get("pair_matrix_present"))
    patterns_available = (
        int(np.asarray(e_patterns).size) if e_patterns is not None else 0
    )

    memory_pressure = _clamp(
        (1.0 - hit_rate) * 0.35
        + miss_rate * 0.30
        + avg_memory_util * 0.20
        + eviction_rate * 0.15
    )
    coordination_pressure = _clamp(
        avg_specialization_load * 0.45
        + avg_memory_util * 0.25
        + (1.0 - avg_capability) * 0.20
        + queue_pressure * 0.10
        + (0.10 if not topology_ready else 0.0)
    )
    stability_score = _clamp(
        1.0 - max(memory_pressure, coordination_pressure, queue_pressure)
    )
    fast_path_ready = bool(
        ma.get("total_agents", 0) > 0
        and avg_capability >= 0.20
        and stability_score >= 0.25
    )

    return {
        "avg_specialization_load": avg_specialization_load,
        "memory_pressure": memory_pressure,
        "coordination_pressure": coordination_pressure,
        "queue_pressure": queue_pressure,
        "stability_score": stability_score,
        "topology_ready": topology_ready,
        "patterns_available": patterns_available,
        "ltm_status": ltm_status,
        "fast_path_ready": fast_path_ready,
        "signal_source": "state-service",
    }


def _serialize_system_state(
    system_state: SystemState, ops_summary: Dict[str, Any]
) -> Dict[str, Any]:
    return {
        "h_hgnn": None
        if system_state.h_hgnn is None
        else system_state.h_hgnn.tolist(),
        "E_patterns": None
        if system_state.E_patterns is None
        else system_state.E_patterns.tolist(),
        "w_mode": None
        if system_state.w_mode is None
        else system_state.w_mode.tolist(),
        "ml": dict(system_state.ml),
        "operational_summary": ops_summary,
    }


async def _component_statuses() -> Dict[str, Dict[str, Any]]:
    ts_system = 0.0
    if state.system_aggregator:
        try:
            ts_system = await state.system_aggregator.get_last_update_time()
        except Exception:
            ts_system = 0.0

    return {
        "agent": {
            "ready": bool(
                state.agent_aggregator and state.agent_aggregator.is_running()
            ),
            "required": True,
            "last_update_time": (
                await state.agent_aggregator.get_last_update_time()
                if state.agent_aggregator
                else 0.0
            ),
        },
        "memory": {
            "ready": bool(
                state.memory_aggregator and state.memory_aggregator.is_running()
            ),
            "required": True,
            "last_update_time": (
                await state.memory_aggregator.get_last_update_time()
                if state.memory_aggregator
                else 0.0
            ),
        },
        "system": {
            "ready": bool(
                state.system_aggregator and state.system_aggregator.is_running()
            ),
            "required": False,
            "last_update_time": ts_system,
        },
    }


async def _build_state_response(
    *,
    include_unified_state: bool = False,
) -> StateEnvelope:
    start_ts = time.perf_counter()

    if not state.agent_aggregator:
        raise HTTPException(status_code=503, detail="Agent aggregator not initialized")
    if not state.memory_aggregator:
        raise HTTPException(status_code=503, detail="Memory aggregator not initialized")

    async def _get_e_patterns():
        if state.system_aggregator:
            return await state.system_aggregator.get_E_patterns()
        return np.asarray([], dtype=np.float32)

    tasks = [
        state.agent_aggregator.get_system_metrics(),
        state.memory_aggregator.get_memory_stats(),
        _get_e_patterns(),
        state.agent_aggregator.get_last_update_time(),
        state.memory_aggregator.get_last_update_time(),
    ]

    if include_unified_state:
        tasks.append(state.agent_aggregator.get_all_agent_snapshots())
        tasks.append(_fetch_authoritative_assets())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    agent_metrics = results[0]
    if isinstance(agent_metrics, Exception):
        raise HTTPException(
            status_code=503,
            detail=f"Agent aggregator error: {agent_metrics}",
        )
    if not agent_metrics:
        raise HTTPException(
            status_code=503,
            detail="Agent aggregator not ready yet (no metrics available)",
        )

    memory_stats = results[1] if not isinstance(results[1], Exception) else {}
    e_patterns = results[2] if not isinstance(results[2], Exception) else []
    ts_agent = float(results[3]) if not isinstance(results[3], Exception) else 0.0
    ts_memory = float(results[4]) if not isinstance(results[4], Exception) else 0.0

    is_degraded = not bool(memory_stats)
    status_label = "degraded" if is_degraded else "healthy"

    memory_vector = MemoryVector(
        ma=agent_metrics,
        mw=memory_stats.get("mw", {}) if isinstance(memory_stats, dict) else {},
        mlt=memory_stats.get("mlt", {}) if isinstance(memory_stats, dict) else {},
        mfb=memory_stats.get("mfb", {}) if isinstance(memory_stats, dict) else {},
    )

    ops_summary = _build_operational_summary(agent_metrics, memory_stats, e_patterns)
    system_state = SystemState(
        h_hgnn=agent_metrics.get("h_hgnn"),
        E_patterns=e_patterns,
        w_mode=state.w_mode.copy(),
        ml={
            "signal_source": "state-service",
            "coordination_pressure": ops_summary["coordination_pressure"],
            "memory_pressure": ops_summary["memory_pressure"],
            "stability_score": ops_summary["stability_score"],
        },
    )

    metrics = {
        "memory": _serialize_memory(memory_vector),
        "system": _serialize_system_state(system_state, ops_summary),
        "ops": ops_summary,
    }

    components = await _component_statuses()
    latency_ms = (time.perf_counter() - start_ts) * 1000.0
    final_ts = max(ts_agent, ts_memory)
    meta = {
        "status": status_label,
        "latency_ms": latency_ms,
        "ts_agent": ts_agent,
        "ts_memory": ts_memory,
        "components": components,
        "snapshot_version": "state-v3",
    }

    payload = None
    if include_unified_state:
        snapshots = results[5] if len(results) > 5 else {}
        if isinstance(snapshots, Exception):
            snapshots = {}
        assets = results[6] if len(results) > 6 else {}
        if isinstance(assets, Exception):
            assets = {}
        payload = UnifiedState(
            agents=snapshots or {},
            organs={},
            system=system_state,
            memory=memory_vector,
            assets=assets if isinstance(assets, dict) else {},
        )

    response = StateEnvelope.ok(metrics=metrics, meta=meta, payload=payload)
    response.timestamp = final_ts or time.time()
    return response


@app.on_event("startup")
async def startup_event():
    logger.info("StateService starting up...")
    state.started_at = time.time()
    try:
        w_mode_str = os.getenv("SYSTEM_W_MODE", "0.4,0.3,0.3")
        try:
            parsed = [float(part) for part in w_mode_str.split(",")]
            if len(parsed) == 3:
                state.w_mode = np.asarray(parsed, dtype=np.float32)
            else:
                state.w_mode = DEFAULT_W_MODE.copy()
        except Exception:
            logger.warning("Using default w_mode %s", DEFAULT_W_MODE.tolist())
            state.w_mode = DEFAULT_W_MODE.copy()

        try:
            organism_router = get_organism_service_handle()
        except Exception as exc:
            logger.warning(
                "Failed to get organism service handle at startup: %s", exc
            )
            organism_router = None

        graph_repo = AgentGraphRepository()
        try:
            state.pg_session_factory = get_async_pg_session_factory()
        except Exception as exc:
            logger.warning("StateService asset snapshot DB unavailable: %s", exc)
            state.pg_session_factory = None
        state.agent_aggregator = AgentAggregator(
            organism_router=organism_router,
            graph_repo=graph_repo,
            poll_interval=2.0,
        )
        await state.agent_aggregator.start()

        state.memory_aggregator = MemoryAggregator(poll_interval=5.0)
        await state.memory_aggregator.start()

        try:
            state.system_aggregator = SystemAggregator(poll_interval=5.0)
            await state.system_aggregator.start()
        except Exception as exc:
            logger.warning(
                "SystemAggregator unavailable, continuing without topology patterns: %s",
                exc,
            )
            state.system_aggregator = None

        waiters = [
            state.agent_aggregator.wait_for_first_poll(),
            state.memory_aggregator.wait_for_first_poll(),
        ]
        if state.system_aggregator:
            waiters.append(state.system_aggregator.wait_for_first_poll())

        try:
            await asyncio.wait_for(
                asyncio.gather(*waiters, return_exceptions=True),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "StateService warmup timed out; aggregators will continue in background"
            )
    except Exception:
        logger.error("Failed to initialize StateService", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("StateService shutting down...")
    tasks = []
    if state.agent_aggregator:
        tasks.append(state.agent_aggregator.stop())
    if state.memory_aggregator:
        tasks.append(state.memory_aggregator.stop())
    if state.system_aggregator:
        tasks.append(state.system_aggregator.stop())
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@app.get("/health")
async def health():
    components = await _component_statuses()
    required_ready = all(
        component["ready"]
        for component in components.values()
        if component["required"]
    )
    if not required_ready:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "service": "state",
                "components": components,
            },
        )

    overall_status = (
        "healthy"
        if all(component["ready"] for component in components.values())
        else "degraded"
    )
    return {
        "status": overall_status,
        "service": "state",
        "components": components,
        "uptime_s": max(0.0, time.time() - state.started_at),
    }


@app.get("/status")
async def status():
    components = await _component_statuses()
    return {
        "status": (
            "ready"
            if all(
                component["ready"]
                for component in components.values()
                if component["required"]
            )
            else "initializing"
        ),
        "service": "state",
        "w_mode": state.w_mode.tolist(),
        "components": components,
        "uptime_s": max(0.0, time.time() - state.started_at),
        "snapshot_version": "state-v3",
    }


@app.get("/system-metrics")
async def get_system_metrics(response: FastAPIResponse):
    snapshot = await _build_state_response(include_unified_state=False)
    body = _numpy_to_python(snapshot.to_dict())
    if response is not None:
        meta = body.get("meta", {})
        response.headers["X-System-Status"] = str(meta.get("status", "unknown"))
        response.headers["X-Processing-Time"] = f"{meta.get('latency_ms', 0.0):.3f}ms"
    return body


@app.get("/unified-state")
async def get_unified_state(response: FastAPIResponse):
    snapshot = await _build_state_response(include_unified_state=True)
    body = _numpy_to_python(snapshot.to_dict())
    if response is not None:
        response.headers["X-State-Snapshot"] = "unified"
    return body


@app.post("/unified-state")
async def post_unified_state(
    payload: Dict[str, Any] = Body(default={}),
    response: FastAPIResponse = None,
):
    include_unified_state = bool(payload.get("include_payload", True))
    snapshot = await _build_state_response(
        include_unified_state=include_unified_state
    )
    body = _numpy_to_python(snapshot.to_dict())
    if response is not None:
        response.headers["X-State-Snapshot"] = "unified"
    return body


@app.post("/config/w_mode")
async def update_w_mode(payload: Dict[str, Any] = Body(...)):
    new_w = payload.get("w_mode")
    if not isinstance(new_w, list) or len(new_w) != 3:
        raise HTTPException(status_code=400, detail="w_mode must be a list of 3 floats")

    try:
        state.w_mode = np.asarray([float(value) for value in new_w], dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "success": True,
        "w_mode": state.w_mode.tolist(),
        "timestamp": time.time(),
    }


@app.get("/agent-snapshots")
async def get_all_agent_snapshots():
    if not state.agent_aggregator:
        raise HTTPException(status_code=503, detail="Agent aggregator not initialized")

    snapshots = await state.agent_aggregator.get_all_agent_snapshots()
    snapshots_dict = {}
    for agent_id, snapshot in snapshots.items():
        snapshots_dict[agent_id] = {
            "h": snapshot.h,
            "p": snapshot.p,
            "c": snapshot.c,
            "mem_util": snapshot.mem_util,
            "lifecycle": snapshot.lifecycle,
            "learned_skills": snapshot.learned_skills,
            "load": snapshot.load,
            "timestamp": snapshot.timestamp,
            "schema_version": snapshot.schema_version,
        }

    return _numpy_to_python(
        {
            "success": True,
            "count": len(snapshots_dict),
            "snapshots": snapshots_dict,
            "timestamp": await state.agent_aggregator.get_last_update_time(),
        }
    )


@serve.deployment(name="StateService")
@serve.ingress(app)
class StateService:
    async def rpc_system_metrics(self):
        snapshot = await _build_state_response(include_unified_state=False)
        return _numpy_to_python(snapshot.to_dict())

    async def rpc_unified_state(self):
        snapshot = await _build_state_response(include_unified_state=True)
        return _numpy_to_python(snapshot.to_dict())

    async def rpc_agent_snapshots(self):
        return await get_all_agent_snapshots()

    async def rpc_update_w_mode(self, payload: Dict[str, Any]):
        return await update_w_mode(payload)

    async def rpc_health(self):
        return await health()

    async def rpc_status(self):
        return await status()


state_app = StateService.bind()


def build_state_app(args: dict | None = None):
    return state_app


async def _fetch_authoritative_assets(limit: int = 256) -> Dict[str, Any]:
    session_factory = getattr(state, "pg_session_factory", None)
    if session_factory is None:
        return {}

    try:
        async with session_factory() as session:
            custody_result = await session.execute(
                select(AssetCustodyState)
                .order_by(AssetCustodyState.updated_at.desc(), AssetCustodyState.created_at.desc())
                .limit(limit)
            )
            custody_rows = custody_result.scalars().all()
            result = await session.execute(
                select(SourceRegistration)
                .order_by(SourceRegistration.updated_at.desc(), SourceRegistration.created_at.desc())
                .limit(limit)
            )
            registrations = result.scalars().all()
    except Exception as exc:
        logger.debug("StateService asset snapshot fetch failed: %s", exc)
        return {}

    assets = _project_asset_custody_states(custody_rows)
    return _merge_registration_fallback_assets(assets, registrations)


def _project_asset_custody_states(rows: list[AssetCustodyState]) -> Dict[str, Any]:
    assets: Dict[str, Any] = {}
    for row in rows:
        asset_state = {
            "source_registration_id": row.source_registration_id,
            "lot_id": row.lot_id,
            "batch_id": row.lot_id,
            "product_id": getattr(row, "product_id", None),
            "source_claim_id": row.source_claim_id,
            "producer_id": row.producer_id,
            "registration_status": "quarantined" if bool(row.is_quarantined) else None,
            "is_quarantined": bool(row.is_quarantined),
            "current_zone": row.current_zone,
            "authority_source": row.authority_source,
            "last_transition_seq": int(getattr(row, "last_transition_seq", 0) or 0),
            "last_receipt_hash": row.last_receipt_hash,
            "last_receipt_nonce": row.last_receipt_nonce,
            "last_endpoint_id": row.last_endpoint_id,
            "updated_at": (
                row.updated_at.isoformat()
                if getattr(row, "updated_at", None) is not None
                else None
            ),
        }
        for key in _asset_custody_keys(row):
            assets.setdefault(key, dict(asset_state))
    return assets


def _asset_custody_keys(row: AssetCustodyState) -> list[str]:
    keys = [str(row.asset_id)]
    for value in (row.lot_id, row.source_registration_id, row.source_claim_id):
        if value:
            keys.append(str(value))
    # preserve order while removing duplicates
    return list(dict.fromkeys(keys))


def _project_authoritative_assets(registrations: list[SourceRegistration]) -> Dict[str, Any]:
    assets: Dict[str, Any] = {}
    for registration in registrations:
        asset_state = {
            "source_registration_id": str(registration.id),
            "lot_id": str(registration.lot_id),
            "batch_id": str(registration.lot_id),
            "product_id": (
                str(getattr(registration, "product_id"))
                if getattr(registration, "product_id", None) is not None
                else None
            ),
            "producer_id": str(registration.producer_id),
            "registration_status": str(registration.status.value),
            "is_quarantined": registration.status == SourceRegistrationStatus.QUARANTINED,
            "current_zone": _derive_registration_zone(registration),
            "updated_at": (
                registration.updated_at.isoformat()
                if getattr(registration, "updated_at", None) is not None
                else None
            ),
        }
        for key in _registration_asset_keys(registration):
            assets.setdefault(key, dict(asset_state))
    return assets


def _merge_registration_fallback_assets(
    custody_assets: Dict[str, Any],
    registrations: list[SourceRegistration],
) -> Dict[str, Any]:
    assets = {
        str(key): dict(value)
        for key, value in custody_assets.items()
        if isinstance(value, dict)
    }
    registration_assets = _project_authoritative_assets(registrations)
    for key, registration_state in registration_assets.items():
        existing = assets.get(key)
        if existing is None:
            assets[key] = dict(registration_state)
            continue
        assets[key] = {
            **dict(registration_state),
            **existing,
            "registration_status": (
                existing.get("registration_status")
                or registration_state.get("registration_status")
            ),
            "producer_id": existing.get("producer_id") or registration_state.get("producer_id"),
            "source_registration_id": (
                existing.get("source_registration_id")
                or registration_state.get("source_registration_id")
            ),
            "lot_id": existing.get("lot_id") or registration_state.get("lot_id"),
            "batch_id": existing.get("batch_id") or registration_state.get("batch_id"),
            "product_id": existing.get("product_id") or registration_state.get("product_id"),
        }
    return assets


def _registration_asset_keys(registration: SourceRegistration) -> list[str]:
    keys = [str(registration.id), str(registration.lot_id)]
    source_claim_id = getattr(registration, "source_claim_id", None)
    if source_claim_id:
        keys.append(str(source_claim_id))
    return keys


def _derive_registration_zone(registration: SourceRegistration) -> Optional[str]:
    claimed_origin = (
        dict(registration.claimed_origin)
        if isinstance(getattr(registration, "claimed_origin", None), dict)
        else {}
    )
    collection_site = (
        dict(registration.collection_site)
        if isinstance(getattr(registration, "collection_site", None), dict)
        else {}
    )
    zone = (
        claimed_origin.get("zone_id")
        or collection_site.get("zone_id")
        or collection_site.get("site_id")
    )
    return str(zone) if zone is not None else None
