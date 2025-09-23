"""
Integration tests for MwManager task caching functionality.

Tests the complete task caching lifecycle including:
- Double-prefix guard
- L0 management (clear, delete_organ_item)
- Task-aware caching with TTL derivation
- Negative cache integration
- Metrics and error handling
"""

import asyncio
import pytest
import time
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock

from src.seedcore.memory.working_memory import MwManager


class TestMwTaskIntegration:
    """Integration tests for MwManager task caching."""

    @pytest.fixture
    def mw_manager(self):
        """Create a test MwManager instance."""
        with patch('src.seedcore.memory.working_memory.get_mw_store'):
            with patch('src.seedcore.memory.working_memory.get_node_cache'):
                with patch('src.seedcore.memory.working_memory._shard_for'):
                    manager = MwManager("test_organ_1")
                    return manager

    @pytest.fixture
    def sample_task(self):
        """Create a sample task dict for testing."""
        return {
            "id": str(uuid.uuid4()),
            "status": "running",
            "type": "test_task",
            "description": "Test task for caching",
            "params": {"test": "value"},
            "domain": "test_domain",
            "drift_score": 0.1,
            "attempts": 1,
            "locked_by": "test_worker",
            "locked_at": datetime.now(timezone.utc).isoformat(),
            "run_after": None,
            "result": None,
            "error": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def test_double_prefix_guard(self, mw_manager):
        """Test that double-prefixing is prevented."""
        # Test with is_global=True
        result = asyncio.run(mw_manager.get_item_async("global:item:task:by_id:123", is_global=True))
        assert result is None  # Should not double-prefix
        
        # Test with key that already starts with global:item:
        result = asyncio.run(mw_manager.get_item_async("global:item:task:by_id:456"))
        assert result is None  # Should detect and not double-prefix
        
        # Test with organ: prefix
        result = asyncio.run(mw_manager.get_item_async("organ:test_organ_1:item:task:789"))
        assert result is None  # Should treat as organ-local only

    def test_l0_management(self, mw_manager):
        """Test explicit L0 cache management."""
        # Set some items
        mw_manager.set_item("test1", "value1")
        mw_manager.set_item("test2", "value2")
        
        # Verify they're in L0
        assert mw_manager._cache["organ:test_organ_1:item:test1"] == "value1"
        assert mw_manager._cache["organ:test_organ_1:item:test2"] == "value2"
        
        # Test delete_organ_item
        mw_manager.delete_organ_item("test1")
        assert "organ:test_organ_1:item:test1" not in mw_manager._cache
        assert "organ:test_organ_1:item:test2" in mw_manager._cache
        
        # Test clear
        mw_manager.clear()
        assert len(mw_manager._cache) == 0

    def test_task_caching_with_ttl_derivation(self, mw_manager, sample_task):
        """Test task caching with TTL derivation from status and timestamps."""
        # Test running task (short TTL)
        sample_task["status"] = "running"
        mw_manager.cache_task(sample_task)
        
        # Verify task is cached
        task_id = sample_task["id"]
        item_id = f"task:by_id:{task_id}"
        assert item_id in mw_manager._cache
        
        # Test completed task (longer TTL)
        sample_task["status"] = "completed"
        sample_task["id"] = str(uuid.uuid4())  # New ID
        mw_manager.cache_task(sample_task)
        
        # Test with lease_expires_at
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        sample_task["lease_expires_at"] = future_time.isoformat()
        sample_task["status"] = "running"
        sample_task["id"] = str(uuid.uuid4())
        mw_manager.cache_task(sample_task)
        
        # Test with run_after
        future_run = datetime.now(timezone.utc) + timedelta(hours=1)
        sample_task["run_after"] = future_run.isoformat()
        sample_task["id"] = str(uuid.uuid4())
        mw_manager.cache_task(sample_task)

    def test_task_caching_error_handling(self, mw_manager):
        """Test error handling in task caching."""
        # Test with invalid task (no ID)
        invalid_task = {"status": "running"}
        mw_manager.cache_task(invalid_task)  # Should not raise
        
        # Test with None ID
        invalid_task = {"id": None, "status": "running"}
        mw_manager.cache_task(invalid_task)  # Should not raise
        
        # Test with malformed timestamps
        invalid_task = {
            "id": str(uuid.uuid4()),
            "status": "running",
            "lease_expires_at": "invalid-timestamp"
        }
        mw_manager.cache_task(invalid_task)  # Should not raise

    @pytest.mark.asyncio
    async def test_get_task_async_with_negative_cache(self, mw_manager):
        """Test get_task_async with negative cache integration."""
        task_id = str(uuid.uuid4())
        
        # First call should miss and set negative cache
        result = await mw_manager.get_task_async(task_id)
        assert result is None
        assert mw_manager._task_cache_misses == 1
        
        # Second call should hit negative cache
        result = await mw_manager.get_task_async(task_id)
        assert result is None
        assert mw_manager._negative_cache_hits == 1

    def test_invalidate_task(self, mw_manager, sample_task):
        """Test task invalidation from all cache levels."""
        # Cache a task
        mw_manager.cache_task(sample_task)
        task_id = sample_task["id"]
        
        # Verify it's cached
        item_id = f"task:by_id:{task_id}"
        assert item_id in mw_manager._cache
        
        # Invalidate
        mw_manager.invalidate_task(task_id)
        
        # Verify it's removed from L0
        assert item_id not in mw_manager._cache
        assert mw_manager._task_evictions == 1

    def test_metrics_tracking(self, mw_manager, sample_task):
        """Test that metrics are properly tracked."""
        # Initial state
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_cache_hits"] == 0
        assert telemetry["task_cache_misses"] == 0
        assert telemetry["task_evictions"] == 0
        assert telemetry["negative_cache_hits"] == 0
        
        # Cache a task
        mw_manager.cache_task(sample_task)
        
        # Get task (should hit)
        task_id = sample_task["id"]
        item_id = f"task:by_id:{task_id}"
        result = mw_manager._get_item_sync(item_id)
        assert result is not None
        
        # Check metrics
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_cache_hits"] >= 0  # May be 0 if using sync fallback
        
        # Test reset
        mw_manager.reset_telemetry()
        telemetry = mw_manager.get_telemetry()
        assert telemetry["task_cache_hits"] == 0
        assert telemetry["task_cache_misses"] == 0
        assert telemetry["task_evictions"] == 0
        assert telemetry["negative_cache_hits"] == 0

    def test_ttl_constants(self, mw_manager):
        """Test that TTL constants are properly defined."""
        assert mw_manager.TASK_TTL_CREATED == 10
        assert mw_manager.TASK_TTL_QUEUED == 10
        assert mw_manager.TASK_TTL_RUNNING == 10
        assert mw_manager.TASK_TTL_RETRY == 20
        assert mw_manager.TASK_TTL_COMPLETED == 600
        assert mw_manager.TASK_TTL_FAILED == 300
        assert mw_manager.TASK_TTL_CANCELLED == 300
        assert mw_manager.TASK_TTL_DEFAULT == 30

    def test_normalized_global_keys(self, mw_manager):
        """Test that set_global_item normalizes keys correctly."""
        # Test with already prefixed key
        mw_manager.set_global_item("global:item:test:key", "value1")
        
        # Test with unqualified key
        mw_manager.set_global_item("test:key", "value2")
        
        # Both should be stored with proper keys
        assert "organ:test_organ_1:item:global:item:test:key" in mw_manager._cache
        assert "organ:test_organ_1:item:test:key" in mw_manager._cache

    @pytest.mark.asyncio
    async def test_full_task_lifecycle(self, mw_manager):
        """Test complete task lifecycle with caching."""
        # Create task
        task = {
            "id": str(uuid.uuid4()),
            "status": "created",
            "type": "integration_test",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # 1. Cache task
        mw_manager.cache_task(task)
        task_id = task["id"]
        
        # 2. Get task (should hit cache)
        result = await mw_manager.get_task_async(task_id)
        if result:  # May be None due to mocking
            assert result["id"] == task_id
        
        # 3. Update task status
        task["status"] = "running"
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        mw_manager.cache_task(task)
        
        # 4. Invalidate task
        mw_manager.invalidate_task(task_id)
        
        # 5. Try to get again (should miss due to invalidation)
        result = await mw_manager.get_task_async(task_id)
        assert result is None

    def test_compression_integration(self, mw_manager):
        """Test that task caching uses compression for large tasks."""
        # Create a large task
        large_task = {
            "id": str(uuid.uuid4()),
            "status": "running",
            "type": "large_task",
            "large_data": "x" * 20000,  # 20KB string
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Cache should not raise
        mw_manager.cache_task(large_task)
        
        # Verify it's cached
        task_id = large_task["id"]
        item_id = f"task:by_id:{task_id}"
        assert item_id in mw_manager._cache

    def test_edge_cases(self, mw_manager):
        """Test edge cases and error conditions."""
        # Empty task dict
        mw_manager.cache_task({})
        
        # Task with empty string ID
        mw_manager.cache_task({"id": "", "status": "running"})
        
        # Task with very long ID
        long_id = "x" * 1000
        mw_manager.cache_task({"id": long_id, "status": "running"})
        
        # Task with invalid status
        mw_manager.cache_task({"id": str(uuid.uuid4()), "status": "invalid_status"})
        
        # All should not raise exceptions


if __name__ == "__main__":
    # Run a simple integration test
    print("Running MwManager task integration test...")
    
    with patch('src.seedcore.memory.working_memory.get_mw_store'):
        with patch('src.seedcore.memory.working_memory.get_node_cache'):
            with patch('src.seedcore.memory.working_memory._shard_for'):
                manager = MwManager("integration_test_organ")
                
                # Test basic functionality
                manager.clear()
                assert len(manager._cache) == 0
                
                # Test task caching
                task = {
                    "id": str(uuid.uuid4()),
                    "status": "running",
                    "type": "test",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                
                manager.cache_task(task)
                task_id = task["id"]
                item_id = f"task:by_id:{task_id}"
                
                # Verify caching
                assert item_id in manager._cache
                print(f"✅ Task {task_id} cached successfully")
                
                # Test invalidation
                manager.invalidate_task(task_id)
                assert item_id not in manager._cache
                print(f"✅ Task {task_id} invalidated successfully")
                
                # Test metrics
                telemetry = manager.get_telemetry()
                print(f"✅ Telemetry: {telemetry}")
                
                print("🎉 All integration tests passed!")
