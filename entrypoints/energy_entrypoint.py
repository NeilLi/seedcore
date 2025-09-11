#!/usr/bin/env python3
"""
Energy Service Entrypoint for SeedCore
entrypoints/energy_entrypoint.py

This service runs the energy calculator as a standalone Ray Serve deployment,
providing energy calculations and optimization for the SeedCore system.
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
    Builder function for the energy service application.
    
    This function returns a bound Serve application that can be deployed
    via Ray Serve YAML configuration.
    
    Args:
        args: Optional configuration arguments (unused in this implementation)
        
    Returns:
        Bound Serve application
    """
    return EnergyService.bind()

def main():
    logger.info("🚀 Starting deployment driver for Energy Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            sys.exit(1)

        serve.run(
            energy_app,
            name="energy-service",
            route_prefix="/energy"
        )
        logger.info("✅ Energy service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
