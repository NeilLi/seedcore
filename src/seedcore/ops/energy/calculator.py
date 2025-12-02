"""
Energy Calculator (Unified Physics Engine).
Implements the Unified Energy Function E(s_t) from §3.1.2.
"""

import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional, Union, Tuple

from .weights import EnergyWeights
from seedcore.models.state import UnifiedState

# ----------------------------------------------------------------------
# 1. PARAMETERS & RESULTS
# ----------------------------------------------------------------------


@dataclass
class SystemParameters:
    """
    Compute-time parameters for the energy function.
    Holds model weights (W_ij, alpha, beta) and telemetry knobs.
    """

    weights: EnergyWeights
    memory_stats: Dict[str, Any]
    include_gradients: bool = False
    ml_stats: Optional[Dict[str, Any]] = None


@dataclass
class EnergyResult:
    """
    Standard output payload for energy calculations.
    """

    breakdown: Dict[str, float]
    gradients: Optional[Dict[str, Any]] = None


# ----------------------------------------------------------------------
# 2. ENERGY CALCULATION
# ----------------------------------------------------------------------


def compute_energy_unified(
    unified: Union[UnifiedState, Dict[str, Any]],
    params: SystemParameters,
) -> EnergyResult:
    """
    Calculates E(s_t) according to Equation (2).
    Accepts either a UnifiedState object or a raw dictionary payload.
    """
    # A. Normalize Input State
    if hasattr(unified, "to_energy_state"):
        try:
            # Defensive projection (Simplex/Clamping)
            state_obj = unified.projected()
            state_dict = state_obj.to_energy_state()
        except Exception:
            # Fallback if projection fails
            state_dict = unified.to_energy_state()  # type: ignore[attr-defined]
    else:
        # It's a dict (e.g. from JSON payload)
        state_dict = unified  # type: ignore[assignment]

    # B. Extract Matrices (with defaults)
    H = np.asarray(state_dict.get("h_agents", []), dtype=np.float32)
    P = np.asarray(state_dict.get("P_roles", []), dtype=np.float32)
    E_sel = np.asarray(state_dict.get("hyper_sel", []), dtype=np.float32)
    s_norm = float(state_dict.get("s_norm", 0.0))

    # C. Compute Basic Terms
    breakdown, gradients = _energy_terms_and_grad(
        H=H,
        P=P,
        E_sel=E_sel,
        s_norm=s_norm,
        weights=params.weights,
        memory_stats=params.memory_stats,
    )

    # D. Add Drift/Anomaly Bias (Real-world grounding)
    ml_stats = params.ml_stats or {}

    drift_score = float(ml_stats.get("drift", 0.0))
    anomaly_score = float(ml_stats.get("anomaly", 0.0))

    E_drift = float(getattr(params.weights, "lambda_drift", 0.0)) * drift_score
    E_anomaly = float(getattr(params.weights, "mu_anomaly", 0.0)) * anomaly_score

    # E. Aggregate Total
    base_total = float(breakdown.get("total", 0.0))
    final_total = base_total + E_drift + E_anomaly

    breakdown["drift_term"] = E_drift
    breakdown["anomaly_term"] = E_anomaly
    breakdown["total"] = final_total

    return EnergyResult(
        breakdown=breakdown,
        gradients=gradients if params.include_gradients else None,
    )


# ----------------------------------------------------------------------
# 3. TERM COMPUTATION HELPER
# ----------------------------------------------------------------------


def _energy_terms_and_grad(
    H: np.ndarray,
    P: np.ndarray,
    E_sel: np.ndarray,
    s_norm: float,
    weights: EnergyWeights,
    memory_stats: Dict[str, Any],
) -> Tuple[Dict[str, float], Optional[Dict[str, Any]]]:
    """
    Computes the 5 core terms (Pair, Hyper, Entropy, Reg, Mem) and their gradients.
    """
    # 1. Dimensions
    N = int(H.shape[0]) if H.ndim == 2 else 0
    K = int(E_sel.shape[0]) if E_sel.size > 0 else 0

    # 2. Pairwise Term: - sum(w_ij * h_i * h_j)
    if N > 0:
        # Resize W_pair if needed (defensive)
        W_pair = weights.W_pair
        if W_pair.shape != (N, N):
            # Fallback identity if shape mismatch
            W_pair = np.eye(N, dtype=np.float32) * 0.1

        E_pair = -float(np.sum(W_pair * (H @ H.T)))
        dE_dH = -2.0 * (W_pair @ H)  # Gradient
    else:
        E_pair = 0.0
        dE_dH = np.zeros_like(H)

    # 3. Hyperedge Term: - sum(w_e * E_sel)
    if K > 0:
        W_hyper = getattr(weights, "W_hyper", np.ones(K, dtype=np.float32))
        # Resize W_hyper if needed
        if W_hyper.size < K:
            W_hyper = np.pad(W_hyper, (0, K - W_hyper.size), mode="edge")
        elif W_hyper.size > K:
            W_hyper = W_hyper[:K]

        E_hyper = -float(np.sum(W_hyper * E_sel))
        dE_dE_sel = -W_hyper  # Gradient
    else:
        E_hyper = 0.0
        dE_dE_sel = None

    # 4. Entropy Term: - alpha * H(P)
    # Rewards role diversity
    E_ent = -float(weights.alpha_entropy) * _entropy_of_roles(P)

    # 5. Regularization Term: lambda * ||s||^2
    # Penalizes complexity
    E_reg = float(weights.lambda_reg) * (s_norm**2)

    # 6. Memory Cost: beta * CostVQ
    # Penalizes storage/compute
    E_mem = float(weights.beta_mem) * _cost_vq(memory_stats)

    # Breakdown
    total = E_pair + E_hyper + E_ent + E_reg + E_mem
    breakdown = {
        "pair": E_pair,
        "hyper": E_hyper,
        "entropy": E_ent,
        "reg": E_reg,
        "mem": E_mem,
        "total": total,
    }

    # Gradients
    gradients = {
        "dE/dH": dE_dH,
        "dE/dE_sel": dE_dE_sel,
        "dE/ds_norm": 2.0 * float(weights.lambda_reg) * s_norm,
        "dE/dmem": float(weights.beta_mem),
    }

    return breakdown, gradients


# ----------------------------------------------------------------------
# 4. LOW-LEVEL MATH HELPERS
# ----------------------------------------------------------------------


def _entropy_of_roles(P_roles: np.ndarray) -> float:
    """Computes sum of Shannon entropy across all agents."""
    if P_roles.size == 0:
        return 0.0
    # Safe log
    q = np.clip(P_roles, 1e-8, 1.0)
    # Normalize rows to be sure
    q = q / (q.sum(axis=1, keepdims=True) + 1e-8)
    return float(-(q * np.log(q)).sum())


def _cost_vq(memory_stats: Dict[str, Any]) -> float:
    """
    Approximates the 'Vector Quantization Cost' from memory stats.
    Cost = Storage_Pressure + Compression_Overhead
    """
    # r_effective: Effective compression ratio (e.g. 2.0 = 50% savings)
    r = max(float(memory_stats.get("r_effective", 1.0)), 1.0)
    # p_compress: Probability of running compression (CPU cost)
    pcompr = float(memory_stats.get("p_compress", 0.0))

    # Heuristic: High compression saves storage (1/r) but costs CPU (pcompr)
    # We want to balance these.
    # Cost = CPU_Work * (Efficiency_Gain)
    return pcompr * (1.0 - 1.0 / r)
