"""
Energy-Aware Agent Selection Optimizer

This module implements the energy gradient proxy system for intelligent agent selection
based on the Cognitive Organism Architecture (COA) specifications.
"""

import ray
from typing import Dict, List, Any, Optional, Tuple
from seedcore.agents.ray_actor import RayAgent
import numpy as np
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger.addHandler(handler)


def score_agent(agent: RayAgent, task: Dict[str, Any]) -> float:
    """
    Scores an agent for a task based on the energy gradient proxy.
    score = w_pair * ΔE_pair + w_hyper * ΔE_hyper - w_explore * ΔH
    
    Args:
        agent: The agent to evaluate
        task: Task information and requirements
    
    Returns:
        Suitability score (lower is better)
    """
    try:
        # Get energy proxy from agent
        proxy = ray.get(agent.get_energy_proxy.remote())
        
        # Expected change in pairwise energy (simplified)
        # Lower is better, so high capability leads to a better score
        epair_delta = 1.0 - proxy['capability']
        
        # Expected gain in entropy (higher is better)
        # This encourages exploration by favoring agents that increase diversity
        entropy_gain = proxy['entropy_contribution']
        
        # Memory utilization penalty
        mem_penalty = proxy['mem_util'] * 0.3
        
        # State complexity penalty
        state_penalty = proxy['state_norm'] * 0.01
        
        # Weights for each term (could be dynamic)
        w_pair = 1.0
        w_explore = 0.2
        w_mem = 0.3
        w_state = 0.01
        
        # Final score to be minimized
        score = (w_pair * epair_delta) - (w_explore * entropy_gain) + (w_mem * mem_penalty) + (w_state * state_penalty)
        
        return score
        
    except Exception as e:
        logger.error(f"Error scoring agent: {e}")
        return float('inf')  # Worst possible score


def select_best_agent(agent_pool: List[RayAgent], task: Dict[str, Any]) -> Tuple[Optional[RayAgent], float]:
    """
    Selects the best agent from a pool by finding the one with the
    minimum energy score (arg-min).
    
    Args:
        agent_pool: List of available agents
        task: Task information and requirements
    
    Returns:
        Tuple of (best_agent, predicted_delta_e)
    """
    if not agent_pool:
        return None, float('inf')
    
    # Filter for agents that meet the basic requirements for the task
    available_agents = []
    for agent in agent_pool:
        try:
            # Check if agent is available (basic requirement)
            if hasattr(agent, 'is_available') and callable(getattr(agent, 'is_available')):
                is_available = ray.get(agent.is_available.remote())
            else:
                is_available = True  # Assume available if method doesn't exist
            
            # Check capability requirement if specified
            required_capability = task.get('required_capability', 0.0)
            if required_capability > 0:
                proxy = ray.get(agent.get_energy_proxy.remote())
                has_capability = proxy['capability'] >= required_capability
            else:
                has_capability = True
            
            if is_available and has_capability:
                available_agents.append(agent)
                
        except Exception as e:
            logger.warning(f"Error checking agent availability: {e}")
            continue

    if not available_agents:
        logger.warning("No available agents meet task requirements")
        return None, float('inf')

    # Score all available agents
    agent_scores = []
    for agent in available_agents:
        try:
            score = score_agent(agent, task)
            agent_scores.append((agent, score))
        except Exception as e:
            logger.error(f"Error scoring agent: {e}")
            continue
    
    if not agent_scores:
        logger.error("No agents could be scored")
        return None, float('inf')
    
    # Find the agent with minimum score
    best_agent, min_score = min(agent_scores, key=lambda x: x[1])
    
    # Predicted ΔE is approximated by the score
    predicted_delta_e = min_score
    
    return best_agent, predicted_delta_e


