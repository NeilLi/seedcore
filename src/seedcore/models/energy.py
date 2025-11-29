from typing import Dict, List, Optional, Any
from pydantic import BaseModel  # pyright: ignore[reportMissingImports]

from ..models.state import AgentSnapshot

# --- Request/Response Models ---
# (Pydantic models like EnergyRequest, EnergyResponse, etc. are unchanged)
# ... (all Pydantic models from your original file go here) ...
# --- (Keep all Pydantic models as-is) ---
class AgentSnapshotDTO(BaseModel):
    h: List[float]
    p: Dict[str, float]
    c: float
    mem_util: float
    lifecycle: str
    load: float = 0.0
    learned_skills: Dict[str, float] = {}
    timestamp: Optional[float] = None
    schema_version: str = "v1"
    
    @classmethod
    def from_snapshot(cls, snap: AgentSnapshot):
        return cls(
            h=snap.h.tolist(),
            p=snap.p,
            c=snap.c,
            mem_util=snap.mem_util,
            lifecycle=snap.lifecycle,
            learned_skills=snap.learned_skills,
            load=snap.load,
            timestamp=snap.timestamp,
            schema_version=snap.schema_version
        )
# ---------------------------------------------------------------------
# NOTE:
#   This schema is intentionally kept unused in v2.
#
#   It belongs to the original SeedCore theory where "organs" were
#   structural cognitive units with:
#       - h_org   : organ-level latent vector
#       - P_org   : intra-organ adjacency / connectivity matrix
#       - v_pso   : PSO velocity for structural optimization
#
#   The current implementation uses organs only as execution containers.
#   The PSO-based structural model is postponed until a future version
#   (SeedCore v3+) when we have more compute and multi-organ dynamics.
#
#   Do NOT remove; this is a placeholder for future research.
# ---------------------------------------------------------------------
class OrganStatePayload(BaseModel):
    h: List[float]
    P: List[List[float]]
    v_pso: Optional[List[float]] = None

class SystemStatePayload(BaseModel):
    h_hgnn: Optional[List[float]] = None
    E_patterns: Optional[List[float]] = None
    w_mode: Optional[List[float]] = None
    ml: Optional[Dict[str, Any]] = None


class MemoryVectorPayload(BaseModel):
    ma: Dict[str, Any] = {}
    mw: Dict[str, Any] = {}
    mlt: Dict[str, Any] = {}
    mfb: Dict[str, Any] = {}


class UnifiedStatePayload(BaseModel):
    agents: Dict[str, AgentSnapshotDTO]
    organs: Dict[str, OrganStatePayload]
    system: SystemStatePayload
    memory: MemoryVectorPayload


class EnergyWeightsPayload(BaseModel):
    alpha_entropy: Optional[float] = None
    lambda_reg: Optional[float] = None
    beta_mem: Optional[float] = None
    W_pair: Optional[List[List[float]]] = None
    W_hyper: Optional[List[float]] = None
    lambda_drift: Optional[float] = None
    mu_anomaly: Optional[float] = None


class EnergyRequest(BaseModel):
    unified_state: UnifiedStatePayload
    weights: Optional[EnergyWeightsPayload] = None
    include_gradients: bool = False
    include_breakdown: bool = True


class EnergyResponse(BaseModel):
    success: bool
    energy: Optional[Dict[str, float]] = None
    gradients: Optional[Dict[str, Any]] = None
    breakdown: Optional[Dict[str, float]] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float


class FlywheelResultRequest(BaseModel):
    delta_e: float
    breakdown: Optional[Dict[str, float]] = None
    cost: Optional[float] = 0.0
    scope: Optional[str] = "cluster"
    scope_id: Optional[str] = "-"
    p_fast: Optional[float] = 0.9
    drift: Optional[float] = 0.0
    beta_mem: Optional[float] = None


class FlywheelResultResponse(BaseModel):
    success: bool
    updated_weights: Dict[str, float]
    ledger_ok: bool
    balance_after: Optional[float] = None
    timestamp: float


class OptimizationRequest(BaseModel):
    unified_state: Dict[str, Any]
    task: Dict[str, Any]
    weights: Optional[Dict[str, float]] = None
    max_agents: Optional[int] = None


class OptimizationResponse(BaseModel):
    success: bool
    selected_agents: Optional[List[str]] = None
    suitability_scores: Optional[Dict[str, float]] = None
    recommended_roles: Optional[Dict[str, str]] = None
    task_complexity: Optional[float] = None
    error: Optional[str] = None
    timestamp: float
    computation_time_ms: float


class HealthResponse(BaseModel):
    status: str
    service: str
    sampler_running: bool
    state_service_healthy: bool
    error: Optional[str] = None

class GradientRequest(BaseModel):
    unified_state: Dict[str, Any]
    weights: Optional[Dict[str, Any]] = None
