#!/usr/bin/env python3
"""
Eventizer Utils

Shared utilities for text processing, pattern compilation, and normalization.

Note: To avoid circular imports, modules should import directly from submodules:
- from ..eventizer.utils.text_normalizer import TextNormalizer, SpanMap
- from ..eventizer.utils.pattern_compiler import PatternCompiler, CompiledRegex
- from ..eventizer.utils.aho_corasick import create_keyword_matcher
- from ..eventizer.utils.json_schema_validator import validate_patterns_file

Do NOT import from this __init__.py as it can cause circular dependency issues.
"""

# This __init__.py intentionally left minimal to avoid circular imports.
# Import directly from submodules instead.

__all__ = []
