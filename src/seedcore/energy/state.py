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


