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
import numpy as np
import random
import uuid
import ray
from fastapi import FastAPI, Depends, HTTPException, Request
from typing import List, Dict
import time
# import redis
from ..telemetry.stats import StatsCollector
from ..energy.api import energy_gradient_payload, _ledger
from ..energy.pair_stats import PairStatsTracker
from ..control.fast_loop import fast_loop_select_agent
from ..control.slow_loop import slow_loop_update_roles, slow_loop_update_roles_simple, get_role_performance_metrics
from ..control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from ..organs.base import Organ
from ..organs.registry import OrganRegistry
from ..organs.organism_manager import organism_manager
from ..agents.base import Agent
from ..agents import RayAgent, Tier0MemoryManager, tier0_manager
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
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
from ..telemetry.metrics import COSTVQ, ENERGY_SLOPE, MEM_WRITES
from ..control.memory.meta_controller import adjust
import asyncio
from ..api.routers.mfb_router import mfb_router
from ..api.routers.salience_router import router as salience_router
from ..config.ray_config import get_ray_config
from ..utils.ray_utils import init_ray, get_ray_cluster_info, is_ray_available

# --- Persistent State ---
# Create a single, persistent registry when the server starts.
# This holds the state of our simulation.
print("Initializing persistent simulation state...")
SIMULATION_REGISTRY = OrganRegistry()
PAIR_TRACKER = PairStatsTracker()
MEMORY_SYSTEM = SharedMemorySystem()  # Persistent memory system

# Note: Organ and agent creation is now handled by the OrganismManager
# during startup. The old manual creation code has been removed.
print("Organism initialization will be handled by OrganismManager during startup.")

# Global compression knob for memory control
compression_knob = 0.5

# Global Holon Fabric instance
holon_fabric = None
# --- End Persistent State ---

# In-memory Tier-1 cache (Mw) for demonstration
mw_cache = {}  # This should be updated by your memory system as needed

app = FastAPI()
app.include_router(mfb_router)
app.include_router(salience_router)

class _Ctl:
    tau: float = 0.3
    gamma: float = 2.0
    kappa: float = 0.5  # TD-priority knob
app.state.controller = _Ctl()

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global mw_cache, MEMORY_SYSTEM
    
    # Initialize memory system
    MEMORY_SYSTEM = SharedMemorySystem()
    app.state.mem = MEMORY_SYSTEM
    
    # Initialize Ray with flexible configuration
    try:
        ray_config = get_ray_config()
        if ray_config.is_configured():
            logging.info(f"Initializing Ray with configuration: {ray_config}")
            
            # Check if Ray is already initialized to avoid double initialization
            if not ray.is_initialized():
                success = init_ray()
                if success:
                    logging.info("Ray initialization successful")
                    cluster_info = get_ray_cluster_info()
                    logging.info(f"Ray cluster info: {cluster_info}")
                else:
                    logging.warning("Ray initialization failed, continuing without Ray")
            else:
                logging.info("Ray is already initialized, skipping initialization")
                cluster_info = get_ray_cluster_info()
                logging.info(f"Ray cluster info: {cluster_info}")
            
            # Initialize the COA organism after Ray is ready
            try:
                await organism_manager.initialize_organism()
                app.state.organism = organism_manager
                logging.info("✅ COA organism initialized successfully")
            except Exception as e:
                logging.error(f"❌ Failed to initialize COA organism: {e}")
        else:
            logging.info("Ray not configured, skipping Ray initialization")
    except Exception as e:
        logging.error(f"Error during Ray initialization: {e}")
    
    # Start consolidator loop
    import asyncio
    asyncio.create_task(start_consolidator())
    logging.info("Consolidator loop started")

