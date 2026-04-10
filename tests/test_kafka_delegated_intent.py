from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from seedcore.infra.kafka.delegated_intent import (
    DELEGATED_INTENT_PAYLOAD_SCHEMA_VERSION,
    DelegatedIntentPayload,
    build_delegated_intent_envelope,
)
from seedcore.infra.kafka.intent_ingress import process_delegated_intent_event


def _gateway_request() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": "req-kafka-delegated-001",
        "requested_at": now.isoformat(),
        "idempotency_key": "idem-kafka-delegated-001",
        "policy_snapshot_ref": "snapshot:pkg-delegated-v1",
        "principal": {
            "agent_id": "agent:openai-assistant-01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-123",
            "owner_id": "did:seedcore:owner:abc",
            "delegation_ref": "delegation:deleg-001",
            "hardware_fingerprint": {
                "fingerprint_id": "hw-fp-001",
                "public_key_fingerprint": "pk-fp-001",
            },
        },
        "workflow": {
            "type": "restricted_custody_transfer",
            "action_type": "TRANSFER_CUSTODY",
            "valid_until": (now + timedelta(minutes=5)).isoformat(),
        },
        "asset": {
            "asset_id": "asset:lot-8841",
            "product_ref": "product:sku-8841",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:asset-proof-8841",
            "declared_value_usd": 1200.0,
        },
        "approval": {
            "approval_envelope_id": "approval-transfer-001",
        },
        "authority_scope": {
            "scope_id": "scope-transfer-001",
            "asset_ref": "asset:lot-8841",
            "product_ref": "product:sku-8841",
            "facility_ref": "facility:bangkok-01",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
        },
        "telemetry": {
            "observed_at": now.isoformat(),
            "freshness_seconds": 5,
            "max_allowed_age_seconds": 60,
            "current_zone": "vault_a",
            "evidence_refs": ["evidence:telemetry-001"],
        },
        "security_contract": {
            "hash": "sha256:security-contract-001",
            "version": "rules@transfer-v1",
        },
        "options": {
            "debug": False,
            "no_execute": False,
        },
    }


def _delegated_payload() -> dict:
    return {
        "stream": "intent",
        "payload_schema_version": DELEGATED_INTENT_PAYLOAD_SCHEMA_VERSION,
        "request_id": "req-kafka-delegated-001",
        "workflow_id": "wf-kafka-delegated-001",
        "correlation_id": "corr-kafka-delegated-001",
        "assistant_namespace": "openai-agents",
        "owner_context_preflight": {
            "owner_id": "did:seedcore:owner:abc",
            "assistant_id": "agent:openai-assistant-01",
            "delegation_id": "deleg-001",
            "declared_value_usd": 1200.0,
            "required_modalities": ["telemetry"],
            "available_modalities": ["telemetry"],
            "observed_provenance_level": "verified",
            "risk_score": 0.1,
        },
        "gateway_request": _gateway_request(),
    }


def test_build_delegated_intent_envelope_shape() -> None:
    payload = DelegatedIntentPayload.model_validate(_delegated_payload())
    env = build_delegated_intent_envelope(payload, producer="openai-agent-gateway")
    assert env["producer"] == "openai-agent-gateway"
    assert env["payload"]["stream"] == "intent"
    assert env["payload"]["gateway_request"]["request_id"] == payload.request_id


def test_delegated_intent_payload_rejects_request_mismatch() -> None:
    payload = _delegated_payload()
    payload["request_id"] = "req-mismatch"
    with pytest.raises(ValueError, match="payload.request_id"):
        DelegatedIntentPayload.model_validate(payload)


@pytest.mark.asyncio
async def test_process_delegated_intent_event_rejects_on_failed_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEDCORE_KAFKA_INTENT_INGRESS_PREFLIGHT_REQUIRED", "1")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/owner-context/preflight":
            return httpx.Response(
                200,
                json={
                    "ok": False,
                    "delegation_check": {"valid": False, "issues": ["delegation_not_active"]},
                    "predicted_policy_signals": {"trust_gap_codes": ["owner_trust_risk_escalation"]},
                },
            )
        raise AssertionError(f"unexpected downstream call: {request.url.path}")

    event = build_delegated_intent_envelope(
        DelegatedIntentPayload.model_validate(_delegated_payload()),
        producer="openai-agent-gateway",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await process_delegated_intent_event(event, http_client=client)

    assert out["status"] == "rejected_preflight"
    assert out["request_id"] == "req-kafka-delegated-001"
    assert out["preflight"]["ok"] is False


@pytest.mark.asyncio
async def test_process_delegated_intent_event_forwards_to_agent_action_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEEDCORE_KAFKA_INTENT_INGRESS_PREFLIGHT_REQUIRED", "1")
    seen_paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        body = await request.aread()
        if request.url.path == "/api/v1/owner-context/preflight":
            return httpx.Response(200, json={"ok": True, "delegation_check": {"valid": True}})
        if request.url.path == "/api/v1/agent-actions/evaluate":
            assert request.url.params.get("no_execute") == "false"
            return httpx.Response(
                200,
                json={
                    "request_id": "req-kafka-delegated-001",
                    "decision": {"disposition": "allow", "reason_code": "restricted_custody_transfer_allowed"},
                    "trust_gaps": [],
                    "required_approvals": [],
                    "echo": body.decode("utf-8"),
                },
            )
        raise AssertionError(f"unexpected path: {request.url.path}")

    event = build_delegated_intent_envelope(
        DelegatedIntentPayload.model_validate(_delegated_payload()),
        producer="openai-agent-gateway",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await process_delegated_intent_event(event, http_client=client)

    assert seen_paths == ["/api/v1/owner-context/preflight", "/api/v1/agent-actions/evaluate"]
    assert out["status"] == "evaluated"
    assert out["evaluation"]["decision"]["disposition"] == "allow"
