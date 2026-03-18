import os
import sys
import types
import uuid
from datetime import datetime, timezone

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

import pytest

from seedcore.models.source_registration import (
    SourceRegistration,
    SourceRegistrationStatus,
)
from seedcore.models.state import (
    AgentSnapshot,
    MemoryVector,
    SystemState,
    UnifiedState,
)
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


def test_project_authoritative_assets_projects_registration_status_and_zone():
    registration = SourceRegistration(
        id=uuid.uuid4(),
        source_claim_id="claim-7",
        lot_id="lot-7",
        producer_id="producer-7",
        status=SourceRegistrationStatus.QUARANTINED,
        claimed_origin={"zone_id": "vault-a"},
        collection_site={"site_id": "site-7"},
    )
    registration.updated_at = datetime(2026, 3, 18, 12, 30, tzinfo=timezone.utc)

    assets = state_service._project_authoritative_assets([registration])

    assert assets[str(registration.id)]["registration_status"] == "quarantined"
    assert assets[str(registration.id)]["is_quarantined"] is True
    assert assets[str(registration.id)]["current_zone"] == "vault-a"
    assert assets["lot-7"]["source_registration_id"] == str(registration.id)
    assert assets["claim-7"]["producer_id"] == "producer-7"


def test_unified_state_round_trips_assets_in_payload():
    state = UnifiedState(
        agents={
            "agent-1": AgentSnapshot(
                h=[0.1, 0.2, 0.3],
                p={"E": 0.5, "S": 0.3, "O": 0.2},
                c=0.9,
                mem_util=0.2,
                lifecycle="active",
            )
        },
        organs={},
        system=SystemState(),
        memory=MemoryVector(),
        assets={
            "lot-9": {
                "registration_status": "approved",
                "current_zone": "zone-c",
            }
        },
    )

    payload = state.to_payload()
    restored = UnifiedState.from_payload(payload)

    assert payload["assets"]["lot-9"]["current_zone"] == "zone-c"
    assert restored.assets["lot-9"]["registration_status"] == "approved"


@pytest.mark.asyncio
async def test_build_state_response_publishes_authoritative_assets(monkeypatch):
    class _AgentAggregator:
        async def get_system_metrics(self):
            return {
                "total_agents": 1,
                "avg_capability": 0.8,
                "avg_memory_util": 0.1,
                "specialization_load": {"planner": 0.2},
                "pair_matrix_present": True,
                "h_hgnn": [0.1, 0.2, 0.3],
            }

        async def get_last_update_time(self):
            return 123.0

        async def get_all_agent_snapshots(self):
            return {
                "agent-1": AgentSnapshot(
                    h=[0.1, 0.2, 0.3],
                    p={"E": 0.4, "S": 0.4, "O": 0.2},
                    c=1.0,
                    mem_util=0.1,
                    lifecycle="active",
                )
            }

        def is_running(self):
            return True

    class _MemoryAggregator:
        async def get_memory_stats(self):
            return {"mw": {"hit_rate": 0.9}, "mlt": {}, "mfb": {}}

        async def get_last_update_time(self):
            return 120.0

        def is_running(self):
            return True

    async def _fake_component_statuses():
        return {
            "agent": {"ready": True, "required": True, "last_update_time": 123.0},
            "memory": {"ready": True, "required": True, "last_update_time": 120.0},
            "system": {"ready": False, "required": False, "last_update_time": 0.0},
        }

    async def _fake_fetch_authoritative_assets(limit: int = 256):
        assert limit == 256
        return {
            "lot-11": {
                "registration_status": "approved",
                "current_zone": "zone-d",
                "is_quarantined": False,
            }
        }

    monkeypatch.setattr(state_service.state, "agent_aggregator", _AgentAggregator())
    monkeypatch.setattr(state_service.state, "memory_aggregator", _MemoryAggregator())
    monkeypatch.setattr(state_service.state, "system_aggregator", None)
    monkeypatch.setattr(state_service.state, "w_mode", state_service.DEFAULT_W_MODE.copy())
    monkeypatch.setattr(state_service, "_component_statuses", _fake_component_statuses)
    monkeypatch.setattr(
        state_service,
        "_fetch_authoritative_assets",
        _fake_fetch_authoritative_assets,
    )

    response = await state_service._build_state_response(include_unified_state=True)

    assert response.payload is not None
    assert response.payload.assets["lot-11"]["current_zone"] == "zone-d"
    assert response.payload.to_payload()["assets"]["lot-11"]["registration_status"] == "approved"
