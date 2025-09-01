# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# src/seedcore/telemetry/server.py

"""
Simple FastAPI/uvicorn server that exposes simulation controls and telemetry.
"""
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
import os
import numpy as np  # type: ignore
import random
import uuid
import ray
from fastapi import FastAPI, Depends, HTTPException, Request  # type: ignore
from fastapi.responses import JSONResponse
from collections import deque
from typing import List, Dict, Any
import time
from contextlib import asynccontextmanager
# import redis
from ..telemetry.stats import StatsCollector
from ..energy.api import energy_gradient_payload, _ledger
from ..energy.pair_stats import PairStatsTracker
from ..control.fast_loop import fast_loop_select_agent
from ..control.slow_loop import slow_loop_update_roles, slow_loop_update_roles_simple, get_role_performance_metrics
from ..control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from ..organs.base import Organ
from ..organs.registry import OrganRegistry
# REMOVED: Safe import to avoid shadowing issues in organs.__init__.py
# from importlib import import_module

# try:
#     om_mod = import_module("src.seedcore.organs.organism_manager")  # explicit submodule
#     OrganismManager = getattr(om_mod, "OrganismManager")
# except Exception as e:
#     logging.critical("❌ Cannot import OrganismManager: %s", e)
#     OrganismManager = None  # type: ignore

from ..agents.base import Agent
from ..agents import RayAgent
# Conditional import to prevent eager Ray connections
if os.getenv("SEEDCORE_SKIP_EAGER_RAY", "0") != "1":
    from ..agents import Tier0MemoryManager, tier0_manager
else:
    Tier0MemoryManager = None
    tier0_manager = None
from ..memory.system import SharedMemorySystem
from ..memory.adaptive_loop import (
    calculate_dynamic_mem_util, 
    calculate_cost_vq, 
    adaptive_mem_update as new_adaptive_mem_update,
    get_memory_metrics as new_get_memory_metrics,
    estimate_memory_gradient as new_estimate_memory_gradient
)
from ..memory.working_memory import MwManager
from ..memory.long_term_memory import LongTermMemoryManager
from ..memory.holon_fabric import HolonFabric
from ..memory.backends.pgvector_backend import PgVectorStore, Holon
from ..memory.backends.neo4j_graph import Neo4jGraph
from ..memory.consolidation_logic import consolidate_batch
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
from fastapi import Response  # type: ignore
from ..telemetry.metrics import COSTVQ, ENERGY_SLOPE, MEM_WRITES
from ..control.memory.meta_controller import adjust
import asyncio
from ..api.routers.mfb_router import mfb_router
from ..api.routers.salience_router import router as salience_router
from ..api.routers.organism_router import router as organism_router
from ..api.routers.tier0_router import router as tier0_router
from ..api.routers.energy_router import router as energy_router
from ..api.routers.holon_router import router as holon_router
from ..api.routers.control_router import router as control_router
from ..api.routers.tasks_router import router as tasks_router
from ..config.ray_config import get_ray_config
from ..utils.ray_utils import ensure_ray_initialized, is_ray_available
from ..utils.ray_connector import (
    connect, is_connected, get_connection_info, wait_for_ray_ready
)

# NEW: Import DSPy cognitive core
from ..agents.cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)

# Import the new centralized result schema
from ..models.result_schema import (
    create_cognitive_result, create_error_result, TaskResult
)

# Serve modules are now running as separate services
# from ..serve.cognitive_serve import CognitiveCoreClient
from ..energy.weights import EnergyWeights
from ..energy.calculator import energy_and_grad
from ..energy.state import UnifiedState, AgentSnapshot, OrganState, SystemState, MemoryVector
from ..hgnn.pattern_shim import SHIM
from ..energy.energy_persistence import EnergyLedgerStore

# --- Persistent State ---
# Create a single, persistent registry when the server starts.
# This holds the state of our simulation.
print("Initializing persistent simulation state...")
SIMULATION_REGISTRY = OrganRegistry()
PAIR_TRACKER = PairStatsTracker()
MEMORY_SYSTEM = SharedMemorySystem()  # Persistent memory system

# Note: Organ and agent creation is now handled by the Coordinator actor
# during startup. The old manual creation code has been removed.
print("Organism initialization will be handled by the Coordinator actor during startup.")

# Global compression knob for memory control
compression_knob = 0.5

# Global Holon Fabric instance
holon_fabric = None
# --- End Persistent State ---

# Energy weights state (initialized lazily once Tier0 agents are known)
ENERGY_WEIGHTS: EnergyWeights | None = None

# In-memory Tier-1 cache (Mw) for demonstration
mw_cache = {}  # This should be updated by your memory system as needed

# ✅ SOLUTION: Consolidate all startup logic into a single lifespan manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP LOGIC ---
    logging.info("🚀 FastAPI startup sequence initiated.")

    # 1. Connect to Ray ONCE.
    ray_ready = False
    logging.info("   - Step 1: Connecting to Ray cluster...")
    try:
        connect()  # idempotent
        logging.info("   - ✅ Ray connect() returned.")
        connection_info = get_connection_info()
        logging.info(f"   - Ray connection info: {connection_info}")
        
        # Additional Ray diagnostics
        try:
            if ray.is_initialized():
                runtime_context = ray.get_runtime_context()
                logging.info(f"   - Ray runtime context: namespace={getattr(runtime_context, 'namespace', 'unknown')}")
                
                # Try to get cluster resources
                try:
                    cluster_resources = ray.cluster_resources()
                    available_resources = ray.available_resources()
                    logging.info(f"   - Cluster resources: {cluster_resources}")
                    logging.info(f"   - Available resources: {available_resources}")
                except Exception as e:
                    logging.warning(f"   - Could not get cluster resources: {e}")
                
                # Try to list some actors
                try:
                    # Note: list_actors() might not work with Ray client connections
                    logging.info("   - Ray client connection detected")
                except Exception as e:
                    logging.debug(f"   - Actor listing not available: {e}")
            else:
                logging.warning("   - Ray is not initialized after connect() call")
        except Exception as e:
            logging.warning(f"   - Ray diagnostics failed: {e}")
        
        # Verify Ray is fully connected and ready
        if is_ray_available():
            ray_ready = True
            logging.info("   - ✅ Ray connection verified and ready.")
            
            # Initialize Janitor actor for cluster maintenance
            try:
                from ..maintenance.janitor import Janitor
                try:
                    # Use explicit namespace for cross-namespace actor lookup
                    namespace = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
                    janitor = ray.get_actor("seedcore_janitor", namespace=namespace)
                    logging.info("   - ✅ Janitor actor already exists")
                except Exception:
                    janitor = Janitor.options(name="seedcore_janitor", lifetime="detached", num_cpus=0).remote()
                    logging.info("   - ✅ Janitor actor created successfully")
                app.state.janitor = janitor
            except Exception as e:
                logging.warning(f"   - ⚠️ Failed to initialize Janitor actor: {e}")
                app.state.janitor = None
        else:
            logging.info("   - ⏳ Waiting up to 5s for Ray to become ready...")
            if wait_for_ray_ready(max_wait_seconds=5):
                ray_ready = True
                logging.info("   - ✅ Ray connection verified after waiting.")
            if not ray_ready:
                logging.warning("   - ⚠️ Ray connection verification failed, but continuing...")
    except Exception as e:
        logging.critical(f"   - ❌ Ray connection failed: {e}. Some features will be disabled.")

    # 2. REMOVED: Initialize OrganismManager locally - this is now handled by the Coordinator actor
    # The API should not bootstrap or hold a live OrganismManager
    logging.info("   - Step 2: Skipping local OrganismManager initialization (handled by Coordinator actor)")
    
    # 3. Initialize memory system
    logging.info("   - Step 3: Initializing Memory System...")
    try:
        global MEMORY_SYSTEM
        MEMORY_SYSTEM = SharedMemorySystem()
        app.state.mem = MEMORY_SYSTEM
        logging.info("   - ✅ Memory system initialized")
    except Exception as e:
        logging.error(f"   - ❌ Failed to initialize memory system: {e}")
    
    # 4. Initialize Holon Fabric
    logging.info("   - Step 4: Initializing Holon Fabric...")
    try:
        await build_memory()
        logging.info("   - ✅ Holon Fabric initialized")
    except Exception as e:
        logging.error(f"   - ❌ Failed to initialize Holon Fabric: {e}")
    
    # 5. Start consolidator loop (depends on Ray for some operations)
    logging.info("   - Step 5: Starting Consolidator Loop...")
    try:
        asyncio.create_task(start_consolidator())
        logging.info("   - ✅ Consolidator loop started")
    except Exception as e:
        logging.error(f"   - ❌ Failed to start consolidator loop: {e}")
    
    # 6. Initialize energy ledger
    logging.info("   - Step 6: Initializing Energy Ledger...")
    try:
        store = EnergyLedgerStore({"enabled": True})
        backend = (store.cfg.get("backend") or "").lower()
        if backend in ("fs", "s3"):
            logging.info(f"   - Rebuilding energy balances from ledger (backend={backend})")
            store.rebuild_balances()
        logging.info("   - ✅ Energy ledger initialized")
    except Exception as e:
        logging.error(f"   - ❌ Failed to initialize energy ledger: {e}")
    
    # 7. Initialize ENERGY_WEIGHTS (depends on Ray for agent management)
    if ray_ready:
        logging.info("   - Step 7: Initializing Energy Weights...")
        try:
            global ENERGY_WEIGHTS
            from ..agents.tier0_manager import Tier0MemoryManager
            tier0_mgr = Tier0MemoryManager()
            agent_ids = tier0_mgr.list_agents()
            if agent_ids and ENERGY_WEIGHTS is None:
                n = len(agent_ids)
                # Start with zeros; learn from PairStats
                ENERGY_WEIGHTS = EnergyWeights(
                    W_pair=np.zeros((n, n), dtype=np.float32),
                    W_hyper=np.zeros((0,), dtype=np.float32),
                    alpha_entropy=0.1,
                    lambda_reg=0.01,
                    beta_mem=0.05,
                )
                ENERGY_WEIGHTS.project()
                app.state.energy_weights = ENERGY_WEIGHTS
            logging.info("   - ✅ Energy weights initialized")
        except Exception as e:
            logging.error(f"   - ❌ Failed to initialize ENERGY_WEIGHTS: {e}")
    else:
        logging.warning("   - ⚠️ Skipping Energy Weights initialization due to Ray connection issues")
    
    # 8. Start metrics integration
    logging.info("   - Step 8: Starting Metrics Integration...")
    try:
        from .metrics_integration import start_metrics_integration
        base_url = os.getenv("SEEDCORE_API_ADDRESS", "127.0.0.1:8002")
        
        # Avoid hairpin to our own Service inside the same Pod
        svc_names = {
            os.getenv("SERVICE_NAME", "seedcore-api"),
            f'{os.getenv("SERVICE_NAME", "seedcore-api")}.{os.getenv("NAMESPACE", "default")}.svc',
        }
        if any(str(base_url).startswith(name) for name in svc_names):
            base_url = "127.0.0.1:8002"
        
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        asyncio.create_task(start_metrics_integration(
            base_url=base_url,
            update_interval=30,
            app_state=app.state  # Pass app state for local access
        ))
        logging.info("   - ✅ Metrics integration started")
    except Exception as e:
        logging.error(f"   - ❌ Failed to start metrics integration: {e}")
    
    # 9. Sync counters
    logging.info("   - Step 9: Syncing Counters...")
    try:
        await sync_counters()
        logging.info("   - ✅ Counters synced")
    except Exception as e:
        logging.error(f"   - ❌ Failed to sync counters: {e}")
    
    logging.info("✅ FastAPI application startup complete.")
    
    # Keep trying in the background until we're fully ready.
    async def _runtime_bootstrapper():
        while True:
            try:
                # 1) Connect to Ray if needed
                if not is_ray_available():
                    connect()  # idempotent
                    if not wait_for_ray_ready(max_wait_seconds=10):
                        await asyncio.sleep(3)
                        continue

                # 2) REMOVED: Initialize OrganismManager locally - this is now handled by the Coordinator actor
                # The API should not bootstrap or hold a live OrganismManager
                logging.info("✅ Runtime bootstrap complete (Ray connection established).")
                return
                
            except Exception as e:
                logging.warning(f"Runtime bootstrap attempt failed: {e}, retrying in 3s...")
                await asyncio.sleep(3)

    asyncio.create_task(_runtime_bootstrapper())
    
    yield
    
    # --- SHUTDOWN LOGIC ---
    logging.info("🛑 FastAPI shutdown sequence initiated.")
    
    # Cleanup memory connections
    try:
        await cleanup_memory()
        logging.info("   - ✅ Memory cleanup completed")
    except Exception as e:
        logging.error(f"   - ❌ Memory cleanup failed: {e}")
    
    # Shutdown Ray
    if ray.is_initialized():
        ray.shutdown()
        logging.info("   - ✅ Ray shutdown completed")
    
    logging.info("✅ FastAPI shutdown complete.")

