from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.agent_actions_router as agent_actions_router
import seedcore.api.routers.replay_router as replay_router_module
from seedcore.adapters.rct_agent_action_gateway_reference_adapter import (
    build_rct_agent_action_evaluate_request_v1,
    build_rct_gateway_correlation_from_evaluate_response,
)
from seedcore.models.action_intent import ExecutionToken
from seedcore.models.agent_action_gateway import AgentActionEvaluateRequest
from seedcore.models.pdp_hot_path import HotPathDecisionView, HotPathEvaluateResponse

from test_agent_actions_router import _bundle_manager, _empty_authoritative_approval, _organism_preflight_ok
from test_replay_router import _make_client as _make_replay_client
from test_replay_service import _apply_transition_metadata, _build_audit_record


def _base_principal() -> dict:
    return {
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
    }


def _base_asset_base() -> dict:
    return {
        "asset_id": "asset:lot-8841",
        "lot_id": "lot-8841",
        "from_custodian_ref": "principal:facility_mgr_001",
        "to_custodian_ref": "principal:outbound_mgr_002",
        "from_zone": "vault_a",
        "to_zone": "handoff_bay_3",
        "provenance_hash": "sha256:asset-provenance",
    }


def _base_authority_scope_base() -> dict:
    return {
        "scope_id": "scope:rct-2026-0001",
        "asset_ref": "asset:lot-8841",
        "expected_from_zone": "vault_a",
        "expected_to_zone": "handoff_bay_3",
        "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
    }


def _base_telemetry() -> dict:
    return {
        "observed_at": "2026-03-31T09:59:58Z",
        "freshness_seconds": 2,
        "max_allowed_age_seconds": 300,
        "current_zone": "vault_a",
        "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
        "evidence_refs": ["ev:cam-1", "ev:seal-sensor-7"],
    }


def _base_security_contract() -> dict:
    return {"hash": "sha256:contract-hash", "version": "rules@8.0.0"}


def _base_approval() -> dict:
    return {"approval_envelope_id": "approval-transfer-001", "expected_envelope_version": "23"}


def _base_shopify_transaction() -> dict:
    return {
        "product_ref": "shopify:gid://shopify/Product/1234567890",
        "quote_ref": "shopify:quote:tea-set-2026-04-01-0001",
        "declared_value_usd": 1500,
        "economic_hash": "sha256:shopify-order",
    }


def _base_options() -> dict:
    return {"debug": False}


def test_shopify_sandbox_adapter_maps_product_quote_value_and_economic_hash() -> None:
    req = build_rct_agent_action_evaluate_request_v1(
        request_id="req-transfer-2026-0001",
        idempotency_key="idem-transfer-2026-0001",
        requested_at="2026-03-31T10:00:00Z",
        policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
        principal=_base_principal(),
        workflow_valid_until="2026-03-31T10:01:00Z",
        asset_base=_base_asset_base(),
        approval_envelope_id=_base_approval()["approval_envelope_id"],
        approval_expected_envelope_version=_base_approval()["expected_envelope_version"],
        authority_scope_base=_base_authority_scope_base(),
        telemetry=_base_telemetry(),
        security_contract=_base_security_contract(),
        shopify_sandbox_transaction=_base_shopify_transaction(),
        options=_base_options(),
    )

    assert req["asset"]["product_ref"] == _base_shopify_transaction()["product_ref"]
    assert req["asset"]["quote_ref"] == _base_shopify_transaction()["quote_ref"]
    assert req["asset"]["declared_value_usd"] == 1500.0
    assert (
        req["forensic_context"]["fingerprint_components"]["economic_hash"]
        == _base_shopify_transaction()["economic_hash"]
    )


