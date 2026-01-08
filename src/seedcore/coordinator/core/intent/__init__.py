"""
Intent extraction and interpretation module for Coordinator.

Architecture:
- PKG decides WHAT and IN WHAT ORDER (policy layer)
- Coordinator decides HOW and WHERE (execution layer)
- Intent is the translation layer between them

This module provides:
- Intent models (RoutingIntent, ExecutionIntent, etc.)
- Intent extractors (PKG plan → Intent)
- Intent enrichers (memory/context augmentation)
- Intent validators (safety checks)
"""

from .model import RoutingIntent, IntentSource, IntentConfidence, IntentInsight
from .extractors import PKGPlanIntentExtractor
from .enrichers import IntentEnricher
from .validators import IntentValidator
from .summary import SummaryGenerator

__all__ = [
    "RoutingIntent",
    "IntentSource",
    "IntentConfidence",
    "IntentInsight",
    "PKGPlanIntentExtractor",
    "IntentEnricher",
    "IntentValidator",
    "SummaryGenerator",
]
