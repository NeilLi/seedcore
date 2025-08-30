#!/usr/bin/env python
"""
bootstrap_organism.py
---------------------
Adaptive bootstrap script for OrganismManager and its organs.
Intended to run as a Kubernetes Job, exits cleanly once initialization completes.
"""

import os
import sys
import time
import json
import logging
import asyncio
import requests
import ray
import yaml
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bootstrap_organism")

# --- Config defaults ---
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "src" / "seedcore" / "config" / "defaults.yaml"

ORGANISM_URL = os.getenv("ORGANISM_URL", "http://127.0.0.1:8000/organism")
SERVE_BASE_URL = os.getenv("SERVE_BASE_URL", "http://127.0.0.1:8000")
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://127.0.0.1:10001")
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

EXIT_AFTER_BOOTSTRAP = os.getenv("EXIT_AFTER_BOOTSTRAP", "true").lower() == "true"


def load_config(path=DEFAULT_CONFIG_PATH):
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        log.error(f"Failed to load config {path}: {e}")
        sys.exit(1)


async def init_via_ray(config):
    """Initialize OrganismManager and organs using Ray handles (preferred)."""
    import ray

    try:
        ray.init(address=RAY_ADDRESS, namespace=RAY_NAMESPACE)
        log.info(f"✅ Connected to Ray at {RAY_ADDRESS} (ns={RAY_NAMESPACE})")
    except Exception as e:
        log.error(f"❌ Failed to connect to Ray: {e}")
        return False

    try:
        # Get handle to OrganismManager Serve deployment
        from ray import serve
        handle = serve.get_deployment_handle("OrganismManager", app_name="organism")

        # Call initialize-organism
        result = await handle.initialize_organism.remote(config["seedcore"]["organism"])
        result = await result
        log.info(f"Organism initialize response: {result}")
        return True
    except Exception as e:
        log.error(f"❌ Failed to initialize OrganismManager via Ray: {e}")
        return False


def init_via_http(config):
    """Fallback path: initialize via Serve HTTP API."""
    url = f"{ORGANISM_URL}/initialize-organism"
    try:
        resp = requests.post(url, json=config["seedcore"]["organism"], timeout=10)
        if resp.status_code == 200:
            log.info(f"✅ Organism initialized via HTTP: {resp.json()}")
            return True
        else:
            log.error(f"❌ HTTP init failed {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        log.error(f"❌ Exception in HTTP init: {e}")
        return False


def wait_for_health(timeout=60, interval=5):
    """Poll /organism/health until healthy or timeout."""
    url = f"{ORGANISM_URL}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("organism_initialized"):
                    log.info(f"✅ Organism health OK: {data}")
                    return True
                else:
                    log.info("⏳ Organism still initializing...")
            else:
                log.warning(f"⚠️ Health returned {resp.status_code}")
        except Exception as e:
            log.warning(f"Health check failed: {e}")
        time.sleep(interval)
    log.error("❌ Timed out waiting for organism to initialize")
    return False


async def main():
    cfg = load_config()
    log.info(f"Loaded config with organs: {cfg['seedcore']['organism']['organ_types']}")

    # Step 1: Try Ray Serve initialization
    ok = await init_via_ray(cfg)
    if not ok:
        log.warning("⚠️ Falling back to HTTP initialization")
        ok = init_via_http(cfg)

    # Step 2: Poll health endpoint
    if ok:
        if not wait_for_health(timeout=120, interval=5):
            sys.exit(1)
    else:
        sys.exit(1)

    log.info("🎉 Organism bootstrap completed successfully")

    if EXIT_AFTER_BOOTSTRAP:
        log.info("🚪 EXIT_AFTER_BOOTSTRAP=true, exiting now")
        sys.exit(0)
    else:
        log.info("👀 Staying alive for debugging...")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())

