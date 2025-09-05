"""
MwManager: robust, namespaced access to a shared MwStore plus cluster-wide cache & miss tracking.

Features:
- Robust Ray bootstrap (address/namespace) with env + optional bootstrap helper
- Resilient actor lookup with retries & (optional) auto-create (AUTO_CREATE=1)
- Shared resources:
    * SharedCache: cluster-wide K/V cache
    * MwStore: frequency / miss tracking (no separate MissTracker needed)
- Async compat helpers that avoid blocking event loop
- Structured logging (hits, misses, errors with organ & namespace)
- Config via env: actor names, namespace, retry counts, backoff, auto-create

Environment (defaults shown):
    RAY_ADDRESS=auto
    RAY_NAMESPACE=<bootstrap helper or env>
    MW_ACTOR_NAME=mw
    SHARED_CACHE_NAME=shared_cache
    AUTO_CREATE=0
    LOOKUP_RETRIES=12
    LOOKUP_BACKOFF_S=0.5
    LOOKUP_BACKOFF_MULT=1.5
    LOG_LEVEL=INFO
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

# -------------------------
# Optional bootstrap helper
# -------------------------
def _bootstrap_namespace() -> Optional[str]:
    """Try to import a project helper (optional). Falls back to env."""
    try:
        # If your project exposes a bootstrap namespace helper, use it
        from src.seedcore.bootstrap import get_ray_namespace  # type: ignore
        return get_ray_namespace()
    except Exception:
        return os.getenv("RAY_NAMESPACE")

try:
    # If MwStore class is available, we can optionally auto-create it
    from src.seedcore.memory.mw_store import MwStore  # type: ignore
except Exception:  # pragma: no cover - MwStore may not be importable in some contexts
    MwStore = None  # type: ignore


# -------------------------
# Configuration
# -------------------------
@dataclass(frozen=True)
class MwConfig:
    # Ray
    ray_address: str = os.getenv("RAY_ADDRESS", "auto")
    namespace: Optional[str] = _bootstrap_namespace()

    # Actor names
    mw_actor_name: str = os.getenv("MW_ACTOR_NAME", "mw")
    shared_cache_name: str = os.getenv("SHARED_CACHE_NAME", "shared_cache")

    # Behavior flags
    auto_create: bool = os.getenv("AUTO_CREATE", "0") in {"1", "true", "True"}

    # Lookup behavior
    lookup_retries: int = int(os.getenv("LOOKUP_RETRIES", "12"))
    lookup_backoff_s: float = float(os.getenv("LOOKUP_BACKOFF_S", "0.5"))
    lookup_backoff_mult: float = float(os.getenv("LOOKUP_BACKOFF_MULT", "1.5"))

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

CONFIG = MwConfig()


# -------------------------
# Logging
# -------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(_h)
logger.setLevel(CONFIG.log_level)
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


class SharedCache:
    """Cluster-wide simple key/value cache (no TTL; best-effort)."""
    def __init__(self) -> None:
        self._cache: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._cache.get(key)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value

    def delete(self, key: str) -> None:
        self._cache.pop(key, None)

    def get_all(self) -> Dict[str, Any]:
        return dict(self._cache)


class MwStore:
    """
    Tracks item frequencies/misses; returns hot items.
    You can repurpose this to also record hits, etc., if needed.
    """
    def __init__(self) -> None:
        self._counts: Dict[str, int] = {}

    def incr(self, item_id: str, by: int = 1) -> int:
        cur = self._counts.get(item_id, 0) + by
        self._counts[item_id] = cur
        return cur

    def get(self, item_id: str) -> int:
        return self._counts.get(item_id, 0)

    def total(self) -> int:
        return sum(self._counts.values())

    def topn(self, n: int = 5) -> List[Tuple[str, int]]:
        return sorted(self._counts.items(), key=lambda kv: kv[1], reverse=True)[: max(0, n)]

    def snapshot(self) -> Dict[str, int]:
        return dict(self._counts)

# -------------------------
# Ray bootstrap
# -------------------------
def ensure_ray_initialized(ray_address: str, ray_namespace: Optional[str]) -> bool:
    """
    Ensure Ray is initialized to the specified address/namespace.
    Returns True if Ray is initialized (newly or already), False otherwise.
    """
    try:
        import ray  # lazy import
        if ray.is_initialized():
            return True
        # In Ray 2.x, namespace can be passed to ray.init
        ray.init(address=ray_address, namespace=ray_namespace)  # type: ignore
        logger.info(
            "Ray initialized: address=%s namespace=%s",
            ray_address,
            ray_namespace,
        )
        return True
    except Exception as e:
        logger.error("Failed to initialize Ray: %s", e)
        return False

def _ensure_ray(namespace: Optional[str]) -> None:
    import ray  # lazy import
    if ray.is_initialized():
        return
    if not ensure_ray_initialized(CONFIG.ray_address, namespace):
        raise RuntimeError(
            f"Failed to initialize Ray (address={CONFIG.ray_address}, namespace={namespace})"
        )

# -------------------------
# Async compat: non-blocking ray.get
# -------------------------
async def _await_ref(ref: Any) -> Any:
    """Await a Ray ObjectRef without blocking the event loop (runs ray.get in a thread pool)."""
    import ray
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, ray.get, ref)

def _lookup_actor(name: str, namespace: Optional[str]):
    try:
        import ray
        return ray.get_actor(name, namespace=namespace)
    except Exception:
        return None

def _remoteify(cls):
    """Attach @ray.remote to a class dynamically if not already remote."""
    import ray
    return cls if hasattr(cls, "remote") else ray.remote(cls)

def _create_actor_if_needed(name: str, namespace: Optional[str], cls: Optional[Any]):
    if not CONFIG.auto_create:
        return None
    if cls is None:
        logger.warning(
            "AUTO_CREATE requested but class is None for actor '%s' — skipping.", name
        )
        return None
    logger.info("Creating missing actor '%s' in namespace '%s'...", name, namespace)
    import ray
    rcls = _remoteify(cls)
    handle = (
        rcls.options(name=name, lifetime="detached", namespace=namespace, get_if_exists=True)
        .remote()
    )
    return handle

def _get_or_create(name: str, namespace: Optional[str], cls: Optional[Any]):
    _ensure_ray(namespace)

    backoff = CONFIG.lookup_backoff_s
    last_err: Optional[Exception] = None

    for attempt in range(1, CONFIG.lookup_retries + 1):
        h = _lookup_actor(name, namespace)
        if h is not None:
            if attempt > 1:
                logger.info("Actor '%s' found after %d attempts.", name, attempt)
            return h

        if attempt == 1 and CONFIG.auto_create:
            try:
                h = _create_actor_if_needed(name, namespace, cls)
                if h is not None:
                    return h
            except Exception as e:
                last_err = e  # races are normal; continue retry

        time.sleep(backoff)
        backoff *= max(1.0, CONFIG.lookup_backoff_mult)

    # One final check before raising
    h = _lookup_actor(name, namespace)
    if h is not None:
        return h

    ns = f"'{namespace}'" if namespace else "<default>"
    msg = (
        f"Failed to acquire actor '{name}' in namespace {ns}. "
        f"(retries={CONFIG.lookup_retries}, backoff~{CONFIG.lookup_backoff_s}s*, auto_create={CONFIG.auto_create}). "
        f"Likely causes: (1) bootstrap never created it; (2) it died; (3) namespace mismatch."
    )
    if last_err:
        msg += f" Last create error: {last_err}"
    raise RuntimeError(msg)


# -------------------------
# Public actor getters
# -------------------------
def get_shared_cache():
    return _get_or_create(CONFIG.shared_cache_name, CONFIG.namespace, SharedCache)

def get_mw_store():
    return _get_or_create(CONFIG.mw_actor_name, CONFIG.namespace, MwStore)


# -------------------------
# MwManager (per-organ facade)
# -------------------------
class MwManager:
    """
    Per-organ manager that consults a global cache (SharedCache), organ-local cache,
    and records misses into MwStore.

    organ_id: stable identifier for the owning organ/agent (used in keys/logs).
    """
    def __init__(self, organ_id: str) -> None:
        self.organ_id = organ_id
        self.namespace = CONFIG.namespace
        self.mw_store = get_mw_store()
        self._cache: Dict[str, Any] = {}

        logger.info(
            "✅ MwManager ready: %s",
            {"organ": self.organ_id, "namespace": self.namespace, "mw_actor": CONFIG.mw_actor_name},
        )

    # -------------------- key builders --------------------
    def _organ_key(self, item_id: str) -> str:
        return f"organ:{self.organ_id}:item:{item_id}"

    def _global_key(self, item_id: str) -> str:
        return f"global:item:{item_id}"

    # ---- async APIs ----
    async def get_item_async(self, item_id: str) -> Optional[Any]:
        """Check global cache, then organ-local cache; record a miss in MwStore if not found."""
        shared_cache = get_shared_cache()
        gkey = self._global_key(item_id)

        try:
            global_val = await _await_ref(shared_cache.get.remote(gkey))
        except Exception as e:
            logger.error(
                "SharedCache.get failed",
                extra={"organ": self.organ_id, "namespace": self.namespace, "key": gkey, "error": str(e)},
            )
            global_val = None

        if global_val is not None:
            logger.info(
                "HIT(GLOBAL)",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
            )
            return global_val

        okey = self._organ_key(item_id)
        if okey in self._cache:
            logger.info(
                "HIT(ORGAN)",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
            )
            return self._cache[okey]

        logger.warning(
            "MISS",
            extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
        )
        try:
            # record miss
            self.mw_store.incr.remote(item_id)
        except Exception as e:
            logger.error(
                "MwStore.incr failed",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id, "error": str(e)},
            )
        return None

    async def get_hot_items_async(self, top_n: int = 5) -> List[Tuple[str, int]]:
        try:
            return await _await_ref(self.mw_store.topn.remote(top_n))
        except Exception as e:
            logger.error(
                "get_hot_items_async error",
                extra={"organ": self.organ_id, "namespace": self.namespace, "error": str(e)},
            )
            return []

    # ---- sync APIs ----
    def get_hot_items(self, top_n: int = 5) -> List[Tuple[str, int]]:
        try:
            import ray
            return ray.get(self.mw_store.topn.remote(top_n))
        except Exception as e:
            logger.error(
                "get_hot_items error",
                extra={"organ": self.organ_id, "namespace": self.namespace, "error": str(e)},
            )
            return []

    def set_item(self, item_id: str, value: Any) -> None:
        """Set an organ-local cached value (not visible to other organs)."""
        self._cache[self._organ_key(item_id)] = value

    def set_global_item(self, item_id: str, value: Any) -> None:
        """Write-through to SharedCache (cluster-wide)."""
        shared_cache = get_shared_cache()
        try:
            shared_cache.set.remote(self._global_key(item_id), value)
        except Exception as e:
            logger.error(
                "set_global_item error",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id, "error": str(e)},
            )


# -------------------------
# Optional smoke test
# -------------------------
if __name__ == "__main__":
    mgr = MwManager("utility_organ_1")

    async def _demo() -> None:
        v1 = await mgr.get_item_async("foo")
        assert v1 is None
        mgr.set_global_item("foo", {"x": 1})
        v2 = await mgr.get_item_async("foo")
        print("foo ->", v2)
        print("hot:", await mgr.get_hot_items_async(5))

    asyncio.run(_demo()) 