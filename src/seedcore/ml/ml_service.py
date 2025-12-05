"""
Ray Serve Application for SeedCore ML Service

This module provides a comprehensive ML-as-a-Service platform deployed via Ray Serve,
offering traditional ML, gradient boosting, LLM capabilities, and Deep Graph Reasoning.

Architecture:
    The service is built on:
    - Ray Serve: Distributed deployment and scaling of ML workloads
    - FastAPI: RESTful API layer with async request handling
    - StatusActor: Ray Actor for managing shared job state across processes/threads
    - PyTorch Geometric: Backend for hypergraph and graph neural network operations

Core Capabilities:

    1. Traditional ML Models:
       - Salience Scoring (/score/salience): Computes importance scores for features
         or text using statistical and embedding-based methods
       - Anomaly Detection (/detect/anomaly): Identifies outliers and anomalous
         patterns in feature vectors or time-series data
       - Drift Scoring (/drift/score): Measures distribution shift between training
         and production data using TF-IDF and statistical methods
       - Scaling Prediction (/predict/scaling): Forecasts resource requirements and
         scaling needs based on workload patterns

    2. XGBoost Service (/xgboost/*):
       Distributed gradient boosting for structured data:
       - Training: Distributed model training with configurable hyperparameters
       - Inference: Real-time and batch prediction endpoints
       - Model Management: Load, list, delete, and promote models
       - Hyperparameter Tuning: Async job-based optimization with status tracking
       - Model Refresh: Automatic model updates with energy-based promotion gates
       - Distillation: Knowledge distillation from episodes to lightweight models

    3. LLM Capabilities (/chat, /embeddings, /rerank):
       OpenAI-compatible endpoints for language model operations:
       - Chat Completions: Conversational AI with configurable models
       - Embeddings: Text-to-vector encoding for semantic search and RAG
       - Reranking: Relevance scoring for retrieval-augmented generation

    4. Graph & Hypergraph Learning (/hgnn/*):
       Deep structural reasoning for the "Escalated" path:
       - Structural Embedding (/hgnn/embed): Converts hypergraph topology (nodes/edges)
         and anomaly snapshots into a dense vector space (hgnn_embedding). This allows
         neuro-symbolic systems to reason about where in the system architecture a
         failure occurred.
       - Causal Path Finding (/hgnn/causal-path): Identifies probable root-cause paths
         by analyzing hyperedge activation patterns during anomaly events.

Key Components:

    StatusActor (Ray Actor):
        Manages shared state for async jobs (e.g., hyperparameter tuning):
        - Thread-safe job status tracking with automatic local fallback

    Drift Detector:
        Lazy-initialized service for detecting data distribution shifts using
        statistical comparison.

    XGBoost Service:
        Singleton service for gradient boosting with energy-aware promotion gates.

    HGNN Service (Hypergraph Neural Network):
        Specialized deep learning service for structural analysis:
        - Uses incidence matrices to model high-order dependencies (shared resources,
          multi-service failures)
        - Provides the hgnn_embedding vector used by the Coordinator to seed deep reasoning
        - Optimized for inference latency using TorchScript or ONNX Runtime

Integration Points:

    Energy Service:
        Model promotion gates and flywheel event logging

    Coordinator Service:
        - Consumes /drift/score for routing decisions (Fast vs. Cognitive)
        - Consumes /hgnn/embed to generate the context vector for "Escalated" tasks

    Cognitive Service:
        Consumes /embeddings for RAG and /hgnn/causal-path for root cause analysis

Deployment:
    Deployed as a Ray Serve deployment with async request handling, background task
    support, and health/resource monitoring.

Environment Variables:
    SEEDCORE_HGNN_MODEL_PATH: Path to the pre-trained HGNN weights
    SEEDCORE_PROMOTION_LTOT_CAP: Maximum Lipschitz constant for model promotion
    SEEDCORE_E_GUARD: Energy guard threshold for promotion

Error Handling:
    - Graceful degradation: Local fallback when Ray Actor unavailable
    - Comprehensive error logging with context and HTTPException-based responses
"""

from __future__ import annotations

import os
import time
import math
import uuid
import asyncio
import threading
import concurrent.futures
from typing import Any, Dict, Optional