# Create FastAPI app with lifespan manager
app = FastAPI(lifespan=lifespan)

# Include all routers
app.include_router(mfb_router)
app.include_router(salience_router)
app.include_router(organism_router)
app.include_router(tier0_router)
app.include_router(energy_router)
app.include_router(holon_router)
app.include_router(control_router)
app.include_router(tasks_router)
from ..api.routers.ocps_router import router as ocps_router
from ..api.routers.dspy_router import router as dspy_router
app.include_router(ocps_router)
app.include_router(dspy_router)

# --- Readiness Probe ---
def _readiness_check():
    reasons = []

    # 1) Ray must be connected
    if not is_ray_available():
        reasons.append("ray:not_connected")

    # 2) REMOVED: OrganismManager check - this is now handled by the Coordinator actor
    # The API should not bootstrap or hold a live OrganismManager

    return reasons

@app.get("/readyz", include_in_schema=False)
async def readyz():
    # Try to self-heal readiness quickly
    if not is_ray_available():
        try:
            # 1) Connect to Ray if needed
            if not is_ray_available():
                connect()  # idempotent
                if not wait_for_ray_ready(max_wait_seconds=5):  # Shorter timeout for /readyz
                    pass  # Continue with status check
        except Exception as e:
            logging.warning(f"Self-heal attempt in /readyz failed: {e}")

    ray_ok = is_ray_available()
    # REMOVED: organism_ok check - this is now handled by the Coordinator actor
    status = 200 if ray_ok else 503
    return JSONResponse(
        {"ray_ok": ray_ok, "organism_ok": "coordinator_managed"}, 
        status_code=status
    )

# Optional: HEAD variant (saves bandwidth/log noise for k8s probes)
@app.head("/readyz", include_in_schema=False)
async def readyz_head():
    reasons = _readiness_check()
    return JSONResponse(status_code=200 if not reasons else 503, content=None)

# --- NEW: OrganismManager Serve Deployment Proxy Functions ---
async def get_organism_manager_handle():
    """Get the OrganismManager Serve deployment handle."""
    try:
        from ray import serve
        coord = serve.get_deployment_handle("OrganismManager", app_name="organism")
        return coord
    except Exception as e:
        logging.warning(f"Could not get OrganismManager Serve deployment: {e}")
        return None

async def submit_task_to_coordinator(task: dict):
    """Submit a task to the OrganismManager Serve deployment for processing."""
    coord = await get_organism_manager_handle()
    if not coord:
        raise HTTPException(status_code=503, detail="OrganismManager Serve deployment not available")
    
    try:
        # The OrganismManager.handle_incoming_task() method expects the task dict and returns the result directly
        result = await coord.handle_incoming_task.remote(task)
        return result
    except Exception as e:
        logging.error(f"Task submission to OrganismManager failed: {e}")
        raise HTTPException(status_code=500, detail=f"Task processing failed: {str(e)}")

async def check_coordinator_health():
    """Check if the OrganismManager Serve deployment is alive and responsive."""
    try:
        coord = await get_organism_manager_handle()
        if not coord:
            return {"status": "degraded", "coordinator": "unavailable"}
        
        # Test OrganismManager with a health check
        health_result = await coord.health.remote()
        if health_result.get("status") == "healthy":
            return {"status": "ok", "coordinator": "healthy", "organism_initialized": health_result.get("organism_initialized", False)}
        else:
            return {"status": "degraded", "coordinator": "unresponsive"}
    except Exception as e:
        logging.warning(f"OrganismManager health check failed: {e}")
        return {"status": "degraded", "coordinator": "error"}

# --- Unified State Builder ---
def _get_tier0_manager():
    """Safely get tier0_manager, importing it if needed."""
    if tier0_manager is not None:
        return tier0_manager
    
    # Import it now if it wasn't imported earlier
    try:
        from ..agents import tier0_manager as tm
        return tm
    except Exception:
        return None

def _get_ma_stats() -> dict:
    try:
        if tier0_manager is None:
            return {"count": 0, "error": "tier0_manager_not_available"}
        return {"count": len(tier0_manager.list_agents())}
    except Exception:
        return {}


def _get_mw_stats() -> dict:
    try:
        return app.state.stats.mw_stats()
    except Exception:
        return {}


def _get_mlt_stats() -> dict:
    try:
        return app.state.mem.get_memory_stats() if hasattr(app.state, "mem") else {}
    except Exception:
        return {}


def _get_mfb_stats() -> dict:
    try:
        return {"incidents": 0}
    except Exception:
        return {}


def build_unified_state(agent_ids: list[str]) -> UnifiedState:
    tm = _get_tier0_manager()
    if tm is None:
        # Return empty state if tier0_manager is not available
        return UnifiedState(
            agents={}, 
            organs={}, 
            system=SystemState(E_patterns=np.array([])), 
            memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
        )
    
    agents: dict[str, AgentSnapshot] = {}
    for agent_id in agent_ids:
        ag = tm.get_agent(agent_id)
        if not ag:
            continue
        hb = ray.get(ag.get_heartbeat.remote())
        agents[agent_id] = AgentSnapshot(
            h=np.array(hb.get('state_embedding_h') or [], dtype=np.float32),
            p=hb.get('role_probs', {}),
            c=float(hb.get('performance_metrics', {}).get('capability_score_c', 0.0)),
            mem_util=float(hb.get('performance_metrics', {}).get('mem_util', 0.0)),
            lifecycle=str(hb.get('lifecycle', {}).get('state', 'Employed')),
        )

    organs: dict[str, OrganState] = {}
    E_vec, _emap = SHIM.get_E_patterns()
    system = SystemState(E_patterns=E_vec)
    memory = MemoryVector(
        ma=_get_ma_stats(),
        mw=_get_mw_stats(),
        mlt=_get_mlt_stats(),
        mfb=_get_mfb_stats(),
    )
    return UnifiedState(agents=agents, organs=organs, system=system, memory=memory)

class _Ctl:
    tau: float = 0.3
    gamma: float = 2.0
    kappa: float = 0.5  # TD-priority knob
app.state.controller = _Ctl()

# --- Energy Meta/Audit State ---
# Rolling counters for router fast-path vs escalation (for contractivity audit)
router_fast_hits: int = 0
router_escalations: int = 0
router_latency_ms_window: deque = deque(maxlen=1000)

# DSPy/LLM token accounting (optional)
tokens_in_total: int = 0
tokens_out_total: int = 0
token_cost_total: float = 0.0

# Guard-rail and weighting knobs (overridable via env)
BETA_ROUTER: float = float(os.getenv("SEEDCORE_BETA_ROUTER", "1.0"))
BETA_META: float = float(os.getenv("SEEDCORE_BETA_META", "0.80"))
RHO_CLIP: float = float(os.getenv("SEEDCORE_RHO_CLIP", "0.95"))
# Token cost term is OFF by default; can enable later safely
BETA_TOK: float = float(os.getenv("SEEDCORE_BETA_TOK", "0.0"))
PROMOTION_LTOT_CAP: float = float(os.getenv("SEEDCORE_PROMOTION_LTOT_CAP", "0.98"))



async def build_memory():
    """Initialize the Holon Fabric on server startup"""
    global holon_fabric
    import os
    
    # Get connection details from environment variables
    pg_dsn = os.getenv("PG_DSN")
    neo4j_uri = os.getenv("NEO4J_URI") or os.getenv("NEO4J_BOLT_URL")
    neo4j_user = os.getenv("NEO4J_USER")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    
    # Validate required environment variables
    optional_backends = str(os.getenv("SEEDCORE_OPTIONAL_BACKENDS", "false")).lower() in ("1", "true", "yes")
    missing_vars: list[str] = []
    if not pg_dsn:
        missing_vars.append("PG_DSN")
    if not neo4j_uri:
        missing_vars.append("NEO4J_URI")
    if not neo4j_user:
        missing_vars.append("NEO4J_USER")
    if not neo4j_password:
        missing_vars.append("NEO4J_PASSWORD")

    if missing_vars:
        if optional_backends:
            logging.warning("Optional backends enabled; skipping Holon Fabric initialization due to missing env vars: %s", ", ".join(missing_vars))
            return
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")
    
    # Initialize backends
    vec_store = PgVectorStore(pg_dsn)
    graph = Neo4jGraph(neo4j_uri, (neo4j_user, neo4j_password))
    
    # Create Holon Fabric
    holon_fabric = HolonFabric(vec_store, graph)
    app.state.mem = holon_fabric
    
    # Attach StatsCollector to app state
    app.state.stats = StatsCollector(
        pg_dsn=pg_dsn,
        neo_uri=neo4j_uri,
        neo_auth=(neo4j_user, neo4j_password),
        mw_ref=mw_cache,
    )
    
    print(f"Holon Fabric initialized with PG_DSN={pg_dsn}, NEO4J_URI={neo4j_uri}")

async def start_consolidator():
    import asyncio, time
    async def loop():
        tick = 0
        while True:
            logging.warning("⚙ consolidator tick at %.0f", time.time())
            try:
                n = await consolidate_batch(
                    app.state.mem,
                    app.state.stats.mw,
                    tau=app.state.controller.tau,
                    batch=128,
                    kappa=app.state.controller.kappa,
                )
                logging.info("✓ consolidated %d", n)
                tick += 1
                if tick % 10 == 0:
                    await adjust(app.state.controller, ENERGY_SLOPE._value.get())
            except Exception:
                logging.exception("consolidator crashed")
            await asyncio.sleep(app.state.controller.gamma)
    print("⇢ CONSOLIDATOR TASK SCHEDULED")
    asyncio.create_task(loop())

