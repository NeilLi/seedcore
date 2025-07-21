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

"""
Adaptive memory loop implementation.
Implements the dynamic calculation logic for memory utility and cost functions.
"""

from typing import Dict, List
import numpy as np

def calculate_dynamic_mem_util(agent, weights: Dict[str, float] = None) -> float:
    """
    Calculate dynamic memory utility for an agent based on their memory interactions.
    
    This implements the Update Equations from Section 4.1 of the energy validation document.
    
    Args:
        agent: The agent to calculate mem_util for
        weights: Dictionary of weights for different components
        
    Returns:
        float: The calculated mem_util score
    """
    if weights is None:
        weights = {
            'w_hit': 0.6,      # Weight for memory hits on writes
            'w_salience': 0.4   # Weight for salient events
        }
    
    # Calculate the score using the formula from Section 4.1
    hit_component = weights['w_hit'] * agent.memory_hits_on_writes
    salience_component = weights['w_salience'] * agent.salient_events_logged
    
    score = hit_component + salience_component
    
    # Normalize by total writes to get a rate rather than absolute count
    if agent.memory_writes > 0:
        score = score / agent.memory_writes
    
    return score

def calculate_cost_vq(memory_system, compression_knob: float) -> Dict[str, float]:
    """
    Calculate the CostVQ term representing the trade-off between memory usage and information quality.
    
    This implements the cost function described in Section 5 of the energy validation document.
    
    Args:
        memory_system: The SharedMemorySystem instance
        compression_knob: Current compression setting (0.0 to 1.0)
        
    Returns:
        Dict: Components of the cost calculation
    """
    # Get total bytes used across all tiers
    bytes_used = memory_system.Mw.bytes_used + memory_system.Mlt.bytes_used
    
    # Calculate reconstruction loss (inversely proportional to compression_knob)
    # Higher compression = more information loss
    recon_loss = 1.0 - compression_knob
    
    # Calculate staleness based on hit rate
    # Lower hit rate = higher staleness
    total_hits = memory_system.Mw.hit_count + memory_system.Mlt.hit_count
    total_data = len(memory_system.Mw.datastore) + len(memory_system.Mlt.datastore)
    
    if total_data > 0:
        hit_rate = total_hits / total_data
        staleness = 1.0 / (1.0 + hit_rate)
    else:
        staleness = 1.0  # Maximum staleness when no data exists
    
    # Calculate the weighted cost components
    # These weights can be tuned based on system requirements
    w_bytes = 0.4
    w_recon = 0.4
    w_staleness = 0.2
    
    cost_vq = (w_bytes * bytes_used / 1000.0) + (w_recon * recon_loss) + (w_staleness * staleness)
    
    return {
        'cost_vq': cost_vq,
        'bytes_used': bytes_used,
        'recon_loss': recon_loss,
        'staleness': staleness,
        'hit_rate': total_hits / max(total_data, 1),
        'components': {
            'bytes_component': w_bytes * bytes_used / 1000.0,
            'recon_component': w_recon * recon_loss,
            'staleness_component': w_staleness * staleness
        }
    }

def adaptive_mem_update(organs: List, compression_knob: float, 
                       memory_system, beta_mem: float = 1.0) -> float:
    """
    Update the compression knob based on memory energy gradient.
    
    This implements the adaptive memory control loop described in the document.
    
    Args:
        organs: List of organs containing agents
        compression_knob: Current compression setting
        memory_system: The SharedMemorySystem instance
        beta_mem: Weight for memory energy term
        
    Returns:
        float: Updated compression knob value
    """
    # Calculate current memory energy
    cost_vq_data = calculate_cost_vq(memory_system, compression_knob)
    current_mem_energy = beta_mem * cost_vq_data['cost_vq']
    
    # Calculate gradient by perturbing the compression knob
    perturbation = 0.01
    perturbed_cost_vq = calculate_cost_vq(memory_system, compression_knob + perturbation)
    perturbed_mem_energy = beta_mem * perturbed_cost_vq['cost_vq']
    
    # Calculate gradient: dE/dk
    gradient = (perturbed_mem_energy - current_mem_energy) / perturbation
    
    # Update compression knob using gradient descent
    learning_rate = 0.1
    new_compression_knob = compression_knob - learning_rate * gradient
    
    # Clamp to valid range [0.0, 1.0]
    new_compression_knob = max(0.0, min(1.0, new_compression_knob))
    
    return new_compression_knob

def get_memory_metrics(organs: List) -> Dict:
    """
    Get comprehensive memory metrics across all agents.
    
    Args:
        organs: List of organs containing agents
        
    Returns:
        Dict: Memory metrics including average mem_util and distribution
    """
    all_agents = [agent for organ in organs for agent in organ.agents]
    
    if not all_agents:
        return {
            'average_mem_util': 0.0,
            'total_memory_writes': 0,
            'total_memory_hits': 0,
            'total_salient_events': 0,
            'agent_count': 0
        }
    
    # Calculate individual mem_util scores
    mem_utils = []
    total_writes = 0
    total_hits = 0
    total_salient = 0
    
    for agent in all_agents:
        mem_util = calculate_dynamic_mem_util(agent)
        mem_utils.append(mem_util)
        total_writes += agent.memory_writes
        total_hits += agent.memory_hits_on_writes
        total_salient += agent.salient_events_logged
    
    return {
        'average_mem_util': np.mean(mem_utils),
        'mem_util_std': np.std(mem_utils),
        'mem_util_min': np.min(mem_utils),
        'mem_util_max': np.max(mem_utils),
        'total_memory_writes': total_writes,
        'total_memory_hits': total_hits,
        'total_salient_events': total_salient,
        'agent_count': len(all_agents),
        'individual_mem_utils': {agent.agent_id: mem_util for agent, mem_util in zip(all_agents, mem_utils)}
    }

def estimate_memory_gradient(organs: List) -> float:
    """
    Estimate the memory energy gradient for monitoring purposes.
    
    Args:
        organs: List of organs containing agents
        
    Returns:
        float: Estimated gradient value
    """
    # This is a simplified gradient estimation for monitoring
    # In practice, this would be calculated from actual energy measurements
    
    all_agents = [agent for organ in organs for agent in organ.agents]
    
    if not all_agents:
        return 0.0
    
    # Calculate a simple gradient based on memory utilization patterns
    total_writes = sum(agent.memory_writes for agent in all_agents)
    total_hits = sum(agent.memory_hits_on_writes for agent in all_agents)
    
    if total_writes > 0:
        hit_rate = total_hits / total_writes
        # Gradient is positive when hit rate is low (inefficient memory usage)
        # and negative when hit rate is high (efficient memory usage)
        gradient = 1.0 - hit_rate
    else:
        gradient = 0.0
    
    return gradient 