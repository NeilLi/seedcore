"""
Energy-Aware Agent Selection Optimizer

This module implements the energy gradient proxy system for intelligent agent selection.
It calculates agent suitability scores based on energy optimization principles.
"""

import ray
from typing import Dict, List, Any, Optional
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


def calculate_agent_suitability_score(
    agent: RayAgent, 
    task_data: Dict[str, Any],
    weights: Dict[str, float]
) -> float:
    """
    Calculates an agent's suitability for a task based on an energy gradient proxy.
    The agent with the lowest score is the most suitable, as it's expected to
    minimize the energy increase (or maximize the decrease).
    
    Formula from the paper:
    score_i = w_pair * E_pair_delta(i,t) + w_hyper * E_hyper_delta(i,t) - w_explore * entropy-gain(i)
    
    Args:
        agent: The agent to evaluate
        task_data: Task information and requirements
        weights: Energy weights for different terms
    
    Returns:
        Suitability score (lower is better)
    """
    # Get default weights if not provided
    w_pair = weights.get('w_pair', 1.0)
    w_hyper = weights.get('w_hyper', 1.0)
    w_explore = weights.get('w_explore', 0.2)
    
    # 1. Capability Score: Higher capability is better (lower energy cost)
    summary_stats = ray.get(agent.get_summary_stats.remote())
    capability = summary_stats.get("capability_score", 0.5)
    
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
    mem_util = summary_stats.get("mem_util", 0.0)
    
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


def select_best_agent(
    agents: List[RayAgent], 
    task_data: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None
) -> Optional[RayAgent]:
    """
    Selects the best agent for a task by minimizing the suitability score.
    
    Args:
        agents: List of available agents
        task_data: Task information and requirements
        weights: Energy weights for scoring
    
    Returns:
        Best agent for the task, or None if no agents available
    """
    if not agents:
        logger.warning("No agents available for task execution")
        return None
    
    if weights is None:
        weights = {}
    
    best_agent = None
    min_score = float('inf')
    
    logger.info(f"Evaluating {len(agents)} agents for task: {task_data.get('type', 'unknown')}")
    
    for agent in agents:
        try:
            score = calculate_agent_suitability_score(agent, task_data, weights)
            if score < min_score:
                min_score = score
                best_agent = agent
        except Exception as e:
            logger.error(f"Error evaluating agent {agent.get_id()}: {e}")
            continue
    
    if best_agent:
        best_agent_id = ray.get(best_agent.get_id.remote())
        logger.info(f"Selected agent {best_agent_id} with score {min_score:.4f}")
    else:
        logger.error("Could not select any agent")
    
    return best_agent


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