async def sync_counters():
    import asyncpg  # type: ignore
    pg_dsn = os.getenv("PG_DSN")
    if not pg_dsn:
        logging.warning("PG_DSN not configured, skipping counter sync")
        return
    c = await asyncpg.connect(pg_dsn)
    try:
        total, = await c.fetchrow("SELECT COUNT(*) FROM holons;")
        MEM_WRITES.labels(tier="Mlt").inc(total)
        avg_cost, = await c.fetchrow("SELECT AVG((meta->>'stored_bytes')::float / GREATEST((meta->>'raw_bytes')::int,1)) FROM holons")
        from ..telemetry.metrics import COSTVQ
        COSTVQ.set(avg_cost or 0)
    finally:
        await c.close()



async def cleanup_memory():
    """Cleanup connections on server shutdown"""
    global holon_fabric
    if holon_fabric and holon_fabric.graph:
        close_method = getattr(holon_fabric.graph, "close", None)
        if callable(close_method):
            holon_fabric.graph.close()

def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    
    return dot_product / (norm_v1 * norm_v2)

# Energy logging storage for XGBoost integration
energy_logs = []

@app.post('/energy/log')
async def log_energy_event(event: dict):
    """
    Log energy events from XGBoost predictions and other sources.
    
    This endpoint integrates with the Energy system to track:
    - XGBoost model predictions and their impact
    - Utility organ performance metrics
    - Model refresh events and success rates
    
    The logged events influence the Unified Energy Function (E_core)
    by updating pair, mem, and reg energy terms.
    """
    try:
        # Add timestamp if not provided
        if 'ts' not in event:
            event['ts'] = time.time()
        
        # Store the event
        energy_logs.append(event)
        
        # Limit log size to prevent memory issues
        if len(energy_logs) > 10000:
            energy_logs.pop(0)
        
        # Update energy/meta based on event type
        metric = event.get('metric')
        organ = event.get('organ')

        # 1) Existing XGBoost predicted_risk → pair/mem/reg adjustments
        if organ == 'utility' and metric == 'predicted_risk':
            success = bool(event.get('success', False))
            # Successful prediction reduces pair energy (better collaboration)
            _ledger.add_pair_delta(-0.1 if success else 0.1)
            # Memory pressure when model is loaded/used
            if event.get('model_path'):
                _ledger.add_mem_delta(memory_usage=0.1, compression_ratio=0.5)
            # Complexity tax when prediction volume is large
            if event.get('prediction_count', 0) > 100:
                _ledger.add_reg_delta(regularization_strength=0.05, model_complexity=1.0)

        # 2) Core flow health: router_hit / escalation
        elif metric in ("router_hit", "escalation"):
            global router_fast_hits, router_escalations
            latency_ms = float(event.get('latency_ms', 0))
            router_latency_ms_window.append(latency_ms)
            if metric == 'router_hit':
                router_fast_hits += 1
                # Reward fast-path with tiny negative regularization delta
                _ledger.add_reg_delta(regularization_strength=0.01, model_complexity=-0.5)
            else:
                router_escalations += 1
                # Penalize escalation with small positive regularization delta
                _ledger.add_reg_delta(regularization_strength=0.01, model_complexity=0.5)

        # 3) HGNN outcomes: hyperedge_apply
        elif metric == 'hyperedge_apply':
            success = bool(event.get('success', False))
            novelty = float(event.get('novelty', 0.0))
            # If success, reduce hyper energy slightly; else increase
            complexity = novelty
            precision = 1.0 if success else 0.5
            _ledger.add_hyper_delta(complexity=complexity, precision=precision)

        # 4) DSPy/LLM costs
        elif metric in ("llm_call", "dspy_step"):
            global tokens_in_total, tokens_out_total, token_cost_total
            ti = int(event.get('tokens_in', 0))
            to = int(event.get('tokens_out', 0))
            latency_ms = float(event.get('latency_ms', 0))
            tokens_in_total += ti
            tokens_out_total += to
            token_cost_total += BETA_TOK * (ti + to)
            # Map to reg as complexity; tiny token-cost if enabled
            reg_base = 0.001 * (ti + to) + 0.0005 * latency_ms
            if BETA_TOK > 0:
                reg_base += BETA_TOK * (ti + to)
            _ledger.add_reg_delta(regularization_strength=reg_base, model_complexity=1.0)

        # 5) Memory/CostVQ updates
        elif metric == 'memory_op':
            # event fields: tier, cost_vq, compressed(bool), r (compression factor)
            cost_vq = float(event.get('cost_vq', 0.0))
            compressed = bool(event.get('compressed', False))
            r = float(event.get('r', 1.0))
            # Update COSTVQ gauge if available
            try:
                from ..telemetry.metrics import COSTVQ
                COSTVQ.set(cost_vq)
            except Exception:
                pass
            # Map to mem term: usage minus compression effectiveness
            compression_ratio = 1.0 / max(r, 1e-6) if compressed else 0.0
            _ledger.add_mem_delta(memory_usage=cost_vq, compression_ratio=compression_ratio)

        # 6) Pair outcomes update (agents/organs)
        elif metric == 'pair_outcome':
            success = bool(event.get('success', False))
            similarity = float(event.get('similarity', 0.5))
            w_effective = float(event.get('w_effective', 0.1))
            # Lower energy when success is True and similarity high
            delta = -w_effective * (similarity if success else (1.0 - similarity))
            _ledger.add_pair_delta(delta)
            # Also update PairStats for future full recompute
            try:
                agents = event.get('agents') or []
                if isinstance(agents, list) and len(agents) == 2:
                    PAIR_TRACKER.update_on_task_complete(agents[0], agents[1], success)
            except Exception:
                pass

        # 7) Flywheel results
        elif metric == 'flywheel_result':
            delta_E = float(event.get('delta_E', 0.0))
            beta_mem_new = event.get('beta_mem_new')
            # Reflect delta_E into reg minimally (telemetry)
            _ledger.add_reg_delta(regularization_strength=delta_E, model_complexity=0.0)
            if beta_mem_new is not None:
                try:
                    # Adjust runtime beta_mem knob if present on ledger
                    _ledger.beta_mem = float(beta_mem_new)
                except Exception:
                    pass
        
        logger.info(f"Energy event logged: {event}")
        return {"status": "success", "message": "Energy event logged", "event_count": len(energy_logs)}
        
    except Exception as e:
        logger.error(f"Failed to log energy event: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to log energy event: {str(e)}")


@app.get('/energy/logs')
async def get_energy_logs(limit: int = 100):
    """
    Retrieve energy logs for monitoring and analysis.
    
    Args:
        limit: Maximum number of logs to return (default: 100)
    
    Returns:
        List of energy events with timestamps and metadata
    """
    try:
        # Return the most recent logs
        recent_logs = energy_logs[-limit:] if len(energy_logs) > limit else energy_logs
        
        return {
            "logs": recent_logs,
            "total_count": len(energy_logs),
            "returned_count": len(recent_logs)
        }
        
    except Exception as e:
        logger.error(f"Failed to retrieve energy logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve energy logs: {str(e)}")


