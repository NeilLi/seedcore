# Import mock dependencies BEFORE any other imports
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import json
import uuid
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seedcore.services import coordinator_service as cs
from seedcore.coordinator.dao import MAX_PROTO_PLAN_BYTES
from seedcore.models import TaskPayload
from seedcore.models.source_registration import TrackingEventSourceKind, TrackingEventType


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return _FakeTransaction(self)


class _FakeTransaction:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_factory():
    return _FakeSession()


@pytest.mark.asyncio
async def test_task_proto_plan_dao_upsert_updates_sorted_json():
    dao = cs.TaskProtoPlanDAO()
    session = AsyncMock()

    result = await dao.upsert(
        session,
        task_id="00000000-0000-0000-0000-000000000001",
        route="fast",
        proto_plan={"b": 2, "a": 1},
    )
    assert result == {"truncated": False}
    stmt, params = session.execute.await_args.args
    assert json.loads(params["proto_plan"]) == {"a": 1, "b": 2}

    session.execute.reset_mock()
    result = await dao.upsert(
        session,
        task_id="00000000-0000-0000-0000-000000000001",
        route="planner",
        proto_plan={"b": 3, "a": 1},
    )
    assert result == {"truncated": False}
    stmt, params = session.execute.await_args.args
    assert params["route"] == "planner"
    assert json.loads(params["proto_plan"]) == {"a": 1, "b": 3}


@pytest.mark.asyncio
async def test_task_proto_plan_dao_truncates_large_payload():
    dao = cs.TaskProtoPlanDAO()
    session = AsyncMock()
    huge_value = "x" * (MAX_PROTO_PLAN_BYTES + 100)
    proto_plan: Dict[str, Any] = {"tasks": ["seed"], "notes": huge_value}

    result = await dao.upsert(
        session,
        task_id="00000000-0000-0000-0000-000000000002",
        route="hgnn",
        proto_plan=proto_plan,
    )
    assert result == {"truncated": True}
    stmt, params = session.execute.await_args.args
    stored = json.loads(params["proto_plan"])
    assert stored["_truncated"] is True
    assert stored["size_bytes"] > MAX_PROTO_PLAN_BYTES
    assert len(params["proto_plan"].encode("utf-8")) <= MAX_PROTO_PLAN_BYTES


