import numpy as np
from seedcore.energy.weights import EnergyWeights
from seedcore.services.energy_service import EnergyService


def test_energy_service_hyper_weight_projection():
    svc = EnergyService()
    us = {
        "agents": {
            "a1": {"h": [0.1, 0.2], "p": {"E": 0.34, "S": 0.33, "O": 0.33}, "c": 0.5, "mem_util": 0.2, "lifecycle": "Employed"},
            "a2": {"h": [0.0, 0.1], "p": {"E": 0.3, "S": 0.3, "O": 0.4}, "c": 0.5, "mem_util": 0.2, "lifecycle": "Employed"},
        },
        "organs": {},
        "system": {"E_patterns": [1.0, 1.0, 1.0, 1.0]},
        "memory": {"ma": {}, "mw": {}, "mlt": {}, "mfb": {}},
    }
    # Provide mismatched W_hyper
    req = type("Req", (), {
        "unified_state": type("US", (), {"dict": lambda self: us})(),
        "weights": type("W", (), {"dict": lambda self: {"W_pair": [[1.0]], "W_hyper": [1.0, 1.0]}})(),
        "include_gradients": False,
        "include_breakdown": True,
    })()
    # Directly call the endpoint function
    resp = None
    try:
        import asyncio
        resp = asyncio.get_event_loop().run_until_complete(svc.compute_energy_endpoint(req))
    except RuntimeError:
        # If no running loop, create one
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        resp = loop.run_until_complete(svc.compute_energy_endpoint(req))
    assert resp.success is True
    assert isinstance(resp.energy, dict)