@app.get('/energy/gradient')
async def energy_gradient():
    """
    Enhanced energy gradient endpoint that provides real energy data from the Energy Model Foundation.
    Now with Redis caching for improved performance.
    """
    try:
        from ..energy.calculator import energy_gradient_payload, calculate_energy
        from ..energy.ledger import EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        from ..caching.redis_cache import get_redis_cache, energy_gradient_cache_key
        import ray  # type: ignore

        # Try to get from cache first
        cache = get_redis_cache()
        cache_key = energy_gradient_cache_key()
        
        if cache.ping():
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for energy gradient: {cache_key}")
                return cached_result
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        # Get Tier0 manager instance (create if needed)
        tier0_manager = Tier0MemoryManager()
        
        # Get all available agents
        agent_ids = tier0_manager.list_agents()
        
        if not agent_ids:
            # If no agents exist, create some default agents for demonstration
            agent_configs = [
                {"agent_id": "explorer_1", "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1}},
                {"agent_id": "specialist_1", "role_probs": {"E": 0.1, "S": 0.8, "O": 0.1}},
                {"agent_id": "balanced_1", "role_probs": {"E": 0.4, "S": 0.4, "O": 0.2}}
            ]
            tier0_manager.create_agents_batch(agent_configs)
            agent_ids = tier0_manager.list_agents()
        
        # Collect current agent data
        agents = [tier0_manager.get_agent(agent_id) for agent_id in agent_ids if tier0_manager.get_agent(agent_id)]
        
        # Get memory system stats
        memory_stats = {
            'cost_vq': COSTVQ._value.get(),
            'bytes_used': MEMORY_SYSTEM.get_memory_stats().get('bytes_used', 0),
            'hit_count': MEMORY_SYSTEM.get_memory_stats().get('hit_count', 0),
            'compression_ratio': compression_knob,
            # extra fields used by cost_vq() mapping
            'r_effective': max(1.0, 1.0 / max(compression_knob, 1e-6)),
            'p_compress': 1.0 if compression_knob > 0 else 0.0,
        }
        
        # Calculate real energy using the Energy Model Foundation
        if agents:
            # Create state for energy calculation
            state = {
                'agents': agents,
                'memory_stats': memory_stats,
                'pair_stats': PAIR_TRACKER.get_all_stats(),
                'alpha': 0.1,
                'lambda_reg': 0.01,
                'beta_mem': 0.05
            }
            
            # Calculate energy terms
            energy_terms = calculate_energy(state)
            
            # Create energy ledger with real data
            ledger = EnergyLedger()
            # Update ledger with energy terms (terms is a read-only property)
            ledger.pair = energy_terms.pair
            ledger.hyper = energy_terms.hyper
            ledger.entropy = energy_terms.entropy
            ledger.reg = energy_terms.reg
            ledger.mem = energy_terms.mem
            
            # Add some pair stats for demonstration
            if len(agents) >= 2:
                # Simulate some pair interactions
                for i in range(len(agents)):
                    for j in range(i + 1, min(i + 2, len(agents))):
                        pair_key = tuple(sorted([agent_ids[i], agent_ids[j]]))
                        ledger.pair_stats[pair_key] = {
                            'w': 0.7,  # Simulated collaboration weight
                            'sim': 0.6  # Simulated similarity
                        }
            
            # Update W_pair from tracker with current agent ordering
            try:
                global ENERGY_WEIGHTS
                if ENERGY_WEIGHTS is None or ENERGY_WEIGHTS.W_pair.shape[0] != len(agent_ids):
                    ENERGY_WEIGHTS = EnergyWeights(
                        W_pair=np.zeros((len(agent_ids), len(agent_ids)), dtype=np.float32),
                        W_hyper=np.zeros((0,), dtype=np.float32),
                        alpha_entropy=0.1,
                        lambda_reg=0.01,
                        beta_mem=0.05,
                    )
                    app.state.energy_weights = ENERGY_WEIGHTS
                # Blend tracker stats into weights
                PAIR_TRACKER.to_weights(tuple(agent_ids), ENERGY_WEIGHTS, ema=0.5)
            except Exception:
                logger.exception("Failed to update ENERGY_WEIGHTS from PAIR_TRACKER")

            # Build state for unified energy and gradient
            try:
                # Agent embeddings and role probabilities
                H = []
                P = []
                for agent_id in agent_ids:
                    ag = tier0_manager.get_agent(agent_id)
                    if ag:
                        hb = ray.get(ag.get_heartbeat.remote())
                        P.append([
                            hb.get('role_probs', {}).get('E', 0.0),
                            hb.get('role_probs', {}).get('S', 0.0),
                            hb.get('role_probs', {}).get('O', 0.0),
                        ])
                        H.append(ray.get(ag.get_state_embedding.remote()))
                H = np.array(H, dtype=np.float32) if H else np.zeros((0, 0), dtype=np.float32)
                P = np.array(P, dtype=np.float32) if P else np.zeros((0, 3), dtype=np.float32)
                s_norm = float(np.linalg.norm(H))
                # HGNN-pattern shim vector for hyper term (bounded [0,1])
                E_vec, _ = SHIM.get_E_patterns()
                # Ensure hyper weights match current E_vec length
                try:
                    if ENERGY_WEIGHTS is not None:
                        if ENERGY_WEIGHTS.W_hyper.shape[0] != int(getattr(E_vec, "shape", [0])[0]):
                            # Default to ones to enable contribution; clip via project()
                            ENERGY_WEIGHTS.W_hyper = np.ones((E_vec.shape[0],), dtype=np.float32)
                            ENERGY_WEIGHTS.project()
                except Exception:
                    pass
                state = {"h_agents": H, "P_roles": P, "hyper_sel": E_vec, "s_norm": s_norm}
                breakdown, grad = energy_and_grad(state, ENERGY_WEIGHTS, memory_stats)
            except Exception:
                logger.exception("Failed computing unified energy and gradients")
                breakdown, grad = {"pair": 0.0, "hyper": 0.0, "entropy": 0.0, "reg": 0.0, "mem": memory_stats['cost_vq'], "total": memory_stats['cost_vq']}, {"dE/dmem": 0.0}

            # Get energy gradient payload and augment with unified breakdown/grad and L_tot
            energy_payload = energy_gradient_payload(ledger)
            energy_payload.update({
                "breakdown": {k: float(v) for k, v in breakdown.items()},
                "grad": {k: (float(v) if isinstance(v, (int, float)) else None) for k, v in grad.items()},
            })
            
            # Add additional real-time metrics
            energy_payload.update({
                "real_time_metrics": {
                    "active_agents": len(agents),
                    "total_agents": len(agent_ids),
                    "memory_utilization": memory_stats['bytes_used'] / 1024,  # KB
                    "compression_knob": compression_knob,
                    "last_energy_update": time.time()
                },
                "agent_summaries": [
                    {
                        "agent_id": agent_id,
                        "capability": ray.get(tier0_manager.get_agent(agent_id).get_heartbeat.remote()).get('capability_score', 0.5),
                        "mem_util": ray.get(tier0_manager.get_agent(agent_id).get_heartbeat.remote()).get('mem_util', 0.0),
                        "role_probs": ray.get(tier0_manager.get_agent(agent_id).get_heartbeat.remote()).get('role_probs', {})
                    }
                    for agent_id in agent_ids[:5]  # Limit to first 5 agents
                ]
            })
            
            # Cache the result for 30 seconds
            if cache.ping():
                cache.set(cache_key, energy_payload, expire=30)
                logger.debug(f"Cached energy gradient result: {cache_key}")
            
            return energy_payload
            
        else:
            # Fallback to basic energy calculation
            ledger = EnergyLedger()
            fallback_payload = energy_gradient_payload(ledger)
            
            # Cache the fallback result for 30 seconds
            if cache.ping():
                cache.set(cache_key, fallback_payload, expire=30)
                logger.debug(f"Cached fallback energy gradient result: {cache_key}")
            
            return fallback_payload
            
    except Exception as e:
        logger.error(f"Error calculating energy gradient: {e}")
        # Return enhanced error response with fallback data
        error_payload = {
            "error": str(e),
            "ts": time.time(),
            "E_terms": {
                "pair": 0.0,
                "hyper": 0.0,
                "entropy": 0.0,
                "reg": 0.0,
                "mem": COSTVQ._value.get(),
                "total": COSTVQ._value.get()
            },
            "deltaE_last": ENERGY_SLOPE._value.get(),
            "pair_stats_count": 0,
            "hyper_stats_count": 0,
            "role_entropy_count": 0,
            "mem_stats_count": 0,
            "real_time_metrics": {
                "active_agents": 0,
                "total_agents": 0,
                "memory_utilization": 0,
                "compression_knob": compression_knob,
                "last_energy_update": time.time()
            }
        }
        
        # Cache the error response for a shorter time (10 seconds)
        if cache.ping():
            cache.set(cache_key, error_payload, expire=10)
            logger.debug(f"Cached error energy gradient result: {cache_key}")
        
        return error_payload


@app.get("/energy/meta")
def energy_meta():
    """Runtime contractivity audit and guard-rails for promotions.
    Returns L_tot components and current cap.
    """
    try:
        # p_fast / p_esc
        total_router = (router_fast_hits + router_escalations) or 1
        p_fast = router_fast_hits / total_router
        p_esc = router_escalations / total_router

        # Components
        beta_router = BETA_ROUTER
        beta_meta = BETA_META
        rho = RHO_CLIP
        beta_mem = float(getattr(_ledger, 'beta_mem', 0.95)) if hasattr(_ledger, 'beta_mem') else 0.95

        # Composite Lipschitz-like factor (heuristic composition)
        L_tot = min(0.999, beta_router * (p_fast + p_esc) * beta_meta * rho * beta_mem)

        return {
            "p_fast": p_fast,
            "p_esc": p_esc,
            "beta_router": beta_router,
            "beta_meta": beta_meta,
            "rho": rho,
            "beta_mem": beta_mem,
            "L_tot": L_tot,
            "cap": PROMOTION_LTOT_CAP,
            "ok_for_promotion": L_tot < PROMOTION_LTOT_CAP
        }
    except Exception as e:
        logger.error(f"Energy meta computation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/energy/calibrate")
def energy_calibrate():
    """Energy calibration endpoint that runs synthetic tasks and returns calibration results."""
    try:
        from ..energy.calculator import calculate_energy
        from ..energy.ledger import EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        from ..caching.redis_cache import get_redis_cache, energy_calibrate_cache_key
        import ray  # type: ignore
        import numpy as np  # type: ignore
        
        # Try to get from cache first
        cache = get_redis_cache()
        cache_key = energy_calibrate_cache_key()
        
        if cache.ping():
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for energy calibrate: {cache_key}")
                return cached_result
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        # Get Tier0 manager
        tier0_manager = Tier0MemoryManager()
        agent_ids = tier0_manager.list_agents()
        
        # Create calibration agents if needed
        if len(agent_ids) < 3:
            agent_configs = [
                {"agent_id": "cal_explorer", "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1}},
                {"agent_id": "cal_specialist", "role_probs": {"E": 0.1, "S": 0.8, "O": 0.1}},
                {"agent_id": "cal_balanced", "role_probs": {"E": 0.4, "S": 0.4, "O": 0.2}}
            ]
            tier0_manager.create_agents_batch(agent_configs)
            agent_ids = tier0_manager.list_agents()
        
        # Get agents
        agents = [tier0_manager.get_agent(agent_id) for agent_id in agent_ids if tier0_manager.get_agent(agent_id)]
        
        # Run calibration tasks
        calibration_results = []
        energy_history = []
        
        for i in range(10):  # Run 10 calibration tasks
            # Create synthetic task
            task = {
                "task_id": f"calibration_task_{i}",
                "type": np.random.choice(["optimization", "exploration", "analysis"]),
                "complexity": np.random.uniform(0.1, 0.9),
                "description": f"Calibration task {i}"
            }
            
            # Execute task with energy-aware selection
            result = tier0_manager.execute_task_on_best_agent(task)
            
            if result and result.get('success'):
                # Update energy ledger
                ledger = EnergyLedger()
                
                # Simulate pair success event
                if len(agents) >= 2:
                    pair_event = {
                        'type': 'pair_success',
                        'agents': [result['agent_id'], f"task_{i}"],
                        'success': result['success'],
                        'sim': np.random.uniform(0.5, 0.9)
                    }
                    
                    from ..energy.calculator import on_pair_success
                    on_pair_success(pair_event, ledger)
                
                # Record energy
                current_energy = ledger.get_total()
                energy_history.append({
                    'task_num': i + 1,
                    'energy': current_energy,
                    'timestamp': time.time()
                })
                
                calibration_results.append({
                    'task_id': task['task_id'],
                    'agent_id': result.get('agent_id'),
                    'success': result.get('success'),
                    'energy': current_energy
                })
        
        # Calculate calibration metrics
        if energy_history:
            energies = [e['energy'] for e in energy_history]
            energy_trend = energies[-1] - energies[0] if len(energies) > 1 else 0.0
            
            calibration_metrics = {
                'total_tasks': len(calibration_results),
                'successful_tasks': len([r for r in calibration_results if r.get('success')]),
                'final_energy': energies[-1] if energies else 0.0,
                'energy_trend': energy_trend,
                'energy_range': {'min': min(energies), 'max': max(energies)} if energies else {'min': 0.0, 'max': 0.0},
                'trend_direction': 'decreasing' if energy_trend < 0 else 'increasing',
                'calibration_quality': 'good' if energy_trend < 0 else 'needs_adjustment'
            }
        else:
            calibration_metrics = {
                'total_tasks': 0,
                'successful_tasks': 0,
                'final_energy': 0.0,
                'energy_trend': 0.0,
                'energy_range': {'min': 0.0, 'max': 0.0},
                'trend_direction': 'unknown',
                'calibration_quality': 'insufficient_data'
            }
        
        calibrate_payload = {
            "timestamp": time.time(),
            "calibration_metrics": calibration_metrics,
            "energy_history": energy_history,
            "task_results": calibration_results,
            "agent_summary": {
                "total_agents": len(agent_ids),
                "active_agents": len([a for a in agents if a is not None]),
                "agent_ids": agent_ids
            }
        }
        
        # Cache the result for 60 seconds (calibration is more expensive)
        if cache.ping():
            cache.set(cache_key, calibrate_payload, expire=60)
            logger.debug(f"Cached energy calibrate result: {cache_key}")
        
        return calibrate_payload
        
    except Exception as e:
        logger.error(f"Energy calibration failed: {e}")
        error_payload = {
            "error": str(e),
            "timestamp": time.time(),
            "calibration_metrics": {"error": "Calibration failed"},
            "energy_history": [],
            "task_results": [],
            "agent_summary": {"total_agents": 0}
        }
        
        # Cache the error response for a shorter time (10 seconds)
        if cache.ping():
            cache.set(cache_key, error_payload, expire=10)
            logger.debug(f"Cached error energy calibrate result: {cache_key}")
        
        return error_payload


def _build_energy_health_payload():
    """Internal: Build energy health payload for both legacy and new health routes."""
    from ..energy.calculator import energy_gradient_payload
    from ..energy.ledger import EnergyLedger
    from ..agents.tier0_manager import Tier0MemoryManager
    import ray

    # Initialize Ray if not already done
    if not ray.is_initialized():
        ensure_ray_initialized()

    # Get Tier0 manager for real agent data
    tier0_manager = Tier0MemoryManager()
    agent_ids = tier0_manager.list_agents()

    # Create a ledger with real data
    ledger = EnergyLedger()

    # Add some real pair stats if agents exist
    if len(agent_ids) >= 2:
        for i in range(len(agent_ids)):
            for j in range(i + 1, min(i + 2, len(agent_ids))):
                pair_key = tuple(sorted([agent_ids[i], agent_ids[j]]))
                ledger.pair_stats[pair_key] = {
                    'w': 0.7,  # Simulated collaboration weight
                    'sim': 0.6  # Simulated similarity
                }

    # Get energy ledger snapshot
    ledger_snapshot = energy_gradient_payload(ledger)

    # Check if energy system is responsive
    current_energy = ledger.get_total()

    # Determine health status
    if current_energy < float('inf') and current_energy > float('-inf'):
        status = "healthy"
        message = "Energy system operational"
    else:
        status = "unhealthy"
        message = "Energy calculation error"

    # Get real-time agent metrics
    agent_metrics = {
        "total_agents": len(agent_ids),
        "active_agents": 0,
        "avg_capability": 0.0,
        "avg_mem_util": 0.0
    }

    if agent_ids:
        active_count = 0
        total_capability = 0.0
        total_mem_util = 0.0
        for agent_id in agent_ids[:5]:  # Check first 5 agents
            try:
                agent = tier0_manager.get_agent(agent_id)
                if agent:
                    heartbeat = ray.get(agent.get_heartbeat.remote())
                    if heartbeat.get('last_heartbeat', 0) > time.time() - 300:  # Active in last 5 minutes
                        active_count += 1
                    total_capability += heartbeat.get('capability_score', 0.5)
                    total_mem_util += heartbeat.get('mem_util', 0.0)
            except Exception:
                pass

        agent_metrics.update({
            "active_agents": active_count,
            "avg_capability": total_capability / len(agent_ids) if agent_ids else 0.0,
            "avg_mem_util": total_mem_util / len(agent_ids) if agent_ids else 0.0
        })

    return {
        "status": status,
        "message": message,
        "timestamp": time.time(),
        "energy_snapshot": ledger_snapshot,
        "agent_metrics": agent_metrics,
        "checks": {
            "energy_calculation": "pass" if status == "healthy" else "fail",
            "ledger_accessible": "pass",
            "ray_connection": "pass" if ray.is_initialized() else "fail",
            "tier0_manager": "pass" if tier0_manager else "fail",
            "pair_stats_count": len(ledger.pair_stats),
            "hyper_stats_count": len(ledger.hyper_stats),
            "role_entropy_count": len(ledger.role_entropy),
            "mem_stats_count": len(ledger.mem_stats)
        }
    }


@app.get("/healthz/energy", include_in_schema=False)
def healthz_energy():
    """Legacy health path; use /energy/health. Returns same payload."""
    try:
        return _build_energy_health_payload()
    except Exception as e:
        logger.error(f"Energy health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Energy health check error: {str(e)}",
            "timestamp": time.time(),
            "checks": {
                "energy_calculation": "fail",
                "ledger_accessible": "fail",
                "ray_connection": "fail",
                "tier0_manager": "fail"
            }
        }


@app.get("/energy/health")
def energy_health():
    """Energy health endpoint aligned with /energy/* namespace."""
    try:
        return _build_energy_health_payload()
    except Exception as e:
        logger.error(f"Energy health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": f"Energy health check error: {str(e)}",
            "timestamp": time.time(),
            "checks": {
                "energy_calculation": "fail",
                "ledger_accessible": "fail",
                "ray_connection": "fail",
                "tier0_manager": "fail"
            }
        }


@app.get("/energy/monitor")
def energy_monitor():
    """Real-time energy monitoring endpoint with detailed metrics."""
    try:
        from ..energy.calculator import energy_gradient_payload, calculate_energy
        from ..energy.ledger import EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        from ..caching.redis_cache import get_redis_cache, energy_monitor_cache_key
        import ray
        
        # Try to get from cache first
        cache = get_redis_cache()
        cache_key = energy_monitor_cache_key()
        
        if cache.ping():
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                logger.debug(f"Cache hit for energy monitor: {cache_key}")
                return cached_result
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        # Get Tier0 manager
        tier0_manager = Tier0MemoryManager()
        agent_ids = tier0_manager.list_agents()
        
        # Create default agents if none exist
        if not agent_ids:
            agent_configs = [
                {"agent_id": "monitor_explorer", "role_probs": {"E": 0.8, "S": 0.1, "O": 0.1}},
                {"agent_id": "monitor_specialist", "role_probs": {"E": 0.1, "S": 0.8, "O": 0.1}},
                {"agent_id": "monitor_balanced", "role_probs": {"E": 0.4, "S": 0.4, "O": 0.2}}
            ]
            tier0_manager.create_agents_batch(agent_configs)
            agent_ids = tier0_manager.list_agents()
        
        # Get agents and calculate real energy
        agents = [tier0_manager.get_agent(agent_id) for agent_id in agent_ids if tier0_manager.get_agent(agent_id)]
        
        # Memory system stats
        memory_stats = {
            'cost_vq': COSTVQ._value.get(),
            'bytes_used': MEMORY_SYSTEM.get_memory_stats().get('bytes_used', 0),
            'hit_count': MEMORY_SYSTEM.get_memory_stats().get('hit_count', 0),
            'compression_ratio': compression_knob
        }
        
        # Calculate energy if agents exist
        if agents:
            state = {
                'agents': agents,
                'memory_stats': memory_stats,
                'pair_stats': PAIR_TRACKER.get_all_stats(),
                'alpha': 0.1,
                'lambda_reg': 0.01,
                'beta_mem': 0.05
            }
            energy_terms = calculate_energy(state)
        else:
            energy_terms = EnergyLedger().terms
        
        # Get detailed agent metrics
        agent_details = []
        for agent_id in agent_ids:
            try:
                agent = tier0_manager.get_agent(agent_id)
                if agent:
                    heartbeat = ray.get(agent.get_heartbeat.remote())
                    summary = ray.get(agent.get_summary_stats.remote())
                    energy_proxy = ray.get(agent.get_energy_proxy.remote())
                    
                    agent_details.append({
                        "agent_id": agent_id,
                        "capability": heartbeat.get('capability_score', 0.5),
                        "mem_util": heartbeat.get('mem_util', 0.0),
                        "role_probs": heartbeat.get('role_probs', {}),
                        "tasks_processed": summary.get('tasks_processed', 0),
                        "success_rate": summary.get('success_rate', 0.0),
                        "energy_proxy": energy_proxy,
                        "last_heartbeat": heartbeat.get('last_heartbeat', time.time()),
                        "is_active": heartbeat.get('last_heartbeat', 0) > time.time() - 300
                    })
            except Exception as e:
                logger.warning(f"Failed to get details for agent {agent_id}: {e}")
        
        # Router fast/esc metrics
        total_router = (router_fast_hits + router_escalations) or 1
        p_fast = router_fast_hits / total_router
        p_esc = router_escalations / total_router

        monitor_payload = {
            "timestamp": time.time(),
            "energy_terms": {
                "pair": energy_terms.pair,
                "hyper": energy_terms.hyper,
                "entropy": energy_terms.entropy,
                "reg": energy_terms.reg,
                "mem": energy_terms.mem,
                "total": energy_terms.total
            },
            "router_metrics": {
                "p_fast": p_fast,
                "p_esc": p_esc,
                "latency_ms_p50": float(np.percentile(list(router_latency_ms_window), 50)) if len(router_latency_ms_window) > 0 else 0.0,
                "latency_ms_p95": float(np.percentile(list(router_latency_ms_window), 95)) if len(router_latency_ms_window) > 0 else 0.0,
                "fast_hits": router_fast_hits,
                "escalations": router_escalations
            },
            "memory_metrics": {
                "cost_vq": memory_stats['cost_vq'],
                "bytes_used_kb": memory_stats['bytes_used'] / 1024,
                "hit_count": memory_stats['hit_count'],
                "compression_ratio": memory_stats['compression_ratio']
            },
            "agent_metrics": {
                "total_agents": len(agent_ids),
                "active_agents": len([a for a in agent_details if a.get('is_active', False)]),
                "avg_capability": sum(a.get('capability', 0) for a in agent_details) / len(agent_details) if agent_details else 0.0,
                "avg_mem_util": sum(a.get('mem_util', 0) for a in agent_details) / len(agent_details) if agent_details else 0.0,
                "agent_details": agent_details
            },
            "system_metrics": {
                "compression_knob": compression_knob,
                "energy_slope": ENERGY_SLOPE._value.get(),
                "ray_initialized": ray.is_initialized(),
                "tier0_manager_available": tier0_manager is not None
            }
        }

        # Cache the result for 30 seconds
        if cache.ping():
            cache.set(cache_key, monitor_payload, expire=30)
            logger.debug(f"Cached energy monitor result: {cache_key}")

        return monitor_payload
        
    except Exception as e:
        logger.error(f"Energy monitoring failed: {e}")
        error_payload = {
            "error": str(e),
            "timestamp": time.time(),
            "energy_terms": {"total": 0.0},
            "memory_metrics": {},
            "agent_metrics": {"total_agents": 0},
            "system_metrics": {}
        }
        
        # Cache the error response for a shorter time (10 seconds)
        if cache.ping():
            cache.set(cache_key, error_payload, expire=10)
            logger.debug(f"Cached error energy monitor result: {cache_key}")
        
        return error_payload

@app.get('/tier0/agents/state')
def get_agents_state() -> Dict:
    """Returns the current state of all agents in the simulation with real data."""
    try:
        from ..agents import tier0_manager
        import ray
        
        # Ensure Ray connection (idempotent)
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        all_agents = []

        # Only report Tier 0 agents for consistency
        agent_ids = tier0_manager.list_agents()

        for agent_id in agent_ids:
            try:
                agent = tier0_manager.get_agent(agent_id)
                if agent:
                    heartbeat = ray.get(agent.get_heartbeat.remote())
                    summary = ray.get(agent.get_summary_stats.remote())

                    all_agents.append({
                        "id": agent_id,
                        "type": "tier0_ray_agent",
                        "capability": heartbeat.get('capability_score', 0.5),
                        "mem_util": heartbeat.get('mem_util', 0.0),
                        "role_probs": heartbeat.get('role_probs', {}),
                        "state_embedding": ray.get(agent.get_state_embedding.remote()).tolist(),
                        "memory_writes": summary.get('memory_writes', 0),
                        "memory_hits_on_writes": summary.get('memory_hits_on_writes', 0),
                        "salient_events_logged": summary.get('salient_events_logged', 0),
                        "total_compression_gain": summary.get('total_compression_gain', 0.0),
                        "tasks_processed": summary.get('tasks_processed', 0),
                        "success_rate": summary.get('success_rate', 0.0),
                        "avg_quality": summary.get('avg_quality', 0.0),
                        "peer_interactions": summary.get('peer_interactions_count', 0),
                        "last_heartbeat": heartbeat.get('last_heartbeat', time.time()),
                        "energy_state": heartbeat.get('energy_state', {}),
                        "created_at": heartbeat.get('created_at', time.time())
                    })
            except Exception as e:
                logger.warning(f"Failed to get state for Tier0 agent {agent_id}: {e}")
                all_agents.append({
                    "id": agent_id,
                    "type": "tier0_ray_agent",
                    "error": str(e),
                    "status": "unavailable"
                })
        
        return {
            "agents": all_agents,
            "summary": {
                "total_agents": len(all_agents),
                "tier0_agents": len([a for a in all_agents if a.get('type') == 'tier0_ray_agent']),
                "legacy_agents": 0,
                "active_agents": len([a for a in all_agents if a.get('last_heartbeat', 0) > time.time() - 300]),
                "timestamp": time.time()
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting agents state: {e}")
        return {
            "error": str(e),
            "agents": [],
            "summary": {
                "total_agents": 0,
                "tier0_agents": 0,
                "legacy_agents": 0,
                "active_agents": 0,
                "timestamp": time.time()
            }
        }

# Backward-compat alias, hidden from schema
@app.get('/agents/state', include_in_schema=False)
def get_agents_state_legacy_alias() -> Dict:
    return get_agents_state()

@app.get('/system/status')
def system_status():
    """Returns the current status of the persistent system with real data."""
    try:
        from ..energy.calculator import energy_gradient_payload
        from ..energy.ledger import EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        import ray
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ensure_ray_initialized()
        
        # Get Tier0 manager for real agent data
        tier0_manager = Tier0MemoryManager()
        agent_ids = tier0_manager.list_agents()
        
        # Get legacy organ data
        organs = SIMULATION_REGISTRY.all()
        legacy_agents = sum(len(organ.agents) for organ in organs)
        
        # Get real energy state
        try:
            energy_state = energy_gradient_payload(EnergyLedger())
        except Exception:
            energy_state = {"error": "Energy calculation failed"}
        
        # Get enhanced memory system stats
        memory_stats = MEMORY_SYSTEM.get_memory_stats()
        memory_stats.update({
            "compression_knob": compression_knob,
            "cost_vq": COSTVQ._value.get(),
            "energy_slope": ENERGY_SLOPE._value.get()
        })
        
        # Get real agent statistics
        agent_stats = []
        if agent_ids:
            for agent_id in agent_ids[:10]:  # Limit to first 10 agents
                try:
                    agent = tier0_manager.get_agent(agent_id)
                    if agent:
                        heartbeat = ray.get(agent.get_heartbeat.remote())
                        agent_stats.append({
                            "agent_id": agent_id,
                            "capability_score": heartbeat.get('capability_score', 0.5),
                            "mem_util": heartbeat.get('mem_util', 0.0),
                            "tasks_processed": heartbeat.get('tasks_processed', 0),
                            "success_rate": heartbeat.get('success_rate', 0.0),
                            "role_probs": heartbeat.get('role_probs', {}),
                            "last_heartbeat": heartbeat.get('last_heartbeat', time.time())
                        })
                except Exception as e:
                    logger.warning(f"Failed to get stats for agent {agent_id}: {e}")
        
        return {
            "system_info": {
                "timestamp": time.time(),
                "version": "1.0.0",
                "status": "operational"
            },
            "agents": {
                "tier0_agents": len(agent_ids),
                "legacy_agents": legacy_agents,
                "total_agents": len(agent_ids) + legacy_agents,
                "agent_details": agent_stats
            },
            "organs": [{"id": organ.organ_id, "agent_count": len(organ.agents)} for organ in organs],
            "energy_system": {
                "energy_state": energy_state,
                "compression_knob": compression_knob,
                "cost_vq": COSTVQ._value.get(),
                "energy_slope": ENERGY_SLOPE._value.get()
            },
            "memory_system": memory_stats,
            "pair_stats": PAIR_TRACKER.get_all_stats(),
            "performance_metrics": {
                "memory_utilization_kb": memory_stats.get('bytes_used', 0) / 1024,
                "hit_rate": memory_stats.get('hit_count', 0) / max(memory_stats.get('total_requests', 1), 1),
                "compression_efficiency": compression_knob,
                "active_agents": len([a for a in agent_stats if a.get('last_heartbeat', 0) > time.time() - 300])  # Active in last 5 minutes
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        return {
            "error": str(e),
            "timestamp": time.time(),
            "status": "error",
            "organs": [],
            "agents": {"total_agents": 0},
            "energy_system": {"energy_state": {"error": "Calculation failed"}},
            "memory_system": {"error": "Unavailable"},
            "pair_stats": {},
            "performance_metrics": {}
        }

@app.post('/actions/run_two_agent_task', include_in_schema=False)
def run_two_agent_task():
    """
    Runs a realistic two-agent task simulation with learning.
    """
    # Get the main organ
    organ = SIMULATION_REGISTRY.get("cognitive_organ_1")
    
    if len(organ.agents) < 2:
        return {
            "error": "Need at least 2 agents to run a two-agent task",
            "available_agents": len(organ.agents)
        }
    
    # Randomly select two agents
    selected_agents = random.sample(organ.agents, 2)
    agent1, agent2 = selected_agents
    
    # Calculate cosine similarity between their personality vectors
    sim = cosine_similarity(agent1.h, agent2.h)
    
    # Get historical collaboration weight for this pair
    pair_stats = PAIR_TRACKER.get_pair(agent1.agent_id, agent2.agent_id)
    w_historical = pair_stats.w
    
    # Calculate effective weight by multiplying historical weight with agent capabilities
    w_effective = w_historical * agent1.capability * agent2.capability
    
    # Calculate energy delta: -w_effective * sim (negative because higher similarity should lower energy)
    energy_delta = -w_effective * sim
    
    # Update the energy ledger
    _ledger.add_pair_delta(energy_delta)
    
    # Simulate task success based on similarity
    task_was_successful = random.random() < sim
    
    # Update pair statistics for future collaborations
    PAIR_TRACKER.update_on_task_complete(agent1.agent_id, agent2.agent_id, task_was_successful)
    
    return {
        "message": f"Two-agent task completed between {agent1.agent_id} and {agent2.agent_id}",
        "agents": {
            "agent1": {
                "id": agent1.agent_id,
                "capability": agent1.capability,
                "personality": agent1.h.tolist()
            },
            "agent2": {
                "id": agent2.agent_id,
                "capability": agent2.capability,
                "personality": agent2.h.tolist()
            }
        },
        "calculations": {
            "cosine_similarity": sim,
            "historical_weight": w_historical,
            "effective_weight": w_effective,
            "energy_delta": energy_delta
        },
        "task_result": {
            "successful": bool(task_was_successful),
            "success_probability": sim
        },
        "new_energy_state": energy_gradient_payload(),
        "pair_stats": PAIR_TRACKER.get_all_stats()
    }

@app.get('/run_simulation_step', include_in_schema=False)
def run_simulation_step():
    """
    Legacy endpoint: Runs a single simulation step to demonstrate an energy change.
    """
    try:
        organ = SIMULATION_REGISTRY.get("cognitive_organ_1")
        if not organ or not getattr(organ, 'agents', None):
            return {
                "success": False,
                "error": "Legacy simulation organ 'cognitive_organ_1' not available",
                "hint": "Initialize legacy SIMULATION_REGISTRY or use /organism/* endpoints for COA."
            }
        fast_loop_select_agent(organ, task="analyze_data")
        return {
            "success": True,
            "message": "Simulation step completed successfully!",
            "new_energy_state": energy_gradient_payload(),
            "active_agents": len(organ.agents)
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# --- Slow Loop Endpoints ---
@app.post('/actions/run_slow_loop', include_in_schema=False)
def run_slow_loop_endpoint():
    """
    Runs the slow loop, evolving agent roles based on energy state.
    """
    all_agents = [agent for organ in SIMULATION_REGISTRY.all() for agent in organ.agents]
    slow_loop_update_roles(all_agents)
    
    # Get performance metrics
    role_metrics = get_role_performance_metrics(SIMULATION_REGISTRY.all())
    
    return {
        "message": "Slow loop completed. Agent roles have been adapted.",
        "role_performance_metrics": role_metrics,
        "new_agent_states": get_agents_state(),
        "energy_state": energy_gradient_payload()
    }

@app.get('/run_slow_loop', include_in_schema=False)
def run_slow_loop():
    """
    Legacy endpoint: Runs the slow loop to update agent roles based on performance.
    """
    slow_loop_update_roles(SIMULATION_REGISTRY.all())
    role_metrics = get_role_performance_metrics(SIMULATION_REGISTRY.all())
    
    return {
        "message": "Slow loop completed successfully!",
        "role_performance_metrics": role_metrics,
        "updated_agents": get_agents_state(),
        "energy_state": energy_gradient_payload()
    }

@app.get('/run_slow_loop_simple', include_in_schema=False)
def run_slow_loop_simple():
    """
    Runs the simple slow loop that strengthens dominant roles without energy context.
    """
    all_agents = [agent for organ in SIMULATION_REGISTRY.all() for agent in organ.agents]
    slow_loop_update_roles_simple(all_agents)
    
    return {
        "message": "Simple slow loop completed successfully!",
        "updated_agents": get_agents_state(),
        "energy_state": energy_gradient_payload()
    }

# --- Memory Loop Endpoints ---
@app.get('/run_memory_loop', include_in_schema=False)
def run_memory_loop():
    """
    Runs the comprehensive adaptive memory loop with tiered memory system.
    """
    global compression_knob
    
    # 1. Simulate Activity (The "Write" Phase)
    organs = SIMULATION_REGISTRY.all()
    all_agents = [agent for organ in organs for agent in organ.agents]
    
    if len(all_agents) >= 2:
        # Randomly select agents to write data
        writers = random.sample(all_agents, min(3, len(all_agents)))
        written_data_ids = []
        
        for writer in writers:
            # Randomly choose tier (Mw or Mlt)
            tier = random.choice(['Mw', 'Mlt'])
            data_size = random.randint(5, 20)
            
            success = MEMORY_SYSTEM.write(writer, tier_name=tier, data_size=data_size)
            if success:
                # Get the data_id that was written (we'll need to track this)
                # For now, we'll use a simple approach
                written_data_ids.append(f"data_{writer.agent_id}_{len(written_data_ids)}")
        
        # Randomly select an agent to log a salient event
        salient_agent = random.choice(all_agents)
        MEMORY_SYSTEM.log_salient_event(salient_agent)
        
        # 2. Simulate Activity (The "Read" Phase)
        if written_data_ids:
            readers = random.sample(all_agents, min(2, len(all_agents)))
            for reader in readers:
                # Try to read some of the written data
                for data_id in random.sample(written_data_ids, min(1, len(written_data_ids))):
                    author_id = MEMORY_SYSTEM.read(reader, data_id)
                    if author_id:
                        # Find the author agent and increment their hits_on_writes
                        for agent in all_agents:
                            if agent.agent_id == author_id:
                                agent.memory_hits_on_writes += 1
                                break
    
    # 3. Calculate mem_util for all Agents
    mem_util_scores = {}
    total_mem_util = 0.0
    
    for agent in all_agents:
        mem_util = calculate_dynamic_mem_util(agent)
        mem_util_scores[agent.agent_id] = mem_util
        total_mem_util += mem_util
        agent.mem_util = mem_util  # Update the agent's mem_util field
    
    average_mem_util = total_mem_util / len(all_agents) if all_agents else 0.0
    
    # 4. Calculate Global Memory Energy
    cost_vq_data = calculate_cost_vq(MEMORY_SYSTEM, compression_knob)
    beta_mem = 1.0  # Weight for memory energy term
    mem_energy = beta_mem * cost_vq_data['cost_vq']
    
    # Update the energy ledger with the new memory energy
    _ledger.mem = mem_energy
    
    # 5. Calculate the Gradient and Update Compression Knob
    new_compression_knob = new_adaptive_mem_update(
        SIMULATION_REGISTRY.all(), 
        compression_knob, 
        MEMORY_SYSTEM, 
        beta_mem
    )
    compression_knob = new_compression_knob
    
    # 6. Get comprehensive metrics
    memory_metrics = new_get_memory_metrics(SIMULATION_REGISTRY.all())
    gradient = new_estimate_memory_gradient(SIMULATION_REGISTRY.all())
    
    return {
        "message": "Comprehensive memory loop completed successfully!",
        "compression_knob": compression_knob,
        "average_mem_util": average_mem_util,
        "individual_mem_utils": mem_util_scores,
        "memory_metrics": memory_metrics,
        "memory_gradient": gradient,
        "cost_vq_breakdown": cost_vq_data,
        "memory_energy": mem_energy,
        "memory_system_stats": MEMORY_SYSTEM.get_memory_stats(),
        "energy_state": energy_gradient_payload()
    }

# Experiment moved to examples; endpoint removed to prefer script usage.

# --- Combined Operations ---
@app.get('/run_all_loops', include_in_schema=False)
def run_all_loops():
    """
    Runs all control loops in sequence: fast, slow, and memory.
    """
    global compression_knob
    
    # Run fast loop (simulation step)
    organ = SIMULATION_REGISTRY.get("cognitive_organ_1")
    fast_loop_select_agent(organ, task="analyze_data")
    
    # Run slow loop (role evolution)
    slow_loop_update_roles(SIMULATION_REGISTRY.all())
    
    # Run memory loop (compression control)
    compression_knob = adaptive_mem_update(SIMULATION_REGISTRY.all(), compression_knob)
    
    # Get all metrics
    role_metrics = get_role_performance_metrics(SIMULATION_REGISTRY.all())
    memory_metrics = get_memory_metrics(SIMULATION_REGISTRY.all())
    gradient = estimate_memory_gradient(SIMULATION_REGISTRY.all())
    
    return {
        "message": "All control loops completed successfully!",
        "energy_state": energy_gradient_payload(),
        "role_performance_metrics": role_metrics,
        "memory_metrics": memory_metrics,
        "memory_gradient": gradient,
        "compression_knob": compression_knob,
        "system_status": system_status()
    }

# ---- Register builtin task handlers on app.state (no hairpin HTTP) ----
# Put this after the functions are defined (run_memory_loop, run_all_loops, energy_calibrate)
try:
    app.state.builtin_task_handlers = {
        "memory_loop": lambda: run_memory_loop(),
        "run_all_loops": lambda: run_all_loops(),
        "energy_calibrate": lambda: energy_calibrate(),
        # Add more convenience shortcuts as needed:
        # "energy_monitor": lambda: energy_monitor(),
        # "energy_health": lambda: energy_health(),
        # "two_agent_task": lambda: run_two_agent_task(),  # if desired
    }
except Exception as e:
    logging.warning("Failed to register builtin task handlers: %s", e)

# --- Reset Operations ---
@app.post('/actions/reset', include_in_schema=False)
def reset_simulation():
    """Resets the energy ledger, pair statistics, and memory system back to zero."""
    global PAIR_TRACKER, MEMORY_SYSTEM
    _ledger.reset()
    PAIR_TRACKER = PairStatsTracker()  # Create new instance to reset
    MEMORY_SYSTEM = SharedMemorySystem()  # Create new memory system to reset
    
    # Reset agent memory tracking fields
    for organ in SIMULATION_REGISTRY.all():
        for agent in organ.agents:
            agent.memory_writes = 0
            agent.memory_hits_on_writes = 0
            agent.salient_events_logged = 0
            agent.total_compression_gain = 0.0
            agent.mem_util = 0.0
    
    return {
        "message": "Energy ledger, pair statistics, and memory system have been reset.",
        "pair_stats": PAIR_TRACKER.get_all_stats(),
        "memory_system_stats": MEMORY_SYSTEM.get_memory_stats()
    }

# Energy endpoints are registered via energy_router
 
@app.get('/energy/pair_stats')
@app.get('/pair_stats', include_in_schema=False)
def get_pair_stats():
    """Get all pair collaboration statistics."""
    return {
        "pair_statistics": PAIR_TRACKER.get_all_stats(),
        "total_pairs": len(PAIR_TRACKER.pair_stats)
    }

## Holon endpoints are registered via holon_router

import os
import base64
@app.get("/admin/mw_snapshot", include_in_schema=False)
async def mw_snapshot(limit: int = 10):
    """Dev-only: return a JSON-serializable snapshot of Mw for consolidation examples."""
    try:
        items = list(app.state.stats.mw.items())[: max(0, min(limit, 1024))]
        out = []
        for key, val in items:
            blob = val.get("blob") if isinstance(val, dict) else None
            ts = val.get("ts") if isinstance(val, dict) else None
            enc: dict
            if isinstance(blob, (bytes, bytearray)):
                enc = {"type": "bytes", "b64": base64.b64encode(blob).decode("ascii")}
            elif hasattr(blob, "tolist"):
                enc = {"type": "array", "data": blob.tolist()}
            elif isinstance(blob, list):
                enc = {"type": "array", "data": blob}
            elif blob is None:
                enc = {"type": "none"}
            else:
                try:
                    enc = {"type": "str", "data": str(blob)}
                except Exception:
                    enc = {"type": "unknown"}
            out.append({"key": key, "ts": ts or time.time(), "blob": enc})
        return {"mw": out, "count": len(out)}
    except Exception as e:
        return {"error": str(e)}

@app.post("/admin/write_to_mw", include_in_schema=False)
def write_to_mw():
    import time, uuid
    mw = app.state.stats.mw
    mw[str(uuid.uuid4())] = {"blob": b"hello world", "ts": time.time()}
    return {"status": "ok", "message": "Wrote one item to Mw."}

@app.get("/admin/mw_len", include_in_schema=False)
async def mw_len():
    return {"mw_len": len(mw_cache)}

@app.get("/admin/debug_ids", include_in_schema=False)
async def debug_ids():
    return {
        "mw_writer": id(mw_cache),
        "mw_stats": id(app.state.stats.mw)
    }

@app.get("/admin/metric_ids", include_in_schema=False)
async def metric_ids():
    return {
        "route_COSTVQ": id(COSTVQ),
        "route_MEM": id(MEM_WRITES),
    }

@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/health")
async def health():
    import time
    from ..telemetry.stats import StatsCollector
    from ..telemetry.metrics import ENERGY_SLOPE
    mw_staleness = app.state.stats.mw_stats().get("avg_staleness_s", 0)
    energy_slope = ENERGY_SLOPE._value.get()
    # Track how long energy_slope has been positive
    if not hasattr(app.state, "_slope_positive_since"):
        app.state._slope_positive_since = None
    now = time.time()
    if energy_slope > 0:
        if app.state._slope_positive_since is None:
            app.state._slope_positive_since = now
    else:
        app.state._slope_positive_since = None
    slope_positive_duration = (now - app.state._slope_positive_since) if app.state._slope_positive_since else 0
    warnings = []
    if mw_staleness > 3:
        warnings.append(f"Mw staleness high: {mw_staleness:.2f}s")
    if slope_positive_duration > 300:
        warnings.append(f"energy_delta_last positive for {slope_positive_duration:.0f}s")
    return {
        "ok": not warnings,
        "warnings": warnings,
        "mw_staleness": mw_staleness,
        "energy_delta_last": energy_slope,
        "slope_positive_duration": slope_positive_duration
    }

@app.get("/admin/kappa", include_in_schema=False)
async def get_kappa():
    return {"kappa": app.state.controller.kappa}

@app.post("/admin/kappa", include_in_schema=False)
async def set_kappa(request: Request):
    data = await request.json()
    kappa = float(data.get("kappa", app.state.controller.kappa))
    app.state.controller.kappa = max(0.0, min(1.0, kappa))
    return {"kappa": app.state.controller.kappa, "status": "updated"}

@app.get("/ray/status")
async def ray_status():
    """Get Ray cluster status and configuration."""
    try:
        return {
            "is_initialized": ray.is_initialized(),
            "cluster_resources": ray.cluster_resources() if ray.is_initialized() else {},
            "available_resources": ray.available_resources() if ray.is_initialized() else {},
            "nodes": ray.nodes() if ray.is_initialized() else [],
        }
    except Exception as e:
        return {"error": str(e)}

@app.post("/ray/connect")
async def ray_connect(request: dict):
    """Connect to Ray cluster with specified configuration."""
    try:
        host = request.get('host')
        port = request.get('port', 10001)
        password = request.get('password')
        
        if not host:
            return {"error": "Host is required"}
        
        from ..config.ray_config import configure_ray_remote
        configure_ray_remote(host, port, password)
        
        # Force reconnect (idempotent)
        connect()
        success = is_connected()
        if success:
            return {
                "success": True,
                "message": f"Connected to Ray at {host}:{port}",
                "cluster_info": get_connection_info()
            }
        else:
            return {"error": "Failed to connect to Ray cluster"}
            
    except Exception as e:
        return {"error": str(e)}

# --- Tier 0 (Ma) Memory Endpoints ---

# Tier0 endpoints are registered via tier0_router

# --- Tier 1 (Mw) Working Memory Endpoints ---

@app.post('/mw/{organ_id}/set')
def mw_set_item(organ_id: str, request: dict):
    """Set a working memory item for an organ."""
    item_id = request.get('item_id')
    value = request.get('value')
    if not item_id or value is None:
        return {"success": False, "message": "item_id and value are required"}
    mw = MwManager(organ_id)
    mw.set_item(item_id, value)
    return {"success": True, "message": f"Item {item_id} set for organ {organ_id}"}

@app.get('/mw/{organ_id}/get/{item_id}')
def mw_get_item(organ_id: str, item_id: str):
    """Get a working memory item for an organ."""
    mw = MwManager(organ_id)
    value = mw.get_item(item_id)
    return {"success": value is not None, "value": value}

# --- Tier 2 (Mlt) Long-Term Memory Endpoints are handled via holon_router ---

# --- COA Organism Endpoints are registered via organism_router ---

# =============================================================================
# DSPy Cognitive Core Endpoints
# =============================================================================

# Global cognitive core client (HTTP client to separate serve service)
cognitive_client = None

def get_cognitive_client():
    """Get or create the cognitive core client via HTTP."""
    global cognitive_client
    if cognitive_client is None:
        try:
            # Import here to avoid circular imports
            import httpx
            cognitive_client = httpx.AsyncClient(
                base_url="http://seedcore-serve:8000",
                timeout=30.0
            )
            logger.info("✅ Cognitive core HTTP client initialized")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize cognitive core HTTP client: {e}")
            cognitive_client = None
    return cognitive_client

@app.post("/dspy/reason-about-failure")
async def reason_about_failure(incident_id: str, agent_id: str = None):
    """
    Analyze agent failures using cognitive reasoning.
    
    Args:
        incident_id: ID of the incident to analyze
        agent_id: ID of the agent (optional, will use default if not provided)
    
    Returns:
        Analysis results with thought process and proposed solutions
    """
    try:
        client = get_cognitive_client()
        # Build incident context once so both branches have it
        incident_context = {
            "incident_id": incident_id,
            "error_message": "Task execution failed",
            "agent_state": {"capability_score": 0.5, "memory_utilization": 0.3, "tasks_processed": 10},
            "task_context": {"task_type": "data_processing", "complexity": 0.7, "timestamp": time.time()},
        }
        if not client:
            # Fallback to direct cognitive core if client not available
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.FAILURE_ANALYSIS,
                input_data=incident_context
            )
            
            result = cognitive_core(context)
            return {
                "success": True,
                "agent_id": agent_id or "default_agent",
                "incident_id": incident_id,
                "thought_process": result.get("thought", ""),
                "proposed_solution": result.get("proposed_solution", ""),
                "confidence_score": result.get("confidence_score", 0.0)
            }
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/reason-about-failure", json={
                "agent_id": agent_id or "default_agent",
                "incident_context": incident_context
            })
            result = response.json()
            return result
        except Exception as e:
            logger.warning(f"⚠️ HTTP client call failed: {e}, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in failure reasoning: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dspy/plan-task")
async def plan_task(
    task_description: str,
    agent_id: str = None,
    agent_capabilities: Dict[str, Any] = None,
    available_resources: Dict[str, Any] = None
):
    """
    Plan complex tasks using cognitive reasoning.
    
    Args:
        task_description: Description of the task to plan
        agent_id: ID of the agent (optional)
        agent_capabilities: Agent capabilities (optional)
        available_resources: Available resources (optional)
    
    Returns:
        Task planning results with step-by-step plan
    """
    try:
        client = get_cognitive_client()
        if not client:
            # Fallback to direct cognitive core
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            input_data = {
                "task_description": task_description,
                "agent_capabilities": agent_capabilities or {"capability_score": 0.5},
                "available_resources": available_resources or {}
            }
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data=input_data
            )
            
            result = cognitive_core(context)
            return {
                "success": True,
                "agent_id": agent_id or "default_agent",
                "task_description": task_description,
                "step_by_step_plan": result.get("step_by_step_plan", ""),
                "estimated_complexity": result.get("estimated_complexity", ""),
                "risk_assessment": result.get("risk_assessment", "")
            }
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/plan-task", json={
                "agent_id": agent_id or "default_agent",
                "task_description": task_description,
                "agent_capabilities": agent_capabilities or {"capability_score": 0.5},
                "available_resources": available_resources or {}
            })
            result = response.json()
            return result
        except Exception as e:
            logger.warning(f"⚠️ HTTP client call failed: {e}, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in task planning: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dspy/make-decision")
async def make_decision(
    decision_context: Dict[str, Any],
    agent_id: str = None,
    historical_data: Dict[str, Any] = None
):
    """
    Make decisions using cognitive reasoning.
    
    Args:
        decision_context: Context for the decision
        agent_id: ID of the agent (optional)
        historical_data: Historical data (optional)
    
    Returns:
        Decision results with reasoning and confidence
    """
    try:
        client = get_cognitive_client()
        if not client:
            # Fallback to direct cognitive core
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            input_data = {
                "decision_context": decision_context,
                "historical_data": historical_data or {}
            }
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.DECISION_MAKING,
                input_data=input_data
            )
            
            result = cognitive_core(context)
            return {
                "success": True,
                "agent_id": agent_id or "default_agent",
                "reasoning": result.get("reasoning", ""),
                "decision": result.get("decision", ""),
                "confidence": result.get("confidence", 0.0),
                "alternative_options": result.get("alternative_options", "")
            }
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/make-decision", json={
                "agent_id": agent_id or "default_agent",
                "decision_context": decision_context,
                "historical_data": historical_data or {}
            })
            result = response.json()
            return result
        except Exception as e:
            logger.warning(f"⚠️ HTTP client call failed: {e}, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in decision making: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dspy/solve-problem")
