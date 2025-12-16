"""Feature extraction functions for surprise score computation.

This module provides plug-and-play feature extraction functions (x1-x6)
for the Coordinator's surprise score system. Features can be easily
experimented with and swapped out for different implementations.

Updates:
- Integration with Eventizer EventTags for semantic criticality (x6).
- Removed unused network clients (BaseServiceClient, httpx).
- Fixed circular imports.
"""

import math
import logging
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Literal
from dataclasses import dataclass

# Integration with the new Eventizer Schema
from seedcore.models.eventizer import EventTags, Urgency

logger = logging.getLogger(__name__)

# Constants
EPS = 1e-12


@dataclass(slots=True)
class OCPSState:
    """Immutable state snapshot of OCPS valve."""
    S_t: float
    h: float
    h_clr: float
    flag_on: bool
    drift_score: float
    mapping: str


def _clip01(x: float) -> float:
    """Clip value to [0, 1] range."""
    return max(0.0, min(1.0, float(x)))


def _normalized_entropy(probs: Sequence[float]) -> float:
    """
    Compute normalized entropy using natural logarithm.
    Returns [0, 1] where 1.0 = maximum uncertainty.
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
    """Validate OCPS parameters."""
    if h <= 0:
        raise ValueError(f"h must be > 0, got {h}")
    if not (0 <= h_clr < h):
        # Auto-correct if h_clr is invalid instead of crashing in prod
        logger.warning(f"Invalid h_clr={h_clr} for h={h}. Resetting to 0.5*h")
        h_clr = h * 0.5
    return h, h_clr


def normalize_features(
    features: Sequence[float],
    mode: Literal["simple", "softmax"] = "simple"
) -> Tuple[float, ...]:
    """Normalize feature values."""
    if mode == "simple":
        return tuple(_clip01(f) for f in features)
    elif mode == "softmax":
        if not features:
            return tuple()
        try:
            max_val = max(features)
            exp_features = [math.exp(f - max_val) for f in features]
            sum_exp = sum(exp_features)
            if sum_exp <= 0:
                return tuple(_clip01(f) for f in features)
            return tuple(exp / sum_exp for exp in exp_features)
        except (OverflowError, ValueError):
            return tuple(_clip01(f) for f in features)
    else:
        return tuple(_clip01(f) for f in features)


# -----------------------------------------------------------------------------
# Feature Functions (x1-x6)
# -----------------------------------------------------------------------------

def compute_x1_cache_novelty(mw_hit: Optional[float]) -> float:
    """
    x1: Cache novelty. 1.0 = Not in cache (Novel).
    """
    if mw_hit is None:
        return 0.5
    try:
        return _clip01(1.0 - float(mw_hit))
    except Exception:
        return 0.5


def compute_x2_ocps(
    ocps: Dict[str, Any],
    drift_minmax: Optional[Tuple[float, float]]
) -> Tuple[float, OCPSState]:
    """
    x2: OCPS Drift Accumulation.
    """
    try:
        St = float(ocps.get("S_t", 0.0))
        h = float(ocps.get("h", 1.0))
        hclr = float(ocps.get("h_clr", h / 2.0))
        flag = bool(ocps.get("flag_on", ocps.get("drift_flag", False)))
        
        h, hclr = _validate_ocps_params(h, hclr)
        
        # Normalized CUSUM score
        if not flag:
            score = _clip01(St / h)
        else:
            # If flag is on, we are in escalation territory
            # Normalize between h_clr and h to keep signal high
            denom = h - hclr
            score = _clip01((St - hclr) / denom) if denom > 0 else 1.0

        state = OCPSState(
            S_t=St, h=h, h_clr=hclr, flag_on=flag, 
            drift_score=score, mapping="ocps"
        )
        return score, state

    except Exception as e:
        logger.debug(f"OCPS computation error: {e}")
        return 0.5, OCPSState(0.0, 1.0, 0.0, False, 0.5, "error_fallback")


def compute_x3_ood(ood_dist: Optional[float], ood_to01: Optional[Callable[[float], float]]) -> float:
    """
    x3: Out-of-Distribution distance.
    """
    if ood_dist is None:
        return 0.5
    if ood_to01 is None:
        return _clip01(float(ood_dist) / 10.0)
    try:
        return _clip01(float(ood_to01(float(ood_dist))))
    except Exception:
        return 0.5


def compute_x4_graph_novelty(graph_delta: Optional[float], mu_delta: Optional[float]) -> float:
    """
    x4: Graph Structural Novelty (delta vs expected delta).
    """
    if graph_delta is None or not mu_delta or mu_delta <= 0:
        return 0.5
    return _clip01(float(graph_delta) / float(mu_delta))


def compute_x5_dep_uncertainty(dep_probs: Optional[Sequence[float]]) -> float:
    """
    x5: Dependency Uncertainty (Entropy).
    """
    try:
        return _normalized_entropy(dep_probs or [])
    except Exception:
        return 0.5


def compute_x6_cost_risk(
    est_runtime: Optional[float],
    SLO: Optional[float],
    kappa: Optional[float],
    criticality: Optional[float],
    event_tags: Optional[EventTags] = None
) -> float:
    """
    x6: Cost & Risk score.
    
    Integrates:
    1. Runtime Risk (Will we breach SLO?)
    2. Semantic Criticality (From Eventizer Tags)
    """
    # 1. Calculate Runtime Risk
    if est_runtime is None or SLO is None:
        r = 0.5
    else:
        k = float(kappa) if (kappa and kappa > 0) else 0.8
        r = _clip01(float(est_runtime) / max(EPS, float(SLO) * k))

    # 2. Calculate Criticality (Fusion)
    # Start with the raw criticality signal
    c_raw = criticality if criticality is not None else 0.5
    
    # Boost with Semantic Urgency if tags are present
    c_semantic = 0.0
    if event_tags:
        # Map Eventizer Urgency to float [0, 1]
        urgency_map = {
            Urgency.CRITICAL: 1.0,
            Urgency.HIGH: 0.8,
            Urgency.NORMAL: 0.4,
            Urgency.LOW: 0.1
        }
        # Use the higher of Priority (0-10 scale -> 0-1) or Urgency
        prio_score = min(1.0, event_tags.priority / 10.0)
        urg_score = urgency_map.get(event_tags.urgency, 0.4)
        c_semantic = max(prio_score, urg_score)

    # Fusion: Take the max of manual criticality or semantic criticality
    c_final = max(c_raw, c_semantic)

    # Final Risk Score is average of Runtime Risk and Criticality
    return 0.5 * (r + c_final)


# -----------------------------------------------------------------------------
# Aggregator
# -----------------------------------------------------------------------------

def compute_all_features(
    signals: Dict[str, Any],
    normalize_mode: Literal["simple", "softmax"] = "simple"
) -> Tuple[Tuple[float, ...], OCPSState]:
    """
    Compute all six features (x1-x6) from signals.
    
    Expects 'signals' to contain standard metrics plus optional 'event_tags'
    populated by the Coordinator's Eventizer pass.
    """
    # Extract EventTags if present (populated by Coordinator)
    event_tags_data = signals.get("event_tags")
    event_tags = None
    if isinstance(event_tags_data, EventTags):
        event_tags = event_tags_data
    elif isinstance(event_tags_data, dict):
        try:
            event_tags = EventTags(**event_tags_data)
        except Exception:
            pass

    # x2: OCPS State
    x2_score, ocps_state = compute_x2_ocps(
        signals.get("ocps", {}), 
        signals.get("drift_minmax")
    )
    
    # Compute features
    x1 = compute_x1_cache_novelty(signals.get("mw_hit"))
    x3 = compute_x3_ood(signals.get("ood_dist"), signals.get("ood_to01"))
    x4 = compute_x4_graph_novelty(signals.get("graph_delta"), signals.get("mu_delta"))
    x5 = compute_x5_dep_uncertainty(signals.get("dep_probs"))
    
    # x6: Now enriched with Eventizer Tags
    x6 = compute_x6_cost_risk(
        est_runtime=signals.get("est_runtime"),
        SLO=signals.get("SLO"),
        kappa=signals.get("kappa"),
        criticality=signals.get("criticality"),
        event_tags=event_tags # <--- Injection point
    )
    
    features = (x1, x2_score, x3, x4, x5, x6)
    norm_features = normalize_features(features, mode=normalize_mode)
    
    return norm_features, ocps_state