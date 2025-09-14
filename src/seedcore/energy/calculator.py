"""
Energy Model Foundation - unified energy function, term breakdown, gradients.
Implements the bijective mapping of operational costs to energy terms (pair, hyper,
role-entropy, L2 regularizer, memory cost) and exposes JSON-safe breakdowns.
"""

import ray  # type: ignore
import numpy as np  # type: ignore
import time
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING, Union
from dataclasses import dataclass, field, asdict
from .weights import EnergyWeights
from ..models.state import UnifiedState  # lightweight import; no heavy deps

# Avoid runtime circular import: only import RayAgent for typing
if TYPE_CHECKING:
    from seedcore.agents.ray_actor import RayAgent  # pragma: no cover
else:
    RayAgent = Any  # type: ignore


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
    
    # Get agent states for dynamic capability-based weighting
    agent_states = event.get('agent_states', {})
    if len(agent_states) >= 2:
        # Calculate dynamic pair weight based on min(ci, cj)
        from ..agents.lifecycle import calculate_pair_weight
        agent_ids = list(agent_states.keys())
        agent_i_state = agent_states[agent_ids[0]]
        agent_j_state = agent_states[agent_ids[1]]
        dynamic_weight = calculate_pair_weight(agent_i_state, agent_j_state)
        
        # Update weight with EWMA, incorporating dynamic capability
        stats['w'] = (1 - 0.1) * stats['w'] + 0.1 * (event['success'] * dynamic_weight)
    else:
        # Fallback to original logic
        stats['w'] = (1 - 0.1) * stats['w'] + 0.1 * event['success']
    
    stats['sim'] = event['sim']
    # Update the ledger (subtracting because lower energy is better)
    delta = (stats['w'] * stats['sim']) - ledger.pair
    ledger.pair += delta


def on_hyper_exec(event: Dict[str, Any], ledger: EnergyLedger):
    """Update hyper energy term after a cross-organ task."""
    # Placeholder for hyperedge logic - will be implemented in future
    pass


def on_role_update(event: Dict[str, Any], ledger: EnergyLedger, alpha: float):
    """Update entropy term when agent roles change."""
    delta = -alpha * (event['H_new'] - event['H_prev'])
    ledger.entropy += delta


def on_state_update(event: Dict[str, Any], ledger: EnergyLedger, lambda_reg: float):
    """Update regularization term when agent embeddings change."""
    delta = lambda_reg * (event['norm2_new'] - event['norm2_old'])
    ledger.reg += delta


def on_mem_event(event: Dict[str, Any], ledger: EnergyLedger, beta_mem: float):
    """Update memory term after memory operations."""
    base_cost = event['cost_delta']
    
    # Apply memory utility discount if agent state is provided
    agent_state = event.get('agent_state')
    if agent_state:
        from ..agents.lifecycle import apply_memory_discount
        discounted_cost = apply_memory_discount(agent_state, base_cost)
        delta = beta_mem * discounted_cost
    else:
        delta = beta_mem * base_cost
    
    ledger.mem += delta


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

    # Hyper term placeholder until HGNN integration supplies activations/weights
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


# New: Unified energy and gradients (paper §3 / §6)
def entropy_of_roles(P_roles: np.ndarray) -> float:
    q = np.clip(P_roles, 1e-8, 1.0)
    q = q / (q.sum(axis=1, keepdims=True) + 1e-8)
    return float(-(q * np.log(q)).sum())


def cost_vq(memory_stats: Dict[str, Any]) -> float:
    r = max(float(memory_stats.get("r_effective", 1.0)), 1.0)
    pcompr = float(memory_stats.get("p_compress", 0.0))
    return pcompr * (1.0 - 1.0 / r)


