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
Environment variables are configured in deploy/rayservice.yaml at the container level.
"""

import os
import sys
import time
from typing import Optional

from ray import serve  # type: ignore[reportMissingImports]
from fastapi import FastAPI  # type: ignore[reportMissingImports]

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Use Ray Serve specific logging setup to force stdout output
from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.utils.ray_utils import ensure_ray_initialized

# Import the ML service components
from seedcore.ml.ml_service import MLService

setup_logging(app_name="seedcore.ml_service.driver")
logger = ensure_serve_logger("seedcore.ml_service", level="DEBUG")

# --- Configuration ---
# These defaults are used only for local testing via main()
# When deployed via rayservice.yaml, env vars are set at container level
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# --- No-op deployment for when ML service is disabled ---
_noop_app = FastAPI()

@serve.deployment(name="MLService")
@serve.ingress(_noop_app)
class MLServiceNoOp:
    """No-op ML service deployment used when ENABLE_ML_SERVICE is false."""
    
    def __init__(self):
        logger.warning("🚫 MLService is DISABLED (ENABLE_ML_SERVICE=false). Using no-op deployment.")
    
    @_noop_app.get("/")
    async def root(self):
        return {
            "status": "disabled",
            "service": "seedcore-ml",
            "message": "ML service is disabled. Set ENABLE_ML_SERVICE=true to enable."
        }
    
    @_noop_app.get("/health")
    async def health(self):
        return {"status": "disabled", "service": "seedcore-ml"}

def build_ml_service(args: Optional[dict] = None):
    """
    Builder function for the ML service application.
    
    This function reads the ENABLE_ML_SERVICE environment variable to conditionally
    build and return the MLService application or a no-op deployment.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application (MLService if enabled, MLServiceNoOp if disabled)
    """
    # Read the environment variable switch (default to "false" for safety)
    is_enabled = os.getenv("ENABLE_ML_SERVICE", "false").lower() in ("true", "1")
    
    if is_enabled:
        logger.info("✅ ENABLE_ML_SERVICE is 'true'. Building MLService...")
        return MLService.bind()
    else:
        logger.warning("🚫 ENABLE_ML_SERVICE is 'false' or not set. Building no-op MLService...")
        return MLServiceNoOp.bind()

def main():
    """Main entrypoint for running the ML service directly."""
    logger.info("🚀 Starting ML Service...")
    try:
        # Initialize Ray connection using shared utility (idempotent)
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            sys.exit(1)

        # Deploy the ML service
        serve.run(
            build_ml_service(),
            name="ml_service",
            route_prefix="/ml"
        )
        logger.info("✅ ML Service is running.")
        
        # Keep the service running
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
