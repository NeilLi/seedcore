"""Metrics exporters for pushing metrics to external systems.

This module provides pluggable exporters for metrics backends like Prometheus,
OpenTelemetry, Redis streams, or custom endpoints.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import time

logger = logging.getLogger(__name__)


class MetricsExporter(ABC):
    """Base class for metrics exporters."""
    
    @abstractmethod
    def export(self, metrics: Dict[str, Any]) -> bool:
        """
        Export metrics to external system.
        
        Args:
            metrics: Dictionary of metrics from MetricsTracker.get_metrics()
        
        Returns:
            True if export succeeded, False otherwise
        """
        pass
    
    @abstractmethod
    def flush(self) -> bool:
        """
        Flush any buffered metrics.
        
        Returns:
            True if flush succeeded, False otherwise
        """
        pass
    
    def get_health(self) -> Dict[str, Any]:
        """
        Get exporter health status.
        
        Returns:
            Dictionary with health information including:
            - type: Exporter class name
            - available: Whether the exporter is available/configured
            - healthy: Whether the exporter is healthy
        """
        return {
            "type": type(self).__name__,
            "available": True,
            "healthy": True,
        }


class NoOpExporter(MetricsExporter):
    """No-op exporter that discards metrics (default)."""
    
    def export(self, metrics: Dict[str, Any]) -> bool:
        """Discard metrics (no-op)."""
        return True
    
    def flush(self) -> bool:
        """No-op flush."""
        return True


class LoggingExporter(MetricsExporter):
    """Exporter that logs metrics to the application logger."""
    
    def __init__(self, log_level: int = logging.INFO):
        """
        Initialize logging exporter.
        
        Args:
            log_level: Logging level (default: logging.INFO)
        """
        self.log_level = log_level
    
    def export(self, metrics: Dict[str, Any]) -> bool:
        """Log metrics summary."""
        try:
            summary = {
                "total_tasks": metrics.get("total_tasks", 0),
                "success_rate": metrics.get("success_rate"),
                "fast_routed_rate": metrics.get("fast_routed_rate"),
                "hgnn_routed_rate": metrics.get("hgnn_routed_rate"),
            }
            logger.log(self.log_level, f"Metrics snapshot: {summary}")
            return True
        except Exception as e:
            logger.error(f"Failed to log metrics: {e}")
            return False
    
    def flush(self) -> bool:
        """No-op flush."""
        return True


class PrometheusExporter(MetricsExporter):
    """
    Prometheus metrics exporter (stub implementation).
    
    To use this, install the prometheus_client package:
        pip install prometheus-client
    
    Then register metrics with Prometheus registry and update them here.
    """
    
    def __init__(self, registry: Optional[Any] = None):
        """
        Initialize Prometheus exporter.
        
        Args:
            registry: Prometheus registry (optional, will create default if None)
        """
        self.registry = registry
        self._prometheus_available = False
        try:
            from prometheus_client import Counter, Histogram, Gauge, REGISTRY
            self._prometheus_available = True
            self._registry = registry or REGISTRY
            # Initialize Prometheus metrics (would be created here)
            # self._task_counter = Counter('coordinator_tasks_total', 'Total tasks')
            # etc.
        except ImportError:
            logger.warning("prometheus_client not available, PrometheusExporter disabled")
    
    def get_health(self) -> Dict[str, Any]:
        """Get Prometheus exporter health status."""
        return {
            "type": type(self).__name__,
            "available": self._prometheus_available,
            "healthy": self._prometheus_available,
        }
    
    def export(self, metrics: Dict[str, Any]) -> bool:
        """
        Export metrics to Prometheus.
        
        Note: This is a stub. Full implementation would:
        1. Update Counter metrics for totals
        2. Update Histogram metrics for latencies
        3. Update Gauge metrics for rates
        """
        if not self._prometheus_available:
            return False
        
        try:
            # Stub: would update Prometheus metrics here
            # Example:
            # self._task_counter.inc(metrics.get("total_tasks", 0))
            logger.debug("Prometheus export (stub): metrics would be exported here")
            return True
        except Exception as e:
            logger.error(f"Failed to export to Prometheus: {e}")
            return False
    
    def flush(self) -> bool:
        """No-op flush (Prometheus pulls metrics)."""
        return True


class OpenTelemetryExporter(MetricsExporter):
    """
    OpenTelemetry metrics exporter (stub implementation).
    
    To use this, install the opentelemetry packages:
        pip install opentelemetry-api opentelemetry-sdk
    """
    
    def __init__(self):
        """Initialize OpenTelemetry exporter."""
        self._otel_available = False
        try:
            from opentelemetry import metrics
            self._otel_available = True
            # Initialize OpenTelemetry metrics (would be created here)
        except ImportError:
            logger.warning("opentelemetry not available, OpenTelemetryExporter disabled")
    
    def get_health(self) -> Dict[str, Any]:
        """Get OpenTelemetry exporter health status."""
        return {
            "type": type(self).__name__,
            "available": self._otel_available,
            "healthy": self._otel_available,
        }
    
    def export(self, metrics: Dict[str, Any]) -> bool:
        """
        Export metrics to OpenTelemetry.
        
        Note: This is a stub. Full implementation would:
        1. Record counter metrics
        2. Record histogram metrics for latencies
        3. Record gauge metrics for rates
        """
        if not self._otel_available:
            return False
        
        try:
            # Stub: would record OpenTelemetry metrics here
            logger.debug("OpenTelemetry export (stub): metrics would be exported here")
            return True
        except Exception as e:
            logger.error(f"Failed to export to OpenTelemetry: {e}")
            return False
    
    def flush(self) -> bool:
        """Flush OpenTelemetry metrics."""
        return True


class RedisExporter(MetricsExporter):
    """
    Redis stream exporter for metrics (stub implementation).
    
    Pushes metrics to a Redis stream for real-time consumption.
    """
    
    def __init__(self, redis_client: Optional[Any] = None, stream_key: str = "metrics:coordinator"):
        """
        Initialize Redis exporter.
        
        Args:
            redis_client: Redis client instance (optional)
            stream_key: Redis stream key for metrics
        """
        self.redis_client = redis_client
        self.stream_key = stream_key
        self._redis_available = redis_client is not None
    
    def get_health(self) -> Dict[str, Any]:
        """Get Redis exporter health status."""
        return {
            "type": type(self).__name__,
            "available": self._redis_available,
            "healthy": self._redis_available,
        }
    
    def export(self, metrics: Dict[str, Any]) -> bool:
        """
        Export metrics to Redis stream.
        
        Note: This is a stub. Full implementation would:
        1. Serialize metrics to JSON
        2. Push to Redis stream with XADD
        """
        if not self._redis_available:
            return False
        
        try:
            # Stub: would push to Redis stream here
            # Example:
            # import json
            # self.redis_client.xadd(self.stream_key, {"metrics": json.dumps(metrics)})
            logger.debug(f"Redis export (stub): metrics would be pushed to {self.stream_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to export to Redis: {e}")
            return False
    
    def flush(self) -> bool:
        """No-op flush."""
        return True
