from __future__ import annotations

import datetime
import threading
import uuid
import pytest

from seedcore.sdk import (
    gated_action,
    set_evaluator,
    reset_evaluator,
    using_evaluator,
    GovernedResult,
    GatedActionEvaluatorNotConfigured,
    GatedActionEvaluationError,
)

# Helper functions to build standard RCT intent structures matching test baselines
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


def _base_telemetry(evidence_refs: list[str] = None) -> dict:
    if evidence_refs is None:
        evidence_refs = ["origin_scan", "delivery_scan", "signed_edge_telemetry"]
    return {
        "observed_at": "2026-03-31T09:59:58Z",
        "freshness_seconds": 2,
        "max_allowed_age_seconds": 300,
        "current_zone": "vault_a",
        "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
        "evidence_refs": evidence_refs,
    }


def _base_security_contract() -> dict:
    return {"hash": "sha256:contract-hash", "version": "rules@8.0.0"}


def _base_approval() -> dict:
    return {"approval_envelope_id": "approval-transfer-001", "expected_envelope_version": "23"}


def _base_shopify_transaction() -> dict:
    return {
        "product_ref": "shopify:gid://shopify/Product/1234567890",
        "order_ref": "shopify:gid://shopify/Order/1002003004",
        "quote_ref": "shopify:quote:tea-set-2026-04-01-0001",
        "declared_value_usd": 1500,
        "economic_hash": "sha256:shopify-order",
    }


def _make_valid_intent(evidence_refs: list[str] = None) -> dict:
    """Builds a complete, valid intent payload matching RCT schema expectations."""
    return {
        "request_id": "req-transfer-2026-sdk-001",
        "idempotency_key": "idem-transfer-2026-sdk-001",
        "requested_at": "2026-03-31T10:00:00Z",
        "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31",
        "principal": _base_principal(),
        "workflow_valid_until": "2026-03-31T10:01:00Z",
        "asset_base": _base_asset_base(),
        "approval_envelope_id": _base_approval()["approval_envelope_id"],
        "approval_expected_envelope_version": _base_approval()["expected_envelope_version"],
        "authority_scope_base": _base_authority_scope_base(),
        "telemetry": _base_telemetry(evidence_refs),
        "security_contract": _base_security_contract(),
        "shopify_sandbox_transaction": _base_shopify_transaction(),
        "options": {"debug": False},
    }


@pytest.fixture(autouse=True)
def clean_evaluator_state():
    """Automatically resets the registered evaluator between test runs."""
    reset_evaluator()
    yield
    reset_evaluator()


