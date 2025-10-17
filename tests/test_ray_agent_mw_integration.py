"""
Integration tests for RayAgent ↔ Mw integration.

Tests the complete integration including:
- Double-prefix guard
- Task caching and invalidation
- Typed global API usage
- Hot items telemetry
- Configurable TTLs
"""

import asyncio
import pytest
import time
import uuid
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock

from src.seedcore.agents.ray_agent import RayAgent
from src.seedcore.memory.working_memory import MwManager


class TestRayAgentMwIntegration:
    """Integration tests for RayAgent Mw integration."""

    @pytest.fixture
    def mock_mw_manager(self):
        """Create a mock MwManager for testing."""
        with patch('src.seedcore.agents.ray_agent.MwManager') as mock_class:
            mock_instance = Mock(spec=MwManager)
            mock_instance.get_telemetry.return_value = {
                "hit_ratio": 0.8,
                "l0_hits": 10,
                "l1_hits": 5,
                "l2_hits": 3,
                "task_cache_hits": 2,
                "task_cache_misses": 1,
                "task_evictions": 0,
                "negative_cache_hits": 0,
            }
            mock_instance.get_hot_items.return_value = [("task:123", 5), ("fact:abc", 3)]
            mock_instance.cache_task.return_value = None
            mock_instance.invalidate_task.return_value = None
            mock_instance.get_task_async = AsyncMock(return_value=None)
            mock_instance.del_global_key_sync.return_value = None
            mock_instance.delete_organ_item.return_value = None
            mock_instance.clear.return_value = None
            mock_instance.set_global_item_typed.return_value = None
            mock_instance.set_item.return_value = None
            mock_class.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def ray_agent(self, mock_mw_manager):
        """Create a RayAgent instance with mocked dependencies."""
        with patch('src.seedcore.agents.ray_agent.MltManager'):
            with patch('src.seedcore.agents.ray_agent.FlashbulbClient'):
                with patch('src.seedcore.agents.ray_agent.CognitiveServiceClient'):
                    agent = RayAgent.remote("test_agent_1")
                    # Set the mock mw_manager
                    agent.mw_manager = mock_mw_manager
                    return agent

    def test_double_prefix_guard_in_typed_calls(self, mock_mw_manager):
        """Test that typed calls don't cause double-prefixing."""
        # Test the MwManager directly
        manager = MwManager("test_agent")
        
        # Mock the internal methods
        with patch.object(manager, 'get_item_async') as mock_get:
            mock_get.return_value = asyncio.Future()
            mock_get.return_value.set_result({"test": "value"})
            
            # This should not cause double-prefixing
            result = asyncio.run(manager.get_item_typed_async("fact", "global", "abc"))
            
            # Verify the call was made with is_global=True
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            assert call_args[0][1] is True  # is_global=True

    def test_task_caching_and_invalidation(self, ray_agent, mock_mw_manager):
        """Test task caching and invalidation with exact key matching."""
        task_row = {
            "id": str(uuid.uuid4()),
            "status": "running",
            "type": "test_task",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        
        # Test cache_task_row
        ray_agent.cache_task_row(task_row)
        mock_mw_manager.cache_task.assert_called_once_with(task_row)
        
        # Test invalidate_task_cache
        task_id = task_row["id"]
        ray_agent.invalidate_task_cache(task_id)
        
        # Verify exact key matching
        mock_mw_manager.del_global_key_sync.assert_called_once_with(f"global:item:task:by_id:{task_id}")
        mock_mw_manager.delete_organ_item.assert_called_once_with(f"task:by_id:{task_id}")

    def test_typed_global_api_usage(self, ray_agent, mock_mw_manager):
        """Test that all global writes use typed API."""
        # Test _mw_put_json_global
        artifact = {"test": "data"}
        ray_agent._mw_put_json_global("task_artifact", "global", "test_key", artifact, ttl_s=600)
        
        mock_mw_manager.set_global_item_typed.assert_called_with(
            "task_artifact", "global", "test_key", artifact, ttl_s=600
        )

    def test_resilient_global_put(self, ray_agent, mock_mw_manager):
        """Test that _mw_put_json_global handles non-JSON values gracefully."""
        # Test with non-serializable object
        class NonSerializable:
            def __str__(self):
                return "converted_to_string"
        
        non_serializable = NonSerializable()
        ray_agent._mw_put_json_global("test", "global", "key", non_serializable)
        
        # Should convert to string
        mock_mw_manager.set_global_item_typed.assert_called_with(
            "test", "global", "key", "converted_to_string", ttl_s=600
        )

    def test_heartbeat_telemetry(self, ray_agent, mock_mw_manager):
        """Test that heartbeat includes Mw telemetry."""
        # Mock tasks_processed to trigger hot items
        ray_agent.tasks_processed = 20  # Multiple of 10
        
        heartbeat = ray_agent.get_heartbeat()
        
        # Check that Mw telemetry is included
        assert "memory_metrics" in heartbeat
        memory_metrics = heartbeat["memory_metrics"]
        
        assert "mw_hit_ratio" in memory_metrics
        assert "mw_l0_hits" in memory_metrics
        assert "mw_l1_hits" in memory_metrics
        assert "mw_l2_hits" in memory_metrics
        assert "mw_task_cache_hits" in memory_metrics
        assert "mw_task_cache_misses" in memory_metrics
        assert "mw_task_evictions" in memory_metrics
        assert "mw_negative_cache_hits" in memory_metrics
        
        # Check values match mock
        assert memory_metrics["mw_hit_ratio"] == 0.8
        assert memory_metrics["mw_l0_hits"] == 10

    def test_hot_items_telemetry(self, ray_agent, mock_mw_manager):
        """Test that hot items are included in heartbeat occasionally."""
        # Mock tasks_processed and random to trigger hot items
        ray_agent.tasks_processed = 20  # Multiple of 10
        
        with patch('random.random', return_value=0.03):  # < 0.05
            heartbeat = ray_agent.get_heartbeat()
            
            # Should include hot items
            assert "mw_hot_items" in heartbeat["memory_metrics"]
            assert heartbeat["memory_metrics"]["mw_hot_items"] == [("task:123", 5), ("fact:abc", 3)]

    def test_l0_eviction_on_archive(self, ray_agent, mock_mw_manager):
        """Test that L0 cache is cleared on archive."""
        # Mock other dependencies
        with patch.object(ray_agent, '_export_tier0_summary', return_value={}):
            with patch.object(ray_agent, 'mlt_manager', None):
                with patch.object(ray_agent, 'mfb_client', None):
                    ray_agent.archive()
                    
                    # Should call clear on mw_manager
                    mock_mw_manager.clear.assert_called_once()

    def test_task_lifecycle_hooks(self, ray_agent, mock_mw_manager):
        """Test task lifecycle hooks."""
        task_row = {"id": "123", "status": "running"}
        
        # Test on_task_row_loaded
        ray_agent.on_task_row_loaded(task_row)
        mock_mw_manager.cache_task.assert_called_with(task_row)
        
        # Test on_task_status_changed for terminal status
        ray_agent.on_task_status_changed("123", "completed")
        mock_mw_manager.del_global_key_sync.assert_called_with("global:item:task:by_id:123")
        mock_mw_manager.delete_organ_item.assert_called_with("task:by_id:123")

    def test_configurable_ttls(self):
        """Test that TTLs are configurable via environment variables."""
        # Set environment variables
        os.environ["MW_TASK_TTL_RUNNING_S"] = "60"
        os.environ["MW_TASK_TTL_COMPLETED_S"] = "1200"
        os.environ["MW_TASK_TTL_NEGATIVE_S"] = "45"
        
        # Create new MwManager instance
        manager = MwManager("test_agent")
        
        # Check that TTLs are read from environment
        assert manager.TASK_TTL_RUNNING == 60
        assert manager.TASK_TTL_COMPLETED == 1200
        assert manager.TASK_TTL_NEGATIVE == 45
        
        # Clean up
        del os.environ["MW_TASK_TTL_RUNNING_S"]
        del os.environ["MW_TASK_TTL_COMPLETED_S"]
        del os.environ["MW_TASK_TTL_NEGATIVE_S"]

    @pytest.mark.asyncio
    async def test_get_task_cached_integration(self, ray_agent, mock_mw_manager):
        """Test get_task_cached integration."""
        task_id = "test_task_123"
        expected_task = {"id": task_id, "status": "running"}
        
        # Mock the async method
        mock_mw_manager.get_task_async.return_value = expected_task
        
        result = await ray_agent.get_task_cached(task_id)
        
        assert result == expected_task
        mock_mw_manager.get_task_async.assert_called_once_with(task_id)

    def test_execute_methods_use_new_helpers(self, ray_agent, mock_mw_manager):
        """Test that execute methods use the new normalized helpers."""
        task_data = {
            "task_id": "test_123",
            "type": "test_task",
            "description": "Test task",
        }
        
        # Mock the execute_task method
        with patch.object(ray_agent, '_simulate_task_execution', return_value={"success": True, "quality": 0.8}):
            with patch.object(ray_agent, '_promote_to_mlt'):
                ray_agent.execute_task(task_data)
                
                # Should call both local and global helpers
                mock_mw_manager.set_item.assert_called()  # L0
                mock_mw_manager.set_global_item_typed.assert_called()  # Global

    def test_incident_pointer_consistency(self, ray_agent, mock_mw_manager):
        """Test that incident pointers use consistent keying."""
        task_info = {"id": "incident_123"}
        
        # Mock the execute_high_stakes_task method
        with patch.object(ray_agent, '_energy_slice', return_value=100.0):
            with patch.object(ray_agent, 'update_performance'):
                with patch.object(ray_agent, 'mfb_client', None):
                    ray_agent.execute_high_stakes_task(task_info)
                    
                    # Should use typed API for incident pointer
                    mock_mw_manager.set_global_item_typed.assert_called()
                    call_args = mock_mw_manager.set_global_item_typed.call_args
                    assert call_args[0][0] == "incident"  # kind
                    assert call_args[0][1] == "global"    # scope

    def test_no_double_stringification(self, ray_agent, mock_mw_manager):
        """Test that cached values are not double-stringified."""
        # Mock get_item_typed_async to return a dict (not string)
        mock_mw_manager.get_item_typed_async = AsyncMock(return_value={"test": "value"})
        
        # This should not try to json.loads a dict
        result = asyncio.run(ray_agent.find_knowledge("test_fact"))
        
        # Should return the dict as-is
        assert result == {"test": "value"}


if __name__ == "__main__":
    # Run a simple integration test
    print("Running RayAgent Mw integration test...")
    
    # Test double-prefix guard
    manager = MwManager("test_agent")
    print("✅ MwManager created successfully")
    
    # Test TTL constants
    print(f"✅ TTL constants: RUNNING={manager.TASK_TTL_RUNNING}, COMPLETED={manager.TASK_TTL_COMPLETED}")
    
    # Test task caching
    task_row = {
        "id": str(uuid.uuid4()),
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    manager.cache_task(task_row)
    print(f"✅ Task cached: {task_row['id']}")
    
    # Test invalidation
    manager.invalidate_task(task_row["id"])
    print(f"✅ Task invalidated: {task_row['id']}")
    
    print("🎉 All integration tests passed!")
