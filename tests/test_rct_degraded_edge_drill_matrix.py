"""
Repeatable RCT degraded-edge / adversarial scenarios (Q2 schedule: drill matrix).

Maps to operational drills: identity mismatch (tamper stand-in), stale telemetry,
stale compiled graph, missing authz dependency, policy snapshot skew.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.pkg_router as pkg_router
import seedcore.ops.pdp_hot_path as pdp_hot_path
from seedcore.ops.hot_path_parity_log import reset_hot_path_parity_logger_for_tests
import pytest


@pytest.fixture(autouse=True)
def _hot_path_parity_log_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_LOG", str(tmp_path / "drill_events.jsonl"))
    reset_hot_path_parity_logger_for_tests()


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(pkg_router.router, prefix="/api/v1", tags=["PKG"])
    return TestClient(app)


def _base_payload() -> dict:
    return {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": "drill-req-001",
        "requested_at": "2026-04-02T08:00:15Z",
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-02",
        "action_intent": {
            "intent_id": "intent-transfer-001",
            "timestamp": "2026-04-02T08:00:15Z",
            "valid_until": "2026-04-02T08:01:15Z",
            "principal": {
                "agent_id": "agent:custody_runtime_01",
                "role_profile": "TRANSFER_COORDINATOR",
                "session_token": "session-transfer-001",
            },
            "action": {
                "type": "TRANSFER_CUSTODY",
                "operation": "MOVE",
                "parameters": {
                    "approval_context": {
                        "approval_envelope_id": "approval-transfer-001",
                        "approval_binding_hash": "sha256:approval-binding-transfer-001",
                        "required_roles": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
                        "approved_by": [
                            "principal:facility_mgr_001",
                            "principal:quality_insp_017",
                        ],
                    }
                },
                "security_contract": {
                    "hash": "policy-hash-transfer-001",
                    "version": "rules@transfer-v1",
                },
            },
            "resource": {
                "asset_id": "asset:lot-8841",
                "target_zone": "handoff_bay_3",
                "provenance_hash": "asset-proof-hash-8841",
                "category_envelope": {
                    "transfer_context": {
                        "from_zone": "vault_a",
                        "to_zone": "handoff_bay_3",
                        "expected_current_custodian": "principal:facility_mgr_001",
                        "next_custodian": "principal:outbound_mgr_002",
                    }
                },
            },
            "environment": {"origin_network": "network:warehouse_core"},
        },
        "asset_context": {
            "asset_ref": "asset:lot-8841",
            "current_custodian_ref": "principal:facility_mgr_001",
            "current_zone": "vault_a",
            "source_registration_status": "APPROVED",
            "registration_decision_ref": "registration_decision:abc123",
        },
        "telemetry_context": {
            "observed_at": "2026-04-02T08:00:10Z",
            "freshness_seconds": 5,
            "max_allowed_age_seconds": 60,
            "evidence_refs": ["evidence:telemetry-001"],
        },
    }


def _manager(*, snapshot_version: str = "snapshot:pkg-prod-2026-04-02", compiled_at: str | None = None):
    authz_status = {
        "healthy": True,
        "active_snapshot_version": snapshot_version,
        "compiled_at": compiled_at,
        "restricted_transfer_ready": True,
    }
    return SimpleNamespace(
        get_active_compiled_authz_index=lambda: SimpleNamespace(
            snapshot_version=snapshot_version,
            compiled_at=compiled_at,
            restricted_transfer_ready=True,
        ),
        get_metadata=lambda: {"authz_graph": authz_status},
    )


@pytest.mark.rct_degraded_edge
def test_drill_asset_identity_mismatch_denies(monkeypatch):
    """Stand-in for coordinate / shelf identity tamper: intent asset != context asset."""
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()
    payload = _base_payload()
    payload["asset_context"]["asset_ref"] = "asset:lot-attacker-999"
    body = client.post("/api/v1/pdp/hot-path/evaluate", json=payload).json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "asset_custody_mismatch"


@pytest.mark.rct_degraded_edge
def test_drill_stale_telemetry_quarantines(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()
    payload = _base_payload()
    payload["telemetry_context"]["freshness_seconds"] = 400
    payload["telemetry_context"]["max_allowed_age_seconds"] = 300
    body = client.post("/api/v1/pdp/hot-path/evaluate", json=payload).json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "stale_telemetry"
    assert "stale_telemetry" in (body.get("trust_gaps") or [])


@pytest.mark.rct_degraded_edge
def test_drill_compiled_authz_graph_stale_quarantines(monkeypatch):
    stale_compiled_at = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    manager = _manager(compiled_at=stale_compiled_at)
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()
    body = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload()).json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "compiled_authz_graph_stale"


@pytest.mark.rct_degraded_edge
def test_drill_compiled_authz_dependency_unavailable_quarantines(monkeypatch):
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: None)
    client = _make_client()
    body = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload()).json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "hot_path_dependency_unavailable"


@pytest.mark.rct_degraded_edge
def test_drill_policy_snapshot_skew_quarantines(monkeypatch):
    """Replay / promotion skew: request snapshot does not match active compiled graph."""
    manager = _manager(snapshot_version="snapshot:pkg-canary-2026-04-02")
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()
    body = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload()).json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "snapshot_not_ready"