# -----------------------------------------------------------------------------
# 1. GatedActionEvaluatorNotConfigured (Strict Fail Closed)
# -----------------------------------------------------------------------------
def test_raises_gated_action_evaluator_not_configured_when_missing():
    @gated_action(
        policy="strict_custody",
        evidence_required=["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        fail_mode="quarantine",
    )
    def my_gated_endpoint(intent: dict):
        raise AssertionError("Inner function should NEVER execute in preflight mode")

    intent = _make_valid_intent()
    # No evaluator is configured, must fail closed with GatedActionEvaluatorNotConfigured
    with pytest.raises(GatedActionEvaluatorNotConfigured, match="evaluator not configured"):
        my_gated_endpoint(intent)


# -----------------------------------------------------------------------------
# 2. Context Manager Isolation & reset_evaluator
# -----------------------------------------------------------------------------
def test_context_manager_isolates_evaluator_state():
    # Explicit dummy evaluator
    def dummy_evaluator(payload):
        return {
            "contract_version": "seedcore.agent_action_gateway.v1",
            "request_id": payload["request_id"],
            "decided_at": "2026-03-31T10:00:01Z",
            "latency_ms": 1,
            "decision": {"disposition": "allow", "reason_code": "allowed"},
        }

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    intent = _make_valid_intent()

    # Outside the context manager, it should still fail closed
    with pytest.raises(GatedActionEvaluatorNotConfigured):
        my_gated_endpoint(intent)

    # Inside the context manager, it should succeed using dummy_evaluator
    with using_evaluator(dummy_evaluator):
        result = my_gated_endpoint(intent)
        assert result.decision == "allow"
        assert result.verification_status == "passed"

    # Outside again, it fails closed once more
    with pytest.raises(GatedActionEvaluatorNotConfigured):
        my_gated_endpoint(intent)


def test_context_manager_uses_thread_local_override_without_replacing_global_evaluator():
    def global_evaluator(payload):
        return {"decision": {"disposition": "deny", "reason_code": "global"}}

    def local_evaluator(payload):
        return {"decision": {"disposition": "allow", "reason_code": "local"}}

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    intent = _make_valid_intent()
    set_evaluator(global_evaluator)

    with using_evaluator(local_evaluator):
        result = my_gated_endpoint(intent)
        assert result.decision == "allow"
        assert result.reason_code == "local"

    result = my_gated_endpoint(intent)
    assert result.decision == "deny"
    assert result.reason_code == "global"


def test_context_manager_thread_local_isolation_between_threads():
    barrier = threading.Barrier(2)
    results: dict[str, str] = {}

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    def run_thread(name: str, disposition: str) -> None:
        def evaluator(payload):
            return {"decision": {"disposition": disposition, "reason_code": name}}

        with using_evaluator(evaluator):
            barrier.wait(timeout=5)
            result = my_gated_endpoint(_make_valid_intent())
            results[name] = result.decision

    t1 = threading.Thread(target=run_thread, args=("one", "allow"))
    t2 = threading.Thread(target=run_thread, args=("two", "quarantine"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results == {"one": "allow", "two": "quarantine"}


# -----------------------------------------------------------------------------
# 3. Preflight Mode Preservation (Never execute inner business logic)
# -----------------------------------------------------------------------------
def test_never_executes_wrapped_business_function_in_mvp_preflight():
    execution_counter = 0

    def mock_evaluator(payload):
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "governed_receipt": {"audit_id": "audit-123"},
        }

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        raise RuntimeError("Should never reach this point")

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator):
        result = my_gated_endpoint(intent)
        assert result.decision == "allow"
        # Counter must remain exactly 0, confirming business function was bypassed
        assert execution_counter == 0


# -----------------------------------------------------------------------------
# 4. SDK-Side Telemetry Validation
# -----------------------------------------------------------------------------
def test_sdk_side_telemetry_validation_missing_evidence_direct_fail_mode():
    evaluator_called = False

    def dummy_evaluator(payload):
        nonlocal evaluator_called
        evaluator_called = True
        return {"decision": {"disposition": "allow"}}

    # Protecting function requiring three distinct evidence tokens
    @gated_action(
        policy="strict_custody",
        evidence_required=["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        fail_mode="quarantine",
    )
    def transfer_item(intent: dict):
        pass

    # Provide intent missing 'signed_edge_telemetry' ref
    intent = _make_valid_intent(evidence_refs=["origin_scan", "delivery_scan"])

    with using_evaluator(dummy_evaluator):
        result = transfer_item(intent)
        
        # Must immediately return configured fail_mode (quarantine) with SDK verification status
        assert result.decision == "quarantine"
        assert result.reason_code == "missing_required_evidence"
        assert result.verification_status == "incomplete"
        assert result.audit_id is None
        
        # Evaluator must NOT have been called, bypassing network/eval overhead
        assert not evaluator_called


def test_sdk_side_telemetry_validation_supports_all_evidence_labels():
    def mock_allow_evaluator(payload):
        return {
            "request_id": payload["request_id"],
            "decided_at": "2026-03-31T10:00:01Z",
            "latency_ms": 3,
            "decision": {"disposition": "allow", "reason_code": "allowed_all_evidence_green"},
            "forensic_linkage": {
                "forensic_block_id": "fb-992",
                "audit_id": "audit-992",
                "replay_ref": "replay://workflow/rct_handshake_992",
            },
        }

    @gated_action(
        policy="strict_custody",
        evidence_required=["origin_scan", "delivery_scan", "signed_edge_telemetry"],
        fail_mode="deny",
    )
    def my_gated_endpoint(intent: dict):
        pass

    # Supply all three required evidence tags
    intent = _make_valid_intent(evidence_refs=["origin_scan", "delivery_scan", "signed_edge_telemetry"])

    with using_evaluator(mock_allow_evaluator):
        result = my_gated_endpoint(intent)
        assert result.decision == "allow"
        assert result.reason_code == "allowed_all_evidence_green"
        assert result.verification_status == "passed"
        assert result.audit_id == "audit-992"
        assert result.evidence_bundle_id == "fb-992"
        assert result.replay_ref == "replay://workflow/rct_handshake_992"


def test_rejects_unsupported_policy_fail_mode_and_evidence_label():
    with pytest.raises(ValueError, match="Unsupported gated action policy"):
        gated_action(policy="open_custody")

    with pytest.raises(ValueError, match="Unsupported gated action fail_mode"):
        gated_action(fail_mode="execute_anyway")

    with pytest.raises(ValueError, match="Unsupported gated action evidence labels"):
        gated_action(evidence_required=["origin_scan", "retina_scan"])


def test_evaluator_can_return_testclient_style_json_response():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "decision": {"disposition": "allow", "reason_code": "http_ok"},
                "forensic_linkage": {"replay_ref": "replay://workflow/http"},
            }

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    with using_evaluator(lambda payload: FakeResponse()):
        result = my_gated_endpoint(_make_valid_intent())
        assert result.decision == "allow"
        assert result.reason_code == "http_ok"
        assert result.replay_ref == "replay://workflow/http"


def test_evaluator_http_error_fails_closed():
    class FakeErrorResponse:
        status_code = 503

        def json(self):
            return {"detail": "unavailable"}

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    with using_evaluator(lambda payload: FakeErrorResponse()):
        with pytest.raises(GatedActionEvaluationError, match="HTTP 503"):
            my_gated_endpoint(_make_valid_intent())


# -----------------------------------------------------------------------------
# 5. Gateway Evaluation (Allow & Preflight Refs)
# -----------------------------------------------------------------------------
def test_evaluation_returns_correct_governed_result_structure_without_strict_audit_id():
    def mock_evaluator_no_audit(payload):
        # Emulating a preflight response where execution_token is stripped and audit_id is None
        return {
            "contract_version": "seedcore.agent_action_gateway.v1",
            "request_id": payload["request_id"],
            "decided_at": "2026-03-31T10:00:01Z",
            "latency_ms": 5,
            "decision": {"disposition": "allow", "reason_code": "preflight_allowed"},
            "replay_lookup": {
                "preferred_key": "request_id_fallback",
            },
            "governed_receipt": {
                "audit_id": None, # audit_id is None in preflight
                "forensic_block_id": "fb-preflight-abc",
            },
        }

    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator_no_audit):
        result = my_gated_endpoint(intent)
        assert result.decision == "allow"
        assert result.reason_code == "preflight_allowed"
        assert result.verification_status == "passed"
        assert result.audit_id is None  # preflight allows None audit_id
        assert result.evidence_bundle_id == "fb-preflight-abc"
        # Prefer replay_lookup fallback key
        assert result.replay_ref == "replay://workflow/request_id_fallback"
        assert result.execution_token_id is None  # preflight has no execution token


# -----------------------------------------------------------------------------
# 6. Intent and Delegation Validation
# -----------------------------------------------------------------------------
def test_raises_value_error_on_missing_principal_delegation():
    @gated_action(policy="strict_custody")
    def my_gated_endpoint(intent: dict):
        pass

    # Make intent lacking 'principal' field
    intent = _make_valid_intent()
    intent.pop("principal")

    def dummy_eval(payload):
        return {"decision": {"disposition": "allow"}}

    with using_evaluator(dummy_eval):
        with pytest.raises(ValueError, match="Missing required intent parameter: 'principal'"):
            my_gated_endpoint(intent)
