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
import heapq
import hashlib
import bisect
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# Lazy import for Ray - only imported when functions are called
# This prevents Ray initialization when the module is imported

from ..utils.ray_utils import ensure_ray_initialized

# -------------------------
# Memory configuration
# -------------------------
from ..config.mem_config import CONFIG, get_memory_config

try:
    # If MwStore class is available, we can optionally auto-create it
    from src.seedcore.memory.mw_store import MwStore  # type: ignore
except Exception:  # pragma: no cover - MwStore may not be importable in some contexts
    MwStore = None  # type: ignore


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


class NodeCache:
    """L1 cache: per-node cache with TTL support."""
    def __init__(self, default_ttl_s: int = 30) -> None:
        self._data: Dict[str, Tuple[Any, Optional[float]]] = {}  # key -> (val, expire_ts)
        self._ttl = default_ttl_s

    async def get(self, key: str) -> Optional[Any]:
        rec = self._data.get(key)
        if not rec:
            return None
        val, exp = rec
        if exp and exp < time.time():
            self._data.pop(key, None)
            return None
        return val

    async def set(self, key: str, val: Any, ttl_s: Optional[int] = None) -> None:
        ttl = ttl_s or self._ttl
        exp = time.time() + ttl
        self._data[key] = (val, exp)

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


class SharedCacheShard:
    """L2 cache: sharded global cache with LRU eviction and TTL."""
    def __init__(self, max_items: int = 100000, default_ttl_s: int = 3600) -> None:
        self._map: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expire_ts)
        self._lru: OrderedDict[str, bool] = OrderedDict()
        self._heap: List[Tuple[float, str]] = []  # (expire_ts, key)
        self._max_items = max_items
        self._ttl = default_ttl_s

    async def get(self, key: str) -> Optional[Any]:
        rec = self._map.get(key)
        if not rec:
            return None
        val, exp = rec
        if exp < time.time():
            await self.delete(key)
            return None
        self._lru.move_to_end(key, last=True)
        return val

    async def set(self, key: str, val: Any, ttl_s: Optional[int] = None) -> None:
        ttl = ttl_s or self._ttl
        exp = time.time() + ttl
        self._map[key] = (val, exp)
        self._lru[key] = True
        heapq.heappush(self._heap, (exp, key))
        await self._evict_if_needed()

    async def delete(self, key: str) -> None:
        self._map.pop(key, None)
        self._lru.pop(key, None)

    async def _evict_if_needed(self) -> None:
        now = time.time()
        # Evict expired items
        while self._heap and self._heap[0][0] <= now:
            _, k = heapq.heappop(self._heap)
            self._map.pop(k, None)
            self._lru.pop(k, None)
        # Evict LRU if too many items
        while len(self._map) > self._max_items and self._lru:
            k, _ = self._lru.popitem(last=False)
            self._map.pop(k, None)


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
# Consistent Hashing for Shards
# -------------------------
class _HashRing:
    """Consistent hashing ring for shard distribution."""
    def __init__(self, nodes: List[str], vnodes: int = 64) -> None:
        pairs = []
        for n in nodes:
            for v in range(vnodes):
                h = int(hashlib.md5(f"{n}#{v}".encode()).hexdigest(), 16)
                pairs.append((h, n))
        pairs.sort()
        self._hs = [h for h, _ in pairs]
        self._ns = [n for _, n in pairs]

    def node_for(self, key: str) -> str:
        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        i = bisect.bisect(self._hs, h) % len(self._ns)
        return self._ns[i]


# Global shard management
_RING: Optional[_HashRing] = None
_SHARDS: Dict[str, Any] = {}


def _get_shard_handles(num_shards: Optional[int] = None, namespace: Optional[str] = None) -> Tuple[_HashRing, Dict[str, Any]]:
    """Initialize shard handles and hash ring."""
    import ray
    num_shards = num_shards or CONFIG.num_shards
    namespace = namespace or CONFIG.namespace
    names = CONFIG.shard_names
    handles = {}
    for nm in names:
        try:
            h = ray.get_actor(nm, namespace=namespace)
        except Exception:
            if CONFIG.auto_create:
                h = _remoteify(SharedCacheShard).options(
                    name=nm, 
                    lifetime="detached", 
                    namespace=namespace,
                    num_cpus=0,
                    max_concurrency=2000
                ).remote(CONFIG.max_items_per_shard, CONFIG.l2_ttl_s)
            else:
                raise
        handles[nm] = h
    ring = _HashRing(names, vnodes=CONFIG.vnodes_per_shard)
    return ring, handles


