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
from fastapi import FastAPI
from typing import List, Dict

# Import our system components
from ..energy.api import energy_gradient_payload, _ledger
from ..energy.pair_stats import PairStatsTracker
from ..control.fast_loop import fast_loop_select_agent
from ..control.slow_loop import slow_loop_update_roles, slow_loop_update_roles_simple, get_role_performance_metrics
from ..control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from ..organs.base import Organ
from ..organs.registry import OrganRegistry
from ..agents.base import Agent
from ..memory.system import SharedMemorySystem
from ..memory.adaptive_loop import (
    calculate_dynamic_mem_util, 
    calculate_cost_vq, 
    adaptive_mem_update as new_adaptive_mem_update,
    get_memory_metrics as new_get_memory_metrics,
    estimate_memory_gradient as new_estimate_memory_gradient
)

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
# --- End Persistent State ---

app = FastAPI()

def cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    
    return dot_product / (norm_v1 * norm_v2)

@app.get('/energy/gradient')
def energy_gradient():
    """Returns the current state of the energy ledger."""
    return energy_gradient_payload()

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

