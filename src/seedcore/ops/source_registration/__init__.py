"""
Source registration event projection helpers.
"""

from .normalizer import (
    SourceRegistrationNormalizationResult,
    normalize_source_registration_context,
)

__all__ = [
    "SourceRegistrationNormalizationResult",
    "normalize_source_registration_context",
]
