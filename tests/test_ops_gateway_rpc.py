from __future__ import annotations

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

import pytest

from entrypoints import ops_entrypoint as ops
from seedcore.serve import energy_client as ec
from seedcore.serve import state_client as sc


class _RemoteMethod:
    def __init__(self, fn):
        self._fn = fn

    async def remote(self, *args, **kwargs):
        return self._fn(*args, **kwargs)


class _Handle:
    def __init__(self, mapping):
        for key, fn in mapping.items():
            setattr(self, key, _RemoteMethod(fn))


def test_ops_gateway_routes_cover_state_and_energy_paths():
    paths = {route.path for route in ops.ops_app.routes}

    assert "/state/system-metrics" in paths
    assert "/state/unified-state" in paths
    assert "/state/agent-snapshots" in paths
    assert "/state/config/w_mode" in paths
    assert "/state/health" in paths
    assert "/state/status" in paths
    assert "/energy/metrics" in paths
    assert "/energy/compute-from-state" in paths
    assert "/energy/compute" in paths
    assert "/energy/optimize" in paths
    assert "/energy/health" in paths
    assert "/energy/status" in paths
    assert "/energy/meta" in paths
    assert "/energy/log" in paths
    assert "/energy/logs" in paths


def test_ops_gateway_backend_instantiation_unwraps_ingress_class():
    class Backend:
        def __init__(self, value):
            self.value = value

    class Wrapper:
        __wrapped__ = Backend

    class DeploymentLike:
        func_or_class = Wrapper

    instance = ops._instantiate_deployment_backend(DeploymentLike(), "ok")

    assert isinstance(instance, Backend)
    assert instance.value == "ok"


@pytest.mark.asyncio
async def test_state_service_client_prefers_ops_rpc(monkeypatch):
    handle = _Handle(
        {
            "rpc_state_system_metrics": lambda: {"source": "rpc"},
            "rpc_state_status": lambda: {"status": "ready"},
        }
    )
    monkeypatch.setattr(sc, "get_ops_gateway_handle", lambda: handle)

    client = sc.StateServiceClient(base_url="http://example.test")

    async def _no_http(*args, **kwargs):
        raise AssertionError("HTTP fallback should not be used")

    monkeypatch.setattr(client, "get", _no_http)

    assert await client.get_system_metrics() == {"source": "rpc"}
    assert await client.get_status() == {"status": "ready"}
    await client.close()


@pytest.mark.asyncio
async def test_energy_service_client_prefers_ops_rpc(monkeypatch):
    handle = _Handle(
        {
            "rpc_energy_metrics": lambda: {"source": "rpc"},
            "rpc_energy_meta": lambda: {"beta_mem": 0.1},
            "rpc_energy_log": lambda payload: {"logged": payload["metric"]},
            "rpc_energy_logs": lambda limit: {"returned_count": limit},
        }
    )
    monkeypatch.setattr(ec, "get_ops_gateway_handle", lambda: handle)

    client = ec.EnergyServiceClient(base_url="http://example.test")

    async def _no_http(*args, **kwargs):
        raise AssertionError("HTTP fallback should not be used")

    monkeypatch.setattr(client, "get", _no_http)
    monkeypatch.setattr(client, "post", _no_http)

    assert await client.get_metrics() == {"source": "rpc"}
    assert await client.get_meta() == {"beta_mem": 0.1}
    assert await client.log_event({"metric": "router_hit"}) == {"logged": "router_hit"}
    assert await client.get_logs(limit=5) == {"returned_count": 5}
    await client.close()


@pytest.mark.asyncio
async def test_ops_embedded_state_energy_startup_runs_once(monkeypatch):
    calls = []

    async def _state_startup():
        calls.append("state")

    async def _energy_startup():
        calls.append("energy")

    async def _state_metrics(_response=None):
        return {"success": True, "metrics": {}}

    async def _state_health():
        return {"status": "healthy"}

    monkeypatch.setattr(ops, "state_startup_event", _state_startup)
    monkeypatch.setattr(ops, "energy_startup_event", _energy_startup)
    monkeypatch.setattr(ops, "state_get_system_metrics", _state_metrics)
    monkeypatch.setattr(ops, "state_health", _state_health)
    monkeypatch.setattr(ops, "_ops_embedded_services_started", False)
    monkeypatch.setattr(ops, "_ops_embedded_services_lock", None)
    configured = {}
    monkeypatch.setattr(
        ops,
        "configure_embedded_state_provider",
        lambda **kwargs: configured.update(kwargs),
    )

    await ops._ensure_embedded_ops_dependencies_started()
    await ops._ensure_embedded_ops_dependencies_started()

    assert calls == ["state", "energy"]
    assert callable(configured["metrics_fetch"])
    assert callable(configured["health_fetch"])
