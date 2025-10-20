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

from .schemas.eventizer_models import (
    EventizerRequest,
    EventizerResponse,
    EventTags,
    EventAttributes,
    EventizerConfig,
)
from .fact_dao import FactDAO
from .eventizer_features import features_from_payload

__all__ = [
    "EventizerRequest", 
    "EventizerResponse",
    "EventTags",
    "EventAttributes",
    "EventizerConfig",
    "FactDAO",
    "features_from_payload",
]
