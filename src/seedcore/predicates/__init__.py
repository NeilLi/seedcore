"""
Predicate-based routing system for SeedCore.

This module provides a comprehensive system for:
- Canonical signal registry
- YAML-based predicate configuration
- Safe expression evaluation
- GPU guard and resource management
- Prometheus metrics integration
"""

from .signals import SIGNALS, get_signal_spec, validate_signal_value, create_signal_context
from .schema import PredicatesConfig, Rule, GpuGuard, Metadata
from .loader import load_predicates, validate_predicates
from .evaluator import PredicateEvaluator, eval_predicate
from .metrics import PredicateMetrics

__all__ = [
    "SIGNALS",
    "get_signal_spec", 
    "validate_signal_value",
    "create_signal_context",
    "PredicatesConfig",
    "Rule",
    "GpuGuard", 
    "Metadata",
    "load_predicates",
    "validate_predicates",
    "PredicateEvaluator",
    "eval_predicate",
    "PredicateMetrics"
]