def energy_and_grad(
    state: Dict[str, Any],
    weights: EnergyWeights,
    memory_stats: Dict[str, Any],
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Compute term-wise energy and coarse gradients for controllers.

    state keys:
      - h_agents: np.ndarray [N, D]
      - P_roles: np.ndarray [N, 3]
      - hyper_sel: Optional[np.ndarray] [E]
      - s_norm: float
    """
    # Normalize and enforce dtypes/shapes
    H: np.ndarray = np.asarray(state.get("h_agents", np.zeros((0, 0), dtype=np.float32)), dtype=np.float32)
    P: np.ndarray = np.asarray(state.get("P_roles", np.zeros((0, 3), dtype=np.float32)), dtype=np.float32)
    E_raw = state.get("hyper_sel")
    if E_raw is None:
        E_sel: np.ndarray = np.asarray([], dtype=np.float32)
    else:
        E_sel = np.asarray(E_raw, dtype=np.float32)
        if E_sel.ndim == 0:
            E_sel = E_sel.reshape(1)
    s_norm: float = float(state.get("s_norm", 0.0))

    N = int(H.shape[0]) if H.ndim == 2 else 0
    K = int(E_sel.shape[0]) if E_sel.size > 0 else 0

    # Ensure weight matrices/vectors are compatible (do not mutate input weights)
    W_pair = weights.W_pair
    if N == 0:
        W_pair_adj = np.zeros((0, 0), dtype=np.float32)
    else:
        if W_pair.shape != (N, N):
            W_pair_adj = np.eye(N, dtype=np.float32) * 0.1
        else:
            W_pair_adj = W_pair.astype(np.float32, copy=False)

    if K <= 0:
        W_hyper_adj: Optional[np.ndarray] = None
    else:
        W_hyper_adj = getattr(weights, "W_hyper", np.ones((K,), dtype=np.float32)).astype(np.float32, copy=False)
        if W_hyper_adj.size != K:
            # Pad or truncate to match K
            if W_hyper_adj.size < K:
                W_hyper_adj = np.pad(W_hyper_adj, (0, K - W_hyper_adj.size), mode='edge')
            else:
                W_hyper_adj = W_hyper_adj[:K]

    # Terms
    if N == 0:
        pair = 0.0
        dE_dH = np.zeros_like(H, dtype=np.float32)
    else:
        pair = -float(np.sum(W_pair_adj * (H @ H.T)))
        dE_dH = -2.0 * (W_pair_adj @ H)

    if K <= 0 or W_hyper_adj is None:
        hyper = 0.0
        dE_dE_sel = None
    else:
        hyper = -float(np.sum(W_hyper_adj * E_sel))
        dE_dE_sel = -W_hyper_adj.copy()

    ent = -float(weights.alpha_entropy) * entropy_of_roles(P)
    reg = float(weights.lambda_reg) * (s_norm ** 2)
    mem = float(weights.beta_mem) * cost_vq(memory_stats)

    total = pair + hyper + ent + reg + mem
    breakdown = {
        "pair": float(pair),
        "hyper": float(hyper),
        "entropy": float(ent),
        "reg": float(reg),
        "mem": float(mem),
        "total": float(total),
    }

    grad = {
        "dE/dH": dE_dH.astype(np.float32, copy=False),
        "dE/dP_entropy": -float(weights.alpha_entropy),
        "dE/dE_sel": dE_dE_sel,
        "dE/ds_norm": 2.0 * float(weights.lambda_reg) * s_norm,
        "dE/dmem": float(weights.beta_mem),
    }
    return breakdown, grad


# Extended API for unified state users
@dataclass
class SystemParameters:
    """Compute-time parameters for the energy function.

    Holds model weights and auxiliary telemetry knobs that are not part of state.
    """
    weights: EnergyWeights
    memory_stats: Dict[str, Any]
    include_gradients: bool = True


@dataclass
class EnergyResult:
    """Lightweight result structure for in-process compute calls."""
    breakdown: Dict[str, float]
    gradients: Optional[Dict[str, Any]] = None


def compute_energy_unified(
    unified: Union[UnifiedState, Dict[str, Any]],
    params: SystemParameters,
) -> EnergyResult:
    """Convenience wrapper accepting UnifiedState or dict payload.

    - Ensures projection/guardrails if UnifiedState is provided via .projected().
    - Delegates to energy_and_grad or compute_energy based on params.include_gradients.
    """
    if hasattr(unified, "to_energy_state"):
        try:
            # Defensive projection before compute
            unified = unified.projected()  # type: ignore[assignment]
        except Exception:
            pass
        state = unified.to_energy_state()  # type: ignore[assignment]
    else:
        # Assume dict-like already in energy-state format or similar
        u = unified  # type: ignore[assignment]
        state = u

    # Enforce dtypes/shapes (canonicalization)
    H = np.asarray(state.get("h_agents", np.zeros((0, 0), dtype=np.float32)), dtype=np.float32)
    P = np.asarray(state.get("P_roles", np.zeros((0, 3), dtype=np.float32)), dtype=np.float32)
    E_sel = np.asarray(state.get("hyper_sel", np.asarray([], dtype=np.float32)), dtype=np.float32)
    if E_sel.ndim == 0:
        E_sel = E_sel.reshape(1)
    s_norm = float(state.get("s_norm", 0.0))
    state_dict = {"h_agents": H, "P_roles": P, "hyper_sel": E_sel, "s_norm": s_norm}

    # Compute
    bd, gd = energy_and_grad(state_dict, params.weights, params.memory_stats)
    if "total" not in bd:
        bd["total"] = sum(float(bd.get(k, 0.0)) for k in ("pair", "hyper", "entropy", "reg", "mem"))
    return EnergyResult(breakdown=bd, gradients=(gd if params.include_gradients else None))


def compute_energy(
    H: np.ndarray,
    P: np.ndarray,
    weights: EnergyWeights,
    memory_stats: Dict[str, Any],
    E_sel: Optional[np.ndarray] = None,
    s_norm: float = 0.0,
) -> Tuple[float, Dict[str, float]]:
    """Compute total energy and per-term breakdown (includes hyper term)."""
    pair = -float(np.sum(weights.W_pair * (H @ H.T)))
    
    # Handle hyper term with proper dimension matching
    if E_sel is not None and E_sel.size > 0:
        W_hyper = getattr(weights, "W_hyper", np.array([1.0]))
        # Ensure W_hyper matches E_sel dimensions
        if W_hyper.size != E_sel.size:
            # Pad or truncate W_hyper to match E_sel size
            if W_hyper.size < E_sel.size:
                # Pad with the last value
                W_hyper = np.pad(W_hyper, (0, E_sel.size - W_hyper.size), mode='edge')
            else:
                # Truncate to match E_sel size
                W_hyper = W_hyper[:E_sel.size]
        hyper = -float(np.sum(W_hyper * E_sel))
    else:
        hyper = 0.0
    
    ent = -float(weights.alpha_entropy) * entropy_of_roles(P)
    reg = float(weights.lambda_reg) * (s_norm ** 2)
    mem = float(weights.beta_mem) * cost_vq(memory_stats)
    total = pair + hyper + ent + reg + mem
    return total, {"pair": pair, "hyper": hyper, "entropy": ent, "reg": reg, "mem": mem}


def role_entropy_grad(P_roles: np.ndarray) -> np.ndarray:
    """Safe, bounded gradient of entropy wrt P (for controllers)."""
    q = np.clip(P_roles, 1e-8, 1.0)
    q = q / (q.sum(axis=1, keepdims=True) + 1e-8)
    # d/dp (-sum p log p) = -(log p + 1); we return per-entry gradient
    return -(np.log(q) + 1.0)


def energy_gradient(unified_state: Any, weights: EnergyWeights) -> Dict[str, Any]:
    """Return lightweight partial gradients for controllers (pair, entropy, mem)."""
    H = unified_state.H_matrix()
    P = unified_state.P_matrix()
    d_pair_dH = -2.0 * (weights.W_pair @ H)
    d_ent_dP = -float(weights.alpha_entropy) * role_entropy_grad(P)
    d_mem_dCost = float(weights.beta_mem)
    return {"d_pair_dH": d_pair_dH, "d_ent_dP": d_ent_dP, "d_mem_dCost": d_mem_dCost}


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