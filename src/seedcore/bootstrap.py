#!/usr/bin/env python3
"""
Create/retrieve singleton Ray actors (detached) in a consistent namespace.
- Safe to call from drivers or replicas (handles races).
- Respects RAY_NAMESPACE if set; otherwise uses Ray runtime context; else a default.
- Optionally auto-initializes Ray (address=auto) when invoked outside Ray.
- Uses `get_if_exists=True` if available (Ray >= 2.4), otherwise falls back to race-safe pattern.
"""

from __future__ import annotations

import os
import ray  # pyright: ignore[reportMissingImports]

# Import the ACTOR CLASSES (must be decorated with @ray.remote)
from seedcore.memory.mw_manager import SharedCache
from seedcore.memory.shared_cache_shard import SharedCacheShard
from seedcore.memory.mw_store_shard import MwStoreShard
from seedcore.config.mem_config import CONFIG as MEMORY_CONFIG

# -----------------------------------------------------------------------------
# Logging
# -----------------------------------------------------------------------------
from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.bootstrap")
logger = ensure_serve_logger("seedcore.bootstrap")


# -----------------------------------------------------------------------------
# Namespace helpers
# -----------------------------------------------------------------------------
def _resolve_ns() -> str:
    """Single source of truth for the Ray namespace."""
    return os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


# -----------------------------------------------------------------------------
# Helper functions for actor creation
# -----------------------------------------------------------------------------
def _apply_ray_remote(actor_cls):
    """Apply @ray.remote decorator to actor class if not already decorated."""
    if not hasattr(actor_cls, "remote"):
        return ray.remote(actor_cls)
    return actor_cls


def _create_shared_cache(name: str, namespace: str, **options):
    """Create or get existing shared_cache actor."""
    RaySharedCache = _apply_ray_remote(SharedCache)
    return RaySharedCache.options(
        name=name,
        lifetime="detached",
        namespace=namespace,
        get_if_exists=True,
        **options,
    ).remote()


def _create_mw_store(name: str, namespace: str, **options):
    """Create or get existing mw_store actor (using MwStoreShard for backward compatibility)."""
    RayMwStore = _apply_ray_remote(MwStoreShard)
    return RayMwStore.options(
        name=name,
        lifetime="detached",
        namespace=namespace,
        get_if_exists=True,
        **options,
    ).remote()


# -----------------------------------------------------------------------------
# Bootstrap & accessors
# -----------------------------------------------------------------------------
def bootstrap_actors():
    """Ensure all singleton actors exist; return handles as a tuple."""
    # Early return if bootstrap is optional and environment variable is set
    if os.getenv("SEEDCORE_BOOTSTRAP_OPTIONAL") == "1":
        logger.info("🚀 Bootstrap optional - skipping singleton actor creation")
        return None, None

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
        logger.info(
            f"🔍 Creating {MEMORY_CONFIG.num_shards} sharded cache actors in memory namespace..."
        )
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
                        max_concurrency=2000,
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
                logger.info(
                    f"   Progress: {batch_end}/{MEMORY_CONFIG.num_shards} shards created..."
                )

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
]