import numpy as np
import ray  # pyright: ignore[reportMissingImports]
from fastapi import BackgroundTasks, FastAPI, HTTPException  # pyright: ignore[reportMissingImports]
from ray import serve  # pyright: ignore[reportMissingImports]


# ---------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------
from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.ml_service.driver")
logger = ensure_serve_logger("seedcore.ml_service", level="DEBUG")

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

# Service state for startup initialization
# Runtime state (model cache, adaptive params, snapshot)
_service_state = {
    "scaling_temperature": 1.0,
    "ml_snapshot": None,
}

# ------------------------- helpers ----------------------------------------

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _safe_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}

# ------------------------- unified payload extraction ----------------------

def extract_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    StateService v2 MUST provide summary vector:
        payload["summary"] = {...}
    MLService does NOT compute or infer metrics.
    """
    if isinstance(payload, dict) and isinstance(payload.get("summary"), dict):
        return payload["summary"]

    logger.warning("[MLService] Missing summary in payload; returning empty summary")
    return {}

# ------------------------- DRIFT ------------------------------------------

def _coerce_drift_output(result: Any) -> Dict[str, Any]:
    """Normalize drift detector output."""
    if isinstance(result, dict):
        return {
            "score": _safe_float(result.get("score"), 0.5),
            "confidence": _safe_float(result.get("confidence"), 0.1),
            "model_version": result.get("model_version", "unknown"),
        }
    return {"score": _safe_float(result, 0.5), "confidence": 0.1, "model_version": "unknown"}

async def run_drift(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Run drift detection model (LLM or local)."""
    try:
        from seedcore.ml.drift_detector import compute_drift_score
        desc = f"{summary.get('total_agents',0)} agents • mem={summary.get('memory_util_scalar',0.0):.2f}"
        task = {"id": f"drift_{int(time.time()*1000)}", "description": desc}
        result = await compute_drift_score(task, text=desc)
        return _coerce_drift_output(result)
    except Exception as e:
        logger.warning(f"[MLService] drift failed: {e}")
        snap = get_snapshot()
        fallback = snap.get("drift", 0.5) if snap else 0.5
        return {"score": fallback, "confidence": 0.1, "fallback": True}

# ------------------------- ANOMALY ----------------------------------------

def run_anomaly(summary: Dict[str, Any], drift_score: float) -> float:
    """
    Combine drift + memory_anomaly_score.
    StateService must provide memory_anomaly_score.
    """
    memory_anom = _safe_float(summary.get("memory_anomaly_score"), None)
    if memory_anom is None:
        # drift-only fallback
        return float(drift_score)
    return float(max(0.0, min(1.0, 0.6 * drift_score + 0.4 * memory_anom)))

# ------------------------- SCALING ----------------------------------------

def adjust_temp(delta_E: Optional[float]) -> float:
    """Adaptive temperature update from Energy feedback."""
    temp = _service_state.get("scaling_temperature", 1.0)
    if delta_E is None:
        return temp

    if delta_E < 0:  # energy worsening → more conservative
        temp *= 1.02
    else:            # improving → sharper decisions
        temp *= 0.98

    temp = max(0.5, min(2.0, temp))
    _service_state["scaling_temperature"] = temp
    return temp

def run_scaling(summary: Dict[str, Any]) -> float:
    """
    StateService should compute `scaling_score`.
    MLService only applies temperature shaping.
    """
    base = _safe_float(summary.get("scaling_score"), 0.5)
    temp = _service_state.get("scaling_temperature", 1.0)
    if temp != 1.0:
        base = base ** (1.0 / temp)
    return float(max(0.0, min(1.0, base)))

# ------------------------- ROLES ------------------------------------------

def extract_roles(summary: Dict[str, Any]) -> Dict[str, float]:
    """
    StateService should provide avg_role = {"E":..., "S":..., "O":...}
    """
    avg_role = _safe_dict(summary.get("avg_role"))
    if avg_role:
        return {
            "E": _safe_float(avg_role.get("E"), 1/3),
            "S": _safe_float(avg_role.get("S"), 1/3),
            "O": _safe_float(avg_role.get("O"), 1/3),
        }
    return {"E": 1/3, "S": 1/3, "O": 1/3}

# ------------------------- SNAPSHOT ----------------------------------------

