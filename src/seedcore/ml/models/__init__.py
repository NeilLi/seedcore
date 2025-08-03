"""
SeedCore ML Models Module

This module provides model services for:
- XGBoost distributed training and inference
- Model management and persistence
- Batch and real-time prediction
"""

from .xgboost_service import XGBoostService, XGBoostConfig, TrainingConfig, get_xgboost_service
from .xgboost_models import (
    TrainModelRequest, PredictRequest, BatchPredictRequest,
    LoadModelRequest, DeleteModelRequest,
    TrainModelResponse, PredictResponse, BatchPredictResponse,
    ModelInfoResponse, ModelListResponse, DeleteModelResponse
)

__all__ = [
    # Service classes
    "XGBoostService",
    "XGBoostConfig", 
    "TrainingConfig",
    "get_xgboost_service",
    
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