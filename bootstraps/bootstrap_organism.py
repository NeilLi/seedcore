#!/usr/bin/env python3
"""
init_organism.py
Robust Bootstrap Driver for SeedCore Organism.

Phases:
1. Connect to Ray Cluster
2. Bootstrap Shared Singletons (Memory, Cache, MW)
3. Trigger OrganismService Initialization (via Serve Handle or HTTP)
4. Block until Healthy
"""

import os
import sys
import time
import requests  # pyright: ignore[reportMissingModuleSource]
from ray import serve  # pyright: ignore[reportMissingImports]

from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors
from seedcore.utils.ray_utils import (
    ensure_ray_initialized,
    get_ray_cluster_info,
    is_ray_available,
    ORG,
    shutdown_ray,
)
from seedcore.logging_setup import setup_logging, ensure_serve_logger

# Configuration
setup_logging(app_name="seedcore.bootstrap.organism")
logger = ensure_serve_logger("seedcore.bootstrap.organism")

ORGANISM_URL = ORG
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
HEALTH_TIMEOUT_S = int(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "180"))
HEALTH_INTERVAL_S = float(os.getenv("ORGANISM_HEALTH_INTERVAL_S", "2.0"))
ROLLING_INIT = os.getenv("SEEDCORE_ROLLING_INIT", "false").lower() == "true"


def bootstrap_organism() -> bool:
    """
    Main entry point. Returns True on success, False on failure.
    """
    logger.info("🚀 Starting SeedCore Bootstrap Sequence...")

    # ---------------------------------------------------------
    # Phase 1: Infrastructure Connectivity
    # ---------------------------------------------------------
    if not _ensure_ray_connection():
        return False

    # ---------------------------------------------------------
    # Phase 2: Dependency Injection (Singletons)
    # ---------------------------------------------------------
    if not _bootstrap_dependencies():
        logger.error("❌ Critical: Failed to bootstrap singleton dependencies.")
        return False

    # ---------------------------------------------------------
    # Phase 3: Service Activation
    # ---------------------------------------------------------
    logger.info("🚀 Triggering OrganismService Initialization...")

    # Try Ray Handle (Preferred: Fastest, Internal)
    activated = _trigger_via_ray_handle()

    # Fallback to HTTP (External)
    if not activated:
        logger.warning("⚠️ Ray Handle failed, attempting HTTP fallback...")
        activated = _trigger_via_http()

    if not activated:
        logger.error("❌ Failed to trigger initialization via any method.")
        return False

    # ---------------------------------------------------------
    # Phase 4: Readiness Check (Barrier)
    # ---------------------------------------------------------
    return _wait_for_healthy_state(HEALTH_TIMEOUT_S, HEALTH_INTERVAL_S)


# ==============================================================================
# Helper Functions
# ==============================================================================


def _ensure_ray_connection() -> bool:
    """Connects to Ray cluster idempotently."""
    try:
        if is_ray_available():
            logger.info("✅ Ray already connected.")
            return True

        logger.info(f"🔌 Connecting to Ray (Namespace: {RAY_NAMESPACE})...")
        if ensure_ray_initialized(ray_namespace=RAY_NAMESPACE, force_reinit=False):
            logger.info(f"✅ Connected: {get_ray_cluster_info()}")
            return True
    except Exception as e:
        logger.error(f"❌ Ray connection failure: {e}")

    return False


def _bootstrap_dependencies() -> bool:
    """Bootstraps lower-level actors (Memory, Cache) before the main Organism."""
    try:
        logger.info("🛠 Bootstrapping Shared Singletons...")
        # These functions should be idempotent internally
        bootstrap_actors()  # System actors (seedcore-dev)
        bootstrap_memory_actors()  # Memory actors (mem-dev)
        logger.info("✅ Singletons (MW, Cache, Memory) ready.")
        return True
    except Exception as e:
        logger.exception(f"❌ Dependency bootstrap failed: {e}")
        return False


def _trigger_via_ray_handle() -> bool:
    """Invokes initialize_organism() via Ray Serve Handle."""
    try:
        # Get handle to the 'OrganismService' deployment app
        # Note: 'organism' is the app name in serve_config.yaml
        h = serve.get_deployment_handle("OrganismService", app_name="organism")

        # Invoke remote method
        # Using a timeout prevents hanging if the actor is dead
        ref = h.initialize_organism.remote()
        result = ref.result(timeout_s=30)  # Blocks safely

        logger.info(f"✅ Ray Init Triggered: {result}")
        return True

    except Exception as e:
        logger.warning(f"⚠️ Ray Handle Trigger failed: {e}")
        return False


def _trigger_via_http() -> bool:
    """Invokes initialize-organism via HTTP API."""
    url = f"{ORGANISM_URL}/initialize-organism"
    try:
        resp = requests.post(url, timeout=10)
        if resp.status_code == 200:
            logger.info(f"✅ HTTP Init Triggered: {resp.json()}")
            return True
        logger.error(f"❌ HTTP Error {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"❌ HTTP Connection failed: {e}")
    return False


def _wait_for_healthy_state(timeout: int, interval: float) -> bool:
    """Blocks until the /health endpoint reports initialized=True."""
    logger.info(f"⏳ Waiting for Healthy State (Timeout: {timeout}s)...")

    deadline = time.time() + timeout

    # Use handle for health checks too if possible, but HTTP is fine for external validation
    url = f"{ORGANISM_URL}/health"

    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("organism_initialized") is True:
                    logger.info("✅ System Ready! 🚀")
                    return True

                # Still warming up
                logger.debug(f"Still initializing... ({data.get('status')})")

        except requests.RequestException:
            # Service might be restarting or unreachable
            pass

        time.sleep(interval)

    logger.error("❌ Timeout waiting for OrganismService health.")
    return False


if __name__ == "__main__":
    try:
        success = bootstrap_organism()
        sys.exit(0 if success else 1)
    finally:
        # Cleanup acts as a good citizen in shared environments
        shutdown_ray()
