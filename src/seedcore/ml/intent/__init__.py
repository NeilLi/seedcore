"""
Intent Compilation Module for SeedCore

Provides deterministic natural-language → structured function call translation
using FunctionGemma as a low-latency intent compiler.

This module is designed for:
- Device/robot/automation command compilation
- Fast path inference (not cognitive reasoning)
- Deterministic JSON output (no reasoning text)
- Edge-deployable intent compilation
"""

from .intent_compiler import IntentCompiler, IntentResult, get_intent_compiler
from .schema_registry import SchemaRegistry, FunctionSchema, get_schema_registry

__all__ = [
    "IntentCompiler",
    "IntentResult",
    "get_intent_compiler",
    "SchemaRegistry",
    "FunctionSchema",
    "get_schema_registry",
]

