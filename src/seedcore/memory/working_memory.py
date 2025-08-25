"""
MwManager: robust, namespaced access to a shared MwStore plus cluster‑wide cache & miss tracking.

Key improvements vs. your draft:
- Safer Ray bootstrap (auto-init with the right namespace).
- Resilient actor lookup with retry/backoff and optional auto-create.
- Clear env/config knobs (actor names, namespace, auto-create flag, address).
- Async compatibility helpers (no blocking the event loop on ray.get()).
- Defensive logging and structured error messages.
- Fix: do NOT call `incr` on MwStore (leave miss counting to MissTracker).
- Optional creation for SharedCache & MissTracker if missing.

Expected cluster bootstrap (if you do not enable AUTO_CREATE):
    MwStore.options(name="mw", lifetime="detached", namespace=<ns>).remote(...)
    MissTracker.options(name="miss_tracker", lifetime="detached", namespace=<ns>).remote()
    SharedCache.options(name="shared_cache", lifetime="detached", namespace=<ns>).remote()

You may also set AUTO_CREATE=1 to let this module create any missing actors.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# Lazy import for Ray - only imported when functions are called
# This prevents Ray initialization when the module is imported

from ..utils.ray_utils import ensure_ray_initialized

try:
    # Prefer the project-provided namespace helper if available
    from ..bootstrap import get_ray_namespace as _bootstrap_ns  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    _bootstrap_ns = None  # fallback to env/None

try:
    # If MwStore class is available, we can optionally auto-create it
    from src.seedcore.memory.mw_store import MwStore  # type: ignore
except Exception:  # pragma: no cover - MwStore may not be importable in some contexts
    MwStore = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class MwConfig:
    # Ray
    ray_address: str = os.getenv("RAY_ADDRESS", "auto")
    namespace: Optional[str] = os.getenv("RAY_NAMESPACE")

    # Actor names
    mw_actor_name: str = os.getenv("MW_ACTOR_NAME", "mw")
    miss_tracker_name: str = os.getenv("MISS_TRACKER_NAME", "miss_tracker")
    shared_cache_name: str = os.getenv("SHARED_CACHE_NAME", "shared_cache")

    # Behavior flags
    auto_create: bool = os.getenv("AUTO_CREATE", "0") in {"1", "true", "True"}

    # Lookup behavior
    lookup_retries: int = int(os.getenv("LOOKUP_RETRIES", "12"))  # ~6s by default
    lookup_backoff_s: float = float(os.getenv("LOOKUP_BACKOFF_S", "0.5"))


CONFIG = MwConfig(
    namespace=_bootstrap_ns() if _bootstrap_ns else os.getenv("RAY_NAMESPACE")
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = True


# ---------------------------------------------------------------------------
# Cluster-safe async helpers
# ---------------------------------------------------------------------------
async def _await_ref(ref: Any) -> Any:
    """Await a Ray ObjectRef without blocking the event loop.

    This uses a threadpool to call ray.get(). Works across Ray/Python versions,
    including environments where `await ref` is not supported.
    """
    # Lazy import Ray only when needed
    import ray
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ray.get, ref)


# ---------------------------------------------------------------------------
# Shared actors (definitions) — created only if AUTO_CREATE=1
# ---------------------------------------------------------------------------
# These classes will be decorated with @ray.remote when Ray is imported
class MissTracker:
    """Tracks miss counts for item IDs across the cluster."""

    def __init__(self) -> None:
        from collections import defaultdict

        self._miss_counts = defaultdict(int)

    def incr(self, item_id: str) -> None:
        self._miss_counts[item_id] += 1

    def get_top_n(self, n: int) -> List[Tuple[str, int]]:
        return sorted(self._miss_counts.items(), key=lambda kv: kv[1], reverse=True)[:n]


class SharedCache:
    """Cluster-wide simple key/value cache."""

    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def get_all(self) -> Dict[str, Any]:
        return dict(self._cache)


# ---------------------------------------------------------------------------
# Ray bootstrap & resilient actor acquisition
# ---------------------------------------------------------------------------

def _ensure_ray(namespace: Optional[str]) -> None:
    # Lazy import Ray only when needed
    import ray
    if ray.is_initialized():
        return
    if not ensure_ray_initialized(ray_address=CONFIG.ray_address, ray_namespace=namespace):
        raise RuntimeError(f"Failed to initialize Ray (address={CONFIG.ray_address}, namespace={namespace})")
    logger.info(
        "Ray initialized: address=%s namespace=%s",
        CONFIG.ray_address,
        namespace,
    )


def _lookup_actor(name: str, namespace: Optional[str]) -> Optional[Any]:
    try:
        # Lazy import Ray only when needed
        import ray
        return ray.get_actor(name, namespace=namespace)
    except Exception:
        return None


def _create_actor_if_needed(
    name: str,
    namespace: Optional[str],
    cls: Optional[Any],
) -> Optional[Any]:
    if not CONFIG.auto_create:
        return None
    if cls is None:
        logger.warning(
            "AUTO_CREATE requested but class is not importable for actor '%s' — skipping.",
            name,
        )
        return None
    logger.info("Creating missing actor '%s' in namespace '%s'...", name, namespace)
    # Lazy import Ray only when needed
    import ray
    # Apply @ray.remote decorator to the class if not already decorated
    if not hasattr(cls, 'remote'):
        cls = ray.remote(cls)
    handle = (
        cls.options(name=name, lifetime="detached", namespace=namespace, get_if_exists=True)
        .remote()
    )
    return handle


def _get_or_create(name: str, namespace: Optional[str], cls: Optional[Any]) -> Any:
    _ensure_ray(namespace)

    # Retry loop: actor may not be up yet due to race conditions at startup
    last_exc: Optional[Exception] = None
    for attempt in range(CONFIG.lookup_retries):
        handle = _lookup_actor(name, namespace)
        if handle is not None:
            return handle
        if attempt == 0 and CONFIG.auto_create:
            # best-effort single creation attempt (idempotent via get_if_exists)
            try:
                handle = _create_actor_if_needed(name, namespace, cls)
                if handle is not None:
                    return handle
            except Exception as e:  # creation can race; continue retry loop
                last_exc = e
        time.sleep(CONFIG.lookup_backoff_s)

    # Final check before raising
    handle = _lookup_actor(name, namespace)
    if handle is not None:
        return handle

    ns_msg = f"'{namespace}'" if namespace else "<default>"
    msg = (
        f"Failed to look up actor '{name}' in namespace {ns_msg}. "
        f"(retries={CONFIG.lookup_retries}, backoff={CONFIG.lookup_backoff_s}s, auto_create={CONFIG.auto_create})\n"
        f"Likely causes: (1) bootstrap never created it; (2) it died; (3) namespace mismatch."
    )
    if last_exc:
        msg += f" Last creation error: {last_exc}"
    raise RuntimeError(msg)


# ---------------------------------------------------------------------------
# Public accessors for shared actors
# ---------------------------------------------------------------------------

def get_miss_tracker() -> Any:
    return _get_or_create(CONFIG.miss_tracker_name, CONFIG.namespace, MissTracker)


def get_shared_cache() -> Any:
    return _get_or_create(CONFIG.shared_cache_name, CONFIG.namespace, SharedCache)


def get_mw_store() -> Any:
    # MwStore may be project-specific; we create it only if AUTO_CREATE=1 and import succeeded
    return _get_or_create(CONFIG.mw_actor_name, CONFIG.namespace, MwStore)


# ---------------------------------------------------------------------------
# MwManager
# ---------------------------------------------------------------------------
class MwManager:
    """Per-organ manager that consults a global cache, organ-local cache, and miss tracker.

    Parameters
    ----------
    organ_id : str
        Identifier for the owning organ/agent.
    """

    def __init__(self, organ_id: str) -> None:
        self.organ_id = organ_id
        self.mw_store = get_mw_store()
        self._cache: Dict[str, Any] = {}
        logger.info(
            "✅ MwManager for organ='%s' ready (namespace=%s, mw='%s').",
            self.organ_id,
            CONFIG.namespace,
            CONFIG.mw_actor_name,
        )

    # -------------------- key builders --------------------
    def _organ_key(self, item_id: str) -> str:
        return f"organ:{self.organ_id}:item:{item_id}"

    def _global_key(self, item_id: str) -> str:
        return f"global:item:{item_id}"

    # -------------------- async APIs --------------------
    async def get_item_async(self, item_id: str) -> Optional[Any]:
        """Fast path: check global then local cache; on miss, record miss.

        Returns the value or None.
        """
        shared_cache = get_shared_cache()

        # Global cache first (cluster-wide)
        gkey = self._global_key(item_id)
        try:
            global_val = await _await_ref(shared_cache.get.remote(gkey))
        except Exception as e:
            logger.error("[%s] SharedCache.get failed for %s: %s", self.organ_id, gkey, e)
            global_val = None
        if global_val is not None:
            logger.info("[%s] HIT (GLOBAL) for '%s'", self.organ_id, item_id)
            return global_val

        # Organ-local cache
        okey = self._organ_key(item_id)
        if okey in self._cache:
            logger.info("[%s] HIT (ORGAN) for '%s'", self.organ_id, item_id)
            return self._cache[okey]

        # Miss path
        logger.warning("[%s] MISS for '%s' — recording miss.", self.organ_id, item_id)
        try:
            miss_tracker = get_miss_tracker()
            miss_tracker.incr.remote(item_id)
        except Exception as e:
            logger.error("[%s] MissTracker.incr failed for '%s': %s", self.organ_id, item_id, e)
        return None

    async def get_hot_items_async(self, top_n: int = 3) -> List[Tuple[str, int]]:
        miss_tracker = get_miss_tracker()
        try:
            return await _await_ref(miss_tracker.get_top_n.remote(top_n))
        except Exception as e:
            logger.error("get_hot_items_async error: %s", e)
            return []

    # -------------------- sync APIs --------------------
    def get_hot_items(self, top_n: int = 3) -> List[Tuple[str, int]]:
        miss_tracker = get_miss_tracker()
        try:
            # Lazy import Ray only when needed
            import ray
            return ray.get(miss_tracker.get_top_n.remote(top_n))
        except Exception as e:
            logger.error("get_hot_items error: %s", e)
            return []

    def set_item(self, item_id: str, value: Any) -> None:
        self._cache[self._organ_key(item_id)] = value

    def set_global_item(self, item_id: str, value: Any) -> None:
        """Write-through to cluster-wide cache; visible to all organs."""
        shared_cache = get_shared_cache()
        try:
            shared_cache.set.remote(self._global_key(item_id), value)
        except Exception as e:
            logger.error("set_global_item error for '%s': %s", item_id, e)


# ---------------------------------------------------------------------------
# Quick manual check (optional)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example smoke test when running this module directly
    mgr = MwManager("utility_organ_1")

    async def _demo() -> None:
        v1 = await mgr.get_item_async("foo")
        assert v1 is None
        mgr.set_global_item("foo", {"x": 1})
        v2 = await mgr.get_item_async("foo")
        print("foo ->", v2)
        print("hot:", await mgr.get_hot_items_async(5))

    asyncio.run(_demo()) 