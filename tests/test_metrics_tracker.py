#!/usr/bin/env python3
"""
Unit tests for MetricsTracker.

Tests metrics tracking functionality including:
- Routing decision tracking
- Task execution metrics
- Persistence and dispatch metrics
- Thread-safety
- Metadata and reset functionality
"""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock

from seedcore.ops.metrics.tracker import MetricsTracker
from seedcore.ops.metrics.exporters import NoOpExporter, LoggingExporter


class TestMetricsTracker:
    """Tests for MetricsTracker class."""
    
    @pytest.fixture
    def tracker(self):
        """Create a MetricsTracker instance for testing."""
        return MetricsTracker(latency_reservoir_size=100)
    
    def test_initialization(self, tracker):
        """Test tracker initialization."""
        assert tracker._latency_reservoir_size == 100
        assert tracker._initialized_at is not None
        assert tracker._last_reset_at is None
        assert tracker._exporter is None
        
        # Check that metrics are initialized
        assert tracker._task_metrics["total_tasks"] == 0
        assert tracker._task_metrics["fast_routed_total"] == 0
        assert len(tracker._task_metrics["fast_path_latency_ms"]) == 0
    
    def test_initialization_with_exporter(self):
        """Test tracker initialization with exporter."""
        exporter = NoOpExporter()
        tracker = MetricsTracker(exporter=exporter)
        assert tracker._exporter is exporter
    
    def test_track_routing_decision_fast(self, tracker):
        """Test tracking fast routing decision."""
        tracker.track_routing_decision("fast")
        assert tracker._task_metrics["fast_routed_total"] == 1
        assert tracker._task_metrics["planner_routed_total"] == 0
        assert tracker._task_metrics["hgnn_routed_total"] == 0
    
    def test_track_routing_decision_planner(self, tracker):
        """Test tracking planner routing decision."""
        tracker.track_routing_decision("planner")
        assert tracker._task_metrics["planner_routed_total"] == 1
        assert tracker._task_metrics["fast_routed_total"] == 0
    
    def test_track_routing_decision_hgnn_with_plan(self, tracker):
        """Test tracking HGNN routing decision with plan."""
        tracker.track_routing_decision("hgnn", has_plan=True)
        assert tracker._task_metrics["hgnn_routed_total"] == 1
        assert tracker._task_metrics["hgnn_plan_generated_total"] == 1
        assert tracker._task_metrics["hgnn_plan_empty_total"] == 0
    
    def test_track_routing_decision_hgnn_without_plan(self, tracker):
        """Test tracking HGNN routing decision without plan."""
        tracker.track_routing_decision("hgnn", has_plan=False)
        assert tracker._task_metrics["hgnn_routed_total"] == 1
        assert tracker._task_metrics["hgnn_plan_generated_total"] == 0
        assert tracker._task_metrics["hgnn_plan_empty_total"] == 1
    
    def test_track_metrics_fast_path(self, tracker):
        """Test tracking fast path execution metrics."""
        tracker.track_metrics("fast", success=True, latency_ms=42.0)
        
        assert tracker._task_metrics["total_tasks"] == 1
        assert tracker._task_metrics["successful_tasks"] == 1
        assert tracker._task_metrics["failed_tasks"] == 0
        assert tracker._task_metrics["fast_path_tasks"] == 1
        assert len(tracker._task_metrics["fast_path_latency_ms"]) == 1
        assert tracker._task_metrics["fast_path_latency_ms"][0] == 42.0
    
    def test_track_metrics_hgnn(self, tracker):
        """Test tracking HGNN execution metrics."""
        tracker.track_metrics("hgnn", success=True, latency_ms=100.0)
        
        assert tracker._task_metrics["total_tasks"] == 1
        assert tracker._task_metrics["successful_tasks"] == 1
        assert tracker._task_metrics["hgnn_tasks"] == 1
        assert len(tracker._task_metrics["hgnn_latency_ms"]) == 1
    
    def test_track_metrics_failure(self, tracker):
        """Test tracking failed execution."""
        tracker.track_metrics("fast", success=False, latency_ms=50.0)
        
        assert tracker._task_metrics["total_tasks"] == 1
        assert tracker._task_metrics["successful_tasks"] == 0
        assert tracker._task_metrics["failed_tasks"] == 1
    
    def test_track_metrics_escalation_failure(self, tracker):
        """Test tracking escalation failure."""
        tracker.track_metrics("escalation_failure", success=False, latency_ms=200.0)
        
        assert tracker._task_metrics["escalation_failures"] == 1
        assert len(tracker._task_metrics["escalation_latency_ms"]) == 1
    
    def test_record_proto_plan_upsert(self, tracker):
        """Test recording proto plan upsert."""
        tracker.record_proto_plan_upsert("ok")
        tracker.record_proto_plan_upsert("err")
        tracker.record_proto_plan_upsert("truncated")
        
        assert tracker._task_metrics["proto_plan_upsert_ok_total"] == 1
        assert tracker._task_metrics["proto_plan_upsert_err_total"] == 1
        assert tracker._task_metrics["proto_plan_upsert_truncated_total"] == 1
    
    def test_record_outbox_enqueue(self, tracker):
        """Test recording outbox enqueue."""
        tracker.record_outbox_enqueue("ok")
        tracker.record_outbox_enqueue("dup")
        tracker.record_outbox_enqueue("err")
        
        assert tracker._task_metrics["outbox_embed_enqueue_ok_total"] == 1
        assert tracker._task_metrics["outbox_embed_enqueue_dup_total"] == 1
        assert tracker._task_metrics["outbox_embed_enqueue_err_total"] == 1
    
    def test_record_dispatch(self, tracker):
        """Test recording dispatch metrics."""
        tracker.record_dispatch("planner", "ok")
        tracker.record_dispatch("planner", "err")
        tracker.record_dispatch("hgnn", "ok")
        tracker.record_dispatch("hgnn", "err")
        
        assert tracker._task_metrics["dispatch_planner_ok_total"] == 1
        assert tracker._task_metrics["dispatch_planner_err_total"] == 1
        assert tracker._task_metrics["dispatch_hgnn_ok_total"] == 1
        assert tracker._task_metrics["dispatch_hgnn_err_total"] == 1
    
    def test_record_route_latency(self, tracker):
        """Test recording route latency."""
        tracker.record_route_latency(150.0)
        tracker.record_route_latency(200.0)
        
        assert len(tracker._task_metrics["route_and_execute_latency_ms"]) == 2
        assert tracker._task_metrics["route_and_execute_latency_ms"][0] == 150.0
        assert tracker._task_metrics["route_and_execute_latency_ms"][1] == 200.0
    
    def test_increment_counter(self, tracker):
        """Test incrementing counter metrics."""
        tracker.increment_counter("route_cache_hit_total")
        tracker.increment_counter("route_cache_hit_total", value=2)
        
        assert tracker._task_metrics["route_cache_hit_total"] == 3
    
    def test_increment_counter_invalid_key(self, tracker):
        """Test incrementing invalid counter key."""
        # Should not raise, just log warning
        tracker.increment_counter("invalid_key")
        assert "invalid_key" not in tracker._task_metrics
    
    def test_append_latency(self, tracker):
        """Test appending latency samples."""
        tracker.append_latency("fast_path_latency_ms", 50.0)
        tracker.append_latency("fast_path_latency_ms", 75.0)
        
        assert len(tracker._task_metrics["fast_path_latency_ms"]) == 2
        assert tracker._task_metrics["fast_path_latency_ms"][0] == 50.0
        assert tracker._task_metrics["fast_path_latency_ms"][1] == 75.0
    
    def test_append_latency_invalid_key(self, tracker):
        """Test appending to invalid latency key."""
        # Should not raise, just log warning
        tracker.append_latency("invalid_key", 50.0)
        assert "invalid_key" not in tracker._task_metrics
    
    def test_get_metrics(self, tracker):
        """Test getting metrics with computed aggregates."""
        # Add some metrics
        tracker.track_routing_decision("fast")
        tracker.track_routing_decision("planner")
        tracker.track_routing_decision("hgnn", has_plan=True)
        tracker.track_metrics("fast", success=True, latency_ms=50.0)
        tracker.track_metrics("fast", success=True, latency_ms=75.0)
        
        metrics = tracker.get_metrics()
        
        # Check basic metrics
        assert metrics["fast_routed_total"] == 1
        assert metrics["planner_routed_total"] == 1
        assert metrics["hgnn_routed_total"] == 1
        
        # Check computed rates
        assert "fast_routed_rate" in metrics
        assert "planner_routed_rate" in metrics
        assert "hgnn_routed_rate" in metrics
        assert metrics["fast_routed_rate"] == pytest.approx(1.0 / 3.0)
        
        # Check latency averages
        assert "fast_path_latency_avg_ms" in metrics
        assert metrics["fast_path_latency_avg_ms"] == pytest.approx(62.5)
        
        # Check timestamp
        assert "export_ts" in metrics
        assert isinstance(metrics["export_ts"], float)
    
    def test_get_metrics_empty(self, tracker):
        """Test getting metrics when no data exists."""
        metrics = tracker.get_metrics()
        
        assert metrics["total_tasks"] == 0
        assert metrics.get("fast_routed_rate") is None or metrics["fast_routed_rate"] == 0
        assert "export_ts" in metrics
    
    def test_get_metadata(self, tracker):
        """Test getting tracker metadata."""
        metadata = tracker.get_metadata()
        
        assert "initialized_at" in metadata
        assert "uptime_seconds" in metadata
        assert "last_reset_at" in metadata
        assert "latency_reservoir_size" in metadata
        assert "total_metrics_count" in metadata
        assert "counter_metrics_count" in metadata
        assert "latency_metrics_count" in metadata
        assert "exporter_configured" in metadata
        assert "exporter_health" in metadata
        
        assert metadata["last_reset_at"] is None
        assert metadata["latency_reservoir_size"] == 100
        assert metadata["exporter_configured"] is False
        assert metadata["exporter_health"] is None
        assert metadata["uptime_seconds"] >= 0
    
    def test_get_metadata_with_exporter(self):
        """Test getting metadata with exporter configured."""
        exporter = LoggingExporter()
        tracker = MetricsTracker(exporter=exporter)
        
        metadata = tracker.get_metadata()
        
        assert metadata["exporter_configured"] is True
        assert metadata["exporter_health"] is not None
        assert metadata["exporter_health"]["type"] == "LoggingExporter"
        assert metadata["exporter_health"]["healthy"] is True
    
    def test_reset(self, tracker):
        """Test resetting metrics."""
        # Add some metrics
        tracker.track_routing_decision("fast")
        tracker.track_metrics("fast", success=True, latency_ms=50.0)
        
        # Verify metrics exist
        assert tracker._task_metrics["fast_routed_total"] == 1
        assert tracker._task_metrics["total_tasks"] == 1
        
        # Reset
        tracker.reset()
        
        # Verify all metrics are zero
        assert tracker._task_metrics["fast_routed_total"] == 0
        assert tracker._task_metrics["total_tasks"] == 0
        assert len(tracker._task_metrics["fast_path_latency_ms"]) == 0
        assert tracker._last_reset_at is not None
        
        # Verify metadata shows reset
        metadata = tracker.get_metadata()
        assert metadata["last_reset_at"] is not None
    
    def test_latency_reservoir_bounded(self):
        """Test that latency reservoirs are bounded."""
        tracker = MetricsTracker(latency_reservoir_size=5)
        
        # Add more samples than reservoir size
        for i in range(10):
            tracker.append_latency("fast_path_latency_ms", float(i))
        
        # Should only retain last 5 samples
        assert len(tracker._task_metrics["fast_path_latency_ms"]) == 5
        assert tracker._task_metrics["fast_path_latency_ms"][0] == 5.0  # First retained value
        assert tracker._task_metrics["fast_path_latency_ms"][-1] == 9.0  # Last value
    
    def test_thread_safety(self):
        """Test thread-safety of concurrent operations."""
        tracker = MetricsTracker()
        num_threads = 10
        operations_per_thread = 100
        
        def track_operations():
            for _ in range(operations_per_thread):
                tracker.track_routing_decision("fast")
                tracker.track_metrics("fast", success=True, latency_ms=50.0)
                tracker.increment_counter("route_cache_hit_total")
        
        threads = []
        for _ in range(num_threads):
            thread = threading.Thread(target=track_operations)
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        # Verify all operations were recorded
        expected_fast_routed = num_threads * operations_per_thread
        expected_tasks = num_threads * operations_per_thread
        expected_cache_hits = num_threads * operations_per_thread
        
        assert tracker._task_metrics["fast_routed_total"] == expected_fast_routed
        assert tracker._task_metrics["total_tasks"] == expected_tasks
        assert tracker._task_metrics["route_cache_hit_total"] == expected_cache_hits

