"""
Ray Serve Application for SeedCore ML Models

This module provides a Ray Serve application that deploys:
- Salience scoring models
- Anomaly detection models  
- Predictive scaling models
- XGBoost distributed training and inference
"""

import ray
from ray import serve
from typing import Dict, Any, List, Optional
import numpy as np
import json
import logging
import time
import requests
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app for ML services
ml_app = FastAPI()

@ml_app.get("/")
async def root():
    """Root endpoint for health checks and basic info."""
    return {
        "status": "ok",
        "service": "seedcore-ml",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "salience_scoring": "/score/salience",
            "anomaly_detection": "/detect/anomaly",
            "scaling_prediction": "/predict/scaling",
            "xgboost": {
                "train": "/xgboost/train",
                "predict": "/xgboost/predict",
                "batch_predict": "/xgboost/batch_predict",
                "load_model": "/xgboost/load_model",
                "list_models": "/xgboost/list_models",
                "model_info": "/xgboost/model_info",
                "delete_model": "/xgboost/delete_model"
            }
        }
    }

@ml_app.get("/health")
async def health_check():
    """Health check endpoint for ML Serve applications."""
    try:
        # Get system info
        import psutil
        system_info = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
        
        # Check XGBoost service status
        xgboost_status = "unavailable"
        try:
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            xgb_service = get_xgboost_service()
            if xgb_service:
                xgboost_status = "available"
        except Exception as e:
            logger.warning(f"XGBoost service not available: {e}")
        
        return {
            "status": "healthy",
            "service": "ml_serve",
            "timestamp": time.time(),
            "models": {
                "salience_scorer": "available",
                "xgboost_service": xgboost_status
            },
            "system": system_info,
            "endpoints": {
                "salience_scoring": "/score/salience",
                "anomaly_detection": "/detect/anomaly",
                "scaling_prediction": "/predict/scaling",
                "xgboost_training": "/xgboost/train",
                "xgboost_prediction": "/xgboost/predict",
                "xgboost_batch_prediction": "/xgboost/batch_predict",
                "xgboost_model_management": "/xgboost/list_models, /xgboost/model_info"
            },
            "version": "1.0.0"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

@ml_app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    """Score the salience of input data using ML model."""
    try:
        features_list = request.get("features", [])
        
        if not features_list:
            return {
                "error": "No features provided",
                "status": "error"
            }
        
        # Use ML model to score features with lazy loading
        from src.seedcore.ml.salience.scorer import SalienceScorer as MLSalienceScorer
        try:
            scorer = MLSalienceScorer()
            scores = scorer.score_features(features_list)
        except Exception as e:
            logger.error(f"Error loading salience scorer: {e}")
            # Fallback to simple scoring
            scores = [0.5] * len(features_list)
        
        return {
            "scores": scores,
            "model": "ml_salience_scorer",
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in salience scoring: {e}")
        return {
            "error": str(e),
            "status": "error",
            "timestamp": time.time()
        }

@ml_app.post("/detect/anomaly")
async def detect_anomaly(request: Dict[str, Any]):
    """Detect anomalies in input data."""
    try:
        data = request.get("data", [])
        
        if not data:
            return {
                "error": "No data provided",
                "status": "error"
            }
        
        # Simple anomaly detection (placeholder)
        anomalies = []
        for i, point in enumerate(data):
            if isinstance(point, (int, float)) and point > 0.8:
                anomalies.append({"index": i, "value": point, "severity": "high"})
        
        return {
            "anomalies": anomalies,
            "model": "anomaly_detector",
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in anomaly detection: {e}")
        return {
            "error": str(e),
            "status": "error",
            "timestamp": time.time()
        }

@ml_app.post("/predict/scaling")
async def predict_scaling(request: Dict[str, Any]):
    """Predict scaling requirements."""
    try:
        metrics = request.get("metrics", {})
        
        if not metrics:
            return {
                "error": "No metrics provided",
                "status": "error"
            }
        
        # Simple scaling prediction (placeholder)
        cpu_usage = metrics.get("cpu_usage", 0.5)
        memory_usage = metrics.get("memory_usage", 0.5)
        
        if cpu_usage > 0.8 or memory_usage > 0.8:
            recommendation = "scale_up"
        elif cpu_usage < 0.2 and memory_usage < 0.2:
            recommendation = "scale_down"
        else:
            recommendation = "maintain"
        
        return {
            "recommendation": recommendation,
            "confidence": 0.85,
            "model": "scaling_predictor",
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in scaling prediction: {e}")
        return {
            "error": str(e),
            "status": "error",
            "timestamp": time.time()
        }

# XGBoost Service Endpoints
@ml_app.post("/xgboost/train")
async def train_xgboost_model(request: Dict[str, Any]):
    """Train a new XGBoost model using distributed Ray training."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import TrainModelRequest, TrainModelResponse
        
        # Validate request
        train_request = TrainModelRequest(**request)
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Prepare dataset
        if train_request.use_sample_data:
            dataset = xgb_service.create_sample_dataset(
                n_samples=train_request.sample_size,
                n_features=train_request.sample_features
            )
        elif train_request.data_source:
            dataset = xgb_service.load_dataset_from_source(
                train_request.data_source,
                format=train_request.data_format
            )
        else:
            raise HTTPException(status_code=400, detail="Either use_sample_data or data_source must be provided")
        
        # Convert configurations
        xgb_config = None
        training_config = None
        
        if train_request.xgb_config:
            from src.seedcore.ml.models.xgboost_service import XGBoostConfig
            # Convert enum values to strings for XGBoost compatibility
            xgb_config_dict = train_request.xgb_config.dict()
            xgb_config_dict['objective'] = xgb_config_dict['objective'].value  # Convert enum to string
            xgb_config_dict['tree_method'] = xgb_config_dict['tree_method'].value  # Convert enum to string
            xgb_config = XGBoostConfig(**xgb_config_dict)
        
        if train_request.training_config:
            from src.seedcore.ml.models.xgboost_service import TrainingConfig
            training_config = TrainingConfig(**train_request.training_config.dict())
        
        # Train model
        result = xgb_service.train_model(
            dataset=dataset,
            label_column=train_request.label_column,
            xgb_config=xgb_config,
            training_config=training_config,
            model_name=train_request.model_name
        )
        
        return TrainModelResponse(**result)
        
    except Exception as e:
        logger.error(f"Error in XGBoost training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/predict")
async def predict_xgboost(request: Dict[str, Any]):
    """Make predictions using a trained XGBoost model."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import PredictRequest, PredictResponse
        
        # Validate request
        predict_request = PredictRequest(**request)
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Load model if specified
        if predict_request.model_path:
            success = xgb_service.load_model(predict_request.model_path)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to load model from {predict_request.model_path}")
        
        # Make prediction
        predictions = xgb_service.predict(predict_request.features)
        
        # Convert to list if single prediction
        if len(predictions) == 1:
            prediction = float(predictions[0])
        else:
            prediction = [float(p) for p in predictions]
        
        return PredictResponse(
            status="success",
            prediction=prediction,
            model_path=xgb_service.current_model_path or "unknown"
        )
        
    except Exception as e:
        logger.error(f"Error in XGBoost prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/batch_predict")
async def batch_predict_xgboost(request: Dict[str, Any]):
    """Make batch predictions on a dataset."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import BatchPredictRequest, BatchPredictResponse
        
        # Validate request
        batch_request = BatchPredictRequest(**request)
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Load model if specified
        if batch_request.model_path:
            success = xgb_service.load_model(batch_request.model_path)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to load model from {batch_request.model_path}")
        
        # Load dataset
        dataset = xgb_service.load_dataset_from_source(
            batch_request.data_source,
            format=batch_request.data_format
        )
        
        # Make batch predictions
        result_dataset = xgb_service.batch_predict(dataset, batch_request.feature_columns)
        
        # Save predictions to file
        predictions_path = f"/data/predictions_{int(time.time())}.parquet"
        result_dataset.write_parquet(predictions_path)
        
        return BatchPredictResponse(
            status="success",
            predictions_path=predictions_path,
            num_predictions=result_dataset.count(),
            model_path=xgb_service.current_model_path or "unknown"
        )
        
    except Exception as e:
        logger.error(f"Error in XGBoost batch prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/load_model")
async def load_xgboost_model(request: Dict[str, Any]):
    """Load a trained XGBoost model."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import LoadModelRequest, ModelInfoResponse
        
        # Validate request
        load_request = LoadModelRequest(**request)
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Load model
        success = xgb_service.load_model(load_request.model_path)
        
        if success:
            return ModelInfoResponse(
                status="success",
                model_path=xgb_service.current_model_path,
                metadata=xgb_service.model_metadata,
                message="Model loaded successfully"
            )
        else:
            raise HTTPException(status_code=400, detail="Failed to load model")
        
    except Exception as e:
        logger.error(f"Error loading XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.get("/xgboost/list_models")
async def list_xgboost_models():
    """List all available XGBoost models."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import ModelListResponse
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # List models
        models = xgb_service.list_models()
        
        return ModelListResponse(
            models=models,
            total_count=len(models)
        )
        
    except Exception as e:
        logger.error(f"Error listing XGBoost models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.get("/xgboost/model_info")
async def get_xgboost_model_info():
    """Get information about the currently loaded XGBoost model."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import ModelInfoResponse
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Get model info
        info = xgb_service.get_model_info()
        
        return ModelInfoResponse(**info)
        
    except Exception as e:
        logger.error(f"Error getting XGBoost model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.delete("/xgboost/delete_model")
async def delete_xgboost_model(request: Dict[str, Any]):
    """Delete a XGBoost model."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        from src.seedcore.ml.models.xgboost_models import DeleteModelRequest, DeleteModelResponse
        
        # Validate request
        delete_request = DeleteModelRequest(**request)
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        
        # Delete model
        success = xgb_service.delete_model(delete_request.model_name)
        
        if success:
            return DeleteModelResponse(
                status="success",
                model_name=delete_request.model_name,
                message="Model deleted successfully"
            )
        else:
            raise HTTPException(status_code=400, detail="Failed to delete model")
        
    except Exception as e:
        logger.error(f"Error deleting XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@serve.deployment(
    num_replicas=1,
    ray_actor_options={"num_cpus": 0.1, "num_gpus": 0, "memory": 200000000}
)
@serve.ingress(ml_app)
class MLService:
    """Ray Serve deployment for ML services."""
    
    def __init__(self):
        logger.info("✅ MLService initialized successfully")
        # Initialize models lazily to avoid startup issues
        self._salience_scorer = None
        self._xgboost_service = None
        
        # Initialize XGBoost service during startup
        try:
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            self._xgboost_service = get_xgboost_service()
            logger.info("✅ XGBoost service initialized during MLService startup")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize XGBoost service during startup: {e}")
            self._xgboost_service = None
    
    def _get_salience_scorer(self):
        """Lazy load salience scorer to avoid startup issues."""
        if self._salience_scorer is None:
            try:
                from src.seedcore.ml.salience.scorer import SalienceScorer
                self._salience_scorer = SalienceScorer()
            except Exception as e:
                logger.error(f"Failed to load salience scorer: {e}")
                self._salience_scorer = None
        return self._salience_scorer
    
    def _get_xgboost_service(self):
        """Get XGBoost service, initialize if needed."""
        if self._xgboost_service is None:
            try:
                from src.seedcore.ml.models.xgboost_service import get_xgboost_service
                self._xgboost_service = get_xgboost_service()
                logger.info("✅ XGBoost service initialized lazily")
            except Exception as e:
                logger.error(f"Failed to initialize XGBoost service: {e}")
                self._xgboost_service = None
        return self._xgboost_service

def create_serve_app():
    """Create a single Ray Serve deployment."""
    try:
        # Create a single deployment with FastAPI ingress
        ml_service = MLService.bind()
        
        logger.info("✅ Ray Serve deployment created successfully")
        return ml_service
        
    except Exception as e:
        logger.error(f"Error creating Serve application: {e}")
        raise

class SalienceServiceClient:
    """
    Client for interacting with the Salience ML service with circuit breaker pattern.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.salience_endpoint = f"{self.base_url}/ml/score/salience"
        
        # Circuit breaker configuration
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 60
        self.fallback_enabled = True
        
        # Circuit breaker state
        self.failure_count = 0
        self.last_failure_time = 0
        self._circuit_open = False
        
        # HTTP client
        self.client = httpx.Client(timeout=10.0)
    
    def score_salience(self, features: List[Dict[str, Any]]) -> List[float]:
        """
        Score salience using ML service with circuit breaker pattern.
        
        Args:
            features: List of feature dictionaries
            
        Returns:
            List of salience scores
        """
        if self._is_circuit_open():
            logger.warning("Circuit breaker is open, using fallback scoring")
            return self._simple_fallback(features)
        
        try:
            response = self.client.post(
                self.salience_endpoint,
                json={"features": features},
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                self.failure_count = 0  # Reset failure count on success
                return result.get("scores", [])
            else:
                raise Exception(f"HTTP {response.status_code}: {response.text}")
                
        except Exception as e:
            logger.error(f"Salience scoring failed: {e}")
            self.failure_count += 1
            
            if self.failure_count >= self.circuit_breaker_threshold:
                self._open_circuit()
            
            if self.fallback_enabled:
                return self._simple_fallback(features)
            else:
                raise
    
    def _simple_fallback(self, features: List[Dict[str, Any]]) -> List[float]:
        """Simple fallback scoring when ML service is unavailable."""
        scores = []
        for feature in features:
            task_risk = feature.get('task_risk', 0.5)
            failure_severity = feature.get('failure_severity', 0.5)
            score = task_risk * failure_severity
            scores.append(score)
        return scores
    
    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if not self._circuit_open:
            return False
        
        # Check if timeout has passed
        if time.time() - self.last_failure_time > self.circuit_breaker_timeout:
            self._close_circuit()
            return False
        
        return True
    
    def _open_circuit(self):
        """Open the circuit breaker."""
        self._circuit_open = True
        self.last_failure_time = time.time()
        logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def _close_circuit(self):
        """Close the circuit breaker."""
        self._circuit_open = False
        self.failure_count = 0
        logger.info("Circuit breaker closed")

if __name__ == "__main__":
    # For direct execution
    app = create_serve_app()
    serve.run(app) 