"""
Ray Serve Application for SeedCore ML Models

This module provides a Ray Serve application that deploys:
- Salience scoring models
- Anomaly detection models
- Predictive scaling models
- XGBoost distributed training and inference
"""

from __future__ import annotations

import os
import time
import json
import math
import uuid
import asyncio
import logging
import threading
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import ray
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from ray import serve

from src.seedcore.utils.ray_utils import get_serve_urls

# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Small pool for any ad-hoc CPU work (kept for parity; most heavy work uses asyncio.to_thread)
thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)

# ---------------------------------------------------------------------
# Shared status state (Ray actor with local fallback)
# ---------------------------------------------------------------------
@ray.remote
class StatusActor:
    """Ray Actor for managing shared job status state across threads and processes."""
    def __init__(self):
        self.job_status: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def set_status(self, job_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            existing = self.job_status.get(job_id)
            if existing and "submitted_at" in existing and "submitted_at" not in payload:
                payload = dict(payload)
                payload["submitted_at"] = existing["submitted_at"]
            self.job_status[job_id] = payload

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return self.job_status.get(job_id)

    def get_all_statuses(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return self.job_status.copy()

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            if job_id in self.job_status:
                del self.job_status[job_id]
                return True
            return False

    def clear_all(self) -> None:
        with self._lock:
            self.job_status.clear()


def sanitize_json(data: Any) -> Any:
    """Recursively clean payloads to be JSON serializable and NaN/inf-safe."""
    if isinstance(data, dict):
        return {k: sanitize_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [sanitize_json(v) for v in data]
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
        return data
    if isinstance(data, np.floating):
        v = float(data)
        return None if math.isnan(v) or math.isinf(v) else v
    if isinstance(data, np.integer):
        return int(data)
    if isinstance(data, np.ndarray):
        return sanitize_json(data.tolist())
    return data


# ---------------------------------------------------------------------
# FastAPI app (ingressed by Serve)
# ---------------------------------------------------------------------
ml_app = FastAPI()

# Global status actor handle (init in MLService.__init__)
status_actor = None

# Local fallback for status (if actor not available)
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
    global status_actor
    if status_actor:
        try:
            ray.get(status_actor.set_status.remote(job_id, payload))
            return
        except Exception as e:
            logger.error(f"StatusActor.set failed (falling back): {e}")
    _status_set_local(job_id, payload)

def _status_get(job_id: str) -> Optional[Dict[str, Any]]:
    global status_actor
    if status_actor:
        try:
            return ray.get(status_actor.get_status.remote(job_id))
        except Exception as e:
            logger.error(f"StatusActor.get failed (falling back): {e}")
    return _status_get_local(job_id)

def _status_all() -> Dict[str, Dict[str, Any]]:
    global status_actor
    if status_actor:
        try:
            return ray.get(status_actor.get_all_statuses.remote())
        except Exception as e:
            logger.error(f"StatusActor.get_all_statuses failed (falling back): {e}")
    return _status_all_local()


# ---------------------------------------------------------------------
# Basic endpoints
# ---------------------------------------------------------------------
@ml_app.get("/")
async def root():
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
                    "list_jobs": "/xgboost/tune/jobs",
                },
                "refresh_model": "/xgboost/refresh_model",
            },
        },
    }

@ml_app.get("/health")
async def health_check():
    try:
        import psutil
        try:
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            xgb_status = "available" if get_xgboost_service() else "unavailable"
        except Exception:
            xgb_status = "unavailable"

        system_info = {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        }
        return {
            "status": "healthy",
            "service": "ml_serve",
            "timestamp": time.time(),
            "models": {"salience_scorer": "available", "xgboost_service": xgb_status},
            "system": system_info,
            "version": "1.0.0",
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e), "timestamp": time.time()}


