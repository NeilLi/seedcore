# state.py
# SeedCore state models — enhanced helpers & safety projections
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple, Union
import numpy as np
import time

ROLE_KEYS: Tuple[str, str, str] = ("E", "S", "O")


# ------------------------ utilities ------------------------

def _as_f32(a: Any, allow_empty: bool = True) -> np.ndarray:
    if a is None:
        return np.asarray([], dtype=np.float32) if allow_empty else np.zeros((0,), dtype=np.float32)
    arr = np.asarray(a)
    # handle empty or object dtype gracefully
    if arr.size == 0 and allow_empty:
        return np.asarray([], dtype=np.float32)
    try:
        return arr.astype(np.float32, copy=False)
    except Exception:
        return np.asarray(arr, dtype=np.float32)

def _project_row_to_simplex(v: np.ndarray) -> np.ndarray:
    """
    Euclidean projection of a 1D vector onto the probability simplex:
    {x | x_i >= 0, sum x_i = 1}. See: Wang & Carreira-Perpiñán (2013).
    """
    v = np.maximum(v.astype(np.float32, copy=False), 0.0)
    if v.ndim != 1:
        raise ValueError("Simplex projection expects 1D vector")
    s = float(v.sum())
    if s == 0.0:
        # uniform distribution if all-zero
        return np.full(v.shape[0], 1.0 / float(v.shape[0]), dtype=np.float32)
    return (v / s).astype(np.float32, copy=False)

def _project_rows_to_simplex(M: np.ndarray) -> np.ndarray:
    if M.ndim == 1:
        return _project_row_to_simplex(M)
    out = np.empty_like(M, dtype=np.float32)
    for i in range(M.shape[0]):
        out[i] = _project_row_to_simplex(M[i])
    return out

def role_entropy(P: np.ndarray, eps: float = 1e-12) -> float:
    """
    Shannon entropy over rows of P (role probabilities). Returns mean entropy.
    P must be simplexed row-wise; we project defensively.
    """
    Pp = _project_rows_to_simplex(_as_f32(P))
    # avoid log(0)
    Pp = np.clip(Pp, eps, 1.0)
    H = -np.sum(Pp * np.log(Pp), axis=-1)  # nat units
    return float(np.mean(H)) if H.size else 0.0


# ------------------------ core models ------------------------

@dataclass
class MemoryVector:
    ma: Dict[str, Any] = field(default_factory=dict)
    mw: Dict[str, Any] = field(default_factory=dict)
    mlt: Dict[str, Any] = field(default_factory=dict)
    mfb: Dict[str, Any] = field(default_factory=dict)

    def utilization_scalar(self) -> float:
        """
        Optional helper: compress memory stats into a single utilization proxy
        (for telemetry only; not used directly by energy calc).
        """
        def _util(d: Dict[str, Any]) -> float:
            try:
                used = float(d.get("used", 0.0))
                cap = float(d.get("cap", d.get("capacity", 1.0)))
                return used / max(cap, 1e-6)
            except Exception:
                return 0.0
        vals = [_util(self.ma), _util(self.mw), _util(self.mlt), _util(self.mfb)]
        return float(np.mean(vals))


@dataclass
class OrganState:
    h: np.ndarray                      # shape: (n_agents_in_organ, d) or (d,)
    P: np.ndarray                      # shape: (n_agents_in_organ, 3) or (3,)
    v_pso: Optional[np.ndarray] = None # optional PSO velocity or controller aux

    def __post_init__(self):
        self.h = _as_f32(self.h)
        self.P = _as_f32(self.P)

    def P_agg(self) -> np.ndarray:
        """
        Aggregate per-agent role probabilities to organ-level distribution P(o).
        Projection ensures a valid probability simplex of length 3.
        """
        if self.P.size == 0:
            return np.full(3, 1.0/3.0, dtype=np.float32)
        P = _as_f32(self.P)
        if P.ndim == 1:
            # Defensive: trim/pad to 3, then simplex-project
            P = P[:3] if P.shape[0] >= 3 else np.pad(P, (0, 3-P.shape[0]))
            return _project_row_to_simplex(P)
        # Mean over agents, then project
        m = np.mean(P, axis=0)
        m = (m[:3] if m.shape[0] >= 3 else np.pad(m, (0, 3 - m.shape[0])))
        return _project_row_to_simplex(m)


