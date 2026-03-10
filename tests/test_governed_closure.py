# Import mock dependencies BEFORE any other imports
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

import pytest

from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import RoleProfile, RoleRegistry, Specialization
from seedcore.models.task_payload import TaskPayload
from seedcore.tools.base import ToolBase
from seedcore.tools.manager import ToolError, ToolManager


class DummyReachyMotionTool(ToolBase):
    name = "reachy.motion"
    description = "Dummy actuation tool for tests"

    async def run(self, **kwargs):
        return {"status": "ok", "robot_state": {"head": kwargs.get("head", {})}}


@pytest.mark.asyncio
async def test_tool_manager_requires_execution_token_for_actuation():
    manager = ToolManager()
    await manager.register_internal(DummyReachyMotionTool())

    with pytest.raises(ToolError) as exc:
        await manager.execute("reachy.motion", {"head": {"yaw": 0.1}}, agent_id="agent-1")
    assert "missing_execution_token" in str(exc.value)

    governance = {
        "execution_token": {
            "token_id": "tok-1",
            "intent_id": "intent-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": "sig-1",
        }
    }
    out = await manager.execute(
        "reachy.motion",
        {"head": {"yaw": 0.2}, "_governance": governance},
        agent_id="agent-1",
    )
    assert out["status"] == "ok"

    rec = await manager.execute(
        "custody.ledger.record",
        {"entry": {"task_id": "task-1", "intent_ref": "governance://action-intent/intent-1"}},
        agent_id="agent-1",
    )
    assert rec["ok"] is True
    rows = await manager.execute("custody.ledger.list", {"limit": 10}, agent_id="agent-1")
    assert rows["ok"] is True
    assert len(rows["entries"]) == 1


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
                    "signature": "sig-governed-1",
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
