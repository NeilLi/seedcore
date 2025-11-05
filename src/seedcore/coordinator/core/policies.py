"""Core policies for drift scoring, energy state management, and routing decisions."""

import os
import math
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Set, Callable, TypedDict, NotRequired
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Constants and utility functions from surprise module
EPS = 1e-12

# Type definitions for better API contracts
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
    spikes: Sequence[float]
    fatigue: Sequence[float]
    novelty: Sequence[float]
    reward: Sequence[float]
    tips: Sequence[float]
    speed: float
    quality: float
    status: Dict[str, Any]  # e.g., {"obs": [...]}
    drift_minmax: Tuple[float, float]
    ood_dist: float
    ood_to01: Callable[[float], float]
    graph_delta: float
    mu_delta: float
    dep_probs: Sequence[float]
    est_runtime: float
    SLO: float
    kappa: float
    criticality: float

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
    return max(0.0, min(1.0, float(x)))


def _normalize_weights(w: Sequence[float]) -> Tuple[float, ...]:
    w_pos = [max(0.0, wi) for wi in w]
    s = sum(w_pos)
    return tuple((wi / (s + EPS)) for wi in w_pos)


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


def _env_float(name: str, default: float) -> float:
    """Get float from environment with logging of overrides."""
    val = os.getenv(name)
    if val is None:
        return default
    try:
        parsed = float(val)
        logger.info("Overriding %s via env: %s -> %s", name, default, parsed)
        return parsed
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, val, default)
        return default

def _validate_ocps_params(h: float, h_clr: float) -> Tuple[float, float]:
    """Validate OCPS parameters and raise on invalid values."""
    if h <= 0:
        raise ValueError(f"h must be > 0, got {h}")
    if not (0 <= h_clr < h):
        raise ValueError(f"h_clr must be in [0, h), got h_clr={h_clr}, h={h}")
    return h, h_clr

def _require_keys(d: Dict[str, Any], keys: Sequence[str], ctx: str) -> None:
    """Log warnings for missing required keys."""
    missing = [k for k in keys if k not in d]
    if missing:
        logger.warning("%s missing keys: %s", ctx, ",".join(missing))

def _parse_weights(env_var: str, default=(0.25, 0.20, 0.15, 0.20, 0.10, 0.10)):
    raw = os.getenv(env_var)
    if not raw:
        return default
    try:
        ws = [max(0.0, float(x.strip())) for x in raw.split(",")]
        if not ws or len(ws) != 6:
            logger.warning("Invalid weight count in %s: expected 6, got %d", env_var, len(ws))
            return default
        s = sum(ws) or 1.0
        return tuple(w/s for w in ws)
    except Exception as e:
        logger.warning("Failed to parse weights from %s: %s", env_var, e)
        return default


