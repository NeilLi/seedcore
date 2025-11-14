from __future__ import annotations

import asyncio
import os
from typing import Optional
import numpy as np
from ray import serve  # pyright: ignore[reportMissingImports]
from fastapi import FastAPI, HTTPException  # pyright: ignore[reportMissingImports]

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
# We create the app at the module level so we can attach lifespan events
app = FastAPI(title="SeedCore Proactive State Service", version="2.0.0")

# --- Service State ---
# We hold the service state in a simple class or dict that FastAPI's
# lifespan events can access.
class ServiceState:
    agent_aggregator: Optional[AgentAggregator] = None
    memory_aggregator: Optional[MemoryAggregator] = None
    system_aggregator: Optional[SystemAggregator] = None
    w_mode: np.ndarray = np.array([0.4, 0.3, 0.3], dtype=np.float32)

state = ServiceState()

# --- Lifespan Events (Startup and Shutdown) ---

@app.on_event("startup")
async def startup_event():
    """
    On service startup, initialize and start all proactive aggregators.
    """
    logger.info("🚀 StateService starting up...")
    try:
        # Load w_mode from config
        w_mode_str = os.getenv("SYSTEM_W_MODE", "0.4,0.3,0.3")
        try:
            state.w_mode = np.array([float(w) for w in w_mode_str.split(',')], dtype=np.float32)
        except Exception:
            logger.warning("Using default w_mode [0.4, 0.3, 0.3]")
            state.w_mode = np.array([0.4, 0.3, 0.3], dtype=np.float32)
        logger.info(f"✅ Loaded w_mode: {state.w_mode}")
        
        # Get the OrganismService (v2) router handle using the client helper
        # This provides a clean abstraction while still allowing Ray Serve handle access
        organism_router = get_organism_service_handle()
        logger.info("✅ StateService connected to OrganismService router via client helper.")
        
        # 1. Start Agent Aggregator
        state.agent_aggregator = AgentAggregator(organism_router, poll_interval=2.0)
        await state.agent_aggregator.start()
        
        # 2. Start Memory Aggregator
        state.memory_aggregator = MemoryAggregator(poll_interval=5.0)
        await state.memory_aggregator.start()

        # 3. Start System (E_patterns) Aggregator
        state.system_aggregator = SystemAggregator(poll_interval=5.0)
        await state.system_aggregator.start()
        
        # 4. Wait for all to get first data
        await asyncio.gather(
            state.agent_aggregator.wait_for_first_poll(),
            state.memory_aggregator.wait_for_first_poll(),
            state.system_aggregator.wait_for_first_poll()
        )
        
        logger.info("✅ All proactive aggregators are running and have data. Service is ready.")
        
    except Exception as e:
        logger.error(f"❌ FATAL: Failed to initialize proactive aggregators: {e}", exc_info=True)
        # We re-raise to fail the service startup if it can't initialize.
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """
    On service shutdown, gracefully stop all aggregator loops.
    """
    logger.info("🛑 StateService shutting down...")
    tasks = []
    if state.agent_aggregator:
        tasks.append(state.agent_aggregator.stop())
    if state.memory_aggregator:
        tasks.append(state.memory_aggregator.stop())
    if state.system_aggregator:
        tasks.append(state.system_aggregator.stop())
    
    await asyncio.gather(*tasks)
    logger.info("✅ All aggregators stopped.")

# --- API Endpoints ---

@app.get("/health")
async def health():
    """
    Health check endpoint.
    """
    if (state.agent_aggregator and state.agent_aggregator.is_running() and
        state.memory_aggregator and state.memory_aggregator.is_running() and
        state.system_aggregator and state.system_aggregator.is_running()):
        return {"status": "healthy", "service": "state", "aggregators": "running"}
    
    raise HTTPException(status_code=503, detail="Service is initializing or aggregators have failed.")

