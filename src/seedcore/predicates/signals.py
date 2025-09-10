"""
Canonical signal registry for predicate-based routing.

This module defines the canonical names and types of all signals used in routing
predicates. Both Coordinator and other services reference this registry to ensure
consistency across the system.
"""

from dataclasses import dataclass
from typing import Dict, Type, Any, Union
import logging

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class SignalSpec:
    """Specification for a canonical signal."""
    name: str
    dtype: Type
    description: str
    unit: str = ""
    min_value: Union[float, int, None] = None
    max_value: Union[float, int, None] = None

# Canonical signal registry - the single source of truth for all signal names
SIGNALS: Dict[str, SignalSpec] = {
    # OCPS and routing signals
    "p_fast": SignalSpec(
        "p_fast", 
        float, 
        "Fast-path probability from OCPS valve",
        unit="probability",
        min_value=0.0,
        max_value=1.0
    ),
    "s_drift": SignalSpec(
        "s_drift", 
        float, 
        "Drift slice gᵀh from Neural-CUSUM drift detector (ML service)",
        unit="drift_score"
    ),
    "escalation_ratio": SignalSpec(
        "escalation_ratio", 
        float, 
        "Ratio of escalated requests to total requests",
        unit="ratio",
        min_value=0.0,
        max_value=1.0
    ),
    
    # Energy and performance signals
    "ΔE_est": SignalSpec(
        "ΔE_est", 
        float, 
        "Expected energy improvement if we mutate",
        unit="energy_delta"
    ),
    "ΔE_realized": SignalSpec(
        "ΔE_realized", 
        float, 
        "Observed energy improvement post-mutation",
        unit="energy_delta"
    ),
    "energy_cost": SignalSpec(
        "energy_cost", 
        float, 
        "Current energy cost",
        unit="energy_units"
    ),
    
    # GPU guard signals
    "gpu_queue_depth": SignalSpec(
        "gpu_queue_depth", 
        int, 
        "Number of pending GPU jobs",
        unit="count",
        min_value=0
    ),
    "gpu_concurrent_jobs": SignalSpec(
        "gpu_concurrent_jobs", 
        int, 
        "Number of active GPU jobs",
        unit="count",
        min_value=0
    ),
    "gpu_budget_remaining_s": SignalSpec(
        "gpu_budget_remaining_s", 
        float, 
        "GPU budget remaining in seconds",
        unit="seconds",
        min_value=0.0
    ),
    "gpu_guard_ok": SignalSpec(
        "gpu_guard_ok", 
        bool, 
        "Whether GPU guard allows new jobs",
        unit="boolean"
    ),
    
    # System performance signals
    "fast_path_latency_ms": SignalSpec(
        "fast_path_latency_ms", 
        float, 
        "Average fast path latency in milliseconds",
        unit="milliseconds",
        min_value=0.0
    ),
    "hgnn_latency_ms": SignalSpec(
        "hgnn_latency_ms", 
        float, 
        "Average HGNN path latency in milliseconds",
        unit="milliseconds",
        min_value=0.0
    ),
    "success_rate": SignalSpec(
        "success_rate", 
        float, 
        "Overall task success rate",
        unit="ratio",
        min_value=0.0,
        max_value=1.0
    ),
    
    # Memory and resource signals
    "memory_utilization": SignalSpec(
        "memory_utilization", 
        float, 
        "Memory utilization ratio",
        unit="ratio",
        min_value=0.0,
        max_value=1.0
    ),
    "cpu_utilization": SignalSpec(
        "cpu_utilization", 
        float, 
        "CPU utilization ratio",
        unit="ratio",
        min_value=0.0,
        max_value=1.0
    ),
    
    # Task-specific signals
    "task_priority": SignalSpec(
        "task_priority", 
        int, 
        "Task priority level",
        unit="level",
        min_value=1,
        max_value=10
    ),
    "task_complexity": SignalSpec(
        "task_complexity", 
        float, 
        "Task complexity score",
        unit="score",
        min_value=0.0,
        max_value=1.0
    ),
}

def get_signal_spec(name: str) -> SignalSpec:
    """Get signal specification by name."""
    if name not in SIGNALS:
        raise ValueError(f"Unknown signal: {name}")
    return SIGNALS[name]

def validate_signal_value(name: str, value: Any) -> bool:
    """Validate that a signal value matches its specification."""
    spec = get_signal_spec(name)
    
    # Type check
    if not isinstance(value, spec.dtype):
        logger.warning(f"Signal {name} value {value} has wrong type {type(value)}, expected {spec.dtype}")
        return False
    
    # Range checks
    if spec.min_value is not None and value < spec.min_value:
        logger.warning(f"Signal {name} value {value} below minimum {spec.min_value}")
        return False
        
    if spec.max_value is not None and value > spec.max_value:
        logger.warning(f"Signal {name} value {value} above maximum {spec.max_value}")
        return False
    
    return True

def get_all_signal_names() -> list:
    """Get all registered signal names."""
    return list(SIGNALS.keys())

def get_signals_by_type(dtype: Type) -> Dict[str, SignalSpec]:
    """Get all signals of a specific type."""
    return {name: spec for name, spec in SIGNALS.items() if spec.dtype == dtype}

def create_signal_context(**kwargs) -> Dict[str, Any]:
    """Create a signal context dictionary with validation."""
    context = {}
    for name, value in kwargs.items():
        if name in SIGNALS:
            if validate_signal_value(name, value):
                context[name] = value
            else:
                logger.warning(f"Skipping invalid signal value for {name}: {value}")
        else:
            logger.warning(f"Unknown signal name in context: {name}")
    
    return context