@dataclass
class SystemState:
    h_hgnn: Optional[np.ndarray] = None
    E_patterns: Optional[np.ndarray] = None  # hyperedge selection/activation
    w_mode: Optional[np.ndarray] = None      # system mode weights (optional)
    ml: Dict[str, Any] = field(default_factory=dict)  # ML annotations (roles, drift, anomaly, scaling)

    def __post_init__(self):
        if self.h_hgnn is not None:
            self.h_hgnn = _as_f32(self.h_hgnn)
        if self.E_patterns is not None:
            self.E_patterns = _as_f32(self.E_patterns)
        if self.w_mode is not None:
            self.w_mode = _as_f32(self.w_mode)
        if self.ml is None:
            self.ml = {}
        else:
            # Ensure JSON-safe shallow copy
            self.ml = dict(self.ml)


@dataclass
class AgentSnapshot:
    h: np.ndarray
    p: Dict[str, float]                 # keys: "E","S","O"
    c: float                            # optional capacity/credit
    mem_util: float                     # optional memory util proxy
    lifecycle: str
    learned_skills: Dict[str, float] = field(default_factory=dict)  # Agent's learned skill levels
    load: float = 0.0                   # Operational activity load (for RL signals, scheduling)
    timestamp: float = field(default_factory=time.time)  # When snapshot was taken
    schema_version: str = "v1"          # Schema version for backward compatibility

    def __post_init__(self):
        self.h = _as_f32(self.h)
        # normalize p defensively to the 3-role simplex
        vec = np.asarray([float(self.p.get(k, 0.0)) for k in ROLE_KEYS], dtype=np.float32)
        vec = _project_row_to_simplex(vec)
        self.p = {k: float(vec[i]) for i, k in enumerate(ROLE_KEYS)}


