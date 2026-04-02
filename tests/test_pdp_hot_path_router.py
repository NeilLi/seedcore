from __future__ import annotations

import json
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
from seedcore.models.action_intent import ExecutionToken, PolicyDecision
from seedcore.models.pdp_hot_path import HotPathDecisionView, HotPathEvaluateResponse
from seedcore.ops.hot_path_parity_log import parity_log_file_path, reset_hot_path_parity_logger_for_tests
import pytest


@pytest.fixture(autouse=True)
def _hot_path_parity_log_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_LOG", str(tmp_path / "events.jsonl"))
    reset_hot_path_parity_logger_for_tests()


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(pkg_router.router, prefix="/api/v1", tags=["PKG"])
    return TestClient(app)


def _base_payload() -> dict:
    return {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": "pdp-req-test-001",
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


def test_pdp_hot_path_quarantines_when_compiled_graph_unavailable(monkeypatch):
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: None)
    client = _make_client()

    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "hot_path_dependency_unavailable"
    assert body["execution_token"] is None


def test_pdp_hot_path_denies_asset_ref_mismatch(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()

    payload = _base_payload()
    payload["asset_context"]["asset_ref"] = "asset:lot-mismatch"
    response = client.post("/api/v1/pdp/hot-path/evaluate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "asset_custody_mismatch"


def test_pdp_hot_path_quarantines_snapshot_mismatch(monkeypatch):
    manager = _manager(snapshot_version="snapshot:pkg-other-2026-04-02")
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()

    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "snapshot_not_ready"


def test_pdp_hot_path_terminal_quarantine_updates_shadow_stats(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    monkeypatch.setattr(pdp_hot_path, "_HOT_PATH_SHADOW_STATS", pdp_hot_path.HotPathShadowStats())
    client = _make_client()

    payload = _base_payload()
    payload["request_id"] = "pdp-req-stale-001"
    payload["telemetry_context"]["freshness_seconds"] = 301
    payload["telemetry_context"]["max_allowed_age_seconds"] = 300
    response = client.post("/api/v1/pdp/hot-path/evaluate", json=payload)
    assert response.status_code == 200
    assert response.json()["decision"]["disposition"] == "quarantine"
    assert response.json()["decision"]["reason_code"] == "stale_telemetry"

    status = client.get("/api/v1/pdp/hot-path/status")
    assert status.status_code == 200
    body = status.json()
    assert body["total"] == 1
    assert body["parity_ok"] == 1
    assert body["mismatched"] == 0
    assert body["recent_results"][-1]["request_id"] == "pdp-req-stale-001"
    assert body["recent_results"][-1]["candidate"]["disposition"] == "quarantine"
    assert body["recent_results"][-1]["parity_ok"] is True


def test_pdp_hot_path_allow_includes_execution_token_and_signer_provenance(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)

    fake_decision = PolicyDecision(
        allowed=True,
        reason="restricted_custody_transfer_allowed",
        disposition="allow",
        policy_snapshot="snapshot:pkg-prod-2026-04-02",
        execution_token=ExecutionToken(
            token_id="token-transfer-001",
            intent_id="intent-transfer-001",
            issued_at="2026-04-02T08:00:16Z",
            valid_until="2026-04-02T08:01:16Z",
            contract_version="rules@transfer-v1",
            constraints={"asset_id": "asset:lot-8841"},
            signature={
                "signer_type": "service",
                "signer_id": "seedcore-verify",
                "key_ref": "kms:seedcore/pdp",
                "attestation_level": "baseline",
            },
        ),
        governed_receipt={
            "decision_hash": "receipt-transfer-001",
            "snapshot_ref": "snapshot:pkg-prod-2026-04-02",
            "snapshot_hash": "sha256:snapshot-hash-transfer-001",
        },
        obligations=[{"code": "publish_replay_artifact"}],
    )
    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", lambda *args, **kwargs: fake_decision)
    client = _make_client()

    response = client.post("/api/v1/pdp/hot-path/evaluate?debug=true", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "allow"
    assert body["execution_token"]["token_id"] == "token-transfer-001"
    assert body["signer_provenance"][0]["artifact_type"] == "execution_token"
    assert body["signer_provenance"][0]["signer_id"] == "seedcore-verify"


def test_pdp_hot_path_quarantines_when_compiled_graph_is_stale(monkeypatch):
    stale_compiled_at = (datetime.now(timezone.utc) - timedelta(minutes=11)).isoformat()
    manager = _manager(compiled_at=stale_compiled_at)
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()

    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "compiled_authz_graph_stale"


def test_pdp_hot_path_status_reports_runtime_readiness_and_mode(monkeypatch):
    compiled_at = datetime.now(timezone.utc).isoformat()
    manager = _manager(compiled_at=compiled_at)
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    monkeypatch.setattr(pdp_hot_path, "_HOT_PATH_SHADOW_STATS", pdp_hot_path.HotPathShadowStats())
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_MODE", "enforce")
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED", "1")
    pdp_hot_path.record_false_positive_hot_path_signal(
        request_id="req-false-positive",
        asset_ref="asset:lot-8841",
        baseline_disposition="deny",
        candidate_disposition="allow",
        baseline_reason_code="policy_denied",
        candidate_reason_code="restricted_custody_transfer_allowed",
    )
    client = _make_client()

    response = client.get("/api/v1/pdp/hot-path/status")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "enforce"
    assert body["resolved_mode"] == "enforce"
    assert body["authz_graph_ready"] is True
    assert body["graph_freshness_ok"] is True
    assert body["enforce_ready"] is False
    assert body["runtime_ready"] is True
    assert body["promotion"]["promotion_gate_disabled"] is True
    assert body["active_snapshot_version"] == "snapshot:pkg-prod-2026-04-02"
    assert body["compiled_at"] == compiled_at
    assert body["graph_age_seconds"] is not None
    assert body["false_positive_allow_count"] == 1
    assert body["last_false_positive_allow_at"] is not None
    assert body["recent_mismatch_count"] >= 1
    assert body["rollback_triggered"] is True
    assert "false_positive_allow" in body["rollback_reasons"]


def test_pdp_hot_path_route_resolves_and_forwards_authoritative_approval(monkeypatch):
    async def fake_resolve(request):
        assert request.action_intent.action.parameters["approval_context"]["approval_envelope_id"] == "approval-transfer-001"
        return {
            "authoritative_approval_envelope": {
                "approval_envelope_id": "approval-transfer-001",
                "status": "APPROVED",
            },
            "authoritative_approval_transition_history": [
                {"event_id": "approval-transition-event:001"}
            ],
            "authoritative_approval_transition_head": "sha256:transition-head-001",
        }

    def fake_evaluate(
        request,
        *,
        authoritative_approval_envelope=None,
        authoritative_approval_transition_history=None,
        authoritative_approval_transition_head=None,
    ):
        assert authoritative_approval_envelope == {
            "approval_envelope_id": "approval-transfer-001",
            "status": "APPROVED",
        }
        assert authoritative_approval_transition_history == [
            {"event_id": "approval-transition-event:001"}
        ]
        assert authoritative_approval_transition_head == "sha256:transition-head-001"
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=4,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="restricted_custody_transfer_allowed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        )

    monkeypatch.setattr(pkg_router, "resolve_authoritative_transfer_approval", fake_resolve)
    monkeypatch.setattr(pkg_router, "evaluate_pdp_hot_path", fake_evaluate)

    client = _make_client()
    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "allow"
    assert body["required_approvals"] == ["FACILITY_MANAGER", "QUALITY_INSPECTOR"]


def test_pdp_hot_path_persists_parity_event_jsonl(monkeypatch):
    manager = _manager()
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    fake_decision = PolicyDecision(
        allowed=True,
        reason="restricted_custody_transfer_allowed",
        disposition="allow",
        policy_snapshot="snapshot:pkg-prod-2026-04-02",
        governed_receipt={
            "snapshot_hash": "sha256:snapshot-hash-transfer-001",
            "snapshot_ref": "snapshot:pkg-prod-2026-04-02",
        },
    )
    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", lambda *args, **kwargs: fake_decision)
    client = _make_client()
    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())
    assert response.status_code == 200
    path = parity_log_file_path()
    assert path.is_file()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["request_id"] == "pdp-req-test-001"
    assert "parity_ok" in row
    assert "resolved_mode" in row


def test_pdp_hot_path_canary_mode_surfaces_percent(monkeypatch):
    compiled_at = datetime.now(timezone.utc).isoformat()
    manager = _manager(compiled_at=compiled_at)
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    monkeypatch.setattr(pdp_hot_path, "_HOT_PATH_SHADOW_STATS", pdp_hot_path.HotPathShadowStats())
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_MODE", "canary")
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_CANARY_PERCENT", "25")
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED", "1")
    client = _make_client()
    body = client.get("/api/v1/pdp/hot-path/status").json()
    assert body["mode"] == "canary"
    assert body["canary_percent"] == 25


def test_hot_path_canary_authority_is_stable_per_request_id(monkeypatch):
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_MODE", "canary")
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_CANARY_PERCENT", "50")
    rid = "custody-transfer-req-stable"
    a = pdp_hot_path.hot_path_authority_uses_candidate(rid)
    b = pdp_hot_path.hot_path_authority_uses_candidate(rid)
    assert a == b


def test_pdp_hot_path_enforce_ready_requires_promotion_window_when_gate_enabled(monkeypatch):
    compiled_at = datetime.now(timezone.utc).isoformat()
    manager = _manager(compiled_at=compiled_at)
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    monkeypatch.setattr(pdp_hot_path, "_HOT_PATH_SHADOW_STATS", pdp_hot_path.HotPathShadowStats())
    monkeypatch.setenv("SEEDCORE_RCT_HOT_PATH_MODE", "enforce")
    monkeypatch.delenv("SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED", raising=False)
    client = _make_client()
    body = client.get("/api/v1/pdp/hot-path/status").json()
    assert body["runtime_ready"] is True
    assert body["enforce_ready"] is False
    assert body["promotion"]["promotion_eligible"] is False
    assert body["promotion"]["window_events"] == 0
