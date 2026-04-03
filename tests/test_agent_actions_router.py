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

import seedcore.api.routers.agent_actions_router as agent_actions_router
from seedcore.models.action_intent import ExecutionToken
from seedcore.models.agent_action_gateway import AgentActionClosureRequest
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
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
            "organization_ref": "org:warehouse-north",
            "hardware_fingerprint": {
                "fingerprint_id": "fp:jetson-orin-01",
                "node_id": "node:jetson-orin-01",
                "public_key_fingerprint": "sha256:fingerprint-key",
                "attestation_type": "tpm",
                "key_ref": "tpm2:jetson-orin-01-ak",
            },
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
        "authority_scope": {
            "scope_id": "scope:rct-2026-0001",
            "asset_ref": "asset:lot-8841",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
            "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
        },
        "telemetry": {
            "observed_at": "2026-03-31T09:59:58Z",
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "current_zone": "vault_a",
            "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
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
        "forensic_block": {
            "forensic_block_id": "fb-2026-0001",
            "fingerprint_components": {
                "economic_hash": "sha256:shopify-order",
                "physical_presence_hash": "sha256:gazebo-point-cloud",
                "reasoning_hash": "sha256:reason-trace",
                "actuator_hash": "sha256:unitree-b2-torque",
            },
            "current_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
            "current_zone": "handoff_bay_3",
        },
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


def _bundle_manager(*, snapshot_version: str = "rules@8.0.0"):
    return SimpleNamespace(
        get_metadata=lambda: {"active_version": snapshot_version},
        get_active_request_schema_bundle=lambda: {
            "artifact_type": "request_schema_bundle",
            "snapshot_version": snapshot_version,
            "request_shape": {"required_task_fact_keys": ["tags", "signals", "context"]},
        },
        get_active_taxonomy_bundle=lambda: {
            "artifact_type": "taxonomy_bundle",
            "snapshot_version": snapshot_version,
            "trust_gap_codes": [{"code": "stale_telemetry"}],
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
    monkeypatch.setattr(agent_actions_router, "get_global_pkg_manager", lambda: _bundle_manager())
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    payload = _base_payload()
    payload["asset"]["declared_value_usd"] = 1500
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
    assert mapped_request.action_intent.action.parameters["value_usd"] == 1500.0
    assert mapped_request.request_schema_bundle["artifact_type"] == "request_schema_bundle"
    assert mapped_request.taxonomy_bundle["artifact_type"] == "taxonomy_bundle"


def test_agent_actions_evaluate_propagates_bundle_fields_on_response(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    def _fake_evaluate(request, **kwargs):
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=41,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            request_schema_bundle=request.request_schema_bundle,
            taxonomy_bundle=request.taxonomy_bundle,
        )

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "get_global_pkg_manager",
        lambda: _bundle_manager(snapshot_version="snapshot:pkg-prod-2026-03-31"),
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["request_schema_bundle"]["artifact_type"] == "request_schema_bundle"
    assert body["taxonomy_bundle"]["artifact_type"] == "taxonomy_bundle"


def test_agent_actions_evaluate_maps_scope_and_fingerprint_fields(monkeypatch):
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
    payload["principal"]["hardware_fingerprint"] = {
        "fingerprint_id": "fp:jetson-orin-01",
        "node_id": "node:jetson-orin-01",
        "public_key_fingerprint": "sha256:fingerprint-key",
    }
    payload["authority_scope"] = {
        "scope_id": "scope:rct-2026-0001",
        "asset_ref": "asset:lot-8841",
        "expected_from_zone": "vault_a",
        "expected_to_zone": "handoff_bay_3",
        "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
    }
    payload["forensic_context"] = {
        "reason_trace_ref": "reason:trace-1",
        "fingerprint_components": {
            "economic_hash": "sha256:econ",
            "physical_presence_hash": "sha256:presence",
            "reasoning_hash": "sha256:reasoning",
            "actuator_hash": "sha256:actuator",
        },
    }
    payload["telemetry"]["current_zone"] = "vault_a"
    payload["telemetry"]["current_coordinate_ref"] = "gazebo://warehouse/shelf/A3"

    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200
    mapped_request = captured["request"]
    gateway_params = mapped_request.action_intent.action.parameters["gateway"]
    assert gateway_params["scope_id"] == "scope:rct-2026-0001"
    assert gateway_params["expected_coordinate_ref"] == "gazebo://warehouse/shelf/A3"
    assert gateway_params["hardware_fingerprint_id"] == "fp:jetson-orin-01"
    assert gateway_params["reason_trace_ref"] == "reason:trace-1"
    body = response.json()
    assert body["authority_scope_verdict"]["status"] == "matched"
    assert body["fingerprint_verdict"]["status"] == "matched"


def test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch(monkeypatch):
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

    payload = _base_payload()
    payload["authority_scope"] = {
        "scope_id": "scope:rct-2026-0001",
        "asset_ref": "asset:lot-8841",
        "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
    }
    payload["telemetry"]["current_coordinate_ref"] = "gazebo://warehouse/shelf/B9"

    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "coordinate_scope_mismatch"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert "authority_scope_mismatch" in body["trust_gaps"]


def test_agent_actions_evaluate_requires_identity_proof():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    payload = _base_payload()
    payload["principal"].pop("session_token")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 422


def test_agent_actions_evaluate_requires_hardware_scope_and_owner_binding():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    payload = _base_payload()
    payload["principal"].pop("hardware_fingerprint")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 422

    payload = _base_payload()
    payload.pop("authority_scope")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 422

    payload = _base_payload()
    payload["principal"].pop("owner_id")
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 422


def test_agent_actions_evaluate_rejects_scope_asset_mismatch_at_schema_layer():
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    payload = _base_payload()
    payload["authority_scope"]["asset_ref"] = "asset:other"
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
    conflicting_payload["authority_scope"]["asset_ref"] = "asset:lot-9000"
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


def test_agent_actions_evaluate_no_execute_query_strips_execution_token(monkeypatch):
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

    response = client.post("/api/v1/agent-actions/evaluate?no_execute=true", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "allow"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert "PolicyReceipt" in body["minted_artifacts"]


def test_agent_actions_evaluate_no_execute_option_strips_execution_token(monkeypatch):
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

    payload = _base_payload()
    payload["options"]["no_execute"] = True
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "allow"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]


def test_agent_actions_evaluate_includes_owner_context_refs_in_governed_receipt(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    captured = {}

    def _fake_evaluate(request, **kwargs):
        captured["relevant_twin_snapshot"] = kwargs.get("relevant_twin_snapshot")
        return _allow_hot_path_response()

    async def _fake_owner_snapshot(*args, **kwargs):
        return {
            "identity": {"did": "did:seedcore:owner:acme-001"},
            "provenance": {
                "creator_profile_ref": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "version": "v2",
                    "updated_at": "2026-03-31T10:00:00Z",
                    "updated_by": "identity_router",
                    "source_namespace": "identity",
                    "source_predicate": "creator_profile",
                    "signer_did": "did:seedcore:owner:acme-001",
                    "signer_key_ref": "owner-k1",
                },
                "trust_preferences_ref": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "trust_version": "v3",
                    "updated_at": "2026-03-31T10:00:01Z",
                    "updated_by": "identity_router",
                    "source_namespace": "identity",
                    "source_predicate": "trust_preferences",
                    "signer_did": "did:seedcore:owner:acme-001",
                    "signer_key_ref": "owner-k1",
                },
            },
        }

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_owner_twin_snapshot_for_payload",
        _fake_owner_snapshot,
    )

    payload = _base_payload()
    payload["principal"]["owner_id"] = "did:seedcore:owner:acme-001"
    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    owner_context = body["governed_receipt"]["owner_context"]
    assert owner_context["owner_id"] == "did:seedcore:owner:acme-001"
    assert owner_context["creator_profile_ref"]["version"] == "v2"
    assert owner_context["trust_preferences_ref"]["trust_version"] == "v3"
    assert owner_context["creator_profile_ref"]["source_namespace"] == "identity"
    assert owner_context["creator_profile_ref"]["signer_key_ref"] == "owner-k1"
    assert owner_context["trust_preferences_ref"]["source_predicate"] == "trust_preferences"
    assert owner_context["trust_preferences_ref"]["signer_did"] == "did:seedcore:owner:acme-001"
    assert isinstance(captured.get("relevant_twin_snapshot"), dict)
    assert "owner" in captured["relevant_twin_snapshot"]


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


def test_build_closure_evidence_bundle_includes_forensic_block():
    request_record = agent_actions_router._AgentActionStoredRecord(
        request_id="req-transfer-2026-0001",
        idempotency_key="idem-transfer-2026-0001",
        request_hash="hash-1",
        recorded_at=datetime.now(timezone.utc),
        response=agent_actions_router.AgentActionEvaluateResponse(
            request_id="req-transfer-2026-0001",
            decided_at=datetime.now(timezone.utc),
            latency_ms=10,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="ok",
                reason="ok",
                policy_snapshot_ref="snapshot:1",
            ),
            execution_token=ExecutionToken(
                token_id="token-1",
                intent_id="req-transfer-2026-0001",
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:00:06Z",
                contract_version="rules@8.0.0",
                constraints={"endpoint_id": "node-x"},
            ),
        ),
        request_payload={},
    )
    closure_payload = AgentActionClosureRequest.model_validate(
        {
            "contract_version": "seedcore.agent_action_gateway.v1",
            "request_id": "req-transfer-2026-0001",
            "closure_id": "closure-transfer-2026-0001",
            "idempotency_key": "idem-closure-2026-0001",
            "closed_at": "2026-03-31T10:02:00Z",
            "outcome": "completed",
            "evidence_bundle_id": "evidence-bundle-001",
            "transition_receipt_ids": ["transition-receipt-001"],
            "forensic_block": {
                "forensic_block_id": "fb-2026-0001",
                "fingerprint_components": {
                    "economic_hash": "sha256:shopify-order",
                    "physical_presence_hash": "sha256:gazebo-point-cloud",
                    "reasoning_hash": "sha256:reason-trace",
                    "actuator_hash": "sha256:unitree-b2-torque",
                },
            },
        }
    )
    bundle = agent_actions_router._build_closure_evidence_bundle(
        closure_payload=closure_payload,
        request_record=request_record,
    )
    assert bundle["forensic_block"]["@type"] == "ForensicBlock"
    assert bundle["forensic_block"]["forensic_block_id"] == "fb-2026-0001"
