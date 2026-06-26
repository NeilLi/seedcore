"""
SeedCore ML Models Module

This module provides model services for:
- XGBoost distributed training and inference
- Model management and persistence
- Batch and real-time prediction
"""

import logging

from .governance_student import GovernanceShadowStudent

try:
    from .xgboost_service import XGBoostService, XGBoostConfig, TrainingConfig, get_xgboost_service
    from .xgboost_models import (
        TrainModelRequest, PredictRequest, BatchPredictRequest,
        LoadModelRequest, DeleteModelRequest,
        TrainModelResponse, PredictResponse, BatchPredictResponse,
        ModelInfoResponse, ModelListResponse, DeleteModelResponse
    )
except ModuleNotFoundError as e:
    logging.getLogger(__name__).debug(f"Skipping optional XGBoost model imports in thin environment: {e}")

__all__ = [
    # Service classes
    "XGBoostService",
    "XGBoostConfig", 
    "TrainingConfig",
    "get_xgboost_service",
    "GovernanceShadowStudent",
    
    # Request models
    "TrainModelRequest",
    "PredictRequest", 
    "BatchPredictRequest",
    "LoadModelRequest",
    "DeleteModelRequest",
    
    # Response models
    "TrainModelResponse",
    "PredictResponse",
    "BatchPredictResponse", 
    "ModelInfoResponse",
    "ModelListResponse",
    "DeleteModelResponse"
]
