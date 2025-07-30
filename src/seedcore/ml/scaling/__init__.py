"""
Predictive Scaling and Resource Allocation Module

Provides ML-driven resource management for:
- Predictive scaling based on usage patterns
- Intelligent resource allocation
- Performance optimization recommendations
"""

from .predictor import ScalingPredictor
from .allocator import ResourceAllocator

__all__ = ["ScalingPredictor", "ResourceAllocator"] 