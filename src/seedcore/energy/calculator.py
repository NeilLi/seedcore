"""
Energy Model Foundation - Real Implementation

This module implements the core energy calculation engine based on the Cognitive Organism Architecture (COA).
It provides incremental energy updates using EnergyLedger and real energy calculations.
"""

import ray
import numpy as np
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from seedcore.agents.ray_actor import RayAgent


@dataclass
class EnergyTerms:
    """Represents the individual terms of the Unified Energy Function."""
    pair: float = 0.0
    hyper: float = 0.0
    entropy: float = 0.0
    reg: float = 0.0
    mem: float = 0.0
    total: float = 0.0


@dataclass
class EnergyLedger:
    """A ledger for incrementally updating energy terms to avoid re-computation."""
    terms: EnergyTerms = field(default_factory=EnergyTerms)
    # Caches for incremental updates
    pair_stats: Dict[tuple, Dict[str, Any]] = field(default_factory=dict)
    hyper_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    role_entropy: Dict[str, float] = field(default_factory=dict)
    mem_stats: Dict[str, float] = field(default_factory=dict)

    def get_total(self) -> float:
        """Calculate and return the total energy."""
        self.terms.total = (self.terms.pair + self.terms.hyper +
                           self.terms.entropy + self.terms.reg + self.terms.mem)
        return self.terms.total


def on_pair_success(event: Dict[str, Any], ledger: EnergyLedger):
    """Update pair energy term after a multi-agent task."""
    pair_key = tuple(sorted(event['agents']))
    if pair_key not in ledger.pair_stats:
        ledger.pair_stats[pair_key] = {'w': 0.0, 'sim': 0.0}
    
    stats = ledger.pair_stats[pair_key]
    # Update weight with an EWMA
    stats['w'] = (1 - 0.1) * stats['w'] + 0.1 * event['success']
    stats['sim'] = event['sim']
    # Update the ledger (subtracting because lower energy is better)
    delta = (stats['w'] * stats['sim']) - ledger.terms.pair
    ledger.terms.pair += delta


def on_hyper_exec(event: Dict[str, Any], ledger: EnergyLedger):
    """Update hyper energy term after a cross-organ task."""
    # Placeholder for hyperedge logic - will be implemented in future
    pass


def on_role_update(event: Dict[str, Any], ledger: EnergyLedger, alpha: float):
    """Update entropy term when agent roles change."""
    delta = -alpha * (event['H_new'] - event['H_prev'])
    ledger.terms.entropy += delta


def on_state_update(event: Dict[str, Any], ledger: EnergyLedger, lambda_reg: float):
    """Update regularization term when agent embeddings change."""
    delta = lambda_reg * (event['norm2_new'] - event['norm2_old'])
    ledger.terms.reg += delta


def on_mem_event(event: Dict[str, Any], ledger: EnergyLedger, beta_mem: float):
    """Update memory term after memory operations."""
    delta = beta_mem * event['cost_delta']
    ledger.terms.mem += delta


def calculate_energy(state: Dict[str, Any]) -> EnergyTerms:
    """
    Calculates the total energy based on the full system state.
    This function implements Equation (2) from the COA paper.
    """
    agents = state['agents']
    memory_stats = state.get('memory_stats', {})
    pair_stats = state.get('pair_stats', {})
    
    # Coefficients from config or state
    alpha = state.get('alpha', 0.1)
    lambda_reg = state.get('lambda_reg', 0.01)
    beta_mem = state.get('beta_mem', 0.05)

    # Pair Term: -∑(wij * sim(hi, hj))
    pair_term = -sum(
        stats['w'] * stats['sim']
        for stats in pair_stats.values()
    )

    # Entropy Term: H(p) = -∑ p * log(p)
    entropy_term = 0.0
    for agent in agents:
        # Get role probabilities from agent
        heartbeat = ray.get(agent.get_heartbeat.remote())
        role_probs = heartbeat['role_probs']
        # Calculate entropy for this agent
        agent_entropy = -sum(p * np.log2(p + 1e-9) for p in role_probs.values())
        entropy_term += agent_entropy
    entropy_term = -alpha * entropy_term

    # Regularization Term: λ||s||²
    reg_term = 0.0
    for agent in agents:
        h = ray.get(agent.get_state_embedding.remote())
        reg_term += np.linalg.norm(h)**2
    reg_term = lambda_reg * reg_term

    # Memory Term: β * CostVQ(M)
    mem_term = beta_mem * memory_stats.get('cost_vq', 0.0)

    # Hyper term is still a placeholder
    hyper_term = 0.0
    
    total = pair_term + hyper_term + entropy_term + reg_term + mem_term

    return EnergyTerms(
        pair=pair_term, hyper=hyper_term, entropy=entropy_term,
        reg=reg_term, mem=mem_term, total=total
    )


def energy_gradient_payload(ledger: EnergyLedger) -> Dict[str, Any]:
    """
    Returns the JSON payload for the /energy/gradient telemetry endpoint.
    """
    return {
        "ts": time.time(),
        "E_terms": asdict(ledger.terms),
        "deltaE_last": ledger.mem_stats.get('last_delta', 0.0),
        "pair_stats_count": len(ledger.pair_stats),
        "hyper_stats_count": len(ledger.hyper_stats),
        "role_entropy_count": len(ledger.role_entropy),
        "mem_stats_count": len(ledger.mem_stats)
    }


# Legacy functions for backward compatibility
def calculate_pair_energy(agents: List[RayAgent]) -> float:
    """
    Legacy function for backward compatibility.
    Calculates the pairwise collaboration energy.
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
    Legacy function for backward compatibility.
    Calculates the role diversity energy.
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
    Legacy function for backward compatibility.
    Calculates the regularization energy.
    """
    total_norm_sq = 0.0
    for agent in agents:
        h = ray.get(agent.get_state_embedding.remote())
        total_norm_sq += np.sum(h**2)
        
    return lambda_reg * total_norm_sq


def calculate_mem_energy(memory_system, beta_mem: float = 0.2) -> float:
    """
    Legacy function for backward compatibility.
    Calculates the memory pressure and information loss energy.
    """
    try:
        from seedcore.memory.adaptive_loop import calculate_cost_vq
        
        # You'll need access to the memory system and the compression knob
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
    Legacy function for backward compatibility.
    Calculates the total unified energy by summing all terms.
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