@app.get("/system-metrics")
async def get_system_metrics():
    """
    Returns the pre-computed 'helpful parameters' for the Coordinator.
    This is the main O(1) data endpoint.
    """
    if not state.agent_aggregator or not state.memory_aggregator or not state.system_aggregator:
        # This check is for the brief moment *before* startup_event completes
        raise HTTPException(status_code=503, detail="Aggregators not ready.")
        
    # 1. Get agent metrics (includes 'ma' and 'h_hgnn')
    agent_metrics = await state.agent_aggregator.get_system_metrics()
    
    # 2. Get memory manager stats (mw, mlt, mfb)
    mem_stats = await state.memory_aggregator.get_memory_stats()
    
    # 3. Get system stats (E_patterns)
    e_patterns = await state.system_aggregator.get_E_patterns()
    
    # 4. Build the final response objects
    
    # Build MemoryVector (ma + mw + mlt + mfb)
    unified_memory = MemoryVector(
        ma=agent_metrics, # 'ma' stats *are* the agent_metrics
        mw=mem_stats.get("mw", {}),
        mlt=mem_stats.get("mlt", {}),
        mfb=mem_stats.get("mfb", {})
    )
    
    # Build SystemState (h_hgnn + E_patterns + w_mode)
    system_state = SystemState(
        h_hgnn=agent_metrics.get("h_hgnn"), # Get h_hgnn from agent metrics
        E_patterns=e_patterns,
        w_mode=state.w_mode # Get w_mode from config
    )

    return {
        "success": True,
        "metrics": {
            "memory": unified_memory.model_dump(), 
            "system": system_state.model_dump(),
        },
        "timestamp": await state.agent_aggregator.get_last_update_time()
    }

@app.get("/agent-snapshots")
async def get_all_agent_snapshots():
    """
    Returns the full state snapshot for *all* agents.
    
    This is the "cold path" endpoint for debugging or deep-dive analysis.
    The payload can be very large (multi-megabyte) as it includes raw data
    for every agent in the system.
    
    For real-time routing decisions, use /system-metrics instead.
    """
    if not state.agent_aggregator:
        # This check is for the brief moment *before* startup_event completes
        raise HTTPException(status_code=503, detail="Aggregator not ready.")
    
    # Get all agent snapshots (the RAW DATA)
    snapshots = await state.agent_aggregator.get_all_agent_snapshots()
    
    # Convert snapshots to dict format (AgentSnapshot is a dataclass)
    # Convert numpy arrays to lists for JSON serialization
    snapshots_dict = {}
    for agent_id, snapshot in snapshots.items():
        snapshots_dict[agent_id] = {
            "h": snapshot.h.tolist() if hasattr(snapshot.h, "tolist") else list(snapshot.h),
            "p": snapshot.p,
            "c": snapshot.c,
            "mem_util": snapshot.mem_util,
            "lifecycle": snapshot.lifecycle,
            "learned_skills": snapshot.learned_skills,
        }
    
    return {
        "success": True,
        "count": len(snapshots_dict),
        "snapshots": snapshots_dict,  # Note: This payload could be very large
        "timestamp": await state.agent_aggregator.get_last_update_time()
    }

# --- Ray Serve Deployment ---

@serve.deployment(
    name="StateService",
    num_replicas=1,
    max_ongoing_requests=16,
    ray_actor_options={
        "num_cpus": 0.15,
        "memory": 1073741824,  # 1GB
    },
)
@serve.ingress(app)
class StateService:
    """
    Ray Serve wrapper for the proactive FastAPI StateService.
    All logic is handled by the FastAPI app, its lifespan events,
    and its endpoints. This class is just the entrypoint for Ray Serve.
    """
    def __init__(self):
        # The FastAPI app `app` handles all logic.
        pass

# --- Main Entrypoint ---
state_app = StateService.bind()

def build_state_app(args: dict = None):
    """
    Builder function for the state service application.
    """
    return StateService.bind()