# ---------------------------------------------------------------------
# Salience / anomaly / scaling (as-is)
# ---------------------------------------------------------------------
@ml_app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    try:
        features_list = request.get("features", [])
        if not features_list:
            return {"error": "No features provided", "status": "error"}

        from src.seedcore.ml.salience.scorer import SalienceScorer as MLSalienceScorer
        try:
            scorer = MLSalienceScorer()
            scores = scorer.score_features(features_list)
        except Exception as e:
            logger.error(f"Error loading salience scorer: {e}")
            scores = [0.5] * len(features_list)

        return {
            "scores": scores,
            "model": "ml_salience_scorer",
            "status": "success",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Error in salience scoring: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@ml_app.post("/detect/anomaly")
async def detect_anomaly(request: Dict[str, Any]):
    try:
        data = request.get("data", [])
        if not data:
            return {"error": "No data provided", "status": "error"}

        anomalies = []
        for i, point in enumerate(data):
            if isinstance(point, (int, float)) and point > 0.8:
                anomalies.append({"index": i, "value": point, "severity": "high"})
        return {
            "anomalies": anomalies,
            "model": "anomaly_detector",
            "status": "success",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Error in anomaly detection: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@ml_app.post("/predict/scaling")
async def predict_scaling(request: Dict[str, Any]):
    try:
        metrics = request.get("metrics", {})
        if not metrics:
            return {"error": "No metrics provided", "status": "error"}

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
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Error in scaling prediction: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}


# ---------------------------------------------------------------------
# XGBoost (main API under /xgboost/*)
# ---------------------------------------------------------------------
@ml_app.post("/xgboost/train")
async def train_xgboost_model(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_models import TrainModelRequest, TrainModelResponse
        from src.seedcore.ml.models.xgboost_service import (
            get_xgboost_service,
            TrainingConfig,
            XGBoostConfig,
        )

        train_request = TrainModelRequest(**request)
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        if train_request.use_sample_data:
            dataset = await asyncio.to_thread(
                svc.create_sample_dataset,
                train_request.sample_size,
                train_request.sample_features,
            )
        elif train_request.data_source:
            dataset = await asyncio.to_thread(
                svc.load_dataset_from_source,
                train_request.data_source,
                train_request.data_format,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="Either use_sample_data or data_source must be provided",
            )

        xgb_config = None
        training_config = None
        if train_request.xgb_config:
            cfg = train_request.xgb_config.dict()
            cfg["objective"] = cfg["objective"].value
            cfg["tree_method"] = cfg["tree_method"].value
            xgb_config = XGBoostConfig(**cfg)
        if train_request.training_config:
            training_config = TrainingConfig(**train_request.training_config.dict())

        result = await asyncio.to_thread(
            svc.train_model,
            dataset,
            train_request.label_column,
            None,
            xgb_config,
            training_config,
            train_request.name,
        )
        return TrainModelResponse(**sanitize_json(result))

    except Exception as e:
        logger.error(f"Error in XGBoost training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/predict")
async def predict_xgboost(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_models import PredictRequest, PredictResponse
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        predict_request = PredictRequest(**request)
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        if predict_request.path:
            ok = await asyncio.to_thread(svc.load_model, predict_request.path)
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to load model from {predict_request.path}",
                )

        preds = await asyncio.to_thread(svc.predict, predict_request.features)
        out = float(preds[0]) if len(preds) == 1 else [float(p) for p in preds]
        return PredictResponse(
            status="success",
            prediction=sanitize_json(out),
            path=svc.current_model_path or "unknown",
        )

    except Exception as e:
        logger.error(f"Error in XGBoost prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/batch_predict")
async def batch_predict_xgboost(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_models import (
            BatchPredictRequest,
            BatchPredictResponse,
        )
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        batch_request = BatchPredictRequest(**request)
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        if batch_request.path:
            ok = await asyncio.to_thread(svc.load_model, batch_request.path)
            if not ok:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to load model from {batch_request.path}",
                )

        dataset = await asyncio.to_thread(
            svc.load_dataset_from_source,
            batch_request.data_source,
            batch_request.data_format,
        )
        result_ds = await asyncio.to_thread(
            svc.batch_predict, dataset, batch_request.feature_columns
        )

        predictions_path = f"/data/predictions_{int(time.time())}.parquet"
        await asyncio.to_thread(result_ds.write_parquet, predictions_path)

        return BatchPredictResponse(
            status="success",
            predictions_path=predictions_path,
            num_predictions=await asyncio.to_thread(result_ds.count),
            path=svc.current_model_path or "unknown",
        )

    except Exception as e:
        logger.error(f"Error in XGBoost batch prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/load_model")
async def load_xgboost_model(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_models import LoadModelRequest, ModelInfoResponse
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        load_request = LoadModelRequest(**request)
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        ok = await asyncio.to_thread(svc.load_model, load_request.path)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to load model")

        return ModelInfoResponse(
            status="success",
            path=svc.current_model_path,
            metadata=svc.model_metadata,
            message="Model loaded successfully",
        )

    except Exception as e:
        logger.error(f"Error loading XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.get("/xgboost/list_models")
async def list_xgboost_models():
    try:
        from src.seedcore.ml.models.xgboost_models import ModelListResponse
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        models = await asyncio.to_thread(svc.list_models)
        return ModelListResponse(models=models, total_count=len(models))

    except Exception as e:
        logger.error(f"Error listing XGBoost models: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.get("/xgboost/model_info")
async def get_xgboost_model_info():
    try:
        from src.seedcore.ml.models.xgboost_models import ModelInfoResponse
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        info = await asyncio.to_thread(svc.get_model_info)
        return ModelInfoResponse(**info)

    except Exception as e:
        logger.error(f"Error getting XGBoost model info: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.delete("/xgboost/delete_model")
async def delete_xgboost_model(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_models import DeleteModelRequest, DeleteModelResponse
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service

        delete_request = DeleteModelRequest(**request)
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        ok = await asyncio.to_thread(svc.delete_model, delete_request.name)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to delete model")

        return DeleteModelResponse(
            status="success", name=delete_request.name, message="Model deleted successfully"
        )

    except Exception as e:
        logger.error(f"Error deleting XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
# Tuning + Promotion / Refresh
# ---------------------------------------------------------------------
@ml_app.post("/xgboost/tune")
async def run_tuning_sweep(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.tuning_service import get_tuning_service
        from src.seedcore.ml.models.xgboost_models import TuneRequest, TuneResponse

        tune_request = TuneRequest(**request)
        tuning_service = get_tuning_service()
        result = tuning_service.run_tuning_sweep(
            space_type=tune_request.space_type,
            config_type=tune_request.config_type,
            custom_search_space=tune_request.custom_search_space,
            custom_tune_config=tune_request.custom_tune_config,
            experiment_name=tune_request.experiment_name,
        )
        return TuneResponse(**sanitize_json(result))
    except Exception as e:
        logger.error(f"Error in XGBoost tuning: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ray.remote
def _run_tuning_job_task(status_actor_handle, job_id: str, request: Dict[str, Any]):
    stop_heartbeat = threading.Event()
    start_ts = time.time()

    def _heartbeat():
        while not stop_heartbeat.wait(5):
            try:
                elapsed = int(time.time() - start_ts)
                _status_set(job_id, {"status": "RUNNING", "result": None, "progress": f"Running... {elapsed}s elapsed"})
            except Exception as e:
                logger.warning(f"Heartbeat for job {job_id} failed: {e}")

    t = threading.Thread(target=_heartbeat, daemon=True)
    t.start()

    try:
        from src.seedcore.ml.tuning_service import get_tuning_service
        tuning_service = get_tuning_service()
        result = tuning_service.run_tuning_sweep(
            space_type=request.get("space_type", "default"),
            config_type=request.get("config_type", "default"),
            experiment_name=request.get("experiment_name", f"async_tuning_{job_id}"),
        )
        _status_set(job_id, {"status": "COMPLETED", "result": sanitize_json(result), "progress": "Tuning sweep completed successfully"})
    except Exception as e:
        msg = str(e)
        logger.error(f"Async tuning job {job_id} failed: {msg}")
        _status_set(job_id, {"status": "FAILED", "result": {"error": msg}, "progress": f"Tuning sweep failed: {msg}"})
    finally:
        stop_heartbeat.set()

@ml_app.post("/xgboost/tune/submit")
async def submit_tuning_job(request: Dict[str, Any], background_tasks: BackgroundTasks):
    job_id = f"tune-{uuid.uuid4().hex[:8]}"
    try:
        await asyncio.to_thread(
            _status_set,
            job_id,
            {"status": "PENDING", "result": None, "progress": "Job submitted, waiting to start...", "submitted_at": time.time()},
        )
        asyncio.create_task(asyncio.to_thread(_run_tuning_job_task, status_actor, job_id, request))
        return {"status": "submitted", "job_id": job_id}
    except Exception as e:
        logger.error(f"Failed to submit tuning job {job_id}: {e}")
        try:
            await asyncio.to_thread(
                _status_set, job_id, {"status": "FAILED", "result": {"error": f"Submission error: {e}"}, "progress": "Failed to launch job task."}
            )
        finally:
            raise HTTPException(status_code=500, detail=f"Failed to submit job: {e}")

@ml_app.get("/xgboost/tune/status/{job_id}")
async def get_tuning_status(job_id: str):
    status = await asyncio.to_thread(_status_get, job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job ID not found")
    return sanitize_json(status)

@ml_app.get("/xgboost/tune/jobs")
async def list_tuning_jobs():
    all_statuses = await asyncio.to_thread(_status_all)
    return {"total_jobs": len(all_statuses), "jobs": sanitize_json(list(all_statuses.values()))}

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
        import requests
        r = requests.get(f"{base}/energy/meta", timeout=3)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Failed to fetch /energy/meta: {e}")
        raise HTTPException(status_code=502, detail=f"Energy meta unavailable: {e}")

def _log_flywheel_event(payload: Dict[str, Any]) -> None:
    try:
        base = _get_seedcore_api_base()
        import requests
        requests.post(f"{base}/energy/log", json=payload, timeout=2)
    except Exception as e:
        logger.warning(f"Failed to log flywheel event: {e}")

@ml_app.post("/xgboost/refresh_model")
async def refresh_xgboost_model():
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        try:
            meta_before = _get_energy_meta()
            if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
                return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}
        except HTTPException:
            return {"accepted": False, "reason": "Energy meta unavailable"}

        old_path = getattr(svc, "current_model_path", None)
        ok = await asyncio.to_thread(svc.refresh_model)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to refresh model")

        meta_after = _get_energy_meta()
        if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            if old_path:
                try:
                    await asyncio.to_thread(svc.load_model, old_path)
                except Exception:
                    logger.error("Rollback failed after L_tot cap violation (refresh)")
            return {"accepted": False, "reason": "Post-refresh L_tot cap violated", "meta": meta_after}

        _log_flywheel_event({"organ": "utility", "metric": "model_refresh", "model_path": svc.current_model_path, "success": True})
        return {"accepted": True, "message": "Model refreshed successfully", "current_model_path": svc.current_model_path}

    except Exception as e:
        logger.error(f"Error refreshing XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/promote")
async def promote_xgboost_model(request: Dict[str, Any]):
    try:
        from src.seedcore.ml.models.xgboost_service import get_xgboost_service
        candidate = request.get("model_path") or request.get("candidate_uri")
        if not candidate:
            raise HTTPException(status_code=400, detail="model_path (or candidate_uri) is required")

        try:
            delta_E = float(request.get("delta_E", 0.0))
        except Exception:
            raise HTTPException(status_code=400, detail="delta_E must be a number")

        if not (delta_E <= -E_GUARD):
            return {"accepted": False, "reason": f"ΔE guard failed (delta_E={delta_E} must be ≤ {-E_GUARD})"}

        meta_before = _get_energy_meta()
        if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}

        svc = get_xgboost_service()
        if not svc:
            return {"accepted": False, "reason": "XGBoost service unavailable"}

        old_path = getattr(svc, "current_model_path", None)
        ok = await asyncio.to_thread(svc.load_model, candidate)
        if not ok:
            return {"accepted": False, "reason": "Failed to load candidate model"}

        meta_after = _get_energy_meta()
        if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            if old_path:
                try:
                    await asyncio.to_thread(svc.load_model, old_path)
                except Exception:
                    logger.error("Rollback failed after L_tot cap violation")
            return {"accepted": False, "reason": "Post-promotion L_tot cap violated", "meta": meta_after}

        _log_flywheel_event(
            {
                "organ": "utility",
                "metric": "flywheel_result",
                "delta_E": delta_E,
                "latency_ms": request.get("latency_ms"),
                "beta_mem_new": request.get("beta_mem_new"),
                "model_path": candidate,
                "success": True,
            }
        )
        return {"accepted": True, "current_model_path": getattr(svc, "current_model_path", None), "meta": meta_after}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during xgboost promotion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------
# Serve deployment that hosts ml_app
# ---------------------------------------------------------------------
@serve.deployment(
    num_replicas=1,
    max_ongoing_requests=32,
    ray_actor_options={
        "num_cpus": 0.1,
        "num_gpus": 0,
        "memory": 200_000_000,
    },
)
@serve.ingress(ml_app)
class MLService:
    """Ray Serve deployment for ML services (FastAPI ingress)."""

    def __init__(self):
        logger.info("✅ MLService initializing")
        global status_actor
        try:
            ns = None
            try:
                ns = ray.get_runtime_context().namespace
            except Exception:
                ns = os.getenv("RAY_NAMESPACE", None)
            try:
                status_actor = ray.get_actor("job_status_actor", namespace=ns)
                logger.info(f"✅ Connected to existing status actor (ns={ns})")
            except Exception:
                status_actor = StatusActor.options(name="job_status_actor", lifetime="detached", namespace=ns).remote()
                logger.info(f"✅ Created new status actor (ns={ns})")
        except Exception as e:
            logger.error(f"❌ Failed to initialize status actor: {e}")
            status_actor = None

        self._salience_scorer = None
        self._xgboost_service = None  # kept for possible future use
        logger.info("✅ MLService initialized")

    def _get_salience_scorer(self):
        if self._salience_scorer is None:
            try:
                from src.seedcore.ml.salience.scorer import SalienceScorer
                self._salience_scorer = SalienceScorer()
            except Exception as e:
                logger.error(f"Failed to load salience scorer: {e}")
                self._salience_scorer = None
        return self._salience_scorer


# ---------------------------------------------------------------------
# A second Serve app factory with convenience /ml_serve/xgb* endpoints
# ---------------------------------------------------------------------
def create_serve_app(args: Dict[str, Any]):
    """Create a separate Serve deployment with a small FastAPI for XGBoost convenience endpoints."""
    try:
        fastapi_app = FastAPI()

        @fastapi_app.get("/")
        async def root():
            return {"status": "ok", "message": "ml_serve is alive"}

        @fastapi_app.get("/health")
        async def health():
            return {"status": "healthy", "service": "ml_serve"}

        @fastapi_app.get("/xgb/models")
        async def list_models():
            try:
                from src.seedcore.ml.models.xgboost_service import get_xgboost_service
                svc = get_xgboost_service()
                if not svc:
                    return {"error": "XGBoost service unavailable"}
                return {"models": await asyncio.to_thread(svc.list_models)}
            except Exception as e:
                logger.exception("list_models failed")
                return {"error": f"{e}"}

        @fastapi_app.get("/xgb/model_info")
        async def model_info():
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            svc = get_xgboost_service()
            if not svc:
                return {"error": "XGBoost service unavailable"}
            return {"model_info": await asyncio.to_thread(svc.get_model_info)}

        @fastapi_app.post("/xgb")
        async def predict(request: Request):
            """Flexible predict that accepts:
               - {"features": [[...], ...]} or {"data": [[...], ...]}
               - single list: {"features": [...]}
               - dict row(s): {"data": [{"feature_0": ...}, ...]}
            """
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            svc = get_xgboost_service()
            if not svc:
                return {"error": "XGBoost service unavailable"}

            body = await request.json()
            raw = body.get("features") or body.get("data") or body

            # Normalize to 2D float matrix
            if isinstance(raw, dict):
                rows = [raw]
            else:
                rows = raw

            try:
                if rows and isinstance(rows[0], dict):
                    cols = (svc.model_metadata.get("feature_columns")
                            or [f"feature_{i}" for i in range(len(rows[0]))])
                    matrix = [[float(r.get(c, 0.0)) for c in cols] for r in rows]
                else:
                    # numeric vectors
                    if rows and isinstance(rows[0], (int, float)):
                        matrix = [rows]
                    else:
                        matrix = rows

                pred = await asyncio.to_thread(svc.predict, matrix)
                if isinstance(pred, np.ndarray):
                    pred = pred.tolist()
                return {"prediction": pred}
            except Exception as e:
                logger.exception("Prediction failed")
                return {"error": f"Failed to make prediction: {e}"}

        @fastapi_app.post("/xgb/load")
        async def xgb_load(payload: dict):
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            svc = get_xgboost_service()
            if not svc:
                return {"error": "XGBoost service unavailable"}
            path = payload.get("path") or payload.get("model_path")
            if not path:
                return {"error": "Provide 'path' (or 'model_path') to model.xgb"}
            ok = await asyncio.to_thread(svc.load_model, path)
            return {"status": "success" if ok else "error", "path": path}

        @fastapi_app.post("/xgb/refresh")
        async def xgb_refresh():
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            svc = get_xgboost_service()
            if not svc:
                return {"error": "XGBoost service unavailable"}
            ok = await asyncio.to_thread(svc.refresh_model)
            return {"status": "success" if ok else "error"}

        @fastapi_app.post("/xgb/train_sample")
        async def xgb_train_sample(payload: dict = {}):
            from src.seedcore.ml.models.xgboost_service import get_xgboost_service
            svc = get_xgboost_service()
            if not svc:
                return {"error": "XGBoost service unavailable"}

            n = int(payload.get("n_samples", 5000))
            f = int(payload.get("n_features", 20))
            label = payload.get("label_column", "target")
            name = payload.get("name") or f"quick_xgb_{int(time.time())}"

            ds = await asyncio.to_thread(svc.create_sample_dataset, n, f)
            result = await asyncio.to_thread(svc.train_model, ds, label, None, None, None, name)
            ok = await asyncio.to_thread(svc.load_model, result["path"])
            return {"trained": result, "loaded": ok}

        @serve.deployment(route_prefix="/ml_serve")
        @serve.ingress(fastapi_app)
        class MLServeWrapper:
            pass

        logger.info("✅ Ray Serve deployment (wrapper) created successfully")
        return MLServeWrapper.bind()
    except Exception as e:
        logger.error(f"Error creating Serve application: {e}")
        raise


# ---------------------------------------------------------------------
# Salience client using ray_utils constants
# ---------------------------------------------------------------------
class SalienceServiceClient:
    def __init__(self, base_url: str | None = None, base_path: str | None = None):
        import httpx
        urls = get_serve_urls(base_gateway=base_url, ml_base=base_path)
        self.base_url = urls["gateway"]
        self.salience_endpoint = urls["ml_salience"]
        self.health_endpoint = urls["ml_health"]
        self.client = httpx.Client(timeout=10.0)

    def score_salience(self, features: List[Dict[str, Any]]) -> List[float]:
        try:
            resp = self.client.post(self.salience_endpoint, json={"features": features}, headers={"Content-Type": "application/json"})
            if resp.status_code == 200:
                return resp.json().get("scores", [])
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.error(f"Salience scoring failed: {e}")
            return self._simple_fallback(features)

    def _simple_fallback(self, features: List[Dict[str, Any]]) -> List[float]:
        out = []
        for f in features:
            out.append(float(f.get("task_risk", 0.5)) * float(f.get("failure_severity", 0.5)))
        return out


# ---------------------------------------------------------------------
# Entrypoint (optional)
# ---------------------------------------------------------------------
if __name__ == "__main__":
    serve.run(MLService.bind())


# ---------------------------------------------------------------------
# Application builder function for Serve YAML
# ---------------------------------------------------------------------
def build_ml_service(args: dict):
    """Application builder for MLService (required by Serve YAML)."""
    return MLService.bind()
