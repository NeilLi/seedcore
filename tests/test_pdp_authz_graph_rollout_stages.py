from __future__ import annotations

import os
from types import SimpleNamespace
import pytest

import seedcore.ops.pdp_hot_path as pdp_hot_path
from seedcore.models.action_intent import ActionIntent, PolicyCase, PolicyDecision
from seedcore.models.pdp_hot_path import HotPathEvaluateRequest
from seedcore.ops.pdp_hot_path import evaluate_pdp_hot_path, _pdp_authz_graph_rollout_stage


def _base_evaluate_request(action_type: str = "TRANSFER_CUSTODY") -> HotPathEvaluateRequest:
    payload = {
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
                "type": action_type,
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
            "evidence_refs": ["evidence:telemetry-001"],
        },
    }
    return HotPathEvaluateRequest.model_validate(payload)


def test_rollout_stage_env_parsing(monkeypatch) -> None:
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "2")
    assert _pdp_authz_graph_rollout_stage() == 2

    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "9")
    assert _pdp_authz_graph_rollout_stage() == 4

    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "invalid")
    assert _pdp_authz_graph_rollout_stage() == 4

    monkeypatch.delenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", raising=False)
    monkeypatch.delenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH", raising=False)
    assert _pdp_authz_graph_rollout_stage() == 4

    monkeypatch.setenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH", "true")
    assert _pdp_authz_graph_rollout_stage() == 4

    monkeypatch.setenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH", "false")
    assert _pdp_authz_graph_rollout_stage() == 0


def test_evaluate_pdp_hot_path_stage_0_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "0")

    def fail_if_resolved():
        raise AssertionError("stage 0 must not resolve the compiled graph")

    monkeypatch.setattr(pdp_hot_path, "_resolve_hot_path_runtime_status", fail_if_resolved)

    # Let evaluate_intent mock baseline decision
    fake_baseline = PolicyDecision(
        allowed=True,
        disposition="allow",
        reason="baseline_allowed",
    )
    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", lambda policy_case, compiled_authz_index=None: fake_baseline)

    req = _base_evaluate_request()
    res = evaluate_pdp_hot_path(req)
    assert res.decision.allowed is True
    assert res.decision.disposition == "allow"
    assert res.decision.reason_code == "baseline_allowed"


def test_evaluate_pdp_hot_path_stage_1_shadow_comparison(monkeypatch) -> None:
    # Stage 1: run both, return baseline, compare/log (no alert)
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "1")

    dummy_index = SimpleNamespace(
        snapshot_version="snapshot:pkg-prod-2026-04-02",
        snapshot_id=1,
    )
    monkeypatch.setattr(pdp_hot_path, "_resolve_hot_path_runtime_status", lambda: {
        "compiled_authz_index": dummy_index,
        "active_snapshot_version": "snapshot:pkg-prod-2026-04-02",
        "compiled_at": "2026-04-02T08:00:00Z",
        "graph_age_seconds": 10.0,
        "graph_freshness_ok": True,
        "authz_graph_ready": True,
        "restricted_transfer_ready": True,
    })

    fake_baseline = PolicyDecision(
        allowed=True,
        disposition="allow",
        reason="baseline_allowed",
    )
    fake_compiled = PolicyDecision(
        allowed=False,
        disposition="deny",
        reason="compiled_denied",
    )

    def mock_evaluate_intent(policy_case, compiled_authz_index=None):
        if compiled_authz_index is not None:
            return fake_compiled
        return fake_baseline

    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", mock_evaluate_intent)

    req = _base_evaluate_request()
    res = evaluate_pdp_hot_path(req)

    # Should use baseline (allowed)
    assert res.decision.allowed is True
    assert res.decision.disposition == "allow"
    # No trust alert generated under stage 1
    assert res.decision.trust_alert is None


