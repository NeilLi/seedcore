#!/usr/bin/env python3
"""
Unit tests for PKGManager (v2.6).

These tests validate:
- Lifecycle (start/stop/context manager)
- Snapshot loading & integrity validation
- Evaluator caching (LRU)
- Metadata & health reporting
- Redis hot-swap handling

Tests are written against the *current* PKGManager contract,
not legacy internal attributes.
"""

import os
import sys
import asyncio
import hashlib
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa

from seedcore.ops.pkg.manager import (
    PKGManager,
    PKGMode,
    initialize_global_pkg_manager,
    get_global_pkg_manager,
    PKG_REDIS_CHANNEL,
    PKG_UPDATE_AUTHZ_REFRESH_KIND,
    MAX_EVALUATOR_CACHE_SIZE,
)
from seedcore.ops.pkg.client import PKGClient
from seedcore.ops.pkg.dao import PKGSnapshotData


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def mock_pkg_client():
    client = AsyncMock(spec=PKGClient)
    client.get_taxonomy_bundle = AsyncMock(return_value={
        "reason_codes": [],
        "trust_gap_codes": [],
        "obligation_codes": [],
    })
    client.get_subtask_types = AsyncMock(return_value=[])
    client.upsert_snapshot_manifest = AsyncMock(return_value={})
    client.list_snapshot_artifacts = AsyncMock(return_value=[])
    client.store_snapshot_artifact_json = AsyncMock(
        return_value={"sha256": "a" * 64, "size_bytes": 12}
    )
    return client


@pytest.fixture
def mock_redis_client():
    redis = AsyncMock()

    pubsub = AsyncMock()

    async def empty_listen():
        if False:
            yield None

    pubsub.listen = MagicMock(return_value=empty_listen())
    redis.pubsub = AsyncMock(return_value=pubsub)
    return redis


def make_wasm_snapshot(version: str):
    wasm = b"valid_wasm_bytes"
    checksum = hashlib.sha256(wasm).hexdigest()
    return PKGSnapshotData(
        id=1,
        version=version,
        engine="wasm",
        wasm_artifact=wasm,
        checksum=checksum,
        rules=[],
    )


def make_native_snapshot(version: str):
    rules = [{"id": "r1", "priority": 1}]
    # Match manager's checksum generation logic: JSON with sort_keys=True
    rules_json = json.dumps(
        rules,
        sort_keys=True,  # Deterministic ordering
        default=str  # Handle non-serializable values
    ).encode('utf-8')
    checksum = hashlib.sha256(rules_json).hexdigest()

    return PKGSnapshotData(
        id=1,
        version=version,
        engine="native",
        wasm_artifact=None,
        checksum=checksum,
        rules=rules,
    )


@pytest.fixture
def manager(mock_pkg_client, mock_redis_client):
    return PKGManager(
        pkg_client=mock_pkg_client,
        redis_client=mock_redis_client,
    )


# ---------------------------------------------------------------------
# Lifecycle Tests
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_initial_state(manager):
    meta = manager.get_metadata()

    assert meta["active_version"] is None
    assert meta["cache_size"] == 0
    assert meta["status"]["healthy"] is False


@pytest.mark.asyncio
async def test_manager_start_with_snapshot(manager, mock_pkg_client):
    snap = make_wasm_snapshot("rules@1.0.0")
    mock_pkg_client.get_active_snapshot.return_value = snap

    manager._redis_client = None  # disable listener

    await manager.start()

    evaluator = manager.get_active_evaluator()
    assert evaluator is not None
    assert evaluator.version == "rules@1.0.0"

    meta = manager.get_metadata()
    assert meta["active_version"] == "rules@1.0.0"
    assert meta["cache_size"] == 1
    assert meta["status"]["healthy"] is True

    await manager.stop()


@pytest.mark.asyncio
async def test_manager_start_no_snapshot(manager, mock_pkg_client):
    mock_pkg_client.get_active_snapshot.return_value = None

    manager._redis_client = None
    await manager.start()

    assert manager.get_active_evaluator() is None
    assert manager.get_metadata()["status"]["healthy"] is False

    await manager.stop()


@pytest.mark.asyncio
async def test_async_context_manager(mock_pkg_client):
    mock_pkg_client.get_active_snapshot.return_value = None

    async with PKGManager(mock_pkg_client, redis_client=None) as mgr:
        assert mgr.get_metadata()["active_version"] is None

    # exited cleanly


# ---------------------------------------------------------------------
# Evaluator Cache & Access
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_active_evaluator_none(manager):
    assert manager.get_active_evaluator() is None


@pytest.mark.asyncio
async def test_get_evaluator_by_version(manager):
    snap = make_wasm_snapshot("rules@1.2.3")
    await manager._load_and_activate_snapshot(snap, source="test")

    ev = manager.get_evaluator_by_version("rules@1.2.3")
    assert ev is not None
    assert ev.version == "rules@1.2.3"


