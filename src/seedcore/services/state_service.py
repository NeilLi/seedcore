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
from seedcore.graph.agent_repository import AgentGraphRepository
from seedcore.ops.state.agent_aggregator import AgentAggregator
from seedcore.ops.state.memory_aggregator import MemoryAggregator
from seedcore.ops.state.system_aggregator import SystemAggregator
from ..models.state import Response, SystemState, MemoryVector

# Import organism client helper
from seedcore.serve.organism_client import get_organism_service_handle

# Logging
from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.state_service.driver")
logger = ensure_serve_logger("seedcore.state_service", level="DEBUG")

# --- FastAPI app for ingress ---
app = FastAPI(title="SeedCore Proactive State Service", version="2.1.0", docs_url=None, redoc_url=None)  # Disable docs - only accessed via RPC


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

        # Connect to Organism Service (with error handling)
        try:
            organism_router = get_organism_service_handle()
        except Exception as e:
            logger.warning(f"⚠️ Failed to get organism service handle: {e} - will retry during polling")
            organism_router = None

        # 1. Start Agent Aggregator (Fast poll for dynamics)
        try:
            graph_repo = AgentGraphRepository()
            state.agent_aggregator = AgentAggregator(
                organism_router=organism_router,
                graph_repo=graph_repo,           # ← inject repository here
                poll_interval=2.0,
            )
        except Exception as e:
            logger.error(f"❌ Failed to initialize AgentAggregator: {e}", exc_info=True)
            raise  # AgentAggregator is critical, fail fast

        # 2. Start Memory Aggregator (Slower poll for stability)
        try:
            state.memory_aggregator = MemoryAggregator(poll_interval=5.0)
            await state.memory_aggregator.start()
        except Exception as e:
            logger.error(f"❌ Failed to start MemoryAggregator: {e}", exc_info=True)
            raise  # MemoryAggregator is critical, fail fast

        # 3. Start System Aggregator (Pattern tracking)
        try:
            state.system_aggregator = SystemAggregator(poll_interval=5.0)
            await state.system_aggregator.start()
        except Exception as e:
            logger.warning(f"⚠️ Failed to start SystemAggregator: {e} - continuing without it")
            state.system_aggregator = None  # SystemAggregator is optional

        # 4. Warmup: Wait for first data (with timeout to prevent startup failure)
        # Note: We don't fail startup if aggregators can't get initial data immediately
        # They will continue polling in the background and data will be available soon
        wait_tasks = [
            state.agent_aggregator.wait_for_first_poll(),
            state.memory_aggregator.wait_for_first_poll(),
        ]
        if state.system_aggregator:
            wait_tasks.append(state.system_aggregator.wait_for_first_poll())
        
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*wait_tasks, return_exceptions=True),
                timeout=30.0,  # 30 second timeout for initial data
            )
            # Check for exceptions in results
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"⚠️ Aggregator {i} had error during first poll: {result}")
            logger.info("✅ Proactive aggregators are running (some may still be gathering initial data).")
        except asyncio.TimeoutError:
            logger.warning("⚠️ Timeout waiting for first poll data - aggregators will continue in background")
        except Exception as e:
            logger.warning(f"⚠️ Error waiting for first poll data: {e} - aggregators will continue in background")

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
async def get_system_metrics(response: Optional[Response] = None):
    """
    Returns the Distilled Unified State.
    Input for: EnergyService (to compute H) and MLService (to predict drift).
    Complexity: O(1) - Returns pre-computed cached data.
    """
    start_ts = time.perf_counter()

    # 1. Check Vital Aggregator
    if not state.agent_aggregator:
        raise HTTPException(status_code=503, detail="Agent Aggregator not initialized")

    # 2. Parallel Fetch (Fail-Safe)
    # We gather data concurrently. If Memory/System aggregators fail, 
    # we continue in DEGRADED mode so the Coordinator/Energy services don't crash.
    results = await asyncio.gather(
        state.agent_aggregator.get_system_metrics(),
        state.memory_aggregator.get_memory_stats(),
        state.system_aggregator.get_E_patterns(),
        state.agent_aggregator.get_last_update_time(),
        state.memory_aggregator.get_last_update_time(),
        return_exceptions=True
    )

    # 3. Unpack Safely
    # Agent Metrics are CRITICAL. If this failed, we must error out.
    if isinstance(results[0], Exception) or not results[0]:
        logger.error(f"Agent Aggregator failed: {results[0]}")
        raise HTTPException(status_code=503, detail="Agent Aggregator unavailable")
    
    agent_metrics = results[0]
    
    # Memory/System are OPTIONAL (Degraded Mode).
    mem_stats = results[1] if not isinstance(results[1], Exception) else {}
    e_patterns = results[2] if not isinstance(results[2], Exception) else []
    
    ts_agent = results[3] if not isinstance(results[3], Exception) else 0.0
    ts_memory = results[4] if not isinstance(results[4], Exception) else 0.0

    # Determine Health Status
    # Degraded if memory stats are missing (Coordinator can still route, but Energy calc will be approx)
    is_degraded = isinstance(results[1], Exception) or not mem_stats
    status_label = "degraded" if is_degraded else "healthy"

    # 4. Construct Data Transfer Objects (DTOs)

    # Unified Memory Vector
    # CRITICAL V2: 'ma' (agent_metrics) includes 'specialization_distribution' 
    # which the Coordinator's SignalEnricher needs for Capability Gap calculation.
    unified_memory = MemoryVector(
        ma=agent_metrics,  
        mw=mem_stats.get("mw", {}),
        mlt=mem_stats.get("mlt", {}),
        mfb=mem_stats.get("mfb", {}),
    )

    # System State Vector
    system_state_obj = SystemState(
        h_hgnn=agent_metrics.get("h_hgnn"),  # HGNN centroid from Agent Aggregator
        E_patterns=e_patterns,               # Historical energy patterns
        w_mode=state.w_mode,                 # Current global weight config
    )

    # 5. Construct Metadata & Response
    latency_ms = (time.perf_counter() - start_ts) * 1000.0
    
    # Use the freshest timestamp available
    final_ts = max(ts_agent, ts_memory)

    # Build meta dictionary
    meta = {
        "status": status_label,
        "ts_agent": ts_agent,
        "ts_memory": ts_memory,
        "latency_ms": latency_ms
    }

    # Build metrics dictionary
    metrics = {
        "memory": unified_memory.model_dump(),
        "system": system_state_obj.model_dump(),
    }

    # 6. Return Serialized Response using the new Model
    response_obj = Response.ok(
        metrics=metrics,
        meta=meta
    )
    # Set timestamp for backward compatibility
    response_obj.timestamp = final_ts

    # 7. Set Observability Headers (Using the injected 'response' object)
    response.headers["X-System-Status"] = status_label
    response.headers["X-Processing-Time"] = f"{latency_ms:.3f}ms"
    if is_degraded:
        response.headers["X-Degraded-Reason"] = "memory_aggregator_unavailable"

    # Ensure JSON safety (NumPy -> Python)
    return _numpy_to_python(response_obj.to_dict())


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

    # --- RPC Methods ---

    async def rpc_system_metrics(self):
        """Internal RPC wrapper for the distilled system metrics."""
        return await get_system_metrics(response=None)   # calls FastAPI endpoint

    async def rpc_agent_snapshots(self):
        """Internal RPC wrapper for raw agent snapshot dump."""
        return await get_all_agent_snapshots()  # calls FastAPI endpoint

    async def rpc_update_w_mode(self):
        """Internal RPC wrapper for raw agent w_mode update."""
        return await update_w_mode()  # calls FastAPI endpoint

    async def rpc_health(self):
        """Internal RPC health check."""
        return await health()           # FastAPI health endpoint


# --- Main Entrypoint ---
state_app = StateService.bind()


def build_state_app(args: dict = None):
    return state_app