async def solve_problem(
    problem_statement: str,
    constraints: Dict[str, Any],
    available_tools: Dict[str, Any],
    agent_id: str = None
):
    """
    Solve problems using cognitive reasoning.
    
    Args:
        problem_statement: Statement of the problem
        constraints: Problem constraints
        available_tools: Available tools
        agent_id: ID of the agent (optional)
    
    Returns:
        Problem solution with approach and steps
    """
    try:
        client = get_cognitive_client()
        if not client:
            # Fallback to direct cognitive core
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            input_data = {
                "problem_statement": problem_statement,
                "constraints": constraints,
                "available_tools": available_tools
            }
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.PROBLEM_SOLVING,
                input_data=input_data
            )
            
            result = cognitive_core(context)
            return create_cognitive_result(
                agent_id=agent_id or "default_agent",
                task_type="problem_solving",
                result={
                    "solution_approach": result.get("solution_approach", ""),
                    "solution_steps": result.get("solution_steps", ""),
                    "success_metrics": result.get("success_metrics", "")
                }
            ).model_dump()
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/solve-problem", json={
                "agent_id": agent_id or "default_agent",
                "problem_statement": problem_statement,
                "constraints": constraints,
                "available_tools": available_tools
            })
            result = response.json()
            return create_cognitive_result(
                agent_id=agent_id or "default_agent",
                task_type="problem_solving",
                result={
                    "solution_approach": result.get("solution_approach", ""),
                    "solution_steps": result.get("solution_steps", ""),
                    "success_metrics": result.get("success_metrics", "")
                }
            ).model_dump()
        except Exception:  # Remove unused variable e
            logger.warning(f"⚠️ HTTP client call failed, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in problem solving: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dspy/synthesize-memory")