class SurpriseComputer:
    """Computes surprise scores for routing decisions."""
    
    def __init__(self, weights=None, tau_fast=0.35, tau_plan=0.60):
        weights = weights or _parse_weights("SURPRISE_WEIGHTS")
        self.w_hat = _normalize_weights(weights)
        self.tau_fast = _env_float("SURPRISE_TAU_FAST", tau_fast)
        self.tau_plan = _env_float("SURPRISE_TAU_PLAN", tau_plan)
        
        # Validate weight count matches component count
        if len(self.w_hat) != 6:
            raise ValueError(f"Expected 6 weights, got {len(self.w_hat)}")
        
        # Log weight normalization if sum was near zero
        if sum(weights or []) < EPS:
            logger.warning("Weight sum was near zero, applied uniform normalization")

    def compute(self, signals: SurpriseSignals) -> Dict[str, Any]:
        """Compute surprise score with structured logging and validation."""
        # Check for missing critical signals
        _require_keys(signals, ["mw_hit", "ocps"], "SurpriseComputer.compute")
        
        def x1(mw_hit):
            if mw_hit is None:
                logger.debug("Missing mw_hit signal, using default 0.5")
                return 0.5
            try:
                return _clip01(1.0 - float(mw_hit))
            except Exception as e:
                logger.debug("Invalid mw_hit value %r: %s", mw_hit, e)
                return 0.5

        def x2(ocps, drift_minmax):
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

        def x3(ood_dist, ood_to01):
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

        def x4(graph_delta, mu_delta):
            if graph_delta is None or mu_delta is None or mu_delta <= 0:
                logger.debug("Missing or invalid graph signals, using default 0.5")
                return 0.5
            try:
                return _clip01(float(graph_delta) / float(mu_delta))
            except Exception as e:
                logger.debug("Graph delta computation failed: %s", e)
                return 0.5

        def x5(dep_probs):
            try:
                return _normalized_entropy(dep_probs or [])
            except Exception as e:
                logger.debug("Dependency entropy computation failed: %s", e)
                return 0.5

        def x6(est_runtime, SLO, kappa, criticality):
            c = _clip01(criticality if criticality is not None else 0.5)
            if est_runtime is None or SLO is None:
                logger.debug("Missing runtime/SLO signals, using default 0.5")
                r = 0.5
            else:
                k = float(kappa) if (kappa and kappa > 0) else 0.8
                r = _clip01(float(est_runtime) / max(EPS, float(SLO) * k))
            return 0.5 * (r + c)

        # Compute component scores
        x2_result = x2(signals.get("ocps", {}), signals.get("drift_minmax"))
        x2_score, ocps_state = x2_result
        
        xs = (
            x1(signals.get("mw_hit")),
            x2_score,
            x3(signals.get("ood_dist"), signals.get("ood_to01")),
            x4(signals.get("graph_delta"), signals.get("mu_delta")),
            x5(signals.get("dep_probs")),
            x6(signals.get("est_runtime"), signals.get("SLO"), signals.get("kappa"), signals.get("criticality")),
        )
        
        # Ensure all components are clamped
        xs = tuple(_clip01(x) for x in xs)
        
        S = _clip01(sum(w * x for w, x in zip(self.w_hat, xs)))
        decision = ("fast" if S < self.tau_fast else "planner" if S < self.tau_plan else "hgnn")
        
        # Structured logging for decision points
        logger.info("Surprise computation: S=%.3f, decision=%s, thresholds=(fast=%.3f, plan=%.3f)", 
                   S, decision, self.tau_fast, self.tau_plan)
        logger.debug("Component scores: x1=%.3f, x2=%.3f, x3=%.3f, x4=%.3f, x5=%.3f, x6=%.3f", *xs)
        logger.debug("OCPS state: S_t=%.3f, h=%.3f, h_clr=%.3f, flag_on=%s, mapping=%s",
                    ocps_state.S_t, ocps_state.h, ocps_state.h_clr, ocps_state.flag_on, ocps_state.mapping)
        
        return {
            "S": S, 
            "x": xs, 
            "weights": self.w_hat, 
            "decision": decision, 
            "ocps": {
                "S_t": ocps_state.S_t,
                "h": ocps_state.h,
                "h_clr": ocps_state.h_clr,
                "flag_on": ocps_state.flag_on,
                "drift_score": ocps_state.drift_score,
                "mapping": ocps_state.mapping
            }
        }


