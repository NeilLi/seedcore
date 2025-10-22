#!/usr/bin/env python3
"""
init_dispatchers.py
Create/refresh Reaper, GraphDispatchers, and N queue Dispatchers.
Warm them up (DB pools) and kick off their run loops.
"""
from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.dispatchers")  # centralized stdout logging only

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

log = logging.getLogger("seedcore.dispatchers")

# ---------- helpers ----------
def _env_bool(name: str, default: str | bool = "false") -> bool:
    val = os.getenv(name, str(default)).strip().lower()
    return val in ("1", "true", "yes", "y", "on")

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

# --- ENV defaults ---
# Use ray_utils for unified Ray configuration - no need to set defaults here
# ray_utils will handle RAY_ADDRESS internally with proper fallbacks

RAY_ADDRESS = os.getenv("RAY_ADDRESS")  # used by ensure_ray_initialized if set
RAY_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev")).strip() or "seedcore-dev"
PG_DSN = os.getenv("SEEDCORE_PG_DSN", os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore"))

DISPATCHER_COUNT = _env_int("DISPATCHER_COUNT", _env_int("SEEDCORE_DISPATCHERS", 2))
GRAPH_COUNT      = _env_int("SEEDCORE_GRAPH_DISPATCHERS", 1)

FORCE_REPLACE = _env_bool("FORCE_REPLACE_DISPATCHERS", "false")
EXIT_AFTER    = _env_bool("EXIT_AFTER_BOOTSTRAP", "true")

PIN_TO_HEAD   = _env_bool("PIN_TO_HEAD_NODE", "false")

# strict gating for graph dispatchers
EXPECT_GRAPH  = _env_int("EXPECT_GRAPH_DISPATCHERS", GRAPH_COUNT)
STRICT_GRAPH  = _env_bool("STRICT_GRAPH_DISPATCHERS", "false")
GRAPH_READY_TOTAL_TIMEOUT_S = _env_float("GRAPH_READY_TOTAL_TIMEOUT_S", 90.0)
GRAPH_PING_TIMEOUT_S = _env_float("GRAPH_PING_TIMEOUT_S", 10.0)

ENV_KEYS = [
    "OCPS_DRIFT_THRESHOLD",
    "COGNITIVE_TIMEOUT_S",
    "COGNITIVE_MAX_INFLIGHT",
    "FAST_PATH_LATENCY_SLO_MS",
    "MAX_PLAN_STEPS",
    "SEEDCORE_GRAPH_DISPATCHERS",
    "ENABLE_GRAPH_DISPATCHERS",
]


# ---------- ray resolution utilities ----------

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
    if not _env_bool("ENABLE_REAPER", "true"):
        log.info("ℹ️ Reaper disabled (ENABLE_REAPER=false)")
        return
    try:
        reaper = ray.get_actor("seedcore_reaper", namespace=RAY_NAMESPACE)
        log.info("✅ Reaper already exists")
        
        # Run one-shot stale task sweep during bootstrap
        try:
            result = ray.get(reaper.reap_stale_tasks.remote(), timeout=30)
            log.info(f"✅ Initial stale task sweep completed: {result}")
        except Exception as e:
            log.warning(f"Initial stale task sweep failed: {e}")
    except Exception:
        from seedcore.dispatcher import Reaper
        opts = dict(name="seedcore_reaper", lifetime="detached", namespace=RAY_NAMESPACE, num_cpus=0.05, runtime_env={"env_vars": env_vars})
        res = _optional_resources()
        if res:
            opts["resources"] = res
        reaper = Reaper.options(**opts).remote(dsn=PG_DSN)
        log.info("✅ Reaper created")
        
        # Run one-shot stale task sweep after creating reaper
        try:
            result = ray.get(reaper.reap_stale_tasks.remote(), timeout=30)
            log.info(f"✅ Initial stale task sweep completed: {result}")
        except Exception as e:
            log.warning(f"Initial stale task sweep failed: {e}")

def _ensure_graph_dispatchers(env_vars: dict):
    if not _env_bool("ENABLE_GRAPH_DISPATCHERS", "true"):
        log.info("ℹ️ GraphDispatchers disabled")
        return
    from seedcore.dispatcher import GraphDispatcher

    graph_dispatchers_all = []
    graph_dispatchers_created = []
    ok = 0
    for i in range(GRAPH_COUNT):
        name = f"seedcore_graph_dispatcher_{i}"
        if FORCE_REPLACE:
            _kill_if_exists(name)
        else:
            try:
                a = ray.get_actor(name, namespace=RAY_NAMESPACE)
                try:
                    if ray.get(a.ping.remote(), timeout=GRAPH_PING_TIMEOUT_S) == "pong":
                        log.info("✅ %s alive", name)
                        graph_dispatchers_all.append(a)
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
        graph_dispatchers_all.append(a)
        graph_dispatchers_created.append(a)

        # Short grace before probing
        time.sleep(1.0)

        # Retry ping with capped exponential backoff (bounded by GRAPH_READY_TOTAL_TIMEOUT_S)
        max_retries = 6
        retry_delay = 2.0
        ping_success = False
        waited = 0.0
        
        for attempt in range(max_retries):
            try:
                # Optional: ask for startup status if actor implements it
                try:
                    status = ray.get(a.get_startup_status.remote(), timeout=5)
                    log.info("📊 %s startup (attempt %d/%d): %s", name, attempt + 1, max_retries, status)
                except Exception:
                    pass

                if ray.get(a.ping.remote(), timeout=GRAPH_PING_TIMEOUT_S) == "pong":
                    log.info("✅ %s created and responsive (attempt %d/%d)", name, attempt + 1, max_retries)
                    ok += 1
                    ping_success = True
                    break
            except Exception as e:
                if attempt < max_retries - 1:
                    log.info("⏳ %s not ready (attempt %d/%d): %s — retrying in %.1fs", name, attempt + 1, max_retries, e, retry_delay)
                    time.sleep(retry_delay)
                    waited += retry_delay
                    if waited >= GRAPH_READY_TOTAL_TIMEOUT_S:
                        log.warning("⚠️ %s exceeded total wait budget (%.1fs)", name, GRAPH_READY_TOTAL_TIMEOUT_S)
                        break
                    retry_delay *= 2  # Exponential backoff
                else:
                    log.warning("⚠️ %s ping failed after %d attempts: %s", name, max_retries, e)
        
        if not ping_success:
            log.warning("⚠️ %s created but not responsive after all retries", name)

    # Start run loops only for actors we just created (avoid double-run enqueues)
    for a in graph_dispatchers_created:
        try:
            a.run.remote()
            log.info("🚀 Started GraphDispatcher run loop")
        except Exception as e:
            log.warning("⚠️ Failed to start GraphDispatcher loop: %s", e)

    log.info("📊 GraphDispatchers responsive: %d/%d (expected=%d, strict=%s)", ok, GRAPH_COUNT, EXPECT_GRAPH, STRICT_GRAPH)
    if STRICT_GRAPH and ok < EXPECT_GRAPH:
        # Surface a clear gating error to the caller
        raise RuntimeError(f"Only {ok}/{EXPECT_GRAPH} GraphDispatchers responsive with STRICT_GRAPH_DISPATCHERS=true")

def _ensure_dispatchers(env_vars: dict):
    from seedcore.dispatcher import Dispatcher

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
    try:
        _ensure_graph_dispatchers(env_vars)
    except Exception as e:
        log.error("❌ GraphDispatcher bring-up failed: %s", e)
        # If strict, abort bootstrap; otherwise continue with queue dispatchers
        if STRICT_GRAPH:
            return False

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

