"""
Hyperparameter Tuning Configuration for SeedCore ML Models

This module defines search spaces and configurations for hyperparameter tuning
using Ray Tune, specifically for XGBoost models in the SeedCore platform.
"""

from ray import tune
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# Default XGBoost search space for hyperparameter tuning
XGBOOST_SEARCH_SPACE = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "tree_method": "hist",
    # Learning Rate (eta) from 0.01 to 0.2
    "eta": tune.loguniform(1e-2, 2e-1),
    # Tree depth from 4 to 10
    "max_depth": tune.randint(4, 11),
    # Subsample ratio of columns and rows
    "subsample": tune.uniform(0.6, 0.9),
    "colsample_bytree": tune.uniform(0.6, 0.9),
    # L1 and L2 regularization
    "lambda": tune.uniform(1.0, 4.0),
    "alpha": tune.uniform(0.0, 3.0),
    # Number of boosting rounds (can be tuned but often fixed)
    "num_boost_round": 200,
    # Early stopping rounds
    "early_stopping_rounds": 10,
}

# Conservative search space for quick tuning
XGBOOST_CONSERVATIVE_SPACE = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "tree_method": "hist",
    "eta": tune.loguniform(5e-2, 1.5e-1),
    "max_depth": tune.randint(4, 8),
    "subsample": tune.uniform(0.7, 0.9),
    "colsample_bytree": tune.uniform(0.7, 0.9),
    "lambda": tune.uniform(1.0, 3.0),
    "alpha": tune.uniform(0.0, 2.0),
    "num_boost_round": 20,  # Reduced for faster testing
    "early_stopping_rounds": 5,  # Reduced for faster testing
}

# Aggressive search space for extensive tuning
XGBOOST_AGGRESSIVE_SPACE = {
    "objective": "binary:logistic",
    "eval_metric": ["logloss", "auc"],
    "tree_method": "hist",
    "eta": tune.loguniform(1e-3, 3e-1),
    "max_depth": tune.randint(3, 12),
    "subsample": tune.uniform(0.5, 1.0),
    "colsample_bytree": tune.uniform(0.5, 1.0),
    "colsample_bylevel": tune.uniform(0.5, 1.0),
    "lambda": tune.uniform(0.1, 5.0),
    "alpha": tune.uniform(0.0, 5.0),
    "gamma": tune.uniform(0.0, 1.0),
    "min_child_weight": tune.uniform(1.0, 10.0),
    "num_boost_round": tune.randint(100, 300),
    "early_stopping_rounds": 15,
}

# Default tuning configuration
DEFAULT_TUNE_CONFIG = {
    "num_samples": 50,  # Number of different hyperparameter sets to try
    "max_concurrent_trials": 4,  # Maximum concurrent trials
    "time_budget_s": 3600,  # 1 hour time budget
    "grace_period": 10,  # Minimum training iterations before early stopping
    "reduction_factor": 2,  # ASHA reduction factor
}

# Conservative tuning configuration
CONSERVATIVE_TUNE_CONFIG = {
    "num_samples": 5,  # Reduced for faster testing
    "max_concurrent_trials": 2,
    "time_budget_s": 600,  # 10 minutes
    "grace_period": 5,
    "reduction_factor": 2,
}

# Aggressive tuning configuration
AGGRESSIVE_TUNE_CONFIG = {
    "num_samples": 100,
    "max_concurrent_trials": 8,
    "time_budget_s": 7200,  # 2 hours
    "grace_period": 15,
    "reduction_factor": 3,
}

def get_search_space(space_type: str = "default") -> Dict[str, Any]:
    """
    Get the search space configuration based on the specified type.
    
    Args:
        space_type: Type of search space ("default", "conservative", "aggressive")
        
    Returns:
        Dictionary containing the search space configuration
    """
    spaces = {
        "default": XGBOOST_SEARCH_SPACE,
        "conservative": XGBOOST_CONSERVATIVE_SPACE,
        "aggressive": XGBOOST_AGGRESSIVE_SPACE,
    }
    
    if space_type not in spaces:
        logger.warning(f"Unknown space type '{space_type}', using default")
        space_type = "default"
    
    return spaces[space_type]

def get_tune_config(config_type: str = "default") -> Dict[str, Any]:
    """
    Get the tuning configuration based on the specified type.
    
    Args:
        config_type: Type of tuning config ("default", "conservative", "aggressive")
        
    Returns:
        Dictionary containing the tuning configuration
    """
    configs = {
        "default": DEFAULT_TUNE_CONFIG,
        "conservative": CONSERVATIVE_TUNE_CONFIG,
        "aggressive": AGGRESSIVE_TUNE_CONFIG,
    }
    
    if config_type not in configs:
        logger.warning(f"Unknown config type '{config_type}', using default")
        config_type = "default"
    
    return configs[config_type] 