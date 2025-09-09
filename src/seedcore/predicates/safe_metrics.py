"""
Safe metrics implementation with NullMetric fallback for environments without Prometheus.
"""

import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Check if metrics are enabled
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "1") == "1"

try:
    from prometheus_client import CollectorRegistry, REGISTRY, Counter, Gauge, Histogram, Summary
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    logger.warning("Prometheus client not available, using NullMetric fallback")

class NullMetric:
    """Null object pattern for metrics when Prometheus is not available."""
    
    def labels(self, **kwargs):
        return self
    
    def inc(self, *args, **kwargs):
        pass
    
    def observe(self, *args, **kwargs):
        pass
    
    def set(self, *args, **kwargs):
        pass
    
    def _value(self):
        return 0

class NullCounter(NullMetric):
    pass

class NullGauge(NullMetric):
    pass

class NullHistogram(NullMetric):
    pass

class NullSummary(NullMetric):
    pass

def create_metric_or_null(metric_type, name, description, **kwargs):
    """Create a metric or null metric based on availability."""
    if not METRICS_ENABLED or not PROMETHEUS_AVAILABLE:
        if metric_type == Counter:
            return NullCounter()
        elif metric_type == Gauge:
            return NullGauge()
        elif metric_type == Histogram:
            return NullHistogram()
        elif metric_type == Summary:
            return NullSummary()
        else:
            return NullMetric()
    
    try:
        return metric_type(name, description, **kwargs)
    except Exception as e:
        logger.warning(f"Failed to create metric {name}: {e}, using null metric")
        if metric_type == Counter:
            return NullCounter()
        elif metric_type == Gauge:
            return NullGauge()
        elif metric_type == Histogram:
            return NullHistogram()
        elif metric_type == Summary:
            return NullSummary()
        else:
            return NullMetric()

class SafeMetricsRegistry:
    """Centralized metrics registry with safe fallbacks."""
    
    def __init__(self):
        self._metrics: Dict[str, Any] = {}
        self._registry = REGISTRY if PROMETHEUS_AVAILABLE else None
    
    def get_or_create_counter(self, name: str, description: str, **kwargs) -> Any:
        """Get or create a counter metric."""
        if name not in self._metrics:
            self._metrics[name] = create_metric_or_null(Counter, name, description, **kwargs)
        return self._metrics[name]
    
    def get_or_create_gauge(self, name: str, description: str, **kwargs) -> Any:
        """Get or create a gauge metric."""
        if name not in self._metrics:
            self._metrics[name] = create_metric_or_null(Gauge, name, description, **kwargs)
        return self._metrics[name]
    
    def get_or_create_histogram(self, name: str, description: str, **kwargs) -> Any:
        """Get or create a histogram metric."""
        if name not in self._metrics:
            self._metrics[name] = create_metric_or_null(Histogram, name, description, **kwargs)
        return self._metrics[name]
    
    def get_or_create_summary(self, name: str, description: str, **kwargs) -> Any:
        """Get or create a summary metric."""
        if name not in self._metrics:
            self._metrics[name] = create_metric_or_null(Summary, name, description, **kwargs)
        return self._metrics[name]
    
    def is_enabled(self) -> bool:
        """Check if metrics are enabled."""
        return METRICS_ENABLED and PROMETHEUS_AVAILABLE
    
    def get_registry(self) -> Optional[CollectorRegistry]:
        """Get the Prometheus registry."""
        return self._registry

# Global safe registry
_safe_registry = SafeMetricsRegistry()

def get_safe_registry() -> SafeMetricsRegistry:
    """Get the global safe metrics registry."""
    return _safe_registry

def create_safe_counter(name: str, description: str, **kwargs) -> Any:
    """Create a safe counter metric."""
    return _safe_registry.get_or_create_counter(name, description, **kwargs)

def create_safe_gauge(name: str, description: str, **kwargs) -> Any:
    """Create a safe gauge metric."""
    return _safe_registry.get_or_create_gauge(name, description, **kwargs)

def create_safe_histogram(name: str, description: str, **kwargs) -> Any:
    """Create a safe histogram metric."""
    return _safe_registry.get_or_create_histogram(name, description, **kwargs)

def create_safe_summary(name: str, description: str, **kwargs) -> Any:
    """Create a safe summary metric."""
    return _safe_registry.get_or_create_summary(name, description, **kwargs)
