"""
Pydantic models for XGBoost API endpoints.

This module defines the request and response models for the XGBoost service API.
"""

from pydantic import BaseModel, Field, field_validator, model_validator  # pyright: ignore[reportMissingImports]
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from datetime import datetime

# Allowed evaluation metrics for XGBoost
ALLOWED_METRICS = {
    "logloss", "auc", "rmse", "mae", "error", "merror", "mlogloss",
    "ndcg", "map", "poisson-nloglik", "gamma-nloglik", "cox-nloglik",
    "gamma-deviance", "tweedie-nloglik", "aucpr"
}

class ModelObjective(str, Enum):
    """XGBoost objective functions."""
    BINARY_LOGISTIC = "binary:logistic"
    MULTI_SOFTMAX = "multi:softmax"
    MULTI_SOFTPROB = "multi:softprob"
    REG_SQUARED_ERROR = "reg:squarederror"
    REG_LOGISTIC = "reg:logistic"

class TreeMethod(str, Enum):
    """XGBoost tree methods."""
    HIST = "hist"
    AUTO = "auto"
    EXACT = "exact"
    APPROX = "approx"

class SpaceType(str, Enum):
    """Type of hyperparameter search space."""
    DEFAULT = "default"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"

class ConfigType(str, Enum):
    """Type of tuning configuration."""
    DEFAULT = "default"
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"

class XGBoostConfigRequest(BaseModel):
    """Request model for XGBoost configuration."""
    objective: ModelObjective = Field(default=ModelObjective.BINARY_LOGISTIC, description="XGBoost objective function")
    eval_metric: List[str] = Field(default=["logloss", "auc"], description="Evaluation metrics")
    eta: float = Field(default=0.1, ge=0.0, le=1.0, description="Learning rate")
    max_depth: int = Field(default=5, ge=1, le=20, description="Maximum tree depth")
    tree_method: TreeMethod = Field(default=TreeMethod.HIST, description="Tree construction method")
    num_boost_round: int = Field(default=50, ge=1, le=1000, description="Number of boosting rounds")
    early_stopping_rounds: int = Field(default=10, ge=1, le=100, description="Early stopping rounds")

    @field_validator("eval_metric", mode="before")
    @classmethod
    def validate_metrics(cls, v):
        """Validate that all evaluation metrics are supported by XGBoost."""
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            raise ValueError("eval_metric must be a list of strings")
        for metric in v:
            if metric not in ALLOWED_METRICS:
                raise ValueError(f"Unsupported eval_metric: {metric}. Allowed metrics: {sorted(ALLOWED_METRICS)}")
        return v

class TrainingConfigRequest(BaseModel):
    """Request model for training configuration."""
    num_workers: int = Field(default=3, ge=1, le=10, description="Number of Ray workers")
    use_gpu: bool = Field(default=False, description="Whether to use GPU acceleration")
    cpu_per_worker: int = Field(default=1, ge=1, le=8, description="CPU cores per worker")
    memory_per_worker: int = Field(default=2000000000, ge=1000000000, description="Memory per worker in bytes")

class TrainModelRequest(BaseModel):
    """Request model for training a new XGBoost model."""
    data_source: Optional[str] = Field(default=None, description="Path to data source (CSV, Parquet)")
    data_format: str = Field(default="auto", description="Data format (csv, parquet, auto)")
    use_sample_data: bool = Field(default=False, description="Use synthetic sample data for testing")
    sample_size: int = Field(default=10000, ge=1000, le=100000, description="Sample dataset size")
    sample_features: int = Field(default=20, ge=5, le=100, description="Number of features in sample data")
    label_column: str = Field(default="target", description="Name of the target column")
    name: Optional[str] = Field(default=None, description="Optional name for the model")
    xgb_config: Optional[XGBoostConfigRequest] = Field(default=None, description="XGBoost hyperparameters")
    training_config: Optional[TrainingConfigRequest] = Field(default=None, description="Training configuration")

    @model_validator(mode="after")
    def validate_data_source(self):
        """Enforce mutual exclusivity between use_sample_data and data_source."""
        use_sample = self.use_sample_data
        data_source = self.data_source

        if not use_sample and not data_source:
            raise ValueError("data_source is required unless use_sample_data=true")

        if use_sample and data_source:
            raise ValueError("Cannot set data_source when use_sample_data=true")

        return self

