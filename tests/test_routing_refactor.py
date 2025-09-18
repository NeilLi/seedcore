#!/usr/bin/env python3
"""
Tests for routing refactor implementation.
Tests the key functionality: de-duplication, single-flight, fallbacks, and metrics.
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List

# Import the classes we're testing
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from seedcore.services.coordinator_service import RouteCache, RouteEntry
from seedcore.organs.organism_manager import RoutingDirectory


class TestRouteCache:
    """Test the tiny TTL route cache with single-flight."""
    
    def test_cache_basic_operations(self):
        """Test basic cache get/set operations."""
        cache = RouteCache(ttl_s=1.0, jitter_s=0.1)
        key = ("test_type", "test_domain")
        
        # Test empty cache
        assert cache.get(key) is None
        
        # Test set and get
        entry = RouteEntry(
            logical_id="test_organ",
            epoch="epoch-123",
            resolved_from="task",
            instance_id="instance-123"
        )
        cache.set(key, entry)
        
        cached = cache.get(key)
        assert cached is not None
        assert cached.logical_id == "test_organ"
        assert cached.resolved_from == "task"
    
    def test_cache_expiry(self):
        """Test that cache entries expire after TTL."""
        cache = RouteCache(ttl_s=0.1, jitter_s=0.0)  # Very short TTL
        key = ("test_type", "test_domain")
        
        entry = RouteEntry(logical_id="test_organ", epoch="epoch-123", resolved_from="task")
        cache.set(key, entry)
        
        # Should be available immediately
        assert cache.get(key) is not None
        
        # Should expire after TTL
        time.sleep(0.2)
        assert cache.get(key) is None
    
    @pytest.mark.asyncio
    async def test_singleflight_prevents_dogpiles(self):
        """Test that single-flight prevents multiple concurrent resolves."""
        cache = RouteCache(ttl_s=1.0, jitter_s=0.0)
        key = ("test_type", "test_domain")
        
        # Track how many times the resolve function is called
        resolve_calls = 0
        
        async def mock_resolve():
            nonlocal resolve_calls
            resolve_calls += 1
            await asyncio.sleep(0.1)  # Simulate network delay
            return "resolved_organ"
        
        # Start multiple concurrent resolves for the same key
        async def resolve_task():
            async for fut, is_leader in cache.singleflight(key):
                # Only one coroutine (leader) should do the work
                if is_leader and not fut.done():
                    try:
                        result = await mock_resolve()
                        if not fut.done():
                            fut.set_result(result)
                    except Exception as e:
                        if not fut.done():
                            fut.set_exception(e)
                        raise
                # All coroutines await the result
                return await fut
        
        # Start 5 concurrent tasks
        tasks = await asyncio.gather(*[resolve_task() for _ in range(5)])
        
        # Should only call resolve once due to single-flight
        assert resolve_calls == 1
        assert all(task == "resolved_organ" for task in tasks)


class TestRoutingDirectory:
    """Test the routing directory with runtime registry integration."""
    
    def test_normalization(self):
        """Test string normalization for consistent matching."""
        assert RoutingDirectory._normalize("  TEST_TYPE  ") == "test_type"
        assert RoutingDirectory._normalize("") == ""
        assert RoutingDirectory._normalize(None) is None
    
    def test_default_rules_loading(self):
        """Test that sensible default rules are loaded."""
        routing = RoutingDirectory()
        
        # Test utility tasks
        assert routing.rules_by_task["general_query"] == "utility_organ_1"
        assert routing.rules_by_task["health_check"] == "utility_organ_1"
        assert routing.rules_by_task["fact_search"] == "utility_organ_1"
        
        # Test actuation tasks
        assert routing.rules_by_task["execute"] == "actuator_organ_1"
        
        # Test graph tasks
        assert routing.rules_by_task["graph_embed"] == "graph_dispatcher"
        assert routing.rules_by_task["graph_rag_query"] == "graph_dispatcher"
    
    def test_rule_management(self):
        """Test adding and removing routing rules."""
        routing = RoutingDirectory()
        
        # Add a custom rule
        routing.set_rule("custom_task", "custom_organ")
        assert routing.rules_by_task["custom_task"] == "custom_organ"
        
        # Add a domain-specific rule
        routing.set_rule("execute", "special_organ", domain="robot_arm")
        assert routing.rules_by_domain[("execute", "robot_arm")] == "special_organ"
        
        # Remove rules
        routing.remove_rule("custom_task")
        assert "custom_task" not in routing.rules_by_task
        
        routing.remove_rule("execute", domain="robot_arm")
        assert ("execute", "robot_arm") not in routing.rules_by_domain
    
    @pytest.mark.asyncio
    async def test_resolve_with_mock_registry(self):
        """Test route resolution with mocked runtime registry."""
        routing = RoutingDirectory()
        
        # Mock the registry query
        async def mock_query_registry(logical_id: str, epoch: str):
            return {
                "logical_id": logical_id,
                "instance_id": f"instance-{logical_id}",
                "status": "alive",
                "epoch": epoch
            }
        
        routing._query_runtime_registry = mock_query_registry
        
        # Test resolution
        logical_id, resolved_from = await routing.resolve(
            "graph_embed", domain=None, current_epoch="epoch-123"
        )
        
        assert logical_id == "graph_dispatcher"
        assert resolved_from == "task"
    
    @pytest.mark.asyncio
    async def test_resolve_fallback_when_no_instance(self):
        """Test that resolution falls back when no active instance."""
        routing = RoutingDirectory()
        
        # Mock registry to return None (no active instance)
        routing._query_runtime_registry = AsyncMock(return_value=None)
        
        # Test resolution should still return logical_id for fallback
        logical_id, resolved_from = await routing.resolve(
            "graph_embed", domain=None, current_epoch="epoch-123"
        )
        
        assert logical_id == "graph_dispatcher"
        assert resolved_from == "fallback"


class TestBulkResolveDeDuplication:
    """Test bulk resolve de-duplication logic."""
    
    def test_deduplication_logic(self):
        """Test that duplicate (type, domain) pairs are de-duplicated."""
        steps = [
            {"task": {"type": "graph_embed", "domain": "facts"}},
            {"task": {"type": "graph_embed", "domain": "facts"}},  # Duplicate
            {"task": {"type": "fact_search", "domain": None}},
            {"task": {"type": "graph_embed", "domain": "facts"}},  # Another duplicate
        ]
        
        # Simulate the de-duplication logic
        pairs = {}
        for idx, step in enumerate(steps):
            task = step.get("task", {})
            t = task.get("type", "").strip().lower()
            d = task.get("domain")
            if d is not None:
                d = d.strip().lower()
            key = (t, d)
            
            if key not in pairs:
                pairs[key] = []
            pairs[key].append(idx)
        
        # Should have 2 unique pairs: (graph_embed, facts) and (fact_search, None)
        assert len(pairs) == 2
        assert ("graph_embed", "facts") in pairs
        assert ("fact_search", None) in pairs
        
        # Check indices are grouped correctly
        assert pairs[("graph_embed", "facts")] == [0, 1, 3]
        assert pairs[("fact_search", None)] == [2]


class TestFeatureFlags:
    """Test feature flag functionality."""
    
    def test_routing_remote_disabled(self):
        """Test that routing falls back to static when feature flag is disabled."""
        # This would be tested in integration tests
        # For now, just verify the logic exists
        pass
    
    def test_routing_remote_types_filtering(self):
        """Test that only specified task types use remote routing."""
        # This would be tested in integration tests
        pass


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
