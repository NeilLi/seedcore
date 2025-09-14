from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import time
import os
import numpy as np  # type: ignore

from .calculator import energy_and_grad, compute_energy_unified, SystemParameters
from .weights import EnergyWeights


@dataclass
class Gradients:
    at: float
    dE_dH: Optional[np.ndarray]
    dE_dP_entropy: float
    dE_dE_sel: Optional[np.ndarray]
    dE_dmem: float
    breakdown: Dict[str, float]


class GradientSource:
    def compute(self, unified_state) -> Gradients:  # pragma: no cover - interface
        raise NotImplementedError


class InProcEnergySource(GradientSource):
    """Compute gradients in-process via unified wrapper."""

    def __init__(self, default_alpha: float = 0.1, default_lambda: float = 0.01, default_beta_mem: float = 0.05):
        self.default_alpha = float(default_alpha)
        self.default_lambda = float(default_lambda)
        self.default_beta_mem = float(default_beta_mem)

    def _shape_weights(self, H: np.ndarray, E_sel: Optional[np.ndarray]) -> EnergyWeights:
        n_agents = H.shape[0] if H.size > 0 else 1
        n_hyper = int(E_sel.shape[0]) if E_sel is not None and hasattr(E_sel, "shape") else 1
        return EnergyWeights(
            W_pair=np.eye(n_agents, dtype=np.float32) * 0.1,
            W_hyper=np.ones((n_hyper,), dtype=np.float32) * 0.1,
            alpha_entropy=self.default_alpha,
            lambda_reg=self.default_lambda,
            beta_mem=self.default_beta_mem,
        )

    def compute(self, unified_state) -> Gradients:
        # Accept either typed UnifiedState or a dict with agents/system
        if hasattr(unified_state, "to_energy_state"):
            try:
                us = unified_state.projected()
            except Exception:
                us = unified_state
            state = us.to_energy_state()
            H = state["h_agents"]
            P = state["P_roles"]
            E_sel = state.get("hyper_sel")
            s_norm = float(state.get("s_norm", 0.0))
        else:
            agents = unified_state.get("agents", {})
            H = np.vstack([np.asarray(v.get("h", []), dtype=np.float32) for v in agents.values()]) if agents else np.zeros((0, 0), dtype=np.float32)
            P = np.asarray([[float(v.get("p", {}).get("E", 0.0)), float(v.get("p", {}).get("S", 0.0)), float(v.get("p", {}).get("O", 0.0))] for v in agents.values()], dtype=np.float32) if agents else np.zeros((0, 3), dtype=np.float32)
            sysd = unified_state.get("system", {})
            E_sel = np.asarray(sysd.get("E_patterns", []), dtype=np.float32) if sysd.get("E_patterns") is not None else None
            s_norm = float(np.linalg.norm(H)) if H.size > 0 else 0.0

        weights = self._shape_weights(H, E_sel)
        memory_stats = {"r_effective": 1.0, "p_compress": 0.0}
        result = compute_energy_unified(
            # If unified_state has to_energy_state, wrapper will project and convert
            unified_state if hasattr(unified_state, "to_energy_state") else {"h_agents": H, "P_roles": P, "hyper_sel": E_sel, "s_norm": s_norm},
            SystemParameters(weights=weights, memory_stats=memory_stats, include_gradients=True),
        )
        breakdown = result.breakdown
        grad = result.gradients or {}
        return Gradients(
            at=time.time() * 1000,
            dE_dH=grad.get("dE/dH"),
            dE_dP_entropy=float(grad.get("dE/dP_entropy", 0.0)),
            dE_dE_sel=grad.get("dE/dE_sel"),
            dE_dmem=float(grad.get("dE/dmem", 0.0)),
            breakdown=breakdown,
        )


