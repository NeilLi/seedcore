"""Feature extraction functions for surprise score computation.

This module provides plug-and-play feature extraction functions (x1-x6)
for the Coordinator's surprise score system. Features can be easily
experimented with and swapped out for different implementations.
"""

import math
import logging
from typing import Any, Dict, Optional, Sequence, Tuple, Callable, Literal
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Constants
EPS = 1e-12


def _clip01(x: float) -> float:
    """Clip value to [0, 1] range."""
    return max(0.0, min(1.0, float(x)))


def _normalized_entropy(probs: Sequence[float]) -> float:
    """
    Compute normalized entropy using natural logarithm.
    
    Formula: H_norm = -Σ p log p / log K
    where K is the number of categories and p are normalized probabilities.
    
    Returns:
        Normalized entropy in range [0, 1] where:
        - 0 = deterministic (single mass)
        - 1 = uniform distribution
    """
    if not probs:
        return 0.5
    probs = [max(EPS, p) for p in probs]
    Z = sum(probs)
    if Z <= 0:
        return 0.5
    probs = [p / Z for p in probs]
    H = -sum(p * math.log(p) for p in probs if p > 0)
    Hmax = math.log(max(2, len(probs)))
    return _clip01(H / (Hmax + EPS))


def _validate_ocps_params(h: float, h_clr: float) -> Tuple[float, float]:
    """Validate OCPS parameters and raise on invalid values."""
    if h <= 0:
        raise ValueError(f"h must be > 0, got {h}")
    if not (0 <= h_clr < h):
        raise ValueError(f"h_clr must be in [0, h), got h_clr={h_clr}, h={h}")
    return h, h_clr


@dataclass(slots=True)
class OCPSState:
    """Immutable state snapshot of OCPS valve."""
    S_t: float
    h: float
    h_clr: float
    flag_on: bool
    drift_score: float
    mapping: str


def normalize_features(
    features: Sequence[float],
    mode: Literal["simple", "softmax"] = "simple"
) -> Tuple[float, ...]:
    """
    Normalize feature values using specified mode.
    
    Args:
        features: Sequence of feature values to normalize
        mode: Normalization mode - "simple" (clamp to [0,1]) or "softmax" (probabilistic)
        
    Returns:
        Normalized feature tuple
    """
    if mode == "simple":
        return tuple(_clip01(f) for f in features)
    elif mode == "softmax":
        # Softmax normalization: exp(x_i) / sum(exp(x_j))
        if not features:
            return tuple()
        try:
            # Subtract max for numerical stability
            max_val = max(features)
            exp_features = [math.exp(f - max_val) for f in features]
            sum_exp = sum(exp_features)
            if sum_exp <= 0:
                return tuple(_clip01(f) for f in features)  # Fallback to simple
            return tuple(exp / sum_exp for exp in exp_features)
        except (OverflowError, ValueError):
            # Fallback to simple normalization on error
            logger.debug("Softmax normalization failed, falling back to simple")
            return tuple(_clip01(f) for f in features)
    else:
        logger.warning(f"Unknown normalization mode '{mode}', using simple")
        return tuple(_clip01(f) for f in features)


def compute_x1_cache_novelty(mw_hit: Optional[float]) -> float:
    """
    Compute x1: Cache novelty feature.
    
    Measures how novel the task is based on cache hit rate.
    Higher values indicate more novel (less cached) tasks.
    
    Args:
        mw_hit: Cache hit rate (0-1), where 1.0 = fully cached
        
    Returns:
        Novelty score in [0, 1], where 1.0 = most novel
    """
    if mw_hit is None:
        logger.debug("Missing mw_hit signal, using default 0.5")
        return 0.5
    try:
        return _clip01(1.0 - float(mw_hit))
    except Exception as e:
        logger.debug("Invalid mw_hit value %r: %s", mw_hit, e)
        return 0.5


def compute_x2_ocps(
    ocps: Dict[str, Any],
    drift_minmax: Optional[Tuple[float, float]]
) -> Tuple[float, OCPSState]:
    """
    Compute x2: OCPS (Online Change Point Scoring) feature.
    
    Measures drift accumulation using CUSUM-based OCPS algorithm.
    Returns both the score and the OCPS state for tracking.
    
    Args:
        ocps: OCPS parameters dict with S_t, h, h_clr, flag_on
        drift_minmax: Optional (p10, p90) tuple for minmax fallback
        
    Returns:
        Tuple of (score in [0, 1], OCPSState)
    """
    try:
        St = float(ocps.get("S_t"))
        h = float(ocps.get("h"))
        hclr = float(ocps.get("h_clr", h / 2.0))
        flag = bool(ocps.get("flag_on", ocps.get("drift_flag", False)))
        
        # Validate OCPS parameters
        h, hclr = _validate_ocps_params(h, hclr)
        
        if not flag:
            score = _clip01(St / h)
            state = OCPSState(S_t=St, h=h, h_clr=hclr, flag_on=flag, drift_score=score, mapping="ocps")
            return score, state
        else:
            score = _clip01((St - hclr) / (h - hclr))
            state = OCPSState(S_t=St, h=h, h_clr=hclr, flag_on=flag, drift_score=score, mapping="ocps")
            return score, state
    except ValueError as e:
        logger.warning("OCPS parameter validation failed: %s", e)
        return 0.5, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=0.5, mapping="validation_error")
    except Exception as e:
        logger.debug("OCPS computation failed: %s", e)
        if not drift_minmax:
            return 0.5, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=0.5, mapping="minmax_fallback")
        drift = ocps.get("drift")
        if drift is None:
            return 0.5, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=0.5, mapping="minmax_fallback")
        p10, p90 = drift_minmax
        if p90 <= p10:
            return 0.5, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=0.5, mapping="minmax_fallback")
        try:
            score = _clip01((float(drift) - p10) / (p90 - p10))
            return score, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=score, mapping="minmax_fallback")
        except Exception:
            return 0.5, OCPSState(S_t=0, h=1, h_clr=0, flag_on=False, drift_score=0.5, mapping="minmax_fallback")