def get_snapshot(max_age: float = 60.0) -> Optional[Dict[str, Any]]:
    snap = _service_state.get("ml_snapshot")
    if not isinstance(snap, dict):
        return None
    if time.time() - snap.get("ts", 0) > max_age:
        return None
    return snap.get("data")

def set_snapshot(data: Dict[str, Any]):
    _service_state["ml_snapshot"] = {"ts": time.time(), "data": data}

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
        "service": "ml_service",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "llm": {
                "chat": "/chat",
                "embeddings": "/embeddings",
                "rerank": "/rerank",
                "models": "/models"
            },
            "scoring": {
                "salience": "/score/salience"
            },
            "detection": {
                "anomaly": "/detect/anomaly"
            },
            "drift": {
                "score": "/drift/score",
                "warmup": "/drift/warmup"
            },
            "prediction": {
                "scaling": "/predict/scaling"
            },
            "integrations": {
                "predict_all": "/integrations/predict_all",
                "adaptive_params": {
                    "get": "/integrations/adaptive_params",
                    "update": "/integrations/adaptive_params"
                }
            },
            "xgboost": {
                "training": {
                    "train": "/xgboost/train",
                    "train_distilled": "/xgboost/train_distilled"
                },
                "inference": {
                    "predict": "/xgboost/predict",
                    "batch_predict": "/xgboost/batch_predict",
                    "system_regime": "/xgboost/system_regime"
                },
                "model_management": {
                    "load_model": "/xgboost/load_model",
                    "list_models": "/xgboost/list_models",
                    "model_info": "/xgboost/model_info",
                    "delete_model": "/xgboost/delete_model",
                    "refresh_model": "/xgboost/refresh_model",
                    "promote": "/xgboost/promote"
                },
                "tuning": {
                    "tune": "/xgboost/tune",
                    "tune_async": {
                        "submit": "/xgboost/tune/submit",
                        "status": "/xgboost/tune/status/{job_id}",
                        "list_jobs": "/xgboost/tune/jobs"
                    }
                },
                "distillation": {
                    "distill_episode": "/xgboost/distill/episode"
                }
            }
        }
    }

@ml_app.get("/health")
async def health_check():
    try:
        import psutil  # pyright: ignore[reportMissingModuleSource]
        try:
            from seedcore.ml.models.xgboost_service import get_xgboost_service
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
        # Support both old format (features) and new format (text/context)
        features_list = request.get("features", [])
        text = request.get("text")
        context = request.get("context", {})
        
        if not features_list and not text:
            return {"error": "No features or text provided", "status": "error"}

        from seedcore.ml.salience.scorer import SalienceScorer as MLSalienceScorer
        try:
            scorer = MLSalienceScorer()
            
            if text:
                # New format: compute salience for text
                # TODO: Implement actual text-based salience scoring
                # For now, return a simple score based on text length and context
                score = min(1.0, len(text.split()) / 100.0)  # Simple heuristic
                if context:
                    # Adjust score based on context
                    priority = context.get("priority", 5)
                    score *= (priority / 10.0)
                
                return {
                    "score": score,
                    "model": "ml_salience_scorer",
                    "status": "success",
                    "timestamp": time.time(),
                }
            else:
                # Old format: score features list
                scores = scorer.score_features(features_list)
                return {
                    "scores": scores,
                    "model": "ml_salience_scorer",
                    "status": "success",
                    "timestamp": time.time(),
                }
        except Exception as e:
            logger.error(f"Error loading salience scorer: {e}")
            if text:
                return {
                    "score": 0.5,
                    "model": "ml_salience_scorer",
                    "status": "success",
                    "timestamp": time.time(),
                }
            else:
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
    """
    Time-series anomaly detection using drift detector.
    MLService performs only:
    - drift-based embedding comparison
    - returns raw drift scores
    No classification, no thresholds, no business logic.
    """
    try:
        from seedcore.ml.drift_detector import compute_drift_score
        
        data = request.get("data")
        if not isinstance(data, list) or len(data) == 0:
            return {"status": "error", "error": "Request must include non-empty 'data' array"}

        # Minimal ML input
        task = {
            "id": f"detect_anomaly_{int(time.time()*1000)}",
            "type": "anomaly_series",
            "series_length": len(data),
            "series_mean": float(np.mean(data)),
            "series_std": float(np.std(data)),
        }

        # Drift computation
        drift_result = await compute_drift_score(task, text=str(data))

        return {
            "status": "success",
            "drift_score": drift_result.score,
            "log_likelihood": drift_result.log_likelihood,
            "confidence": drift_result.confidence,
            "processing_time_ms": drift_result.processing_time_ms,
            "model_version": drift_result.model_version,
            "drift_mode": drift_result.drift_mode,
            "timestamp": time.time(),
        }

    except Exception as e:
        logger.error(f"[MLService] detect_anomaly failed: {e}")
        return {"status": "error", "error": str(e), "timestamp": time.time()}

