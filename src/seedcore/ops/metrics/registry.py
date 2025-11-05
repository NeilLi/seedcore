"""Global metrics tracker registry.

This module provides a singleton pattern for accessing the global MetricsTracker
instance, similar to the PKGManager pattern used elsewhere in the codebase.
"""

from __future__ import annotations

import threading
from typing import Optional
from .tracker import MetricsTracker

# Global singleton instance
_global_metrics_tracker: Optional[MetricsTracker] = None
_registry_lock = threading.Lock()


def get_global_metrics_tracker() -> MetricsTracker:
    """
    Get or create the global MetricsTracker instance.
    
    This function implements a thread-safe singleton pattern. The first call
    creates the instance; subsequent calls return the same instance.
    
    Returns:
        Global MetricsTracker instance
    """
    global _global_metrics_tracker
    
    if _global_metrics_tracker is None:
        with _registry_lock:
            # Double-check pattern to avoid race conditions
            if _global_metrics_tracker is None:
                _global_metrics_tracker = MetricsTracker()
    
    return _global_metrics_tracker


def reset_global_metrics_tracker():
    """
    Reset the global MetricsTracker (useful for testing).
    
    This function clears the singleton instance, allowing tests to create
    a fresh instance. Use with caution in production code.
    """
    global _global_metrics_tracker
    
    with _registry_lock:
        if _global_metrics_tracker is not None:
            _global_metrics_tracker.reset()
        _global_metrics_tracker = None


def set_global_metrics_tracker(tracker: MetricsTracker):
    """
    Set a custom MetricsTracker instance (useful for testing).
    
    Args:
        tracker: MetricsTracker instance to use as global singleton
    
    This function allows injecting a custom tracker, primarily for testing.
    """
    global _global_metrics_tracker
    
    with _registry_lock:
        _global_metrics_tracker = tracker
