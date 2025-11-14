"""
Unit tests for coordinator.core.routing module.

Tests routing functionality for bulk route resolution and cache management.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import time
import asyncio
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock
from seedcore.coordinator.core.routing import (
    RouteCache,
    RouteEntry,
    get_cached_route,
    resolve_route_cached_async,
    bulk_resolve_routes_cached,
    static_route_fallback,
)


class TestRouteCache:
    """Tests for RouteCache class."""
    
    @pytest.mark.asyncio
    async def test_get_set(self):
        """Test getting and setting cache entries."""
        cache = RouteCache(ttl_s=1.0, jitter_s=0.1)
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        
        cache.set(key, entry)
        retrieved = cache.get(key)
        
        assert retrieved is not None
        assert retrieved.logical_id == "organ-123"
        assert retrieved.epoch == "epoch-1"
    
    @pytest.mark.asyncio
    async def test_get_expired(self):
        """Test getting expired cache entry returns None."""
        cache = RouteCache(ttl_s=0.01, jitter_s=0.0)  # Very short TTL
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        
        cache.set(key, entry)
        time.sleep(0.02)  # Wait for expiration
        retrieved = cache.get(key)
        
        assert retrieved is None
    
    @pytest.mark.asyncio
    async def test_singleflight(self):
        """Test singleflight prevents concurrent requests."""
        cache = RouteCache()
        key = ("test_type", "test_domain")
        
        results = []
        async def resolve():
            async for fut, is_leader in cache.singleflight(key):
                if is_leader:
                    # Simulate work
                    await asyncio.sleep(0.01)
                    fut.set_result("organ-123")
                else:
                    result = await fut
                    results.append(result)
        
        # Run multiple concurrent resolves
        await asyncio.gather(resolve(), resolve(), resolve())
        
        # All should get the same result
        assert len(results) == 2  # 2 followers
        assert all(r == "organ-123" for r in results)
    
    def test_clear(self):
        """Test clearing cache."""
        cache = RouteCache()
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        
        cache.set(key, entry)
        cache.clear()
        
        assert cache.get(key) is None
    
    def test_stats(self):
        """Test cache statistics."""
        cache = RouteCache(ttl_s=1.0, jitter_s=0.1)
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        
        cache.set(key, entry)
        stats = cache.stats()
        
        assert "active_entries" in stats
        assert "total_entries" in stats
        assert stats["total_entries"] == 1


class TestGetCachedRoute:
    """Tests for get_cached_route function."""
    
    def test_get_cached_route_hit(self):
        """Test getting cached route when available."""
        cache = RouteCache()
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        cache.set(key, entry)
        
        result = get_cached_route("test_type", "test_domain", cache)
        assert result == "organ-123"
    
    def test_get_cached_route_miss(self):
        """Test getting cached route when not available."""
        cache = RouteCache()
        result = get_cached_route("test_type", "test_domain", cache)
        assert result is None
    
    def test_get_cached_route_no_cache(self):
        """Test getting cached route when cache is None."""
        result = get_cached_route("test_type", "test_domain", None)
        assert result is None


class TestStaticRouteFallback:
    """Tests for static_route_fallback function."""
    
    def test_fallback_anomaly_triage(self):
        """Test fallback for anomaly_triage type."""
        result = static_route_fallback("anomaly_triage", None)
        assert result is not None
        assert isinstance(result, str)
    
    def test_fallback_graph_operations(self):
        """Test fallback for graph operation types."""
        result = static_route_fallback("graph_embed", None)
        assert result is not None
    
    def test_fallback_unknown_type(self):
        """Test fallback for unknown type."""
        result = static_route_fallback("unknown_type", None)
        assert result is not None  # Should return a default organ


@pytest.mark.asyncio
class TestResolveRouteCachedAsync:
    """Tests for resolve_route_cached_async function."""
    
    async def test_resolve_from_cache(self):
        """Test resolving route from cache."""
        cache = RouteCache()
        key = ("test_type", "test_domain")
        entry = RouteEntry(
            logical_id="organ-123",
            epoch="epoch-1",
            resolved_from="cache"
        )
        cache.set(key, entry)
        
        organism_client = Mock()
        normalize_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback-organ"
        
        result = await resolve_route_cached_async(
            task_type="test_type",
            domain="test_domain",
            route_cache=cache,
            normalize_func=normalize_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            routing_remote_enabled=False,
            routing_remote_types=set(),
        )
        
        assert result == "organ-123"
    
    async def test_resolve_with_remote_success(self):
        """Test resolving route with remote call success."""
        cache = RouteCache()
        organism_client = Mock()
        organism_client.post = AsyncMock(return_value={
            "logical_id": "organ-456",
            "status": "ok",
            "epoch": "epoch-2",
            "resolved_from": "remote"
        })
        
        normalize_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback-organ"
        
        result = await resolve_route_cached_async(
            task_type="test_type",
            domain="test_domain",
            route_cache=cache,
            normalize_func=normalize_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            routing_remote_enabled=True,
            routing_remote_types={"test_type"},
        )
        
        assert result == "organ-456"
        organism_client.post.assert_called_once()
    
    async def test_resolve_with_remote_fallback(self):
        """Test resolving route with remote call failure falls back."""
        cache = RouteCache()
        organism_client = Mock()
        organism_client.post = AsyncMock(side_effect=Exception("Network error"))
        
        normalize_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback-organ"
        
        result = await resolve_route_cached_async(
            task_type="test_type",
            domain="test_domain",
            route_cache=cache,
            normalize_func=normalize_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            routing_remote_enabled=True,
            routing_remote_types={"test_type"},
        )
        
        assert result == "fallback-organ"


@pytest.mark.asyncio
class TestBulkResolveRoutesCached:
    """Tests for bulk_resolve_routes_cached function."""
    
    async def test_bulk_resolve_all_cached(self):
        """Test bulk resolve when all routes are cached."""
        cache = RouteCache()
        key1 = ("type1", None)
        key2 = ("type2", None)
        cache.set(key1, RouteEntry("organ-1", "epoch-1", "cache"))
        cache.set(key2, RouteEntry("organ-2", "epoch-1", "cache"))
        
        steps = [
            {"task": {"type": "type1"}},
            {"task": {"type": "type2"}}
        ]
        
        organism_client = Mock()
        normalize_func = lambda x: x.lower() if x else None
        normalize_domain_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback"
        
        mapping, epoch = await bulk_resolve_routes_cached(
            steps=steps,
            cid="test-cid",
            route_cache=cache,
            normalize_func=normalize_func,
            normalize_domain_func=normalize_domain_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            metrics=None,
            last_seen_epoch=None,
        )
        
        assert mapping[0] == "organ-1"
        assert mapping[1] == "organ-2"
        assert epoch is None  # No new epoch when all cached
    
    async def test_bulk_resolve_with_remote(self):
        """Test bulk resolve with remote call."""
        cache = RouteCache()
        steps = [
            {"task": {"type": "type1"}},
            {"task": {"type": "type2"}}
        ]
        
        organism_client = Mock()
        organism_client.timeout = 1.0
        organism_client.post = AsyncMock(return_value={
            "epoch": "epoch-2",
            "results": [
                {"key": "type1|", "logical_id": "organ-1", "status": "ok", "epoch": "epoch-2"},
                {"key": "type2|", "logical_id": "organ-2", "status": "ok", "epoch": "epoch-2"}
            ]
        })
        
        normalize_func = lambda x: x.lower() if x else None
        normalize_domain_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback"
        
        mapping, epoch = await bulk_resolve_routes_cached(
            steps=steps,
            cid="test-cid",
            route_cache=cache,
            normalize_func=normalize_func,
            normalize_domain_func=normalize_domain_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            metrics=None,
            last_seen_epoch=None,
        )
        
        assert mapping[0] == "organ-1"
        assert mapping[1] == "organ-2"
        assert epoch == "epoch-2"
    
    async def test_bulk_resolve_remote_fallback(self):
        """Test bulk resolve with remote failure uses fallback."""
        cache = RouteCache()
        steps = [
            {"task": {"type": "type1"}},
            {"task": {"type": "type2"}}
        ]
        
        organism_client = Mock()
        organism_client.timeout = 1.0
        organism_client.post = AsyncMock(side_effect=Exception("Network error"))
        
        normalize_func = lambda x: x.lower() if x else None
        normalize_domain_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback-organ"
        
        mapping, epoch = await bulk_resolve_routes_cached(
            steps=steps,
            cid="test-cid",
            route_cache=cache,
            normalize_func=normalize_func,
            normalize_domain_func=normalize_domain_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            metrics=None,
            last_seen_epoch=None,
        )
        
        assert mapping[0] == "fallback-organ"
        assert mapping[1] == "fallback-organ"
        assert epoch is None
    
    async def test_bulk_resolve_epoch_rotation(self):
        """Test bulk resolve clears cache on epoch rotation."""
        cache = RouteCache()
        key = ("type1", None)
        cache.set(key, RouteEntry("old-organ", "epoch-1", "cache"))
        
        steps = [{"task": {"type": "type1"}}]
        
        organism_client = Mock()
        organism_client.timeout = 1.0
        organism_client.post = AsyncMock(return_value={
            "epoch": "epoch-2",  # New epoch
            "results": [
                {"key": "type1|", "logical_id": "new-organ", "status": "ok", "epoch": "epoch-2"}
            ]
        })
        
        normalize_func = lambda x: x.lower() if x else None
        normalize_domain_func = lambda x: x.lower() if x else None
        static_fallback = lambda t, d: "fallback"
        
        mapping, epoch = await bulk_resolve_routes_cached(
            steps=steps,
            cid="test-cid",
            route_cache=cache,
            normalize_func=normalize_func,
            normalize_domain_func=normalize_domain_func,
            static_route_fallback_func=static_fallback,
            organism_client=organism_client,
            metrics=None,
            last_seen_epoch="epoch-1",  # Different from new epoch
        )
        
        # Cache should be cleared due to epoch rotation
        assert cache.get(key) is None or cache.get(key).epoch == "epoch-2"
        assert epoch == "epoch-2"

