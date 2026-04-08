from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

import seedcore.api.routers.policy_assistant_router as policy_assistant_router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(policy_assistant_router.router, prefix="/api/v1", tags=["Policy Assistant"])
    return TestClient(app)


def _scenario_request(request_id: str, idempotency_key: str) -> dict:
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": idempotency_key,
        "principal": {
            "agent_id": "agent:custody_runtime_01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-abc",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
            "hardware_fingerprint": {
                "fingerprint_id": "fp:jetson-orin-01",
                "node_id": "node:jetson-orin-01",
                "public_key_fingerprint": "sha256:fingerprint-key",
            },
        },
        "workflow": {
            "type": "restricted_custody_transfer",
            "action_type": "TRANSFER_CUSTODY",
            "valid_until": datetime.now(timezone.utc).isoformat(),
        },
        "asset": {
            "asset_id": "asset:lot-8841",
            "provenance_hash": "sha256:asset-provenance",
        },
        "approval": {"approval_envelope_id": "approval-transfer-001"},
        "authority_scope": {
            "scope_id": "scope:rct-2026-0001",
            "asset_ref": "asset:lot-8841",
            "expected_to_zone": "handoff_bay_3",
        },
        "telemetry": {
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "evidence_refs": ["ev:cam-1"],
        },
        "security_contract": {
            "hash": "sha256:contract-hash",
            "version": "rules@8.0.0",
        },
        "options": {"no_execute": False},
    }


def test_policy_assistant_scenario_pack_forces_preflight_and_summarizes(monkeypatch):
    client = _make_client()
    captured_calls = []

    async def _fake_evaluate(payload_body, debug, no_execute):
        captured_calls.append({"payload_body": payload_body, "debug": debug, "no_execute": no_execute})
        disposition = "allow" if payload_body["request_id"].endswith("1") else "deny"
        return SimpleNamespace(
            decision=SimpleNamespace(disposition=disposition, reason_code=f"{disposition}_reason"),
            trust_gaps=[],
            required_approvals=["owner_step_up"] if disposition == "deny" else [],
            obligations=[],
            governed_receipt={"audit_id": f"audit-{payload_body['request_id']}"},
        )

    monkeypatch.setattr(policy_assistant_router, "evaluate_agent_action", _fake_evaluate)

    payload = {
        "owner_id": "did:seedcore:owner:acme-001",
        "policy_version": "v1",
        "scenarios": [
            {
                "scenario_id": "safe_purchase_001",
                "label": "Safe purchase",
                "request": _scenario_request("req-safe-1", "idem-safe-1"),
            },
            {
                "scenario_id": "risky_purchase_001",
                "label": "Risky purchase",
                "request": _scenario_request("req-risk-2", "idem-risk-2"),
            },
        ],
    }
    response = client.post("/api/v1/policy-assistant/scenario-pack/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"total": 2, "allowed": 1, "denied": 1, "escalated": 0, "errors": 0}
    assert all(call["no_execute"] is True for call in captured_calls)
    assert all(call["payload_body"]["options"]["no_execute"] is True for call in captured_calls)
    risky = next(item for item in body["results"] if item["scenario_id"] == "risky_purchase_001")
    assert risky["required_approvals"] == ["owner_step_up"]


def test_policy_assistant_scenario_pack_isolates_per_scenario_errors(monkeypatch):
    client = _make_client()

    async def _fake_evaluate(payload_body, debug, no_execute):
        del debug, no_execute
        if payload_body["request_id"].endswith("2"):
            raise HTTPException(
                status_code=422,
                detail={"error_code": "request_validation_failed", "message": "invalid telemetry"},
            )
        return SimpleNamespace(
            decision=SimpleNamespace(disposition="allow", reason_code="allow_reason"),
            trust_gaps=["owner_trust_modality_violation"],
            required_approvals=[],
            obligations=[],
            governed_receipt={"audit_id": f"audit-{payload_body['request_id']}"},
        )

    monkeypatch.setattr(policy_assistant_router, "evaluate_agent_action", _fake_evaluate)

    payload = {
        "owner_id": "did:seedcore:owner:acme-001",
        "policy_version": "v1",
        "scenarios": [
            {
                "scenario_id": "safe_purchase_001",
                "label": "Safe purchase",
                "request": _scenario_request("req-safe-1", "idem-safe-1"),
            },
            {
                "scenario_id": "bad_purchase_001",
                "label": "Bad purchase",
                "request": _scenario_request("req-bad-2", "idem-bad-2"),
            },
        ],
    }
    response = client.post("/api/v1/policy-assistant/scenario-pack/evaluate", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"total": 2, "allowed": 1, "denied": 0, "escalated": 0, "errors": 1}
    errored = next(item for item in body["results"] if item["scenario_id"] == "bad_purchase_001")
    assert errored["decision"] == "ERROR"
    assert errored["reason_code"] == "request_validation_failed"
