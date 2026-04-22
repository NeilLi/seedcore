from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.agent_actions_router as agent_actions_router
from seedcore.models.action_intent import ExecutionToken
import pytest
from pydantic import ValidationError

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
            execution_preconditions={
                "resource_state_hash": "sha256:resource-state-001",
                "approval_transition_head": "sha256:approval-transition-001",
                "context_token": "sha256:context-token-001",
                "payload_hash": "sha256:payload-transfer-001",
                "endpoint_id": "hal://robot-sim/1",
            },
        ),
        request_schema_bundle={
            "artifact_type": "request_schema_bundle",
            "snapshot_version": "rules@8.0.0",
            "request_shape": {"required_task_fact_keys": ["tags", "signals", "context"]},
        },
        taxonomy_bundle={
            "artifact_type": "taxonomy_bundle",
            "snapshot_version": "rules@8.0.0",
            "trust_gap_codes": [{"code": "stale_telemetry"}],
        },
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


async def _closure_settlement_disabled(*args, **kwargs):
    return "pending", {"enabled": False}


async def _result_verifier_gate_open(*args, **kwargs):
    return {"blocked": False, "checked_refs": 0}


class _ResultVerifierGateOpenService:
    async def evaluate_result_verifier_gate(self, *, twin_refs):
        return {"blocked": False, "checked_refs": len(list(twin_refs or []))}


class _ResultVerifierGateBlockedService:
    async def evaluate_result_verifier_gate(self, *, twin_refs):
        return {
            "blocked": True,
            "reason_code": "result_verifier_lockout",
            "reason": "Authoritative RESULT_VERIFIER lockout is active.",
            "twin_type": "asset",
            "twin_id": "asset:lot-8841",
            "checked_refs": len(list(twin_refs or [])),
        }


class _ResultVerifierGateReplayMismatchService:
    async def evaluate_result_verifier_gate(self, *, twin_refs):
        return {
            "blocked": True,
            "reason_code": "result_verifier_replay_mismatch",
            "reason": "Authoritative RESULT_VERIFIER replay mismatch is active.",
            "twin_type": "asset",
            "twin_id": "asset:lot-8841",
            "checked_refs": len(list(twin_refs or [])),
        }


class _ResultVerifierGateRaisesService:
    async def evaluate_result_verifier_gate(self, *, twin_refs):
        raise RuntimeError("simulated gate failure")


class _ResultVerifierGateBadReturnService:
    async def evaluate_result_verifier_gate(self, *, twin_refs):
        return None


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
    assert body["execution_context"]["context_token"] == "sha256:context-token-001"
    assert "ExecutionToken" in body["minted_artifacts"]
    assert "PolicyReceipt" in body["minted_artifacts"]


def test_agent_actions_execute_routes_governed_task(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    captured = {}

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )

    def _fake_evaluate(request, **kwargs):
        captured["hot_path_request"] = request
        plan_dag_hash = request.action_intent.action.parameters["plan_dag_hash"]
        endpoint_id = request.action_intent.action.parameters["endpoint_id"]
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=35,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            execution_token=ExecutionToken(
                token_id="token-transfer-execute-001",
                intent_id=request.request_id,
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:05:01Z",
                contract_version="rules@8.0.0",
                execution_preconditions={
                    "resource_state_hash": "sha256:resource-state-001",
                    "approval_transition_head": "sha256:approval-transition-001",
                    "context_token": "sha256:context-token-001",
                    "plan_dag_hash": plan_dag_hash,
                    "endpoint_id": endpoint_id,
                },
            ),
            governed_receipt={
                "audit_id": "audit-execute-001",
                "policy_receipt_id": "receipt-policy-execute-001",
            },
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(
        agent_actions_router,
        "_evaluate_result_verifier_gate_for_twin_refs",
        _result_verifier_gate_open,
    )

    class _FakeOrganismClient:
        def __init__(self, timeout=None):
            captured["organism_timeout"] = timeout

        async def route_and_execute(self, task, current_epoch=None):
            captured["execution_task"] = task
            return {
                "success": True,
                "payload": {
                    "results": [
                        {
                            "tool": "reachy.motion",
                            "output": {"status": "accepted", "execution_token_id": "token-transfer-execute-001"},
                        }
                    ]
                },
            }

        async def close(self):
            return None

    monkeypatch.setattr(agent_actions_router, "OrganismServiceClient", _FakeOrganismClient)

    payload = _base_payload()
    payload["execution"] = {
        "planner_type": "physical_digital_handover",
        "default_directive": {
            "tool_name": "reachy.motion",
            "args": {
                "behavior_name": "move_forward",
                "behavior_params": {
                    "distance": 1.25,
                    "asset_id": "asset:lot-8841",
                    "to_zone": "handoff_bay_3",
                },
            },
        },
    }

    response = client.post("/api/v1/agent-actions/execute", json=payload)
    assert response.status_code == 200
    body = response.json()

    expected_plan_hash = body["execution_plan"]["plan_dag_hash"]
    assert captured["hot_path_request"].action_intent.action.parameters["payload_hash"] is None
    assert captured["hot_path_request"].action_intent.action.parameters["plan_dag_hash"] == expected_plan_hash
    assert body["evaluation"]["decision"]["disposition"] == "allow"
    assert body["execution_task"]["params"]["tool_calls"][0]["name"] == "reachy.motion"
    assert body["execution_task"]["params"]["tool_calls"][0]["args"]["behavior_name"] == "move_forward"
    assert body["execution_task"]["params"]["tool_calls"][1]["name"] == "forensic.seal"
    assert body["execution_task"]["params"]["governance"]["execution_context"]["plan_dag_hash"] == expected_plan_hash
    assert body["execution_result"]["success"] is True