@ml_app.post("/predict/scaling")
async def predict_scaling(request: Dict[str, Any]):
    """
    DEPRECATED: compatibility wrapper.
    Redirects to unified /integrations/predict_all endpoint.
    Scaling policy must be applied in Coordinator, not MLService.
    """
    try:
        metrics = request.get("metrics") or request
        result = await predict_all_state_metrics(metrics)
        
        scaling_score = result["ml_stats"]["scaling_score"]
        
        return {
            "status": "success",
            "scaling_score": scaling_score,
            "deprecated": True,
            "note": "Use /integrations/predict_all instead",
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"[MLService] scaling wrapper failed: {e}")
        return {"status": "error", "error": str(e), "timestamp": time.time()}

@ml_app.post("/integrations/predict_all")
async def predict_all_state_metrics(request: Dict[str, Any]):
    """
    Unified ML inference entrypoint.
    MLService v2 expects ONLY a pre-aggregated summary vector from StateService.
    No aggregation, no heuristics, no State logic.
    """
    try:
        # Extract summary provided by StateService
        summary = extract_summary(request)
        if not summary:
            raise HTTPException(
                status_code=400,
                detail="Missing 'summary' in payload. StateService must provide pre-aggregated summary."
            )

        # --- Run ML models only ---
        drift_info = await run_drift(summary)
        drift_score = _safe_float(drift_info.get("score"), 0.5)

        anomaly_score = run_anomaly(summary, drift_score)
        scaling_score = run_scaling(summary)
        roles = extract_roles(summary)

        ml_stats = {
            "p_pred": roles,
            "drift": drift_score,
            "drift_meta": drift_info,
            "anomaly": anomaly_score,
            "scaling_score": scaling_score,
            "adaptive_params": {
                "scaling_temperature": _service_state.get("scaling_temperature", 1.0),
            },
            "summary": summary,
            "timestamp": time.time(),
        }

        # Snapshot for degraded mode resilience
        set_snapshot(ml_stats)

        return {"status": "success", "ml_stats": ml_stats}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MLService] predict_all failed: {e}", exc_info=True)
        fallback = get_snapshot(max_age=300)
        if fallback:
            return {
                "status": "degraded",
                "ml_stats": fallback,
                "error": str(e),
            }
        raise HTTPException(500, detail=str(e))

@ml_app.get("/integrations/adaptive_params")
async def get_adaptive_params():
    """
    ML-only adaptive parameters.
    StateService owns all baselines & aggregation logic.
    """
    return {
        "status": "success",
        "adaptive_params": {
            "scaling_temperature": _service_state.get("scaling_temperature", 1.0),
        },
        "timestamp": time.time(),
        "note": "All baselines and system metrics are computed by StateService.",
    }
@ml_app.post("/integrations/adaptive_params")
async def update_adaptive_params(request: Dict[str, Any]):
    """
    Update ML-only tuning parameters.
    Supported: scaling_temperature (0.5–2.0)
    """
    try:
        updates = {}

        # Scaling temperature
        if "scaling_temperature" in request:
            temp = _safe_float(request["scaling_temperature"], 1.0)
            temp = max(0.5, min(2.0, temp))
            _service_state["scaling_temperature"] = temp
            updates["scaling_temperature"] = temp

        if not updates:
            raise HTTPException(
                400, "No valid parameters. Supported: scaling_temperature"
            )

        return {
            "status": "success",
            "updated_params": updates,
            "current_params": {
                "scaling_temperature": _service_state.get("scaling_temperature", 1.0),
            },
            "timestamp": time.time(),
            "note": "StateService owns baselines, EMA, scaling weights.",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MLService] Failed to update adaptive params: {e}")
        raise HTTPException(500, detail=str(e))

