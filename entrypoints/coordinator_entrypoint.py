#!/usr/bin/env python3
"""
Coordinator Entrypoint for SeedCore
entrypoints/coordinator_entrypoint.py

This service provides the coordinator functionality by importing and using
the Coordinator service from src.seedcore.services.coordinator_service.
"""

import os
import sys

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.services.coordinator_service import coordinator_deployment

from seedcore.logging_setup import ensure_serve_logger, setup_logging

setup_logging(app_name="seedcore.coordinator_service.driver")
logger = ensure_serve_logger("seedcore.coordinator_service", level="DEBUG")

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

def build_coordinator(args: dict = None):
    """Builder for the Coordinator Serve app."""
    # Collect env vars from the *controller* process to inject into replicas
    # Note: OCPS_DRIFT_THRESHOLD, FAST_PATH_LATENCY_SLO_MS, MAX_PLAN_STEPS,
    # COGNITIVE_MAX_INFLIGHT, and REDIS_URL are set in rayservice.yaml and env.example
    env_vars = {
        "SEEDCORE_PG_DSN": os.getenv("SEEDCORE_PG_DSN", ""),
        "COORDINATOR_REPLICAS": os.getenv("COORDINATOR_REPLICAS", "1"),
        "COORDINATOR_NUM_CPUS": os.getenv("COORDINATOR_NUM_CPUS", "0.2"),
        "SERVE_GATEWAY": os.getenv("SERVE_GATEWAY", "http://seedcore-svc-stable-svc:8000"),
        "SEEDCORE_API_URL": os.getenv("SEEDCORE_API_URL", "http://seedcore-api:8002"),
        "SEEDCORE_API_TIMEOUT": os.getenv("SEEDCORE_API_TIMEOUT", "5.0"),
        "ORCH_HTTP_TIMEOUT": os.getenv("ORCH_HTTP_TIMEOUT", "10.0"),
        "ML_SERVICE_TIMEOUT": os.getenv("ML_SERVICE_TIMEOUT", "8.0"),
        "COGNITIVE_SERVICE_TIMEOUT": os.getenv("COGNITIVE_SERVICE_TIMEOUT", "15.0"),
        "ORGANISM_SERVICE_TIMEOUT": os.getenv("ORGANISM_SERVICE_TIMEOUT", "5.0"),
        "SERVE_CALL_TIMEOUT_S": os.getenv("SERVE_CALL_TIMEOUT_S", "120"),
        # Circuit breaker timeouts
        "CB_ML_TIMEOUT_S": os.getenv("CB_ML_TIMEOUT_S", "5.0"),
        "CB_COG_TIMEOUT_S": os.getenv("CB_COG_TIMEOUT_S", "8.0"),
        "CB_ORG_TIMEOUT_S": os.getenv("CB_ORG_TIMEOUT_S", "6.0"),
        "CB_FAIL_THRESHOLD": os.getenv("CB_FAIL_THRESHOLD", "5"),
        "CB_RESET_S": os.getenv("CB_RESET_S", "30.0"),
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
    import uvicorn  # type: ignore[reportMissingImports]
    uvicorn.run(app, host="0.0.0.0", port=8000)