def test_agent_actions_execute_is_idempotent(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    call_count = {"route_and_execute": 0}

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )

    def _fake_evaluate(request, **kwargs):
        plan_dag_hash = request.action_intent.action.parameters["plan_dag_hash"]
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=35,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            execution_token=ExecutionToken(
                token_id="token-transfer-execute-001",
                intent_id=request.request_id,
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:05:01Z",
                contract_version="rules@8.0.0",
                execution_preconditions={
                    "resource_state_hash": "sha256:resource-state-001",
                    "approval_transition_head": "sha256:approval-transition-001",
                    "context_token": "sha256:context-token-001",
                    "plan_dag_hash": plan_dag_hash,
                    "endpoint_id": "node:jetson-orin-01",
                },
            ),
            governed_receipt={
                "audit_id": "audit-execute-001",
                "policy_receipt_id": "receipt-policy-execute-001",
            },
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(
        agent_actions_router,
        "_evaluate_result_verifier_gate_for_twin_refs",
        _result_verifier_gate_open,
    )

    class _FakeOrganismClient:
        def __init__(self, timeout=None):
            pass

        async def route_and_execute(self, task, current_epoch=None):
            call_count["route_and_execute"] += 1
            return {"success": True, "payload": {"results": []}}

        async def close(self):
            return None

    monkeypatch.setattr(agent_actions_router, "OrganismServiceClient", _FakeOrganismClient)

    payload = _base_payload()
    payload["execution"] = {
        "planner_type": "physical_digital_handover",
        "default_directive": {
            "tool_name": "reachy.motion",
            "args": {
                "behavior_name": "move_forward",
                "behavior_params": {"distance": 1.0},
            },
        },
    }

    first = client.post("/api/v1/agent-actions/execute", json=payload)
    second = client.post("/api/v1/agent-actions/execute", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count["route_and_execute"] == 1
    assert first.json()["execution_result"] == second.json()["execution_result"]


def test_agent_actions_execute_delegated_authority_returns_subtoken(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    call_count = {"route_and_execute": 0}

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )

    def _fake_evaluate(request, **kwargs):
        endpoint_id = request.action_intent.action.parameters["endpoint_id"]
        plan_dag_hash = request.action_intent.action.parameters["plan_dag_hash"]
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=35,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            execution_token=ExecutionToken(
                token_id="token-transfer-delegate-001",
                intent_id=request.request_id,
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:05:01Z",
                contract_version="rules@8.0.0",
                execution_preconditions={
                    "resource_state_hash": "sha256:resource-state-001",
                    "approval_transition_head": "sha256:approval-transition-001",
                    "context_token": "sha256:context-token-001",
                    "plan_dag_hash": plan_dag_hash,
                    "endpoint_id": endpoint_id,
                },
            ),
            governed_receipt={
                "audit_id": "audit-execute-delegate-001",
                "policy_receipt_id": "receipt-policy-execute-delegate-001",
            },
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(
        agent_actions_router,
        "_evaluate_result_verifier_gate_for_twin_refs",
        _result_verifier_gate_open,
    )

    class _FakeOrganismClient:
        def __init__(self, timeout=None):
            pass

        async def route_and_execute(self, task, current_epoch=None):
            call_count["route_and_execute"] += 1
            return {"success": True}

        async def close(self):
            return None

    monkeypatch.setattr(agent_actions_router, "OrganismServiceClient", _FakeOrganismClient)

    payload = _base_payload()
    payload["execution"] = {
        "planner_type": "delegated_authority",
        "planner_inputs": {
            "delegate_agent_id": "agent:openclaw-01",
            "delegate_endpoint_id": "hal://openclaw/01",
            "subtoken_ttl_seconds": 45,
        },
    }

    response = client.post("/api/v1/agent-actions/execute", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert call_count["route_and_execute"] == 0
    assert body["execution_plan"]["planner_type"] == "delegated_authority"
    assert body["execution_result"]["status"] == "delegated_ready"
    assert body["execution_result"]["delegate_agent_id"] == "agent:openclaw-01"
    assert body["execution_result"]["sub_execution_token"]["constraints"]["principal_agent_id"] == "agent:openclaw-01"
    assert body["execution_task"]["params"]["tool_calls"] == []


def test_agent_actions_execute_conditional_escrow_returns_waiting_state(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()
    call_count = {"route_and_execute": 0}

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )

    def _fake_evaluate(request, **kwargs):
        plan_dag_hash = request.action_intent.action.parameters["plan_dag_hash"]
        return HotPathEvaluateResponse(
            request_id=request.request_id,
            decided_at=datetime.now(timezone.utc),
            latency_ms=35,
            decision=HotPathDecisionView(
                allowed=True,
                disposition="allow",
                reason_code="restricted_custody_transfer_allowed",
                reason="all mandatory checks passed",
                policy_snapshot_ref=request.policy_snapshot_ref,
            ),
            execution_token=ExecutionToken(
                token_id="token-transfer-escrow-001",
                intent_id=request.request_id,
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:05:01Z",
                contract_version="rules@8.0.0",
                execution_preconditions={
                    "resource_state_hash": "sha256:resource-state-001",
                    "approval_transition_head": "sha256:approval-transition-001",
                    "context_token": "sha256:context-token-001",
                    "plan_dag_hash": plan_dag_hash,
                    "endpoint_id": "node:jetson-orin-01",
                },
            ),
            governed_receipt={
                "audit_id": "audit-execute-escrow-001",
                "policy_receipt_id": "receipt-policy-execute-escrow-001",
            },
        )

    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _fake_evaluate)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)
    monkeypatch.setattr(
        agent_actions_router,
        "_evaluate_result_verifier_gate_for_twin_refs",
        _result_verifier_gate_open,
    )

    class _FakeOrganismClient:
        def __init__(self, timeout=None):
            pass

        async def route_and_execute(self, task, current_epoch=None):
            call_count["route_and_execute"] += 1
            return {"success": True}

        async def close(self):
            return None

    monkeypatch.setattr(agent_actions_router, "OrganismServiceClient", _FakeOrganismClient)

    payload = _base_payload()
    payload["execution"] = {
        "planner_type": "conditional_escrow",
        "planner_inputs": {
            "governed_vault_ref": "vault:lot-8841",
            "condition_ref": "scan:buyer-001",
            "dead_mans_switch_seconds": 180,
        },
    }

    response = client.post("/api/v1/agent-actions/execute", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert call_count["route_and_execute"] == 0
    assert body["execution_plan"]["planner_type"] == "conditional_escrow"
    assert body["execution_result"]["status"] == "awaiting_condition"
    assert body["execution_result"]["dead_mans_switch_seconds"] == 180
    assert body["execution_task"]["params"]["tool_calls"] == []


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
    expected_request_hash = agent_actions_router._canonical_gateway_payload_hash(
        agent_actions_router.AgentActionEvaluateRequest.model_validate(payload),
        requested_no_execute=False,
    )
    assert mapped_request.request_id == payload["request_id"]
    assert mapped_request.policy_snapshot_ref == "rules@8.0.0"
    assert mapped_request.asset_context.asset_ref == "asset:lot-8841"
    assert mapped_request.asset_context.current_custodian_ref == "principal:facility_mgr_001"
    assert (
        mapped_request.action_intent.action.parameters["approval_context"]["approval_envelope_id"]
        == "approval-transfer-001"
    )
    assert mapped_request.action_intent.action.parameters["endpoint_id"] == "node:jetson-orin-01"
    assert mapped_request.action_intent.action.parameters["payload_hash"] is None
    assert str(mapped_request.action_intent.action.parameters["plan_dag_hash"]).startswith("sha256:")
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
    assert mapped_request.action_intent.action.parameters["endpoint_id"] == "node:jetson-orin-01"
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


@pytest.mark.asyncio
async def test_evaluate_result_verifier_gate_for_twin_refs_empty_is_not_blocked():
    verdict = await agent_actions_router._evaluate_result_verifier_gate_for_twin_refs(twin_refs=[])
    assert verdict.get("blocked") is False
    assert verdict.get("checked_refs") in (0, None)


def test_agent_actions_evaluate_denies_when_digital_twin_service_unavailable(monkeypatch):
    """Hot-path allow is flipped to deny when the twin service cannot run the verifier gate (fail-closed)."""
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
    monkeypatch.setattr(agent_actions_router, "_resolve_digital_twin_service", lambda: None)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_gate_service_unavailable"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert "result_verifier_gate_service_unavailable" in body["trust_gaps"]


def test_agent_actions_evaluate_denies_when_result_verifier_gate_eval_raises(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateRaisesService(),
    )

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_gate_eval_failed"
    assert body["execution_token"] is None


def test_agent_actions_evaluate_denies_when_result_verifier_gate_method_missing(monkeypatch):
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
    monkeypatch.setattr(agent_actions_router, "_resolve_digital_twin_service", lambda: SimpleNamespace())

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_gate_unavailable"
    assert body["execution_token"] is None


def test_agent_actions_evaluate_denies_when_result_verifier_gate_returns_invalid_verdict(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateBadReturnService(),
    )

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_gate_invalid_verdict"
    assert body["execution_token"] is None


def test_agent_actions_evaluate_denies_when_result_verifier_gate_blocks(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateBlockedService(),
    )

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_lockout"
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]
    assert "result_verifier_lockout" in body["trust_gaps"]