class PredictRequest(BaseModel):
    """Request model for making predictions."""
    features: List[Union[float, int]] = Field(description="Feature vector for prediction")
    path: Optional[str] = Field(default=None, description="Path to specific model (optional)")

class BatchPredictRequest(BaseModel):
    """Request model for batch predictions."""
    data_source: str = Field(description="Path to data source for batch prediction")
    data_format: str = Field(default="auto", description="Data format")
    feature_columns: List[str] = Field(min_length=1, description="List of feature column names")
    path: Optional[str] = Field(default=None, description="Path to specific model (optional)")

    @field_validator("feature_columns")
    @classmethod
    def validate_unique_columns(cls, v):
        """Ensure feature_columns are unique and non-empty."""
        if len(v) != len(set(v)):
            raise ValueError("feature_columns must be unique")
        return v

class LoadModelRequest(BaseModel):
    """Request model for loading a model."""
    path: str = Field(description="Path to the model file")

class DeleteModelRequest(BaseModel):
    """Request model for deleting a model."""
    name: str = Field(description="Name of the model to delete")

class TrainModelResponse(BaseModel):
    """Response model for training results."""
    status: str = Field(description="Training status")
    path: str = Field(description="Path to the trained model")
    name: str = Field(description="Name of the trained model")
    training_time: float = Field(description="Training time in seconds")
    metrics: Dict[str, Any] = Field(description="Training metrics")
    config: Dict[str, Any] = Field(description="Training configuration used")
    message: Optional[str] = Field(default=None, description="Additional message")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Response timestamp")

class PredictResponse(BaseModel):
    """Response model for predictions."""
    status: str = Field(description="Prediction status")
    prediction: Union[float, List[float]] = Field(description="Prediction result(s)")
    path: str = Field(description="Path to the model used")
    confidence: Optional[float] = Field(default=None, description="Prediction confidence (if applicable)")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Response timestamp")

class BatchPredictResponse(BaseModel):
    """Response model for batch predictions."""
    status: str = Field(description="Batch prediction status")
    predictions_path: str = Field(description="Path to predictions output")
    num_predictions: int = Field(description="Number of predictions made")
    path: str = Field(description="Path to the model used")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Response timestamp")

class ModelInfoResponse(BaseModel):
    """Response model for model information."""
    status: str = Field(description="Model status")
    path: Optional[str] = Field(default=None, description="Path to current model")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Model metadata")
    message: Optional[str] = Field(default=None, description="Additional message")

class ModelListResponse(BaseModel):
    """Response model for listing models."""
    models: List[Dict[str, Any]] = Field(description="List of available models")
    total_count: int = Field(description="Total number of models")

class DeleteModelResponse(BaseModel):
    """Response model for model deletion."""
    status: str = Field(description="Deletion status")
    name: str = Field(description="Name of the deleted model")
    message: str = Field(description="Deletion message")

class ErrorResponse(BaseModel):
    """Response model for errors."""
    status: str = Field(default="error", description="Error status")
    error: str = Field(description="Error message")
    details: Optional[Dict[str, Any]] = Field(default=None, description="Error details")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Error timestamp")

class TuneRequest(BaseModel):
    """Request model for hyperparameter tuning."""
    space_type: SpaceType = Field(default=SpaceType.DEFAULT, description="Type of search space (default, conservative, aggressive)")
    config_type: ConfigType = Field(default=ConfigType.DEFAULT, description="Type of tuning config (default, conservative, aggressive)")
    custom_search_space: Optional[Dict[str, Any]] = Field(default=None, description="Custom search space (overrides space_type)")
    custom_tune_config: Optional[Dict[str, Any]] = Field(default=None, description="Custom tuning config (overrides config_type)")
    experiment_name: str = Field(default="xgboost_tuning", description="Name for the tuning experiment")

class TuneResponse(BaseModel):
    """Response model for hyperparameter tuning results."""
    status: str = Field(description="Tuning status")
    experiment_name: str = Field(description="Name of the tuning experiment")
    best_trial: Optional[Dict[str, Any]] = Field(default=None, description="Best trial information")
    promotion: Optional[Dict[str, Any]] = Field(default=None, description="Model promotion information")
    total_trials: Optional[int] = Field(default=None, description="Total number of trials")
    experiment_path: Optional[str] = Field(default=None, description="Path to experiment results")
    error: Optional[str] = Field(default=None, description="Error message if tuning failed")
    timestamp: Optional[datetime] = Field(default_factory=datetime.now, description="Response timestamp") 