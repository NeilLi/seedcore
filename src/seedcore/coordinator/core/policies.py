"""Core policies for drift scoring and routing decisions.

This module implements the 'Amygdala' of the system:
- SurpriseComputer: Calculates S(t) based on 6 signals.
- OCPSValve: Neural-CUSUM accumulator for drift detection.
- Routing Logic: Hysteresis-based decision making (Fast vs. Planner vs. HGNN).

It delegates raw feature extraction to `_features.py` to stay clean.
"""

import os
import logging
from typing import Any, Dict, Optional, Sequence, Callable, TypedDict

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired  # pyright: ignore[reportMissingModuleSource]

from seedcore.models.cognitive import DecisionKind
from .features import compute_all_features

logger = logging.getLogger(__name__)

# Constants
EPS = 1e-12


# --- Type Definitions ---


class OCPSIn(TypedDict):
    S_t: float
    h: float
    h_clr: NotRequired[float]
    flag_on: NotRequired[bool]
    drift_flag: NotRequired[bool]
    drift: NotRequired[float]


class SurpriseSignals(TypedDict, total=False):
    mw_hit: float
    ocps: OCPSIn
    # ... (other signals) ...
    drift_minmax: Any
    ood_dist: float
    ood_to01: Callable[[float], float]
    graph_delta: float
    mu_delta: float
    dep_probs: Sequence[float]
    est_runtime: float
    SLO: float
    kappa: float
    criticality: float
    # NEW: Eventizer Tags for Semantic Urgency
    event_tags: Any


# --- Helpers ---


def _env_float(name: str, default: float) -> float:
    """Get float from environment."""
    val = os.getenv(name)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


def _normalize_weights(w: Sequence[float]) -> tuple[float, ...]:
    w_pos = [max(0.0, wi) for wi in w]
    s = sum(w_pos)
    return tuple((wi / (s + EPS)) for wi in w_pos)


def _parse_weights(env_var: str, default=(0.25, 0.20, 0.15, 0.20, 0.10, 0.10)):
    raw = os.getenv(env_var)
    if not raw:
        return default
    try:
        ws = [max(0.0, float(x.strip())) for x in raw.split(",")]
        if len(ws) != 6:
            return default
        s = sum(ws) or 1.0
        return tuple(w / s for w in ws)
    except Exception:
        return default


# --- Core Classes ---


class SurpriseComputer:
    """
    Computes surprise scores for routing decisions.
    Now enriched with Semantic Urgency (x6) via Eventizer tags.
    """

    def __init__(
        self, weights=None, tau_fast=0.35, tau_plan=0.60, normalize_mode: str = "simple"
    ):
        weights = weights or _parse_weights("SURPRISE_WEIGHTS")
        self.w_hat = _normalize_weights(weights)
        self.tau_fast = _env_float("SURPRISE_TAU_FAST", tau_fast)
        self.tau_plan = _env_float("SURPRISE_TAU_PLAN", tau_plan)
        self.normalize_mode = normalize_mode

    def compute(self, signals: SurpriseSignals) -> Dict[str, Any]:
        """Compute surprise score with structured logging."""

        # 1. Compute Features (x1-x6)
        # Note: x6 (Cost/Risk) now includes semantic urgency from event_tags
        xs, ocps_state = compute_all_features(
            signals, normalize_mode=self.normalize_mode
        )

        # 2. Weighted Sum
        S = max(0.0, min(1.0, sum(w * x for w, x in zip(self.w_hat, xs))))

        # 3. Thresholding
        if S < self.tau_fast:
            decision_kind = DecisionKind.FAST_PATH.value
        elif S < self.tau_plan:
            decision_kind = DecisionKind.COGNITIVE.value
        else:
            decision_kind = DecisionKind.ESCALATED.value

        return {
            "S": S,
            "x": xs,
            "weights": self.w_hat,
            "decision_kind": decision_kind,
            "ocps": {
                "S_t": ocps_state.S_t,
                "h": ocps_state.h,
                "flag_on": ocps_state.flag_on,
                "drift_score": ocps_state.drift_score,
            },
        }

def decide_route_with_hysteresis(
    surprise_score: float,
    last_decision: Optional[str] = None,
    fast_enter: float = 0.35,
    fast_exit: float = 0.38,
    plan_enter: float = 0.60,
    plan_exit: float = 0.57,
) -> str:
    """Hysteresis-based routing decision (fast → plan → HGNN)."""

    # Clamp and alias
    S = max(0.0, min(1.0, surprise_score))

    FAST = DecisionKind.FAST_PATH.value
    PLAN = DecisionKind.COGNITIVE.value
    HGNN = DecisionKind.ESCALATED.value

    # ------------------------------------------------------------------
    # 1) Hysteresis: stick with last decision if still inside its band.
    # ------------------------------------------------------------------
    if last_decision == FAST and S < fast_exit:
        return FAST

    if last_decision == PLAN and fast_exit <= S < plan_exit:
        return PLAN

    if last_decision == HGNN and S >= plan_exit:
        return HGNN

    # ------------------------------------------------------------------
    # 2) Fresh decision if hysteresis does not apply.
    # ------------------------------------------------------------------
    if S < fast_enter:
        return FAST
    elif S < plan_enter:
        return PLAN
    else:
        return HGNN


# --- Drift Calculation (The "System 2" Input) ---


async def compute_drift_score(
    task: Dict[str, Any],
    text_payload: str | Dict[str, Any] | None,
    ml_client: Any,
    metrics: Optional[Any] = None,
) -> float:
    """
    Compute drift score.
    Combines ML Service (Statistical Drift) with Task Metadata (Heuristic Drift).
    
    Args:
        task: Task dictionary with metadata
        text_payload: Text string for drift detection, or dict containing "text" key, or None
        ml_client: ML service client
        metrics: Optional metrics tracker
    """
    # Extract text string from text_payload (handle both string and dict)
    text_for_drift: str | None = None
    if isinstance(text_payload, str):
        text_for_drift = text_payload
    elif isinstance(text_payload, dict):
        text_for_drift = text_payload.get("text") or text_payload.get("description")
    # If text_payload is None or empty, fallback to task description
    if not text_for_drift:
        text_for_drift = task.get("description") or ""
    
    # 1. ML Service Call (Remote)
    if ml_client and hasattr(ml_client, "compute_drift_score"):
        try:
            # Pass text as string to ML client
            response = await ml_client.compute_drift_score(task=task, text=text_for_drift)
            if response.get("status") == "success":
                return max(0.0, min(1.0, float(response.get("drift_score", 0.0))))

        except Exception as e:
            logger.warning(f"ML drift computation failed: {e}")

    # 2. Fallback Heuristics (Local)
    return _compute_fallback_drift_score(task)


def _compute_fallback_drift_score(task: Dict[str, Any]) -> float:
    """Heuristic drift score based on task type and priority."""
    score = 0.0
    t_type = str(task.get("type", "")).lower()

    if "anomaly" in t_type:
        score += 0.3  # noqa: E701
    if "graph" in t_type:
        score += 0.1  # noqa: E701

    prio = float(task.get("priority", 5))
    if prio >= 8:
        score += 0.2

    return max(0.0, min(1.0, score))