async def synthesize_memory(
    memory_fragments: List[Dict[str, Any]],
    synthesis_goal: str,
    agent_id: str = None
):
    """
    Synthesize information from multiple memory sources.
    
    Args:
        memory_fragments: List of memory fragments to synthesize
        synthesis_goal: Goal of the synthesis
        agent_id: ID of the agent (optional)
    
    Returns:
        Synthesis results with insights and patterns
    """
    try:
        client = get_cognitive_client()
        if not client:
            # Fallback to direct cognitive core
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            input_data = {
                "memory_fragments": memory_fragments,
                "synthesis_goal": synthesis_goal
            }
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
                input_data=input_data
            )
            
            result = cognitive_core(context)
            return create_cognitive_result(
                agent_id=agent_id or "default_agent",
                task_type="memory_synthesis",
                result={
                    "synthesized_insight": result.get("synthesized_insight", ""),
                    "confidence_level": self._safe_float_convert(result.confidence_level),
                    "related_patterns": result.get("related_patterns", "")
                }
            ).model_dump()
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/synthesize-memory", json={
                "agent_id": agent_id or "default_agent",
                "memory_fragments": memory_fragments,
                "synthesis_goal": synthesis_goal
            })
            result = response.json()
            return create_cognitive_result(
                agent_id=agent_id or "default_agent",
                task_type="memory_synthesis",
                result={
                    "synthesized_insight": result.get("synthesized_insight", ""),
                    "confidence_level": self._safe_float_convert(result.confidence_level),
                    "related_patterns": result.get("related_patterns", "")
                }
            ).model_dump()
        except Exception:  # Remove unused variable e
            logger.warning(f"⚠️ HTTP client call failed, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in memory synthesis: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/dspy/assess-capabilities")