@pytest.mark.asyncio
async def test_get_evaluator_by_version_not_found(manager):
    assert manager.get_evaluator_by_version("missing") is None


@pytest.mark.asyncio
async def test_lru_cache_eviction(manager):
    for i in range(MAX_EVALUATOR_CACHE_SIZE + 2):
        snap = make_native_snapshot(f"rules@{i}.0.0")
        await manager._load_and_activate_snapshot(snap, source="test")
        await asyncio.sleep(0.01)

    meta = manager.get_metadata()
    assert meta["cache_size"] <= MAX_EVALUATOR_CACHE_SIZE


# ---------------------------------------------------------------------
# Snapshot Integrity Validation
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_validate_snapshot_wasm_missing_artifact(manager):
    snap = PKGSnapshotData(
        id=1,
        version="bad",
        engine="wasm",
        wasm_artifact=None,
        checksum="x" * 64,
        rules=[],
    )

    ok, err = await manager._validate_snapshot_integrity(snap)
    assert ok is False
    assert "missing artifact" in err.lower()


@pytest.mark.asyncio
async def test_validate_snapshot_native_ok(manager):
    snap = make_native_snapshot("rules@native-ok")

    ok, err = await manager._validate_snapshot_integrity(snap)
    assert ok is True
    assert err is None


@pytest.mark.asyncio
async def test_validate_task_facts_prefers_active_request_schema_bundle(manager):
    manager._active_contract_artifacts = {
        "request_schema_bundle": {
            "request_shape": {
                "required_task_fact_keys": ["tags", "signals", "context", "extra"],
                "injected_task_fact_keys": ["semantic_context"],
            }
        }
    }

    assert manager._validate_task_facts(
        {
            "tags": ["urgent"],
            "signals": {"load": 0.5},
            "context": {"domain": "warehouse"},
            "extra": {"note": "allowed by active bundle"},
        }
    ) is None

    err = manager._validate_task_facts(
        {
            "tags": ["urgent"],
            "signals": {"load": 0.5},
            "context": {"domain": "warehouse"},
            "unexpected": True,
        }
    )
    assert err is not None
    assert "unexpected" in err


# ---------------------------------------------------------------------
# Redis Hot Swap
# ---------------------------------------------------------------------
@pytest.mark.asyncio
async def test_redis_listener_handles_activate(
    manager, mock_pkg_client, mock_redis_client
):
    """Test Redis listener processes an activate message correctly."""

    snap = make_wasm_snapshot("rules@redis")

    async def listen_once():
        yield {
            "type": "message",
            "data": b"activate:rules@redis",
        }
        # allow loop to continue briefly (triggers reconnect behavior)
        await asyncio.sleep(0.01)

    # pubsub() is synchronous in real redis clients
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = listen_once

    mock_redis_client.pubsub = MagicMock(return_value=pubsub)
    mock_pkg_client.get_snapshot_by_version = AsyncMock(return_value=snap)

    task = asyncio.create_task(manager._redis_listen_loop())

    # give the listener time to process the message
    await asyncio.sleep(0.05)

    # stop the listener
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # ✅ Core behavioral assertion (the only one that matters)
    mock_pkg_client.get_snapshot_by_version.assert_called_with("rules@redis")


@pytest.mark.asyncio
async def test_parse_pkg_update_message_supports_legacy_and_json(manager):
    legacy = manager._parse_pkg_update_message("activate:rules@2.0.0")
    authz = manager._parse_pkg_update_message("authz_graph_refresh")
    structured = manager._parse_pkg_update_message(
        json.dumps({"kind": "activate", "version": "rules@json"})
    )

    assert legacy == {"kind": "activate", "version": "rules@2.0.0"}
    assert authz == {"kind": PKG_UPDATE_AUTHZ_REFRESH_KIND, "version": None}
    assert structured == {"kind": "activate", "version": "rules@json"}


@pytest.mark.asyncio
async def test_refresh_active_authz_graph_uses_active_snapshot(manager):
    snap = make_native_snapshot("rules@1.0.0")
    compiled = type(
        "CompiledAuthzIndex",
        (),
        {
            "snapshot_hash": "snapshot-refresh-1",
            "compiled_at": "2026-04-03T00:00:00+00:00",
            "restricted_transfer_ready": False,
            "decision_graph_snapshot": None,
        },
    )()
    manager.authz_graph.activate_snapshot = AsyncMock(return_value=compiled)
    await manager._load_and_activate_snapshot(snap, source="test")

    result = await manager.refresh_active_authz_graph()

    assert result["success"] is True
    manager.authz_graph.activate_snapshot.assert_called()