def test_agent_actions_evaluate_denies_when_result_verifier_replay_mismatch_blocks(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateReplayMismatchService(),
    )

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "deny"
    assert body["decision"]["reason_code"] == "result_verifier_replay_mismatch"
    assert body["execution_token"] is None
    assert "result_verifier_replay_mismatch" in body["trust_gaps"]


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
    assert body["execution_context"] is None
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
    assert body["execution_context"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]


def test_agent_actions_evaluate_no_execute_skips_organism_preflight(monkeypatch):
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

    response = client.post("/api/v1/agent-actions/evaluate?no_execute=true", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["decision"]["disposition"] == "allow"
    assert str(body["decision"]["reason_code"]).startswith("restricted_custody_transfer")
    assert "organism_not_ready" not in body["trust_gaps"]
    assert body["execution_token"] is None
    assert "ExecutionToken" not in body["minted_artifacts"]


def test_agent_actions_evaluate_hydrates_governed_receipt_fields(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    def _allow_without_receipt(*args, **kwargs):
        return _allow_hot_path_response().model_copy(update={"governed_receipt": {}})

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(
        agent_actions_router,
        "evaluate_pdp_hot_path",
        _allow_without_receipt,
    )
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    response = client.post("/api/v1/agent-actions/evaluate?no_execute=true", json=_base_payload())
    assert response.status_code == 200
    body = response.json()
    governed_receipt = body["governed_receipt"]

    assert isinstance(governed_receipt.get("decision_hash"), str)
    assert governed_receipt["decision_hash"].startswith("sha256:")
    assert governed_receipt.get("policy_receipt_id") == "policy-receipt:req-transfer-2026-0001"
    assert isinstance(governed_receipt.get("audit_id"), str)
    assert len(governed_receipt["audit_id"]) > 0


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
    # SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF now defaults to `true`
    # (see agent_action_gateway_contract.md §Closure Surface), so with the
    # twin service mocked the closure reaches a terminal status rather than
    # the legacy `feature_flag_disabled` short-circuit.  Accept any of the
    # terminal statuses so this smoke test does not couple to the mock
    # twin service's internal behavior.
    assert close_body["settlement_status"] in {
        "applied",
        "pending",
        "pending_reconcile",
    }
    assert close_body["replay_status"] in {"ready", "pending", "pending_reconcile"}
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


def test_agent_actions_closure_rejects_when_result_verifier_gate_blocks(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateOpenService(),
    )

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateBlockedService(),
    )
    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.status_code == 409
    detail = close_response.json()["detail"]
    assert detail["error_code"] == "closure_blocked_by_result_verifier"
    assert detail["gate_reason_code"] == "result_verifier_lockout"


def test_agent_actions_closure_rejects_when_result_verifier_replay_mismatch_blocks(monkeypatch):
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateOpenService(),
    )

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateReplayMismatchService(),
    )
    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.status_code == 409
    detail = close_response.json()["detail"]
    assert detail["error_code"] == "closure_blocked_by_result_verifier"
    assert detail["gate_reason_code"] == "result_verifier_replay_mismatch"


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