@app.on_event("startup")
async def build_memory():
    """Initialize the Holon Fabric on server startup"""
    global holon_fabric
    import os
    
    # Get connection details from environment variables
    pg_dsn = os.getenv("PG_DSN")
    neo4j_uri = os.getenv("NEO4J_URI")
    neo4j_user = os.getenv("NEO4J_USER")
    neo4j_password = os.getenv("NEO4J_PASSWORD")
    
    # Validate required environment variables
    if not pg_dsn:
        raise ValueError("PG_DSN environment variable is required")
    if not neo4j_uri:
        raise ValueError("NEO4J_URI environment variable is required")
    if not neo4j_user:
        raise ValueError("NEO4J_USER environment variable is required")
    if not neo4j_password:
        raise ValueError("NEO4J_PASSWORD environment variable is required")
    
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

@app.on_event("startup")
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

@app.on_event("startup")
async def sync_counters():
    import asyncpg
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

@app.on_event("startup")
async def start_metrics_integration():
    """Start the metrics integration service on startup."""
    try:
        from .metrics_integration import start_metrics_integration
        import asyncio
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Start metrics integration in background
        # Use SEEDCORE_API_ADDRESS for internal container communication
        # SEEDCORE_API_URL is for external access, not needed here
        base_url = os.getenv("SEEDCORE_API_ADDRESS", "localhost:8002")
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
            
        logger.info(f"🔗 Metrics integration using base_url: {base_url}")
        
        asyncio.create_task(start_metrics_integration(
            base_url=base_url,  # Use internal API service address
            update_interval=30  # Update every 30 seconds
        ))
        logger.info("🚀 Started metrics integration service")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to start metrics integration: {e}")

@app.on_event("shutdown")
async def stop_metrics_integration():
    """Stop the metrics integration service on shutdown."""
    try:
        from .metrics_integration import stop_metrics_integration
        import logging
        
        logger = logging.getLogger(__name__)
        await stop_metrics_integration()
        logger.info("🛑 Stopped metrics integration service")
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to stop metrics integration: {e}")

@app.on_event("shutdown")
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
        
        # Update energy terms based on event type
        if event.get('organ') == 'utility' and event.get('metric') == 'predicted_risk':
            # Update pair energy based on prediction success
            if event.get('success', False):
                # Successful prediction reduces pair energy (better collaboration)
                _ledger.add_pair_delta(w_effective=0.1, similarity=0.8)
            else:
                # Failed prediction increases pair energy (worse collaboration)
                _ledger.add_pair_delta(w_effective=0.1, similarity=0.2)
            
            # Update mem energy based on model usage
            if event.get('model_path'):
                # Model loading adds to memory pressure
                _ledger.add_mem_delta(memory_usage=0.1, compression_ratio=0.5)
            
            # Update reg energy based on model complexity
            if event.get('prediction_count', 0) > 100:
                # High prediction count indicates model complexity
                _ledger.add_reg_delta(complexity=0.05)
        
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
        from ..energy.calculator import energy_gradient_payload, EnergyLedger, calculate_energy
        from ..agents.tier0_manager import Tier0MemoryManager
        from ..caching.redis_cache import get_redis_cache, energy_gradient_cache_key
        import ray
        
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
            ray.init(address="auto", ignore_reinit_error=True)
        
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
            'compression_ratio': compression_knob
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
            ledger.terms = energy_terms
            
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
            
            # Get energy gradient payload
            energy_payload = energy_gradient_payload(ledger)
            
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


@app.get("/energy/calibrate")
def energy_calibrate():
    """Energy calibration endpoint that runs synthetic tasks and returns calibration results."""
    try:
        from ..energy.calculator import EnergyLedger, calculate_energy
        from ..agents.tier0_manager import Tier0MemoryManager
        from ..caching.redis_cache import get_redis_cache, energy_calibrate_cache_key
        import ray
        import numpy as np
        
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
            ray.init(address="auto", ignore_reinit_error=True)
        
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


@app.get("/healthz/energy")
def healthz_energy():
    """Health check endpoint for energy system readiness."""
    try:
        from ..energy.calculator import energy_gradient_payload, EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        import ray
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ray.init(address="auto", ignore_reinit_error=True)
        
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
        from ..energy.calculator import energy_gradient_payload, EnergyLedger, calculate_energy
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
            ray.init(address="auto", ignore_reinit_error=True)
        
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

