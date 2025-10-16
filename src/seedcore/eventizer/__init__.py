#!/usr/bin/env python3
"""
SeedCore Eventizer Service

Deterministic text processing pipeline for task classification and routing.
Provides structured tags, attributes, and confidence scores to influence
OrganismManager routing decisions.

Architecture:
- services/: Business logic for text processing and pattern matching
- schemas/: Pydantic models for inputs/outputs
- clients/: External service integrations (Presidio, etc.)
- utils/: Shared helpers for pattern compilation and text normalization
"""

from ..eventizer_service import EventizerService
from .schemas.eventizer_models import (
    EventizerRequest,
    EventizerResponse,
    EventTags,
    EventAttributes,
    EventizerConfig
)

__all__ = [
    "EventizerService",
    "EventizerRequest", 
    "EventizerResponse",
    "EventTags",
    "EventAttributes",
    "EventizerConfig"
]
