#!/usr/bin/env python3
"""
Unit tests for metrics registry.

Tests the global singleton pattern for MetricsTracker.
"""

import pytest
import threading

from seedcore.ops.metrics.registry import (
    get_global_metrics_tracker,
    reset_global_metrics_tracker,
    set_global_metrics_tracker,
)
from seedcore.ops.metrics.tracker import MetricsTracker


class TestMetricsRegistry:
    """Tests for metrics registry."""
    
    def teardown_method(self):
        """Reset global tracker after each test."""
        reset_global_metrics_tracker()
    
    def test_get_global_metrics_tracker_creates_instance(self):
        """Test that get_global_metrics_tracker creates an instance."""
        tracker = get_global_metrics_tracker()
        assert tracker is not None
        assert isinstance(tracker, MetricsTracker)
    
    def test_get_global_metrics_tracker_returns_same_instance(self):
        """Test that get_global_metrics_tracker returns the same instance."""
        tracker1 = get_global_metrics_tracker()
        tracker2 = get_global_metrics_tracker()
        
        assert tracker1 is tracker2
    
    def test_get_global_metrics_tracker_thread_safety(self):
        """Test that get_global_metrics_tracker is thread-safe."""
        trackers = []
        
        def get_tracker():
            trackers.append(get_global_metrics_tracker())
        
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=get_tracker)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # All should be the same instance
        assert all(tracker is trackers[0] for tracker in trackers)
    
    def test_reset_global_metrics_tracker(self):
        """Test resetting the global tracker."""
        tracker1 = get_global_metrics_tracker()
        tracker1.track_routing_decision("fast")
        
        reset_global_metrics_tracker()
        
        tracker2 = get_global_metrics_tracker()
        assert tracker2 is not tracker1
        assert tracker2._task_metrics["fast_routed_total"] == 0
    
    def test_set_global_metrics_tracker(self):
        """Test setting a custom tracker."""
        custom_tracker = MetricsTracker(latency_reservoir_size=500)
        custom_tracker.track_routing_decision("fast")
        
        set_global_metrics_tracker(custom_tracker)
        
        retrieved_tracker = get_global_metrics_tracker()
        assert retrieved_tracker is custom_tracker
        assert retrieved_tracker._task_metrics["fast_routed_total"] == 1
    
    def test_set_global_metrics_tracker_preserves_state(self):
        """Test that setting a custom tracker preserves its state."""
        custom_tracker = MetricsTracker()
        custom_tracker.track_routing_decision("fast")
        custom_tracker.track_routing_decision("planner")
        
        set_global_metrics_tracker(custom_tracker)
        
        retrieved_tracker = get_global_metrics_tracker()
        assert retrieved_tracker._task_metrics["fast_routed_total"] == 1
        assert retrieved_tracker._task_metrics["planner_routed_total"] == 1

