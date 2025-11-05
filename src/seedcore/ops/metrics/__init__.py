#!/usr/bin/env python3
"""
SeedCore Metrics Module (`ops.metrics`)

Centralized observability framework for tracking coordinator performance, routing
efficiency, and execution outcomes across distributed SeedCore components.

Architecture:
- tracker.py: Core metrics logic with thread-safe counters and latency tracking
- registry.py: Global singleton registry for consistent access
- schemas.py: Typed dataclasses for structured metrics categories
- exporters.py: Pluggable exporter layer (Prometheus, OpenTelemetry, Redis)

The MetricsTracker provides a lightweight, in-memory instrumentation layer that:
- Tracks routing decisions (fast/planner/HGNN)
- Monitors task execution outcomes (success/failure, latency)
- Records persistence events (proto_plan upsert, outbox enqueue)
- Measures dispatch performance (planner/HGNN success rates)
- Calculates aggregate statistics (success rates, routing ratios, latency averages)

Thread-safety:
- All operations use threading.Lock for concurrent safety
- Bounded memory via deque(maxlen=N) for latency histories
- Encapsulated operations (no direct access to internal state)

Pattern Consistency:
- Mirrors PKG module architecture with singleton registry pattern
- get_global_metrics_tracker() provides consistent access across services
- Supports exporter integration for Prometheus, OpenTelemetry, Redis

Usage:
    from seedcore.ops.metrics import get_global_metrics_tracker
    
    # Get global tracker instance
    tracker = get_global_metrics_tracker()
    
    # Track routing decisions
    tracker.track_routing_decision("fast")
    tracker.track_routing_decision("hgnn", has_plan=True)
    
    # Track execution metrics
    tracker.track_metrics("fast", success=True, latency_ms=42.0)
    tracker.track_metrics("hgnn", success=False, latency_ms=150.0)
    
    # Record persistence operations
    tracker.record_proto_plan_upsert("ok")
    tracker.record_outbox_enqueue("dup")
    
    # Get metrics snapshot
    metrics = tracker.get_metrics()
    print(f"Success rate: {metrics.get('success_rate')}")
    print(f"Fast path avg latency: {metrics.get('fast_path_latency_avg_ms')}ms")
    
    # Get metadata
    metadata = tracker.get_metadata()
    print(f"Uptime: {metadata['uptime_seconds']}s")
    print(f"Exporter health: {metadata['exporter_health']}")

Integration in Coordinator:
    The metrics module is integrated into coordinator_service.py:
    
    from seedcore.ops.metrics import get_global_metrics_tracker
    
    # In Coordinator.__init__()
    self.metrics = get_global_metrics_tracker()
    
    # Thread-safe operations
    self.metrics.increment_counter("route_cache_hit_total")
    self.metrics.track_routing_decision(decision, has_plan=has_plan)
    self.metrics.append_latency("route_remote_latency_ms", latency_ms)

See Also:
    - docs/METRICS_MODULE_OVERVIEW.md - Complete architecture documentation
    - docs/PKG_MODULE_ARCHITECTURE.md - Similar singleton pattern reference
"""

from .tracker import MetricsTracker
from .registry import (
    get_global_metrics_tracker,
    reset_global_metrics_tracker,
    set_global_metrics_tracker,
)
from .exporters import (
    MetricsExporter,
    NoOpExporter,
    LoggingExporter,
    PrometheusExporter,
    OpenTelemetryExporter,
    RedisExporter,
)
from .schemas import (
    RoutingMetrics,
    ExecutionMetrics,
    LatencyMetrics,
    DispatchMetrics,
    PersistenceMetrics,
)

__all__ = [
    # Core tracker
    "MetricsTracker",
    # Registry
    "get_global_metrics_tracker",
    "reset_global_metrics_tracker",
    "set_global_metrics_tracker",
    # Exporters
    "MetricsExporter",
    "NoOpExporter",
    "LoggingExporter",
    "PrometheusExporter",
    "OpenTelemetryExporter",
    "RedisExporter",
    # Schemas
    "RoutingMetrics",
    "ExecutionMetrics",
    "LatencyMetrics",
    "DispatchMetrics",
    "PersistenceMetrics",
]

