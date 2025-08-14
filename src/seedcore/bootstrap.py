# src/seedcore/bootstrap.py
#!/usr/bin/env python3
"""
Create/retrieve singleton Ray actors (detached) in the current Ray namespace.
Safe to call from driver or replicas; handles races.
"""
import os
import ray
from .memory.working_memory import MissTracker, SharedCache, MwStore  # these should be @ray.remote classes

def _namespace() -> str:
    # Prefer explicit env (set by K8s), else runtime context, else a default.
    ns = os.getenv("RAY_NAMESPACE")
    if ns:
        return ns
    try:
        ctx = ray.get_runtime_context()
        # Ray 2.33.0 exposes 'namespace' on the context
        if getattr(ctx, "namespace", None):
            return ctx.namespace
    except Exception:
        pass
    return "seedcore-dev"

def _get_or_create(actor_cls, name: str, **options):
    ns = _namespace()
    try:
        return ray.get_actor(name, namespace=ns)
    except Exception:
        # Not found; try to create
        try:
            return actor_cls.options(
                name=name, namespace=ns, lifetime="detached", **options
            ).remote()
        except Exception:
            # Race: someone else created it
            return ray.get_actor(name, namespace=ns)

def bootstrap_actors():
    """Ensure all singleton actors exist; return handles."""
    miss_tracker  = _get_or_create(MissTracker, "miss_tracker")
    shared_cache  = _get_or_create(SharedCache, "shared_cache")
    mw_store      = _get_or_create(MwStore,     "mw")
    return miss_tracker, shared_cache, mw_store

# Optional convenience accessors
def get_miss_tracker(): return _get_or_create(MissTracker, "miss_tracker")
def get_shared_cache(): return _get_or_create(SharedCache, "shared_cache")
def get_mv_store():    return _get_or_create(MwStore,      "mw")
