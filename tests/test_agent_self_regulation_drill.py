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
    assert shadow_evidence["payload_no_execute"] is True
    assert shadow_evidence["execution_result"] is None
    assert shadow_evidence["business_logic_executed"] is False
    assert shadow_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/sdk-shadow"

    enforce_evidence = evidence["sdk_enforce"]
    assert enforce_evidence["decision"] == "allow"
    assert enforce_evidence["payload_no_execute"] is False
    assert enforce_evidence["execution_token_id"] == "token:sdk-enforce"
    assert enforce_evidence["execution_result"]["status"] == "governed_business_executed"
    assert enforce_evidence["closure_called"] is True
    assert enforce_evidence["closure_request_id"] == "req-agent-self-regulation-drill-001"
    assert enforce_evidence["replay_ref"] == "replay://workflow/agent-self-regulation/sdk-enforce"

    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