def test_agent_action_adapter_rejects_authority_scope_product_ref_mismatch() -> None:
    authority = _base_authority_scope_base()
    # Conflicting with the commerce adapter's product_ref.
    authority["product_ref"] = "shopify:gid://shopify/Product/DIFFERENT"

    with pytest.raises(ValueError, match="authority_scope\\.product_ref must equal asset\\.product_ref"):
        build_rct_agent_action_evaluate_request_v1(
            request_id="req-transfer-2026-0001",
            idempotency_key="idem-transfer-2026-0001",
            requested_at="2026-03-31T10:00:00Z",
            policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
            principal=_base_principal(),
            workflow_valid_until="2026-03-31T10:01:00Z",
            asset_base=_base_asset_base(),
            approval_envelope_id=_base_approval()["approval_envelope_id"],
            approval_expected_envelope_version=_base_approval()["expected_envelope_version"],
            authority_scope_base=authority,
            telemetry=_base_telemetry(),
            security_contract=_base_security_contract(),
            shopify_sandbox_transaction=_base_shopify_transaction(),
            options=_base_options(),
        )


def test_agent_action_adapter_rejects_missing_principal_identity_proof() -> None:
    principal = _base_principal()
    principal.pop("session_token", None)

    with pytest.raises(ValueError, match="principal\\.session_token or principal\\.actor_token is required"):
        build_rct_agent_action_evaluate_request_v1(
            request_id="req-transfer-2026-0001",
            idempotency_key="idem-transfer-2026-0001",
            requested_at="2026-03-31T10:00:00Z",
            policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
            principal=principal,
            workflow_valid_until="2026-03-31T10:01:00Z",
            asset_base=_base_asset_base(),
            approval_envelope_id=_base_approval()["approval_envelope_id"],
            approval_expected_envelope_version=_base_approval()["expected_envelope_version"],
            authority_scope_base=_base_authority_scope_base(),
            telemetry=_base_telemetry(),
            security_contract=_base_security_contract(),
            shopify_sandbox_transaction=_base_shopify_transaction(),
            options=_base_options(),
        )


def test_agent_action_adapter_rejects_commerce_product_ref_missing() -> None:
    shopify = _base_shopify_transaction()
    shopify["product_ref"] = None

    with pytest.raises(ValueError, match="commerce\\.product_ref must be non-empty"):
        build_rct_agent_action_evaluate_request_v1(
            request_id="req-transfer-2026-0001",
            idempotency_key="idem-transfer-2026-0001",
            requested_at="2026-03-31T10:00:00Z",
            policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
            principal=_base_principal(),
            workflow_valid_until="2026-03-31T10:01:00Z",
            asset_base=_base_asset_base(),
            approval_envelope_id=_base_approval()["approval_envelope_id"],
            approval_expected_envelope_version=_base_approval()["expected_envelope_version"],
            authority_scope_base=_base_authority_scope_base(),
            telemetry=_base_telemetry(),
            security_contract=_base_security_contract(),
            shopify_sandbox_transaction=shopify,
            options=_base_options(),
        )


