#!/usr/bin/env python3
"""
init_dispatchers.py
Create/refresh Reaper, GraphDispatchers, and N queue Dispatchers.
Warm them up (DB pools) and kick off their run loops.
"""

import os
import sys
import time
import logging
from pathlib import Path

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
log = logging.getLogger("init_dispatchers")

# --- ENV defaults ---
# Use ray_utils for unified Ray configuration - no need to set defaults here
# ray_utils will handle RAY_ADDRESS internally with proper fallbacks

RAY_ADDRESS = os.getenv("RAY_ADDRESS")  # ray_utils will use this if set
RAY_NAMESPACE = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))
PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

DISPATCHER_COUNT = int(os.getenv("DISPATCHER_COUNT") or os.getenv("SEEDCORE_DISPATCHERS", "2"))
GRAPH_COUNT      = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))

FORCE_REPLACE = os.getenv("FORCE_REPLACE_DISPATCHERS", "false").lower() in ("1", "true", "yes")
EXIT_AFTER    = os.getenv("EXIT_AFTER_BOOTSTRAP", "true").lower() in ("1", "true", "yes")

PIN_TO_HEAD   = os.getenv("PIN_TO_HEAD_NODE", "false").lower() in ("1", "true", "yes")

ENV_KEYS = [
    "OCPS_DRIFT_THRESHOLD",
    "COGNITIVE_TIMEOUT_S",
    "COGNITIVE_MAX_INFLIGHT",
    "FAST_PATH_LATENCY_SLO_MS",
    "MAX_PLAN_STEPS",
    "SEEDCORE_GRAPH_DISPATCHERS",
    "ENABLE_GRAPH_DISPATCHERS",
]

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

def _kill_if_exists(name: str):
    try:
        a = ray.get_actor(name, namespace=RAY_NAMESPACE)
        ray.kill(a, no_restart=True)
        log.info("♻️ Killed %s", name)
        # wait name to be reusable
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                _ = ray.get_actor(name, namespace=RAY_NAMESPACE)
                time.sleep(0.3)
            except Exception:
                return
        log.warning("⚠️ Actor %s name may still be reserved", name)
    except Exception:
        pass

def _optional_resources():
    return {"head_node": 0.001} if PIN_TO_HEAD else None

def _ensure_reaper(env_vars: dict):
    if os.getenv("ENABLE_REAPER", "true").lower() not in ("1", "true", "yes"):
        log.info("ℹ️ Reaper disabled (ENABLE_REAPER=false)")
        return
    try:
        ray.get_actor("seedcore_reaper", namespace=RAY_NAMESPACE)
        log.info("✅ Reaper already exists")
    except Exception:
        from seedcore.agents.queue_dispatcher import Reaper
        opts = dict(name="seedcore_reaper", lifetime="detached", namespace=RAY_NAMESPACE, num_cpus=0.05, runtime_env={"env_vars": env_vars})
        res = _optional_resources()
        if res:
            opts["resources"] = res
        Reaper.options(**opts).remote(dsn=PG_DSN)
        log.info("✅ Reaper created")

def _ensure_graph_dispatchers(env_vars: dict):
    if os.getenv("ENABLE_GRAPH_DISPATCHERS", "true").lower() not in ("1", "true", "yes"):
        log.info("ℹ️ GraphDispatchers disabled")
        return
    from seedcore.agents.graph_dispatcher import GraphDispatcher

    ok = 0
    for i in range(GRAPH_COUNT):
        name = f"seedcore_graph_dispatcher_{i}"
        if FORCE_REPLACE:
            _kill_if_exists(name)
        else:
            try:
                a = ray.get_actor(name, namespace=RAY_NAMESPACE)
                try:
                    if ray.get(a.ping.remote(), timeout=5) == "pong":
                        log.info("✅ %s alive", name)
                        ok += 1
                        continue
                except Exception:
                    log.info("↪️ %s unresponsive; recreating", name)
                    _kill_if_exists(name)
            except Exception:
                pass

        opts = dict(name=name, lifetime="detached", namespace=RAY_NAMESPACE, num_cpus=0.1, runtime_env={"env_vars": env_vars}, max_restarts=1)
        res = _optional_resources()
        if res:
            opts["resources"] = res
        a = GraphDispatcher.options(**opts).remote(dsn=PG_DSN, name=name)
        time.sleep(0.5)
        try:
            if ray.get(a.ping.remote(), timeout=5) == "pong":
                log.info("✅ %s created", name)
                ok += 1
        except Exception as e:
            log.warning("⚠️ %s ping failed after create: %s", name, e)
    log.info("📊 GraphDispatchers ready: %d/%d", ok, GRAPH_COUNT)