@app.get('/agents/state')
def get_agents_state() -> Dict:
    """Returns the current state of all agents in the simulation with real data."""
    try:
        from ..agents.tier0_manager import Tier0MemoryManager
        import ray
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ray.init(address="auto", ignore_reinit_error=True)
        
        all_agents = []
        
        # Get Tier0 agents (real Ray actors)
        tier0_manager = Tier0MemoryManager()
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
                # Add error entry
                all_agents.append({
                    "id": agent_id,
                    "type": "tier0_ray_agent",
                    "error": str(e),
                    "status": "unavailable"
                })
        
        # Get legacy organ agents
        for organ in SIMULATION_REGISTRY.all():
            for agent in organ.agents:
                all_agents.append({
                    "id": agent.agent_id,
                    "type": "legacy_organ_agent",
                    "capability": agent.capability,
                    "mem_util": agent.mem_util,
                    "role_probs": agent.role_probs,
                    "personality_vector": agent.h.tolist(),
                    "memory_writes": agent.memory_writes,
                    "memory_hits_on_writes": agent.memory_hits_on_writes,
                    "salient_events_logged": agent.salient_events_logged,
                    "total_compression_gain": agent.total_compression_gain
                })
        
        return {
            "agents": all_agents,
            "summary": {
                "total_agents": len(all_agents),
                "tier0_agents": len([a for a in all_agents if a.get('type') == 'tier0_ray_agent']),
                "legacy_agents": len([a for a in all_agents if a.get('type') == 'legacy_organ_agent']),
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

@app.get('/system/status')
def system_status():
    """Returns the current status of the persistent system with real data."""
    try:
        from ..energy.calculator import energy_gradient_payload, EnergyLedger
        from ..agents.tier0_manager import Tier0MemoryManager
        import ray
        
        # Initialize Ray if not already done
        if not ray.is_initialized():
            ray.init(address="auto", ignore_reinit_error=True)
        
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

@app.post('/actions/run_two_agent_task')
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

@app.get('/run_simulation_step')
def run_simulation_step():
    """
    Legacy endpoint: Runs a single simulation step to demonstrate an energy change.
    """
    organ = SIMULATION_REGISTRY.get("cognitive_organ_1")
    fast_loop_select_agent(organ, task="analyze_data")
    
    return {
        "message": "Simulation step completed successfully!",
        "new_energy_state": energy_gradient_payload(),
        "active_agents": len(organ.agents)
    }

# --- Slow Loop Endpoints ---
@app.post('/actions/run_slow_loop')
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

@app.get('/run_slow_loop')
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

@app.get('/run_slow_loop_simple')
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
@app.get('/run_memory_loop')
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

@app.get('/run_pgvector_neo4j_experiment')
def run_pgvector_neo4j_experiment():
    """
    Runs the PGVector + Neo4j memory loop experiment and returns the results.
    """
    return run_memory_loop_experiment()

# --- Combined Operations ---
@app.get('/run_all_loops')
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

# --- Reset Operations ---
@app.post('/actions/reset')
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

@app.get('/reset_energy')
def reset_energy():
    """Legacy endpoint: Resets the energy ledger back to zero."""
    _ledger.reset()
    return {"message": "Energy ledger has been reset."}

@app.get('/pair_stats')
def get_pair_stats():
    """Get all pair collaboration statistics."""
    return {
        "pair_statistics": PAIR_TRACKER.get_all_stats(),
        "total_pairs": len(PAIR_TRACKER.pair_stats)
    }

# --- Holon Fabric Endpoints ---
@app.post('/rag')
async def rag_endpoint(q: dict):
    """RAG endpoint for fuzzy search with holon expansion"""
    global holon_fabric
    if not holon_fabric:
        return {"error": "Holon Fabric not initialized"}
    
    embedding = np.array(q.get("embedding", []))
    k = q.get("k", 10)
    
    if len(embedding) == 0:
        return {"error": "No embedding provided"}
    
    # Pad or truncate to 768 dimensions
    if len(embedding) < 768:
        embedding = np.pad(embedding, (0, 768 - len(embedding)), mode='constant')
    else:
        embedding = embedding[:768]
    
    holons = await holon_fabric.query_fuzzy(embedding, k=k)
    return {"holons": holons}

@app.post('/holon/insert')
async def insert_holon(holon_data: dict):
    """Insert a new holon into the fabric"""
    global holon_fabric
    if not holon_fabric:
        return {"error": "Holon Fabric not initialized"}
    
    try:
        embedding = np.array(holon_data["embedding"])
        # Pad or truncate to 768 dimensions
        if len(embedding) < 768:
            embedding = np.pad(embedding, (0, 768 - len(embedding)), mode='constant')
        else:
            embedding = embedding[:768]
            
        holon = Holon(
            uuid=holon_data.get("uuid", str(uuid.uuid4())),
            embedding=embedding,
            meta=holon_data.get("meta", {})
        )
        await holon_fabric.insert_holon(holon)
        return {"message": "Holon inserted successfully", "uuid": holon.uuid}
    except Exception as e:
        return {"error": f"Failed to insert holon: {str(e)}"}

@app.get('/holon/stats')
async def holon_stats():
    sc = app.state.stats
    errors = {}
    # Mw stats
    try:
        mw = sc.mw_stats()
    except Exception as e:
        mw = {"error": str(e)}
        errors["Mw"] = str(e)
    # PGVector (Mlt) stats
    try:
        mlt = await sc.mlt_stats()
    except Exception as e:
        mlt = {"error": str(e)}
        errors["Mlt"] = str(e)
    # Neo4j relationship stats
    try:
        rel = sc.rel_stats()
    except Exception as e:
        rel = {"error": str(e)}
        errors["Neo4j"] = str(e)
    # Prometheus energy stats
    try:
        energy = sc.energy_stats()
    except Exception as e:
        energy = {"error": str(e)}
        errors["Prometheus"] = str(e)
    # Compose response
    body = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tiers": {
            "Mw": mw,
            "Mlt": mlt
        },
        "vector_dimensions": getattr(sc, "EMB_DIM", 768),
        "energy": energy,
        "status": "healthy" if not errors else "unhealthy"
    }
    if isinstance(rel, dict):
        body.update(rel)
    if errors:
        body["errors"] = errors
    # simple rule: status=unhealthy if Mw staleness > 3 s or PG query slow
    if isinstance(mw, dict) and mw.get("avg_staleness_s", 0) > 3:
        body["status"] = "unhealthy"
    return body

