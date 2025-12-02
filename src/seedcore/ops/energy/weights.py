"""
Energy Weights Container & Adaptation Logic.

Manages the coefficients for the Unified Energy Function E(s_t).
Ensures weights remain bounded (non-expansive) to guarantee system stability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any
import numpy as np

# Safety bounds for scalar coefficients to prevent runaway adaptation
MIN_SCALAR = 0.001
MAX_SCALAR = 10.0

@dataclass
class EnergyWeights:
    """
    Container for energy weights with projection logic.
    
    Matrices:
    - W_pair: (N, N) Symmetric pairwise collaboration weights.
    - W_hyper: (K,) Hyperedge pattern weights.
    
    Scalars (The "Knobs"):
    - alpha_entropy: Role diversity reward (higher = more exploration).
    - lambda_reg: L2 Regularization (higher = penalize complexity/load).
    - beta_mem: Memory cost penalty (higher = compress more aggressive).
    - lambda_drift: Stabilizer for ML drift term.
    - mu_anomaly: Stabilizer for ML anomaly term.
    """

    W_pair: np.ndarray  
    W_hyper: np.ndarray  
    
    alpha_entropy: float
    lambda_reg: float
    beta_mem: float
    
    lambda_drift: float = 0.0
    mu_anomaly: float = 0.0

    def project(self, r_pair: float = 1.0, r_hyper: float = 1.0) -> None:
        """
        Enforce spectral constraints to keep maps non-expansive.
        This prevents feedback loops from exploding.
        """
        # 1. Symmetrize and Clip Spectral Norm for W_pair
        if self.W_pair.size > 0 and self.W_pair.ndim == 2:
            # Enforce symmetry: W = (W + W.T) / 2
            self.W_pair = 0.5 * (self.W_pair + self.W_pair.T)
            
            # Clip spectral norm (max singular value)
            # We use 2-norm (spectral norm)
            spectral_norm = float(np.linalg.norm(self.W_pair, 2))
            if spectral_norm > r_pair and spectral_norm > 1e-9:
                scale = r_pair / spectral_norm
                self.W_pair *= scale

        # 2. Clip Element-wise for Hyperedge Weights
        if self.W_hyper.size > 0:
            np.clip(self.W_hyper, -r_hyper, r_hyper, out=self.W_hyper)

        # 3. Clip Scalars (Safety)
        self.alpha_entropy = max(MIN_SCALAR, min(MAX_SCALAR, self.alpha_entropy))
        self.lambda_reg = max(MIN_SCALAR, min(MAX_SCALAR, self.lambda_reg))
        self.beta_mem = max(MIN_SCALAR, min(MAX_SCALAR, self.beta_mem))
        # Drift/Anomaly terms can be 0.0 (disabled), so only cap max
        self.lambda_drift = max(0.0, min(MAX_SCALAR, self.lambda_drift))
        self.mu_anomaly = max(0.0, min(MAX_SCALAR, self.mu_anomaly))

    def as_dict(self) -> Dict[str, float]:
        """Return scalar weights for lightweight telemetry."""
        return {
            "alpha_entropy": float(self.alpha_entropy),
            "lambda_reg": float(self.lambda_reg),
            "beta_mem": float(self.beta_mem),
            "lambda_drift": float(self.lambda_drift),
            "mu_anomaly": float(self.mu_anomaly),
        }

    def as_debug_dict(self) -> Dict[str, Any]:
        """Return scalars plus summary stats of matrices."""
        base = self.as_dict()
        base.update({
            "W_pair_mean": float(np.mean(self.W_pair)) if self.W_pair.size else 0.0,
            "W_pair_max": float(np.max(self.W_pair)) if self.W_pair.size else 0.0,
            "W_hyper_mean": float(np.mean(self.W_hyper)) if self.W_hyper.size else 0.0,
        })
        return base


def adapt_energy_weights(
    weights: EnergyWeights,
    dspec: float = 0.0,   # Delta Specialization (e.g. alignment score)
    dacc: float = 0.0,    # Delta Accuracy (e.g. task success rate)
    dsmart: float = 0.0,  # Delta Intelligence (e.g. reasoning depth)
    dreason: float = 0.0, # Delta Reasoning (e.g. plan complexity)
    learning_rate: float = 0.01,
) -> None:
    """
    Heuristic adaptation of energy weights based on performance signals.
    
    Strategy:
    - If Accuracy (dacc) improves -> Reinforce current W_pair (Hebbian-ish).
    - If Reasoning (dreason) is high -> Increase Hyperedge weights (reward structure).
    - If Specialization (dspec) drops -> Increase Alpha (force diversity).
    """
    lr = learning_rate

    # 1. Adapt Scalars
    # ----------------
    # If reasoning is needed (dreason > 0), reduce entropy penalty to allow exploration?
    # Or increase it to force sharp roles? 
    # Logic: dspec (specialization) up -> we can lower alpha (roles are distinct).
    weights.alpha_entropy *= (1.0 - lr * dspec)

    # If complexity (dsmart) is high, relax regularization slightly to allow it,
    # OR tighten it if system is struggling?
    # Logic: If system is "smart" (good outputs), we allow more complexity (lower lambda).
    weights.lambda_reg *= (1.0 - lr * dsmart)

    # Memory pressure usually drives beta_mem externally, but we can nudge it here.
    
    # 2. Adapt Matrices
    # -----------------
    # Hyperedges: Reward successful reasoning chains
    if weights.W_hyper.size > 0:
        weights.W_hyper *= (1.0 + lr * dreason)

    # Pairwise: Reward successful collaboration (dacc)
    # Simple uniform scaling; a real implementation would update specific w_ij indices.
    if weights.W_pair.size > 0:
        weights.W_pair *= (1.0 + lr * dacc)

    # 3. Project to Safety Bounds
    weights.project()