def test_agent_actions_closure_detects_outcome_contradiction(monkeypatch):
    """A closure that reports `quarantined` against an `allow` evaluate must
    flip to `settlement_status=contradicted` without touching the twin
    service, and its `next_actions` must include the documented
    `quarantine_asset` + `investigate_scope_mismatch` remediation steps.
    """

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
    closure_payload["outcome"] = "quarantined"

    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=closure_payload,
    )
    assert close_response.status_code == 200
    body = close_response.json()
    assert body["settlement_status"] == "contradicted"
    assert body["replay_status"] == "contradicted"
    assert body["settlement_result"]["error_code"] == "closure_contradicts_authority_scope"
    reason_codes = {
        entry.get("reason_code")
        for entry in body["settlement_result"]["contradictions"]
    }
    assert "outcome_contradicts_allow_decision" in reason_codes
    assert "quarantine_asset" in body["next_actions"]
    assert "investigate_scope_mismatch" in body["next_actions"]


def test_agent_actions_closure_detects_summary_zone_contradiction(monkeypatch):
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
    closure_payload["summary"] = {
        "observed_to_zone": "zone_red_unauthorized",
    }

    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=closure_payload,
    )
    assert close_response.status_code == 200
    body = close_response.json()
    assert body["settlement_status"] == "contradicted"
    reason_codes = {
        entry.get("reason_code")
        for entry in body["settlement_result"]["contradictions"]
    }
    assert "summary_to_zone_mismatch" in reason_codes


class _SettlementRaisingTwinService:
    """Passes the RESULT_VERIFIER gate but raises from
    `settle_from_evidence_bundle` — simulates a transient backend fault.
    """

    async def evaluate_result_verifier_gate(self, *, twin_refs):
        return {"blocked": False, "checked_refs": len(list(twin_refs or []))}

    async def settle_from_evidence_bundle(self, **_kwargs):
        raise RuntimeError("transient settlement fault")


def test_agent_actions_closure_pending_reconcile_when_settlement_raises(monkeypatch):
    """When the twin service accepts the gate check but `settle_from_evidence_bundle`
    raises transiently, the closure path must not drop the closure or mark it
    rejected — it must return `pending_reconcile` and enqueue the closure for
    later reconciliation so no action becomes a zombie.
    """

    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "DISABLE_REDIS_STORE", True)
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _SettlementRaisingTwinService(),
    )

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200

    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.status_code == 200
    body = close_response.json()
    assert body["settlement_status"] == "pending_reconcile"
    assert body["replay_status"] == "pending_reconcile"
    assert body["settlement_result"]["error_code"] == "settlement_exception"
    assert body["settlement_result"]["requeued"] is True
    assert "await_settlement_reconcile" in body["next_actions"]

    with agent_actions_router._REQUEST_RECORDS_LOCK:
        queued_ids = [
            entry["closure_id"]
            for entry in agent_actions_router._PENDING_RECONCILE_QUEUE
        ]
    assert "closure-transfer-2026-0001" in queued_ids


