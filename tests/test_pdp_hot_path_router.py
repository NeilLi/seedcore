from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
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
    manager = SimpleNamespace(
        get_active_compiled_authz_index=lambda: SimpleNamespace(snapshot_version="snapshot:pkg-prod-2026-04-02")
    )
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
    manager = SimpleNamespace(
        get_active_compiled_authz_index=lambda: SimpleNamespace(snapshot_version="snapshot:pkg-other-2026-04-02")
    )
    monkeypatch.setattr(pdp_hot_path, "get_global_pkg_manager", lambda: manager)
    client = _make_client()

    response = client.post("/api/v1/pdp/hot-path/evaluate", json=_base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "snapshot_not_ready"


def test_pdp_hot_path_allow_includes_execution_token_and_signer_provenance(monkeypatch):
    manager = SimpleNamespace(
        get_active_compiled_authz_index=lambda: SimpleNamespace(snapshot_version="snapshot:pkg-prod-2026-04-02")
    )
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