@pytest.mark.asyncio
async def test_persist_compiled_authz_artifacts_stores_phase1_artifacts(manager, mock_pkg_client):
    class _DecisionGraphSnapshot:
        def to_dict(self):
            return {
                "snapshot_hash": "snapshot-hash-xyz",
                "hot_path_workflow": "restricted_custody_transfer",
                "trust_gap_taxonomy": ["stale_telemetry"],
            }

    class _CompiledAuthzIndex:
        decision_graph_snapshot = _DecisionGraphSnapshot()
        compiled_at = "2026-04-03T00:00:00+00:00"
        snapshot_hash = "snapshot-hash-xyz"
        restricted_transfer_ready = True

    mock_pkg_client.get_taxonomy_bundle.return_value = {
        "reason_codes": [{"code": "reason_a"}],
        "trust_gap_codes": [{"code": "stale_telemetry"}],
        "obligation_codes": [{"code": "attach_telemetry_proof"}],
    }
    mock_pkg_client.get_subtask_types.return_value = [
        {
            "id": "cap-1",
            "name": "reachy_actuator",
            "snapshot_id": 17,
            "default_params": {"executor": {"specialization": "reachy"}},
        }
    ]

    await manager._persist_compiled_authz_artifacts(
        snapshot_id=17,
        snapshot_version="rules@phase1",
        compiled_authz_index=_CompiledAuthzIndex(),
    )

    assert mock_pkg_client.store_snapshot_artifact_json.await_count == 4
    artifact_types = [
        call.kwargs.get("artifact_type")
        for call in mock_pkg_client.store_snapshot_artifact_json.await_args_list
    ]
    assert artifact_types == [
        "decision_graph_snapshot",
        "request_schema_bundle",
        "taxonomy_bundle",
        "activation_manifest",
    ]
    assert mock_pkg_client.upsert_snapshot_manifest.await_count == 1

    request_schema_payload = mock_pkg_client.store_snapshot_artifact_json.await_args_list[1].kwargs["payload"]
    taxonomy_payload = mock_pkg_client.store_snapshot_artifact_json.await_args_list[2].kwargs["payload"]
    activation_payload = mock_pkg_client.store_snapshot_artifact_json.await_args_list[3].kwargs["payload"]

    assert request_schema_payload["request_shape"]["required_task_fact_keys"] == ["context", "signals", "tags"]
    assert request_schema_payload["capability_count"] == 1
    assert request_schema_payload["capabilities"][0]["name"] == "reachy_actuator"
    assert taxonomy_payload["reason_codes"] == [{"code": "reason_a"}]
    assert taxonomy_payload["trust_gap_codes"] == [{"code": "stale_telemetry"}]
    assert activation_payload["shadow_only"] is True


