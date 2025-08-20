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
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import json
import logging
import time
import requests
import httpx
import os
import uuid
import asyncio
import math
import concurrent.futures
import threading
from typing import Tuple
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create a thread pool executor for running CPU-intensive tuning jobs
thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

@ray.remote
class StatusActor:
    """Ray Actor for managing shared job status state across threads and processes."""
    
    def __init__(self):
        self.job_status = {}
        self._lock = threading.RLock()
    
    def set_status(self, job_id: str, payload: Dict[str, Any]) -> None:
        """Set the status for a specific job."""
        with self._lock:
            # Preserve submitted_at if the update doesn't include it
            existing = self.job_status.get(job_id)
            if existing and "submitted_at" in existing and "submitted_at" not in payload:
                payload = dict(payload)
                payload["submitted_at"] = existing["submitted_at"]
            self.job_status[job_id] = payload
    
    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get the status for a specific job."""
        with self._lock:
            return self.job_status.get(job_id)
    
    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        """Get all job statuses."""
        with self._lock:
            return self.job_status.copy()
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job status."""
        with self._lock:
            if job_id in self.job_status:
                del self.job_status[job_id]
                return True
            return False
    
    def clear_all(self) -> None:
        """Clear all job statuses."""
        with self._lock:
            self.job_status.clear()

def sanitize_json(data):
    """
    Recursively cleans a dictionary or list to make it JSON compliant.
    Replaces NaN, Infinity, and -Infinity with None.
    
    Args:
        data: The data to sanitize (dict, list, or primitive type)
        
    Returns:
        Sanitized data that is JSON compliant
    """
    if isinstance(data, dict):
        return {k: sanitize_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_json(i) for i in data]
    elif isinstance(data, float):
        if math.isnan(data):
            logger.debug(f"Replacing NaN with None in JSON sanitization")
            return None
        elif math.isinf(data):
            logger.debug(f"Replacing {data} with None in JSON sanitization")
            return None
        return data
    elif isinstance(data, np.floating):
        # Handle numpy float types
        if np.isnan(data) or np.isinf(data):
            logger.debug(f"Replacing numpy {data} with None in JSON sanitization")
            return None
        return float(data)
    elif isinstance(data, np.integer):
        # Handle numpy integer types
        return int(data)
    elif isinstance(data, np.ndarray):
        # Handle numpy arrays
        return sanitize_json(data.tolist())
    return data

# Create FastAPI app for ML services
ml_app = FastAPI()

# Global status actor for shared job state (initialized in MLService.__init__)
status_actor = None

# Local in-process fallback (works even if actor is unavailable)
_local_status: Dict[str, Dict[str, Any]] = {}
_local_lock = threading.RLock()

def _status_set_local(job_id: str, payload: Dict[str, Any]) -> None:
    with _local_lock:
        _local_status[job_id] = payload

def _status_get_local(job_id: str) -> Optional[Dict[str, Any]]:
    with _local_lock:
        return _local_status.get(job_id)

def _status_all_local() -> Dict[str, Dict[str, Any]]:
    with _local_lock:
        return dict(_local_status)

def _status_set(job_id: str, payload: Dict[str, Any]) -> None:
    """Sync helper: try actor first, fallback to local dict."""
    global status_actor
    if status_actor:
        try:
            ray.get(status_actor.set_status.remote(job_id, payload))
            return
        except Exception as e:
            logger.error(f"StatusActor.set failed (falling back): {e}")
    _status_set_local(job_id, payload)

def _status_get(job_id: str) -> Optional[Dict[str, Any]]:
    """Sync helper: try actor first, fallback to local dict."""
    global status_actor
    if status_actor:
        try:
            return ray.get(status_actor.get_status.remote(job_id))
        except Exception as e:
            logger.error(f"StatusActor.get failed (falling back): {e}")
    return _status_get_local(job_id)

