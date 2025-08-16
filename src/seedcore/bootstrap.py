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
    ray_address: str = os.getenv("RAY_ADDRESS", "auto")

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
    if ray.is_initialized():
        return
    # Initialize Ray if we are in a fresh driver process.
    ray.init(address=CFG.ray_address, namespace=namespace)
    logger.info("Ray initialized (address=%s, namespace=%s)", CFG.ray_address, namespace)


# -----------------------------------------------------------------------------
# Core: get-or-create for named detached actors
# -----------------------------------------------------------------------------

def _get_or_create(actor_cls: Any, name: str, **options: Any):
    """Return a handle to a named, detached actor in our namespace. Create if absent.

    Race-safe across many concurrent callers. If Ray supports `get_if_exists`,
    use it for idempotent creation; otherwise fall back to create+lookup.
    """
    ns = get_ray_namespace()
    _ensure_ray(ns)

    # Fast path: already exists
    try:
        return ray.get_actor(name, namespace=ns)
    except Exception:
        pass

    # Try to create (idempotent if get_if_exists is available)
    try:
        return (
            actor_cls.options(
                name=name, namespace=ns, lifetime="detached", get_if_exists=True, **options
            ).remote()
        )
    except TypeError:
        # Older Ray without get_if_exists
        try:
            handle = actor_cls.options(name=name, namespace=ns, lifetime="detached", **options).remote()
            return handle
        except Exception:
            # Lost the race: someone else created it
            return ray.get_actor(name, namespace=ns)
    except Exception:
        # Lost the race or transient error
        return ray.get_actor(name, namespace=ns)


# -----------------------------------------------------------------------------
# Bootstrap & accessors
# -----------------------------------------------------------------------------

def bootstrap_actors():
    """Ensure all singleton actors exist; return handles as a tuple."""
    miss_tracker = _get_or_create(MissTracker, "miss_tracker")
    shared_cache = _get_or_create(SharedCache, "shared_cache")
    mw_store = _get_or_create(MwStore, "mw")
    return miss_tracker, shared_cache, mw_store


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
]
