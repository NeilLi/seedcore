"""
Energy Model Foundation - Unified Energy Function Calculator

This module implements the core energy calculation engine based on the Cognitive Organism Architecture (COA).
It contains functions to calculate each of the five core energy terms that make up the Unified Energy Function.
"""

import ray
import numpy as np
from typing import Dict, List, Optional
from seedcore.agents.ray_actor import RayAgent


def calculate_pair_energy(agents: List[RayAgent]) -> float:
    """
    Calculates the pairwise collaboration energy.
    Formula: -∑(wij * sim(hi, hj))
    
    This term rewards stable and successful agent collaborations.
    """
    pair_energy = 0.0
    if len(agents) < 2:
        return 0.0

    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            agent1 = agents[i]
            agent2 = agents[j]
            
            # Get embeddings (h) from agents using Ray remote calls
            h1 = ray.get(agent1.get_state_embedding.remote())
            h2 = ray.get(agent2.get_state_embedding.remote())
            
            # Cosine similarity
            sim = np.dot(h1, h2) / (np.linalg.norm(h1) * np.linalg.norm(h2))
            wij = 1.0  # Placeholder for learned weight
            pair_energy -= wij * sim
            
    return pair_energy


def calculate_entropy_energy(agents: List[RayAgent], alpha: float = 0.5) -> float:
    """
    Calculates the role diversity energy.
    Formula: -α * H(p)
    
    This term maintains role diversity for exploration.
    """
    total_entropy = 0.0
    for agent in agents:
        # Get role probabilities using Ray remote call
        heartbeat = ray.get(agent.get_heartbeat.remote())
        role_probs = np.array(list(heartbeat["role_probs"].values()))
        # Add a small epsilon to prevent log(0)
        entropy = -np.sum(role_probs * np.log2(role_probs + 1e-9))
        total_entropy += entropy
        
    return -alpha * total_entropy


def calculate_reg_energy(agents: List[RayAgent], lambda_reg: float = 0.01) -> float:
    """
    Calculates the regularization energy.
    Formula: λ_reg * ||s||₂²
    
    This term penalizes overall state complexity.
    """
    total_norm_sq = 0.0
    for agent in agents:
        h = ray.get(agent.get_state_embedding.remote())
        total_norm_sq += np.sum(h**2)
        
    return lambda_reg * total_norm_sq


def calculate_mem_energy(memory_system, beta_mem: float = 0.2) -> float:
    """
    Calculates the memory pressure and information loss energy.
    Formula: β_mem * CostVQ(M)
    
    This requires the CostVQ function from your memory system.
    """
    # This assumes you have a `calculate_cost_vq` function available
    # from your memory loop implementation.
    try:
        from seedcore.memory.adaptive_loop import calculate_cost_vq
        
        # You'll need access to the memory system and the compression knob
        # This might be passed in or accessed from a global state.
        compression_knob = 0.5  # Placeholder
        cost_vq_data = calculate_cost_vq(memory_system, compression_knob)
        
        return beta_mem * cost_vq_data['cost_vq']
    except ImportError:
        # Fallback if adaptive_loop is not available
        print("Warning: adaptive_loop not available, using placeholder for memory energy")
        return beta_mem * 0.1  # Placeholder value


def calculate_total_energy(
    agents: List[RayAgent],
    memory_system,
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, float]:
    """
    Calculates the total unified energy by summing all terms.
    
    Args:
        agents: List of RayAgent instances
        memory_system: Memory system instance
        weights: Dictionary of energy weights (alpha, lambda_reg, beta_mem)
    
    Returns:
        Dictionary containing all energy terms and total
    """
    if weights is None:
        weights = {}
    
    pair = calculate_pair_energy(agents)
    # hyper term is stubbed as it requires complex pattern tracking
    hyper = 0.0 
    entropy = calculate_entropy_energy(agents, weights.get('alpha', 0.5))
    reg = calculate_reg_energy(agents, weights.get('lambda_reg', 0.01))
    mem = calculate_mem_energy(memory_system, weights.get('beta_mem', 0.2))
    
    total = pair + hyper + entropy + reg + mem
    
    return {
        "pair": pair,
        "hyper": hyper,
        "entropy": entropy,
        "reg": reg,
        "mem": mem,
        "total": total
    } 