def compute_x3_ood(
    ood_dist: Optional[float],
    ood_to01: Optional[Callable[[float], float]]
) -> float:
    """
    Compute x3: Out-of-Distribution (OOD) feature.
    
    Measures how far the task is from the training distribution.
    Higher values indicate more OOD (unusual) tasks.
    
    Args:
        ood_dist: OOD distance metric
        ood_to01: Optional transformation function to normalize distance to [0, 1]
        
    Returns:
        OOD score in [0, 1], where 1.0 = most OOD
    """
    if ood_dist is None:
        logger.debug("Missing ood_dist signal, using default 0.5")
        return 0.5
    if ood_to01 is None:
        return _clip01(float(ood_dist) / 10.0)
    try:
        return _clip01(float(ood_to01(float(ood_dist))))
    except Exception as e:
        logger.debug("OOD computation failed: %s", e)
        return 0.5


def compute_x4_graph_novelty(
    graph_delta: Optional[float],
    mu_delta: Optional[float]
) -> float:
    """
    Compute x4: Graph novelty feature.
    
    Measures how novel the task is relative to the graph structure.
    Compares graph delta to mean delta to assess relative novelty.
    
    Args:
        graph_delta: Change in graph structure for this task
        mu_delta: Mean/expected delta for normalization
        
    Returns:
        Graph novelty score in [0, 1], where 1.0 = most novel
    """
    if graph_delta is None or mu_delta is None or mu_delta <= 0:
        logger.debug("Missing or invalid graph signals, using default 0.5")
        return 0.5
    try:
        return _clip01(float(graph_delta) / float(mu_delta))
    except Exception as e:
        logger.debug("Graph delta computation failed: %s", e)
        return 0.5


def compute_x5_dep_uncertainty(dep_probs: Optional[Sequence[float]]) -> float:
    """
    Compute x5: Dependency uncertainty feature.
    
    Measures uncertainty in task dependencies using normalized entropy.
    Higher values indicate more uncertainty about which dependencies to use.
    
    Args:
        dep_probs: Sequence of dependency probabilities
        
    Returns:
        Uncertainty score in [0, 1], where 1.0 = maximum uncertainty (uniform)
    """
    try:
        return _normalized_entropy(dep_probs or [])
    except Exception as e:
        logger.debug("Dependency entropy computation failed: %s", e)
        return 0.5


def compute_x6_cost_risk(
    est_runtime: Optional[float],
    SLO: Optional[float],
    kappa: Optional[float],
    criticality: Optional[float]
) -> float:
    """
    Compute x6: Cost-risk feature.
    
    Combines runtime risk (relative to SLO) and criticality to assess
    overall cost-risk of the task.
    
    Args:
        est_runtime: Estimated runtime in seconds
        SLO: Service Level Objective (target runtime)
        kappa: Scaling factor for SLO (default 0.8)
        criticality: Task criticality score (0-1)
        
    Returns:
        Cost-risk score in [0, 1], where 1.0 = highest risk
    """
    c = _clip01(criticality if criticality is not None else 0.5)
    if est_runtime is None or SLO is None:
        logger.debug("Missing runtime/SLO signals, using default 0.5")
        r = 0.5
    else:
        k = float(kappa) if (kappa and kappa > 0) else 0.8
        r = _clip01(float(est_runtime) / max(EPS, float(SLO) * k))
    return 0.5 * (r + c)


def compute_all_features(
    signals: Dict[str, Any],
    normalize_mode: Literal["simple", "softmax"] = "simple"
) -> Tuple[Tuple[float, ...], OCPSState]:
    """
    Compute all six features (x1-x6) from signals.
    
    Args:
        signals: Dictionary of input signals for feature computation
        normalize_mode: Normalization mode for feature values ("simple" or "softmax")
        
    Returns:
        Tuple of (feature tuple (x1, x2, x3, x4, x5, x6), OCPSState)
    """
    # Compute x2 (returns tuple with state)
    x2_result = compute_x2_ocps(signals.get("ocps", {}), signals.get("drift_minmax"))
    x2_score, ocps_state = x2_result
    
    # Compute all features
    x1 = compute_x1_cache_novelty(signals.get("mw_hit"))
    x3 = compute_x3_ood(signals.get("ood_dist"), signals.get("ood_to01"))
    x4 = compute_x4_graph_novelty(signals.get("graph_delta"), signals.get("mu_delta"))
    x5 = compute_x5_dep_uncertainty(signals.get("dep_probs"))
    x6 = compute_x6_cost_risk(
        signals.get("est_runtime"),
        signals.get("SLO"),
        signals.get("kappa"),
        signals.get("criticality")
    )
    
    features = (x1, x2_score, x3, x4, x5, x6)
    
    # Apply normalization mode
    normalized_features = normalize_features(features, mode=normalize_mode)
    
    return normalized_features, ocps_state