@pytest.mark.asyncio
async def test_redis_listener_handles_authz_graph_refresh_message(
    manager, mock_redis_client
):
    manager.refresh_active_authz_graph = AsyncMock(return_value={"success": True})

    async def listen_once():
        yield {
            "type": "message",
            "data": b"authz_graph_refresh",
        }
        await asyncio.sleep(0.01)

    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.listen = listen_once

    mock_redis_client.pubsub = MagicMock(return_value=pubsub)

    task = asyncio.create_task(manager._redis_listen_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert manager.refresh_active_authz_graph.call_count >= 1


@pytest.mark.asyncio
async def test_activate_snapshot_version_publishes_update_event(manager, mock_pkg_client, mock_redis_client):
    snap = make_wasm_snapshot("rules@activate")
    mock_pkg_client.get_snapshot_by_version.return_value = snap
    mock_pkg_client.activate_snapshot.return_value = {
        "id": snap.id,
        "version": snap.version,
        "env": "prod",
        "is_active": True,
    }
    mock_pkg_client.upsert_deployment.return_value = {
        "snapshot_id": snap.id,
        "target": "router",
        "region": "global",
        "percent": 100,
    }
    mock_redis_client.publish = AsyncMock(return_value=1)

    result = await manager.activate_snapshot_version(
        version=snap.version,
        actor="ops",
        reason="test",
        target="router",
        region="global",
        edge_targets=["edge:door"],
    )

    assert result["success"] is True
    assert result["version"] == "rules@activate"
    assert result["publish"]["published"] is True
    assert mock_pkg_client.activate_snapshot.await_count == 1


# ---------------------------------------------------------------------
# RCT Phase-2 activation hardening
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rct_phase2_enforce_rolls_back_when_not_ready(mock_pkg_client, monkeypatch):
    monkeypatch.setenv("SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE", "1")
    mock_pkg_client.get_taxonomy_bundle = AsyncMock(
        return_value={
            "reason_codes": [{"code": "r"}],
            "trust_gap_codes": [{"code": "t"}],
            "obligation_codes": [{"code": "o"}],
        }
    )
    mock_pkg_client.list_snapshot_artifacts = AsyncMock(
        return_value=[
            {"artifact_type": t}
            for t in (
                "decision_graph_snapshot",
                "request_schema_bundle",
                "taxonomy_bundle",
                "activation_manifest",
            )
        ]
    )
    mock_pkg_client.get_snapshot_manifest = AsyncMock(return_value={"snapshot_id": 1})

    class _Dgs:
        def to_dict(self):
            return {
                "snapshot_hash": "sh",
                "hot_path_workflow": "restricted_custody_transfer",
                "trust_gap_taxonomy": ["tg"],
            }

    class _Compiled:
        decision_graph_snapshot = _Dgs()
        compiled_at = "2026-04-03T00:00:00Z"
        snapshot_hash = "sh"
        restricted_transfer_ready = False

    mgr = PKGManager(mock_pkg_client, redis_client=None, mode=PKGMode.CONTROL)
    mgr.authz_graph.activate_snapshot = AsyncMock(return_value=_Compiled())

    snap = make_wasm_snapshot("rules@phase2-fail")
    await mgr._load_and_activate_snapshot(snap, source="test")

    assert mgr.get_active_evaluator() is None
    assert mgr.get_metadata()["status"]["healthy"] is False


@pytest.mark.asyncio
async def test_rct_phase2_enforce_passes_when_ready(mock_pkg_client, monkeypatch):
    monkeypatch.setenv("SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE", "1")
    mock_pkg_client.get_taxonomy_bundle = AsyncMock(
        return_value={
            "reason_codes": [{"code": "r"}],
            "trust_gap_codes": [{"code": "t"}],
            "obligation_codes": [{"code": "o"}],
        }
    )
    mock_pkg_client.list_snapshot_artifacts = AsyncMock(
        return_value=[
            {"artifact_type": t}
            for t in (
                "decision_graph_snapshot",
                "request_schema_bundle",
                "taxonomy_bundle",
                "activation_manifest",
            )
        ]
    )
    mock_pkg_client.get_snapshot_manifest = AsyncMock(return_value={"snapshot_id": 1})

    class _Dgs:
        def to_dict(self):
            return {
                "snapshot_hash": "sh",
                "hot_path_workflow": "restricted_custody_transfer",
                "trust_gap_taxonomy": ["tg"],
            }

    class _Compiled:
        decision_graph_snapshot = _Dgs()
        compiled_at = "2026-04-03T00:00:00Z"
        snapshot_hash = "sh"
        restricted_transfer_ready = True

    mgr = PKGManager(mock_pkg_client, redis_client=None, mode=PKGMode.CONTROL)
    mgr.authz_graph.activate_snapshot = AsyncMock(return_value=_Compiled())

    snap = make_wasm_snapshot("rules@phase2-ok")
    await mgr._load_and_activate_snapshot(snap, source="test")

    assert mgr.get_active_evaluator() is not None
    assert mgr.get_active_evaluator().version == snap.version
    assert mgr.get_metadata()["status"]["healthy"] is True


@pytest.mark.asyncio
async def test_rct_preflight_skips_authz_when_manifest_missing(mock_pkg_client, monkeypatch):
    monkeypatch.setenv("SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT", "1")
    monkeypatch.delenv("SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE", raising=False)
    mock_pkg_client.get_snapshot_manifest = AsyncMock(return_value=None)

    mgr = PKGManager(mock_pkg_client, redis_client=None, mode=PKGMode.CONTROL)
    mgr.authz_graph.activate_snapshot = AsyncMock()

    snap = make_wasm_snapshot("rules@preflight-fail")
    await mgr._load_and_activate_snapshot(snap, source="test")

    assert mgr.get_active_evaluator() is None
    mgr.authz_graph.activate_snapshot.assert_not_awaited()


# ---------------------------------------------------------------------
# Stop Logic
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_stop_cancels_redis_task(manager):
    async def dummy():
        await asyncio.sleep(10)

    manager._redis_task = asyncio.create_task(dummy())
    await manager.stop()

    assert manager._redis_task.cancelled() or manager._redis_task.done()


# ---------------------------------------------------------------------
# Global Manager
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_global_manager_lifecycle():
    import seedcore.ops.pkg.manager as mod
    mod._global_manager = None

    client = AsyncMock(spec=PKGClient)
    client.get_active_snapshot.return_value = None

    mgr = await initialize_global_pkg_manager(client, redis_client=None)
    assert mgr is get_global_pkg_manager()


# ---------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------

def test_constants():
    assert PKG_REDIS_CHANNEL == "pkg_updates"
    assert PKG_UPDATE_AUTHZ_REFRESH_KIND == "authz_graph_refresh"
    assert isinstance(MAX_EVALUATOR_CACHE_SIZE, int)
    assert MAX_EVALUATOR_CACHE_SIZE > 0