def test_gateway_request_to_replay_correlation_by_intent_and_audit_id(monkeypatch: pytest.MonkeyPatch) -> None:
    request_id = "req-transfer-2026-corr-0001"
    decision_hash = f"receipt-{request_id}"
    audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, request_id))
    forensic_block_id = f"fb-{request_id}"

    # ---- Gateway evaluate through the real router (with mocked PDP hot-path) ----
    app = FastAPI()
    app.include_router(agent_actions_router.router, prefix="/api/v1", tags=["Agent Actions"])
    client = TestClient(app)

    async def _fake_resolve_authoritative_transfer_approval(*args, **kwargs):
        return {}

    def _fake_hot_path_evaluate(hot_path_request, **kwargs):
        return HotPathEvaluateResponse(
            request_id=hot_path_request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=7,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=hot_path_request.policy_snapshot_ref,
            ),
            execution_token=ExecutionToken(
                token_id="token-transfer-001",
                intent_id=hot_path_request.request_id,
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:00:06Z",
                contract_version="rules@8.0.0",
                constraints={"endpoint_id": "robot_sim://corr-01"},
            ),
            request_schema_bundle=hot_path_request.request_schema_bundle,
            taxonomy_bundle=hot_path_request.taxonomy_bundle,
            governed_receipt={
                "audit_id": audit_id,
                "policy_receipt_id": "receipt-policy-corr",
                "decision_hash": decision_hash,
            "forensic_block_id": forensic_block_id,
            },
        )

    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "resolve_authoritative_transfer_approval", _fake_resolve_authoritative_transfer_approval)
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_hot_path_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(agent_actions_router, "get_global_pkg_manager", lambda: _bundle_manager(snapshot_version="snapshot:pkg-prod-2026-03-31"))

    gateway_request = build_rct_agent_action_evaluate_request_v1(
        request_id=request_id,
        idempotency_key="idem-transfer-corr-0001",
        requested_at="2026-03-31T10:00:00Z",
        policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
        principal=_base_principal(),
        workflow_valid_until="2026-03-31T10:01:00Z",
        asset_base=_base_asset_base(),
        approval_envelope_id=_base_approval()["approval_envelope_id"],
        approval_expected_envelope_version=_base_approval()["expected_envelope_version"],
        authority_scope_base=_base_authority_scope_base(),
        telemetry=_base_telemetry(),
        security_contract=_base_security_contract(),
        shopify_sandbox_transaction=_base_shopify_transaction(),
        options=_base_options(),
    )

    resp = client.post("/api/v1/agent-actions/evaluate", json=gateway_request)
    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == request_id
    assert body["decision"]["disposition"] == "allow"
    assert body["governed_receipt"]["audit_id"] == audit_id
    assert body["governed_receipt"]["decision_hash"] == decision_hash
    assert body["forensic_linkage"]["forensic_block_id"] == forensic_block_id

    correlation = build_rct_gateway_correlation_from_evaluate_response(
        request_id=request_id,
        gateway_evaluate_response=body,
    )
    assert correlation["intent_id"] == request_id
    assert correlation["audit_id"] == audit_id
    assert correlation["audit_id_source"] == "governed_receipt"
    assert correlation["replay_state"]["status"] == "ready_for_lookup"
    assert correlation["replay_lookup"]["preferred_key"] == "audit_id"

    # ---- Build a replay record that matches the correlation keys ----
    record = _build_audit_record(task_id="task-router-corr", intent_id=request_id, asset_id="asset-1")
    record = _apply_transition_metadata(record, disposition="allow", reason="restricted_custody_transfer")
    record["id"] = audit_id

    replay_client = _make_replay_client(record)

    replay_by_intent = replay_client.get(f"/replay?intent_id={request_id}&projection=public")
    assert replay_by_intent.status_code == 200
    replay_by_intent_body = replay_by_intent.json()
    assert replay_by_intent_body["lookup_key"] == "intent_id"
    assert replay_by_intent_body["lookup_value"] == request_id
    assert replay_by_intent_body["view"]["policy_summary"]["governed_receipt_hash"] == decision_hash

    replay_by_audit = replay_client.get(f"/replay?audit_id={audit_id}&projection=public")
    assert replay_by_audit.status_code == 200
    replay_by_audit_body = replay_by_audit.json()
    assert replay_by_audit_body["lookup_key"] == "audit_id"
    assert replay_by_audit_body["lookup_value"] == audit_id
    assert replay_by_audit_body["view"]["policy_summary"]["governed_receipt_hash"] == decision_hash


def test_gateway_correlation_uses_uuid_safe_fallback_and_pending_semantics_when_audit_missing() -> None:
    request_id = "req-transfer-2026-fallback-0001"
    response_without_audit = {
        "decision": {"disposition": "quarantine"},
        "governed_receipt": {},
        "forensic_linkage": {},
    }

    correlation = build_rct_gateway_correlation_from_evaluate_response(
        request_id=request_id,
        gateway_evaluate_response=response_without_audit,
    )

    expected_fallback_audit_id = str(uuid.uuid5(uuid.NAMESPACE_URL, request_id))
    assert correlation["intent_id"] == request_id
    assert correlation["audit_id"] == expected_fallback_audit_id
    assert correlation["audit_id_source"] == "deterministic_fallback"
    assert correlation["replay_state"]["status"] == "pending_replay_record"
    assert correlation["replay_state"]["reason"] == "governed_receipt_audit_id_missing"
    assert correlation["replay_lookup"]["preferred_key"] == "intent_id"