@pytest.mark.asyncio
async def test_reconcile_pending_closures_applies_when_service_recovers(monkeypatch):
    """The reconciler must be able to promote a `pending_reconcile` closure
    to `applied` on a subsequent run once the twin service is back up.
    """

    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "DISABLE_REDIS_STORE", True)

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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _SettlementRaisingTwinService(),
    )

    eval_response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert eval_response.status_code == 200
    close_response = client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    assert close_response.json()["settlement_status"] == "pending_reconcile"

    async def _settlement_applied(*args, **kwargs):
        return "applied", {"updated": 1, "version_bumped": 1}

    monkeypatch.setattr(
        agent_actions_router,
        "_apply_closure_settlement_handoff",
        _settlement_applied,
    )

    summary = await agent_actions_router.reconcile_pending_closures(max_batch=10)
    assert summary["processed"] == 1
    assert summary["applied"] == 1

    record_response = client.get("/api/v1/agent-actions/closures/closure-transfer-2026-0001")
    assert record_response.status_code == 200
    stored = record_response.json()
    assert stored["response"]["settlement_status"] == "applied"
    assert stored["response"]["replay_status"] == "ready"


@pytest.mark.asyncio
async def test_reconcile_pending_closures_escalates_after_max_attempts(monkeypatch):
    """After `SETTLEMENT_RECONCILE_MAX_ATTEMPTS` retries, the reconciler must
    escalate a stuck closure to `rejected` with a specific error code so it
    cannot linger as a zombie.
    """

    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "DISABLE_REDIS_STORE", True)
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
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _SettlementRaisingTwinService(),
    )

    client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    client.post(
        "/api/v1/agent-actions/req-transfer-2026-0001/closures",
        json=_base_closure_payload(),
    )
    # Pre-age the queue entry so we exercise the escalation branch on the
    # very next reconcile call without needing to loop.
    with agent_actions_router._REQUEST_RECORDS_LOCK:
        agent_actions_router._PENDING_RECONCILE_QUEUE[0]["attempts"] = 99

    summary = await agent_actions_router.reconcile_pending_closures(max_batch=10)
    assert summary["escalated"] == 1

    record_response = client.get("/api/v1/agent-actions/closures/closure-transfer-2026-0001")
    assert record_response.status_code == 200
    stored = record_response.json()
    assert stored["response"]["settlement_status"] == "rejected"
    assert (
        stored["response"]["settlement_result"]["error_code"]
        == "settlement_reconcile_max_attempts_exceeded"
    )


@pytest.mark.asyncio
async def test_closure_settlement_handoff_rejects_when_result_verifier_gate_blocks(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "SETTLEMENT_HANDOFF_ENABLED", True)
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateBlockedService(),
    )

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
            ),
            governed_receipt={"asset_ref": "asset:lot-8841"},
        ),
        request_payload=_base_payload(),
    )
    closure_payload = AgentActionClosureRequest.model_validate(_base_closure_payload())

    settlement_status, settlement_result = await agent_actions_router._apply_closure_settlement_handoff(
        request_record=request_record,
        closure_payload=closure_payload,
    )
    assert settlement_status == "rejected"
    assert settlement_result["error_code"] == "settlement_blocked_by_result_verifier"
    assert settlement_result["gate_reason_code"] == "result_verifier_lockout"


@pytest.mark.asyncio
async def test_closure_settlement_handoff_rejects_when_result_verifier_replay_mismatch_blocks(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    monkeypatch.setattr(agent_actions_router, "SETTLEMENT_HANDOFF_ENABLED", True)
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_digital_twin_service",
        lambda: _ResultVerifierGateReplayMismatchService(),
    )

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
            ),
            governed_receipt={"asset_ref": "asset:lot-8841"},
        ),
        request_payload=_base_payload(),
    )
    closure_payload = AgentActionClosureRequest.model_validate(_base_closure_payload())

    settlement_status, settlement_result = await agent_actions_router._apply_closure_settlement_handoff(
        request_record=request_record,
        closure_payload=closure_payload,
    )
    assert settlement_status == "rejected"
    assert settlement_result["error_code"] == "settlement_blocked_by_result_verifier"
    assert settlement_result["gate_reason_code"] == "result_verifier_replay_mismatch"


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
            governed_receipt={
                "policy_receipt_id": "receipt-policy-1",
                "decision_hash": "sha256:governed-receipt-1",
            },
        ),
        request_payload={"approval": {"approval_envelope_id": "approval-transfer-001"}},
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
    assert bundle["causal_parent_refs"] == [
        {"relation": "approved_by", "artifact_type": "approval_envelope", "artifact_id": "approval-transfer-001"},
        {"relation": "authorized_by", "artifact_type": "policy_receipt", "artifact_id": "receipt-policy-1"},
        {"relation": "authorized_by", "artifact_type": "governed_receipt", "artifact_id": "sha256:governed-receipt-1"},
    ]