def test_evaluate_pdp_hot_path_stage_2_shadow_alert(monkeypatch) -> None:
    # Stage 2: run both, return baseline, alert on mismatch
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "2")

    dummy_index = SimpleNamespace(
        snapshot_version="snapshot:pkg-prod-2026-04-02",
        snapshot_id=1,
    )
    monkeypatch.setattr(pdp_hot_path, "_resolve_hot_path_runtime_status", lambda: {
        "compiled_authz_index": dummy_index,
        "active_snapshot_version": "snapshot:pkg-prod-2026-04-02",
        "compiled_at": "2026-04-02T08:00:00Z",
        "graph_age_seconds": 10.0,
        "graph_freshness_ok": True,
        "authz_graph_ready": True,
        "restricted_transfer_ready": True,
    })

    fake_baseline = PolicyDecision(
        allowed=True,
        disposition="allow",
        reason="baseline_allowed",
    )
    fake_compiled = PolicyDecision(
        allowed=False,
        disposition="deny",
        reason="compiled_denied",
    )

    def mock_evaluate_intent(policy_case, compiled_authz_index=None):
        if compiled_authz_index is not None:
            return fake_compiled
        return fake_baseline

    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", mock_evaluate_intent)

    req = _base_evaluate_request()
    res = evaluate_pdp_hot_path(req)

    # Should use baseline (allowed)
    assert res.decision.allowed is True
    assert res.decision.disposition == "allow"
    # Warning alert should be present due to mismatch
    assert res.decision.trust_alert is not None
    import json
    alert_dict = json.loads(res.decision.trust_alert)
    assert alert_dict["code"] == "authz_graph_divergence"
    assert "Divergence detected" in alert_dict["message"]


def test_evaluate_pdp_hot_path_stage_3_partial_enforcement(monkeypatch) -> None:
    # Stage 3: enforce compiled index on non-critical, baseline on critical
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "3")

    dummy_index = SimpleNamespace(
        snapshot_version="snapshot:pkg-prod-2026-04-02",
        snapshot_id=1,
    )
    monkeypatch.setattr(pdp_hot_path, "_resolve_hot_path_runtime_status", lambda: {
        "compiled_authz_index": dummy_index,
        "active_snapshot_version": "snapshot:pkg-prod-2026-04-02",
        "compiled_at": "2026-04-02T08:00:00Z",
        "graph_age_seconds": 10.0,
        "graph_freshness_ok": True,
        "authz_graph_ready": True,
        "restricted_transfer_ready": True,
    })

    fake_baseline = PolicyDecision(
        allowed=True,
        disposition="allow",
        reason="baseline_allowed",
    )
    fake_compiled = PolicyDecision(
        allowed=False,
        disposition="deny",
        reason="compiled_denied",
    )

    def mock_evaluate_intent(policy_case, compiled_authz_index=None):
        if compiled_authz_index is not None:
            return fake_compiled
        return fake_baseline

    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", mock_evaluate_intent)

    # 1. Critical workflow (TRANSFER_CUSTODY) -> uses baseline (allow)
    req_critical = _base_evaluate_request(action_type="TRANSFER_CUSTODY")
    res_critical = evaluate_pdp_hot_path(req_critical)
    assert res_critical.decision.allowed is True
    assert res_critical.decision.disposition == "allow"

    # 2. Non-critical workflow (e.g. OTHER_ACTION) -> enforces compiled index (deny)
    req_non_critical = _base_evaluate_request(action_type="OTHER_ACTION")
    res_non_critical = evaluate_pdp_hot_path(req_non_critical)
    assert res_non_critical.decision.allowed is False
    assert res_non_critical.decision.disposition == "deny"


def test_evaluate_pdp_hot_path_stage_4_full_enforcement(monkeypatch) -> None:
    # Stage 4: full enforcement
    monkeypatch.setenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE", "4")

    dummy_index = SimpleNamespace(
        snapshot_version="snapshot:pkg-prod-2026-04-02",
        snapshot_id=1,
    )
    monkeypatch.setattr(pdp_hot_path, "_resolve_hot_path_runtime_status", lambda: {
        "compiled_authz_index": dummy_index,
        "active_snapshot_version": "snapshot:pkg-prod-2026-04-02",
        "compiled_at": "2026-04-02T08:00:00Z",
        "graph_age_seconds": 10.0,
        "graph_freshness_ok": True,
        "authz_graph_ready": True,
        "restricted_transfer_ready": True,
    })

    fake_baseline = PolicyDecision(
        allowed=True,
        disposition="allow",
        reason="baseline_allowed",
    )
    fake_compiled = PolicyDecision(
        allowed=False,
        disposition="deny",
        reason="compiled_denied",
    )

    def mock_evaluate_intent(policy_case, compiled_authz_index=None):
        if compiled_authz_index is not None:
            return fake_compiled
        return fake_baseline

    monkeypatch.setattr(pdp_hot_path, "evaluate_intent", mock_evaluate_intent)

    req = _base_evaluate_request()
    res = evaluate_pdp_hot_path(req)

    # Should enforce compiled graph (deny)
    assert res.decision.allowed is False
    assert res.decision.disposition == "deny"
    assert res.decision.reason_code == "compiled_denied"
