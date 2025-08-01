"""
Salience Scoring API Router

Provides REST API endpoints for ML-based salience scoring.
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any, Optional
import logging
import requests
import time

# Configure logger first
logger = logging.getLogger(__name__)

# Import with error handling for startup
try:
    from src.seedcore.ml.serve_app import SalienceServiceClient
    salience_client = SalienceServiceClient()
    SALIENCE_AVAILABLE = True
except Exception as e:
    logger.warning(f"SalienceServiceClient not available: {e}")
    salience_client = None
    SALIENCE_AVAILABLE = False

router = APIRouter(prefix="/salience", tags=["salience"])

@router.post("/score")
async def score_salience(features: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Score the salience of input features using ML model.
        
        Args:
            features: List of feature dictionaries for scoring
            
        Returns:
            Dictionary containing salience scores and metadata
        """
        try:
            start_time = time.time()
            
            if not features:
                raise HTTPException(status_code=400, detail="No features provided")
            
            if not SALIENCE_AVAILABLE or salience_client is None:
                # Fallback to simple scoring
                scores = []
                for feature in features:
                    task_risk = feature.get('task_risk', 0.5)
                    failure_severity = feature.get('failure_severity', 0.5)
                    score = task_risk * failure_severity
                    scores.append(score)
                
                processing_time = time.time() - start_time
                
                return {
                    "scores": scores,
                    "count": len(scores),
                    "processing_time_ms": round(processing_time * 1000, 2),
                    "model": "simple_heuristic",
                    "status": "fallback",
                    "note": "ML service not available, using fallback scoring"
                }
            
            # Score features using ML service
            scores = salience_client.score_salience(features)
            
            processing_time = time.time() - start_time
            
            return {
                "scores": scores,
                "count": len(scores),
                "processing_time_ms": round(processing_time * 1000, 2),
                "model": "gradient_boosting_regressor",
                "status": "success"
            }
            
        except Exception as e:
            logger.error(f"Error in salience scoring: {e}")
            raise HTTPException(status_code=500, detail=f"Salience scoring failed: {str(e)}")

@router.post("/score/batch")
async def score_salience_batch(batch_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score salience for a batch of feature sets.
    
    Args:
        batch_data: Dictionary containing batch_id and features list
        
    Returns:
        Dictionary containing batch results
    """
    try:
        start_time = time.time()
        
        batch_id = batch_data.get("batch_id", f"batch_{int(time.time())}")
        features_list = batch_data.get("features", [])
        
        if not features_list:
            raise HTTPException(status_code=400, detail="No features provided")
        
        # Process each feature set
        results = []
        for i, features in enumerate(features_list):
            try:
                scores = salience_client.score_salience([features])
                results.append({
                    "index": i,
                    "features": features,
                    "score": scores[0] if scores else 0.0,
                    "status": "success"
                })
            except Exception as e:
                results.append({
                    "index": i,
                    "features": features,
                    "score": 0.0,
                    "status": "error",
                    "error": str(e)
                })
        
        processing_time = time.time() - start_time
        
        return {
            "batch_id": batch_id,
            "results": results,
            "total_count": len(features_list),
            "success_count": len([r for r in results if r["status"] == "success"]),
            "processing_time_ms": round(processing_time * 1000, 2),
            "model": "gradient_boosting_regressor",
            "status": "success"
        }
        
    except Exception as e:
        logger.error(f"Error in batch salience scoring: {e}")
        raise HTTPException(status_code=500, detail=f"Batch scoring failed: {str(e)}")

@router.get("/health")
async def salience_health() -> Dict[str, Any]:
        """
        Check the health of the salience scoring service.
        
        Returns:
            Health status and service information
        """
        try:
            # Test with a simple feature set
            test_features = [{
                "task_risk": 0.5,
                "failure_severity": 0.5,
                "agent_capability": 0.5,
                "system_load": 0.5,
                "memory_usage": 0.5,
                "cpu_usage": 0.5,
                "response_time": 1.0,
                "error_rate": 0.0,
                "task_complexity": 0.5,
                "user_impact": 0.5,
                "business_criticality": 0.5
            }]
            
            if not SALIENCE_AVAILABLE or salience_client is None:
                # Simple fallback test
                start_time = time.time()
                score = test_features[0]["task_risk"] * test_features[0]["failure_severity"]
                response_time = time.time() - start_time
                
                return {
                    "status": "healthy",
                    "service": "salience_scoring",
                    "model_loaded": False,
                    "response_time_ms": round(response_time * 1000, 2),
                    "test_score": score,
                    "note": "Using fallback scoring - ML service not available",
                    "circuit_breaker": {
                        "failure_count": 0,
                        "is_open": False
                    }
                }
            
            start_time = time.time()
            scores = salience_client.score_salience(test_features)
            response_time = time.time() - start_time
            
            return {
                "status": "healthy",
                "service": "salience_scoring",
                "model_loaded": True,
                "response_time_ms": round(response_time * 1000, 2),
                "test_score": scores[0] if scores else 0.0,
                "circuit_breaker": {
                    "failure_count": salience_client.failure_count,
                    "is_open": salience_client._is_circuit_open()
                }
            }
            
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "salience_scoring",
                "error": str(e),
                "circuit_breaker": {
                    "failure_count": 0,
                    "is_open": False
                }
            }

@router.get("/info")
async def salience_info() -> Dict[str, Any]:
    """
    Get information about the salience scoring service.
    
    Returns:
        Service information and model details
    """
    try:
        circuit_breaker_info = {
            "enabled": True,
            "threshold": salience_client.circuit_breaker_threshold if salience_client else 5,
            "timeout_seconds": salience_client.circuit_breaker_timeout if salience_client else 60,
            "fallback_enabled": salience_client.fallback_enabled if salience_client else True
        }
    except Exception as e:
        logger.warning(f"Could not get circuit breaker info: {e}")
        circuit_breaker_info = {
            "enabled": False,
            "threshold": 5,
            "timeout_seconds": 60,
            "fallback_enabled": True
        }
    
    return {
        "service": "salience_scoring",
        "model_type": "gradient_boosting_regressor" if SALIENCE_AVAILABLE else "simple_heuristic",
        "model_available": SALIENCE_AVAILABLE,
        "features": [
            "task_risk", "failure_severity", "agent_capability", "system_load",
            "memory_usage", "cpu_usage", "response_time", "error_rate",
            "task_complexity", "user_impact", "business_criticality"
        ],
        "endpoints": {
            "score": "POST /salience/score",
            "batch_score": "POST /salience/score/batch",
            "health": "GET /salience/health",
            "info": "GET /salience/info"
        },
        "circuit_breaker": circuit_breaker_info
    } 