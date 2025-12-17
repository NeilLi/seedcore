#!/usr/bin/env python3
"""
Robust Bootstrap Driver for SeedCore Organism.

Phases:
1. Connect to Ray Cluster
2. Bootstrap Shared Singletons (Memory, Cache, MW)
3. Wait for OrganismService Serve Deployment
4. Trigger OrganismService Initialization
5. Block until Healthy
"""

import os
import sys
import time
import requests  # pyright: ignore[reportMissingModuleSource]

from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors
from seedcore.utils.ray_utils import (
    ensure_ray_initialized,
    get_ray_cluster_info,
    is_ray_available,
    ORG,
    shutdown_ray,
)
from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.serve.organism_client import get_organism_service_handle


# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
setup_logging(app_name="seedcore.bootstrap.organism")
logger = ensure_serve_logger("seedcore.bootstrap.organism")

ORGANISM_URL = ORG
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

HEALTH_TIMEOUT_S = int(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "180"))
HEALTH_INTERVAL_S = float(os.getenv("ORGANISM_HEALTH_INTERVAL_S", "2.0"))

INIT_TRIGGER_TIMEOUT_S = int(os.getenv("ORGANISM_INIT_TRIGGER_TIMEOUT_S", "60"))
INIT_TRIGGER_INTERVAL_S = float(os.getenv("ORGANISM_INIT_TRIGGER_INTERVAL_S", "2.0"))


# ------------------------------------------------------------------------------
# Main Entry
# ------------------------------------------------------------------------------

def bootstrap_organism() -> bool:
    logger.info("🚀 Starting SeedCore Bootstrap Sequence...")

    if not _ensure_ray_connection():
        return False

    if not _bootstrap_dependencies():
        return False

    if not _wait_for_service_reachable(INIT_TRIGGER_TIMEOUT_S):
        logger.error("❌ OrganismService never became reachable.")
        return False

    if not _trigger_initialization(INIT_TRIGGER_TIMEOUT_S):
        logger.error("❌ Failed to trigger OrganismService initialization.")
        return False

    return _wait_for_healthy_state(HEALTH_TIMEOUT_S, HEALTH_INTERVAL_S)


# ------------------------------------------------------------------------------
# Phase Helpers
# ------------------------------------------------------------------------------

def _ensure_ray_connection() -> bool:
    try:
        if is_ray_available():
            logger.info("✅ Ray already connected.")
            return True

        logger.info(f"🔌 Connecting to Ray (namespace={RAY_NAMESPACE})...")
        if ensure_ray_initialized(ray_namespace=RAY_NAMESPACE, force_reinit=False):
            logger.info(f"✅ Connected: {get_ray_cluster_info()}")
            return True
    except Exception as e:
        logger.exception(f"❌ Ray connection failed: {e}")
    return False


def _bootstrap_dependencies() -> bool:
    try:
        logger.info("🛠 Bootstrapping shared singletons...")
        bootstrap_actors()
        bootstrap_memory_actors()
        logger.info("✅ Singletons (MW, Cache, Memory) ready.")
        return True
    except Exception as e:
        logger.exception(f"❌ Dependency bootstrap failed: {e}")
        return False


# ------------------------------------------------------------------------------
# Serve Readiness
# ------------------------------------------------------------------------------

def _wait_for_service_reachable(timeout: int) -> bool:
    """
    Wait until OrganismService Serve deployment is reachable
    (not necessarily initialized).
    """
    logger.info("⏳ Waiting for OrganismService deployment to become reachable...")

    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            # Prefer Ray handle if possible
            handle = get_organism_service_handle()
            handle.options(timeout_s=5)
            logger.info("✅ OrganismService handle acquired.")
            return True
        except Exception:
            pass

        # Fallback: HTTP route existence
        try:
            r = requests.get(f"{ORGANISM_URL}/health", timeout=2)
            if r.status_code in (200, 503):
                logger.info("✅ OrganismService HTTP route detected.")
                return True
        except Exception:
            pass

        time.sleep(2)

    return False


# ------------------------------------------------------------------------------
# Initialization Trigger
# ------------------------------------------------------------------------------

def _trigger_initialization(timeout: int) -> bool:
    logger.info("🚀 Triggering OrganismService initialization...")

    deadline = time.time() + timeout

    while time.time() < deadline:
        if _trigger_via_ray_handle():
            return True

        if _trigger_via_http():
            return True

        time.sleep(INIT_TRIGGER_INTERVAL_S)

    return False


def _trigger_via_ray_handle() -> bool:
    try:
        h = get_organism_service_handle()
        if hasattr(h, "rpc_initialize_organism"):
            ref = h.rpc_initialize_organism.remote()
            ref.result(timeout_s=10)
            logger.info("✅ Initialization triggered via Ray RPC.")
            return True
    except Exception as e:
        logger.debug(f"Ray init attempt failed: {e}")
    return False


def _trigger_via_http() -> bool:
    try:
        r = requests.post(f"{ORGANISM_URL}/initialize-organism", timeout=5)
        if r.status_code == 200:
            logger.info("✅ Initialization triggered via HTTP.")
            return True
        if r.status_code == 503:
            logger.debug("HTTP init endpoint not ready yet (503).")
    except Exception:
        pass
    return False


# ------------------------------------------------------------------------------
# Health Barrier
# ------------------------------------------------------------------------------

def _wait_for_healthy_state(timeout: int, interval: float) -> bool:
    logger.info(f"⏳ Waiting for healthy state (timeout={timeout}s)...")
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            r = requests.get(f"{ORGANISM_URL}/health", timeout=2)
            if r.status_code == 200:
                data = r.json()
                if data.get("organism_initialized") is True:
                    logger.info("✅ Organism fully initialized. System READY 🚀")
                    return True
                logger.debug(f"Still initializing: {data}")
        except Exception:
            pass

        time.sleep(interval)

    logger.error("❌ Timeout waiting for healthy OrganismService.")
    return False


# ------------------------------------------------------------------------------
# Entrypoint
# ------------------------------------------------------------------------------


if __name__ == "__main__":
    try:
        success = bootstrap_organism()
        sys.exit(0 if success else 1)
    finally:
        # Cleanup acts as a good citizen in shared environments
        shutdown_ray()
