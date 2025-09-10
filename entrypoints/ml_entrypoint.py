#!/usr/bin/env python3
"""
ML Service Entrypoint for SeedCore
entrypoints/ml_entrypoint.py

This service provides ML functionality including:
- Drift detection with Neural-CUSUM
- Salience scoring
- Anomaly detection
- XGBoost training and inference
- Predictive scaling

This entrypoint is designed to be deployed by Ray Serve YAML configuration.
"""

# Use Ray Serve specific logging setup to force stdout output
from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.energy")

import os
import sys
import logging
from typing import Dict, Any

import ray
from ray import serve

logger = logging.getLogger("seedcore.ml")

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Import the ML service components
from src.seedcore.ml.serve_app import MLService, ml_app

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

def build_ml_service(args: dict = None):
    """
    Builder function for the ML service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    # Collect env vars from the *controller* process to inject into replicas
    env_vars = {
        "SEEDCORE_NS": os.getenv("SEEDCORE_NS", RAY_NS),
        "RAY_NAMESPACE": os.getenv("RAY_NAMESPACE", RAY_NS),
        "SERVE_GATEWAY": os.getenv("SERVE_GATEWAY", "http://seedcore-svc-stable-svc:8000"),
        "METRICS_ENABLED": os.getenv("METRICS_ENABLED", "1"),
        "MODEL_CACHE_DIR": os.getenv("MODEL_CACHE_DIR", "/app/models"),
        "DRIFT_DETECTOR_MODEL": os.getenv("DRIFT_DETECTOR_MODEL", "all-MiniLM-L6-v2"),
        "DRIFT_DETECTOR_DEVICE": os.getenv("DRIFT_DETECTOR_DEVICE", "cpu"),
        "DRIFT_DETECTOR_MAX_TEXT_LENGTH": os.getenv("DRIFT_DETECTOR_MAX_TEXT_LENGTH", "512"),
        "DRIFT_DETECTOR_ENABLE_FALLBACK": os.getenv("DRIFT_DETECTOR_ENABLE_FALLBACK", "true"),
    }
    
    # Set environment variables for the replicas
    for key, value in env_vars.items():
        if value:
            os.environ[key] = value
    
    logger.info(f"Building ML Service with environment variables: {list(env_vars.keys())}")
    
    # Return the bound deployment from the ML service
    return MLService.bind()

def main():
    """Main entrypoint for running the ML service directly."""
    logger.info("🚀 Starting ML Service...")
    try:
        # Initialize Ray connection
        if not ray.is_initialized():
            ray.init(address=RAY_ADDR, namespace=RAY_NS)
        
        # Deploy the ML service
        serve.run(
            build_ml_service(),
            name="ml_service",
            route_prefix="/ml"
        )
        logger.info("✅ ML Service is running.")
        
        # Keep the service running
        import time
        while True:
            time.sleep(3600)
            
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"❌ Failed to start ML service: {e}")
        sys.exit(1)
    finally:
        serve.shutdown()
        logger.info("✅ ML Service shutdown complete.")

if __name__ == "__main__":
    main()
