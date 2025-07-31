"""
Ray Serve Application for SeedCore ML Models

This module provides a Ray Serve application that deploys:
- Salience scoring models
- Anomaly detection models  
- Predictive scaling models
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
from fastapi import FastAPI

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create FastAPI app for ML services
ml_app = FastAPI()

@ml_app.get("/health")
async def health_check():
    """Health check endpoint for ML Serve applications."""
    try:
        # Check if ML models are available
        from src.seedcore.ml.salience.scorer import SalienceScorer as MLSalienceScorer
        try:
            scorer = MLSalienceScorer()
            salience_model_status = "loaded"
        except Exception as e:
            salience_model_status = f"error: {str(e)}"
        
        # Get system info
        import psutil
        system_info = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
        
        return {
            "status": "healthy",
            "service": "ml_serve",
            "timestamp": time.time(),
            "models": {
                "salience_scorer": salience_model_status
            },
            "system": system_info,
            "endpoints": {
                "salience_scoring": "/ml/score/salience",
                "anomaly_detection": "/ml/detect/anomaly",
                "scaling_prediction": "/ml/predict/scaling"
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
        
        # Use ML model to score features
        from src.seedcore.ml.salience.scorer import SalienceScorer as MLSalienceScorer
        scorer = MLSalienceScorer()
        scores = scorer.score_features(features_list)
        
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

@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)
@serve.ingress(ml_app)
class MLService:
    """Ray Serve deployment for ML services."""
    
    def __init__(self):
        logger.info("✅ MLService initialized successfully")

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

if __name__ == "__main__":
    # For direct execution
    app = create_serve_app()
    serve.run(app) 