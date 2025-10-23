"""Core telemetry and embedding functionality."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from typing import Any, Dict, Optional, Deque

logger = logging.getLogger(__name__)


class MetricsTracker:
    """
    Comprehensive metrics tracker for coordinator operations.

    Tracks:
      - Routing decisions: fast / planner / hgnn (and whether a plan existed for hgnn)
      - Dispatch results per route: ok / err
      - Route+execute latency: bounded reservoir + aggregates

    Thread-safety:
      - Uses a single asyncio.Lock to protect shared state.
      - If used from sync code, you can ignore the lock (best-effort); or wrap updates using asyncio.run_coroutine_threadsafe in your loop.
    """

    # Supported enums (kept simple & open-ended but validated)
    ROUTES = {"fast", "planner", "hgnn"}
    STATUSES = {"ok", "err"}

    def __init__(self, *, latency_reservoir_size: int = 512) -> None:
        # Routing decision counters
        self._fast_routed_total: int = 0
        self._planner_routed_total: int = 0
        self._hgnn_routed_total: int = 0
        self._hgnn_routed_with_plan_total: int = 0  # only when has_plan=True

        # Dispatch outcome counters per route
        self._dispatch_ok: Dict[str, int] = {r: 0 for r in self.ROUTES}
        self._dispatch_err: Dict[str, int] = {r: 0 for r in self.ROUTES}

        # Latency metrics
        self._latency_samples: Deque[float] = deque(maxlen=max(32, latency_reservoir_size))
        self._latency_count: int = 0
        self._latency_sum: float = 0.0
        self._latency_sum_sq: float = 0.0
        self._latency_min: float = math.inf
        self._latency_max: float = -math.inf

        # Concurrency guard
        self._lock = asyncio.Lock()

    # -------------------------------
    # Routing metrics
    # -------------------------------
    async def track_routing_decision_async(self, decision: str, *, has_plan: bool = False) -> None:
        """Async-safe router decision recording."""
        decision = (decision or "").lower().strip()
        if decision not in self.ROUTES:
            logger.warning("Unknown routing decision: %r", decision)
            return
        async with self._lock:
            if decision == "fast":
                self._fast_routed_total += 1
            elif decision == "planner":
                self._planner_routed_total += 1
            elif decision == "hgnn":
                self._hgnn_routed_total += 1
                if has_plan:
                    self._hgnn_routed_with_plan_total += 1

    def track_routing_decision(self, decision: str, *, has_plan: bool = False) -> None:
        """Sync-friendly wrapper."""
        # Best-effort without lock to minimize overhead in hot path.
        decision = (decision or "").lower().strip()
        if decision not in self.ROUTES:
            logger.warning("Unknown routing decision: %r", decision)
            return
        if decision == "fast":
            self._fast_routed_total += 1
        elif decision == "planner":
            self._planner_routed_total += 1
        elif decision == "hgnn":
            self._hgnn_routed_total += 1
            if has_plan:
                self._hgnn_routed_with_plan_total += 1

    # -------------------------------
    # Dispatch metrics
    # -------------------------------
    async def record_dispatch_async(self, route: str, status: str) -> None:
        route = (route or "").lower().strip()
        status = (status or "").lower().strip()
        if route not in self.ROUTES:
            logger.warning("Unknown dispatch route: %r", route)
            return
        if status not in self.STATUSES:
            logger.warning("Unknown dispatch status: %r", status)
            return
        async with self._lock:
            if status == "ok":
                self._dispatch_ok[route] += 1
            else:
                self._dispatch_err[route] += 1

    def record_dispatch(self, route: str, status: str) -> None:
        route = (route or "").lower().strip()
        status = (status or "").lower().strip()
        if route not in self.ROUTES:
            logger.warning("Unknown dispatch route: %r", route)
            return
        if status not in self.STATUSES:
            logger.warning("Unknown dispatch status: %r", status)
            return
        if status == "ok":
            self._dispatch_ok[route] += 1
        else:
            self._dispatch_err[route] += 1

    # -------------------------------
    # Latency metrics
    # -------------------------------
    async def record_route_latency_async(self, latency_ms: float) -> None:
        val = float(latency_ms)
        if not math.isfinite(val) or val < 0:
            logger.warning("Invalid latency value (ms): %r", latency_ms)
            return
        async with self._lock:
            self._latency_samples.append(val)
            self._latency_count += 1
            self._latency_sum += val
            self._latency_sum_sq += val * val
            self._latency_min = min(self._latency_min, val)
            self._latency_max = max(self._latency_max, val)

    def record_route_latency(self, latency_ms: float) -> None:
        val = float(latency_ms)
        if not math.isfinite(val) or val < 0:
            logger.warning("Invalid latency value (ms): %r", latency_ms)
            return
        self._latency_samples.append(val)
        self._latency_count += 1
        self._latency_sum += val
        self._latency_sum_sq += val * val
        self._latency_min = min(self._latency_min, val)
        self._latency_max = max(self._latency_max, val)

    # -------------------------------
    # Summary
    # -------------------------------
    def _latency_snapshot(self) -> Dict[str, Any]:
        n = self._latency_count
        if n == 0:
            return {
                "count": 0,
                "min_ms": None,
                "max_ms": None,
                "mean_ms": None,
                "stdev_ms": None,
                "last_n": 0,
                "p50_ms": None,
                "p90_ms": None,
                "p95_ms": None,
                "p99_ms": None,
            }
        mean = self._latency_sum / n
        # Unbiased sample variance if n>1
        stdev = None
        if n > 1:
            var = max((self._latency_sum_sq - n * mean * mean) / (n - 1), 0.0)
            stdev = math.sqrt(var)

        # Percentiles computed from reservoir (bounded)
        samples = list(self._latency_samples)
        samples.sort()
        def pct(p: float) -> float:
            if not samples:
                return None
            k = (len(samples) - 1) * p
            f = math.floor(k)
            c = min(f + 1, len(samples) - 1)
            if f == c:
                return samples[f]
            return samples[f] + (samples[c] - samples[f]) * (k - f)

        return {
            "count": n,
            "min_ms": self._latency_min if self._latency_min != math.inf else None,
            "max_ms": self._latency_max if self._latency_max != -math.inf else None,
            "mean_ms": mean,
            "stdev_ms": stdev,
            "last_n": len(samples),
            "p50_ms": pct(0.50),
            "p90_ms": pct(0.90),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
        }

    def get_metrics(self) -> Dict[str, Any]:
        """Return a stable schema for exporting/printing."""
        return {
            "routing": {
                "fast_routed_total": self._fast_routed_total,
                "planner_routed_total": self._planner_routed_total,
                "hgnn_routed_total": self._hgnn_routed_total,
                "hgnn_routed_with_plan_total": self._hgnn_routed_with_plan_total,
            },
            "dispatch": {
                "fast": {
                    "ok_total": self._dispatch_ok["fast"],
                    "err_total": self._dispatch_err["fast"],
                },
                "planner": {
                    "ok_total": self._dispatch_ok["planner"],
                    "err_total": self._dispatch_err["planner"],
                },
                "hgnn": {
                    "ok_total": self._dispatch_ok["hgnn"],
                    "err_total": self._dispatch_err["hgnn"],
                },
            },
            "latency_ms": self._latency_snapshot(),
            "export_ts": time.time(),
        }


# -----------------------------------------------------------------------------
# Convenience helpers (stable, minimal API surface)
# -----------------------------------------------------------------------------

def record_dispatch_metrics(metrics_tracker: MetricsTracker, route: str, status: str) -> None:
    """Record dispatch metrics."""
    metrics_tracker.record_dispatch(route, status)


def record_route_latency(metrics_tracker: MetricsTracker, latency_ms: float) -> None:
    """Record route and execute latency."""
    metrics_tracker.record_route_latency(latency_ms)


def get_metrics_summary(metrics_tracker: MetricsTracker) -> Dict[str, Any]:
    """Get comprehensive metrics summary."""
    return metrics_tracker.get_metrics()