@ml_app.post("/drift/score")
async def compute_drift_score_api(request: Dict[str, Any]):
    """
    Drift scoring endpoint (ML-only).
    Runs Neural-CUSUM drift detector on a single task+text pair.
    """
    try:
        from seedcore.ml.drift_detector import compute_drift_score

        task = request.get("task") or {}
        text = request.get("text")

        if not task:
            raise HTTPException(400, "Missing 'task' in request")

        # Run drift model (async)
        drift = await compute_drift_score(task, text)

        return {
            "status": "success",
            "drift_score": drift.score,
            "confidence": drift.confidence,
            "log_likelihood": drift.log_likelihood,
            "processing_time_ms": drift.processing_time_ms,
            "model_version": drift.model_version,
            "drift_mode": drift.drift_mode,
            "timestamp": time.time(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[MLService] Drift scoring error: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "timestamp": time.time(),
        }


@ml_app.post("/drift/warmup")
async def warmup_drift_detector(request: Dict[str, Any] = None):
    """
    Warm up the drift detector to avoid cold start latency.
    
    This endpoint:
    1. Loads models if not already loaded
    2. Performs test computations to warm up the system
    3. Fits fallback featurizer if needed
    
    Should be called during service startup to ensure optimal performance.
    """
    try:
        from seedcore.ml.drift_detector import get_drift_detector
        
        detector = get_drift_detector()
        
        # Extract sample texts from request if provided
        sample_texts = None
        if request and "sample_texts" in request:
            sample_texts = request["sample_texts"]
        
        # Perform warmup
        start_time = time.time()
        await detector.warmup(sample_texts)
        warmup_time = (time.time() - start_time) * 1000
        
        # Get performance stats
        stats = detector.get_performance_stats()
        
        return {
            "status": "success",
            "warmed_up": detector._warmed_up,
            "warmup_time_ms": warmup_time,
            "performance_stats": stats,
            "timestamp": time.time(),
        }
        
    except Exception as e:
        logger.error(f"Error in drift detector warmup: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}


# ---------------------------------------------------------------------
# LLM Endpoints (chat, embeddings, rerank)
# ---------------------------------------------------------------------
@ml_app.post("/chat")
async def chat_completions(request: Dict[str, Any]):
    """
    Chat/completions endpoint for LLM inference.
    
    Expected request format:
    {
        "model": "llama3-8b",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.7,
        "max_tokens": 100
    }
    """
    try:
        model = request.get("model", "default")
        messages = request.get("messages", [])
        
        if not messages:
            return {"error": "No messages provided", "status": "error"}
        
        # TODO: Implement actual LLM inference
        # This is a stub implementation
        response_text = f"LLM response for model '{model}' with {len(messages)} messages"
        
        return {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }],
            "model": model,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15
            },
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in chat completions: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@ml_app.post("/embeddings")
async def embeddings(request: Dict[str, Any]):
    """
    Embeddings endpoint for text embeddings.
    
    Expected request format:
    {
        "model": "embedding-model",
        "input": "text to embed" or ["text1", "text2"]
    }
    """
    try:
        model = request.get("model", "default-embedding")
        inputs = request.get("input", [])
        
        if not inputs:
            return {"error": "No input provided", "status": "error"}
        
        # Handle both string and list inputs
        if isinstance(inputs, str):
            inputs = [inputs]
        
        # TODO: Implement actual embedding inference
        # This is a stub implementation
        embeddings_data = []
        for i, text in enumerate(inputs):
            # Generate fake embedding vector (dimension 384)
            embedding = [0.1 * (i + j) for j in range(384)]
            embeddings_data.append({
                "object": "embedding",
                "index": i,
                "embedding": embedding
            })
        
        return {
            "object": "list",
            "data": embeddings_data,
            "model": model,
            "usage": {
                "prompt_tokens": sum(len(text.split()) for text in inputs),
                "total_tokens": sum(len(text.split()) for text in inputs)
            },
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in embeddings: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@ml_app.post("/rerank")
async def rerank(request: Dict[str, Any]):
    """
    Rerank endpoint for document reranking.
    
    Expected request format:
    {
        "model": "rerank-model",
        "query": "search query",
        "documents": ["doc1", "doc2", "doc3"],
        "top_k": 10
    }
    """
    try:
        model = request.get("model", "default-rerank")
        query = request.get("query", "")
        documents = request.get("documents", [])
        top_k = request.get("top_k", 10)
        
        if not query or not documents:
            return {"error": "Query and documents are required", "status": "error"}
        
        # TODO: Implement actual reranking
        # This is a stub implementation
        results = []
        for i, doc in enumerate(documents):
            # Generate fake relevance score
            score = 0.9 - (i * 0.1)  # Decreasing scores
            results.append({
                "index": i,
                "relevance_score": score,
                "document": doc
            })
        
        # Sort by relevance score and take top_k
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        results = results[:top_k]
        
        return {
            "model": model,
            "results": results,
            "usage": {
                "total_tokens": len(query.split()) + sum(len(doc.split()) for doc in documents)
            },
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error in rerank: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}

@ml_app.get("/models")
async def list_models():
    """
    List available models from the ML service.
    """
    try:
        # TODO: Implement actual model listing
        # This is a stub implementation
        models = {
            "object": "list",
            "data": [
                {
                    "id": "llama3-8b",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "seedcore-ml"
                },
                {
                    "id": "mistral-7b",
                    "object": "model", 
                    "created": int(time.time()),
                    "owned_by": "seedcore-ml"
                },
                {
                    "id": "embedding-model",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "seedcore-ml"
                },
                {
                    "id": "rerank-model",
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": "seedcore-ml"
                }
            ]
        }
        
        return {
            **models,
            "status": "success",
            "timestamp": time.time()
        }
        
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        return {"error": str(e), "status": "error", "timestamp": time.time()}


# ---------------------------------------------------------------------
# XGBoost (main API under /xgboost/*)
# ---------------------------------------------------------------------
@ml_app.post("/xgboost/train")
async def train_xgboost_model(request: Dict[str, Any]):
    try:
        from seedcore.ml.models.xgboost_models import TrainModelRequest, TrainModelResponse
        from seedcore.ml.models.xgboost_service import (
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
        from seedcore.ml.models.xgboost_models import PredictRequest, PredictResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.models.xgboost_models import (
            BatchPredictRequest,
            BatchPredictResponse,
        )
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.models.xgboost_models import LoadModelRequest, ModelInfoResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.models.xgboost_models import ModelListResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.models.xgboost_models import ModelInfoResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.models.xgboost_models import DeleteModelRequest, DeleteModelResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service

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
        from seedcore.ml.tunning.tuning_service import get_tuning_service
        from seedcore.ml.models.xgboost_models import TuneRequest, TuneResponse

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
        from seedcore.ml.tunning.tuning_service import get_tuning_service
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



async def _get_energy_meta() -> Dict[str, Any]:
    """Get energy metadata using EnergyServiceClient."""
    try:
        from seedcore.serve.energy_client import EnergyServiceClient
        from seedcore.utils.ray_utils import SERVE_GATEWAY
        base_url = f"{SERVE_GATEWAY}/ops/energy/meta"
        client = EnergyServiceClient(base_url, timeout=3.0)
        return await client.get_meta()
    except Exception as e:
        logger.error(f"Failed to fetch /energy/meta: {e}")
        raise HTTPException(status_code=502, detail=f"Energy meta unavailable: {e}")

async def _log_flywheel_event(payload: Dict[str, Any]) -> None:
    """Log flywheel event using EnergyServiceClient."""
    try:
        from seedcore.serve.energy_client import EnergyServiceClient
        from seedcore.utils.ray_utils import SERVE_GATEWAY
        
        # Use SERVE_GATEWAY as base URL for energy service
        client = EnergyServiceClient(base_url=SERVE_GATEWAY, timeout=2.0)
        await client.post("/ops/energy/log", json=payload)
    except Exception as e:
        logger.warning(f"Failed to log flywheel event: {e}")

@ml_app.post("/xgboost/refresh_model")
async def refresh_xgboost_model():
    try:
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        try:
            meta_before = await _get_energy_meta()
            if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
                return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}
        except HTTPException:
            return {"accepted": False, "reason": "Energy meta unavailable"}

        old_path = getattr(svc, "current_model_path", None)
        ok = await asyncio.to_thread(svc.refresh_model)
        if not ok:
            raise HTTPException(status_code=400, detail="Failed to refresh model")

        meta_after = await _get_energy_meta()
        if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            if old_path:
                try:
                    await asyncio.to_thread(svc.load_model, old_path)
                except Exception:
                    logger.error("Rollback failed after L_tot cap violation (refresh)")
            return {"accepted": False, "reason": "Post-refresh L_tot cap violated", "meta": meta_after}

        await _log_flywheel_event({"organ": "utility", "metric": "model_refresh", "model_path": svc.current_model_path, "success": True})
        return {"accepted": True, "message": "Model refreshed successfully", "current_model_path": svc.current_model_path}

    except Exception as e:
        logger.error(f"Error refreshing XGBoost model: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/promote")
async def promote_xgboost_model(request: Dict[str, Any]):
    try:
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        candidate = request.get("model_path") or request.get("candidate_uri")
        if not candidate:
            raise HTTPException(status_code=400, detail="model_path (or candidate_uri) is required")

        try:
            delta_E = float(request.get("delta_E", 0.0))
        except Exception:
            raise HTTPException(status_code=400, detail="delta_E must be a number")

        if not (delta_E <= -E_GUARD):
            return {"accepted": False, "reason": f"ΔE guard failed (delta_E={delta_E} must be ≤ {-E_GUARD})"}

        meta_before = await _get_energy_meta()
        if meta_before.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            return {"accepted": False, "reason": "System at/over Lipschitz cap (pre-flight)", "meta": meta_before}

        svc = get_xgboost_service()
        if not svc:
            return {"accepted": False, "reason": "XGBoost service unavailable"}

        old_path = getattr(svc, "current_model_path", None)
        ok = await asyncio.to_thread(svc.load_model, candidate)
        if not ok:
            return {"accepted": False, "reason": "Failed to load candidate model"}

        meta_after = await _get_energy_meta()
        if meta_after.get("L_tot", 1.0) >= PROMOTION_LTOT_CAP:
            if old_path:
                try:
                    await asyncio.to_thread(svc.load_model, old_path)
                except Exception:
                    logger.error("Rollback failed after L_tot cap violation")
            return {"accepted": False, "reason": "Post-promotion L_tot cap violated", "meta": meta_after}

        await _log_flywheel_event(
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

@ml_app.post("/xgboost/distill/episode")
async def distill_episode(request: Dict[str, Any]):
    """
    Accept a SystemEpisode, label it with LLM, and store a training sample
    for XGBoost distillation.
    """
    try:
        from seedcore.ml.distillation.system_episode import SystemEpisode, episode_to_features
        from seedcore.ml.distillation.teacher_llm import label_episode_with_llm
        from seedcore.ml.distillation.sample_store import append_sample  # new module

        ep = SystemEpisode(**request)
        features = episode_to_features(ep)
        labels = await label_episode_with_llm(ep)

        sample = {
            "episode_id": ep.episode_id,
            "features": features,
            "regime_label": labels["regime_label"],
            "action_label": labels["action_label"],
            "confidence": labels["confidence"],
            "start_ts": ep.start_ts,
            "end_ts": ep.end_ts,
        }

        await append_sample(sample)  # implement this to store to disk/DB
        return {"status": "success", "sample": sanitize_json(sample)}
    except Exception as e:
        logger.error(f"Error in distill_episode: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/train_distilled")
async def train_xgboost_distilled(request: Dict[str, Any]):
    """
    Train an XGBoost model using distilled system-episode samples
    (features + LLM-provided labels).
    """
    try:
        from seedcore.ml.models.xgboost_models import TrainModelResponse
        from seedcore.ml.models.xgboost_service import get_xgboost_service
        from seedcore.ml.distillation.sample_store import load_distillation_dataset

        # Optional: allow specifying which label (regime vs action)
        label_type = request.get("label_type", "regime_label")

        X, y, feature_names = await asyncio.to_thread(
            load_distillation_dataset, label_type
        )

        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        # You might extend svc.train_model to accept numpy arrays directly
        result = await asyncio.to_thread(
            svc.train_from_arrays,
            X,
            y,
            feature_names,
            request.get("name", f"distilled_{label_type}_{int(time.time())}")
        )

        return TrainModelResponse(**sanitize_json(result))
    except Exception as e:
        logger.error(f"Error in XGBoost distilled training: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ml_app.post("/xgboost/system_regime")
async def predict_system_regime(request: Dict[str, Any]):
    """
    Inference for system regime classification using distilled XGBoost model.
    Expects features in the same format as episode_to_features output.
    """
    try:
        from seedcore.ml.models.xgboost_service import get_xgboost_service

        features = request.get("features")
        if not features:
            raise HTTPException(status_code=400, detail="features required")

        svc = get_xgboost_service()
        if not svc:
            raise HTTPException(status_code=503, detail="XGBoost service unavailable")

        matrix = [list(features.values())]  # single row
        preds = await asyncio.to_thread(svc.predict, matrix)
        pred_label_id = int(preds[0])

        # Optional: map numeric label back to string regime
        # e.g. via a small config or metadata in svc.model_metadata
        regime = svc.decode_label(pred_label_id) if hasattr(svc, "decode_label") else pred_label_id

        return {
            "status": "success",
            "regime": regime,
            "raw_score": float(preds[0]),
            "model_path": getattr(svc, "current_model_path", None),
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error(f"Error in system_regime prediction: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ---------------------------------------------------------------------
# Serve deployment that hosts ml_app
# ---------------------------------------------------------------------
@ml_app.on_event("startup")
async def startup_event():
    """
    FastAPI startup event handler.
    
    This runs after __init__ and before the service accepts requests.
    This is the correct place to run async initialization logic like warmup tasks.
    """
    logger.info("🚀 FastAPI startup event: Initializing ML service...")
    
    # Initialize status actor (synchronous Ray operations are fine here)
    global status_actor
    try:
        ns = None
        try:
            ns = ray.get_runtime_context().namespace
        except Exception:
            ns = os.getenv("RAY_NAMESPACE", None)
        try:
            # Use explicit namespace (prefer SEEDCORE_NS)
            ns = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))
            status_actor = ray.get_actor("job_status_actor", namespace=ns)
            logger.info(f"✅ Connected to existing status actor (ns={ns})")
        except Exception:
            status_actor = StatusActor.options(name="job_status_actor", lifetime="detached", namespace=ns).remote()
            logger.info(f"✅ Created new status actor (ns={ns})")
    except Exception as e:
        logger.error(f"❌ Failed to initialize status actor: {e}")
        status_actor = None
    
    # Initialize drift detector for warmup (lazy loading)
    try:
        from seedcore.ml.drift_detector import get_drift_detector
        detector = get_drift_detector()
        _service_state["drift_detector"] = detector
        
        # Schedule background warmup task (now in proper async context)
        if detector:
            logger.info("🔄 Scheduling drift detector background warmup...")
            warmup_task = asyncio.create_task(detector.warmup())
            _service_state["warmup_task"] = warmup_task
            logger.info("✅ Drift detector warmup task scheduled")
    except Exception as e:
        logger.warning(f"⚠️ Could not initialize drift detector for warmup: {e}")
    
    logger.info("✅ MLService startup event complete")

@serve.deployment(name="MLService")
@serve.ingress(ml_app)
class MLService:
    """Ray Serve deployment for ML services (FastAPI ingress)."""

    def __init__(self):
        """
        Lightweight __init__ - heavy initialization moved to startup_event.
        
        This keeps startup fast and defers async operations to the proper
        FastAPI lifecycle event handler.
        """
        logger.info("✅ MLService class initializing (lightweight)")
        
        # Initialize instance variables for lazy loading (if needed by endpoints)
        self._salience_scorer = None
        self._xgboost_service = None  # kept for possible future use
        self._drift_detector = None  # Lazy initialization on first use
        
        logger.info("✅ MLService class initialized (startup event will handle async init)")

    def _get_drift_detector(self):
        """Get drift detector with lazy initialization."""
        if self._drift_detector is None:
            try:
                from seedcore.ml.drift_detector import get_drift_detector
                self._drift_detector = get_drift_detector()
                logger.info("✅ Drift detector loaded on first use")
            except Exception as e:
                logger.error(f"❌ Failed to load drift detector: {e}")
                return None
        return self._drift_detector

    def _get_salience_scorer(self):
        if self._salience_scorer is None:
            try:
                from seedcore.ml.salience.scorer import SalienceScorer
                self._salience_scorer = SalienceScorer()
            except Exception as e:
                logger.error(f"Failed to load salience scorer: {e}")
                self._salience_scorer = None
        return self._salience_scorer

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
