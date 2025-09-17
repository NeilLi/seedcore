#!/usr/bin/env python3
"""
Mock XGBoost Service for Testing

This module provides mock implementations of XGBoost service classes
to allow tests to run without requiring Ray or XGBoost dependencies.
"""

import sys
import os
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass
import logging
import tempfile
from pathlib import Path

# Mock XGBoost model
class MockXGBoostModel:
    """Mock XGBoost model for testing."""
    
    def __init__(self):
        self.booster = MockBooster()
        self.feature_names = []
        self.feature_types = []
    
    def fit(self, X, y, **kwargs):
        """Mock fit method."""
        self.feature_names = getattr(X, 'columns', [f'feature_{i}' for i in range(X.shape[1])])
        return self
    
    def predict(self, X):
        """Mock predict method - returns random predictions."""
        if hasattr(X, 'shape'):
            # Return random predictions between 0 and 1
            return np.random.random(X.shape[0])
        return np.random.random(1)
    
    def save_model(self, path):
        """Mock save_model method."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write("mock_xgboost_model")
    
    def load_model(self, path):
        """Mock load_model method."""
        return self
    
    def get_booster(self):
        """Mock get_booster method."""
        return self.booster

class MockBooster:
    """Mock XGBoost booster."""
    
    def __init__(self):
        pass
    
    def predict(self, data):
        """Mock predict method."""
        if hasattr(data, 'shape'):
            return np.random.random(data.shape[0])
        return np.random.random(1)

# Mock XGBoostConfig
@dataclass
class MockXGBoostConfig:
    """Mock XGBoost configuration."""
    num_rounds: int = 100
    max_depth: int = 6
    learning_rate: float = 0.1
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42
    n_jobs: int = 1
    use_gpu: bool = False
    tree_method: str = "hist"
    objective: str = "reg:squarederror"
    eval_metric: str = "rmse"

# Mock TrainingConfig
@dataclass
class MockTrainingConfig:
    """Mock training configuration."""
    test_size: float = 0.2
    random_state: int = 42
    stratify: bool = False
    shuffle: bool = True

# Mock XGBoostService
class MockXGBoostService:
    """Mock XGBoost service for testing."""
    
    def __init__(self, config: MockXGBoostConfig = None):
        self.config = config or MockXGBoostConfig()
        self.model = None
        self.feature_names = []
        self.is_trained = False
    
    def train(self, X, y, validation_data=None, **kwargs):
        """Mock training method."""
        logger = logging.getLogger(__name__)
        logger.info("Mock XGBoost training started...")
        
        # Store feature names
        if hasattr(X, 'columns'):
            self.feature_names = list(X.columns)
        else:
            self.feature_names = [f'feature_{i}' for i in range(X.shape[1])]
        
        # Create mock model
        self.model = MockXGBoostModel()
        self.model.fit(X, y)
        self.is_trained = True
        
        logger.info("Mock XGBoost training completed")
        
        return {
            "model": self.model,
            "feature_names": self.feature_names,
            "training_samples": len(X),
            "validation_samples": len(validation_data[0]) if validation_data else 0,
            "mse": np.random.random(),  # Mock MSE
            "r2": np.random.random(),   # Mock R²
            "training_time": 1.0        # Mock training time
        }
    
    def predict(self, X):
        """Mock prediction method."""
        if not self.is_trained:
            raise ValueError("Model must be trained before making predictions")
        
        if self.model is None:
            raise ValueError("No model available")
        
        return self.model.predict(X)
    
    def save_model(self, path):
        """Mock save model method."""
        if not self.is_trained:
            raise ValueError("Model must be trained before saving")
        
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write("mock_xgboost_model")
        
        return path
    
    def load_model(self, path):
        """Mock load model method."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"Model file not found: {path}")
        
        self.model = MockXGBoostModel()
        self.model.load_model(path)
        self.is_trained = True
        
        return self.model
    
    def get_feature_importance(self):
        """Mock feature importance method."""
        if not self.is_trained:
            return {}
        
        # Return mock feature importance
        importance = {}
        for i, feature in enumerate(self.feature_names):
            importance[feature] = np.random.random()
        
        return importance

def mock_get_xgboost_service(config=None):
    """Mock function to get XGBoost service."""
    return MockXGBoostService(config)

# Mock the modules in sys.modules
sys.modules['src.seedcore.ml.models.xgboost_service'] = type('MockXGBoostServiceModule', (), {
    'XGBoostService': MockXGBoostService,
    'XGBoostConfig': MockXGBoostConfig,
    'TrainingConfig': MockTrainingConfig,
    'get_xgboost_service': mock_get_xgboost_service
})()

print("✅ Mock XGBoost service loaded successfully")
