from __future__ import annotations

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

import pytest

from seedcore.models.cognitive import DecisionKind
from seedcore.models.task_payload import TaskPayload
from seedcore.serve import coordinator_client as kc
from seedcore.serve import cognitive_client as cc
from seedcore.serve import organism_client as oc


class _RemoteMethod:
    def __init__(self, fn):
        self._fn = fn

    async def remote(self, *args, **kwargs):
        return self._fn(*args, **kwargs)


class _Handle:
    def __init__(self, mapping):
        for key, fn in mapping.items():
            setattr(self, key, _RemoteMethod(fn))


@pytest.mark.asyncio
async def test_cognitive_service_client_prefers_rpc(monkeypatch):
    seen = {}

    def _execute(task_payload):
        seen["execute"] = task_payload
        return {"success": True, "result": {"source": "rpc"}}

    handle = _Handle(
        {
            "execute_cognitive_task": _execute,
            "advisory": lambda payload: {"success": True, "advisory": {"task_id": payload.task_id}},
            "health": lambda: {"status": "healthy"},
            "info": lambda: {"service": "cognitive"},
        }
    )
    monkeypatch.setattr(cc, "get_serve_deployment_handle", lambda *a, **k: handle)

    client = cc.CognitiveServiceClient(base_url="http://example.test")

    async def _no_http(*args, **kwargs):
        raise AssertionError("HTTP fallback should not be used")

    monkeypatch.setattr(client, "get", _no_http)
    monkeypatch.setattr(client, "post", _no_http)

    task = TaskPayload(task_id="t-1", type="chat", description="demo", params={})
    result = await client.execute_async(
        agent_id="agent-1",
        cog_type="chat",
        decision_kind=DecisionKind.COGNITIVE,
        task=task,
    )
    assert result["result"]["source"] == "rpc"
    assert seen["execute"].task_id == "t-1"
    assert (await client.health_check())["status"] == "healthy"
    assert (await client.get_service_info())["service"] == "cognitive"
    advisory = await client.advisory_async(task=task)
    assert advisory["advisory"]["task_id"] == "t-1"
    await client.close()


@pytest.mark.asyncio
async def test_organism_service_client_prefers_rpc(monkeypatch):
    seen = {}

    def _route_only(request):
        seen["route_only"] = request
        return {"agent_id": "a-1", "organ_id": "o-1", "reason": "rpc", "is_high_stakes": False}

    def _route_and_execute(request):
        seen["route_and_execute"] = request
        return {"success": True, "result": {"source": "rpc"}}

    handle = _Handle(
        {
            "route_only": _route_only,
            "route_and_execute": _route_and_execute,
            "health": lambda: {"status": "healthy"},
            "get_organism_status": lambda: {"success": True},
            "get_organism_summary": lambda: {"success": True, "summary": {}},
            "rpc_initialize_organism": lambda: {"success": True, "status": "initializing"},
        }
    )
    monkeypatch.setattr(oc, "get_serve_deployment_handle", lambda *a, **k: handle)

    client = oc.OrganismServiceClient(base_url="http://example.test")

    async def _no_http(*args, **kwargs):
        raise AssertionError("HTTP fallback should not be used")

    monkeypatch.setattr(client, "get", _no_http)
    monkeypatch.setattr(client, "post", _no_http)

    task = {"task_id": "x", "type": "chat", "description": "demo", "params": {}}
    route = await client.route_only(task)
    assert route["reason"] == "rpc"
    assert seen["route_only"].task["task_id"] == "x"

    result = await client.route_and_execute(task)
    assert result["result"]["source"] == "rpc"
    assert seen["route_and_execute"].task["task_id"] == "x"

    assert (await client.health())["status"] == "healthy"
    assert (await client.get_organism_status())["success"] is True
    assert (await client.get_organism_summary())["success"] is True
    assert (await client.initialize_organism())["status"] == "initializing"
    await client.close()


@pytest.mark.asyncio
async def test_coordinator_service_client_prefers_rpc(monkeypatch):
    handle = _Handle(
        {
            "route_and_execute": lambda payload: {"success": True, "result": {"source": "rpc", "task_id": payload["task_id"]}},
            "generate_advisory": lambda payload: {"advisory": {"task_id": payload["task_id"]}},
            "health": lambda: {"status": "healthy"},
            "get_metrics": lambda: {"requests": 1},
            "get_predicate_status": lambda: {"enabled": True},
            "get_predicate_config": lambda: {"mode": "strict"},
        }
    )
    monkeypatch.setattr(kc, "get_serve_deployment_handle", lambda *a, **k: handle)

    client = kc.CoordinatorServiceClient(base_url="http://example.test")

    async def _no_http(*args, **kwargs):
        raise AssertionError("HTTP fallback should not be used")

    monkeypatch.setattr(client, "get", _no_http)
    monkeypatch.setattr(client, "post", _no_http)

    task = {"task_id": "coord-1", "type": "general_query", "description": "demo", "params": {}}
    result = await client.route_and_execute(task)
    assert result["result"]["source"] == "rpc"
    assert result["result"]["task_id"] == "coord-1"
    assert (await client.advisory(task))["advisory"]["task_id"] == "coord-1"
    assert (await client.get_health_status())["status"] == "healthy"
    assert (await client.get_metrics())["requests"] == 1
    assert (await client.get_predicate_status())["enabled"] is True
    assert (await client.get_predicate_config())["mode"] == "strict"
    await client.close()
