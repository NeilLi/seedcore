#!/usr/bin/env python3
"""
Eventizer Utils

Shared utilities for text processing, pattern compilation, and normalization.
"""

from .text_normalizer import (
    TextNormalizer,
    SpanMap
)

from .pattern_compiler import (
    PatternCompiler,
    CompiledRegex
)

from .aho_corasick import (
    AhoCorasickTrie,
    AhoCorasickMatcher,
    OptimizedAhoCorasickMatcher,
    create_keyword_matcher,
    Match
)

from .json_schema_validator import (
    EventizerPatternsValidator,
    validate_patterns_file,
    validate_patterns_data,
    validate_enhanced_features,
    ValidationResult,
    ValidationError
)

__all__ = [
    # Text normalization
    "TextNormalizer",
    "SpanMap",
    
    # Pattern compilation
    "PatternCompiler", 
    "CompiledRegex",
    
    # Aho-Corasick keyword matching
    "AhoCorasickTrie",
    "AhoCorasickMatcher", 
    "OptimizedAhoCorasickMatcher",
    "create_keyword_matcher",
    "Match",
    
    # JSON Schema validation
    "EventizerPatternsValidator",
    "validate_patterns_file",
    "validate_patterns_data",
    "validate_enhanced_features",
    "ValidationResult",
    "ValidationError"
]