def _ensure_dispatchers(env_vars: dict):
    from seedcore.agents.queue_dispatcher import Dispatcher

    dispatchers = []
    created = []

    for i in range(DISPATCHER_COUNT):
        name = f"seedcore_dispatcher_{i}"
        if FORCE_REPLACE:
            _kill_if_exists(name)
        else:
            try:
                a = ray.get_actor(name, namespace=RAY_NAMESPACE)
                try:
                    if ray.get(a.ping.remote(), timeout=5) == "pong":
                        log.info("✅ %s alive", name)
                        dispatchers.append(a)
                        continue
                except Exception:
                    log.info("↪️ %s unresponsive; recreating", name)
                    _kill_if_exists(name)
            except Exception:
                pass

        opts = dict(
            name=name,
            lifetime="detached",
            namespace=RAY_NAMESPACE,
            num_cpus=0.1,
            runtime_env={"env_vars": env_vars},
            max_restarts=1,
        )
        res = _optional_resources()
        if res:
            opts["resources"] = res

        a = Dispatcher.options(**opts).remote(dsn=PG_DSN, name=name)
        dispatchers.append(a)
        created.append(a)
        log.info("✅ %s created", name)

    # Warm-up newly created (ensure pool ready)
    ready = 0
    for a in created:
        try:
            ok = ray.get(a.ready.remote(timeout_s=30.0, interval_s=0.5), timeout=35.0)
            if ok:
                ready += 1
                st = ray.get(a.get_status.remote(), timeout=5)
                log.info("✅ warmup: %s", st)
            else:
                st = ray.get(a.get_status.remote(), timeout=5)
                log.warning("⚠️ not ready: %s", st)
        except Exception as e:
            log.warning("⚠️ warmup failed: %s", e)

    # Kick off run loops (fire & forget)
    for a in dispatchers:
        try:
            a.run.remote()
        except Exception as e:
            log.warning("⚠️ failed to start run loop: %s", e)

    log.info("📊 Dispatchers created: %d, warmed up: %d", len(dispatchers), ready)
    return len(dispatchers) > 0 and (ready > 0 or not created)

def bootstrap_dispatchers() -> bool:
    """Public entry used by bootstrap_entry.py."""
    try:
        if not _ensure_ray():
            log.error("❌ Failed to initialize Ray connection")
            return False
            
        if not is_ray_available():
            log.error("❌ Ray cluster unavailable")
            return False
        try:
            ci = get_ray_cluster_info()
            log.info("ℹ️ Ray cluster: %s", ci)
        except Exception:
            pass
    except Exception as e:
        log.error("❌ Failed to init Ray: %s", e)
        return False

    env_vars = {k: os.getenv(k, "") for k in ENV_KEYS}
    _ensure_reaper(env_vars)
    _ensure_graph_dispatchers(env_vars)
    ok = _ensure_dispatchers(env_vars)
    if not ok:
        log.error("❌ Dispatcher bring-up failed")
        return False

    if EXIT_AFTER:
        log.info("🚪 EXIT_AFTER_BOOTSTRAP=true — exiting")
        return True

    # Optional health loop for debugging
    log.info("👀 EXIT_AFTER_BOOTSTRAP=false — keeping job alive")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        pass
    return True

if __name__ == "__main__":
    try:
        rc = 0 if bootstrap_dispatchers() else 1
        sys.exit(rc)
    finally:
        # Clean up Ray connection
        shutdown_ray()

