from __future__ import annotations

import json

import pytest

from seedcore.drills.agent_self_regulation import (
    DRILL_NAME,
    run_agent_self_regulation_drill,
)


@pytest.mark.agent_self_regulation_drill
@pytest.mark.asyncio
async def test_agent_self_regulation_drill_captures_reviewable_gate_evidence(tmp_path):
    manifest_path = tmp_path / "gated_actions_manifest.json"
    evidence_path = tmp_path / "drill_evidence.json"

    evidence = await run_agent_self_regulation_drill(
        manifest_path=manifest_path,
        evidence_path=evidence_path,
    )

    assert evidence["drill"] == DRILL_NAME
    assert evidence["manifest_path"] == str(manifest_path)
    assert set(evidence["manifest_action_ids"]) == {
        "agent_self_regulation.py:enforce_transfer_custody",
        "agent_self_regulation.py:shadow_transfer_custody",
    }

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["gated_actions"]["agent_self_regulation.py:shadow_transfer_custody"]["mode"] == "shadow"
    assert manifest["gated_actions"]["agent_self_regulation.py:enforce_transfer_custody"]["mode"] == "enforce"

    mcp_evidence = evidence["mcp_check_policy"]
    assert mcp_evidence["ok"] is True
    assert mcp_evidence["decision"]["disposition"] == "allow"
    assert mcp_evidence["no_execute"] is True
    assert mcp_evidence["execution_token_present"] is False
    assert mcp_evidence["owner_id"] == "did:seedcore:owner:self-regulation-buyer"
    assert mcp_evidence["delegation_ref"] == "delegation:self-regulation-transfer"
    assert mcp_evidence["session_token"] == "session-agent-self-regulation"
    assert mcp_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/mcp-check-policy"

    shadow_evidence = evidence["sdk_shadow"]
    assert shadow_evidence["decision"] == "allow"
    assert shadow_evidence["upstream_evaluator_called"] is True
    assert shadow_evidence["payload_no_execute"] is True
    assert shadow_evidence["execution_result"] is None
    assert shadow_evidence["business_logic_executed"] is False
    assert shadow_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/sdk-shadow"

    enforce_evidence = evidence["sdk_enforce"]
    assert enforce_evidence["decision"] == "allow"
    assert enforce_evidence["upstream_evaluator_called"] is True
    assert enforce_evidence["payload_no_execute"] is False
    assert enforce_evidence["execution_token_id"] == "token:sdk-enforce"
    assert enforce_evidence["execution_result"]["status"] == "governed_business_executed"
    assert enforce_evidence["business_logic_executed"] is True
    assert enforce_evidence["closure_called"] is True
    assert enforce_evidence["closure_request_id"] == "req-agent-self-regulation-drill-001"
    assert enforce_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/sdk-enforce"

    negative_drills = evidence["negative_drills"]
    assert set(negative_drills) == {
        "pdp_deny",
        "pdp_quarantine",
        "stale_telemetry_preflight",
        "out_of_bounds_preflight",
        "missing_evidence",
    }

    deny_evidence = negative_drills["pdp_deny"]
    assert deny_evidence["decision"] == "deny"
    assert deny_evidence["reason_code"] == "self_regulation_policy_denied"
    assert deny_evidence["verification_status"] == "failed"
    assert deny_evidence["upstream_evaluator_called"] is True
    assert deny_evidence["payload_no_execute"] is False
    assert deny_evidence["business_logic_executed"] is False
    assert deny_evidence["execution_token_id"] is None
    assert deny_evidence["closure_called"] is False
    assert deny_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/pdp-deny"
    assert deny_evidence["audit_id"] == "audit:pdp-deny"

    quarantine_evidence = negative_drills["pdp_quarantine"]
    assert quarantine_evidence["decision"] == "quarantine"
    assert quarantine_evidence["reason_code"] == "self_regulation_trust_gap_quarantine"
    assert quarantine_evidence["verification_status"] == "incomplete"
    assert quarantine_evidence["upstream_evaluator_called"] is True
    assert quarantine_evidence["payload_no_execute"] is False
    assert quarantine_evidence["business_logic_executed"] is False
    assert quarantine_evidence["execution_token_id"] is None
    assert quarantine_evidence["closure_called"] is False
    assert quarantine_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/pdp-quarantine"
    assert quarantine_evidence["audit_id"] == "audit:pdp-quarantine"

    stale_evidence = negative_drills["stale_telemetry_preflight"]
    assert stale_evidence["decision"] == "quarantine"
    assert stale_evidence["reason_code"] == "stale_context"
    assert stale_evidence["upstream_evaluator_called"] is True
    assert stale_evidence["payload_no_execute"] is True
    assert stale_evidence["payload_request_id"] == "req-agent-self-regulation-stale-telemetry-001"
    assert stale_evidence["business_logic_executed"] is False
    assert stale_evidence["execution_token_id"] is None
    assert stale_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/stale-telemetry-preflight"

    out_of_bounds_evidence = negative_drills["out_of_bounds_preflight"]
    assert out_of_bounds_evidence["decision"] == "deny"
    assert out_of_bounds_evidence["reason_code"] == "out_of_bounds_scope"
    assert out_of_bounds_evidence["upstream_evaluator_called"] is True
    assert out_of_bounds_evidence["payload_no_execute"] is True
    assert out_of_bounds_evidence["payload_request_id"] == "req-agent-self-regulation-out-of-bounds-001"
    assert out_of_bounds_evidence["business_logic_executed"] is False
    assert out_of_bounds_evidence["execution_token_id"] is None
    assert out_of_bounds_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/out-of-bounds-preflight"

    missing_evidence = negative_drills["missing_evidence"]
    assert missing_evidence["decision"] == "quarantine"
    assert missing_evidence["reason_code"] == "missing_required_evidence"
    assert missing_evidence["verification_status"] == "incomplete"
    assert missing_evidence["upstream_evaluator_called"] is False
    assert missing_evidence["payload_no_execute"] is None
    assert missing_evidence["payload_request_id"] is None
    assert missing_evidence["business_logic_executed"] is False
    assert missing_evidence["execution_token_id"] is None
    assert missing_evidence["audit_id"] is None
    assert missing_evidence["replay_ref"] == "replay://workflow/request_id/req-agent-self-regulation-missing-evidence-001"

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
