from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.api.routers.pkg_router as pkg_router


@pytest.mark.asyncio
async def test_pkg_authz_graph_status_reports_uninitialized_manager(monkeypatch):
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: None)

    result = await pkg_router.pkg_authz_graph_status()

    assert result["available"] is False
    assert result["authz_graph_ready"] is False
    assert result["manager_exists"] is False


@pytest.mark.asyncio
async def test_pkg_authz_graph_status_reports_active_graph(monkeypatch):
    manager = SimpleNamespace(
        get_metadata=lambda: {
            "authz_graph": {
                "healthy": True,
                "active_snapshot_id": 7,
                "active_snapshot_version": "rules@7.0.0",
                "snapshot_hash": "hash-7",
                "compiled_at": "2026-03-27T10:00:00+00:00",
                "hot_path_workflow": "restricted_custody_transfer",
                "restricted_transfer_ready": True,
                "trust_gap_taxonomy": ["stale_telemetry"],
                "graph_nodes_count": 12,
                "graph_edges_count": 18,
                "decision_graph_nodes_count": 8,
                "decision_graph_edges_count": 12,
                "enrichment_graph_nodes_count": 4,
                "enrichment_graph_edges_count": 6,
                "error": None,
            }
        },
        get_active_compiled_authz_index=lambda: object(),
    )
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: manager)

    result = await pkg_router.pkg_authz_graph_status()

    assert result["available"] is True
    assert result["authz_graph_ready"] is True
    assert result["active_snapshot_version"] == "rules@7.0.0"
    assert result["snapshot_hash"] == "hash-7"
    assert result["restricted_transfer_ready"] is True
    assert result["graph_edges_count"] == 18


@pytest.mark.asyncio
async def test_pkg_authz_graph_refresh_calls_manager(monkeypatch):
    manager = SimpleNamespace(
        refresh_active_authz_graph=AsyncMock(
            return_value={
                "success": True,
                "version": "rules@7.0.0",
                "snapshot_id": 7,
            }
        )
    )
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: manager)

    result = await pkg_router.pkg_authz_graph_refresh()

    assert result["success"] is True
    manager.refresh_active_authz_graph.assert_awaited_once()


@pytest.mark.asyncio
async def test_pkg_authz_graph_refresh_raises_when_manager_missing(monkeypatch):
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: None)

    with pytest.raises(HTTPException) as exc:
        await pkg_router.pkg_authz_graph_refresh()

    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_pkg_status_includes_authz_graph_summary(monkeypatch):
    evaluator = SimpleNamespace(version="rules@7.0.0", engine_type="native", snapshot_id=7)
    manager = SimpleNamespace(
        get_active_evaluator=lambda: evaluator,
        get_metadata=lambda: {
            "mode": "control",
            "status": {"healthy": True, "error": None},
            "active_version": "rules@7.0.0",
            "cached_versions": ["rules@7.0.0"],
            "cortex_enabled": True,
            "authz_graph": {
                "healthy": True,
                "active_snapshot_id": 7,
                "active_snapshot_version": "rules@7.0.0",
                "snapshot_hash": "hash-7",
                "compiled_at": "2026-03-27T10:00:00+00:00",
                "hot_path_workflow": "restricted_custody_transfer",
                "restricted_transfer_ready": True,
                "trust_gap_taxonomy": ["stale_telemetry"],
                "graph_nodes_count": 12,
                "graph_edges_count": 18,
                "decision_graph_nodes_count": 8,
                "decision_graph_edges_count": 12,
                "enrichment_graph_nodes_count": 4,
                "enrichment_graph_edges_count": 6,
                "error": None,
            },
        },
        get_active_contract_artifacts=lambda: {
            "request_schema_bundle": {"artifact_type": "request_schema_bundle"},
            "taxonomy_bundle": {"artifact_type": "taxonomy_bundle"},
        },
    )
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: manager)

    async def _boom():
        raise RuntimeError("skip artifact diagnostics")

    monkeypatch.setattr(pkg_router, "get_async_pg_session_factory", _boom)

    result = await pkg_router.pkg_status()

    assert result["available"] is True
    assert result["authz_graph_ready"] is True
    assert result["authz_graph"]["active_snapshot_version"] == "rules@7.0.0"
    assert result["authz_graph"]["snapshot_hash"] == "hash-7"
    assert result["active_contract_artifacts"]["request_schema_bundle"]["artifact_type"] == "request_schema_bundle"


@pytest.mark.asyncio
async def test_pkg_activate_snapshot_calls_manager(monkeypatch):
    manager = SimpleNamespace(
        activate_snapshot_version=AsyncMock(
            return_value={
                "success": True,
                "version": "rules@8.0.0",
                "snapshot_id": 8,
            }
        )
    )
    monkeypatch.setattr(pkg_router, "get_global_pkg_manager", lambda: manager)

    payload = pkg_router.PKGActivateSnapshotRequest(actor="ops", reason="test-activation")
    result = await pkg_router.pkg_activate_snapshot("rules@8.0.0", payload)

    assert result["success"] is True
    manager.activate_snapshot_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_pkg_ota_heartbeat_reports_outdated_compliance(monkeypatch):
    mock_client = SimpleNamespace(
        resolve_desired_snapshot_for_device=AsyncMock(
            return_value={
                "snapshot_id": 9,
                "snapshot_version": "rules@9.0.0",
                "target": "edge:door",
                "region": "global",
                "percent": 100,
                "source": "deployment_lane",
            }
        ),
        update_device_heartbeat=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(pkg_router, "_resolve_pkg_client", AsyncMock(return_value=mock_client))

    payload = pkg_router.PKGOTAHeartbeatRequest(
        device_id="door-1",
        device_type="door",
        region="global",
        snapshot_id=7,
        version="rules@7.0.0",
    )
    result = await pkg_router.pkg_ota_heartbeat(payload)

    assert result["ok"] is True
    assert result["compliance"] == "outdated"
    assert result["desired"]["snapshot_version"] == "rules@9.0.0"
    mock_client.update_device_heartbeat.assert_awaited_once()
