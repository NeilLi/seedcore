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
import numpy as np
import random
import uuid
from fastapi import FastAPI, Depends, HTTPException, Request
from typing import List, Dict
import time
from seedcore.telemetry.stats import StatsCollector

# Import our system components
from ..energy.api import energy_gradient_payload, _ledger
from ..energy.pair_stats import PairStatsTracker
from ..control.fast_loop import fast_loop_select_agent
from ..control.slow_loop import slow_loop_update_roles, slow_loop_update_roles_simple, get_role_performance_metrics
from ..control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from ..organs.base import Organ
from ..organs.registry import OrganRegistry
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
# from seedcore.examples.experiment_pgvector_neo4j import run_memory_loop_experiment

# Import Holon Fabric components
from ..memory.holon_fabric import HolonFabric
from ..memory.backends.pgvector_backend import PgVectorStore, Holon
from ..memory.backends.neo4j_graph import Neo4jGraph

import ray
from seedcore.utils.ray_utils import init_ray, is_ray_available, get_ray_cluster_info
from seedcore.config.ray_config import get_ray_config
import logging, os
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
from seedcore.telemetry.metrics import COSTVQ, ENERGY_SLOPE, MEM_WRITES
from src.seedcore.control.memory.meta_controller import adjust
from seedcore.memory.consolidation_logic import consolidate_batch
import redis.asyncio as aioredis

# --- Persistent State ---
# Create a single, persistent registry when the server starts.
# This holds the state of our simulation.
print("Initializing persistent simulation state...")
SIMULATION_REGISTRY = OrganRegistry()
PAIR_TRACKER = PairStatsTracker()
MEMORY_SYSTEM = SharedMemorySystem()  # Persistent memory system

# Create a main organ
main_organ = Organ(organ_id="cognitive_organ_1")

# Create a few agents with different initial role probabilities and personality vectors
# Some vectors are similar, some are dissimilar to test the logic
agents_to_create = [
    Agent(
        agent_id="agent_alpha", 
        role_probs={'E': 0.6, 'S': 0.3, 'O': 0.1},
        h=np.array([0.8, 0.6, 0.4, 0.2, 0.1, 0.3, 0.5, 0.7])  # Similar to beta
    ),
    Agent(
        agent_id="agent_beta", 
        role_probs={'E': 0.2, 'S': 0.7, 'O': 0.1},
        h=np.array([0.7, 0.5, 0.3, 0.1, 0.2, 0.4, 0.6, 0.8])  # Similar to alpha
    ),
    Agent(
        agent_id="agent_gamma", 
        role_probs={'E': 0.3, 'S': 0.3, 'O': 0.4},
        h=np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.6])  # Different from alpha/beta
    ),
]

# Register the agents with the organ, and the organ with the registry
for agent in agents_to_create:
    main_organ.register(agent)
SIMULATION_REGISTRY.add(main_organ)
print(f"State initialized with 1 organ and {len(agents_to_create)} agents.")

# Global compression knob for memory control
compression_knob = 0.5

# Global Holon Fabric instance
holon_fabric = None
# --- End Persistent State ---

# In-memory Tier-1 cache (Mw) for demonstration
mw_cache = {}  # This should be updated by your memory system as needed

app = FastAPI()

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
    
    # Initialize Redis client if configured
    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        try:
            app.state.redis = redis.from_url(redis_url)
            logging.info(f"Redis client initialized: {redis_url}")
        except Exception as e:
            logging.error(f"Failed to initialize Redis: {e}")
            app.state.redis = None
    else:
        app.state.redis = None
        logging.info("Redis not configured, running without Redis")
    
    # Initialize Ray with flexible configuration
    try:
        ray_config = get_ray_config()
        if ray_config.is_configured():
            logging.info(f"Initializing Ray with configuration: {ray_config}")
            success = init_ray()
            if success:
                logging.info("Ray initialization successful")
                cluster_info = get_ray_cluster_info()
                logging.info(f"Ray cluster info: {cluster_info}")
            else:
                logging.warning("Ray initialization failed, continuing without Ray")
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
                    redis=app.state.redis
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
        from seedcore.telemetry.metrics import COSTVQ
        COSTVQ.set(avg_cost or 0)
    finally:
        await c.close()

@app.on_event("shutdown")
async def cleanup_memory():
    """Cleanup connections on server shutdown"""
    global holon_fabric
    if holon_fabric and holon_fabric.graph:
        holon_fabric.graph.close()

def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    
    return dot_product / (norm_v1 * norm_v2)

@app.get('/energy/gradient')
async def energy_gradient():
    return {
        "CostVQ": COSTVQ._value.get(),
        "deltaE_last": ENERGY_SLOPE._value.get()
    }

@app.get('/agents/state')
def get_agents_state() -> List[Dict]:
    """Returns the current state of all agents in the simulation."""
    all_agents = []
    for organ in SIMULATION_REGISTRY.all():
        for agent in organ.agents:
            all_agents.append({
                "id": agent.agent_id,
                "capability": agent.capability,
                "mem_util": agent.mem_util,
                "role_probs": agent.role_probs,
                "personality_vector": agent.h.tolist(),
                "memory_writes": agent.memory_writes,
                "memory_hits_on_writes": agent.memory_hits_on_writes,
                "salient_events_logged": agent.salient_events_logged,
                "total_compression_gain": agent.total_compression_gain
            })
    return all_agents

@app.get('/system/status')
def system_status():
    """Returns the current status of the persistent system."""
    organs = SIMULATION_REGISTRY.all()
    total_agents = sum(len(organ.agents) for organ in organs)
    
    return {
        "organs": [{"id": organ.organ_id, "agent_count": len(organ.agents)} for organ in organs],
        "total_agents": total_agents,
        "energy_state": energy_gradient_payload(),
        "compression_knob": compression_knob,
        "pair_stats": PAIR_TRACKER.get_all_stats(),
        "memory_system": MEMORY_SYSTEM.get_memory_stats()
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
from seedcore.memory.consolidation_task import consolidation_worker
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
    from src.seedcore.telemetry.server import mw_cache
    return {"mw_len": len(mw_cache)}

@app.get("/admin/debug_ids", include_in_schema=False)
async def debug_ids():
    from src.seedcore.telemetry.server import mw_cache
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
    from seedcore.telemetry.stats import StatsCollector
    from seedcore.telemetry.metrics import ENERGY_SLOPE
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
        
        from seedcore.config.ray_config import configure_ray_remote
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
        heartbeat = tier0_manager.get_agent_heartbeat(agent_id)
        
        if heartbeat:
            return {"success": True, "heartbeat": heartbeat}
        else:
            return {"success": False, "message": f"Agent {agent_id} not found"}
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

