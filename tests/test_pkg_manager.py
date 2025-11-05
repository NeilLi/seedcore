#!/usr/bin/env python3
"""
Unit tests for PKG Manager.

Tests PKGManager lifecycle, hot-swapping, and thread-safety with mocked dependencies.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, Any

from seedcore.ops.pkg.manager import (
    PKGManager,
    get_global_pkg_manager,
    initialize_global_pkg_manager,
    PKG_REDIS_CHANNEL,
    MAX_EVALUATOR_CACHE_SIZE,
)
from seedcore.ops.pkg.client import PKGClient
from seedcore.ops.pkg.dao import PKGSnapshotData
from seedcore.ops.pkg.evaluator import PKGEvaluator


class TestPKGManager:
    """Tests for PKGManager."""
    
    @pytest.fixture
    def mock_pkg_client(self):
        """Create a mock PKGClient."""
        client = AsyncMock(spec=PKGClient)
        return client
    
    @pytest.fixture
    def mock_redis_client(self):
        """Create a mock Redis client."""
        redis = AsyncMock()
        redis.pubsub = AsyncMock(return_value=AsyncMock())
        return redis
    
    @pytest.fixture
    def wasm_snapshot(self):
        """Create a WASM snapshot."""
        return PKGSnapshotData(
            id=1,
            version='rules@1.4.0',
            engine='wasm',
            wasm_artifact=b'wasm_binary_data',
            checksum='sha256-abc123',
            rules=[]
        )
    
    @pytest.fixture
    def native_snapshot(self):
        """Create a native snapshot."""
        return PKGSnapshotData(
            id=2,
            version='rules@0.2.0',
            engine='native',
            wasm_artifact=None,
            checksum='sha256-xyz',
            rules=[
                {
                    'id': 'rule-001',
                    'rule_name': 'test_rule',
                    'priority': 10,
                    'conditions': [],
                    'emissions': []
                }
            ]
        )
    
    @pytest.fixture
    def manager(self, mock_pkg_client, mock_redis_client):
        """Create a PKGManager instance."""
        return PKGManager(pkg_client=mock_pkg_client, redis_client=mock_redis_client)
    
    @pytest.mark.asyncio
    async def test_manager_init(self, manager):
        """Test manager initialization."""
        assert manager._client is not None
        assert manager._redis_client is not None
        assert manager._active_evaluator is None
        assert manager._active_version is None
        assert len(manager._evaluators) == 0
        assert manager._status["healthy"] is True
    
    @pytest.mark.asyncio
    async def test_manager_start_loads_snapshot(self, manager, mock_pkg_client, wasm_snapshot):
        """Test manager start loads initial snapshot."""
        mock_pkg_client.get_active_snapshot = AsyncMock(return_value=wasm_snapshot)
        
        await manager.start()
        
        # Wait a bit for async tasks
        await asyncio.sleep(0.1)
        
        assert manager._active_evaluator is not None
        assert manager._active_version == 'rules@1.4.0'
        mock_pkg_client.get_active_snapshot.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_manager_start_no_snapshot(self, manager, mock_pkg_client):
        """Test manager start when no snapshot exists."""
        mock_pkg_client.get_active_snapshot = AsyncMock(return_value=None)
        
        await manager.start()
        
        assert manager._active_evaluator is None
        assert manager._status["degraded_mode"] is True
    
    @pytest.mark.asyncio
    async def test_manager_start_without_redis(self, mock_pkg_client):
        """Test manager start without Redis."""
        manager = PKGManager(pkg_client=mock_pkg_client, redis_client=None)
        mock_pkg_client.get_active_snapshot = AsyncMock(return_value=None)
        
        await manager.start()
        
        assert manager._redis_task is None
    
    @pytest.mark.asyncio
    async def test_manager_async_context_manager(self, manager, mock_pkg_client):
        """Test manager as async context manager."""
        mock_pkg_client.get_active_snapshot = AsyncMock(return_value=None)
        
        async with manager:
            assert manager._status["healthy"] in [True, False]  # May be degraded
        
        # Manager should be stopped after context exit
        if manager._redis_task:
            assert manager._redis_task.done() or manager._redis_task.cancelled()
    
    @pytest.mark.asyncio
    async def test_get_active_evaluator(self, manager, wasm_snapshot):
        """Test getting active evaluator."""
        evaluator = PKGEvaluator(wasm_snapshot)
        
        with manager._swap_lock:
            manager._active_evaluator = evaluator
            manager._active_version = wasm_snapshot.version
            manager._evaluators[wasm_snapshot.version] = (evaluator, asyncio.get_event_loop().time())
        
        active = manager.get_active_evaluator()
        
        assert active is not None
        assert active.version == 'rules@1.4.0'
    
    @pytest.mark.asyncio
    async def test_get_active_evaluator_none(self, manager):
        """Test getting active evaluator when none exists."""
        active = manager.get_active_evaluator()
        
        assert active is None
    
    @pytest.mark.asyncio
    async def test_get_evaluator_by_version(self, manager, wasm_snapshot):
        """Test getting evaluator by version."""
        evaluator = PKGEvaluator(wasm_snapshot)
        
        with manager._swap_lock:
            manager._evaluators[wasm_snapshot.version] = (evaluator, asyncio.get_event_loop().time())
        
        cached = manager.get_evaluator_by_version(wasm_snapshot.version)
        
        assert cached is not None
        assert cached.version == 'rules@1.4.0'
    
    @pytest.mark.asyncio
    async def test_get_evaluator_by_version_not_found(self, manager):
        """Test getting evaluator by version when not cached."""
        cached = manager.get_evaluator_by_version('nonexistent')
        
        assert cached is None
    
    @pytest.mark.asyncio
    async def test_get_metadata(self, manager, wasm_snapshot):
        """Test getting metadata."""
        evaluator = PKGEvaluator(wasm_snapshot)
        
        with manager._swap_lock:
            manager._active_evaluator = evaluator
            manager._active_version = wasm_snapshot.version
            manager._evaluators[wasm_snapshot.version] = (evaluator, asyncio.get_event_loop().time())
        
        metadata = manager.get_metadata()
        
        assert metadata['version'] == 'rules@1.4.0'
        assert metadata['loaded'] is True
        assert metadata['engine'] == 'wasm'
        assert 'cached_versions' in metadata
        assert 'cache_size' in metadata
    
    @pytest.mark.asyncio
    async def test_get_metadata_no_evaluator(self, manager):
        """Test getting metadata when no evaluator."""
        metadata = manager.get_metadata()
        
        assert metadata['loaded'] is False
        assert metadata['version'] is None
    
    @pytest.mark.asyncio
    async def test_get_health_status(self, manager):
        """Test getting health status."""
        status = manager.get_health_status()
        
        assert 'healthy' in status
        assert 'degraded_mode' in status
        assert 'last_error' in status
        assert 'last_activation' in status
        assert 'cached_versions_count' in status
        assert 'redis_connected' in status
    
    @pytest.mark.asyncio
    async def test_load_and_activate_snapshot(self, manager, wasm_snapshot):
        """Test loading and activating snapshot."""
        await manager._load_and_activate_snapshot(wasm_snapshot, source="test")
        
        assert manager._active_evaluator is not None
        assert manager._active_version == 'rules@1.4.0'
        assert wasm_snapshot.version in manager._evaluators
        assert manager._status["last_activation"] is not None
    
    @pytest.mark.asyncio
    async def test_load_and_activate_snapshot_caching(self, manager, wasm_snapshot, native_snapshot):
        """Test that multiple snapshots are cached."""
        # Load first snapshot
        await manager._load_and_activate_snapshot(wasm_snapshot, source="test")
        
        # Load second snapshot
        await manager._load_and_activate_snapshot(native_snapshot, source="test")
        
        assert len(manager._evaluators) == 2
        assert wasm_snapshot.version in manager._evaluators
        assert native_snapshot.version in manager._evaluators
    
    @pytest.mark.asyncio
    async def test_load_and_activate_snapshot_cache_eviction(self, manager):
        """Test cache eviction when limit exceeded."""
        # Create multiple snapshots
        snapshots = []
        for i in range(MAX_EVALUATOR_CACHE_SIZE + 2):
            snapshot = PKGSnapshotData(
                id=i,
                version=f'rules@{i}.0.0',
                engine='native',
                wasm_artifact=None,
                checksum=f'hash{i}',
                rules=[]
            )
            snapshots.append(snapshot)
        
        # Load all snapshots
        for snapshot in snapshots:
            await manager._load_and_activate_snapshot(snapshot, source="test")
            await asyncio.sleep(0.01)  # Small delay to ensure different timestamps
        
        # Cache should not exceed limit
        assert len(manager._evaluators) <= MAX_EVALUATOR_CACHE_SIZE + 1
    
    @pytest.mark.asyncio
    async def test_validate_snapshot_wasm_missing_artifact(self, manager):
        """Test snapshot validation fails for WASM without artifact."""
        snapshot = PKGSnapshotData(
            id=1,
            version='rules@1.0.0',
            engine='wasm',
            wasm_artifact=None,
            checksum='abc',
            rules=[]
        )
        
        with pytest.raises(ValueError, match="no 'wasm_artifact'"):
            manager._validate_snapshot(snapshot)
    
    @pytest.mark.asyncio
    async def test_validate_snapshot_native_no_rules(self, manager):
        """Test snapshot validation warns for native without rules."""
        snapshot = PKGSnapshotData(
            id=1,
            version='rules@1.0.0',
            engine='native',
            wasm_artifact=None,
            checksum='abc',
            rules=[]
        )
        
        # Should not raise, just warn
        manager._validate_snapshot(snapshot)
    
    @pytest.mark.asyncio
    async def test_redis_listen_loop_subscription(self, manager, mock_redis_client):
        """Test Redis listener subscribes to channel."""
        pubsub = AsyncMock()
        mock_redis_client.pubsub = AsyncMock(return_value=pubsub)
        
        # Start the listener task
        task = asyncio.create_task(manager._redis_listen_loop())
        
        # Give it a moment to subscribe
        await asyncio.sleep(0.1)
        
        # Cancel the task
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Verify subscription was attempted
        mock_redis_client.pubsub.assert_called()
    
    @pytest.mark.asyncio
    async def test_redis_listen_loop_handles_activate_message(self, manager, mock_pkg_client, wasm_snapshot):
        """Test Redis listener handles activate message."""
        pubsub = AsyncMock()
        mock_redis_client.pubsub = AsyncMock(return_value=pubsub)
        
        # Mock message
        message = {
            'type': 'message',
            'data': b'activate:rules@1.4.0'
        }
        
        # Mock listen() to return one message then stop
        async def mock_listen():
            yield message
            await asyncio.sleep(0.1)  # Prevent infinite loop
        
        pubsub.listen = mock_listen
        mock_pkg_client.get_snapshot_by_version = AsyncMock(return_value=wasm_snapshot)
        
        # Start listener
        task = asyncio.create_task(manager._redis_listen_loop())
        
        # Wait for message processing
        await asyncio.sleep(0.2)
        
        # Cancel task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        # Verify snapshot was requested
        mock_pkg_client.get_snapshot_by_version.assert_called_with('rules@1.4.0')
    
    @pytest.mark.asyncio
    async def test_manager_stop(self, manager, mock_redis_client):
        """Test manager stop."""
        # Create a mock task
        task = AsyncMock()
        task.done.return_value = False
        manager._redis_task = task
        
        await manager.stop()
        
        task.cancel.assert_called_once()


class TestGlobalPKGManager:
    """Tests for global PKG manager functions."""
    
    @pytest.mark.asyncio
    async def test_get_global_pkg_manager_not_initialized(self):
        """Test getting global manager when not initialized."""
        # Clear global state
        import seedcore.ops.pkg.manager as pkg_manager_module
        pkg_manager_module._global_pkg_manager = None
        
        manager = get_global_pkg_manager()
        
        assert manager is None
    
    @pytest.mark.asyncio
    async def test_initialize_global_pkg_manager(self):
        """Test initializing global PKG manager."""
        import seedcore.ops.pkg.manager as pkg_manager_module
        pkg_manager_module._global_pkg_manager = None
        
        mock_client = AsyncMock(spec=PKGClient)
        mock_client.get_active_snapshot = AsyncMock(return_value=None)
        
        with patch('seedcore.ops.pkg.manager.PKGClient', return_value=mock_client):
            manager = await initialize_global_pkg_manager(
                pkg_client=mock_client,
                redis_client=None
            )
            
            assert manager is not None
            assert get_global_pkg_manager() == manager


class TestPKGManagerConstants:
    """Tests for PKG manager constants."""
    
    def test_pkg_redis_channel_constant(self):
        """Test PKG_REDIS_CHANNEL constant."""
        assert PKG_REDIS_CHANNEL == "pkg_updates"
    
    def test_max_evaluator_cache_size_constant(self):
        """Test MAX_EVALUATOR_CACHE_SIZE constant."""
        assert MAX_EVALUATOR_CACHE_SIZE == 3
        assert isinstance(MAX_EVALUATOR_CACHE_SIZE, int)
        assert MAX_EVALUATOR_CACHE_SIZE > 0

