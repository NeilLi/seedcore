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
from typing import Any, Optional, TYPE_CHECKING

# Lazy import for Ray - only imported when functions are called
# This prevents Ray initialization when the module is imported

# Import the ACTOR CLASSES (must be decorated with @ray.remote)
from .memory.mw_manager import SharedCache, NodeCache  # type: ignore
from .memory.shared_cache_shard import SharedCacheShard  # type: ignore
from .memory.mw_store_shard import MwStoreShard  # type: ignore
from .config.mem_config import CONFIG as MEMORY_CONFIG  # type: ignore

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
    
    # Cache configuration
    num_shards: int = int(os.getenv("CACHE_NUM_SHARDS", "16"))
    shard_max_items: int = int(os.getenv("SHARD_MAX_ITEMS", "100000"))
    shard_cache_ttl: int = int(os.getenv("SHARD_CACHE_TTL", "3600"))
    node_cache_ttl: int = int(os.getenv("NODE_CACHE_TTL", "30"))

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
    return os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

def get_ray_namespace() -> str:
    """Prefer explicit env, else Ray runtime context, else a default value."""
    ns = os.getenv("RAY_NAMESPACE")
    if ns:
        return ns
    try:
        # Lazy import Ray only when needed
        import ray
        ctx = ray.get_runtime_context()  # Requires Ray to be initialized in this proc
        if getattr(ctx, "namespace", None):
            return ctx.namespace  # type: ignore[attr-defined]
    except Exception:
        pass
    return CFG.default_namespace

def _ensure_ray(namespace: Optional[str]) -> None:
    # SOLUTION: Ray connection is now handled centrally by ray_connector.py
    # This function is kept for compatibility but no longer initializes Ray
    # Lazy import Ray only when needed
    import ray
    if not ray.is_initialized():
        logger.critical("❌ Ray not initialized. This should not happen - Ray should be initialized at application startup.")
        raise RuntimeError("Ray not initialized - application startup issue")
    logger.info("✅ Ray connection verified (namespace=%s)", namespace)

def _ready_ping(handle) -> None:
    """Best-effort readiness ping on a freshly created actor."""
    # Lazy import Ray only when needed
    import ray
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
# Helper functions for actor creation
# -----------------------------------------------------------------------------

def _apply_ray_remote(actor_cls):
    """Apply @ray.remote decorator to actor class if not already decorated."""
    if not hasattr(actor_cls, 'remote'):
        import ray
        return ray.remote(actor_cls)
    return actor_cls

def _create_shared_cache(name: str, namespace: str, **options):
    """Create or get existing shared_cache actor."""
    import ray
    RaySharedCache = _apply_ray_remote(SharedCache)
    return RaySharedCache.options(
        name=name, lifetime="detached", namespace=namespace, get_if_exists=True, **options
    ).remote()

def _create_mw_store(name: str, namespace: str, **options):
    """Create or get existing mw_store actor (using MwStoreShard for backward compatibility)."""
    import ray
    RayMwStore = _apply_ray_remote(MwStoreShard)
    return RayMwStore.options(
        name=name, lifetime="detached", namespace=namespace, get_if_exists=True, **options
    ).remote()

# -----------------------------------------------------------------------------
# Core: get-or-create for named detached actors
# -----------------------------------------------------------------------------

def _get_or_create(actor_cls, name: str, *args, **kwargs):
    """
    Idempotent get-or-create for detached, named actors.
    Works in Ray Client mode; always uses the resolved namespace.
    """
    # Lazy import Ray only when needed
    import ray
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
        logger.info("🔍 Creating shared_cache actor...")
        shared_cache = _create_shared_cache("shared_cache", ns)
        logger.info(f"✅ shared_cache created: {shared_cache}")
        
        logger.info("🔍 Creating mw_store actor...")
        mw_store = _create_mw_store("mw", ns)
        logger.info(f"✅ mw_store created: {mw_store}")
        
        logger.info("🎉 All singleton actors bootstrapped successfully!")
        return shared_cache, mw_store
        
    except Exception as e:
        logger.error(f"❌ Bootstrap failed: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise


def bootstrap_memory_actors():
    """Bootstrap memory subsystem actors in dedicated mem-dev namespace."""
    # Early return if bootstrap is optional and environment variable is set
    if os.getenv("SEEDCORE_BOOTSTRAP_OPTIONAL") == "1":
        logger.info("🚀 Bootstrap optional - skipping memory actor creation")
        return None, None, []
    
    # Use dedicated memory namespace
    memory_ns = MEMORY_CONFIG.namespace
    logger.info("Bootstrapping memory actors in namespace %s", memory_ns)

    try:
        logger.info("🔍 Creating shared_cache actor in memory namespace...")
        shared_cache = _create_shared_cache(MEMORY_CONFIG.shared_cache_name, memory_ns)
        logger.info(f"✅ shared_cache created: {shared_cache}")
        
        logger.info("🔍 Creating mw_store actor in memory namespace...")
        mw_store = _create_mw_store(MEMORY_CONFIG.mw_actor_name, memory_ns)
        logger.info(f"✅ mw_store created: {mw_store}")
        
        # Create sharded cache actors in parallel batches
        logger.info(f"🔍 Creating {MEMORY_CONFIG.num_shards} sharded cache actors in memory namespace...")
        shard_handles = []
        
        RaySharedCacheShard = _apply_ray_remote(SharedCacheShard)
        
        # Create shards in parallel batches to avoid sequential bottleneck
        batch_size = min(MEMORY_CONFIG.bootstrap_batch_size, MEMORY_CONFIG.num_shards)
        for batch_start in range(0, MEMORY_CONFIG.num_shards, batch_size):
            batch_end = min(batch_start + batch_size, MEMORY_CONFIG.num_shards)
            batch_shards = []
            
            # Create batch of shard actors
            for i in range(batch_start, batch_end):
                shard_name = MEMORY_CONFIG.get_shard_name(i)
                try:
                    shard = RaySharedCacheShard.options(
                        name=shard_name, 
                        lifetime="detached", 
                        namespace=memory_ns, 
                        get_if_exists=True,
                        num_cpus=0,
                        max_concurrency=2000
                    ).remote(MEMORY_CONFIG.max_items_per_shard, MEMORY_CONFIG.l2_ttl_s)
                    batch_shards.append((i, shard_name, shard))
                except Exception as e:
                    logger.error(f"❌ Failed to create {shard_name}: {e}")
                    raise
            
            # Wait for batch to be ready and log results
            for i, shard_name, shard in batch_shards:
                shard_handles.append(shard)
                logger.info(f"✅ {shard_name} created: {shard}")
            
            # Log progress
            if batch_end < MEMORY_CONFIG.num_shards:
                logger.info(f"   Progress: {batch_end}/{MEMORY_CONFIG.num_shards} shards created...")
        
        logger.info("🎉 All memory actors bootstrapped successfully!")
        return shared_cache, mw_store, shard_handles
        
    except Exception as e:
        logger.error(f"❌ Memory bootstrap failed: {e}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise

# Convenience accessors (match names used elsewhere in the codebase)


def get_shared_cache():
    ns = _resolve_ns()
    return _create_shared_cache("shared_cache", ns)

def get_mw_store():  # note: **mw**, not mv
    ns = _resolve_ns()
    return _create_mw_store("mw", ns)

__all__ = [
    "bootstrap_actors",
    "bootstrap_memory_actors",
    "get_shared_cache",
    "get_mw_store",
    "get_ray_namespace",
    "_resolve_ns",
    "SharedCacheShard",
    "NodeCache",
]
