#!/usr/bin/env python3
"""
init_dispatchers.py
Orchestrates background workers: Reaper, Queue Dispatchers, and Graph Dispatchers.
Ensures High Availability and Warm-up.
"""

import os
import sys
import time
from typing import Type, Any

import ray  # pyright: ignore[reportMissingImports]

# Core Imports
from seedcore.utils.ray_utils import (
    ensure_ray_initialized,
    get_ray_cluster_info,
    shutdown_ray,
)
from seedcore.dispatcher import Reaper, Dispatcher, GraphDispatcher
from seedcore.logging_setup import setup_logging, ensure_serve_logger

# Setup Logging
setup_logging(app_name="seedcore.dispatchers")
logger = ensure_serve_logger("seedcore.dispatchers")

# --- Configuration Constants ---
RAY_NAMESPACE = os.getenv(
    "RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev")
).strip()
FORCE_REPLACE = os.getenv("FORCE_REPLACE_DISPATCHERS", "false").lower() == "true"
EXIT_AFTER = os.getenv("EXIT_AFTER_BOOTSTRAP", "true").lower() == "true"
PIN_TO_HEAD = os.getenv("PIN_TO_HEAD_NODE", "false").lower() == "true"

# Feature Flags & Counts
ENABLE_REAPER = os.getenv("ENABLE_REAPER", "true").lower() == "true"
ENABLE_GRAPH = os.getenv("ENABLE_GRAPH_DISPATCHERS", "true").lower() == "true"

DISPATCHER_COUNT = int(
    os.getenv("DISPATCHER_COUNT", os.getenv("SEEDCORE_DISPATCHERS", "2"))
)
GRAPH_COUNT = int(os.getenv("SEEDCORE_GRAPH_DISPATCHERS", "1"))
STRICT_GRAPH = os.getenv("STRICT_GRAPH_DISPATCHERS", "false").lower() == "true"

# Critical Env Vars to propagate to Actors
ENV_KEYS_TO_PROPAGATE = [
    "OCPS_DRIFT_THRESHOLD",
    "COGNITIVE_TIMEOUT_S",
    "COGNITIVE_MAX_INFLIGHT",
    "FAST_PATH_LATENCY_SLO_MS",
    "MAX_PLAN_STEPS",
    "NIM_RETRIEVAL_MODEL",
    "NIM_RETRIEVAL_BASE_URL",
    "NIM_RETRIEVAL_API_KEY",
    "NIM_RETRIEVAL_PROVIDER",
]

# --- Main Entry Point ---


def bootstrap_dispatchers() -> bool:
    """
    Main orchestration function.
    """
    logger.info("🚀 Starting Dispatcher Bootstrap Sequence...")

    # 1. Connect to Ray
    if not _connect_ray():
        return False

    # 2. Prepare Environment
    env_vars = {k: os.getenv(k, "") for k in ENV_KEYS_TO_PROPAGATE}
    resource_opts = {"resources": {"head_node": 0.001}} if PIN_TO_HEAD else {}

    # 3. Bootstrap Components
    success = True

    # A. Reaper (Singleton)
    if ENABLE_REAPER:
        if not _ensure_singleton(Reaper, "seedcore_reaper", env_vars, resource_opts):
            success = False

    # B. Graph Dispatchers (Pool)
    if ENABLE_GRAPH:
        if not _ensure_actor_pool(
            actor_cls=GraphDispatcher,
            base_name="graph_dispatcher",
            count=GRAPH_COUNT,
            env_vars=env_vars,
            res_opts=resource_opts,
            strict=STRICT_GRAPH,
        ):
            success = False
            if STRICT_GRAPH:
                return False  # Abort early

    # C. Queue Dispatchers (Pool)
    if not _ensure_actor_pool(
        actor_cls=Dispatcher,
        base_name="queue_dispatcher",
        count=DISPATCHER_COUNT,
        env_vars=env_vars,
        res_opts=resource_opts,
    ):
        success = False

    # 4. Exit Strategy
    if success:
        logger.info("✅ All Dispatchers Bootstrapped Successfully.")

    if not EXIT_AFTER and success:
        logger.info("👀 Keeping process alive (monitoring mode)...")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass

    return success


# --- Generic Helpers ---


def _connect_ray() -> bool:
    """Ensures Ray connection."""
    try:
        if ensure_ray_initialized(ray_namespace=RAY_NAMESPACE, force_reinit=False):
            logger.info(f"✅ Ray Connected: {get_ray_cluster_info()}")
            return True
    except Exception as e:
        logger.error(f"❌ Ray Connection Failed: {e}")
    return False


def _kill_actor(name: str):
    """Safely kills an actor by name."""
    try:
        actor = ray.get_actor(name, namespace=RAY_NAMESPACE)
        ray.kill(actor, no_restart=True)
        logger.info(f"♻️ Killed {name}")
        # Wait for death
        for _ in range(10):
            try:
                ray.get_actor(name, namespace=RAY_NAMESPACE)
                time.sleep(0.5)
            except ValueError:
                return  # Gone
    except ValueError:
        pass  # Already gone
    except Exception as e:
        logger.warning(f"⚠️ Error killing {name}: {e}")


