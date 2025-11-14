#!/usr/bin/env python3
"""
Organism Serve Entrypoint for SeedCore
entrypoints/organism_entrypoint.py

This module is the deployment driver. It initializes Ray, binds the Serve
application, and runs it under the desired route prefix. The Ray Serve
deployment itself (FastAPI app, request/response models, and the
OrganismService class) live in `organism_services.py`.
"""

import os
import sys
import time

# Ensure project roots are importable (mirrors original file behavior)
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from ray import serve  # type: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.utils.ray_utils import ensure_ray_initialized

# Configure logging early for the driver process
setup_logging(app_name="seedcore.organism_service.driver")
logger = ensure_serve_logger("seedcore.organism_service", level="DEBUG")

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# Import the Serve deployment definition
# If these files are colocated (e.g., under entrypoints/), a plain import works.
# Adjust the import path to your package layout as needed.
from seedcore.services.organism_service import OrganismService  # noqa: E402

# Bind the application at module import time so Ray Serve YAML can reference it
organism_app = OrganismService.bind()

def build_organism_app(args: dict | None = None):
    """
    Builder function for the organism service application.

    Returns a bound Serve application that can be deployed via Ray Serve YAML.
    Args are currently unused, but accepted for compatibility with other
    deployment driver patterns (e.g., coordinator_entrypoint).
    """
    return OrganismService.bind()

def main():
    logger.info("🚀 Starting deployment driver for Organism Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            raise SystemExit(1)

        serve.run(
            organism_app,
            name="organism",
            route_prefix="/organism",
        )
        logger.info("✅ Organism service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