class OCPSValve:
    """
    Neural-CUSUM accumulator for drift detection and escalation control.
    
    This implements the CUSUM algorithm: S_t = max(0, S_{t-1} + drift - nu)
    where:
    - S_t is the current CUSUM statistic
    - drift is the drift score from the ML service
    - nu is the drift threshold (typically 0.1)
    - h is the escalation threshold (from OCPS_DRIFT_THRESHOLD env var)
    
    RESET SEMANTICS:
    - Reset (S = 0) occurs ONLY on escalation (S > h)
    - This prevents under-escalation and spam escalations
    - The accumulator builds up drift evidence over time
    - Once threshold is exceeded, it resets to start fresh
    """
    def __init__(self, nu: float = 0.1, h: float = None):
        self.nu = nu
        self.h = _env_float("OCPS_DRIFT_THRESHOLD", 0.5) if h is None else h
        self.S = 0.0
        self.fast_hits = 0
        self.esc_hits = 0
        
        # Validate parameters
        if self.nu <= 0:
            raise ValueError(f"nu must be > 0, got {self.nu}")
        if self.h <= 0:
            raise ValueError(f"h must be > 0, got {self.h}")

    def update(self, drift: float) -> bool:
        """
        Update CUSUM statistic with new drift score.
        
        Args:
            drift: Drift score from ML service (s_t)
            
        Returns:
            bool: True if escalation triggered, False otherwise
            
        Note:
            Reset occurs ONLY on escalation to prevent under-escalation.
            This ensures the accumulator builds evidence over time before
            triggering escalation, preventing false positives.
        """
        drift = _clip01(drift)  # Ensure drift is in valid range
        self.S = max(0.0, self.S + drift - self.nu)
        esc = self.S > self.h
        
        if esc:
            self.esc_hits += 1
            self.S = 0.0  # Reset ONLY on escalation
            logger.info("OCPS escalation triggered: drift=%.3f, S_t=%.3f, h=%.3f", drift, self.S, self.h)
        else:
            self.fast_hits += 1
            logger.debug("OCPS update: drift=%.3f, S_t=%.3f, h=%.3f", drift, self.S, self.h)
        
        return esc

    @property
    def p_fast(self) -> float:
        """Probability of fast path based on historical hits."""
        tot = self.fast_hits + self.esc_hits
        return (self.fast_hits / tot) if tot else 1.0

    def state(self) -> OCPSState:
        """Get current state snapshot."""
        return OCPSState(
            S_t=self.S,
            h=self.h,
            h_clr=self.h * 0.5,  # Default h_clr
            flag_on=self.S > self.h,
            drift_score=self.S / self.h if self.h > 0 else 0.0,
            mapping="ocps_valve"
        )


def _decide_route_with_hysteresis(S: float, last_decision: Optional[str] = None,
                                 fast_enter: float = 0.35, fast_exit: float = 0.38,
                                 plan_enter: float = 0.60, plan_exit: float = 0.57) -> str:
    """
    Route decision with hysteresis to prevent flapping around thresholds.
    
    Hysteresis prevents rapid oscillation between routing decisions by using
    different thresholds for entering vs exiting each path:
    - fast_enter ≈ p95 of steady state surprise on OK traffic
    - fast_exit > fast_enter (prevents immediate re-entry to fast)
    - plan_enter ≈ p90 of steady state surprise on degraded traffic  
    - plan_exit < plan_enter (prevents immediate exit from planner)
    
    Args:
        S: Surprise score [0, 1]
        last_decision: Previous decision (for hysteresis)
        fast_enter: Threshold to enter fast path (default: 0.35)
        fast_exit: Threshold to exit fast path (default: 0.38, higher for hysteresis)
        plan_enter: Threshold to enter planner path (default: 0.60)
        plan_exit: Threshold to exit planner path (default: 0.57, lower for hysteresis)
    
    Returns:
        Decision: 'fast', 'planner', or 'hgnn'
    """
    if last_decision == "fast":
        if S >= fast_exit:
            # Allow re-evaluation if we've crossed the exit threshold
            pass
        else:
            return "fast"
    
    if last_decision == "hgnn":
        if S <= plan_exit:
            # Allow re-evaluation if we've crossed the exit threshold
            pass
        else:
            return "hgnn"
    
    # Fresh decision based on current score
    if S < fast_enter:
        return "fast"
    elif S < plan_enter:
        return "planner"
    else:
        return "hgnn"


