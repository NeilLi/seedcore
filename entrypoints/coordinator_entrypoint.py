#!/usr/bin/env python3
"""
Coordinator Entrypoint for SeedCore
entrypoints/coordinator_entrypoint.py

This service provides the coordinator functionality by importing and using
the Coordinator service from src.seedcore.services.coordinator_service.
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.coordinator")

import os
import sys
import logging
from typing import Dict, Any

import ray
from ray import serve

logger = logging.getLogger("seedcore.coordinator")

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

# Import the Coordinator service
from src.seedcore.services.coordinator_service import coordinator_deployment

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

def build_coordinator(args: dict = None):
    """Builder for the Coordinator Serve app."""
    # Collect env vars from the *controller* process to inject into replicas
    env_vars = {
        "SEEDCORE_PG_DSN": os.getenv("SEEDCORE_PG_DSN", ""),
        "OCPS_DRIFT_THRESHOLD": os.getenv("OCPS_DRIFT_THRESHOLD", "0.5"),
        "FAST_PATH_LATENCY_SLO_MS": os.getenv("FAST_PATH_LATENCY_SLO_MS", "1000"),
        "MAX_PLAN_STEPS": os.getenv("MAX_PLAN_STEPS", "16"),
        "COGNITIVE_MAX_INFLIGHT": os.getenv("COGNITIVE_MAX_INFLIGHT", "64"),
        "COORDINATOR_REPLICAS": os.getenv("COORDINATOR_REPLICAS", "1"),
        "COORDINATOR_NUM_CPUS": os.getenv("COORDINATOR_NUM_CPUS", "0.2"),
        "SERVE_GATEWAY": os.getenv("SERVE_GATEWAY", "http://seedcore-svc-stable-svc:8000"),
        "SEEDCORE_API_URL": os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002"),
        "SEEDCORE_API_TIMEOUT": os.getenv("SEEDCORE_API_TIMEOUT", "5.0"),
        "ORCH_HTTP_TIMEOUT": os.getenv("ORCH_HTTP_TIMEOUT", "10"),
        "ML_SERVICE_TIMEOUT": os.getenv("ML_SERVICE_TIMEOUT", "8"),
        "COGNITIVE_SERVICE_TIMEOUT": os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15"),
        "ORGANISM_SERVICE_TIMEOUT": os.getenv("ORGANISM_SERVICE_TIMEOUT", "5"),
        # Tuning configuration
        "TUNE_SPACE_TYPE": os.getenv("TUNE_SPACE_TYPE", "basic"),
        "TUNE_CONFIG_TYPE": os.getenv("TUNE_CONFIG_TYPE", "fast"),
        "TUNE_EXPERIMENT_PREFIX": os.getenv("TUNE_EXPERIMENT_PREFIX", "coordinator-tune"),
    }
    
    # Set environment variables for the replicas
    for key, value in env_vars.items():
        if value:
            os.environ[key] = value
    
    logger.info(f"Building Coordinator with environment variables: {list(env_vars.keys())}")
    
    # Return the bound deployment from the coordinator service
    return coordinator_deployment

if __name__ == "__main__":
    # This allows the entrypoint to be run directly for testing
    from src.seedcore.services.coordinator_service import app
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)