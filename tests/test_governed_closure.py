# Import mock dependencies BEFORE any other imports
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

import pytest

from seedcore.hal.custody.transition_receipts import build_transition_receipt


@pytest.fixture(autouse=True)
def _stub_rust_execution_token_for_tool_manager(monkeypatch):
    monkeypatch.setattr(
        "seedcore.tools.manager.verify_execution_token_with_rust",
        lambda token, now=None: {"verified": True},
    )
    monkeypatch.setattr(
        "seedcore.tools.manager.enforce_execution_token_with_rust",
        lambda token, request_context, now=None: {"allowed": True},
    )


def _stub_token_signature() -> dict:
    return {"signer_type": "test", "signing_scheme": "stub"}
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import RoleProfile, RoleRegistry, Specialization
from seedcore.models.task_payload import TaskPayload
from seedcore.tools.base import ToolBase
from seedcore.tools.manager import ToolError, ToolManager


class DummyReachyMotionTool(ToolBase):
    name = "reachy.motion"
    description = "Dummy actuation tool for tests"

    async def run(self, **kwargs):
        return {
            "status": "ok",
            "robot_state": {"head": kwargs.get("head", {})},
            "execution_token_id": (kwargs.get("execution_token") or {}).get("token_id"),
        }


@pytest.mark.asyncio
async def test_tool_manager_requires_execution_token_for_actuation():
    manager = ToolManager()
    await manager.register_internal(DummyReachyMotionTool())

    with pytest.raises(ToolError) as exc:
        await manager.execute("reachy.motion", {"head": {"yaw": 0.1}}, agent_id="agent-1")
    assert "missing_execution_token" in str(exc.value)

    governance = {
        "action_intent": {
            "intent_id": "intent-1",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "MOVE"},
            "resource": {"asset_id": "asset-1", "target_zone": "zone-a"},
        },
        "execution_token": {
            "token_id": "tok-1",
            "intent_id": "intent-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {
                "action_type": "MOVE",
                "target_zone": "zone-a",
                "asset_id": "asset-1",
                "principal_agent_id": "agent-1",
            },
        }
    }
    out = await manager.execute(
        "reachy.motion",
        {"head": {"yaw": 0.2}, "_governance": governance},
        agent_id="agent-1",
    )
    assert out["status"] == "ok"
    assert out["execution_token_id"] == "tok-1"

    rec = await manager.execute(
        "custody.ledger.record",
        {
            "entry": {"task_id": "task-1", "intent_ref": "governance://action-intent/intent-1"},
            "_governance": governance,
        },
        agent_id="agent-1",
    )
    assert rec["ok"] is True
    rows = await manager.execute("custody.ledger.list", {"limit": 10}, agent_id="agent-1")
    assert rows["ok"] is True
    assert len(rows["entries"]) == 1


@pytest.mark.asyncio
async def test_tool_manager_rejects_mismatched_execution_token_constraints(monkeypatch):
    monkeypatch.setattr(
        "seedcore.tools.manager.enforce_execution_token_with_rust",
        lambda token, request_context, now=None: {"allowed": False, "error_code": "target_zone"},
    )
    manager = ToolManager()
    await manager.register_internal(DummyReachyMotionTool())

    governance = {
        "action_intent": {
            "intent_id": "intent-1",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "MOVE"},
            "resource": {"asset_id": "asset-1", "target_zone": "zone-a"},
        },
        "execution_token": {
            "token_id": "tok-1",
            "intent_id": "intent-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {"target_zone": "zone-b"},
        },
    }

    with pytest.raises(ToolError) as exc:
        await manager.execute(
            "reachy.motion",
            {"head": {"yaw": 0.2}, "_governance": governance},
            agent_id="agent-1",
        )
    assert "execution_token_constraint_mismatch:target_zone" in str(exc.value)


@pytest.mark.asyncio
async def test_base_agent_closes_governed_custody_loop():
    role_registry = RoleRegistry()
    role_registry.register(
        RoleProfile(
            name=Specialization.GENERALIST,
            default_skills={},
            allowed_tools={"reachy.motion"},
            routing_tags=set(),
            safety_policies={},
        )
    )

    manager = ToolManager()
    await manager.register_internal(DummyReachyMotionTool())

    agent = BaseAgent(
        agent_id="agent-governed",
        specialization=Specialization.GENERALIST,
        role_registry=role_registry,
        tool_handler=manager,
    )

    task = TaskPayload(
        task_id="task-governed-1",
        type="action",
        description="move item",
        params={
            "tool_calls": [{"name": "reachy.motion", "args": {"head": {"yaw": 0.3}}}],
            "governance": {
                "action_intent": {
                    "intent_id": "intent-governed-1",
                    "resource": {"target_zone": "zone-a"},
                },
                "execution_token": {
                    "token_id": "tok-governed-1",
                    "intent_id": "intent-governed-1",
                    "valid_until": "2099-01-01T00:00:00+00:00",
                    "signature": _stub_token_signature(),
                },
                "policy_decision": {"allowed": True},
            },
            "multimodal": {"location_context": "zone-a"},
        },
    )

    result = await agent.execute_task(task)
    assert result["success"] is True
    assert result["meta"]["custody"]["validated"] is True
    assert result["meta"]["custody"]["ledger_updated"] is True
    assert "evidence_bundle" in result["meta"]
    assert (
        result["meta"]["evidence_bundle"]["intent_ref"]
        == "governance://action-intent/intent-governed-1"
    )

    ledger = await manager.execute("custody.ledger.list", {"limit": 10}, agent_id="agent-governed")
    assert ledger["ok"] is True
    assert any(
        row.get("intent_ref") == "governance://action-intent/intent-governed-1"
        for row in ledger["entries"]
    )

