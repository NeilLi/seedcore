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
from fastapi import FastAPI
from typing import List, Dict

# Import our system components
from ..energy.api import energy_gradient_payload, _ledger
from ..control.fast_loop import fast_loop_select_agent
from ..control.slow_loop import slow_loop_update_roles, slow_loop_update_roles_simple, get_role_performance_metrics
from ..control.mem_loop import adaptive_mem_update, estimate_memory_gradient, get_memory_metrics
from ..organs.base import Organ
from ..organs.registry import OrganRegistry
from ..agents.base import Agent

# --- Persistent State ---
# Create a single, persistent registry when the server starts.
# This holds the state of our simulation.
print("Initializing persistent simulation state...")
SIMULATION_REGISTRY = OrganRegistry()

# Create a main organ
main_organ = Organ(organ_id="cognitive_organ_1")

# Create a few agents with different initial role probabilities
agents_to_create = [
    Agent(agent_id="agent_alpha", role_probs={'E': 0.6, 'S': 0.3, 'O': 0.1}),
    Agent(agent_id="agent_beta", role_probs={'E': 0.2, 'S': 0.7, 'O': 0.1}),
    Agent(agent_id="agent_gamma", role_probs={'E': 0.3, 'S': 0.3, 'O': 0.4}),
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
                "role_probs": agent.role_probs
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
        "compression_knob": compression_knob
    }

# --- Fast Loop Endpoints ---
@app.post('/actions/run_fast_loop')
def run_fast_loop_endpoint(task: str = "analyze_data"):
    """
    Runs a single fast loop step, selecting an agent and updating energy.
    """
    organ = SIMULATION_REGISTRY.get("cognitive_organ_1")
    selected_agent = fast_loop_select_agent(organ, task=task)
    
    return {
        "message": f"Fast loop selected agent '{selected_agent.agent_id}' for task '{task}'.",
        "selected_agent": {
            "id": selected_agent.agent_id,
            "capability": selected_agent.capability,
            "role_probs": selected_agent.role_probs
        },
        "new_energy_state": energy_gradient_payload()
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
    Runs the adaptive memory loop to adjust compression and memory utilization.
    """
    global compression_knob
    
    # Run the memory loop update
    compression_knob = adaptive_mem_update(SIMULATION_REGISTRY.all(), compression_knob)
    
    # Get memory metrics
    memory_metrics = get_memory_metrics(SIMULATION_REGISTRY.all())
    
    # Estimate memory gradient
    gradient = estimate_memory_gradient(SIMULATION_REGISTRY.all())
    
    return {
        "message": "Memory loop completed successfully!",
        "compression_knob": compression_knob,
        "memory_metrics": memory_metrics,
        "memory_gradient": gradient,
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
    """Resets the energy ledger back to zero."""
    _ledger.reset()
    return {"message": "Energy ledger has been reset."}

@app.get('/reset_energy')
def reset_energy():
    """Legacy endpoint: Resets the energy ledger back to zero."""
    _ledger.reset()
    return {"message": "Energy ledger has been reset."}

