import os
os.environ.setdefault("RAY_DISABLE_IMPORT_WARNING", "1")

import numpy as np
import pytest
import sys
import types

# Stub ray to avoid optional dependency impact in unit tests
sys.modules.setdefault("ray", types.SimpleNamespace())

from seedcore.models.state import UnifiedState, AgentSnapshot, OrganState, SystemState, MemoryVector
from seedcore.energy.calculator import compute_energy_unified, SystemParameters
from seedcore.energy.weights import EnergyWeights


def _simple_unified_state(n: int = 3, d: int = 4) -> UnifiedState:
    agents = {}
    for i in range(n):
        h = np.arange(d, dtype=np.float32) * (i + 1) * 0.01
        p = {"E": 0.34, "S": 0.33, "O": 0.33}
        agents[f"a{i}"] = AgentSnapshot(h=h, p=p, c=1.0, mem_util=0.1, lifecycle="Employed")
    organs = {}
    system = SystemState(E_patterns=np.array([1.0, 0.5, 0.2], dtype=np.float32))
    memory = MemoryVector(ma={}, mw={}, mlt={}, mfb={})
    return UnifiedState(agents=agents, organs=organs, system=system, memory=memory)


def _weights_for(H: np.ndarray, E_sel: np.ndarray | None) -> EnergyWeights:
    n = H.shape[0] if H.size > 0 else 1
    k = (E_sel.shape[0] if (E_sel is not None and E_sel.size > 0) else 1)
    return EnergyWeights(
        W_pair=np.eye(n, dtype=np.float32) * 0.1,
        W_hyper=np.ones((k,), dtype=np.float32) * 0.1,
        alpha_entropy=0.1,
        lambda_reg=0.01,
        beta_mem=0.05,
    )


def test_to_energy_state_shapes():
    us = _simple_unified_state()
    s = us.projected().to_energy_state()
    assert isinstance(s["s_norm"], float)
    H = s["h_agents"]; P = s["P_roles"]
    assert isinstance(H, np.ndarray) and H.dtype == np.float32
    assert isinstance(P, np.ndarray) and P.dtype == np.float32
    if H.size:
        assert H.ndim == 2
        assert P.shape[0] == H.shape[0]
        assert P.shape[1] == 3
        row_sums = P.sum(axis=1)
        assert np.all(np.isfinite(row_sums))
        assert np.allclose(row_sums, 1.0, atol=1e-3)


def test_compute_energy_unified_empty_ok():
    us = UnifiedState(agents={}, organs={}, system=SystemState(), memory=MemoryVector())
    s = us.projected().to_energy_state()
    H = s["h_agents"]; E = s["hyper_sel"]
    params = SystemParameters(weights=_weights_for(H, E), memory_stats={}, include_gradients=True)
    res = compute_energy_unified(us, params)
    assert {"pair","hyper","entropy","reg","mem","total"}.issubset(set(res.breakdown.keys()))
    # gradients should not crash and types are present
    assert isinstance(res.breakdown["total"], float)


def test_gradient_shapes_match():
    us = _simple_unified_state(n=2, d=3)
    s = us.projected().to_energy_state()
    H = s["h_agents"]; E = s["hyper_sel"]
    params = SystemParameters(weights=_weights_for(H, E), memory_stats={}, include_gradients=True)
    res = compute_energy_unified(us, params)
    if H.size:
        dH = res.gradients.get("dE/dH") if res.gradients else None
        assert dH is not None
        assert isinstance(dH, np.ndarray)
        assert dH.shape == H.shape


def test_hyper_grad_shape_matches():
    us = _simple_unified_state(n=1, d=2)
    s = us.projected().to_energy_state()
    H = s["h_agents"]; E = s["hyper_sel"]
    params = SystemParameters(weights=_weights_for(H, E), memory_stats={}, include_gradients=True)
    res = compute_energy_unified(us, params)
    g = res.gradients or {}
    if E.size > 0:
        dEsel = g.get("dE/dE_sel")
        assert dEsel is not None
        assert isinstance(dEsel, np.ndarray)
        assert dEsel.shape == E.shape
    else:
        assert g.get("dE/dE_sel") is None


