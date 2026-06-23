from __future__ import annotations

from datetime import datetime, timezone

from seedcore.models.pdp_hot_path import (
    HotPathDecisionView,
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathSignerProvenance,
)
from seedcore.ops.pdp_protobuf_serialization import (
    serialize_request_to_protobuf,
    deserialize_request_from_protobuf,
    serialize_response_to_protobuf,
    deserialize_response_from_protobuf,
)
from seedcore.ops.pdp_hot_path import evaluate_pdp_hot_path


def _base_evaluate_request() -> HotPathEvaluateRequest:
    payload = {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": "pdp-req-test-001",
        "requested_at": "2026-04-02T08:00:15Z",
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-02",
        "context_freshness": {
            "causality_token": "ctx-token-001",
            "minimum_observed_at": "2026-04-02T08:00:00Z",
            "local_view_ref": "local-view:rct-001",
        },
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
            },
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
            "current_zone": "vault_a",
            "current_coordinate_ref": "coord:vault-a:shelf-3",
            "evidence_refs": ["evidence:telemetry-001"],
        },
        "request_schema_bundle": {"type": "object", "properties": {}},
        "taxonomy_bundle": {"version": "1.0", "terms": []},
    }
    return HotPathEvaluateRequest.model_validate(payload)


def test_request_protobuf_round_trip() -> None:
    req = _base_evaluate_request()

    # 1. Serialize to Protobuf binary
    proto_bytes = serialize_request_to_protobuf(req)
    assert len(proto_bytes) > 0

    # 2. Deserialize back to Pydantic
    deserialized = deserialize_request_from_protobuf(proto_bytes)

    # 3. Assert semantic equivalence of request fields
    assert deserialized.contract_version == req.contract_version
    assert deserialized.request_id == req.request_id
    assert deserialized.policy_snapshot_ref == req.policy_snapshot_ref

    # Verify requested_at timestamps match (up to second precision)
    assert deserialized.requested_at.timestamp() == req.requested_at.timestamp()

    assert deserialized.model_dump(mode="json") == req.model_dump(mode="json")


def test_response_protobuf_round_trip(monkeypatch) -> None:
    # Set stage to 0 to easily evaluate using the mock/baseline without PKGManager errors
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "0")

    req = _base_evaluate_request()
    response = evaluate_pdp_hot_path(req)

    # Serialize response to protobuf
    proto_bytes = serialize_response_to_protobuf(response)
    assert len(proto_bytes) > 0

    # Deserialize back
    deserialized = deserialize_response_from_protobuf(proto_bytes)

    # Assert equivalence
    assert deserialized.contract_version == response.contract_version
    assert deserialized.request_id == response.request_id
    assert deserialized.latency_ms == response.latency_ms
    assert deserialized.decision.allowed == response.decision.allowed
    assert deserialized.decision.disposition == response.decision.disposition
    assert deserialized.decision.reason_code == response.decision.reason_code
    assert deserialized.decision.reason == response.decision.reason
    assert deserialized.decision.policy_snapshot_ref == response.decision.policy_snapshot_ref

    assert list(deserialized.required_approvals) == list(response.required_approvals)
    assert list(deserialized.trust_gaps) == list(response.trust_gaps)
    assert deserialized.obligations == response.obligations

    # Compare checks
    assert len(deserialized.checks) == len(response.checks)
    for c1, c2 in zip(deserialized.checks, response.checks):
        assert c1.check_id == c2.check_id
        assert c1.result == c2.result
        assert c1.detail == c2.detail


def test_response_protobuf_round_trip_preserves_signer_provenance() -> None:
    response = HotPathEvaluateResponse(
        request_id="pdp-req-signer-001",
        decided_at=datetime.now(timezone.utc),
        latency_ms=7,
        decision=HotPathDecisionView(
            allowed=False,
            disposition="deny",
            reason_code="authz_graph_divergence",
            reason="Divergence recorded.",
            policy_snapshot_ref="snapshot:pkg-prod-2026-04-02",
            trust_alert='{"code":"authz_graph_divergence"}',
        ),
        signer_provenance=[
            HotPathSignerProvenance(
                artifact_type="execution_token",
                signer_type="service",
                signer_id="seedcore-verify",
                key_ref="kms:seedcore/pdp",
                attestation_level="baseline",
            )
        ],
    )

    deserialized = deserialize_response_from_protobuf(serialize_response_to_protobuf(response))

    assert deserialized.model_dump(mode="json") == response.model_dump(mode="json")


def test_protobuf_serialization_size_efficiency() -> None:
    req = _base_evaluate_request()

    # Compare raw byte sizes
    json_bytes = req.model_dump_json().encode('utf-8')
    proto_bytes = serialize_request_to_protobuf(req)

    print(f"JSON payload size: {len(json_bytes)} bytes")
    print(f"Protobuf payload size: {len(proto_bytes)} bytes")

    # Protobuf is structurally packed and binary, so it should be smaller
    assert len(proto_bytes) < len(json_bytes)