@dataclass
class Response:
    """
    Standardized API response envelope for StateService.
    Consistent with the 'success/metrics/meta' pattern used in the Hot Path.
    """
    success: bool
    timestamp: float = field(default_factory=time.time)
    
    # Primary Data Slots
    metrics: Optional[Dict[str, Any]] = None  # Distilled metrics (Hot Path)
    meta: Optional[Dict[str, Any]] = None     # Processing metadata (latency, status)
    error: Optional[str] = None               # Error message if success=False
    
    # Optional: Full State Payload (Cold Path / Debugging)
    payload: Optional[Union[Dict[str, Any], UnifiedState]] = None

    @classmethod
    def ok(
        cls, 
        metrics: Optional[Dict[str, Any]] = None, 
        meta: Optional[Dict[str, Any]] = None, 
        payload: Any = None
    ) -> "Response":
        """Factory for successful responses."""
        return cls(success=True, metrics=metrics, meta=meta, payload=payload)

    @classmethod
    def fail(
        cls, 
        error: str, 
        meta: Optional[Dict[str, Any]] = None
    ) -> "Response":
        """Factory for failed responses."""
        return cls(success=False, error=error, meta=meta)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the response to a JSON-ready dictionary.
        Handles nested UnifiedState objects automatically.
        """
        out: Dict[str, Any] = {
            "success": self.success,
            "timestamp": self.timestamp,
        }
        
        if self.metrics is not None:
            out["metrics"] = self.metrics
            
        if self.meta is not None:
            out["meta"] = self.meta
            
        if self.error is not None:
            out["error"] = self.error
            
        if self.payload is not None:
            if isinstance(self.payload, UnifiedState):
                out["payload"] = self.payload.to_payload()
            else:
                out["payload"] = self.payload
                
        return out


@dataclass
class UnifiedState:
    """
    Snapshot container for s_t. Holds only *state variables* (not weights α/β/λ or W).
    Provides helpers to:
      - assemble H and P matrices
      - aggregate organ-level distributions
      - expose a slim payload for the energy calculator/service
      - validate/protect invariants (simplex, shapes)
    """
    agents: Dict[str, AgentSnapshot]
    organs: Dict[str, OrganState]
    system: SystemState
    memory: MemoryVector

    # -------- matrices & basic features --------

    def agent_ids(self) -> List[str]:
        return list(self.agents.keys())

    def H_matrix(self) -> np.ndarray:
        """
        Stack agent embeddings row-wise.
        Returns (n_agents, d). If empty, shape (0, 0).
        """
        if not self.agents:
            return np.zeros((0, 0), dtype=np.float32)
        mats = [_as_f32(a.h) for a in self.agents.values()]
        # ensure 2D rows
        mats = [m.reshape(1, -1) if m.ndim == 1 else m for m in mats]
        return np.vstack(mats).astype(np.float32, copy=False)

    def P_matrix(self, project: bool = True) -> np.ndarray:
        """
        Stack agent role distributions row-wise in E,S,O order.
        Returns (n_agents, 3). Projects to simplex by default.
        """
        if not self.agents:
            return np.zeros((0, 3), dtype=np.float32)
        rows = []
        for a in self.agents.values():
            v = np.asarray([float(a.p.get(k, 0.0)) for k in ROLE_KEYS], dtype=np.float32)
            rows.append(v)
        P = np.vstack(rows).astype(np.float32, copy=False)
        return _project_rows_to_simplex(P) if project else P

    def organ_P_matrix(self) -> np.ndarray:
        """
        Organ-level role distributions stacked row-wise: (n_organs, 3).
        """
        if not self.organs:
            return np.zeros((0, 3), dtype=np.float32)
        rows = [org.P_agg() for org in self.organs.values()]
        return np.vstack(rows).astype(np.float32, copy=False)

    def s_norm(self) -> float:
        """
        Pragmatic ||s_t|| ≈ ||H||_2 used for L2-regularization term.
        (We intentionally keep it to H for tractability.)
        """
        H = self.H_matrix()
        return float(np.linalg.norm(H)) if H.size else 0.0

    def hyper_selection(self, clip_min: float = 0.0, clip_max: float = 1.0) -> np.ndarray:
        """
        Return hyperedge selection vector E_sel used in the hyper term.
        Clamp to [clip_min, clip_max] for numerical hygiene.
        """
        E = self.system.E_patterns
        if E is None:
            return np.asarray([], dtype=np.float32)
        E = _as_f32(E)
        if E.ndim == 0:
            E = E.reshape(1)
        return np.clip(E, clip_min, clip_max).astype(np.float32, copy=False)

    # -------- validations & projections --------

    def validate(self) -> Dict[str, Any]:
        """
        Lightweight validation of common invariants. Returns dict of issues (empty if OK).
        """
        issues: Dict[str, Any] = {}
        H = self.H_matrix()
        P = self.P_matrix(project=False)

        # Role rows should be length 3
        if P.shape[1] != 3:
            issues["P.shape"] = {"got": list(P.shape), "expected_last_dim": 3}

        # Any negative or NaN probabilities?
        if np.any(~np.isfinite(P)):
            issues["P.nan"] = True
        if np.any(P < 0):
            issues["P.negative"] = True

        # Entropy range sanity (after projection)
        Hrole = role_entropy(P)
        if not (0.0 <= Hrole <= np.log(3.0) + 1e-3):
            issues["P.entropy_range"] = {"entropy": Hrole}

        # Hyper vector sanity
        E = self.hyper_selection()
        if E.size and (np.any(~np.isfinite(E)) or np.any(E < 0) or np.any(E > 1)):
            issues["E_patterns.range_or_nan"] = True

        # Embedding shape sanity
        if H.size and H.ndim != 2:
            issues["H.ndim"] = {"got": int(H.ndim), "expected": 2}

        return issues

    def projected(self) -> "UnifiedState":
        """
        Return a shallow-projected copy with safe role simplex rows and clamped E_sel.
        (Agent embeddings are not altered here.)
        """
        # Project agents' p maps
        proj_agents: Dict[str, AgentSnapshot] = {}
        for k, a in self.agents.items():
            vec = np.asarray([float(a.p.get(r, 0.0)) for r in ROLE_KEYS], dtype=np.float32)
            vec = _project_row_to_simplex(vec)
            proj_agents[k] = AgentSnapshot(h=a.h.copy(), p={r: float(vec[i]) for i, r in enumerate(ROLE_KEYS)},
                                           c=a.c, mem_util=a.mem_util, lifecycle=a.lifecycle)
        # Clamp E_patterns
        sys = SystemState(
            h_hgnn=self.system.h_hgnn.copy() if self.system.h_hgnn is not None else None,
            E_patterns=self.hyper_selection().copy(),
            w_mode=self.system.w_mode.copy() if self.system.w_mode is not None else None,
        )
        # Organs: keep P as-is; P_agg projects on demand
        proj_orgs = {k: OrganState(h=v.h.copy(), P=v.P.copy(), v_pso=None if v.v_pso is None else v.v_pso.copy())
                     for k, v in self.organs.items()}
        return UnifiedState(agents=proj_agents, organs=proj_orgs, system=sys, memory=self.memory)

    # -------- serialization & bridging --------

    def to_energy_state(self) -> Dict[str, Any]:
        """
        Slim dict the energy calculator expects.
          - "h_agents": (N, d) float32
          - "P_roles": (N, 3) float32 (simplex-projected)
          - "hyper_sel": (K,) float32 in [0,1]
          - "s_norm": scalar float
        """
        return {
            "h_agents": self.H_matrix(),
            "P_roles": self.P_matrix(project=True),
            "hyper_sel": self.hyper_selection(),
            "s_norm": self.s_norm(),
        }

    def to_payload(self) -> Dict[str, Any]:
        """
        JSON-safe payload (lists) for APIs/telemetry. Not for heavy arrays in hot paths.
        """
        return {
            "agents": {
                aid: {
                    "h": _as_f32(a.h).tolist(),
                    "p": {k: float(a.p.get(k, 0.0)) for k in ROLE_KEYS},
                    "c": float(a.c),
                    "mem_util": float(a.mem_util),
                    "lifecycle": str(a.lifecycle),
                }
                for aid, a in self.agents.items()
            },
            "organs": {
                oid: {
                    "h": _as_f32(o.h).tolist(),
                    "P": _as_f32(o.P).tolist(),
                    "P_agg": o.P_agg().tolist(),
                }
                for oid, o in self.organs.items()
            },
            "system": {
                "h_hgnn": None if self.system.h_hgnn is None else _as_f32(self.system.h_hgnn).tolist(),
                "E_patterns": None if self.system.E_patterns is None else _as_f32(self.system.E_patterns).tolist(),
                "w_mode": None if self.system.w_mode is None else _as_f32(self.system.w_mode).tolist(),
                "ml": self.system.ml or {},
            },
            "memory": {
                "ma": self.memory.ma,
                "mw": self.memory.mw,
                "mlt": self.memory.mlt,
                "mfb": self.memory.mfb,
                "util_scalar": self.memory.utilization_scalar(),
            },
        }

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "UnifiedState":
        """
        Construct from a JSON payload (inverse of to_payload, best-effort).
        """
        agents = {}
        for aid, d in (payload.get("agents") or {}).items():
            agents[aid] = AgentSnapshot(
                h=_as_f32(d.get("h", [])),
                p={k: float((d.get("p") or {}).get(k, 0.0)) for k in ROLE_KEYS},
                c=float(d.get("c", 0.0)),
                mem_util=float(d.get("mem_util", 0.0)),
                lifecycle=str(d.get("lifecycle", "unknown")),
            )
        organs = {}
        for oid, d in (payload.get("organs") or {}).items():
            organs[oid] = OrganState(
                h=_as_f32(d.get("h", [])),
                P=_as_f32(d.get("P", [])),
                v_pso=None
            )
        sysd = payload.get("system") or {}
        system = SystemState(
            h_hgnn=None if sysd.get("h_hgnn") is None else _as_f32(sysd.get("h_hgnn")),
            E_patterns=None if sysd.get("E_patterns") is None else _as_f32(sysd.get("E_patterns")),
            w_mode=None if sysd.get("w_mode") is None else _as_f32(sysd.get("w_mode")),
            ml=dict(sysd.get("ml") or {}),
        )
        memd = payload.get("memory") or {}
        memory = MemoryVector(ma=memd.get("ma", {}), mw=memd.get("mw", {}), mlt=memd.get("mlt", {}), mfb=memd.get("mfb", {}))
        return cls(agents=agents, organs=organs, system=system, memory=memory)
    
@dataclass
class Response:  # noqa: F811
    """
    Standardized API response envelope for StateService.
    Consistent with the 'success/metrics/meta' pattern used in the Hot Path.
    """
    success: bool
    timestamp: float = field(default_factory=time.time)
    
    # Primary Data Slots
    metrics: Optional[Dict[str, Any]] = None  # Distilled metrics (Hot Path)
    meta: Optional[Dict[str, Any]] = None     # Processing metadata (latency, status)
    error: Optional[str] = None               # Error message if success=False
    
    # Optional: Full State Payload (Cold Path / Debugging)
    payload: Optional[Union[Dict[str, Any], Any]] = None

    @classmethod
    def ok(
        cls, 
        metrics: Optional[Dict[str, Any]] = None, 
        meta: Optional[Dict[str, Any]] = None, 
        payload: Any = None
    ) -> "Response":
        """Factory for successful responses."""
        return cls(success=True, metrics=metrics, meta=meta, payload=payload)

    @classmethod
    def fail(
        cls, 
        error: str, 
        meta: Optional[Dict[str, Any]] = None
    ) -> "Response":
        """Factory for failed responses."""
        return cls(success=False, error=error, meta=meta)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serializes the response to a JSON-ready dictionary.
        Handles nested UnifiedState objects automatically if present.
        """
        out: Dict[str, Any] = {
            "success": self.success,
            "timestamp": self.timestamp,
        }
        
        if self.metrics is not None:
            out["metrics"] = self.metrics
            
        if self.meta is not None:
            out["meta"] = self.meta
            
        if self.error is not None:
            out["error"] = self.error
            
        if self.payload is not None:
            # Handle UnifiedState specifically, otherwise assume dict/JSON-safe
            if hasattr(self.payload, "to_payload"):
                out["payload"] = self.payload.to_payload()
            else:
                out["payload"] = self.payload
                
        return out