@pytest.mark.asyncio
async def test_persist_closure_governed_audit_record_sets_strict_state_transition_workflow_hint(monkeypatch):
    class _BeginCtx:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _SessionCtx:
        def __init__(self, session):
            self._session = session

        async def __aenter__(self):
            return self._session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    captured = {}

    class _FakeAuditDAO:
        async def append_record(self, session, **kwargs):
            captured.update(kwargs)
            return {"id": "audit-1"}

    session = SimpleNamespace(begin=lambda: _BeginCtx())
    monkeypatch.setattr(
        agent_actions_router,
        "get_async_pg_session_factory",
        lambda: (lambda: _SessionCtx(session)),
    )
    monkeypatch.setattr(
        agent_actions_router,
        "_resolve_existing_task_id_for_governed_audit",
        AsyncMock(return_value="123e4567-e89b-12d3-a456-426614174000"),
    )
    monkeypatch.setattr(agent_actions_router, "GovernedExecutionAuditDAO", lambda: _FakeAuditDAO())

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
                policy_snapshot_hash="sha256:policy-snapshot-1",
            ),
            execution_token=ExecutionToken(
                token_id="token-1",
                intent_id="req-transfer-2026-0001",
                issued_at="2026-03-31T10:00:01Z",
                valid_until="2026-03-31T10:00:06Z",
                contract_version="rules@8.0.0",
                constraints={"endpoint_id": "node-x"},
            ),
            governed_receipt={
                "asset_ref": "asset:lot-8841",
                "policy_receipt_id": "receipt-policy-1",
                "decision_hash": "sha256:governed-receipt-1",
            },
        ),
        request_payload=_base_payload(),
    )
    closure_payload = AgentActionClosureRequest.model_validate(_base_closure_payload())
    evidence_bundle = agent_actions_router._build_closure_evidence_bundle(
        closure_payload=closure_payload,
        request_record=request_record,
    )

    result = await agent_actions_router._persist_closure_governed_audit_record(
        request_record=request_record,
        closure_payload=closure_payload,
        evidence_bundle=evidence_bundle,
    )

    assert result == {"id": "audit-1"}
    assert captured["policy_case"]["workflow_hints"] == {
        "workflow_type": "restricted_custody_transfer",
        "strict_state_transition_fields": True,
    }


def _sample_signed_telemetry_ref(*, asset_ref: str = "asset:lot-8841", telemetry_id: str = "tel-1") -> dict:
    return {
        "contract_version": "seedcore.edge_telemetry_envelope.v0",
        "telemetry_id": telemetry_id,
        "asset_ref": asset_ref,
        "edge_node_ref": "edge:test",
        "observed_at": "2026-03-31T10:00:00Z",
        "sensor_kind": "motor_torque",
        "payload_sha256": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        "signer_key_ref": "kms:test-key",
    }


def test_agent_action_closure_request_rejects_duplicate_telemetry_id() -> None:
    payload = _base_closure_payload()
    payload["telemetry_refs"] = [
        _sample_signed_telemetry_ref(telemetry_id="dup"),
        _sample_signed_telemetry_ref(telemetry_id="dup"),
    ]
    with pytest.raises(ValidationError, match="duplicate telemetry_id"):
        AgentActionClosureRequest.model_validate(payload)


def test_agent_actions_closure_rejects_telemetry_asset_mismatch(monkeypatch) -> None:
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
    monkeypatch.setattr(agent_actions_router, "_apply_closure_settlement_handoff", _closure_settlement_disabled)

    assert client.post("/api/v1/agent-actions/evaluate", json=_base_payload()).status_code == 200

    bad = _base_closure_payload()
    bad["telemetry_refs"] = [_sample_signed_telemetry_ref(asset_ref="asset:other")]
    close_response = client.post("/api/v1/agent-actions/req-transfer-2026-0001/closures", json=bad)
    assert close_response.status_code == 422
    detail = close_response.json()["detail"]
    assert detail["error_code"] == "request_validation_failed"


def test_agent_actions_closure_accepts_telemetry_refs(monkeypatch) -> None:
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
    monkeypatch.setattr(agent_actions_router, "_apply_closure_settlement_handoff", _closure_settlement_disabled)

    assert client.post("/api/v1/agent-actions/evaluate", json=_base_payload()).status_code == 200

    ok = _base_closure_payload()
    ok["telemetry_refs"] = [_sample_signed_telemetry_ref()]
    close_response = client.post("/api/v1/agent-actions/req-transfer-2026-0001/closures", json=ok)
    assert close_response.status_code == 200
    body = close_response.json()
    assert len(body["telemetry_refs"]) == 1
    assert body["telemetry_refs"][0]["telemetry_id"] == "tel-1"
    assert body["settlement_result"]["telemetry_refs"][0]["telemetry_id"] == "tel-1"


def test_build_closure_evidence_bundle_includes_telemetry_refs() -> None:
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
            **_base_closure_payload(),
            "telemetry_refs": [_sample_signed_telemetry_ref()],
        }
    )
    bundle = agent_actions_router._build_closure_evidence_bundle(
        closure_payload=closure_payload,
        request_record=request_record,
    )
    assert len(bundle["telemetry_refs"]) == 1
    assert bundle["forensic_block"]["physical_evidence"]["telemetry_refs"][0]["telemetry_id"] == "tel-1"


# ---------------------------------------------------------------------------
# Gap-fill tests to cover the agent_action_gateway_contract.md v1 requirements
# that were previously not exercised directly:
#   1. asset_product_scope_mismatch surfaces as decision.reason_code
#   2. stale_telemetry remaps to telemetry_too_stale_for_scope_validation
#   3. physical_presence_proof_missing quarantine distinct from
#      coordinate_scope_unverified
#   4. coordinate_scope_unverified quarantine path
#   5. escalate disposition passes through untouched
#   6. target_zone falls back to authority_scope.expected_to_zone
#   7. hot-path telemetry carries current_zone / current_coordinate_ref
#   8. feature-flagged auth boundary (401 unauthenticated, 403 role mismatch)
# ---------------------------------------------------------------------------