async def assess_capabilities(
    performance_data: Dict[str, Any],
    current_capabilities: Dict[str, Any],
    target_capabilities: Dict[str, Any],
    agent_id: str = None
):
    """
    Assess agent capabilities and suggest improvements.
    
    Args:
        performance_data: Performance data
        current_capabilities: Current capabilities
        target_capabilities: Target capabilities
        agent_id: ID of the agent (optional)
    
    Returns:
        Assessment results with gaps and improvement plans
    """
    try:
        client = get_cognitive_client()
        if not client:
            # Fallback to direct cognitive core
            cognitive_core = get_cognitive_core()
            if not cognitive_core:
                cognitive_core = initialize_cognitive_core()
            
            input_data = {
                "performance_data": performance_data,
                "current_capabilities": current_capabilities,
                "target_capabilities": target_capabilities
            }
            
            context = CognitiveContext(
                agent_id=agent_id or "default_agent",
                task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
                input_data=input_data
            )
            
            result = cognitive_core(context)
            return {
                "success": True,
                "agent_id": agent_id or "default_agent",
                "capability_gaps": result.get("capability_gaps", ""),
                "improvement_plan": result.get("improvement_plan", ""),
                "priority_recommendations": result.get("priority_recommendations", "")
            }
        
        # Use HTTP client to separate serve service
        try:
            response = await client.post("/cognitive/assess-capabilities", json={
                "agent_id": agent_id or "default_agent",
                "performance_data": performance_data,
                "current_capabilities": current_capabilities,
                "target_capabilities": target_capabilities
            })
            result = response.json()
            return result
        except Exception:  # Remove unused variable e
            logger.warning(f"⚠️ HTTP client call failed, using fallback")
            # Continue with fallback logic below
        
    except Exception as e:
        logger.error(f"Error in capability assessment: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/dspy/status")
