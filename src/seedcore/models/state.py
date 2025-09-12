from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import numpy as np


@dataclass
class MemoryVector:
    ma: Dict[str, Any]
    mw: Dict[str, Any]
    mlt: Dict[str, Any]
    mfb: Dict[str, Any]


@dataclass
class OrganState:
    h: np.ndarray
    P: np.ndarray
    v_pso: Optional[np.ndarray] = None

    def P_agg(self) -> np.ndarray:
        """Aggregate per-agent role probabilities to organ-level distribution P(o)."""
        if self.P is None or self.P.size == 0:
            return np.zeros(3, dtype=np.float32)
        try:
            agg = np.asarray(self.P, dtype=np.float32)
            if agg.ndim == 1:
                # Already aggregated or single agent
                if agg.shape[0] == 3:
                    return agg.astype(np.float32, copy=False)
                # Fallback
                return np.zeros(3, dtype=np.float32)
            # Mean over agents
            agg_vec = np.mean(agg, axis=0)
            # Ensure length 3
            if agg_vec.shape[0] >= 3:
                return agg_vec[:3].astype(np.float32, copy=False)
            out = np.zeros(3, dtype=np.float32)
            out[: agg_vec.shape[0]] = agg_vec.astype(np.float32, copy=False)
            return out
        except Exception:
            return np.zeros(3, dtype=np.float32)


@dataclass
class SystemState:
    h_hgnn: Optional[np.ndarray] = None
    E_patterns: Optional[np.ndarray] = None
    w_mode: Optional[np.ndarray] = None


@dataclass
class AgentSnapshot:
    h: np.ndarray
    p: Dict[str, float]
    c: float
    mem_util: float
    lifecycle: str


@dataclass
class UnifiedState:
    agents: Dict[str, AgentSnapshot]
    organs: Dict[str, OrganState]
    system: SystemState
    memory: MemoryVector

    def H_matrix(self) -> np.ndarray:
        if not self.agents:
            return np.zeros((0, 0), dtype=np.float32)
        return np.vstack([np.asarray(a.h, dtype=np.float32) for a in self.agents.values()])

    def P_matrix(self) -> np.ndarray:
        if not self.agents:
            return np.zeros((0, 3), dtype=np.float32)
        rows: List[List[float]] = []
        for a in self.agents.values():
            rows.append([
                float(a.p.get("E", 0.0)),
                float(a.p.get("S", 0.0)),
                float(a.p.get("O", 0.0)),
            ])
        return np.asarray(rows, dtype=np.float32)

    def s_norm(self) -> float:
        """Return ||H|| (L2) as scalar used by L2 regularization term."""
        H = self.H_matrix()
        if H.size == 0:
            return 0.0
        return float(np.linalg.norm(H))

    def hyper_selection(self) -> np.ndarray:
        """Return hyperedge selection/activation vector E_sel used in hyper term."""
        if self.system is None or self.system.E_patterns is None:
            return np.asarray([], dtype=np.float32)
        return np.asarray(self.system.E_patterns, dtype=np.float32)


