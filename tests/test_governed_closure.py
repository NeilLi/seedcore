# Import mock dependencies BEFORE any other imports
import os
import sys
from contextlib import asynccontextmanager

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

    class _InMemoryAuditDAO:
        def __init__(self):
            self._rows = {}

        async def append_record(self, session, **kwargs):
            task_id = str(kwargs.get("task_id"))
            row = {
                "entry_id": str(len(self._rows.get(task_id, [])) + 1),
                "recorded_at": "2026-01-01T00:00:00+00:00",
                "input_hash": "input-hash",
                "evidence_hash": "evidence-hash",
                "task_id": task_id,
                "record_type": kwargs.get("record_type"),
                "intent_id": kwargs.get("intent_id"),
                "token_id": kwargs.get("token_id"),
                "policy_snapshot": kwargs.get("policy_snapshot"),
                "policy_decision": kwargs.get("policy_decision") or {},
                "action_intent": kwargs.get("action_intent") or {},
                "policy_case": kwargs.get("policy_case") or {},
                "policy_receipt": kwargs.get("policy_receipt") or {},
                "evidence_bundle": kwargs.get("evidence_bundle") or {},
                "actor_agent_id": kwargs.get("actor_agent_id"),
                "actor_organ_id": kwargs.get("actor_organ_id"),
            }
            self._rows.setdefault(task_id, []).append(row)
            return {
                "entry_id": row["entry_id"],
                "recorded_at": row["recorded_at"],
                "input_hash": row["input_hash"],
                "evidence_hash": row["evidence_hash"],
            }

        async def list_for_task(self, session, *, task_id, limit=50):
            rows = list(self._rows.get(str(task_id), []))
            rows.reverse()
            return rows[:limit]

        async def get_latest_for_task(self, session, *, task_id):
            rows = self._rows.get(str(task_id), [])
            return rows[-1] if rows else None

    in_memory_dao = _InMemoryAuditDAO()

    class _FakeSession:
        @asynccontextmanager
        async def begin(self):
            yield self

    @asynccontextmanager
    async def _session_factory():
        yield _FakeSession()

    monkeypatch.setattr(
        "seedcore.tools.manager.ToolManager._get_db_session_factory",
        lambda self: _session_factory,
    )
    monkeypatch.setattr(
        "seedcore.tools.manager.ToolManager._get_governance_audit_dao",
        lambda self: in_memory_dao,
    )


def _stub_token_signature() -> dict:
    return {"signer_type": "test", "signing_scheme": "stub"}
from seedcore.agents.base import BaseAgent
from seedcore.agents.roles import RoleProfile, RoleRegistry, Specialization
from seedcore.models.governed_mutation import (
    GovernedMutationContract,
    MutationEffectClass,
    MutationReplayMode,
)
from seedcore.models.task_payload import TaskPayload
from seedcore.tools.base import ToolBase
from seedcore.tools.manager import ToolError, ToolManager


class DummyReachyMotionTool(ToolBase):
    name = "reachy.motion"
    description = "Dummy actuation tool for tests"

    def governance_contract(self) -> GovernedMutationContract:
        return GovernedMutationContract(
            effect_class=MutationEffectClass.PHYSICAL_ACTUATION,
            requires_execution_token=True,
            requires_policy_receipt=False,
            requires_signed_receipt=True,
            snapshot_binding_required=True,
            replay_mode=MutationReplayMode.HASH_STABLE,
        )

    async def run(self, **kwargs):
        return {
            "status": "ok",
            "robot_state": {"head": kwargs.get("head", {})},
            "execution_token_id": (kwargs.get("execution_token") or {}).get("token_id"),
        }


class DummyUngovernedReachyTool(ToolBase):
    name = "reachy.motion"
    description = "Missing governance contract by design"

    async def run(self, **kwargs):
        return {"status": "ok"}


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


@pytest.mark.asyncio
async def test_tool_manager_rejects_mutating_tool_registration_without_contract():
    manager = ToolManager()
    with pytest.raises(ValueError) as exc:
        await manager.register_internal(DummyUngovernedReachyTool())
    assert "GovernedMutationContract" in str(exc.value)


@pytest.mark.asyncio
async def test_governed_mutation_rbac_provider_error_fails_closed():
    class _BrokenRBAC:
        async def allowed(self, agent_id, tool_name):
            raise RuntimeError("rbac backend unavailable")

    manager = ToolManager(rbac_provider=_BrokenRBAC())
    await manager.register_internal(DummyReachyMotionTool())

    governance = {
        "action_intent": {
            "intent_id": "intent-rbac-1",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "MOVE"},
            "resource": {"asset_id": "asset-1", "target_zone": "zone-a"},
        },
        "execution_token": {
            "token_id": "tok-rbac-1",
            "intent_id": "intent-rbac-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {
                "action_type": "MOVE",
                "target_zone": "zone-a",
                "asset_id": "asset-1",
                "principal_agent_id": "agent-1",
            },
        },
    }

    with pytest.raises(ToolError) as exc:
        await manager.execute(
            "reachy.motion",
            {"head": {"yaw": 0.2}, "_governance": governance},
            agent_id="agent-1",
        )
    assert "rbac_denied:provider_error" in str(exc.value)


@pytest.mark.asyncio
async def test_custody_mutation_receipt_chain_uses_persisted_previous_hash():
    manager = ToolManager()
    await manager.register_internal(DummyReachyMotionTool())

    governance = {
        "action_intent": {
            "intent_id": "intent-chain-1",
            "principal": {"agent_id": "agent-1"},
            "action": {"type": "RECORD"},
            "resource": {"asset_id": "asset-chain-1", "target_zone": "zone-a"},
        },
        "execution_token": {
            "token_id": "tok-chain-1",
            "intent_id": "intent-chain-1",
            "valid_until": "2099-01-01T00:00:00+00:00",
            "signature": _stub_token_signature(),
            "constraints": {
                "action_type": "RECORD",
                "asset_id": "asset-chain-1",
                "principal_agent_id": "agent-1",
            },
        },
    }

    first = await manager.execute(
        "custody.ledger.record",
        {
            "entry": {"task_id": "task-chain", "intent_ref": "governance://action-intent/intent-chain-1"},
            "_governance": governance,
        },
        agent_id="agent-1",
    )
    first_receipt = first["mutation_receipt"]
    assert first_receipt["receipt_counter"] == 1
    assert first_receipt.get("previous_receipt_hash") is None

    second = await manager.execute(
        "custody.ledger.record",
        {
            "entry": {"task_id": "task-chain", "intent_ref": "governance://action-intent/intent-chain-1"},
            "_governance": governance,
        },
        agent_id="agent-1",
    )
    second_receipt = second["mutation_receipt"]
    assert second_receipt["receipt_counter"] == 2
    assert second_receipt["previous_receipt_hash"] == first_receipt["payload_hash"]
