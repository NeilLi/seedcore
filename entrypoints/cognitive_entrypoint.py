#!/usr/bin/env python3
"""
Cognitive Serve Entrypoint for SeedCore
entrypoints/cognitive_entrypoint.py

This module is a thin deployment driver. It initializes Ray, binds the Serve
application defined in `cognitive_services.py`, and runs it under /cognitive.
"""

import os
import sys
import time

# Ensure project roots are importable
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/src')

from ray import serve  # type: ignore[reportMissingImports]

from seedcore.logging_setup import ensure_serve_logger, setup_logging
from seedcore.utils.ray_utils import ensure_ray_initialized

# Configure logging early for the driver process
setup_logging(app_name="seedcore.cognitive_service.driver")
logger = ensure_serve_logger("seedcore.cognitive_service", level="DEBUG")

# --- Configuration ---
RAY_ADDR = os.getenv("RAY_ADDRESS", "ray://seedcore-svc-head-svc:10001")
RAY_NS = os.getenv("RAY_NAMESPACE", "seedcore-dev")

# Import the Serve deployment definition (FastAPI + Serve class)
from seedcore.services.cognitive_service import CognitiveService  # noqa: E402

# Bind the application at module import time so Ray Serve YAML can reference it
cognitive_app = CognitiveService.bind()

def build_cognitive_app(args: dict | None = None):
    """Builder function for Ray Serve YAML configuration."""
    return CognitiveService.bind()

def main():
    logger.info("🚀 Starting deployment driver for Cognitive Service...")
    try:
        if not ensure_ray_initialized(ray_address=RAY_ADDR, ray_namespace=RAY_NS):
            logger.error("❌ Failed to initialize Ray connection")
            raise SystemExit(1)

        serve.run(
            cognitive_app,
            name="cognitive",
            route_prefix="/cognitive",
        )
        logger.info("✅ Cognitive service is running.")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutting down gracefully...")
    finally:
        serve.shutdown()
        logger.info("✅ Serve shutdown complete.")


if __name__ == "__main__":
    main()