def _ensure_singleton(
    actor_cls: Type, name: str, env_vars: dict, res_opts: dict
) -> bool:
    """Ensures a single named actor exists and is running."""
    actor = None

    if FORCE_REPLACE:
        _kill_actor(name)
    else:
        try:
            actor = ray.get_actor(name, namespace=RAY_NAMESPACE)
            # Health Check
            ray.get(actor.ping.remote(), timeout=5)
            logger.info(f"✅ Found existing {name}")
        except Exception:
            logger.info(f"re-creating {name}...")
            actor = None

    if not actor:
        try:
            opts = {
                "name": name,
                "lifetime": "detached",
                "namespace": RAY_NAMESPACE,
                "num_cpus": 0.05,
                "runtime_env": {"env_vars": env_vars},
                **res_opts,
            }
            actor = actor_cls.options(**opts).remote()
            logger.info(f"✅ Created {name}")
        except Exception as e:
            logger.error(f"❌ Failed to create {name}: {e}")
            return False

    # Idempotent Run Trigger
    try:
        actor.run.remote()
    except Exception as e:
        logger.warning(f"⚠️ Failed to trigger run loop on {name}: {e}")

    return True


def _ensure_actor_pool(
    actor_cls: Type,
    base_name: str,
    count: int,
    env_vars: dict,
    res_opts: dict,
    strict: bool = False,
) -> bool:
    """
    Generic logic to ensure a pool of actors (Graph or Queue Dispatchers).
    """
    ready_count = 0

    for i in range(count):
        name = f"{base_name}_{i}"
        actor = None

        # 1. Check Existing
        if not FORCE_REPLACE:
            try:
                actor = ray.get_actor(name, namespace=RAY_NAMESPACE)
                ray.get(actor.ping.remote(), timeout=5)
                logger.info(f"✅ Found {name}")
            except Exception:
                actor = None
        else:
            _kill_actor(name)

        # 2. Create if missing
        if not actor:
            try:
                opts = {
                    "name": name,
                    "lifetime": "detached",
                    "namespace": RAY_NAMESPACE,
                    "num_cpus": 0.1,
                    "max_restarts": 1,
                    "runtime_env": {"env_vars": env_vars},
                    **res_opts,
                }
                actor = actor_cls.options(**opts).remote()

                # Wait for startup
                _wait_for_startup(actor, name)
                logger.info(f"✅ Created {name}")

            except Exception as e:
                logger.error(f"❌ Failed to create {name}: {e}")
                continue

        # 3. Warmup & Run
        try:
            # Check readiness (DB pools etc) - only if actor has ready() method
            is_ready = True  # Default to ready if no ready() method
            try:
                # Try to call ready() - only Dispatcher (queue_dispatcher) has this
                # Use a shorter timeout to avoid hanging on gRPC issues
                is_ready = ray.get(actor.ready.remote(timeout_s=20.0), timeout=25.0)
            except AttributeError:
                # GraphDispatcher doesn't have ready() method - that's OK, skip the check
                logger.debug(f"  ℹ️ {name} doesn't have ready() method, skipping readiness check")
                is_ready = True
            except ray.exceptions.RayActorError as ray_err:
                # Actor died or session was cleaned up - this is recoverable
                logger.warning(f"⚠️ {name} actor error during ready() check: {ray_err}")
                is_ready = False
            except Exception as ready_err:
                # Check if it's a gRPC connection error (common during startup)
                err_str = str(ready_err)
                if "cleaned up" in err_str or "NOT_FOUND" in err_str or "reconnect" in err_str:
                    logger.debug(f"  ℹ️ {name} gRPC connection issue during ready() (may retry): {ready_err}")
                    is_ready = False  # Will retry on next cycle
                else:
                    logger.warning(f"⚠️ {name} ready() check failed: {ready_err}")
                    is_ready = False
            
            if is_ready:
                ready_count += 1
                try:
                    actor.run.remote()  # Idempotent start
                except ray.exceptions.RayActorError:
                    logger.warning(f"⚠️ {name} actor died before run() could be called")
            else:
                logger.warning(f"⚠️ {name} reported not ready")
        except Exception as e:
            logger.warning(f"⚠️ {name} warmup/run failed: {e}")

    logger.info(f"📊 {base_name} Pool: {ready_count}/{count} ready")

    if strict and ready_count < count:
        logger.error(f"❌ Strict mode enabled: Expected {count}, got {ready_count}")
        return False

    return ready_count > 0


def _wait_for_startup(actor: Any, name: str, timeout: int = 20):
    """Polite wait for actor to become pingable."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            ray.get(actor.ping.remote(), timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    logger.warning(f"⚠️ {name} slow startup (ping timed out)")


if __name__ == "__main__":
    try:
        success = bootstrap_dispatchers()
        sys.exit(0 if success else 1)
    finally:
        shutdown_ray()