def build_proto_subtasks(tags: Set[str], x6: float, criticality: float, force: bool = False) -> Dict[str, Any]:
    """
    Returns: { "tasks": [{type, params, provenance[]}...], "edges": [(a,b)...] }
    
    Args:
        tags: Set of domain-specific event tags
        x6: Criticality signal (0-1)
        criticality: Derived criticality score
        force: If True, generate baseline tasks even when no domain tags match
    """
    tasks: List[Dict[str, Any]] = []
    edges: List[Tuple[str, str]] = []

    def add(t: str, provenance: str, **params):
        tasks.append({"type": t, "params": params or {}, "provenance": [provenance]})

    privacy_needed = ("vip" in tags) or ("privacy" in tags) or (criticality >= 0.8)
    if privacy_needed:
        add("private_comms", "R_PRIVACY_BASELINE", privacy_mode="STRICT", single_poc=True)
        add("incident_log_restricted", "R_PRIVACY_BASELINE", visibility="restricted")

    if "allergen" in tags:
        add("food_safety_containment", "R_ALLERGEN", sla_min=10)
    if "luggage_custody" in tags:
        add("privacy_luggage_recovery", "R_LUGGAGE", chain="dual_custody")
    if "hvac_fault" in tags:
        add("hvac_stabilize", "R_HVAC", temp_target_c=22)

    if any(t["type"] in {"food_safety_containment","privacy_luggage_recovery","hvac_stabilize"} for t in tasks):
        add("guest_recovery", "R_GUEST_RECOVERY", comp_policy="VIP_TIER1")

    def has(tt): return any(t["type"] == tt for t in tasks)
    if has("private_comms"):
        for tt in ["food_safety_containment","privacy_luggage_recovery","hvac_stabilize","incident_log_restricted"]:
            if has(tt):
                edges.append(("private_comms", tt))
    if has("guest_recovery"):
        for tt in ["food_safety_containment","privacy_luggage_recovery","hvac_stabilize"]:
            if has(tt):
                edges.append((tt, "guest_recovery"))

    # BASELINE TASKS: If no domain-specific tasks and force_decomposition=True,
    # generate generic baseline trio for multi-step analysis
    if not tasks and force:
        add("retrieve_context", "R_GENERIC_BASELINE", retrieval_strategy="semantic")
        add("graph_rag_seed", "R_GENERIC_BASELINE", hops=2, topk=8)
        add("synthesis_writeup", "R_GENERIC_BASELINE", format="structured")
        edges.append(("retrieve_context", "graph_rag_seed"))
        edges.append(("graph_rag_seed", "synthesis_writeup"))

    if x6 >= 0.9:
        for t in tasks:
            t["params"]["priority"] = "critical"
            if "sla_min" in t["params"]:
                t["params"]["sla_min"] = max(1, int(0.8 * t["params"]["sla_min"]))

    return {"tasks": tasks, "edges": edges}


def compute_fallback_drift_score(task: Dict[str, Any]) -> float:
    """
    Fallback drift score computation when ML service is unavailable.
    
    Uses simple heuristics based on task properties.
    """
    try:
        # Base score
        score = 0.0
        
        # Task type influence
        task_type = str(task.get("type", "unknown")).lower()
        if task_type == "anomaly_triage":
            score += 0.3  # Anomaly triage tasks are more likely to indicate drift
        elif task_type == "execute":
            score += 0.1  # Execute tasks have moderate drift potential
        elif task_type in ("graph_fact_embed", "graph_fact_query"):
            score += 0.2  # Fact operations have moderate drift potential
        elif task_type in ("graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2"):
            score += 0.15  # Graph operations have moderate drift potential
        elif task_type in ("artifact_manage", "capability_manage", "memory_cell_manage"):
            score += 0.1  # Resource management has low drift potential
        elif task_type in ("model_manage", "policy_manage", "service_manage", "skill_manage"):
            score += 0.05  # Agent layer management has very low drift potential
        
        # Priority influence
        priority = float(task.get("priority", 5))
        if priority >= 8:
            score += 0.2  # High priority tasks may indicate system stress
        elif priority <= 3:
            score += 0.1  # Low priority tasks might indicate system changes
        
        # Complexity influence
        complexity = float(task.get("complexity", 0.5))
        score += complexity * 0.2  # More complex tasks have higher drift potential
        
        # History influence
        history_ids = task.get("history_ids", [])
        if len(history_ids) == 0:
            score += 0.1  # New tasks without history might indicate drift
        
        # Ensure score is in reasonable range
        return max(0.0, min(1.0, score))
        
    except Exception as e:
        logger.warning(f"Fallback drift score computation failed: {e}")
        return 0.5  # Neutral fallback


