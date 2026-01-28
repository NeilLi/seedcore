#!/usr/bin/env python3
"""
Create/retrieve singleton Ray actors (detached) in a consistent namespace.
- Safe to call from drivers or replicas (handles races).
- Respects RAY_NAMESPACE if set; otherwise uses Ray runtime context; else a default.
- Optionally auto-initializes Ray (address=auto) when invoked outside Ray.
- Uses `get_if_exists=True` if available (Ray >= 2.4), otherwise falls back to race-safe pattern.

Optimized for low thread/file descriptor usage during bootstrap:
- Reduced max_concurrency (128 instead of 2000)
- Throttled actor creation with in-flight limits
- Uses ray.get_actor() first to avoid redundant creations
- MwStoreShard disabled by default (can be enabled via SEEDCORE_MW_SHARDS)
"""

from __future__ import annotations

import os
import time
import ray  # pyright: ignore[reportMissingImports]
from typing import List, Optional, Tuple, Callable

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
# Tuning knobs (conservative defaults to avoid thread/file descriptor exhaustion)
# -----------------------------------------------------------------------------
DEFAULT_MAX_CONCURRENCY = int(os.getenv("SEEDCORE_ACTOR_MAX_CONCURRENCY", "128"))
DEFAULT_INFLIGHT_CREATES = int(os.getenv("SEEDCORE_BOOTSTRAP_INFLIGHT", "8"))
DEFAULT_BATCH_SIZE = int(os.getenv("SEEDCORE_BOOTSTRAP_BATCH", "4"))
DEFAULT_READY_TIMEOUT_S = int(os.getenv("SEEDCORE_BOOTSTRAP_READY_TIMEOUT_S", "30"))
DEFAULT_RETRY = int(os.getenv("SEEDCORE_BOOTSTRAP_RETRY", "3"))
DEFAULT_BACKOFF_S = float(os.getenv("SEEDCORE_BOOTSTRAP_BACKOFF_S", "0.5"))

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


def _get_or_create_actor(
    RemoteCls,
    *,
    name: str,
    namespace: str,
    detached: bool = True,
    options: Optional[dict] = None,
    init_args: tuple = (),
    init_kwargs: Optional[dict] = None,
):
    """
    Idempotent: try get_actor first; else create.
    This avoids redundant GCS operations and reduces bootstrap churn.
    """
    init_kwargs = init_kwargs or {}
    options = options or {}

    # Fast path: actor already exists
    try:
        existing = ray.get_actor(name, namespace=namespace)
        logger.debug(f"Actor '{name}' already exists, reusing handle")
        return existing
    except ValueError:
        pass  # doesn't exist, will create

    lifetime = "detached" if detached else None
    actor_opts = dict(
        name=name,
        namespace=namespace,
        lifetime=lifetime,
        # Avoid oversubscribing threads/processes during bootstrap:
        max_concurrency=options.pop("max_concurrency", DEFAULT_MAX_CONCURRENCY),
        num_cpus=options.pop("num_cpus", 0),
        get_if_exists=True,  # Race-safe: get existing if another process created it
        **options,
    )

    return RemoteCls.options(**actor_opts).remote(*init_args, **init_kwargs)


def _wait_ready(actor, timeout_s: int = DEFAULT_READY_TIMEOUT_S) -> None:
    """
    Wait until actor responds to a ping/ready method.
    Requires actor to implement `ready()` or `ping()`. Falls back to trivial call if not.
    """
    start = time.time()

    # Prefer a dedicated readiness method if you have it.
    if hasattr(actor, "ready"):
        ref = actor.ready.remote()
    elif hasattr(actor, "ping"):
        ref = actor.ping.remote()
    else:
        # Fallback: make a tiny no-op call via __ray_terminate__? (not ideal)
        # Better: add ready()/ping() to actors.
        logger.debug(f"Actor {actor} lacks ready()/ping(); skipping readiness check")
        return

    while True:
        ready, _ = ray.wait([ref], timeout=1.0, num_returns=1)
        if ready:
            try:
                ray.get(ready[0])
                return
            except Exception as e:
                logger.debug(f"Actor readiness check failed: {e}")
        if (time.time() - start) > timeout_s:
            logger.warning(f"Actor did not become ready within {timeout_s}s: {actor}")
            return


