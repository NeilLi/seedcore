#!/usr/bin/env python3
"""
State Service - Proactive Standalone Ray Serve Application
Version: 2.1 (Flywheel Compatible)

Role:
- Aggregates raw data from Agents, Memory, and System.
- Distills complex objects into 'UnifiedState' vectors.
- Serves as the Single Source of Truth for Energy and ML services.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Optional, Dict, Any
import numpy as np
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException, Body  # pyright: ignore[reportMissingImports]

# Import the proactive aggregators
from seedcore.ops.state.agent_aggregator import AgentAggregator
from seedcore.ops.state.memory_aggregator import MemoryAggregator
from seedcore.ops.state.system_aggregator import SystemAggregator
from ..models.state import SystemState, MemoryVector

# Import organism client helper
from seedcore.serve.organism_client import get_organism_service_handle

# Logging
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.state_service.driver")
logger = ensure_serve_logger("seedcore.state_service", level="DEBUG")

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Proactive State Service", version="2.1.0")


# --- Service State ---
class ServiceState:
    agent_aggregator: Optional[AgentAggregator] = None
    memory_aggregator: Optional[MemoryAggregator] = None
    system_aggregator: Optional[SystemAggregator] = None

    # System Weights (w_mode): [Balance, Specialization, Efficiency]
    # Mutable: Can be updated by Coordinator/Energy Service
    w_mode: np.ndarray = np.array([0.4, 0.3, 0.3], dtype=np.float32)


state = ServiceState()


# --- Helper: Serialization ---
def _numpy_to_python(obj):
    """Recursively convert generic numpy objects to standard python types."""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {k: _numpy_to_python(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_numpy_to_python(i) for i in obj]
    return obj


# --- Lifespan Events ---


@app.on_event("startup")
async def startup_event():
    """On service startup, initialize and start all proactive aggregators."""
    logger.info("🚀 StateService starting up...")
    try:
        # Load initial w_mode from environment
        w_mode_str = os.getenv("SYSTEM_W_MODE", "0.4,0.3,0.3")
        try:
            state.w_mode = np.array(
                [float(w) for w in w_mode_str.split(",")], dtype=np.float32
            )
        except Exception:
            logger.warning("Using default w_mode [0.4, 0.3, 0.3]")
            state.w_mode = np.array([0.4, 0.3, 0.3], dtype=np.float32)
        logger.info(f"✅ Loaded w_mode: {state.w_mode}")

        # Connect to Organism Service
        organism_router = get_organism_service_handle()

        # 1. Start Agent Aggregator (Fast poll for dynamics)
        state.agent_aggregator = AgentAggregator(organism_router, poll_interval=2.0)
        await state.agent_aggregator.start()

        # 2. Start Memory Aggregator (Slower poll for stability)
        state.memory_aggregator = MemoryAggregator(poll_interval=5.0)
        await state.memory_aggregator.start()

        # 3. Start System Aggregator (Pattern tracking)
        state.system_aggregator = SystemAggregator(poll_interval=5.0)
        await state.system_aggregator.start()

        # 4. Warmup: Wait for first data
        await asyncio.gather(
            state.agent_aggregator.wait_for_first_poll(),
            state.memory_aggregator.wait_for_first_poll(),
            state.system_aggregator.wait_for_first_poll(),
        )

        logger.info("✅ All proactive aggregators are running and have data.")

    except Exception as e:
        logger.error(
            f"❌ FATAL: Failed to initialize proactive aggregators: {e}", exc_info=True
        )
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Gracefully stop all aggregator loops."""
    logger.info("🛑 StateService shutting down...")
    tasks = []
    if state.agent_aggregator:
        tasks.append(state.agent_aggregator.stop())
    if state.memory_aggregator:
        tasks.append(state.memory_aggregator.stop())
    if state.system_aggregator:
        tasks.append(state.system_aggregator.stop())

    if tasks:
        await asyncio.gather(*tasks)
    logger.info("✅ All aggregators stopped.")


# --- API Endpoints ---


