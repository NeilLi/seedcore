from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.agent_actions_router as agent_actions_router
from seedcore.models.action_intent import ExecutionToken
from seedcore.models.pdp_hot_path import HotPathDecisionView, HotPathEvaluateResponse


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(agent_actions_router.router, prefix="/api/v1", tags=["Agent Actions"])
    return TestClient(app)


def _base_payload() -> dict:
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": "req-transfer-2026-0001",
        "requested_at": "2026-03-31T10:00:00Z",
        "idempotency_key": "idem-transfer-2026-0001",
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31",
        "principal": {
            "agent_id": "agent:custody_runtime_01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-abc",
            "delegation_ref": "delegation:owner-8841-transfer",
            "organization_ref": "org:warehouse-north",
        },
        "workflow": {
            "type": "restricted_custody_transfer",
            "action_type": "TRANSFER_CUSTODY",
            "valid_until": "2026-03-31T10:01:00Z",
        },
        "asset": {
            "asset_id": "asset:lot-8841",
            "lot_id": "lot-8841",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:asset-provenance",
        },
        "approval": {
            "approval_envelope_id": "approval-transfer-001",
            "expected_envelope_version": "23",
        },
        "telemetry": {
            "observed_at": "2026-03-31T09:59:58Z",
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "evidence_refs": ["ev:cam-1", "ev:seal-sensor-7"],
        },
        "security_contract": {
            "hash": "sha256:contract-hash",
            "version": "rules@8.0.0",
        },
        "options": {"debug": False},
    }


def _base_closure_payload(
    *,
    request_id: str = "req-transfer-2026-0001",
    closure_id: str = "closure-transfer-2026-0001",
    idempotency_key: str = "idem-closure-2026-0001",
) -> dict:
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "closure_id": closure_id,
        "idempotency_key": idempotency_key,
        "closed_at": "2026-03-31T10:02:00Z",
        "outcome": "completed",
        "evidence_bundle_id": "evidence-bundle-001",
        "transition_receipt_ids": ["transition-receipt-001"],
        "node_id": "node-warehouse-gateway-01",
        "summary": {"settlement_target": "asset:lot-8841"},
    }


def _allow_hot_path_response() -> HotPathEvaluateResponse:
    return HotPathEvaluateResponse(
        request_id="req-transfer-2026-0001",
        decided_at=datetime.now(timezone.utc),
        latency_ms=42,
        decision=HotPathDecisionView(
            allowed=True,
            disposition="allow",
            reason_code="restricted_custody_transfer_allowed",
            reason="all mandatory checks passed",
            policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
        ),
        execution_token=ExecutionToken(
            token_id="token-transfer-001",
            intent_id="req-transfer-2026-0001",
            issued_at="2026-03-31T10:00:01Z",
            valid_until="2026-03-31T10:00:06Z",
            contract_version="rules@8.0.0",
        ),
        governed_receipt={
            "audit_id": "audit-abc",
            "policy_receipt_id": "receipt-policy-1",
        },
    )


async def _empty_authoritative_approval(*args, **kwargs):
    return {}


async def _organism_preflight_ok(*args, **kwargs):
    return True, "ok"


async def _organism_preflight_fail(*args, **kwargs):
    return False, "organism_route_unavailable:RuntimeError"


