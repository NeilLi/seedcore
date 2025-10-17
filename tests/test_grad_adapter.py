import time
import numpy as np

from seedcore.ops.energy.grad_adapter import InProcEnergySource, GradientBus


def make_unified_state_dict(n_agents: int = 3, d: int = 4, e_len: int = 2):
    agents = {}
    for i in range(n_agents):
        agents[f"a{i}"] = {
            "h": np.random.randn(d).astype(np.float32).tolist(),
            "p": {"E": 1/3, "S": 1/3, "O": 1/3},
            "c": 0.5,
            "mem_util": 0.2,
            "lifecycle": "Employed",
        }
    return {
        "agents": agents,
        "organs": {},
        "system": {"E_patterns": np.ones(e_len, dtype=np.float32).tolist()},
        "memory": {"ma": {}, "mw": {}, "mlt": {}, "mfb": {}},
    }


def test_inproc_energy_source_shapes_and_fields():
    src = InProcEnergySource()
    us = make_unified_state_dict()
    grads = src.compute(us)
    assert isinstance(grads.at, float)
    assert isinstance(grads.dE_dP_entropy, float)
    assert isinstance(grads.dE_dmem, float)
    assert isinstance(grads.breakdown, dict)
    assert grads.dE_dH is None or hasattr(grads.dE_dH, "shape")


def test_gradient_bus_caches_with_ttl():
    src = InProcEnergySource()
    bus = GradientBus(src, ttl_ms=200)
    us = make_unified_state_dict()
    g1 = bus.latest(us, allow_stale=False)
    t1 = g1.at
    g2 = bus.latest(us, allow_stale=True)
    assert g1 is g2
    time.sleep(0.25)
    g3 = bus.latest(us, allow_stale=False)
    assert g3.at >= t1