def _payload_without_product_refs() -> dict:
    payload = _base_payload()
    payload["asset"].pop("product_ref", None)
    payload["authority_scope"].pop("product_ref", None)
    return payload


def _allow_evaluate_response_for_overlay_tests(**overrides) -> agent_actions_router.AgentActionEvaluateResponse:
    defaults = dict(
        request_id="req-transfer-2026-0001",
        decided_at=datetime.now(timezone.utc),
        latency_ms=10,
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
        minted_artifacts=["ExecutionToken", "PolicyReceipt"],
    )
    defaults.update(overrides)
    return agent_actions_router.AgentActionEvaluateResponse(**defaults)


def test_forensic_scope_guards_maps_product_mismatch_to_reason_code():
    # The schema validator rejects contradictory product_ref at parse time, so
    # this overlay path protects against the case where the authority scope
    # verdict is derived from persisted truth rather than the caller's claim.
    payload = agent_actions_router.AgentActionEvaluateRequest.model_validate(_base_payload())
    response = _allow_evaluate_response_for_overlay_tests(
        authority_scope_verdict={
            "status": "mismatch",
            "scope_id": "scope:rct-2026-0001",
            "mismatch_keys": ["asset_product_scope_mismatch"],
        },
    )
    updated = agent_actions_router._apply_forensic_scope_guards(payload=payload, response=response)
    assert updated.decision.disposition == "deny"
    assert updated.decision.reason_code == "asset_product_scope_mismatch"
    assert "authority_scope_mismatch" in updated.trust_gaps
    assert updated.execution_token is None
    assert "ExecutionToken" not in updated.minted_artifacts


def test_forensic_scope_guards_prefers_coordinate_mismatch_over_product_mismatch():
    payload = agent_actions_router.AgentActionEvaluateRequest.model_validate(_base_payload())
    response = _allow_evaluate_response_for_overlay_tests(
        authority_scope_verdict={
            "status": "mismatch",
            "scope_id": "scope:rct-2026-0001",
            "mismatch_keys": [
                "asset_product_scope_mismatch",
                "coordinate_scope_mismatch",
            ],
        },
    )
    updated = agent_actions_router._apply_forensic_scope_guards(payload=payload, response=response)
    assert updated.decision.disposition == "deny"
    assert updated.decision.reason_code == "coordinate_scope_mismatch"


def test_agent_actions_evaluate_remaps_stale_telemetry_reason_code(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    def _stale_response(*args, **kwargs):
        return HotPathEvaluateResponse(
            request_id="req-transfer-2026-0001",
            decided_at=datetime.now(timezone.utc),
            latency_ms=33,
            decision=HotPathDecisionView(
                allowed=False,
                disposition="quarantine",
                reason_code="stale_telemetry",
                reason="Telemetry freshness exceeds policy limits.",
                policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
            ),
            trust_gaps=["stale_telemetry"],
        )

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _stale_response)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "telemetry_too_stale_for_scope_validation"
    assert "telemetry_too_stale_for_scope_validation" in body["trust_gaps"]
    assert "stale_telemetry" not in body["trust_gaps"]
    assert body["execution_token"] is None


def test_agent_actions_evaluate_quarantines_when_coordinate_scope_unverified(monkeypatch):
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
    # Coordinate expected by scope, telemetry cannot prove it, but physical
    # presence hash is present -> should downgrade to `coordinate_scope_unverified`.
    payload["telemetry"].pop("current_coordinate_ref", None)
    payload["forensic_context"] = {
        "fingerprint_components": {
            "physical_presence_hash": "sha256:physical-presence",
        }
    }

    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "coordinate_scope_unverified"
    assert "coordinate_scope_unverified" in body["trust_gaps"]
    assert body["execution_token"] is None


def test_agent_actions_evaluate_quarantines_when_physical_presence_proof_missing(monkeypatch):
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
    payload["telemetry"].pop("current_coordinate_ref", None)
    # No forensic_context at all -> physical_presence_hash missing

    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["disposition"] == "quarantine"
    assert body["decision"]["reason_code"] == "physical_presence_proof_missing"
    assert "physical_presence_proof_missing" in body["trust_gaps"]
    assert body["execution_token"] is None


