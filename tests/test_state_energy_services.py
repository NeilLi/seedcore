import os
import sys
import types

os.environ.setdefault("RAY_DISABLE_IMPORT_WARNING", "1")

import mock_ray_dependencies  # noqa: F401


def _serve_decorator(*args, **kwargs):
    def decorator(cls):
        cls.bind = staticmethod(lambda *bind_args, **bind_kwargs: cls)
        return cls
    return decorator


ray_serve_stub = types.SimpleNamespace(
    deployment=_serve_decorator,
    ingress=lambda app: (lambda cls: cls),
)
sys.modules["ray.serve"] = ray_serve_stub

from seedcore.services import energy_service, state_service


def test_state_operational_summary_surfaces_pressure():
    summary = state_service._build_operational_summary(
        agent_metrics={
            "total_agents": 3,
            "avg_capability": 0.25,
            "avg_memory_util": 0.85,
            "specialization_load": {"planner": 0.95, "router": 0.90},
            "pair_matrix_present": False,
        },
        memory_stats={
            "mw": {"hit_rate": 0.30, "miss_rate": 0.70, "eviction_rate": 0.40},
            "mlt": {"status": "degraded"},
            "mfb": {"queue_size": 900},
        },
        e_patterns=[],
    )

    assert summary["memory_pressure"] > 0.6
    assert summary["coordination_pressure"] > 0.6
    assert summary["topology_ready"] is False
    assert summary["fast_path_ready"] is False


def test_energy_annotations_are_deterministic_without_ml():
    annotations = energy_service._derive_state_annotations(
        {
            "memory": {
                "ma": {
                    "avg_capability": 0.20,
                    "avg_memory_util": 0.80,
                    "specialization_load": {"planner": 0.90, "router": 0.85},
                    "pair_matrix_present": False,
                },
                "mw": {"hit_rate": 0.25, "miss_rate": 0.75, "eviction_rate": 0.40},
                "mlt": {"compression_ratio": 1.8},
                "mfb": {"queue_size": 800},
            },
            "ops": {"memory_pressure": 0.72},
            "system": {"E_patterns": [0.1, 0.2, 0.3]},
        }
    )

    assert annotations["signal_source"] == "state-heuristic"
    assert annotations["drift"] > 0.5
    assert annotations["scaling_score"] > 0.7
    assert 0.05 <= annotations["p_fast"] < 0.5
    assert annotations["memory_stats"]["r_effective"] >= 1.0


def test_energy_meta_uses_runtime_weights_and_router_counters():
    old_fast = energy_service.state.router_fast_hits
    old_esc = energy_service.state.router_escalations
    old_beta = energy_service.state.default_weights.beta_mem
    old_annotations = dict(energy_service.state.last_annotations)

    try:
        energy_service.state.router_fast_hits = 8
        energy_service.state.router_escalations = 2
        energy_service.state.default_weights.beta_mem = 0.2
        energy_service.state.last_annotations = {"signal_source": "state-heuristic"}

        meta = energy_service._build_meta_payload()

        assert meta["p_fast"] == 0.8
        assert meta["p_esc"] == 0.2
        assert meta["beta_mem"] == 0.2
        assert meta["L_tot"] < 1.0
        assert meta["ok_for_promotion"] is True
    finally:
        energy_service.state.router_fast_hits = old_fast
        energy_service.state.router_escalations = old_esc
        energy_service.state.default_weights.beta_mem = old_beta
        energy_service.state.last_annotations = old_annotations