@app.get("/health")
async def health():
    """Simple health check for K8s/Ray."""
    if (
        state.agent_aggregator
        and state.agent_aggregator.is_running()
        and state.memory_aggregator
        and state.memory_aggregator.is_running()
        and state.system_aggregator
        and state.system_aggregator.is_running()
    ):
        return {"status": "healthy", "service": "state", "aggregators": "running"}

    raise HTTPException(status_code=503, detail="Aggregators initializing or failed")


@app.get("/system-metrics")
async def get_system_metrics():
    """
    Returns the Distilled Unified State.
    Input for: EnergyService (to compute H) and MLService (to predict drift).
    Complexity: O(1) - Returns pre-computed cached data.
    """
    if not state.agent_aggregator:
        raise HTTPException(status_code=503, detail="Aggregators not ready")

    # 1. Gather data from aggregators
    agent_metrics = await state.agent_aggregator.get_system_metrics()
    mem_stats = await state.memory_aggregator.get_memory_stats()
    e_patterns = await state.system_aggregator.get_E_patterns()

    # 2. Construct Data Transfer Objects (DTOs)

    # Unified Memory Vector: Combining Agent stats (ma) with Memory Manager stats (mw...)
    unified_memory = MemoryVector(
        ma=agent_metrics,  # 'ma' comes from agent aggregator
        mw=mem_stats.get("mw", {}),
        mlt=mem_stats.get("mlt", {}),
        mfb=mem_stats.get("mfb", {}),
    )

    # System State Vector
    system_state_obj = SystemState(
        h_hgnn=agent_metrics.get("h_hgnn"),  # HGNN centroid
        E_patterns=e_patterns,  # Historical energy patterns
        w_mode=state.w_mode,  # Current global weight configuration
    )

    # 3. Synchronize Timestamp
    # Use the oldest timestamp to ensure data consistency across services
    ts = min(
        await state.agent_aggregator.get_last_update_time(),
        await state.memory_aggregator.get_last_update_time(),
    )

    # 4. Return serialized response
    response_payload = {
        "success": True,
        "metrics": {
            "memory": unified_memory.model_dump(),
            "system": system_state_obj.model_dump(),
        },
        "timestamp": ts,
    }

    # Ensure JSON safety (NumPy float32 -> Python float)
    return _numpy_to_python(response_payload)


@app.post("/config/w_mode")
async def update_w_mode(payload: Dict[str, Any] = Body(...)):
    """
    Update the global system weight configuration (w_mode).
    Used by: Coordinator (manual override) or EnergyService (adaptive).
    """
    try:
        new_w = payload.get("w_mode")
        if not new_w or len(new_w) != 3:
            raise HTTPException(400, "w_mode must be a list of 3 floats")

        state.w_mode = np.array(new_w, dtype=np.float32)
        logger.info(f"🔄 w_mode updated to: {state.w_mode}")

        return {
            "success": True,
            "w_mode": state.w_mode.tolist(),
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Failed to update w_mode: {e}")
        raise HTTPException(500, str(e))


@app.get("/agent-snapshots")
async def get_all_agent_snapshots():
    """
    Returns full raw state for all agents.
    Heavy payload - Use only for deep debugging or cold-start snapshots.
    """
    if not state.agent_aggregator:
        raise HTTPException(status_code=503, detail="Aggregator not ready")

    snapshots = await state.agent_aggregator.get_all_agent_snapshots()

    # Convert dataclasses to dicts for JSON
    snapshots_dict = {}
    for agent_id, snapshot in snapshots.items():
        snapshots_dict[agent_id] = {
            "h": snapshot.h,
            "p": snapshot.p,
            "c": snapshot.c,
            "mem_util": snapshot.mem_util,
            "lifecycle": snapshot.lifecycle,
            "learned_skills": snapshot.learned_skills,
        }

    return _numpy_to_python(
        {
            "success": True,
            "count": len(snapshots_dict),
            "snapshots": snapshots_dict,
            "timestamp": await state.agent_aggregator.get_last_update_time(),
        }
    )


# --- Ray Serve Deployment ---
@serve.deployment(name="StateService")
@serve.ingress(app)
class StateService:
    def __init__(self):
        pass


# --- Main Entrypoint ---
state_app = StateService.bind()


def build_state_app(args: dict = None):
    return state_app
