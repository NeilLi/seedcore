"""
SeedCore Machine Learning Module

This module provides ML-based features for:
- Salience scoring and ranking
- Pattern recognition and anomaly detection  
- Predictive scaling and resource allocation
- XGBoost distributed training and inference
"""

from . import salience
from . import patterns
from . import scaling
from . import models

__all__ = ["salience", "patterns", "scaling", "models"] 