def _shard_for(key: str) -> Any:
    """Get the appropriate shard for a key."""
    global _RING, _SHARDS
    if _RING is None or not _SHARDS:
        _RING, _SHARDS = _get_shard_handles()
    nm = _RING.node_for(key)
    return _SHARDS[nm]


def get_node_cache() -> Any:
    """Get or create the node cache for the current node."""
    import ray
    from ray.util.scheduling_strategies import NodeAffinitySchedulingStrategy
    
    ctx = ray.get_runtime_context()
    node_id = ctx.get_node_id()
    name = CONFIG.get_node_cache_name(node_id)
    
    try:
        return ray.get_actor(name, namespace=CONFIG.namespace)
    except Exception:
        if CONFIG.auto_create:
            return _remoteify(NodeCache).options(
                name=name,
                lifetime="detached",
                namespace=CONFIG.namespace,
                num_cpus=0,
                max_concurrency=1000,
                scheduling_strategy=NodeAffinitySchedulingStrategy(node_id=node_id, soft=False)
            ).remote(CONFIG.l1_ttl_s)
        else:
            raise


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
        """Check L0 (organ-local) -> L1 (node) -> L2 (sharded global) cache hierarchy."""
        okey = self._organ_key(item_id)
        gkey = self._global_key(item_id)
        
        # L0: Check organ-local cache first (fastest)
        if okey in self._cache:
            logger.info(
                "HIT(L0)",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
            )
            return self._cache[okey]

        # L1: Check node cache
        try:
            node_cache = get_node_cache()
            val = await _await_ref(node_cache.get.remote(gkey))
            if val is not None:
                logger.info(
                    "HIT(L1)",
                    extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
                )
                # Populate L0 cache
                self._cache[okey] = val
                return val
        except Exception as e:
            logger.error(
                "NodeCache.get failed",
                extra={"organ": self.organ_id, "namespace": self.namespace, "key": gkey, "error": str(e)},
            )

        # L2: Check sharded global cache
        try:
            shard = _shard_for(item_id)
            val = await _await_ref(shard.get.remote(gkey))
            if val is not None:
                logger.info(
                    "HIT(L2)",
                    extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
                )
                # Populate L1 and L0 caches
                try:
                    node_cache = get_node_cache()
                    node_cache.set.remote(gkey, val, ttl_s=CONFIG.l1_ttl_s)
                except Exception as e:
                    logger.warning(
                        "Failed to populate L1 cache",
                        extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id, "error": str(e)},
                    )
                self._cache[okey] = val
                return val
        except Exception as e:
            logger.error(
                "ShardCache.get failed",
                extra={"organ": self.organ_id, "namespace": self.namespace, "key": gkey, "error": str(e)},
            )

        # Miss: record in MwStore
        logger.warning(
            "MISS",
            extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
        )
        try:
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

    def set_global_item(self, item_id: str, value: Any, ttl_s: Optional[int] = None) -> None:
        """Write-through to all cache levels (L0, L1, L2)."""
        okey = self._organ_key(item_id)
        gkey = self._global_key(item_id)
        
        # L0: Update organ-local cache
        self._cache[okey] = value
        
        # L1: Update node cache
        try:
            node_cache = get_node_cache()
            node_cache.set.remote(gkey, value, ttl_s=CONFIG.l1_ttl_s)
        except Exception as e:
            logger.error(
                "Failed to update L1 cache",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id, "error": str(e)},
            )
        
        # L2: Update sharded global cache
        try:
            shard = _shard_for(item_id)
            shard.set.remote(gkey, value, ttl_s=ttl_s)
        except Exception as e:
            logger.error(
                "Failed to update L2 cache",
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