def test_agent_actions_evaluate_passes_through_escalate_disposition(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    def _escalate_response(*args, **kwargs):
        return HotPathEvaluateResponse(
            request_id="req-transfer-2026-0001",
            decided_at=datetime.now(timezone.utc),
            latency_ms=55,
            decision=HotPathDecisionView(
                allowed=False,
                disposition="escalate",
                reason_code="human_review_required",
                reason="Manual governance review required.",
                policy_snapshot_ref="snapshot:pkg-prod-2026-03-31",
            ),
            required_approvals=["human_governance_review"],
        )

    monkeypatch.setattr(
        agent_actions_router,
        "resolve_authoritative_transfer_approval",
        _empty_authoritative_approval,
    )
    monkeypatch.setattr(agent_actions_router, "evaluate_pdp_hot_path", _escalate_response)
    monkeypatch.setattr(agent_actions_router, "_organism_preflight_check", _organism_preflight_ok)

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["disposition"] == "escalate"
    assert body["decision"]["reason_code"] == "human_review_required"
    assert body["execution_token"] is None
    assert "human_governance_review" in body["required_approvals"]


def test_agent_actions_evaluate_target_zone_falls_back_to_authority_scope(monkeypatch):
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
    payload["asset"].pop("to_zone", None)
    payload["authority_scope"]["expected_to_zone"] = "handoff_bay_3"

    response = client.post("/api/v1/agent-actions/evaluate", json=payload)
    assert response.status_code == 200, response.text
    mapped_request = captured["request"]
    assert mapped_request.action_intent.resource.target_zone == "handoff_bay_3"


def test_agent_actions_evaluate_forwards_current_zone_and_coordinate_to_hot_path(monkeypatch):
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

    response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200, response.text
    telemetry = captured["request"].telemetry_context
    assert telemetry.current_zone == "vault_a"
    assert telemetry.current_coordinate_ref == "gazebo://warehouse/shelf/A3"


def test_agent_actions_evaluate_requires_bearer_when_auth_enabled(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_MODE", "shared_key")
    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_TOKEN", "top-secret")
    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_ALLOWED_ROLES", set())

    # Missing Authorization header
    unauth = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert unauth.status_code == 401

    # Wrong bearer
    wrong = client.post(
        "/api/v1/agent-actions/evaluate",
        json=_base_payload(),
        headers={"Authorization": "Bearer nope"},
    )
    assert wrong.status_code == 401


def test_agent_actions_evaluate_rejects_role_not_on_allowlist(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_MODE", "shared_key")
    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_TOKEN", "top-secret")
    monkeypatch.setattr(
        agent_actions_router,
        "GATEWAY_AUTH_ALLOWED_ROLES",
        {"SUPPLY_CHAIN_ADMIN"},
    )

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

    # Correct bearer but role is TRANSFER_COORDINATOR (not on allowlist)
    response = client.post(
        "/api/v1/agent-actions/evaluate",
        json=_base_payload(),
        headers={"Authorization": "Bearer top-secret"},
    )
    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["error_code"] == "role_not_authorized_for_workflow"
    assert detail["role_profile"] == "TRANSFER_COORDINATOR"


def test_agent_actions_evaluate_accepts_authenticated_request(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()
    client = _make_client()

    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_MODE", "shared_key")
    monkeypatch.setattr(agent_actions_router, "GATEWAY_AUTH_TOKEN", "top-secret")
    monkeypatch.setattr(
        agent_actions_router,
        "GATEWAY_AUTH_ALLOWED_ROLES",
        {"TRANSFER_COORDINATOR"},
    )

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

    response = client.post(
        "/api/v1/agent-actions/evaluate",
        json=_base_payload(),
        headers={"Authorization": "Bearer top-secret"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["decision"]["disposition"] == "allow"


def test_agent_action_gateway_decision_log_is_emitted(monkeypatch, caplog):
    import logging as _stdlib_logging

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

    with caplog.at_level(_stdlib_logging.INFO, logger="seedcore.api.routers.agent_actions_router"):
        response = client.post("/api/v1/agent-actions/evaluate", json=_base_payload())
    assert response.status_code == 200, response.text

    decision_records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "agent_action_gateway.evaluate.decision"
    ]
    assert decision_records, "expected a structured gateway decision log line"
    record = decision_records[-1]
    assert record.request_id == "req-transfer-2026-0001"
    assert record.idempotency_key == "idem-transfer-2026-0001"
    assert record.agent_id == "agent:custody_runtime_01"
    assert record.hardware_fingerprint_id == "fp:jetson-orin-01"
    assert record.asset_id == "asset:lot-8841"
    assert record.scope_id == "scope:rct-2026-0001"
    assert record.disposition == "allow"
    assert record.reason_code == "restricted_custody_transfer_allowed"
    assert record.policy_snapshot_ref
    assert isinstance(record.latency_ms, int)


def test_agent_action_gateway_in_memory_idempotency_respects_ttl(monkeypatch):
    agent_actions_router._clear_agent_action_request_store_for_tests()

    # Shrink TTL to 1 second for this test.
    monkeypatch.setattr(agent_actions_router, "REQUEST_RECORD_TTL_SECONDS", 1)

    # Insert stale entries (recorded 10 minutes ago).
    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    fake_idem_entry = agent_actions_router._AgentActionIdempotencyEntry(
        request_id="req-old",
        request_hash="hash-old",
        created_at=stale,
    )
    agent_actions_router._IDEMPOTENCY_ENTRIES_BY_KEY["idem-old"] = fake_idem_entry

    fake_record = agent_actions_router._AgentActionStoredRecord(
        request_id="req-old",
        idempotency_key="idem-old",
        request_hash="hash-old",
        recorded_at=stale,
        response=agent_actions_router.AgentActionEvaluateResponse(
            request_id="req-old",
            decided_at=stale,
            latency_ms=1,
            decision=HotPathDecisionView(
                allowed=False,
                disposition="deny",
                reason_code="x",
                reason="x",
                policy_snapshot_ref="snap:x",
            ),
        ),
        request_payload={},
    )
    agent_actions_router._REQUEST_RECORDS_BY_ID["req-old"] = fake_record

    agent_actions_router._gc_in_memory_stores()

    assert "idem-old" not in agent_actions_router._IDEMPOTENCY_ENTRIES_BY_KEY
    assert "req-old" not in agent_actions_router._REQUEST_RECORDS_BY_ID