def _status_all() -> Dict[str, Dict[str, Any]]:
    """Sync helper: try actor first, fallback to local dict."""
    global status_actor
    if status_actor:
        try:
            return ray.get(status_actor.get_all_statuses.remote())
        except Exception as e:
            logger.error(f"StatusActor.get_all_statuses failed (falling back): {e}")
    return _status_all_local()

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
                "delete_model": "/xgboost/delete_model",
                "tune": "/xgboost/tune",
                "tune_async": {
                    "submit": "/xgboost/tune/submit",
                    "status": "/xgboost/tune/status/{job_id}",
                    "list_jobs": "/xgboost/tune/jobs"
                },
                "refresh_model": "/xgboost/refresh_model"
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
            model_name=train_request.name
        )
        
        # Sanitize the result to ensure JSON compliance
        sanitized_result = sanitize_json(result)
        
        return TrainModelResponse(**sanitized_result)
        
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
        if predict_request.path:
            success = xgb_service.load_model(predict_request.path)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to load model from {predict_request.path}")
        
        # Make prediction
        predictions = xgb_service.predict(predict_request.features)
        
        # Convert to list if single prediction
        if len(predictions) == 1:
            prediction = float(predictions[0])
        else:
            prediction = [float(p) for p in predictions]
        
        # Sanitize the prediction to ensure JSON compliance
        sanitized_prediction = sanitize_json(prediction)
        
        return PredictResponse(
            status="success",
            prediction=sanitized_prediction,
            path=xgb_service.current_model_path or "unknown"
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
        if batch_request.path:
            success = xgb_service.load_model(batch_request.path)
            if not success:
                raise HTTPException(status_code=400, detail=f"Failed to load model from {batch_request.path}")
        
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
            path=xgb_service.current_model_path or "unknown"
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
        success = xgb_service.load_model(load_request.path)
        
        if success:
            return ModelInfoResponse(
                status="success",
                path=xgb_service.current_model_path,
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
        success = xgb_service.delete_model(delete_request.name)
        
        if success:
            return DeleteModelResponse(
                status="success",
                name=delete_request.name,
                message="Model deleted successfully"
            )
        else:
            raise HTTPException(status_code=400, detail="Failed to delete model")
        
    except Exception as e:
        logger.error(f"Error deleting XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/tune")
async def run_tuning_sweep(request: Dict[str, Any]):
    """Run a hyperparameter tuning sweep using Ray Tune."""
    try:
        from src.seedcore.ml.tuning_service import get_tuning_service
        from src.seedcore.ml.models.xgboost_models import TuneRequest, TuneResponse
        
        # Validate request
        tune_request = TuneRequest(**request)
        
        # Get tuning service
        tuning_service = get_tuning_service()
        
        # Run the tuning sweep
        result = tuning_service.run_tuning_sweep(
            space_type=tune_request.space_type,
            config_type=tune_request.config_type,
            custom_search_space=tune_request.custom_search_space,
            custom_tune_config=tune_request.custom_tune_config,
            experiment_name=tune_request.experiment_name
        )
        
        # Sanitize the result to ensure JSON compliance
        sanitized_result = sanitize_json(result)
        
        return TuneResponse(**sanitized_result)
        
    except Exception as e:
        logger.error(f"Error in XGBoost tuning: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ray.remote
def _run_tuning_job_task(status_actor_handle, job_id: str, request: Dict[str, Any]):
    """Ray Task that runs the actual tuning job in the background."""
    stop_heartbeat = threading.Event()
    start_ts = time.time()

    def _heartbeat():
        """Inner function for the heartbeat thread."""
        while not stop_heartbeat.wait(5): # Wait for 5 seconds
            try:
                elapsed = int(time.time() - start_ts)
                _status_set(job_id, {
                    "status": "RUNNING", "result": None,
                    "progress": f"Running... {elapsed}s elapsed"
                })
            except Exception as e:
                logger.warning(f"Heartbeat for job {job_id} failed: {e}")

    heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat_thread.start()

    try:
        from src.seedcore.ml.tuning_service import get_tuning_service

        tuning_service = get_tuning_service()
        result = tuning_service.run_tuning_sweep(
            space_type=request.get("space_type", "default"),
            config_type=request.get("config_type", "default"),
            experiment_name=request.get("experiment_name", f"async_tuning_{job_id}")
        )

        sanitized_result = sanitize_json(result)
        _status_set(job_id, {
            "status": "COMPLETED",
            "result": sanitized_result,
            "progress": "Tuning sweep completed successfully"
        })

    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Async tuning job {job_id} failed: {error_msg}")
        _status_set(job_id, {
            "status": "FAILED",
            "result": {"error": error_msg},
            "progress": f"Tuning sweep failed: {error_msg}"
        })
    finally:
        stop_heartbeat.set()

@ml_app.post("/xgboost/tune/submit")
async def submit_tuning_job(request: Dict[str, Any], background_tasks: BackgroundTasks):
    """Submit a tuning job asynchronously by launching a Ray Task."""
    job_id = f"tune-{uuid.uuid4().hex[:8]}"

    try:
        # Initialize job status (actor or local fallback)
        await asyncio.to_thread(_status_set, job_id, {
            "status": "PENDING",
            "result": None,
            "progress": "Job submitted, waiting to start...",
            "submitted_at": time.time()
        })

        # Offload to a background thread; never blocks the event loop.
        asyncio.create_task(asyncio.to_thread(_run_tuning_job_task, status_actor, job_id, request))

    except Exception as e:
        logger.error(f"Failed to submit tuning job {job_id}: {e}")
        # Attempt to mark the job as failed if submission fails after status creation
        try:
            await asyncio.to_thread(_status_set, job_id, {
                "status": "FAILED",
                "result": {"error": f"Submission error: {e}"},
                "progress": "Failed to launch job task."
            })
        finally:
            raise HTTPException(status_code=500, detail=f"Failed to submit job: {e}")

    return {"status": "submitted", "job_id": job_id}

@ml_app.get("/xgboost/tune/status/{job_id}")
async def get_tuning_status(job_id: str):
    """Check the status of a tuning job (actor or local fallback)."""
    status = await asyncio.to_thread(_status_get, job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job ID not found")

    return sanitize_json(status)

@ml_app.get("/xgboost/tune/jobs")
async def list_tuning_jobs():
    """List all tuning jobs and their statuses (actor or local fallback)."""
    all_statuses = await asyncio.to_thread(_status_all)
    return {"total_jobs": len(all_statuses), "jobs": sanitize_json(list(all_statuses.values()))}

@ml_app.post("/xgboost/refresh_model")
async def refresh_xgboost_model():
    """Refresh the XGBoost model to use the latest promoted model from tuning."""
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        
        # Get XGBoost service
        xgb_service = get_xgboost_service()
        # Pre-flight Lipschitz audit
        try:
            meta_before = _get_energy_meta()
            if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
                return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}
        except HTTPException:
            # Energy meta unavailable; refuse refresh for safety
            return {"accepted": False, "reason": "Energy meta unavailable"}

        # Keep old model to allow rollback
        old_path = getattr(xgb_service, "current_model_path", None)

        # Refresh the model (load latest promoted)
        success = xgb_service.refresh_model()
        
        if success:
            # Post-flight audit
            meta_after = _get_energy_meta()
            if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
                # Rollback if cap violated
                if old_path:
                    try:
                        xgb_service.load_model(old_path)
                    except Exception:
                        logger.error("Rollback failed after L_tot cap violation (refresh)")
                return {"accepted": False, "reason": "Post-refresh L_tot cap violated", "meta": meta_after}

            # Log a refresh event
            _log_flywheel_event({
                "organ": "utility",
                "metric": "model_refresh",
                "model_path": xgb_service.current_model_path,
                "success": True
            })
            return {
                "accepted": True,
                "message": "Model refreshed successfully",
                "current_model_path": xgb_service.current_model_path
            }
        else:
            raise HTTPException(status_code=400, detail="Failed to refresh model")
        
    except Exception as e:
        logger.error(f"Error refreshing XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Promotion gate configuration
PROMOTION_LTOT_CAP: float = float(os.getenv("SEEDCORE_PROMOTION_LTOT_CAP", "0.98"))
E_GUARD: float = float(os.getenv("SEEDCORE_E_GUARD", "0.0"))  # require delta_E <= -E_GUARD


def _get_seedcore_api_base() -> str:
    base = os.getenv("SEEDCORE_API_ADDRESS", "localhost:8002")
    if not base.startswith("http"):
        base = f"http://{base}"
    return base


def _get_energy_meta() -> Dict[str, Any]:
    try:
        base = _get_seedcore_api_base()
        r = requests.get(f"{base}/energy/meta", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Failed to fetch /energy/meta: {e}")
        raise HTTPException(status_code=502, detail=f"Energy meta unavailable: {e}")


def _log_flywheel_event(payload: Dict[str, Any]) -> None:
    try:
        base = _get_seedcore_api_base()
        requests.post(f"{base}/energy/log", json=payload, timeout=2)
    except Exception as e:
        logger.warning(f"Failed to log flywheel event: {e}")


@ml_app.post("/xgboost/promote")
async def promote_xgboost_model(request: Dict[str, Any]):
    """Gated promotion endpoint for XGBoost models.

    Body fields:
      - model_path | candidate_uri: path/uri of the candidate model
      - delta_E: predicted energy reduction (negative is good)
      - latency_ms (optional)
      - beta_mem_new (optional)
    """
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        candidate = request.get("model_path") or request.get("candidate_uri")
        if not candidate:
            raise HTTPException(status_code=400, detail="model_path (or candidate_uri) is required")
        try:
            delta_E = float(request.get("delta_E", 0.0))
        except Exception:
            raise HTTPException(status_code=400, detail="delta_E must be a number")

        # ΔE guard: require sufficient predicted reduction
        if not (delta_E <= -E_GUARD):
            return {"accepted": False, "reason": f"ΔE guard failed (delta_E={delta_E} must be ≤ {-E_GUARD})"}

        # Pre-flight audit: ensure system is under L_tot cap now
        meta_before = _get_energy_meta()
        if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}

        # Attempt swap
        xgb_service = get_xgboost_service()
        old_path = getattr(xgb_service, "current_model_path", None)
        if not xgb_service.load_model(candidate):
            return {"accepted": False, "reason": "Failed to load candidate model"}

        # Post-flight audit
        meta_after = _get_energy_meta()
        if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            # Rollback
            if old_path:
                try:
                    xgb_service.load_model(old_path)
                except Exception:
                    logger.error("Rollback failed after L_tot cap violation")
            return {"accepted": False, "reason": "Post-promotion L_tot cap violated", "meta": meta_after}

        # Log flywheel/promotion result for observability
        event = {
            "organ": "utility",
            "metric": "flywheel_result",
            "delta_E": delta_E,
            "latency_ms": request.get("latency_ms"),
            "beta_mem_new": request.get("beta_mem_new"),
            "model_path": candidate,
            "success": True,
        }
        _log_flywheel_event(event)

        return {
            "accepted": True,
            "current_model_path": getattr(xgb_service, "current_model_path", None),
            "meta": meta_after,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during xgboost promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@serve.deployment(
    num_replicas=1,
    max_ongoing_requests=1,  # serialize within replica; avoids races
    ray_actor_options={"num_cpus": 0.1, "num_gpus": 0, "memory": 200000000}
)
@serve.ingress(ml_app)
class MLService:
    """Ray Serve deployment for ML services."""
    
    def __init__(self):
        logger.info("✅ MLService initialized successfully")
        
        # Initialize the status actor for shared job state
        global status_actor
        try:
            # Resolve a stable Ray namespace to avoid drift across workers
            ns = None
            try:
                ns = ray.get_runtime_context().namespace
            except Exception:
                ns = os.getenv("RAY_NAMESPACE", None)
            # Try to get existing status actor or create new one in the same namespace
            try:
                status_actor = ray.get_actor("job_status_actor", namespace=ns)
                logger.info(f"✅ Connected to existing status actor (ns={ns})")
            except Exception:
                status_actor = StatusActor.options(
                    name="job_status_actor",
                    lifetime="detached",
                    namespace=ns
                ).remote()
                logger.info(f"✅ Created new status actor (ns={ns})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize status actor: {e}")
            status_actor = None
        
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

def create_serve_app(args: Dict[str, Any]):
    """Create a single Ray Serve deployment."""
    # The 'args' parameter is not used here, but is required by the RayService API.
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
    
    def __init__(self, base_url: str = None):
        if base_url is None:
            # Use environment variable or default to localhost:8000 for ray-head container
            base_url = os.getenv("RAY_SERVE_ADDRESS", "localhost:8000")
            if not base_url.startswith("http"):
                base_url = f"http://{base_url}"
        self.base_url = base_url
        self.salience_endpoint = f"{self.base_url}/score/salience"
        
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
    app = create_serve_app({})
    serve.run(app) 