class ServiceEnergySource(GradientSource):
    """Compute via the Energy Service HTTP API using /energy/compute-energy (with gradients)."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")

    def compute(self, unified_state) -> Gradients:
        try:
            import requests  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("requests not available for ServiceEnergySource") from e

        url = f"{self.base_url}/energy/compute-energy"
        payload = {
            "unified_state": unified_state if not hasattr(unified_state, "H_matrix") else self._serialize_unified_state(unified_state),
            "weights": None,
            "include_gradients": True,
            "include_breakdown": True,
        }
        resp = requests.post(url, json=payload, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise RuntimeError(f"Energy service compute failed: {data}")
        breakdown = data.get("breakdown") or data.get("energy") or {}
        grads = data.get("gradients") or {}
        return Gradients(
            at=time.time() * 1000,
            dE_dH=np.asarray(grads.get("dE/dH"), dtype=np.float32) if grads.get("dE/dH") is not None else None,
            dE_dP_entropy=float(grads.get("dE/dP_entropy", 0.0)) if grads else 0.0,
            dE_dE_sel=np.asarray(grads.get("dE/dE_sel"), dtype=np.float32) if grads.get("dE/dE_sel") is not None else None,
            dE_dmem=float(grads.get("dE/dmem", 0.0)) if grads else 0.0,
            breakdown={k: float(v) for k, v in breakdown.items()},
        )

    def _serialize_unified_state(self, us) -> Dict[str, Any]:
        return {
            "agents": {
                aid: {
                    "h": (a.h.tolist() if hasattr(a.h, "tolist") else a.h),
                    "p": a.p,
                    "c": a.c,
                    "mem_util": a.mem_util,
                    "lifecycle": a.lifecycle,
                }
                for aid, a in us.agents.items()
            },
            "organs": {
                oid: {
                    "h": (o.h.tolist() if hasattr(o.h, "tolist") else o.h),
                    "P": (o.P.tolist() if hasattr(o.P, "tolist") else o.P),
                    "v_pso": (o.v_pso.tolist() if (o.v_pso is not None and hasattr(o.v_pso, "tolist")) else o.v_pso),
                }
                for oid, o in us.organs.items()
            },
            "system": {
                "h_hgnn": (us.system.h_hgnn.tolist() if (us.system.h_hgnn is not None and hasattr(us.system.h_hgnn, "tolist")) else us.system.h_hgnn),
                "E_patterns": (us.system.E_patterns.tolist() if (us.system.E_patterns is not None and hasattr(us.system.E_patterns, "tolist")) else us.system.E_patterns),
                "w_mode": (us.system.w_mode.tolist() if (us.system.w_mode is not None and hasattr(us.system.w_mode, "tolist")) else us.system.w_mode),
            },
            "memory": {
                "ma": us.memory.ma,
                "mw": us.memory.mw,
                "mlt": us.memory.mlt,
                "mfb": us.memory.mfb,
            },
        }


class GradientBus:
    def __init__(self, src: GradientSource, ttl_ms: int = 500):
        self.src = src
        self.ttl_ms = int(ttl_ms)
        self._last: Optional[Gradients] = None

    def latest(self, unified_state, allow_stale: bool = True) -> Gradients:
        now = time.time() * 1000
        if self._last and (now - self._last.at) <= self.ttl_ms:
            return self._last
        try:
            self._last = self.src.compute(unified_state)
            return self._last
        except Exception:
            if allow_stale and self._last:
                return self._last
            raise


_global_bus: Optional[GradientBus] = None


def get_global_gradient_bus() -> GradientBus:
    global _global_bus
    if _global_bus is not None:
        return _global_bus
    source_kind = (os.getenv("GRADIENT_SOURCE", "inproc").lower())
    ttl_ms = int(os.getenv("GRADIENT_TTL_MS", "500"))
    if source_kind == "service":
        base_url = os.getenv("ENERGY_SERVICE_URL", "http://localhost:8000")
        src = ServiceEnergySource(base_url)
    else:
        src = InProcEnergySource()
    _global_bus = GradientBus(src, ttl_ms=ttl_ms)
    return _global_bus