def get_current_energy_state(agent_id: str, provider: Optional[Callable[..., float]] = None) -> Optional[float]:
    """
    Get current energy state for an agent.
    
    Args:
        agent_id: The agent identifier
        provider: Optional callback to get energy state from external source
        
    Returns:
        Current energy state or None if unavailable
    """
    try:
        if provider:
            return provider(agent_id)
        
        # Default placeholder implementation
        # This would typically call the energy service or get from agent state
        return 0.5  # TODO: Implement actual energy state retrieval
    except Exception as e:
        logger.warning(f"Failed to get energy state for agent {agent_id}: {e}")
        return None


def compute_surprise_score(signals: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute surprise score using the SurpriseComputer.
    
    Args:
        signals: Dictionary of signals for surprise computation
        
    Returns:
        Dictionary with surprise score, decision, and metadata
    """
    computer = SurpriseComputer()
    return computer.compute(signals)


def create_ocps_valve(nu: float = 0.1, h: Optional[float] = None) -> OCPSValve:
    """
    Create an OCPS valve for drift detection.
    
    Args:
        nu: Drift threshold parameter
        h: Escalation threshold (uses env var if None)
        
    Returns:
        OCPSValve instance
    """
    return OCPSValve(nu=nu, h=h)


def decide_route_with_hysteresis(
    surprise_score: float, 
    last_decision: Optional[str] = None,
    fast_enter: float = 0.35, 
    fast_exit: float = 0.38,
    plan_enter: float = 0.60, 
    plan_exit: float = 0.57
) -> str:
    """
    Make routing decision with hysteresis to prevent flapping.
    
    Args:
        surprise_score: Current surprise score
        last_decision: Previous routing decision
        fast_enter: Threshold to enter fast path
        fast_exit: Threshold to exit fast path
        plan_enter: Threshold to enter planner path
        plan_exit: Threshold to exit planner path
        
    Returns:
        Routing decision: 'fast', 'planner', or 'hgnn'
    """
    return _decide_route_with_hysteresis(
        surprise_score, last_decision, fast_enter, fast_exit, plan_enter, plan_exit
    )


def generate_proto_subtasks(
    tags: Set[str], 
    x6: float, 
    criticality: float, 
    force: bool = False
) -> Dict[str, Any]:
    """
    Generate proto subtasks based on domain tags and criticality.
    
    Args:
        tags: Set of domain-specific event tags
        x6: Criticality signal (0-1)
        criticality: Derived criticality score
        force: If True, generate baseline tasks even when no domain tags match
        
    Returns:
        Dictionary with tasks and edges
    """
    return build_proto_subtasks(tags, x6, criticality, force)


def compute_fallback_drift_score_or_ml(task: Dict[str, Any], ml_client: Optional[Any] = None) -> float:
    """
    Compute drift score using ML client if available, otherwise fallback.
    
    Args:
        task: Task dictionary
        ml_client: Optional ML client for drift scoring (must implement .score(task)->float)
        
    Returns:
        Drift score (0.0 to 1.0)
    """
    if ml_client is not None:
        try:
            # Check if ML client has the expected interface
            if not hasattr(ml_client, 'score'):
                logger.warning("ML client missing 'score' method, using fallback")
                return compute_fallback_drift_score(task)
            
            # Call ML client
            score = float(ml_client.score(task))
            score = _clip01(score)  # Ensure valid range
            
            # Check for placeholder values that might indicate incomplete implementation
            if os.getenv("ALLOW_PLACEHOLDER", "false").lower() not in ("true", "1", "yes"):
                if abs(score - 0.3) < 1e-6:  # Detect common placeholder value
                    logger.warning("Detected placeholder ML score (0.3), using fallback instead")
                    return compute_fallback_drift_score(task)
            
            logger.debug("ML drift score: %.3f", score)
            return score
            
        except Exception as e:
            logger.warning("ML drift scoring failed, using fallback: %s", e)
    
    # Fallback to heuristic-based scoring
    return compute_fallback_drift_score(task)


# ============================================================================
# PKG (Policy Graph Kernel) Support
# ============================================================================
# NOTE: PKG functionality has been moved to the centralized ops/pkg module.
# Use get_global_pkg_manager() from seedcore.ops.pkg.manager instead.