def calculate_agent_suitability_score(
    agent: RayAgent, 
    task_data: Dict[str, Any],
    weights: Dict[str, float]
) -> float:
    """
    Legacy function for backward compatibility.
    Calculates an agent's suitability for a task based on an energy gradient proxy.
    """
    # Get default weights if not provided
    w_pair = weights.get('w_pair', 1.0)
    w_hyper = weights.get('w_hyper', 1.0)
    w_explore = weights.get('w_explore', 0.2)
    
    try:
        # Get energy proxy from agent
        proxy = ray.get(agent.get_energy_proxy.remote())
        
        # 1. Capability Score: Higher capability is better (lower energy cost)
        capability = proxy['capability']
        
        # 2. Role Match: Better role match for the task is better
        task_type = task_data.get("type", "general")
        ideal_role = get_ideal_role_for_task(task_type)
        heartbeat = ray.get(agent.get_heartbeat.remote())
        role_match = heartbeat["role_probs"].get(ideal_role, 0.0)
        
        # 3. Current Energy State: Consider agent's current energy contribution
        energy_state = ray.get(agent.get_energy_state.remote())
        current_energy = energy_state.get("total", 0.0)
        
        # 4. Task Complexity Estimation
        task_complexity = estimate_task_complexity(task_data)
        
        # 5. Memory Utilization: Consider current memory pressure
        mem_util = proxy['mem_util']
        
        # Calculate the suitability score
        # Lower score = better suitability (will minimize energy increase)
        capability_penalty = (1.0 - capability) * task_complexity
        role_mismatch_penalty = (1.0 - role_match) * 0.5
        energy_penalty = current_energy * 0.1  # Small penalty for high current energy
        memory_penalty = mem_util * 0.3  # Penalty for high memory utilization
        
        score = (capability_penalty + 
                 role_mismatch_penalty + 
                 energy_penalty + 
                 memory_penalty)
        
        agent_id = ray.get(agent.get_id.remote())
        logger.debug(f"Agent {agent_id} suitability score: {score:.4f} "
                    f"(capability: {capability:.3f}, role_match: {role_match:.3f}, "
                    f"energy: {current_energy:.3f}, mem_util: {mem_util:.3f})")
        
        return score
        
    except Exception as e:
        logger.error(f"Error calculating suitability score: {e}")
        return float('inf')


def get_ideal_role_for_task(task_type: str) -> str:
    """
    Maps task types to ideal agent roles.
    
    Args:
        task_type: Type of task to be performed
    
    Returns:
        Ideal role for the task
    """
    role_mapping = {
        "optimization": "S",      # Specialist for optimization tasks
        "exploration": "E",       # Explorer for exploration tasks
        "analysis": "S",          # Specialist for analysis
        "discovery": "E",         # Explorer for discovery
        "execution": "S",         # Specialist for execution
        "research": "E",          # Explorer for research
        "general": "E",           # Default to explorer for general tasks
    }
    
    return role_mapping.get(task_type, "E")


def estimate_task_complexity(task_data: Dict[str, Any]) -> float:
    """
    Estimates the complexity of a task based on its characteristics.
    
    Args:
        task_data: Task information
    
    Returns:
        Complexity score (0.0 to 1.0)
    """
    complexity = 0.5  # Base complexity
    
    # Adjust based on task type
    task_type = task_data.get("type", "general")
    if task_type in ["optimization", "analysis"]:
        complexity += 0.3
    elif task_type in ["exploration", "discovery"]:
        complexity += 0.2
    
    # Adjust based on task size/scope
    task_size = task_data.get("size", "medium")
    if task_size == "large":
        complexity += 0.2
    elif task_size == "small":
        complexity -= 0.1
    
    # Adjust based on urgency
    if task_data.get("urgent", False):
        complexity += 0.1
    
    # Clamp to [0.1, 1.0]
    return max(0.1, min(1.0, complexity))


def rank_agents_by_suitability(
    agents: List[RayAgent],
    task_data: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None
) -> List[tuple[RayAgent, float]]:
    """
    Ranks agents by their suitability for a task.
    
    Args:
        agents: List of available agents
        task_data: Task information and requirements
        weights: Energy weights for scoring
    
    Returns:
        List of (agent, score) tuples, sorted by score (ascending)
    """
    if not agents:
        return []
    
    if weights is None:
        weights = {}
    
    agent_scores = []
    
    for agent in agents:
        try:
            score = calculate_agent_suitability_score(agent, task_data, weights)
            agent_scores.append((agent, score))
        except Exception as e:
            logger.error(f"Error evaluating agent {agent.get_id()}: {e}")
            continue
    
    # Sort by score (ascending - lower is better)
    agent_scores.sort(key=lambda x: x[1])
    
    return agent_scores 