@pytest.mark.asyncio
async def test_tool_manager_requires_execution_token_for_memory_write():
    manager = ToolManager()
    
    # We mock MW Manager
    class MockMwManager:
        async def set_item_async(self, item_id, value, ttl_s=None):
            return True
            
    manager.mw_manager = MockMwManager()
    
    with pytest.raises(ToolError) as exc:
        await manager.execute("memory.mw.write", {"item_id": "test", "value": "test_val"}, agent_id="agent-1")
    assert "missing_execution_token" in str(exc.value)

    governance = {
        "action_intent": {
            "intent_id": "intent-1",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "WRITE"},
            "resource": {"asset_id": "test", "target_zone": None},
        },
        "execution_token": {
            "token_id": "tok-1",
            "intent_id": "intent-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {
                "action_type": "WRITE",
                "target_zone": None,
                "asset_id": "test",
                "principal_agent_id": "agent-1",
            },
        }
    }
    
    out = await manager.execute(
        "memory.mw.write",
        {"item_id": "test", "value": "test_val", "_governance": governance},
        agent_id="agent-1"
    )
    
    assert out.get("status") == "success"
    assert out.get("item_id") == "test"


@pytest.mark.asyncio
async def test_tool_manager_requires_execution_token_for_custody_ledger_record():
    manager = ToolManager()

    with pytest.raises(ToolError) as exc:
        await manager.execute(
            "custody.ledger.record",
            {"entry": {"task_id": "task-2", "intent_ref": "governance://action-intent/intent-2"}},
            agent_id="agent-1",
        )
    assert "missing_execution_token" in str(exc.value)

    governance = {
        "action_intent": {
            "intent_id": "intent-2",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "RECORD"},
            "resource": {"asset_id": "task-2", "target_zone": None},
        },
        "execution_token": {
            "token_id": "tok-2",
            "intent_id": "intent-2",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {
                "action_type": "RECORD",
                "asset_id": "task-2",
                "principal_agent_id": "agent-1",
            },
        },
    }

    out = await manager.execute(
        "custody.ledger.record",
        {
            "entry": {"task_id": "task-2", "intent_ref": "governance://action-intent/intent-2"},
            "_governance": governance,
        },
        agent_id="agent-1",
    )

    assert out["ok"] is True


def test_tool_manager_builds_asset_custody_update_from_governance():
    manager = ToolManager()
    transition_receipt = build_transition_receipt(
        intent_id="intent-7",
        token_id="tok-7",
        actuator_endpoint="robot_sim://asset-7",
        hardware_uuid="hardware-7",
        actuator_result_hash="hash-7",
        target_zone="packing-cell-2",
        to_zone="packing-cell-2",
    )

    update = manager._build_asset_custody_update(
        {
            "task_id": "8f5f4e2f-46d9-458a-85dd-d782c52f249d",
            "agent_id": "agent-7",
            "evidence_bundle": {
                "telemetry_snapshot": {"zone_checks": {"current_zone": "packing-cell-2"}},
                "execution_receipt": {
                    "actuator_endpoint": "robot_sim://asset-7",
                    "transition_receipt": transition_receipt,
                    "transition_receipt_hash": manager._sha256_hex(
                        manager._canonical_json(transition_receipt)
                    ),
                },
            },
        },
        {
            "action_intent": {
                "intent_id": "intent-7",
                "resource": {
                    "asset_id": "asset-7",
                    "target_zone": "staging-a",
                    "source_registration_id": "reg-7",
                },
            },
            "execution_token": {"token_id": "tok-7"},
            "policy_case": {
                "relevant_twin_snapshot": {
                    "asset": {"custody": {"quarantined": True, "target_zone": "vault-z"}}
                }
            },
        },
        prior_state={
            "last_transition_seq": 2,
            "last_receipt_hash": "old-hash",
            "last_receipt_nonce": "old-nonce",
        },
    )

    assert update is not None
    assert update["asset_id"] == "asset-7"
    assert update["current_zone"] == "packing-cell-2"
    assert update["is_quarantined"] is True
    assert update["source_registration_id"] == "reg-7"
    assert update["authority_source"] == "governed_transition_receipt"
    assert update["last_transition_seq"] == 3
    assert update["last_intent_id"] == "intent-7"
    assert update["last_token_id"] == "tok-7"


def test_tool_manager_rejects_replayed_transition_receipt():
    manager = ToolManager()
    transition_receipt = build_transition_receipt(
        intent_id="intent-8",
        token_id="tok-8",
        actuator_endpoint="robot_sim://asset-8",
        hardware_uuid="hardware-8",
        actuator_result_hash="hash-8",
        target_zone="zone-8",
        to_zone="zone-8",
    )

    with pytest.raises(ToolError) as exc:
        manager._build_asset_custody_update(
            {
                "task_id": "task-8",
                "agent_id": "agent-8",
                "evidence_bundle": {
                    "execution_receipt": {
                        "actuator_endpoint": "robot_sim://asset-8",
                        "transition_receipt": transition_receipt,
                        "transition_receipt_hash": manager._sha256_hex(
                            manager._canonical_json(transition_receipt)
                        ),
                    },
                },
            },
            {
                "action_intent": {
                    "intent_id": "intent-8",
                    "resource": {"asset_id": "asset-8", "target_zone": "zone-8"},
                },
                "execution_token": {"token_id": "tok-8"},
            },
            prior_state={
                "last_transition_seq": 1,
                "last_receipt_hash": transition_receipt["payload_hash"],
                "last_receipt_nonce": transition_receipt["receipt_nonce"],
            },
        )
    assert "replayed_transition_receipt" in str(exc.value)
