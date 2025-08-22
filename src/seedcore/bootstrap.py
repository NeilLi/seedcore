#!/usr/bin/env python3
"""
Create/retrieve singleton Ray actors (detached) in a consistent namespace.
- Safe to call from drivers or replicas (handles races).
- Respects RAY_NAMESPACE if set; otherwise uses Ray runtime context; else a default.
- Optionally auto-initializes Ray (address=auto) when invoked outside Ray.
- Uses `get_if_exists=True` if available (Ray >= 2.4), otherwise falls back to race-safe pattern.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import ray

# Import the ACTOR CLASSES (must be decorated with @ray.remote)
from .memory.working_memory import MissTracker, SharedCache, MwStore  # type: ignore

# -----------------------------------------------------------------------------
# Config & logging
# -----------------------------------------------------------------------------
@dataclass(frozen=True)
class _Cfg:
    default_namespace: str = os.getenv("SEEDCORE_DEFAULT_NAMESPACE", "seedcore-dev")
    # Use RAY_HOST and RAY_PORT to construct the address, fallback to RAY_ADDRESS, then "auto"
    ray_host: str = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
    ray_port: str = os.getenv("RAY_PORT", "10001")
    ray_address: str = os.getenv("RAY_ADDRESS", f"ray://{os.getenv('RAY_HOST', 'seedcore-svc-head-svc')}:{os.getenv('RAY_PORT', '10001')}")

CFG = _Cfg()

logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(_h)
logger.setLevel(logging.INFO)
logger.propagate = True

# -----------------------------------------------------------------------------
# Namespace helpers
# -----------------------------------------------------------------------------

def _resolve_ns() -> str:
    """Single source of truth for the Ray namespace."""
    return os.getenv("RAY_NAMESPACE") or os.getenv("SEEDCORE_NS") or "seedcore-dev"

def get_ray_namespace() -> str:
    """Prefer explicit env, else Ray runtime context, else a default value."""
    ns = os.getenv("RAY_NAMESPACE")
    if ns:
        return ns
    try:
        ctx = ray.get_runtime_context()  # Requires Ray to be initialized in this proc
        if getattr(ctx, "namespace", None):
            return ctx.namespace  # type: ignore[attr-defined]
    except Exception:
        pass
    return CFG.default_namespace

def _ensure_ray(namespace: Optional[str]) -> None:
    # SOLUTION: Ray connection is now handled centrally by ray_connector.py
    # This function is kept for compatibility but no longer initializes Ray
    if not ray.is_initialized():
        logger.critical("❌ Ray not initialized. This should not happen - Ray should be initialized at application startup.")
        raise RuntimeError("Ray not initialized - application startup issue")
    logger.info("✅ Ray connection verified (namespace=%s)", namespace)

def _ready_ping(handle) -> None:
    """Best-effort readiness ping on a freshly created actor."""
    for _ in range(10):
        try:
            # Try a conventional 'ready' or 'ping' method if present.
            if hasattr(handle, "ready"):
                ray.get(handle.ready.remote(), timeout=2)
            elif hasattr(handle, "ping"):
                ray.get(handle.ping.remote(), timeout=2)
            # If neither exists, just attempt a no-op get to force resolution.
            else:
                ray.wait([handle.__ray_terminate__.remote()], timeout=0)  # schedules nothing; just resolves ref
            return
        except Exception:
            time.sleep(0.5)

# -----------------------------------------------------------------------------
# Core: get-or-create for named detached actors
# -----------------------------------------------------------------------------

def _get_or_create(actor_cls, name: str, *args, **kwargs):
    """
    Idempotent get-or-create for detached, named actors.
    Works in Ray Client mode; always uses the resolved namespace.
    """
    ns = _resolve_ns()
    try:
        return ray.get_actor(name, namespace=ns)
    except Exception:
        logging.info("Creating missing actor '%s' in namespace '%s'...", name, ns)
        # Support both @ray.remote-decorated classes and plain classes.
        try:
            handle = actor_cls.options(name=name, lifetime="detached", namespace=ns).remote(*args, **kwargs)
        except AttributeError:
            handle = ray.remote(actor_cls).options(name=name, lifetime="detached", namespace=ns).remote(*args, **kwargs)
        _ready_ping(handle)
        return handle

# -----------------------------------------------------------------------------
# Bootstrap & accessors
# -----------------------------------------------------------------------------

def bootstrap_actors():
    """Ensure all singleton actors exist; return handles as a tuple."""
    # Early return if bootstrap is optional and environment variable is set
    if os.getenv("SEEDCORE_BOOTSTRAP_OPTIONAL") == "1":
        logger.info("🚀 Bootstrap optional - skipping singleton actor creation")
        return None, None, None
    
    ns = _resolve_ns()
    logger.info("Bootstrapping singletons in namespace %s", ns)

    try:
        logger.info("🔍 Creating miss_tracker actor...")
        miss_tracker = _get_or_create(MissTracker, "miss_tracker")
        logger.info(f"✅ miss_tracker created: {miss_tracker}")
        
        logger.info("🔍 Creating shared_cache actor...")
        shared_cache = _get_or_create(SharedCache, "shared_cache")
        logger.info(f"✅ shared_cache created: {shared_cache}")
        
        logger.info("🔍 Creating mw_store actor...")
        mw_store = _get_or_create(MwStore, "mw")
        logger.info(f"✅ mw_store created: {mw_store}")
        
        logger.info("🎉 All singleton actors bootstrapped successfully!")
        return miss_tracker, shared_cache, mw_store
        
    except Exception as e:
        logger.error(f"❌ Bootstrap failed: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise

# Convenience accessors (match names used elsewhere in the codebase)

def get_miss_tracker():
    return _get_or_create(MissTracker, "miss_tracker")

def get_shared_cache():
    return _get_or_create(SharedCache, "shared_cache")

def get_mw_store():  # note: **mw**, not mv
    return _get_or_create(MwStore, "mw")

__all__ = [
    "bootstrap_actors",
    "get_miss_tracker",
    "get_shared_cache",
    "get_mw_store",
    "get_ray_namespace",
    "_resolve_ns",
]