@app.get('/holon/{uuid}')
async def get_holon(uuid: str):
    """Get a specific holon by UUID"""
    global holon_fabric
    if not holon_fabric:
        return {"error": "Holon Fabric not initialized"}
    
    result = await holon_fabric.query_exact(uuid)
    if result:
        return result
    else:
        return {"error": "Holon not found"}

@app.post('/holon/relationship')
async def create_relationship(rel_data: dict):
    """Create a relationship between two holons"""
    global holon_fabric
    if not holon_fabric:
        return {"error": "Holon Fabric not initialized"}
    
    src_uuid = rel_data.get("src_uuid")
    rel = rel_data.get("rel")
    dst_uuid = rel_data.get("dst_uuid")
    
    if not all([src_uuid, rel, dst_uuid]):
        return {"error": "Missing required fields: src_uuid, rel, dst_uuid"}
    
    await holon_fabric.create_relationship(src_uuid, rel, dst_uuid)
    return {"message": "Relationship created successfully"}

import os
from ..memory.consolidation_task import consolidation_worker
@app.post("/admin/consolidate_once")
async def consolidate_once(batch: int = 10, tau: float = 0.3):
    mw = dict(list(app.state.stats.mw.items())[:batch])   # freeze a snapshot
    n  = ray.get(
        consolidation_worker.remote(
            os.getenv("PG_DSN"),
            "bolt://seedcore-neo4j:7687",
            ("neo4j", os.getenv("NEO4J_PASSWORD")),
            mw, tau, batch)
    )
    return {"consolidated": n}

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
        config = get_ray_config()
        cluster_info = get_ray_cluster_info()
        
        return {
            "ray_configured": config.is_configured(),
            "ray_available": is_ray_available(),
            "config": str(config),
            "cluster_info": cluster_info
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
        
        success = init_ray(force_reinit=True)
        if success:
            return {
                "success": True,
                "message": f"Connected to Ray at {host}:{port}",
                "cluster_info": get_ray_cluster_info()
            }
        else:
            return {"error": "Failed to connect to Ray cluster"}
            
    except Exception as e:
        return {"error": str(e)}

# --- Tier 0 (Ma) Memory Endpoints ---

@app.post("/tier0/agents/create")
async def create_ray_agent(request: dict):
    """Create a new Ray agent actor."""
    try:
        agent_id = request.get('agent_id')
        role_probs = request.get('role_probs')
        
        if not agent_id:
            return {"success": False, "message": "agent_id is required"}
        
        created_id = tier0_manager.create_agent(agent_id, role_probs)
        return {"success": True, "agent_id": created_id, "message": f"Agent {created_id} created"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/tier0/agents/create_batch")
async def create_ray_agents_batch(request: dict):
    """Create multiple Ray agent actors in batch."""
    try:
        agent_configs = request.get('agent_configs', [])
        
        if not agent_configs:
            return {"success": False, "message": "agent_configs list is required"}
        
        created_ids = tier0_manager.create_agents_batch(agent_configs)
        return {"success": True, "agent_ids": created_ids, "message": f"Created {len(created_ids)} agents"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/tier0/agents")
async def list_ray_agents():
    """List all Ray agent IDs."""
    try:
        agents = tier0_manager.list_agents()
        return {"success": True, "agents": agents, "count": len(agents)}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/tier0/agents/{agent_id}/execute")
async def execute_task_on_agent(agent_id: str, request: dict):
    """Execute a task on a specific agent."""
    try:
        task_data = request.get('task_data', {})
        result = tier0_manager.execute_task_on_agent(agent_id, task_data)
        
        if result:
            return {"success": True, "result": result}
        else:
            return {"success": False, "message": f"Agent {agent_id} not found or task failed"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/tier0/agents/execute_random")
async def execute_task_on_random_agent(request: dict):
    """Execute a task on a randomly selected agent."""
    try:
        task_data = request.get('task_data', {})
        result = tier0_manager.execute_task_on_random_agent(task_data)
        
        if result:
            return {"success": True, "result": result}
        else:
            return {"success": False, "message": "No agents available"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/tier0/agents/{agent_id}/heartbeat")
async def get_agent_heartbeat(agent_id: str):
    """Get the latest heartbeat for a specific agent."""
    try:
        # Force a heartbeat collection before returning
        await tier0_manager.collect_heartbeats()
        heartbeat = tier0_manager.get_agent_heartbeat(agent_id)
        if heartbeat:
            return {"success": True, "heartbeat": heartbeat}
        else:
            return {"success": False, "message": f"Heartbeat for agent {agent_id} not yet collected"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/tier0/agents/heartbeats")
async def get_all_agent_heartbeats():
    """Get heartbeats from all agents."""
    try:
        heartbeats = tier0_manager.get_all_heartbeats()
        return {"success": True, "heartbeats": heartbeats, "count": len(heartbeats)}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.get("/tier0/summary")
async def get_tier0_summary():
    """Get a summary of the Tier 0 memory system."""
    try:
        summary = tier0_manager.get_system_summary()
        return {"success": True, "summary": summary}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/tier0/agents/{agent_id}/reset")
async def reset_agent_metrics(agent_id: str):
    """Reset metrics for a specific agent."""
    try:
        success = tier0_manager.reset_agent_metrics(agent_id)
        return {"success": success, "message": f"Agent {agent_id} metrics reset" if success else f"Agent {agent_id} not found"}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/tier0/agents/shutdown")
async def shutdown_tier0_agents():
    """Shutdown all Tier 0 agents."""
    try:
        tier0_manager.shutdown_agents()
        return {"success": True, "message": "All agents shut down"}
    except Exception as e:
        return {"success": False, "message": str(e)}

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

# --- Tier 2 (Mlt) Long-Term Memory Endpoints ---

ltm_manager = LongTermMemoryManager()

@app.post('/mlt/insert_holon')
async def mlt_insert_holon(request: dict):
    """Insert a holon into long-term memory (PgVector + Neo4j, saga pattern)."""
    result = await ltm_manager.insert_holon(request)
    return {"success": result}

# --- COA Organism Endpoints ---

@app.get("/organism/status")
async def get_organism_status():
    """Returns the current status of all organs and their agents."""
    try:
        if not hasattr(app.state, 'organism') or not app.state.organism:
            return {"success": False, "error": "Organism not initialized"}
            
        status = await app.state.organism.get_organism_status()
        return {"success": True, "data": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/organism/execute/{organ_id}")
async def execute_task_on_organ(organ_id: str, request: dict):
    """Execute a task on a specific organ."""
    try:
        if not hasattr(app.state, 'organism') or not app.state.organism:
            return {"success": False, "error": "Organism not initialized"}
            
        task_data = request.get('task_data', {})
        result = await app.state.organism.execute_task_on_organ(organ_id, task_data)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/organism/execute/random")
async def execute_task_on_random_organ(request: dict):
    """Execute a task on a randomly selected organ."""
    try:
        if not hasattr(app.state, 'organism') or not app.state.organism:
            return {"success": False, "error": "Organism not initialized"}
            
        task_data = request.get('task_data', {})
        result = await app.state.organism.execute_task_on_random_organ(task_data)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/organism/summary")
async def get_organism_summary():
    """Get a summary of the organism including organ and agent counts."""
    try:
        if not hasattr(app.state, 'organism') or not app.state.organism:
            return {"success": False, "error": "Organism not initialized"}
            
        organism = app.state.organism
        summary = {
            "initialized": organism.is_initialized(),
            "organ_count": organism.get_organ_count(),
            "total_agent_count": organism.get_total_agent_count(),
            "organs": {}
        }
        
        # Get detailed organ information
        for organ_id in organism.organs.keys():
            organ_handle = organism.get_organ_handle(organ_id)
            if organ_handle:
                try:
                    status = await organ_handle.get_status.remote()
                    summary["organs"][organ_id] = status
                except Exception as e:
                    summary["organs"][organ_id] = {"error": str(e)}
        
        return {"success": True, "summary": summary}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/organism/initialize")
async def initialize_organism():
    """Manually initialize the organism (useful for testing)."""
    try:
        # Use the global organism_manager directly
        if organism_manager.is_initialized():
            # Also set it in app.state for consistency
            app.state.organism = organism_manager
            return {"success": True, "message": "Organism already initialized"}
            
        await organism_manager.initialize_organism()
        # Set it in app.state for consistency
        app.state.organism = organism_manager
        return {"success": True, "message": "Organism initialized successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/organism/shutdown")
async def shutdown_organism():
    """Shutdown the organism and clean up resources."""
    try:
        if not hasattr(app.state, 'organism') or not app.state.organism:
            return {"success": False, "error": "Organism not initialized"}
            
        app.state.organism.shutdown_organism()
        return {"success": True, "message": "Organism shutdown successfully"}
    except Exception as e:
        return {"success": False, "error": str(e)}

