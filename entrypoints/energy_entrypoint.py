#!/usr/bin/env python3
"""
DEPRECATED: Energy Service Entrypoint for SeedCore
entrypoints/energy_entrypoint.py

⚠️  WARNING: This file is DEPRECATED and should not be used.
The EnergyService has been merged into the unified ops application.

Use the unified ops application instead:
- Import path: entrypoints.ops_entrypoint:build_ops_app
- Route prefix: /ops
- Energy endpoints: /ops/energy/*

This standalone entrypoint is kept for backward compatibility only.
"""

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

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.energy")
logger = logging.getLogger("seedcore.energy")

from seedcore.utils.ray_utils import ensure_ray_initialized

# Import energy service
from seedcore.services.energy_service import EnergyService

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "serve")

# Concurrency settings
MAX_ONGOING_REQUESTS = int(os.getenv("ENERGY_MAX_ONGOING_REQUESTS", "16"))
NUM_CPUS = float(os.getenv("ENERGY_NUM_CPUS", "0.2"))
MEMORY = int(os.getenv("ENERGY_MEMORY", "1073741824"))  # 1GB

# --- Main Entrypoint ---
energy_app = EnergyService.bind()

def build_energy_app(args: dict = None):
    """
    DEPRECATED: Builder function for the energy service application.
    
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
        "build_energy_app is deprecated. Use entrypoints.ops_entrypoint:build_ops_app instead.",
        DeprecationWarning,
        stacklevel=2
    )
    return EnergyService.bind()

def main():
    logger.warning("⚠️  DEPRECATED: Energy service standalone deployment is deprecated.")
    logger.warning("⚠️  Use the unified ops application instead: entrypoints.ops_entrypoint:build_ops_app")
    logger.warning("⚠️  Energy endpoints are now available at /ops/energy/*")
    
    logger.info("🚀 Starting DEPRECATED deployment driver for Energy Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            energy_app,
            name="energy-service-deprecated",
            route_prefix="/energy-deprecated"
        )
        logger.warning("✅ DEPRECATED Energy service is running at /energy-deprecated")
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
