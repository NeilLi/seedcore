#!/usr/bin/env python3
"""
DEPRECATED: State Service Entrypoint for SeedCore
entrypoints/state_entrypoint.py

⚠️  WARNING: This file is DEPRECATED and should not be used.
The StateService has been merged into the unified ops application.

Use the unified ops application instead:
- Import path: entrypoints.ops_entrypoint:build_ops_app
- Route prefix: /ops
- State endpoints: /ops/state/*

This standalone entrypoint is kept for backward compatibility only.
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.state")

import os
import sys
import time
import traceback
import asyncio
import logging
from typing import Dict, Any, Optional

import ray
from ray import serve

# Add the project root to Python path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from seedcore.utils.ray_utils import ensure_ray_initialized

logger = logging.getLogger("seedcore.state")

# Import state service
from seedcore.services.state_service import StateService

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "serve")

# Concurrency settings
MAX_ONGOING_REQUESTS = int(os.getenv("STATE_MAX_ONGOING_REQUESTS", "32"))
NUM_CPUS = float(os.getenv("STATE_NUM_CPUS", "0.2"))
MEMORY = int(os.getenv("STATE_MEMORY", "1073741824"))  # 1GB

# --- Main Entrypoint ---
state_app = StateService.bind()

def build_state_app(args: dict = None):
    """
    DEPRECATED: Builder function for the state service application.
    
    ⚠️  WARNING: This function is DEPRECATED.
    Use the unified ops application instead: entrypoints.ops_entrypoint:build_ops_app
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    import warnings
    warnings.warn(
        "build_state_app is deprecated. Use entrypoints.ops_entrypoint:build_ops_app instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return StateService.bind()

def main():
    logger.warning("⚠️  DEPRECATED: State service standalone deployment is deprecated.")
    logger.warning("⚠️  Use the unified ops application instead: entrypoints.ops_entrypoint:build_ops_app")
    logger.warning("⚠️  State endpoints are now available at /ops/state/*")
    
    logger.info("🚀 Starting DEPRECATED deployment driver for State Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            state_app,
            name="state-service-deprecated",
            route_prefix="/state-deprecated"
        )
        logger.warning("✅ DEPRECATED State service is running at /state-deprecated")
        logger.warning("⚠️  Please migrate to the unified ops application!")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
