#!/usr/bin/env python3
"""
init_organism.py
Initialize OrganismService via Ray Serve handle first; fall back to HTTP.
Blocks until /organism/health shows organism_initialized=true (with timeout).
"""

import os
import sys
import time

import requests  # pyright: ignore[reportMissingModuleSource]
import ray  # pyright: ignore[reportMissingImports]

from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors

from seedcore.utils.ray_utils import (
    ensure_ray_initialized,
    get_ray_cluster_info,
    is_ray_available,
    ORG,
    shutdown_ray,
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.organism")
logger = ensure_serve_logger("seedcore.organism")


# Derive organism URL from ray_utils SERVE_GATEWAY
ORGANISM_URL = ORG

# Ray connection settings - let ray_utils handle defaults
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

HEALTH_TIMEOUT_S = int(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "180"))
HEALTH_INTERVAL_S = float(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "2.0"))


def _env_bool(name: str, default: bool = False) -> bool:
    """Robust environment variable parsing for boolean values."""
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "y", "on")


# Rolling init flag controls epoch rotation behavior in OrganismService
ROLLING_INIT = _env_bool("SEEDCORE_ROLLING_INIT", False)


def _resolve_ray_response(response, timeout_s: float = 15.0):
    """
    Safely resolve Ray responses, handling both ObjectRefs and DeploymentResponses.

    Args:
        response: Either a Ray ObjectRef or Serve DeploymentResponse
        timeout_s: Timeout in seconds

    Returns:
        The resolved result

    Raises:
        Exception: If resolution fails
    """
    try:
        # Try to use .result() first (DeploymentResponse)
        if hasattr(response, "result"):
            return response.result(timeout_s=timeout_s)
        # Fall back to ray.get() for ObjectRefs
        else:
            return ray.get(response, timeout=timeout_s)
    except Exception as e:
        logger.warning(f"Failed to resolve Ray response: {e}")
        raise


def _ensure_ray() -> bool:
    """Use ray_utils to ensure Ray is properly initialized."""
    if is_ray_available():
        logger.info("✅ Ray already available")
        return True

    logger.info("🚀 Initializing Ray connection...")
    success = ensure_ray_initialized(ray_namespace=RAY_NAMESPACE, force_reinit=False)

    if success:
        cluster_info = get_ray_cluster_info()
        logger.info(f"✅ Ray connected: {cluster_info}")
        return True
    else:
        logger.error("❌ Failed to initialize Ray")
        return False


def _init_via_ray() -> bool:
    """Use Serve handle to initialize (preferred)."""
    try:
        if not _ensure_ray():
            logger.error("❌ Cannot initialize via Ray - Ray connection failed")
            return False

        from ray import serve  # pyright: ignore[reportMissingImports]

        # Ensure we're using the correct namespace for the Serve handle
        # The OrganismService is deployed in the 'serve' namespace
        logger.info("🔍 Getting OrganismService handle from 'serve' namespace...")
        h = serve.get_deployment_handle("OrganismService", app_name="organism")

        # Try health quick - handle DeploymentResponse correctly
        try:
            health = h.health.remote()
            resp = _resolve_ray_response(health, timeout_s=15)
            if isinstance(resp, dict) and resp.get("organism_initialized"):
                logger.info("✅ Organism already initialized (Serve handle)")
                return True
        except Exception as e:
            logger.info(f"ℹ️ Serve health not ready: {e}")

        # Bootstrap required singleton actors before organism initialization
        logger.info("🚀 Bootstrapping required singleton actors...")
        try:
            from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors

            bootstrap_actors()  # Core system actors in seedcore-dev namespace
            bootstrap_memory_actors()  # Memory actors in mem-dev namespace
            logger.info(
                "✅ Singleton actors (mw, miss_tracker, shared_cache) bootstrapped successfully"
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
            logger.warning(
                "⚠️ Organism may have limited functionality without memory managers"
            )

        logger.info("🚀 Calling initialize_organism via Serve handle…")
        logger.info(f"🔧 Using namespace '{RAY_NAMESPACE}' for organ/agent creation")
        logger.info(
            f"🔧 Rolling init: {ROLLING_INIT} (false rotates epoch; true keeps epoch)"
        )
        resp = h.initialize_organism.remote()
        result = _resolve_ray_response(resp, timeout_s=120)
        logger.info(f"📋 initialize_organism response: {result}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Serve handle init failed: {e}")
        return False


def _init_via_http() -> bool:
    """HTTP fallback (works even if ray client ingress is blocked)."""
    # Bootstrap required singleton actors before HTTP organism initialization
    logger.info("🚀 Bootstrapping required singleton actors via HTTP path...")
    try:
        bootstrap_actors()  # Core system actors in seedcore-dev namespace
        bootstrap_memory_actors()  # Memory actors in mem-dev namespace
        logger.info(
            "✅ Singleton actors (mw, miss_tracker, shared_cache) bootstrapped successfully"
        )
    except Exception as e:
        logger.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
        logger.warning(
            "⚠️ Organism may have limited functionality without memory managers"
        )

    url = f"{ORGANISM_URL}/initialize-organism"
    try:
        r = requests.post(url, timeout=15)
        if r.status_code == 200:
            logger.info(f"✅ HTTP initialize-organism ok: {r.json()}")
            return True
        logger.error(
            f"❌ HTTP initialize-organism failed {r.status_code}: {r.text[:200]}"
        )
        return False
    except Exception as e:
        logger.error(f"❌ HTTP exception: {e}")
        return False


def _wait_health(timeout_s: int, interval_s: float) -> bool:
    url = f"{ORGANISM_URL}/health"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if data.get("organism_initialized"):
                    # Enrich readiness logs with route and epoch expectations
                    status = data.get("status")
                    route = "/organism/health"
                    init_mode = "rolling" if ROLLING_INIT else "hard"
                    logger.info(
                        f"✅ Organism health: initialized (status={status}, route={route}, mode={init_mode})"
                    )
                    return True
                logger.info("⏳ Organism still initializing...")
            else:
                logger.info(f"ℹ️ Health HTTP {r.status_code}…")
        except Exception as e:
            logger.info(f"ℹ️ Health check error: {e}")
        time.sleep(interval_s)
    logger.error("❌ Timed out waiting for organism to initialize")
    return False


def bootstrap_organism() -> bool:
    """Public entry used by bootstrap_entry.py. Returns True/False (no sys.exit here)."""
    init_mode = "rolling" if ROLLING_INIT else "hard"
    logger.info(
        f"🚀 Starting organism bootstrap in {init_mode} mode (SEEDCORE_ROLLING_INIT={os.getenv('SEEDCORE_ROLLING_INIT', 'unset')})"
    )

    ok = _init_via_ray()
    if not ok:
        logger.info("↪️ Falling back to HTTP init")
        ok = _init_via_http()
    if not ok:
        return False
    return _wait_health(HEALTH_TIMEOUT_S, HEALTH_INTERVAL_S)


if __name__ == "__main__":
    try:
        ok = bootstrap_organism()
        sys.exit(0 if ok else 1)
    finally:
        # Clean up Ray connection
        shutdown_ray()