@pytest.mark.asyncio
async def test_task_outbox_dao_enqueue_dedupes():
    dao = cs.TaskOutboxDAO()
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[SimpleNamespace(rowcount=1), SimpleNamespace(rowcount=0)]
    )

    first = await dao.enqueue_embed_task(
        session,
        task_id="00000000-0000-0000-0000-000000000003",
        reason="router",
        dedupe_key="dedupe",
    )
    second = await dao.enqueue_embed_task(
        session,
        task_id="00000000-0000-0000-0000-000000000003",
        reason="router",
        dedupe_key="dedupe",
    )

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_persist_proto_plan_records_error_on_failure():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator.proto_plan_dao = SimpleNamespace(
        upsert=AsyncMock(side_effect=RuntimeError("boom"))
    )
    coordinator._session_factory = _session_factory

    # _persist_proto_plan signature: (self, repo, tid, kind, plan)
    await coordinator._persist_proto_plan(
        repo=None,
        tid="00000000-0000-0000-0000-000000000004",
        kind="planner",
        plan={"tasks": []},
    )

    coordinator.proto_plan_dao.upsert.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_governance_audit_emits_break_glass_policy_tracking_event():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._session_factory = _session_factory
    coordinator.governance_audit_dao = SimpleNamespace(
        append_record=AsyncMock(
            return_value={
                "entry_id": "audit-1",
                "recorded_at": "2026-03-23T04:16:27+00:00",
                "input_hash": "hash-1",
                "evidence_hash": None,
            }
        )
    )

    governance = {
        "action_intent": {
            "intent_id": "intent-1",
            "principal": {"agent_id": "agent-7", "role_profile": "SYSTEM_ADMIN"},
            "action": {"type": "MUTATE", "operation": "MUTATE"},
            "resource": {
                "asset_id": "asset-9",
                "resource_uri": "seedcore://zones/vault-a/assets/asset-9",
                "target_zone": "vault-a",
            },
        },
        "policy_decision": {
            "allowed": True,
            "policy_snapshot": "snapshot:1",
            "disposition": "allow",
            "reason": "allowed",
            "break_glass": {
                "present": True,
                "validated": True,
                "used": True,
                "override_applied": True,
                "required": True,
                "reason": "operator approved emergency release",
                "principal_id": "agent-7",
                "token_issued_at": "2026-03-23T04:16:20+00:00",
                "token_expires_at": "2026-03-23T04:16:27+00:00",
                "outcome": "break_glass_override",
            },
        },
        "policy_case": {},
        "policy_receipt": {},
    }

    with patch.object(cs, "record_tracking_event", new=AsyncMock()) as mock_record_event:
        await coordinator._record_governance_audit(
            task_id="00000000-0000-0000-0000-0000000000a1",
            governance=governance,
            record_type="policy_decision",
        )

    coordinator.governance_audit_dao.append_record.assert_awaited_once()
    mock_record_event.assert_awaited_once()
    _, kwargs = mock_record_event.await_args
    assert kwargs["event_type"] == TrackingEventType.POLICY_DECISION_RECORDED
    assert kwargs["source_kind"] == TrackingEventSourceKind.POLICY_MONITOR
    assert kwargs["subject_type"] == "principal"
    assert kwargs["subject_id"] == "agent-7"
    assert kwargs["payload"]["break_glass"]["used"] is True
    assert kwargs["payload"]["break_glass"]["override_applied"] is True
    assert kwargs["payload"]["governance_audit"]["entry_id"] == "audit-1"


@pytest.mark.asyncio
async def test_record_governance_audit_emits_break_glass_incident_for_invalid_attempt():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._session_factory = _session_factory
    coordinator.governance_audit_dao = SimpleNamespace(
        append_record=AsyncMock(
            return_value={
                "entry_id": "audit-2",
                "recorded_at": "2026-03-23T04:16:27+00:00",
                "input_hash": "hash-2",
                "evidence_hash": None,
            }
        )
    )

    governance = {
        "action_intent": {
            "intent_id": "intent-2",
            "principal": {"agent_id": "agent-9", "role_profile": "SYSTEM_ADMIN"},
            "action": {"type": "MUTATE", "operation": "MUTATE"},
            "resource": {"asset_id": "asset-11", "target_zone": "vault-b"},
        },
        "policy_decision": {
            "allowed": False,
            "policy_snapshot": "snapshot:1",
            "disposition": "deny",
            "deny_code": "invalid_break_glass_token",
            "reason": "Break-glass token verification failed.",
            "break_glass": {
                "present": True,
                "validated": False,
                "used": False,
                "override_applied": False,
                "required": False,
                "reason": "attempted emergency override",
                "principal_id": "agent-9",
                "outcome": "verification_failed",
            },
        },
        "policy_case": {},
        "policy_receipt": {},
    }

    with patch.object(cs, "record_tracking_event", new=AsyncMock()) as mock_record_event:
        await coordinator._record_governance_audit(
            task_id="00000000-0000-0000-0000-0000000000a2",
            governance=governance,
            record_type="policy_decision",
        )

    mock_record_event.assert_awaited_once()
    _, kwargs = mock_record_event.await_args
    assert kwargs["event_type"] == TrackingEventType.RUNTIME_INCIDENT_DETECTED
    assert kwargs["payload"]["decision"]["deny_code"] == "invalid_break_glass_token"
    assert kwargs["payload"]["break_glass"]["validated"] is False


# Note: _dispatch_hgnn method no longer exists in Coordinator.
# Graph task dispatch is now handled through persist_and_register_dependencies
# in coordinator.core.plan, which is tested in test_coordinator_core_plan.py
