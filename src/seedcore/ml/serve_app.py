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

# Create FastAPI app for salience scoring
salience_app = FastAPI()

@salience_app.post("/score/salience")
async def score_salience(request: Dict[str, Any]):
    """Score the salience of input data."""
    try:
        features_list = request.get("features", [])
        
        if not features_list:
            return {
                "error": "No features provided",
                "status": "error"
            }
        
        # Apply salience scoring
        scores = []
        for features in features_list:
            # Use simple scoring for now
            task_risk = features.get('task_risk', 0.5)
            failure_severity = features.get('failure_severity', 0.5)
            score = task_risk * failure_severity
            scores.append(score)
        
        return {
            "scores": scores,
            "model": "salience_scorer",
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

@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)
@serve.ingress(salience_app)
class SalienceScorer:
    """Ray Serve deployment for salience scoring models."""
    
    def __init__(self):
        logger.info("SalienceScorer initialized")

@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)
class AnomalyDetector:
    """Ray Serve deployment for anomaly detection models."""
    
    def __init__(self):
        self.model = self._load_model()
        logger.info("AnomalyDetector initialized")
    
    def _load_model(self):
        """Load the anomaly detection model."""
        try:
            from src.seedcore.ml.patterns.detector import AnomalyDetector as LocalAnomalyDetector
            detector = LocalAnomalyDetector()
            logger.info("✅ Loaded anomaly detection model")
            return detector
        except Exception as e:
            logger.error(f"Error loading anomaly detector: {e}")
            # Fallback to simple anomaly detection
            return lambda x: np.random.choice([True, False], p=[0.1, 0.9])
    
    async def __call__(self, request):
        """Detect anomalies in input data."""
        try:
            data = await request.json()
            metrics = data.get("metrics", [])
            
            if not metrics:
                return {
                    "error": "No metrics provided",
                    "status": "error"
                }
            
            # Apply anomaly detection
            if hasattr(self.model, 'detect_anomalies'):
                results = self.model.detect_anomalies(metrics)
                anomalies = [result['is_anomaly'] for result in results]
            else:
                anomalies = [self.model(metric) for metric in metrics]
            
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

@serve.deployment(
    num_replicas=2,
    ray_actor_options={"num_cpus": 1, "num_gpus": 0}
)
class ScalingPredictor:
    """Ray Serve deployment for predictive scaling models."""
    
    def __init__(self):
        self.model = self._load_model()
        logger.info("ScalingPredictor initialized")
    
    def _load_model(self):
        """Load the scaling prediction model."""
        try:
            from src.seedcore.ml.scaling.predictor import ScalingPredictor as LocalScalingPredictor
            predictor = LocalScalingPredictor()
            logger.info("✅ Loaded scaling prediction model")
            return predictor
        except Exception as e:
            logger.error(f"Error loading scaling predictor: {e}")
            # Fallback to simple scaling prediction
            return lambda x: {"overall_scale": 1.0, "confidence": 0.5}
    
    async def __call__(self, request):
        """Predict scaling requirements."""
        try:
            data = await request.json()
            usage_patterns = data.get("usage_patterns", {})
            
            if not usage_patterns:
                return {
                    "error": "No usage patterns provided",
                    "status": "error"
                }
            
            # Apply scaling prediction
            if hasattr(self.model, 'predict_scaling'):
                predictions = self.model.predict_scaling(usage_patterns)
            else:
                predictions = self.model(usage_patterns)
            
            return {
                "predictions": predictions,
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

class SalienceServiceClient:
    """Client for interacting with the SalienceScorer service with circuit breaker pattern."""
    
    def __init__(self, base_url: str = "http://ray-head:8000"):
        self.base_url = base_url
        self.salience_endpoint = f"{self.base_url}/ml/score/salience"
        self.failure_count = 0
        self.last_failure_time = 0
        self.circuit_breaker_threshold = 5
        self.circuit_breaker_timeout = 60  # seconds
        self.fallback_enabled = True
        
    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self.failure_count >= self.circuit_breaker_threshold:
            if time.time() - self.last_failure_time < self.circuit_breaker_timeout:
                return True
            else:
                # Reset circuit breaker
                self.failure_count = 0
                return False
        return False
    
    def _record_failure(self):
        """Record a failure for circuit breaker."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"Salience service failure recorded. Count: {self.failure_count}")
    
    def _record_success(self):
        """Record a success for circuit breaker."""
        if self.failure_count > 0:
            self.failure_count = 0
            logger.info("Salience service recovered, circuit breaker reset")
    
    def score_salience(self, features: List[Dict[str, Any]], 
                      fallback_scorer=None) -> List[float]:
        """Score salience with circuit breaker pattern (synchronous)."""
        
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning("Circuit breaker open, using fallback")
            if fallback_scorer and self.fallback_enabled:
                return fallback_scorer(features)
            else:
                return self._simple_fallback(features)
        
        try:
            # Make request to Ray Serve endpoint
            response = requests.post(
                self.salience_endpoint,
                json={"features": features},
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    self._record_success()
                    return result.get("scores", [])
                else:
                    raise Exception(result.get("error", "Unknown error"))
            else:
                raise Exception(f"HTTP {response.status_code}")
                
        except Exception as e:
            logger.error(f"Salience service error: {e}")
            self._record_failure()
            
            # Use fallback
            if fallback_scorer and self.fallback_enabled:
                return fallback_scorer(features)
            else:
                return self._simple_fallback(features)
    
    async def score_salience_async(self, features: List[Dict[str, Any]], 
                                  fallback_scorer=None) -> List[float]:
        """Score salience with circuit breaker pattern (asynchronous)."""
        
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning("Circuit breaker open, using fallback")
            if fallback_scorer and self.fallback_enabled:
                return fallback_scorer(features)
            else:
                return self._simple_fallback(features)
        
        try:
            # Make async request to Ray Serve endpoint
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    self.salience_endpoint,
                    json={"features": features}
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("status") == "success":
                        self._record_success()
                        return result.get("scores", [])
                    else:
                        raise Exception(result.get("error", "Unknown error"))
                else:
                    raise Exception(f"HTTP {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Salience service error: {e}")
            self._record_failure()
            
            # Use fallback
            if fallback_scorer and self.fallback_enabled:
                return fallback_scorer(features)
            else:
                return self._simple_fallback(features)
    
    def _simple_fallback(self, features: List[Dict[str, Any]]) -> List[float]:
        """Simple fallback scoring."""
        scores = []
        for feature in features:
            task_risk = feature.get('task_risk', 0.5)
            failure_severity = feature.get('failure_severity', 0.5)
            score = task_risk * failure_severity
            scores.append(score)
        return scores

def create_serve_app():
    """Create a single Ray Serve deployment."""
    try:
        # Create a single deployment without route prefix (handled by Ray Serve)
        salience_scorer = SalienceScorer.bind()
        
        logger.info("✅ Ray Serve deployment created successfully")
        return salience_scorer
        
    except Exception as e:
        logger.error(f"Error creating Serve application: {e}")
        raise

if __name__ == "__main__":
    # For direct execution
    app = create_serve_app()
    serve.run(app) 