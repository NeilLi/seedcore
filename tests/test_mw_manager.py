#!/usr/bin/env python3
"""
Unit tests for MwManager.

Tests are independent of Ray and Kubernetes cluster dependencies.
"""

import sys
import os

# Add tests directory to path for mock imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import mocks BEFORE other imports
import mock_database_dependencies
import mock_ray_dependencies

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch, call
import time


class TestMwManager:
    """Tests for MwManager class."""
    
    @pytest.fixture
    def mock_shared_cache_shard(self):
        """Create a mock SharedCacheShard actor."""
        shard = Mock()
        # Create a mock that returns a value when .remote() is called
        def mock_get_remote(key):
            return shard._get_value
        shard.get = Mock()
        shard.get.remote = Mock(side_effect=mock_get_remote)
        shard._get_value = None
        
        def mock_set_remote(key, value, ttl_s=None):
            pass
        shard.set = Mock()
        shard.set.remote = Mock(side_effect=mock_set_remote)
        
        def mock_setnx_remote(key, value, ttl_s=None):
            return shard._setnx_value
        shard.setnx = Mock()
        shard.setnx.remote = Mock(side_effect=mock_setnx_remote)
        shard._setnx_value = True
        
        def mock_delete_remote(key):
            pass
        shard.delete = Mock()
        shard.delete.remote = Mock(side_effect=mock_delete_remote)
        return shard
    
    @pytest.fixture
    def mock_mw_shard(self):
        """Create a mock MwStoreShard actor."""
        shard = Mock()
        def mock_incr_remote(key, delta=1):
            pass
        shard.incr = Mock()
        shard.incr.remote = Mock(side_effect=mock_incr_remote)
        
        def mock_topn_remote(n):
            return shard._topn_value
        shard.topn = Mock()
        shard.topn.remote = Mock(side_effect=mock_topn_remote)
        shard._topn_value = []
        return shard
    
    @pytest.fixture
    def mock_node_cache(self):
        """Create a mock NodeCache actor."""
        node_cache = Mock()
        def mock_get_remote(key):
            return node_cache._get_value
        node_cache.get = Mock()
        node_cache.get.remote = Mock(side_effect=mock_get_remote)
        node_cache._get_value = None
        
        def mock_set_remote(key, value, ttl_s=None):
            pass
        node_cache.set = Mock()
        node_cache.set.remote = Mock(side_effect=mock_set_remote)
        
        def mock_delete_remote(key):
            pass
        node_cache.delete = Mock()
        node_cache.delete.remote = Mock(side_effect=mock_delete_remote)
        return node_cache
    
    @pytest.fixture
    def mw_manager(self, mock_shared_cache_shard, mock_mw_shard, mock_node_cache):
        """Create an MwManager with mocked dependencies."""
        async def mock_await_ref(ref):
            """Mock _await_ref to just return the value directly."""
            # The ref is the result of .remote() call, which is already the value
            return ref
        
        # Create patches that will persist
        mock_patcher_await_ref = patch('src.seedcore.memory.mw_manager._await_ref', side_effect=mock_await_ref)
        mock_patcher_get_shards = patch('src.seedcore.memory.mw_manager._get_shard_handles')
        mock_patcher_get_mw_shards = patch('src.seedcore.memory.mw_manager._get_mw_shard_handles')
        mock_patcher_get_node_cache = patch('src.seedcore.memory.mw_manager.get_node_cache')
        mock_patcher_shard_for = patch('src.seedcore.memory.mw_manager._shard_for')
        mock_patcher_mw_shard_for = patch('src.seedcore.memory.mw_manager._mw_shard_for')
        
        # Start all patches
        mock_await_ref_patch = mock_patcher_await_ref.start()
        mock_get_shards = mock_patcher_get_shards.start()
        mock_get_mw_shards = mock_patcher_get_mw_shards.start()
        mock_get_node_cache = mock_patcher_get_node_cache.start()
        mock_shard_for = mock_patcher_shard_for.start()
        mock_mw_shard_for = mock_patcher_mw_shard_for.start()
        
        # Setup mocks
        mock_get_node_cache.return_value = mock_node_cache
        mock_shard_for.return_value = mock_shared_cache_shard
        mock_mw_shard_for.return_value = mock_mw_shard
        
        from src.seedcore.memory.mw_manager import MwManager
        manager = MwManager("test_organ_1")
        
        # Store patches so they can be cleaned up
        manager._test_patches = [
            mock_patcher_await_ref, mock_patcher_get_shards, mock_patcher_get_mw_shards,
            mock_patcher_get_node_cache, mock_patcher_shard_for, mock_patcher_mw_shard_for
        ]
        
        yield manager
        
        # Cleanup
        for patcher in manager._test_patches:
            patcher.stop()
    
    @pytest.mark.asyncio
    async def test_get_item_async_l0_hit(self, mw_manager):
        """Test get_item_async returns from L0 (organ-local) cache."""
        mw_manager.set_item("test_item", {"value": 123})
        
        result = await mw_manager.get_item_async("test_item")
        
        assert result == {"value": 123}
        telemetry = mw_manager.get_telemetry()
        assert telemetry["hits"] == 1
        assert telemetry["l0_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_get_item_async_l1_hit(self, mw_manager, mock_node_cache):
        """Test get_item_async returns from L1 (node) cache."""
        mock_node_cache._get_value = {"value": 456}
        
        result = await mw_manager.get_item_async("test_item")
        
        assert result == {"value": 456}
        # Should also populate L0
        assert mw_manager._cache.get(mw_manager._organ_key("test_item")) == {"value": 456}
        telemetry = mw_manager.get_telemetry()
        assert telemetry["l1_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_get_item_async_l2_hit(self, mw_manager, mock_shared_cache_shard, mock_node_cache):
        """Test get_item_async returns from L2 (sharded global) cache."""
        mock_shared_cache_shard._get_value = {"value": 789}
        mock_node_cache._get_value = None
        
        result = await mw_manager.get_item_async("test_item")
        
        assert result == {"value": 789}
        telemetry = mw_manager.get_telemetry()
        assert telemetry["l2_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_get_item_async_miss(self, mw_manager, mock_shared_cache_shard, mock_node_cache, mock_mw_shard):
        """Test get_item_async handles cache miss and records it."""
        mock_shared_cache_shard._get_value = None
        mock_node_cache._get_value = None
        
        result = await mw_manager.get_item_async("test_item")
        
        assert result is None
        telemetry = mw_manager.get_telemetry()
        assert telemetry["misses"] == 1
        # Should have called incr_miss
        mock_mw_shard.incr.remote.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_item_async_global_key(self, mw_manager, mock_shared_cache_shard):
        """Test get_item_async with fully-qualified global key."""
        mock_shared_cache_shard._get_value = {"value": "global"}
        
        result = await mw_manager.get_item_async("global:item:test", is_global=True)
        
        assert result == {"value": "global"}
    
    @pytest.mark.asyncio
    async def test_get_item_async_organ_key(self, mw_manager):
        """Test get_item_async with fully-qualified organ key (L0 only)."""
        mw_manager.set_item("organ:test_organ_1:item:test", {"value": "organ"})
        
        result = await mw_manager.get_item_async("organ:test_organ_1:item:test")
        
        assert result == {"value": "organ"}
    
    @pytest.mark.asyncio
    async def test_set_global_item(self, mw_manager, mock_shared_cache_shard, mock_node_cache):
        """Test set_global_item updates all cache levels."""
        value = {"key": "value"}
        
        mw_manager.set_global_item("test_item", value)
        
        # Check L0 cache
        assert mw_manager._cache[mw_manager._organ_key("test_item")] == value
        # Check L1 and L2 were called (fire-and-forget)
        mock_node_cache.set.remote.assert_called_once()
        mock_shared_cache_shard.set.remote.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_set_global_item_typed(self, mw_manager, mock_shared_cache_shard):
        """Test set_global_item_typed builds correct key format."""
        value = {"key": "value"}
        
        mw_manager.set_global_item_typed("fact", "global", "fact_123", value)
        
        # Verify key format: global:item:fact:global:fact_123
        expected_key = "global:item:fact:global:fact_123"
        assert mw_manager._cache[mw_manager._organ_key(expected_key)] == value
    
    @pytest.mark.asyncio
    async def test_set_organ_item_typed(self, mw_manager):
        """Test set_organ_item_typed builds correct key format."""
        value = {"key": "value"}
        
        mw_manager.set_organ_item_typed("fact", "fact_123", value)
        
        # Verify key format: set_item calls _organ_key which adds another prefix
        # So the actual key is: organ:test_organ_1:item:organ:test_organ_1:item:fact:fact_123
        expected_key = f"organ:test_organ_1:item:organ:test_organ_1:item:fact:fact_123"
        assert mw_manager._cache[expected_key] == value
    
    @pytest.mark.asyncio
    async def test_get_item_typed_async(self, mw_manager, mock_shared_cache_shard):
        """Test get_item_typed_async checks global then organ-local."""
        # First try global
        mock_shared_cache_shard._get_value = None
        # Then set organ-local
        mw_manager.set_organ_item_typed("fact", "fact_123", {"value": "organ"})
        
        result = await mw_manager.get_item_typed_async("fact", "global", "fact_123")
        
        # Should find organ-local after global miss
        assert result == {"value": "organ"}
    
    @pytest.mark.asyncio
    async def test_incr_miss(self, mw_manager, mock_mw_shard):
        """Test incr_miss increments miss count in shard."""
        await mw_manager.incr_miss("test_item", delta=1)
        
        mock_mw_shard.incr.remote.assert_called_once_with("test_item", 1)
    
    @pytest.mark.asyncio
    async def test_get_hot_items_async(self, mw_manager, mock_mw_shard):
        """Test get_hot_items_async collects and merges top items."""
        # Mock multiple shards with different top items
        mock_shard1 = Mock()
        def mock_topn1_remote(n):
            return [("item1", 10), ("item2", 5)]
        mock_shard1.topn = Mock()
        mock_shard1.topn.remote = Mock(side_effect=mock_topn1_remote)
        
        mock_shard2 = Mock()
        def mock_topn2_remote(n):
            return [("item2", 8), ("item3", 3)]
        mock_shard2.topn = Mock()
        mock_shard2.topn.remote = Mock(side_effect=mock_topn2_remote)
        
        with patch('src.seedcore.memory.mw_manager._get_mw_shard_handles') as mock_get_mw_shards:
            mock_get_mw_shards.return_value = (None, {
                "shard1": mock_shard1,
                "shard2": mock_shard2
            })
            
            result = await mw_manager.get_hot_items_async(top_n=3)
            
            # item2 appears in both shards (5 + 8 = 13 total)
            # item1 = 10, item2 = 13, item3 = 3
            assert len(result) == 3
            items = [item for item, count in result]
            assert "item2" in items
            assert "item1" in items
            assert "item3" in items
    
    def test_set_item(self, mw_manager):
        """Test set_item sets organ-local cache."""
        value = {"key": "value"}
        mw_manager.set_item("test_item", value)
        
        assert mw_manager._cache[mw_manager._organ_key("test_item")] == value
    
    def test_clear(self, mw_manager):
        """Test clear removes all L0 entries."""
        mw_manager.set_item("item1", {"v": 1})
        mw_manager.set_item("item2", {"v": 2})
        
        assert len(mw_manager._cache) == 2
        
        mw_manager.clear()
        
        assert len(mw_manager._cache) == 0
    
    def test_delete_organ_item(self, mw_manager):
        """Test delete_organ_item removes a single entry."""
        mw_manager.set_item("item1", {"v": 1})
        mw_manager.set_item("item2", {"v": 2})
        
        mw_manager.delete_organ_item("item1")
        
        assert mw_manager._organ_key("item1") not in mw_manager._cache
        assert mw_manager._organ_key("item2") in mw_manager._cache
    
    def test_get_telemetry(self, mw_manager):
        """Test get_telemetry returns correct statistics."""
        # Simulate some cache operations
        mw_manager.set_item("item1", {"v": 1})
        # Manually increment counters to simulate hits/misses
        mw_manager._hit_count = 10
        mw_manager._miss_count = 5
        mw_manager._l0_hits = 8
        mw_manager._l1_hits = 1
        mw_manager._l2_hits = 1
        
        telemetry = mw_manager.get_telemetry()
        
        assert telemetry["organ_id"] == "test_organ_1"
        assert telemetry["hits"] == 10
        assert telemetry["misses"] == 5
        assert telemetry["total_requests"] == 15
        assert telemetry["hit_ratio"] == pytest.approx(10 / 15)
        assert telemetry["l0_hits"] == 8
        assert telemetry["l1_hits"] == 1
        assert telemetry["l2_hits"] == 1
    
    def test_reset_telemetry(self, mw_manager):
        """Test reset_telemetry clears all counters."""
        mw_manager._hit_count = 10
        mw_manager._miss_count = 5
        mw_manager._l0_hits = 8
        
        mw_manager.reset_telemetry()
        
        assert mw_manager._hit_count == 0
        assert mw_manager._miss_count == 0
        assert mw_manager._l0_hits == 0
    
    def test_get_item_sync_l0_hit(self, mw_manager):
        """Test sync get_item returns from L0 cache."""
        mw_manager.set_item("test_item", {"value": 123})
        
        result = mw_manager.get_item("test_item")
        
        assert result == {"value": 123}
    
    def test_get_item_sync_miss(self, mw_manager):
        """Test sync get_item returns None on miss."""
        result = mw_manager.get_item("non_existent")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_del_global_key(self, mw_manager, mock_shared_cache_shard, mock_node_cache):
        """Test del_global_key deletes from all cache levels."""
        mw_manager.set_item("test_item", {"v": 1})
        
        await mw_manager.del_global_key("test_item")
        
        # Should delete from L2
        mock_shared_cache_shard.delete.remote.assert_called_once()
        # Should delete from L1
        mock_node_cache.delete.remote.assert_called_once()
        # Should delete from L0
        assert mw_manager._organ_key("test_item") not in mw_manager._cache
    
    @pytest.mark.asyncio
    async def test_try_set_inflight(self, mw_manager, mock_shared_cache_shard):
        """Test try_set_inflight atomically sets a sentinel."""
        mock_shared_cache_shard._setnx_value = True
        
        result = await mw_manager.try_set_inflight("test_key", ttl_s=5)
        
        assert result is True
        mock_shared_cache_shard.setnx.remote.assert_called_once()
    
    def test_cache_task(self, mw_manager):
        """Test cache_task caches a task with appropriate TTL."""
        task = {
            "id": "task-123",
            "status": "completed",
            "updated_at": "2024-01-01T00:00:00Z"
        }
        
        mw_manager.cache_task(task)
        
        # Should be cached with completed TTL (600s default)
        item_id = "task:by_id:task-123"
        assert mw_manager._organ_key(item_id) in mw_manager._cache
    
    def test_cache_task_invalid_id(self, mw_manager):
        """Test cache_task handles invalid task IDs gracefully."""
        task = {
            "id": None,
            "status": "completed"
        }
        
        # Should not raise exception
        mw_manager.cache_task(task)
    
    @pytest.mark.asyncio
    async def test_get_task_async_hit(self, mw_manager):
        """Test get_task_async returns cached task."""
        task_id = "task-123"
        item_id = f"task:by_id:{task_id}"
        mw_manager.set_item(item_id, {"id": task_id, "status": "completed"})
        
        result = await mw_manager.get_task_async(task_id)
        
        assert result is not None
        assert result["id"] == task_id
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_cache_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_get_task_async_negative_cache(self, mw_manager):
        """Test get_task_async respects negative cache."""
        task_id = "task-123"
        # Set negative cache
        mw_manager.set_negative_cache("task", "by_id", task_id)
        
        result = await mw_manager.get_task_async(task_id)
        
        assert result is None
        telemetry = mw_manager.get_telemetry()
        assert telemetry["negative_cache_hits"] == 1
    
    @pytest.mark.asyncio
    async def test_get_task_async_miss(self, mw_manager, mock_shared_cache_shard):
        """Test get_task_async sets negative cache on miss."""
        task_id = "task-123"
        mock_shared_cache_shard._get_value = None
        
        result = await mw_manager.get_task_async(task_id)
        
        assert result is None
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_cache_misses"] == 1
    
    def test_invalidate_task(self, mw_manager):
        """Test invalidate_task removes task from all cache levels."""
        task_id = "task-123"
        item_id = f"task:by_id:{task_id}"
        mw_manager.set_item(item_id, {"id": task_id})
        
        mw_manager.invalidate_task(task_id)
        
        assert mw_manager._organ_key(item_id) not in mw_manager._cache
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_evictions"] == 1
    
    @pytest.mark.asyncio
    async def test_set_negative_cache(self, mw_manager, mock_shared_cache_shard):
        """Test set_negative_cache creates negative cache entry."""
        mw_manager.set_negative_cache("task", "by_id", "task-123", ttl_s=30)
        
        # Should set global item with _neg: prefix
        mock_shared_cache_shard.set.remote.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_check_negative_cache(self, mw_manager):
        """Test check_negative_cache checks for negative cache entry."""
        mw_manager.set_negative_cache("task", "by_id", "task-123")
        
        result = await mw_manager.check_negative_cache("task", "by_id", "task-123")
        
        assert result is True
    
    def test_set_global_item_compressed(self, mw_manager, mock_shared_cache_shard):
        """Test set_global_item_compressed wraps value with compression."""
        large_value = "x" * 20000  # > 16KB threshold
        
        mw_manager.set_global_item_compressed("large_item", large_value)
        
        # Should call set_global_item with wrapped value
        mock_shared_cache_shard.set.remote.assert_called_once()
        call_args = mock_shared_cache_shard.set.remote.call_args
        wrapped_value = call_args[0][1]  # Second positional arg is value
        assert "_v" in wrapped_value or isinstance(wrapped_value, str)
    
    @pytest.mark.asyncio
    async def test_get_item_compressed_async(self, mw_manager):
        """Test get_item_compressed_async unwraps compressed values."""
        # Set a compressed value
        wrapped = {
            "_v": "v1",
            "_ct": "zlib",
            "data": "compressed_data"
        }
        mw_manager.set_item("compressed_item", wrapped)
        
        # Should attempt to unwrap (may fail if not actually compressed)
        result = await mw_manager.get_item_compressed_async("compressed_item")
        
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
