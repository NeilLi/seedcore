#!/usr/bin/env python3
"""
SeedCore Eventizer Package

Deterministic text processing pipeline for task classification and routing.
Provides structured tags, attributes, and confidence scores to influence
OrganismManager routing decisions.

Architecture:
- services/: Business logic for text processing and pattern matching
- schemas/: Pydantic models for inputs/outputs
- clients/: External service integrations (Presidio, etc.)
- utils/: Shared helpers for pattern compilation and text normalization

Note: EventizerService is exported from seedcore.services, not from this package.
"""

# Optional import - eventizer_features may not exist in all deployments
try:
    from .eventizer_features import features_from_payload
    __all__ = [
        "features_from_payload",
    ]
except ImportError:
    # eventizer_features not available (e.g., in test environments)
    __all__ = []