async def get_dspy_status():
    """
    Get the status of the DSPy cognitive core system.
    
    Returns:
        Status information about the cognitive core
    """
    try:
        client = get_cognitive_client()
        cognitive_core = get_cognitive_core()
        
        # Check Ray Serve cognitive core availability
        ray_serve_cognitive_available = False
        try:
            logger.info("Checking Ray Serve cognitive core availability...")
            if client:
                logger.info("HTTP client available, checking cognitive core deployment...")
                # Use our enhanced client to check if the cognitive core is deployed
                from ..cognitive import for_env
                logger.info("Successfully imported for_env from cognitive module")
                dspy_client = for_env()
                logger.info("Successfully created DSpy client")
                ray_serve_cognitive_available = dspy_client.is_deployed()
                logger.info(f"Ray Serve cognitive core deployed: {ray_serve_cognitive_available}")
            else:
                logger.info("HTTP client not available, skipping Ray Serve check")
        except Exception as e:
            logger.error(f"Error checking Ray Serve cognitive core: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
        
        return {
            "success": True,
            "cognitive_core_available": cognitive_core is not None,
            "ray_serve_cognitive_available": ray_serve_cognitive_available,
            "serve_client_available": client is not None,
            "supported_task_types": [task.value for task in CognitiveTaskType],
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error getting DSPy status: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }

# --- Maintenance Endpoints ---
@app.get("/maintenance/status", include_in_schema=False)
async def maintenance_status():
    """Get maintenance status and cluster health info."""
    try:
        if not hasattr(app.state, "janitor") or app.state.janitor is None:
            return {"status": "janitor_not_available"}
        
        status = ray.get(app.state.janitor.status.remote())
        return status
    except Exception as e:
        return {"status": "error", "error": str(e)}

@app.post("/maintenance/cleanup", include_in_schema=False)
async def maintenance_cleanup(request: Request):
    """Trigger cluster cleanup of dead actors."""
    try:
        if not hasattr(app.state, "janitor") or app.state.janitor is None:
            return {"error": "Janitor actor not available"}
        
        data = await request.json()
        prefix = data.get("prefix") if data else None
        
        result = ray.get(app.state.janitor.reap.remote(prefix=prefix))
        return {
            "success": True,
            "result": result
        }
    except Exception as e:
        return {"error": str(e)}

@app.get("/maintenance/dead-actors", include_in_schema=False)
async def list_dead_actors(prefix: str = None):
    """List dead actors in the cluster."""
    try:
        if not hasattr(app.state, "janitor") or app.state.janitor is None:
            return {"error": "Janitor actor not available"}
        
        dead_actors = ray.get(app.state.janitor.list_dead_named.remote(prefix=prefix))
        return {
            "dead_actors": dead_actors,
            "count": len(dead_actors)
        }
    except Exception as e:
        return {"error": str(e)}

# --- NEW: Coordinator Health Endpoint ---
@app.get("/coordinator/health")
async def coordinator_health():
    """Check the health of the Coordinator actor that manages the OrganismManager."""
    return await check_coordinator_health()

# --- NEW: Task Submission Endpoint ---
@app.post("/coordinator/submit")
async def submit_task_to_coordinator_endpoint(task: Dict[str, Any]):
    """Submit a task directly to the Coordinator actor for processing."""
    return await submit_task_to_coordinator(task)



