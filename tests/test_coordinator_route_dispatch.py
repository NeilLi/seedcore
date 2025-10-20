import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from seedcore.services import coordinator_service as cs
from seedcore.services.coordinator_service import TaskPayload


def _metrics_stub():
    return SimpleNamespace(
        track_metrics=MagicMock(),
        record_route_latency=MagicMock(),
        record_dispatch=MagicMock(),
    )


def _make_payload(task_id: str = None) -> TaskPayload:
    return TaskPayload(
        type="unit-test",
        params={"agent_id": "agent-1"},
        description="testing",
        domain="qa",
        drift_score=0.0,
        task_id=task_id or uuid.uuid4().hex,
    )


@pytest.mark.asyncio
async def test_route_and_execute_fast_path_skips_dispatch():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()
    coordinator._resolve_session_factory = MagicMock(return_value=None)
    coordinator.metrics = _metrics_stub()
    coordinator.core = SimpleNamespace(
        route_and_execute=AsyncMock(
            return_value={
                "success": True,
                "payload": {
                    "metadata": {
                        "decision": "fast",
                        "proto_plan": {},
                    }
                },
            }
        )
    )
    coordinator.graph_task_repo = None
    coordinator._persist_proto_plan = AsyncMock()
    planner_mock = AsyncMock()
    coordinator.planner_client = SimpleNamespace(execute_plan=planner_mock)
    coordinator._get_graph_sql_repository = MagicMock(return_value=None)

    payload = _make_payload()
    res = await coordinator.route_and_execute(payload.model_dump())

    assert res["success"] is True
    coordinator._persist_proto_plan.assert_awaited_once()
    assert planner_mock.await_count == 0
    assert coordinator._get_graph_sql_repository.call_count == 0


@pytest.mark.asyncio
async def test_route_and_execute_dispatches_planner():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()
    coordinator._resolve_session_factory = MagicMock(return_value=None)
    coordinator.metrics = _metrics_stub()
    planner_response = {"plan_steps": ["do_something"]}
    planner_mock = AsyncMock(return_value=planner_response)
    coordinator.planner_client = SimpleNamespace(execute_plan=planner_mock)
    coordinator._persist_proto_plan = AsyncMock()
    coordinator._get_graph_sql_repository = MagicMock(return_value=None)

    coordinator.core = SimpleNamespace(
        route_and_execute=AsyncMock(
            return_value={
                "success": True,
                "payload": {
                    "metadata": {
                        "decision": "planner",
                        "proto_plan": {"tasks": [{"type": "analysis"}]},
                    }
                },
            }
        )
    )

    payload = _make_payload()
    result = await coordinator.route_and_execute(payload.model_dump())

    planner_mock.assert_awaited_once()
    assert result["payload"]["metadata"]["planner_response"] == planner_response
    coordinator._persist_proto_plan.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_and_execute_dispatches_hgnn_graph_jobs():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()
    coordinator._resolve_session_factory = MagicMock(return_value=None)
    coordinator.metrics = _metrics_stub()
    coordinator._persist_proto_plan = AsyncMock()
    coordinator.planner_client = None

    created_uuid = uuid.uuid4()
    graph_repo = SimpleNamespace(create_task_async=AsyncMock(return_value=created_uuid))
    coordinator._get_graph_sql_repository = MagicMock(return_value=graph_repo)

    coordinator.core = SimpleNamespace(
        route_and_execute=AsyncMock(
            return_value={
                "success": True,
                "payload": {
                    "metadata": {
                        "decision": "hgnn",
                        "proto_plan": {
                            "tasks": [
                                {"type": "graph_embed", "params": {"start_ids": [101]}},
                                {"type": "graph_rag_query", "params": {"start_ids": [102]}},
                            ]
                        },
                    }
                },
            }
        )
    )

    payload = _make_payload()
    res = await coordinator.route_and_execute(payload.model_dump())

    assert graph_repo.create_task_async.await_count == 2
    dispatch_meta = res["payload"]["metadata"].get("graph_dispatch")
    assert dispatch_meta is not None
    task_ids = {item["task_id"] for item in dispatch_meta["graph_tasks"]}
    assert task_ids == {str(created_uuid)}
    coordinator._persist_proto_plan.assert_awaited_once()
