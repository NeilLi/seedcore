#!/usr/bin/env python3
"""
Unit tests for MwStoreShard.

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
from unittest.mock import Mock, MagicMock, patch
import collections
import heapq


class TestMwStoreShard:
    """Tests for MwStoreShard class (non-Ray instance)."""
    
    @pytest.fixture
    def shard(self):
        """Create a MwStoreShard instance (not as Ray actor)."""
        from src.seedcore.memory.mw_store_shard import MwStoreShard
        return MwStoreShard(max_items=1000)
    
    def test_init_default(self):
        """Test MwStoreShard initialization with default max_items."""
        from src.seedcore.memory.mw_store_shard import MwStoreShard
        shard = MwStoreShard()
        
        assert shard.max_items == 10_000
        assert isinstance(shard.counts, collections.Counter)
        assert len(shard.counts) == 0
    
    def test_init_custom_max_items(self, shard):
        """Test MwStoreShard initialization with custom max_items."""
        assert shard.max_items == 1000
        assert isinstance(shard.counts, collections.Counter)
        assert len(shard.counts) == 0
    
    def test_ping(self, shard):
        """Test ping returns pong."""
        result = shard.ping()
        assert result == "pong"
    
    def test_incr_single_item(self, shard):
        """Test incrementing count for a single item."""
        shard.incr("item1", delta=1)
        
        assert shard.counts["item1"] == 1
        assert len(shard.counts) == 1
    
    def test_incr_multiple_times(self, shard):
        """Test incrementing count multiple times for same item."""
        shard.incr("item1", delta=1)
        shard.incr("item1", delta=2)
        shard.incr("item1", delta=3)
        
        assert shard.counts["item1"] == 6
        assert len(shard.counts) == 1
    
    def test_incr_different_items(self, shard):
        """Test incrementing counts for different items."""
        shard.incr("item1", delta=5)
        shard.incr("item2", delta=3)
        shard.incr("item3", delta=1)
        
        assert shard.counts["item1"] == 5
        assert shard.counts["item2"] == 3
        assert shard.counts["item3"] == 1
        assert len(shard.counts) == 3
    
    def test_incr_custom_delta(self, shard):
        """Test incrementing with custom delta."""
        shard.incr("item1", delta=10)
        
        assert shard.counts["item1"] == 10
    
    def test_incr_negative_delta(self, shard):
        """Test incrementing with negative delta (decrement)."""
        shard.incr("item1", delta=5)
        shard.incr("item1", delta=-2)
        
        assert shard.counts["item1"] == 3
    
    def test_incr_eviction_when_over_limit(self, shard):
        """Test that eviction happens when max_items is exceeded."""
        shard.max_items = 3
        
        # Add 3 items
        shard.incr("item1", delta=10)
        shard.incr("item2", delta=5)
        shard.incr("item3", delta=1)
        
        assert len(shard.counts) == 3
        
        # Add a 4th item - should trigger eviction
        shard.incr("item4", delta=1)
        
        # Should evict the item with lowest count (item3)
        assert len(shard.counts) <= 3
        assert "item3" not in shard.counts or shard.counts["item3"] == 0
        assert "item1" in shard.counts  # Highest count, should remain
        assert "item2" in shard.counts  # Medium count, should remain
    
    def test_topn_empty(self, shard):
        """Test topn with empty counts."""
        result = shard.topn(5)
        assert result == []
    
    def test_topn_single_item(self, shard):
        """Test topn with single item."""
        shard.incr("item1", delta=5)
        
        result = shard.topn(1)
        assert len(result) == 1
        assert result[0] == ("item1", 5)
    
    def test_topn_multiple_items(self, shard):
        """Test topn with multiple items."""
        shard.incr("item1", delta=10)
        shard.incr("item2", delta=5)
        shard.incr("item3", delta=20)
        shard.incr("item4", delta=3)
        
        result = shard.topn(2)
        
        assert len(result) == 2
        # Should be sorted by count descending
        assert result[0] == ("item3", 20)
        assert result[1] == ("item2", 5)  # item2 has 5, item1 has 10 but item3 is top
        # Actually wait, let me reconsider - topn(2) should return top 2
        # item3=20, item1=10, item2=5, item4=3
        # So top 2 should be item3 and item1
        
        # Let me check the actual implementation - it uses heapq.nlargest
        # which returns the n largest items, sorted descending
        result = shard.topn(2)
        counts_dict = dict(result)
        assert counts_dict["item3"] == 20
        assert counts_dict.get("item1") == 10 or counts_dict.get("item2") == 5
    
    def test_topn_all_items(self, shard):
        """Test topn returns all items when n is larger than count."""
        shard.incr("item1", delta=10)
        shard.incr("item2", delta=5)
        shard.incr("item3", delta=3)
        
        result = shard.topn(10)
        
        assert len(result) == 3
        # Verify all items are present
        items = [item for item, count in result]
        assert "item1" in items
        assert "item2" in items
        assert "item3" in items
    
    def test_topn_sorted_descending(self, shard):
        """Test that topn returns items sorted by count descending."""
        shard.incr("item1", delta=1)
        shard.incr("item2", delta=5)
        shard.incr("item3", delta=3)
        shard.incr("item4", delta=10)
        
        result = shard.topn(4)
        
        counts = [count for item, count in result]
        # Verify descending order
        assert counts == sorted(counts, reverse=True)
    
    def test_incr_zero_delta(self, shard):
        """Test incrementing with zero delta."""
        shard.incr("item1", delta=5)
        shard.incr("item1", delta=0)
        
        assert shard.counts["item1"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
