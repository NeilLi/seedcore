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
from seedcore.services.coordinator_service import TaskPayload


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
    huge_value = "x" * (cs.MAX_PROTO_PLAN_BYTES + 100)
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
    assert stored["size_bytes"] > cs.MAX_PROTO_PLAN_BYTES
    assert len(params["proto_plan"].encode("utf-8")) <= cs.MAX_PROTO_PLAN_BYTES


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

    coordinator.metrics = SimpleNamespace(record_proto_plan_upsert=MagicMock())
    coordinator.proto_plan_dao = SimpleNamespace(
        upsert=AsyncMock(side_effect=RuntimeError("boom"))
    )
    coordinator._resolve_session_factory = MagicMock(return_value=_session_factory)

    await coordinator._persist_proto_plan(
        repo=None,
        task_id="00000000-0000-0000-0000-000000000004",
        decision="planner",
        proto_plan={"tasks": []},
    )

    coordinator.proto_plan_dao.upsert.assert_awaited_once()
    coordinator.metrics.record_proto_plan_upsert.assert_called_once_with("err")


@pytest.mark.asyncio
async def test_dispatch_hgnn_partial_failures_reported():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    success_id = uuid.uuid4()
    failing_repo = SimpleNamespace(
        create_task_async=AsyncMock(side_effect=[success_id, RuntimeError("nope")])
    )
    coordinator._get_graph_sql_repository = MagicMock(return_value=failing_repo)
    coordinator.metrics = SimpleNamespace(record_dispatch=MagicMock())

    payload = TaskPayload(
        type="unit-test",
        params={"agent_id": "agent"},
        description="",
        domain="",
        drift_score=0.0,
        task_id="task-123",
    )
    proto_plan = {
        "tasks": [
            {"type": "graph_embed", "params": {"start_ids": [1]}},
            {"type": "graph_rag_query", "params": {"start_ids": [2]}},
        ]
    }

    metadata = await coordinator._dispatch_hgnn(payload, proto_plan)

    assert metadata == {
        "graph_dispatch": {
            "graph_tasks": [{"type": "graph_embed", "task_id": str(success_id)}]
        }
    }
    coordinator.metrics.record_dispatch.assert_called_with("hgnn", "err")
    assert failing_repo.create_task_async.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_hgnn_skips_unsupported_entries():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    repo = SimpleNamespace(create_task_async=AsyncMock(return_value=uuid.uuid4()))
    coordinator._get_graph_sql_repository = MagicMock(return_value=repo)
    coordinator.metrics = SimpleNamespace(record_dispatch=MagicMock())

    payload = TaskPayload(
        type="unit-test",
        params={},
        description="",
        domain="",
        drift_score=0.0,
        task_id="task-unsupported",
    )
    proto_plan = {
        "tasks": [
            {"type": "unsupported", "params": {}},
            {"type": "graph_embed", "params": {"start_ids": [42]}},
        ]
    }

    metadata = await coordinator._dispatch_hgnn(payload, proto_plan)

    assert len(metadata["graph_dispatch"]["graph_tasks"]) == 1
    coordinator.metrics.record_dispatch.assert_called_with("hgnn", "ok")
    assert repo.create_task_async.await_count == 1
