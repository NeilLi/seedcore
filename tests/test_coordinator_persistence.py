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


# Note: _dispatch_hgnn method no longer exists in Coordinator.
# Graph task dispatch is now handled through persist_and_register_dependencies
# in coordinator.core.plan, which is tested in test_coordinator_core_plan.py
