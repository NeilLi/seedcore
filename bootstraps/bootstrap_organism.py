#!/usr/bin/env python3
"""
init_organism.py
Initialize OrganismManager via Ray Serve handle first; fall back to HTTP.
Blocks until /organism/health shows organism_initialized=true (with timeout).
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.organism")

import os
import sys
import time
import json
import logging
from pathlib import Path

import requests

# Add src to path for imports
ROOT = Path(__file__).resolve().parents[1]  # /app
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from seedcore.utils.ray_utils import (
    ensure_ray_initialized,
    is_ray_available,
    get_ray_cluster_info,
    shutdown_ray
)

import ray

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
log = logging.getLogger("seedcore.organism")

# --- Defaults & ENV ---
DEFAULT_CONFIG_PATH = Path(
    os.getenv("SEEDCORE_DEFAULT_CONFIG", str(SRC / "seedcore" / "config" / "defaults.yaml"))
)

# Use ray_utils constants and methods for unified configuration
from seedcore.utils.ray_utils import SERVE_GATEWAY, ML, COG

# Derive organism URL from ray_utils SERVE_GATEWAY
ORGANISM_URL = os.getenv("ORGANISM_URL", f"{SERVE_GATEWAY}/organism")

# Ray connection settings - let ray_utils handle defaults
RAY_ADDRESS = os.getenv("RAY_ADDRESS")  # ray_utils will use this internally
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

HEALTH_TIMEOUT_S = int(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "180"))
HEALTH_INTERVAL_S = float(os.getenv("ORGANISM_HEALTH_TIMEOUT_S", "2.0"))

def _load_config(path: Path) -> dict:
    import yaml
    try:
        with open(path, "r") as f:
            cfg = yaml.safe_load(f)
        if not cfg or "seedcore" not in cfg or "organism" not in cfg["seedcore"]:
            raise ValueError("Config missing required keys: seedcore.organism")
        return cfg
    except Exception as e:
        log.error(f"Failed to load config {path}: {e}")
        raise

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
        if hasattr(response, 'result'):
            return response.result(timeout_s=timeout_s)
        # Fall back to ray.get() for ObjectRefs
        else:
            import ray
            return ray.get(response, timeout=timeout_s)
    except Exception as e:
        log.warning(f"Failed to resolve Ray response: {e}")
        raise

def _ensure_ray() -> bool:
    """Use ray_utils to ensure Ray is properly initialized."""
    if is_ray_available():
        log.info("✅ Ray already available")
        return True
    
    log.info("🚀 Initializing Ray connection...")
    success = ensure_ray_initialized(
        ray_namespace=RAY_NAMESPACE,
        force_reinit=False
    )
    
    if success:
        cluster_info = get_ray_cluster_info()
        log.info(f"✅ Ray connected: {cluster_info}")
        return True
    else:
        log.error("❌ Failed to initialize Ray")
        return False

def _init_via_ray(cfg: dict) -> bool:
    """Use Serve handle to initialize (preferred)."""
    try:
        if not _ensure_ray():
            log.error("❌ Cannot initialize via Ray - Ray connection failed")
            return False
            
        from ray import serve
        
        # Ensure we're using the correct namespace for the Serve handle
        # The OrganismManager is deployed in the 'serve' namespace
        log.info(f"🔍 Getting OrganismManager handle from 'serve' namespace...")
        h = serve.get_deployment_handle("OrganismManager", app_name="organism")
        
        # Try health quick - handle DeploymentResponse correctly
        try:
            health = h.health.remote()
            resp = _resolve_ray_response(health, timeout_s=15)
            if isinstance(resp, dict) and resp.get("organism_initialized"):
                log.info("✅ Organism already initialized (Serve handle)")
                return True
        except Exception as e:
            log.info(f"ℹ️ Serve health not ready: {e}")

        # Bootstrap required singleton actors before organism initialization
        log.info("🚀 Bootstrapping required singleton actors...")
        try:
            from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors
            bootstrap_actors()  # Core system actors in seedcore-dev namespace
            bootstrap_memory_actors()  # Memory actors in mem-dev namespace
            log.info("✅ Singleton actors (mw, miss_tracker, shared_cache) bootstrapped successfully")
        except Exception as e:
            log.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
            log.warning("⚠️ Organism may have limited functionality without memory managers")
        
        log.info("🚀 Calling initialize_organism via Serve handle…")
        log.info(f"🔧 Using namespace '{RAY_NAMESPACE}' for organ/agent creation")
        resp = h.initialize_organism.remote()
        result = _resolve_ray_response(resp, timeout_s=120)
        log.info(f"📋 initialize_organism response: {result}")
        return True
    except Exception as e:
        log.warning(f"⚠️ Serve handle init failed: {e}")
        return False

def _init_via_http(cfg: dict) -> bool:
    """HTTP fallback (works even if ray client ingress is blocked)."""
    # Bootstrap required singleton actors before HTTP organism initialization
    log.info("🚀 Bootstrapping required singleton actors via HTTP path...")
    try:
        from seedcore.bootstrap import bootstrap_actors, bootstrap_memory_actors
        bootstrap_actors()  # Core system actors in seedcore-dev namespace
        bootstrap_memory_actors()  # Memory actors in mem-dev namespace
        log.info("✅ Singleton actors (mw, miss_tracker, shared_cache) bootstrapped successfully")
    except Exception as e:
        log.warning(f"⚠️ Failed to bootstrap singleton actors: {e}")
        log.warning("⚠️ Organism may have limited functionality without memory managers")
    
    url = f"{ORGANISM_URL}/initialize-organism"
    try:
        r = requests.post(url, json=cfg["seedcore"]["organism"], timeout=15)
        if r.status_code == 200:
            log.info(f"✅ HTTP initialize-organism ok: {r.json()}")
            return True
        log.error(f"❌ HTTP initialize-organism failed {r.status_code}: {r.text[:200]}")
        return False
    except Exception as e:
        log.error(f"❌ HTTP exception: {e}")
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
                    log.info("✅ Organism health: initialized")
                    return True
                log.info("⏳ Organism still initializing...")
            else:
                log.info(f"ℹ️ Health HTTP {r.status_code}…")
        except Exception as e:
            log.info(f"ℹ️ Health check error: {e}")
        time.sleep(interval_s)
    log.error("❌ Timed out waiting for organism to initialize")
    return False

def bootstrap_organism() -> bool:
    """Public entry used by bootstrap_entry.py. Returns True/False (no sys.exit here)."""
    try:
        cfg = _load_config(DEFAULT_CONFIG_PATH)
    except Exception:
        return False

    ok = _init_via_ray(cfg)
    if not ok:
        log.info("↪️ Falling back to HTTP init")
        ok = _init_via_http(cfg)
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