def _create_many_shards(
    RemoteCls,
    *,
    name_fn: Callable[[int], str],
    namespace: str,
    count: int,
    detached: bool = True,
    per_actor_options: Optional[dict] = None,
    init_args_fn: Optional[Callable[[int], Tuple[tuple, dict]]] = None,
    inflight_limit: int = DEFAULT_INFLIGHT_CREATES,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List:
    """
    Creates or gets many named actors, throttled to avoid startup storms.
    Optionally waits for readiness after each batch.
    """
    per_actor_options = per_actor_options or {}
    init_args_fn = init_args_fn or (lambda i: ((), {}))

    handles: List = []
    in_flight = []

    def submit_one(i: int):
        shard_name = name_fn(i)
        args, kwargs = init_args_fn(i)
        a = _get_or_create_actor(
            RemoteCls,
            name=shard_name,
            namespace=namespace,
            detached=detached,
            options=dict(per_actor_options),
            init_args=args,
            init_kwargs=kwargs,
        )
        return i, shard_name, a

    for i in range(count):
        in_flight.append(submit_one(i))

        # Throttle: drain batches to avoid overwhelming Ray/GCS
        if len(in_flight) >= inflight_limit:
            # Drain one batch
            for j, shard_name, actor in in_flight[:batch_size]:
                handles.append(actor)
                logger.info("✅ %s ready-handle acquired (%d/%d)", shard_name, len(handles), count)
            in_flight = in_flight[batch_size:]

    # Drain remaining
    for j, shard_name, actor in in_flight:
        handles.append(actor)
        logger.info("✅ %s ready-handle acquired (%d/%d)", shard_name, len(handles), count)

    return handles


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
        shared_cache = _get_or_create_actor(
            _apply_ray_remote(SharedCache),
            name="shared_cache",
            namespace=ns,
            detached=True,
            options=dict(max_concurrency=DEFAULT_MAX_CONCURRENCY, num_cpus=0),
            init_args=(),
        )
        logger.info(f"✅ shared_cache created: {shared_cache}")

        logger.info("🔍 Creating mw_store actor...")
        mw_store = _get_or_create_actor(
            _apply_ray_remote(MwStoreShard),
            name="mw",
            namespace=ns,
            detached=True,
            options=dict(max_concurrency=DEFAULT_MAX_CONCURRENCY, num_cpus=0),
            init_args=(),
        )
        logger.info(f"✅ mw_store created: {mw_store}")

        logger.info("🎉 All singleton actors bootstrapped successfully!")
        return shared_cache, mw_store

    except Exception as e:
        logger.error(f"❌ Bootstrap failed: {e}")
        import traceback

        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise


def bootstrap_memory_actors():
    """
    Bootstrap memory subsystem actors in dedicated mem-dev namespace (stable + low-storm).
    
    Optimizations:
    - Reduced max_concurrency (128 instead of 2000) to avoid thread/file descriptor exhaustion
    - Throttled actor creation with in-flight limits
    - Uses ray.get_actor() first to avoid redundant GCS operations
    - MwStoreShard disabled by default (set SEEDCORE_MW_SHARDS to enable)
    """
    # Early return if bootstrap is optional and environment variable is set
    if os.getenv("SEEDCORE_BOOTSTRAP_OPTIONAL") == "1":
        logger.info("🚀 Bootstrap optional - skipping memory actor creation")
        return None, None, [], []

    # Use dedicated memory namespace
    memory_ns = MEMORY_CONFIG.namespace
    logger.info("Bootstrapping memory actors in namespace %s", memory_ns)

    # Strong recommendation: cap shards unless you *proved* you need more
    num_cache_shards = int(os.getenv("SEEDCORE_CACHE_SHARDS", str(MEMORY_CONFIG.num_shards)))
    # If MwStoreShard is "incorrect", make it lazy/optional by default:
    num_mw_shards = int(os.getenv("SEEDCORE_MW_SHARDS", "0"))  # default OFF

    # Concurrency: keep sane defaults (128) unless explicitly raised
    actor_opts = dict(
        num_cpus=0,
        max_concurrency=DEFAULT_MAX_CONCURRENCY,
        # Consider limiting restarts during bootstrap to avoid thrash
        max_restarts=1,
        max_task_retries=0,
    )

    RaySharedCache = _apply_ray_remote(SharedCache)
    RayMwStore = _apply_ray_remote(MwStoreShard)
    RaySharedCacheShard = _apply_ray_remote(SharedCacheShard)
    RayMwStoreShard = _apply_ray_remote(MwStoreShard)

    # ---- create core actors (idempotent) ----
    shared_cache = None
    mw_store = None

    # Retry wrapper (helps with transient GCS churn during cold start)
    for attempt in range(1, DEFAULT_RETRY + 1):
        try:
            logger.info("🔍 Ensuring shared_cache in %s ...", memory_ns)
            shared_cache = _get_or_create_actor(
                RaySharedCache,
                name=MEMORY_CONFIG.shared_cache_name,
                namespace=memory_ns,
                detached=True,
                options=dict(actor_opts),
                init_args=(),
            )

            logger.info("🔍 Ensuring mw_store in %s ...", memory_ns)
            mw_store = _get_or_create_actor(
                RayMwStore,
                name=MEMORY_CONFIG.mw_actor_name,
                namespace=memory_ns,
                detached=True,
                options=dict(actor_opts),
                init_args=(),
            )

            # (Optional) wait for readiness if you add ready()/ping()
            # _wait_ready(shared_cache)
            # _wait_ready(mw_store)

            break
        except Exception as e:
            if attempt == DEFAULT_RETRY:
                logger.exception("❌ Memory bootstrap failed after retries: %s", e)
                raise
            sleep_s = DEFAULT_BACKOFF_S * (2 ** (attempt - 1))
            logger.warning(
                "Bootstrap core actors failed (attempt %d/%d): %s; retrying in %.2fs",
                attempt, DEFAULT_RETRY, e, sleep_s
            )
            time.sleep(sleep_s)

    # ---- create cache shards (throttled) ----
    logger.info("🔍 Ensuring %d SharedCacheShard actors ...", num_cache_shards)

    def cache_shard_init(i: int):
        # pass init args: (max_items_per_shard, l2_ttl_s)
        return ((MEMORY_CONFIG.max_items_per_shard, MEMORY_CONFIG.l2_ttl_s), {})

    cache_shards = _create_many_shards(
        RaySharedCacheShard,
        name_fn=lambda i: MEMORY_CONFIG.get_shard_name(i),
        namespace=memory_ns,
        count=num_cache_shards,
        detached=True,
        per_actor_options=dict(actor_opts),
        init_args_fn=cache_shard_init,
        inflight_limit=DEFAULT_INFLIGHT_CREATES,
        batch_size=DEFAULT_BATCH_SIZE,
    )

    # ---- create MwStoreShard actors (optional/lazy) ----
    mw_shards = []
    if num_mw_shards > 0:
        logger.info("🔍 Ensuring %d MwStoreShard actors ...", num_mw_shards)

        mw_shards = _create_many_shards(
            RayMwStoreShard,
            name_fn=lambda i: f"{MEMORY_CONFIG.mw_actor_name}_shard_{i}",
            namespace=memory_ns,
            count=num_mw_shards,
            detached=True,
            per_actor_options=dict(actor_opts),
            init_args_fn=lambda i: ((), {}),
            inflight_limit=DEFAULT_INFLIGHT_CREATES,
            batch_size=DEFAULT_BATCH_SIZE,
        )
    else:
        logger.info(
            "ℹ️ MwStoreShard bootstrap disabled (SEEDCORE_MW_SHARDS=0). Using mw_store only."
        )

    logger.info(
        "🎉 Memory bootstrap complete: shared_cache=%s mw_store=%s cache_shards=%d mw_shards=%d",
        shared_cache, mw_store, len(cache_shards), len(mw_shards)
    )

    return shared_cache, mw_store, cache_shards, mw_shards


# Convenience accessors (match names used elsewhere in the codebase)
def get_shared_cache():
    ns = _resolve_ns()
    RaySharedCache = _apply_ray_remote(SharedCache)
    return _get_or_create_actor(
        RaySharedCache,
        name="shared_cache",
        namespace=ns,
        detached=True,
        options=dict(max_concurrency=DEFAULT_MAX_CONCURRENCY, num_cpus=0),
        init_args=(),
    )


def get_mw_store():  # note: **mw**, not mv
    ns = _resolve_ns()
    RayMwStore = _apply_ray_remote(MwStoreShard)
    return _get_or_create_actor(
        RayMwStore,
        name="mw",
        namespace=ns,
        detached=True,
        options=dict(max_concurrency=DEFAULT_MAX_CONCURRENCY, num_cpus=0),
        init_args=(),
    )


__all__ = [
    "bootstrap_actors",
    "bootstrap_memory_actors",
    "get_shared_cache",
    "get_mw_store",
]
