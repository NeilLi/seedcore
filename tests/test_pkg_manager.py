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
    initialize_global_pkg_manager,
    get_global_pkg_manager,
    PKG_REDIS_CHANNEL,
    MAX_EVALUATOR_CACHE_SIZE,
)
from seedcore.ops.pkg.client import PKGClient
from seedcore.ops.pkg.dao import PKGSnapshotData


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def mock_pkg_client():
    return AsyncMock(spec=PKGClient)


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
    assert isinstance(MAX_EVALUATOR_CACHE_SIZE, int)
    assert MAX_EVALUATOR_CACHE_SIZE > 0
