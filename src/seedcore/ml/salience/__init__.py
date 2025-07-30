"""
Salience Scoring Module

Provides ML-based salience scoring for ranking and prioritizing:
- System events and alerts
- Resource utilization patterns
- User interactions and behaviors
"""

from .scorer import SalienceScorer, SalienceModel

__all__ = ["SalienceScorer", "SalienceModel"] 