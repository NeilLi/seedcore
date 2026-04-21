"""Metrics tracking for coordinator operations.

This module provides a lightweight in-memory instrumentation layer that tracks
end-to-end metrics about routing decisions, task execution outcomes, persistence
events, and dispatch operations.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, Any, Optional, TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .exporters import MetricsExporter

logger = logging.getLogger(__name__)


class MetricsTracker:
    """
    Track task execution metrics for monitoring and optimization.
    
    This tracker provides:
    - Routing decision tracking (fast/planner/escalated)
    - Task execution outcomes (success/failure, latency)
    - Outbox, dispatch, and persistence events
    - Escalated plan quality (empty vs generated)
    - Overall success and routing distribution rates
    
    Thread-safety:
    - Uses threading.Lock for thread-safe counter updates
    - Latency lists use bounded deques to prevent unbounded growth
    - Safe for concurrent access from multiple threads/coroutines
    
    Attributes:
        _lock: Thread lock for concurrent safety
        _task_metrics: Internal metrics dictionary
        _latency_reservoir_size: Maximum number of latency samples to retain
    """
    
    def __init__(self, latency_reservoir_size: int = 1000, exporter: Optional["MetricsExporter"] = None):
        """
        Initialize metrics tracker.
        
        Args:
            latency_reservoir_size: Maximum number of latency samples to retain
                per metric. Prevents unbounded memory growth.
            exporter: Optional metrics exporter for pushing metrics to external systems
        """
        self._lock = threading.Lock()
        self._latency_reservoir_size = latency_reservoir_size
        self._exporter = exporter
        self._initialized_at = time.time()
        self._last_reset_at: Optional[float] = None
        
        # Initialize metrics with thread-safe structures
        self._task_metrics = {
            # Routing metrics
            "route_cache_hit_total": 0,
            "route_remote_total": 0,
            "route_remote_latency_ms": deque(maxlen=latency_reservoir_size),
            "route_remote_fail_total": 0,
            "bulk_resolve_items": 0,
            "bulk_resolve_failed_items": 0,
            # Task totals
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            # Routing decisions (counts routing choices, not execution)
            "fast_routed_total": 0,
            "planner_routed_total": 0,
            "escalated_routed_total": 0,
            # Escalated plan generation (when routed to escalated path)
            "escalated_plan_generated_total": 0,  # Non-empty proto_plan
            "escalated_plan_empty_total": 0,       # Empty proto_plan (PKG failed)
            # Execution metrics (tracks actual pipeline runs)
            "fast_path_tasks": 0,
            "escalated_tasks": 0,
            "escalation_failures": 0,
            "fast_path_latency_ms": deque(maxlen=latency_reservoir_size),
            "escalated_latency_ms": deque(maxlen=latency_reservoir_size),
            "escalation_latency_ms": deque(maxlen=latency_reservoir_size),
            # Persistence / dispatch metrics
            "proto_plan_upsert_ok_total": 0,
            "proto_plan_upsert_err_total": 0,
            "proto_plan_upsert_truncated_total": 0,
            "outbox_embed_enqueue_ok_total": 0,
            "outbox_embed_enqueue_dup_total": 0,
            "outbox_embed_enqueue_err_total": 0,
            "dispatch_planner_ok_total": 0,
            "dispatch_planner_err_total": 0,
            "dispatch_escalated_ok_total": 0,
            "dispatch_escalated_err_total": 0,
            "route_and_execute_latency_ms": deque(maxlen=latency_reservoir_size),
            # RESULT_VERIFIER (Coordinator-embedded)
            "result_verifier_jobs_enqueued_total": 0,
            "result_verifier_jobs_processed_total": 0,
            "result_verifier_pass_total": 0,
            "result_verifier_quarantine_total": 0,
            "result_verifier_integrity_fail_total": 0,
            "result_verifier_quarantine_mutations_total": 0,
            "result_verifier_fail_closed_orphan_total": 0,
            "result_verifier_non_rct_skipped_total": 0,
            "result_verifier_stale_processing_requeued_total": 0,
            "result_verifier_retry_total": 0,
            "result_verifier_terminal_fail_total": 0,
            "result_verifier_worker_latency_ms": deque(maxlen=latency_reservoir_size),
            # Total accumulated processing time across all verifier jobs. Stored
            # in milliseconds (int) so `increment_counter` stays type-safe; the
            # Prometheus exposure name is `result_verifier_job_seconds_total`
            # and the converter divides by 1000 on export. Required for the
            # ADR 0006 CPU-pressure trigger: verifier CPU seconds as a fraction
            # of total coordinator replica CPU seconds.
            "result_verifier_job_millis_total": 0,
            # Custody graph integrity / reconciliation operations
            "custody_graph_integrity_scans_total": 0,
            "custody_graph_integrity_failures_total": 0,
            "custody_graph_reconciliations_total": 0,
            "custody_graph_reconciliation_drift_total": 0,
            "custody_graph_repairs_total": 0,
            "custody_graph_reprojections_total": 0,
            "custody_graph_batch_runs_total": 0,
            "custody_graph_batch_assets_total": 0,
            "custody_graph_batch_drift_assets_total": 0,
        }

        # Gauges store the latest observed value (not monotonic). Pre-declare
        # so `set_gauge` can guard against typos the way `increment_counter`
        # does for counters. Initialize floats at 0.0 so they serialize
        # cleanly even when nothing has set them yet.
        self._gauges: Dict[str, float] = {
            # Lag between the newest event in the twin event journal and the
            # verifier's intake watermark. Required for the ADR 0006
            # scaling-shape trigger (default freshness target: < 60s
            # sustained).
            "result_verifier_watermark_lag_seconds": 0.0,
            "custody_graph_last_integrity_issue_count": 0.0,
            "custody_graph_last_reconcile_issue_count": 0.0,
            "custody_graph_last_batch_asset_count": 0.0,
            "custody_graph_last_batch_drift_asset_count": 0.0,
        }
    
    def track_routing_decision(self, decision: str, has_plan: bool = False):
        """
        Track routing decisions (separate from execution).
        
        Args:
            decision: 'fast', 'planner', or 'escalated'
            has_plan: For the escalated path, whether proto_plan has tasks
        """
        with self._lock:
            if decision == "fast":
                self._task_metrics["fast_routed_total"] += 1
            elif decision == "planner":
                self._task_metrics["planner_routed_total"] += 1
            elif decision == "escalated":
                self._task_metrics["escalated_routed_total"] += 1
                if has_plan:
                    self._task_metrics["escalated_plan_generated_total"] += 1
                else:
                    self._task_metrics["escalated_plan_empty_total"] += 1
            else:
                logger.warning(f"Unknown routing decision: {decision}")
    
    def track_metrics(self, path: str, success: bool, latency_ms: float):
        """
        Track task execution metrics.
        
        Args:
            path: Execution path ('fast', 'escalated', 'escalated_fallback', 'escalation_failure')
            success: Whether execution succeeded
            latency_ms: Execution latency in milliseconds
        """
        with self._lock:
            self._task_metrics["total_tasks"] += 1
            if success:
                self._task_metrics["successful_tasks"] += 1
            else:
                self._task_metrics["failed_tasks"] += 1
                
            if path == "fast":
                self._task_metrics["fast_path_tasks"] += 1
                self._task_metrics["fast_path_latency_ms"].append(latency_ms)
            elif path in ["escalated", "escalated_fallback"]:
                self._task_metrics["escalated_tasks"] += 1
                self._task_metrics["escalated_latency_ms"].append(latency_ms)
            elif path == "escalation_failure":
                self._task_metrics["escalation_failures"] += 1
                self._task_metrics["escalation_latency_ms"].append(latency_ms)
    
    def record_proto_plan_upsert(self, status: str):
        """
        Record proto plan upsert operation.
        
        Args:
            status: 'ok', 'err', or 'truncated'
        """
        key = f"proto_plan_upsert_{status}_total"
        with self._lock:
            if key in self._task_metrics:
                self._task_metrics[key] += 1
    
    def record_outbox_enqueue(self, status: str):
        """
        Record outbox embedding enqueue operation.
        
        Args:
            status: 'ok', 'dup', or 'err'
        """
        key = f"outbox_embed_enqueue_{status}_total"
        with self._lock:
            if key in self._task_metrics:
                self._task_metrics[key] += 1
    
    def record_dispatch(self, route: str, status: str):
        """
        Record dispatch operation.
        
        Args:
            route: 'planner' or 'escalated'
            status: 'ok' or 'err'
        """
        key = f"dispatch_{route}_{status}_total"
        with self._lock:
            if key in self._task_metrics:
                self._task_metrics[key] += 1
    
    def record_route_latency(self, latency_ms: float):
        """
        Record route and execute latency.
        
        Args:
            latency_ms: Total latency in milliseconds
        """
        with self._lock:
            self._task_metrics["route_and_execute_latency_ms"].append(latency_ms)
    
    def increment_counter(self, key: str, value: int = 1):
        """
        Increment a counter metric (thread-safe).
        
        Args:
            key: Metric key (must exist in _task_metrics)
            value: Increment amount (default: 1)
        
        This method is provided for direct counter access that was previously
        done via `_task_metrics[key] += 1`. Use this instead of direct access.
        """
        with self._lock:
            if key in self._task_metrics and isinstance(self._task_metrics[key], int):
                self._task_metrics[key] += value
            else:
                logger.warning(f"Attempted to increment non-counter metric: {key}")
    
    def append_latency(self, key: str, latency_ms: float):
        """
        Append a latency sample (thread-safe).
        
        Args:
            key: Metric key (must be a deque-based latency metric)
            latency_ms: Latency in milliseconds
        
        This method is provided for direct latency tracking that was previously
        done via `_task_metrics[key].append(latency_ms)`. Use this instead of direct access.
        """
        with self._lock:
            if key in self._task_metrics and isinstance(self._task_metrics[key], deque):
                self._task_metrics[key].append(latency_ms)
            else:
                logger.warning(f"Attempted to append to non-latency metric: {key}")

    def set_gauge(self, key: str, value: float):
        """
        Set a gauge metric to an absolute value (thread-safe).

        Unlike counters, gauges overwrite rather than accumulate. Used for
        point-in-time values such as queue depth or watermark lag.

        Args:
            key: Gauge key (must be pre-declared in ``self._gauges``)
            value: Absolute value to record. Coerced to ``float``.
        """
        with self._lock:
            if key in self._gauges:
                try:
                    self._gauges[key] = float(value)
                except (TypeError, ValueError):
                    logger.warning(f"Ignoring non-numeric gauge value for {key}: {value!r}")
            else:
                logger.warning(f"Attempted to set unknown gauge metric: {key}")

    def get_gauge(self, key: str) -> float:
        """
        Return the current value of a pre-declared gauge (thread-safe).

        Returns ``0.0`` for unknown keys so callers can use this in telemetry
        joins without special-casing missing gauges.
        """
        with self._lock:
            return float(self._gauges.get(key, 0.0))
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        Get current task execution metrics with computed aggregates.
        
        Returns:
            Dictionary containing all metrics with computed averages and rates.
        """
        with self._lock:
            # Create a snapshot to avoid holding lock during computation
            metrics = {}
            for key, value in self._task_metrics.items():
                if isinstance(value, deque):
                    # Convert deque to list for serialization
                    metrics[key] = list(value)
                else:
                    metrics[key] = value
            # Merge gauges. They overwrite task-metric keys only if a gauge
            # name collides with a counter key, which is not allowed by
            # design; this is defensive in case a refactor introduces one.
            for key, value in self._gauges.items():
                metrics[key] = value

            # Export a seconds-view of verifier processing time alongside the
            # raw millisecond counter so PromQL can apply `rate()` directly on
            # `result_verifier_job_seconds_total`.
            metrics["result_verifier_job_seconds_total"] = (
                float(metrics.get("result_verifier_job_millis_total", 0)) / 1000.0
            )
        
        # Calculate averages (no lock needed for computation)
        if metrics.get("fast_path_latency_ms"):
            latencies = metrics["fast_path_latency_ms"]
            if latencies:
                metrics["fast_path_latency_avg_ms"] = sum(latencies) / len(latencies)
        
        if metrics.get("escalated_latency_ms"):
            latencies = metrics["escalated_latency_ms"]
            if latencies:
                metrics["escalated_latency_avg_ms"] = sum(latencies) / len(latencies)
        
        if metrics.get("escalation_latency_ms"):
            latencies = metrics["escalation_latency_ms"]
            if latencies:
                metrics["escalation_latency_avg_ms"] = sum(latencies) / len(latencies)
        
        if metrics.get("route_remote_latency_ms"):
            latencies = metrics["route_remote_latency_ms"]
            if latencies:
                metrics["route_remote_latency_avg_ms"] = sum(latencies) / len(latencies)
        
        if metrics.get("route_and_execute_latency_ms"):
            latencies = metrics["route_and_execute_latency_ms"]
            if latencies:
                metrics["route_and_execute_latency_avg_ms"] = sum(latencies) / len(latencies)
        
        # Calculate routing rates
        total_routed = (
            metrics.get("fast_routed_total", 0) +
            metrics.get("planner_routed_total", 0) +
            metrics.get("escalated_routed_total", 0)
        )
        if total_routed > 0:
            metrics["fast_routed_rate"] = metrics.get("fast_routed_total", 0) / total_routed
            metrics["planner_routed_rate"] = metrics.get("planner_routed_total", 0) / total_routed
            metrics["escalated_routed_rate"] = metrics.get("escalated_routed_total", 0) / total_routed
        
        # Calculate escalated plan success rate
        escalated_routed = metrics.get("escalated_routed_total", 0)
        if escalated_routed > 0:
            metrics["escalated_plan_success_rate"] = (
                metrics.get("escalated_plan_generated_total", 0) / escalated_routed
            )
        
        # Calculate execution success rates
        total_tasks = metrics.get("total_tasks", 0)
        if total_tasks > 0:
            metrics["success_rate"] = metrics.get("successful_tasks", 0) / total_tasks
            metrics["fast_path_rate"] = metrics.get("fast_path_tasks", 0) / total_tasks
            metrics["escalated_rate"] = metrics.get("escalated_tasks", 0) / total_tasks
        
        # Add timestamp
        metrics["export_ts"] = time.time()
        
        return metrics
    
    def reset(self):
        """Reset all metrics to zero (useful for testing)."""
        with self._lock:
            for key in self._task_metrics:
                if isinstance(self._task_metrics[key], deque):
                    self._task_metrics[key].clear()
                else:
                    self._task_metrics[key] = 0
            for key in self._gauges:
                self._gauges[key] = 0.0
            self._last_reset_at = time.time()
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Get metadata about the metrics tracker instance.
        
        Returns governance metadata similar to PKGManager for symmetry:
        - Uptime since initialization
        - Last reset timestamp (if any)
        - Exporter health status
        - Configuration parameters
        
        Returns:
            Dictionary containing metadata about the tracker instance
        """
        current_time = time.time()
        uptime_seconds = current_time - self._initialized_at
        
        with self._lock:
            # Count metrics
            counter_count = sum(
                1 for v in self._task_metrics.values()
                if isinstance(v, int)
            )
            latency_count = sum(
                1 for v in self._task_metrics.values()
                if isinstance(v, deque)
            )
            gauge_count = len(self._gauges)
            total_metrics = counter_count + latency_count + gauge_count
            
            # Get exporter health
            exporter_health = None
            if self._exporter:
                exporter_health = self._exporter.get_health()
        
        metadata = {
            "initialized_at": self._initialized_at,
            "uptime_seconds": uptime_seconds,
            "last_reset_at": self._last_reset_at,
            "latency_reservoir_size": self._latency_reservoir_size,
            "total_metrics_count": total_metrics,
            "counter_metrics_count": counter_count,
            "latency_metrics_count": latency_count,
            "gauge_metrics_count": gauge_count,
            "exporter_configured": self._exporter is not None,
            "exporter_health": exporter_health,
        }
        
        return metadata