def test_agent_actions_evaluate_wraps_hot_path_result(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "seedcore.agent_action_gateway.v1"
    assert body["request_id"] == "req-transfer-2026-0001"
    assert body["decision"]["disposition"] == "allow"
    assert body["execution_token"]["token_id"] == "token-transfer-001"
    assert "ExecutionToken" in body["minted_artifacts"]
    assert "PolicyReceipt" in body["minted_artifacts"]


def test_agent_actions_evaluate_maps_gateway_payload_to_hot_path_request(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    captured = {}

    def _fake_evaluate(request, **kwargs):
        captured["request"] = request
        return _allow_hot_path_response()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    payload = _base_payload()
    payload.pop("policy_snapshot_ref")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200

    mapped_request = captured["request"]
    assert mapped_request.request_id == payload["request_id"]
    assert mapped_request.policy_snapshot_ref == "rules@8.0.0"
    assert mapped_request.asset_context.asset_ref == "asset:lot-8841"
    assert mapped_request.asset_context.current_custodian_ref == "principal:facility_mgr_001"
    assert (
        mapped_request.action_intent.action.parameters["approval_context"]["approval_envelope_id"]
        == "approval-transfer-001"
    )
    assert mapped_request.action_intent.resource.lot_id == "lot-8841"
    assert mapped_request.action_intent.resource.target_zone == "handoff_bay_3"


def test_agent_actions_evaluate_requires_identity_proof():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    payload = _base_payload()
    payload["principal"].pop("session_token")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 422


def test_agent_actions_get_request_record_returns_stored_response(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    call_count = {"value": 0}

    def _fake_evaluate(*args, **kwargs):
        call_count["value"] += 1
        return _allow_hot_path_response()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    post_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert post_response.status_code == 200
    get_response = client.get("/api/v1/agent-actions/requests/req-transfer-2026-0001")
    assert get_response.status_code == 200
    body = get_response.json()
    assert body["request_id"] == "req-transfer-2026-0001"
    assert body["idempotency_key"] == "idem-transfer-2026-0001"
    assert body["status"] == "completed"
    assert body["response"]["decision"]["disposition"] == "allow"
    assert call_count["value"] == 1


def test_agent_actions_idempotency_replay_and_conflict(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    call_count = {"value": 0}

    def _fake_evaluate(*args, **kwargs):
        call_count["value"] += 1
        return _allow_hot_path_response()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    first_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert first_response.status_code == 200

    same_payload_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert same_payload_response.status_code == 200
    assert call_count["value"] == 1

    conflicting_payload = _base_payload()
    conflicting_payload["request_id"] = "req-transfer-2026-0002"
    conflicting_payload["asset"]["asset_id"] = "asset:lot-9000"
    conflict_response = client.post("/api/v1/agent-actions/evaluate", json=conflicting_payload)
    assert conflict_response.status_code == 409
    detail = conflict_response.json()["detail"]
    assert detail["error_code"] == "idempotency_conflict"


def test_agent_actions_get_request_record_returns_not_found():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    response = client.get("/api/v1/agent-actions/requests/missing-request-id")
    assert response.status_code == 404


def test_agent_actions_evaluate_quarantines_when_organism_preflight_fails(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_fail)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "organism_not_ready"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert "organism_not_ready" in body["trust_gaps"]


def test_agent_actions_closure_accepts_allow_request_and_records(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    closure_payload = _base_closure_payload()
    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=closure_payload,
    )
    assert close_response.status_code == 200
    close_body = close_response.json()
    assert close_body["request_id"] == "req-transfer-2026-0001"
    assert close_body["closure_id"] == "closure-transfer-2026-0001"
    assert close_body["status"] == "accepted_pending_settlement"
    assert close_body["settlement_status"] == "pending"
    assert close_body["replay_status"] == "pending"
    assert close_body["linked_disposition"] == "allow"

    get_response = client.get("/api/v1/agent-actions/closures/closure-transfer-2026-0001")
    assert get_response.status_code == 200
    record_body = get_response.json()
    assert record_body["closure_id"] == "closure-transfer-2026-0001"
    assert record_body["request_id"] == "req-transfer-2026-0001"
    assert record_body["status"] == "completed"


def test_agent_actions_closure_rejects_missing_request():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert response.status_code == 404


def test_agent_actions_closure_idempotency_replay_and_conflict(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    closure_payload = _base_closure_payload()
    first_close = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=closure_payload,
    )
    assert first_close.status_code == 200

    replay_close = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=closure_payload,
    )
    assert replay_close.status_code == 200

    conflicting_payload = _base_closure_payload()
    conflicting_payload["evidence_bundle_id"] = "evidence-bundle-999"
    conflict_close = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=conflicting_payload,
    )
    assert conflict_close.status_code == 409
    detail = conflict_close.json()["detail"]
    assert detail["error_code"] == "idempotency_conflict"


def test_agent_actions_closure_rejects_non_allow_request(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_fail)

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.status_code == 409
    detail = close_response.json()["detail"]
    assert detail["error_code"] == "closure_not_allowed"


def test_agent_actions_closure_marks_replay_ready_when_settlement_applied(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        lambda *args, **kwargs: _allow_hot_path_response(),
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    async def _settlement_applied(*args, **kwargs):
        return "applied", {"updated": 3, "version_bumped": 3}

    monkeypatch.setattr(agent_actions_router, "_apply_closure_settlement_handoff", _settlement_applied)

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.status_code == 200
    body = close_response.json()
    assert body["settlement_status"] == "applied"
    assert body["replay_status"] == "ready"
    assert body["settlement_result"]["updated"] == 3
