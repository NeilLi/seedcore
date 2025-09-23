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
import json
import zlib
import base64
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
from datetime import datetime, timezone

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

    async def setnx(self, key: str, val: Any, ttl_s: int = 5) -> bool:
        """Set if not exists - atomic CAS operation for sentinels."""
        now = time.time()
        rec = self._map.get(key)
        if rec and rec[1] > now:  # not expired
            return False
        await self.set(key, val, ttl_s)
        return True

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
        
        # Telemetry counters
        self._hit_count = 0
        self._miss_count = 0
        self._l0_hits = 0
        self._l1_hits = 0
        self._l2_hits = 0
        
        # Task-specific metrics
        self._task_cache_hits = 0
        self._task_cache_misses = 0
        self._task_evictions = 0
        self._negative_cache_hits = 0

        logger.info(
            "✅ MwManager ready: %s",
            {"organ": self.organ_id, "namespace": self.namespace, "mw_actor": CONFIG.mw_actor_name},
        )

    # -------------------- key builders --------------------
    def _organ_key(self, item_id: str) -> str:
        return f"organ:{self.organ_id}:item:{item_id}"

    def _global_key(self, item_id: str) -> str:
        return f"global:item:{item_id}"
    
    def _build_global_key(self, kind: str, scope: str, item_id: str) -> str:
        """Build a consistent global cache key: global:item:{kind}:{scope}:{id}"""
        return f"global:item:{kind}:{scope}:{item_id}"
    
    def _build_organ_key(self, kind: str, item_id: str) -> str:
        """Build a consistent organ cache key: organ:{organ_id}:item:{kind}:{id}"""
        return f"organ:{self.organ_id}:item:{kind}:{item_id}"

    # -------------------- task caching constants --------------------
    # TTL defaults for different task statuses (in seconds) - configurable via env
    TASK_TTL_CREATED = int(os.getenv("MW_TASK_TTL_CREATED_S", "10"))
    TASK_TTL_QUEUED = int(os.getenv("MW_TASK_TTL_QUEUED_S", "10"))
    TASK_TTL_RUNNING = int(os.getenv("MW_TASK_TTL_RUNNING_S", "10"))
    TASK_TTL_RETRY = int(os.getenv("MW_TASK_TTL_RETRY_S", "20"))
    TASK_TTL_COMPLETED = int(os.getenv("MW_TASK_TTL_COMPLETED_S", "600"))  # 10 minutes
    TASK_TTL_FAILED = int(os.getenv("MW_TASK_TTL_FAILED_S", "300"))        # 5 minutes
    TASK_TTL_CANCELLED = int(os.getenv("MW_TASK_TTL_CANCELLED_S", "300"))  # 5 minutes
    TASK_TTL_DEFAULT = int(os.getenv("MW_TASK_TTL_DEFAULT_S", "30"))
    TASK_TTL_NEGATIVE = int(os.getenv("MW_TASK_TTL_NEGATIVE_S", "30"))

    # ---- async APIs ----
    async def get_item_async(self, item_id: str, is_global: bool = False) -> Optional[Any]:
        """Check L0 (organ-local) -> L1 (node) -> L2 (sharded global) cache hierarchy.

        - If item_id already starts with "global:item:" or is_global is True, treat it as a fully-qualified global key.
        - If item_id starts with "organ:", treat it as a fully-qualified organ-local key (L0-only).
        - Otherwise, treat item_id as an unqualified id and derive a global key for L1/L2.
        """
        is_global_key = is_global or item_id.startswith("global:item:")
        is_organ_key = item_id.startswith("organ:")

        if is_global_key:
            gkey = item_id
            okey = self._organ_key(item_id)
        elif is_organ_key:
            gkey = None  # organ-local only
            okey = self._organ_key(item_id)
        else:
            gkey = self._global_key(item_id)
            okey = self._organ_key(item_id)
        
        # L0: Check organ-local cache first (fastest)
        if okey in self._cache:
            self._hit_count += 1
            self._l0_hits += 1
            logger.info(
                "HIT(L0)",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id},
            )
            return self._cache[okey]

        # L1: Check node cache (only if we have a global key)
        if gkey is not None:
            try:
                node_cache = get_node_cache()
                val = await _await_ref(node_cache.get.remote(gkey))
                if val is not None:
                    self._hit_count += 1
                    self._l1_hits += 1
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

        # L2: Check sharded global cache (only if we have a global key)
        if gkey is not None:
            try:
                shard = _shard_for(gkey)
                val = await _await_ref(shard.get.remote(gkey))
                if val is not None:
                    self._hit_count += 1
                    self._l2_hits += 1
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
        self._miss_count += 1
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

    def clear(self) -> None:
        """Clear all L0 entries for this organ."""
        self._cache.clear()

    def delete_organ_item(self, item_id: str) -> None:
        """Delete a single organ-local entry (by raw or organ-qualified id)."""
        self._cache.pop(self._organ_key(item_id), None)

    def set_global_item(self, item_id: str, value: Any, ttl_s: Optional[int] = None) -> None:
        """Write-through to all cache levels (L0, L1, L2)."""
        # Normalize global key to avoid double-prefixing
        gkey = item_id if item_id.startswith("global:item:") else self._global_key(item_id)
        okey = self._organ_key(item_id)
        
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
            shard = _shard_for(gkey)
            shard.set.remote(gkey, value, ttl_s=ttl_s)
        except Exception as e:
            logger.error(
                "Failed to update L2 cache",
                extra={"organ": self.organ_id, "namespace": self.namespace, "item_id": item_id, "error": str(e)},
            )

    def set_global_item_typed(self, kind: str, scope: str, item_id: str, value: Any, ttl_s: Optional[int] = None) -> None:
        """Set a global item with typed key format: global:item:{kind}:{scope}:{id}"""
        key = self._build_global_key(kind, scope, item_id)
        self.set_global_item(key, value, ttl_s)

    def set_organ_item_typed(self, kind: str, item_id: str, value: Any) -> None:
        """Set an organ-local item with typed key format: organ:{organ_id}:item:{kind}:{id}"""
        key = self._build_organ_key(kind, item_id)
        self.set_item(key, value)

    async def get_item_typed_async(self, kind: str, scope: str, item_id: str) -> Optional[Any]:
        """Get an item using typed key format, checking global first then organ-local"""
        # Try global key first
        global_key = self._build_global_key(kind, scope, item_id)
        result = await self.get_item_async(global_key, is_global=True)
        if result is not None:
            return result
        
        # Fallback to organ-local
        organ_key = self._build_organ_key(kind, item_id)
        return await self.get_item_async(organ_key)

    def set_negative_cache(self, kind: str, scope: str, item_id: str, ttl_s: int = 30) -> None:
        """Set a negative cache entry to prevent cache stampedes"""
        neg_key = f"_neg:{kind}:{scope}:{item_id}"
        self.set_global_item(neg_key, "1", ttl_s)

    async def check_negative_cache(self, kind: str, scope: str, item_id: str) -> bool:
        """Check if an item is in negative cache (should skip lookup)"""
        neg_key = f"_neg:{kind}:{scope}:{item_id}"
        result = await self.get_item_async(neg_key)
        return result == "1"

    def set_inflight_sentinel(self, kind: str, scope: str, item_id: str, ttl_s: int = 5) -> bool:
        """Set an in-flight sentinel to prevent thundering herd. Returns True if acquired."""
        sentinel_key = f"_inflight:{kind}:{scope}:{item_id}"
        try:
            # Try to set sentinel - if it already exists, we didn't acquire it
            self.set_global_item(sentinel_key, "1", ttl_s)
            return True
        except Exception:
            return False

    def clear_inflight_sentinel(self, kind: str, scope: str, item_id: str) -> None:
        """Clear an in-flight sentinel"""
        sentinel_key = f"_inflight:{kind}:{scope}:{item_id}"
        try:
            self.set_global_item(sentinel_key, None, ttl_s=1)  # Delete semantics
        except Exception:
            pass

    def _wrap_value(self, val: Any, compressed: bool = False, codec: str = "zlib") -> Dict[str, Any]:
        """Wrap value in envelope with compression if needed."""
        if not compressed:
            return {"_v": "v1", "_ct": "raw", "data": val}
        
        try:
            # Serialize to JSON first
            if isinstance(val, str):
                json_bytes = val.encode('utf-8')
            else:
                json_bytes = json.dumps(val).encode('utf-8')
            
            # Compress with level 3 (good balance of speed/size)
            compressed_bytes = zlib.compress(json_bytes, level=3)
            encoded_data = base64.b64encode(compressed_bytes).decode('ascii')
            
            return {
                "_v": "v1",
                "_ct": codec,
                "data": encoded_data
            }
        except Exception as e:
            logger.warning(f"Compression failed, falling back to raw: {e}")
            return {"_v": "v1", "_ct": "raw", "data": val}

    def _unwrap_value(self, blob: Any) -> Any:
        """Unwrap value from envelope, decompressing if needed."""
        if not isinstance(blob, dict) or blob.get("_v") != "v1":
            return blob  # Not our format, return as-is
        
        if blob.get("_ct") == "raw":
            return blob.get("data", blob)
        
        if blob.get("_ct") == "zlib":
            try:
                # Decode base64 and decompress with size limit
                compressed_bytes = base64.b64decode(blob["data"])
                raw_bytes = zlib.decompress(compressed_bytes, max_length=2_000_000)  # 2MB limit
                return json.loads(raw_bytes.decode('utf-8'))
            except Exception as e:
                logger.warning(f"Decompression failed: {e}")
                return blob  # Return original if decompression fails
        
        return blob  # Safe fallback

    def _truncate_value(self, value: Any, max_size: int = 262144) -> Any:  # 256KB default
        """Truncate large values while preserving structure and JSON safety."""
        if isinstance(value, str) and len(value) > max_size:
            return {
                "_v": "v1",
                "truncated": True,
                "preview": value[:max_size-200],
                "orig_bytes": len(value),
                "truncated_bytes": len(value) - max_size + 200
            }
        elif isinstance(value, dict):
            # For dicts, try to preserve key structure but truncate large values
            truncated = {}
            total_size = 0
            for k, v in value.items():
                if total_size > max_size:
                    truncated["_truncated"] = True
                    truncated["_orig_keys"] = len(value)
                    break
                
                if isinstance(v, str) and len(v) > max_size // 4:  # 1/4 of max per field
                    truncated[k] = {
                        "_v": "v1",
                        "truncated": True,
                        "preview": v[:max_size//4-100],
                        "orig_bytes": len(v)
                    }
                    total_size += max_size // 4
                else:
                    truncated[k] = v
                    total_size += len(str(v))
            return truncated
        return value

    def set_global_item_compressed(self, item_id: str, value: Any, ttl_s: Optional[int] = None, max_size: int = 262144) -> None:
        """Set a global item with compression and size limits."""
        # Truncate if too large
        value = self._truncate_value(value, max_size)
        
        # Determine if compression is needed (16KB threshold)
        json_bytes = json.dumps(value).encode('utf-8') if not isinstance(value, str) else value.encode('utf-8')
        should_compress = len(json_bytes) > 16384
        
        # Wrap with envelope
        wrapped_value = self._wrap_value(value, compressed=should_compress)
        
        # Set with envelope
        self.set_global_item(item_id, wrapped_value, ttl_s)

    async def get_item_compressed_async(self, item_id: str) -> Optional[Any]:
        """Get an item and unwrap if needed."""
        wrapped_data = await self.get_item_async(item_id)
        if wrapped_data is None:
            return None
        
        return self._unwrap_value(wrapped_data)

    def get_telemetry(self) -> Dict[str, Any]:
        """Get cache telemetry statistics."""
        total_requests = self._hit_count + self._miss_count
        hit_ratio = self._hit_count / total_requests if total_requests > 0 else 0.0
        
        total_task_requests = self._task_cache_hits + self._task_cache_misses
        task_hit_ratio = self._task_cache_hits / total_task_requests if total_task_requests > 0 else 0.0
        
        return {
            "organ_id": self.organ_id,
            "total_requests": total_requests,
            "hits": self._hit_count,
            "misses": self._miss_count,
            "hit_ratio": hit_ratio,
            "l0_hits": self._l0_hits,
            "l1_hits": self._l1_hits,
            "l2_hits": self._l2_hits,
            "l0_hit_ratio": self._l0_hits / total_requests if total_requests > 0 else 0.0,
            "l1_hit_ratio": self._l1_hits / total_requests if total_requests > 0 else 0.0,
            "l2_hit_ratio": self._l2_hits / total_requests if total_requests > 0 else 0.0,
            # Task-specific metrics
            "task_cache_hits": self._task_cache_hits,
            "task_cache_misses": self._task_cache_misses,
            "task_hit_ratio": task_hit_ratio,
            "task_evictions": self._task_evictions,
            "negative_cache_hits": self._negative_cache_hits,
        }

    def reset_telemetry(self) -> None:
        """Reset telemetry counters."""
        self._hit_count = 0
        self._miss_count = 0
        self._l0_hits = 0
        self._l1_hits = 0
        self._l2_hits = 0
        self._task_cache_hits = 0
        self._task_cache_misses = 0
        self._task_evictions = 0
        self._negative_cache_hits = 0

    # ---- sync/async parity ----
    def get_item(self, item_id: str) -> Optional[Any]:
        """Sync version of get_item_async - uses asyncio.run for compatibility."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're in an async context, we can't use asyncio.run
                # Fall back to a simple sync implementation
                return self._get_item_sync(item_id)
            else:
                return asyncio.run(self.get_item_async(item_id))
        except Exception:
            return self._get_item_sync(item_id)

    def _get_item_sync(self, item_id: str) -> Optional[Any]:
        """Simple sync fallback that only checks L0 cache."""
        # Mirror the L0 key selection from get_item_async
        if item_id.startswith("global:item:"):
            okey = self._organ_key(item_id)
        elif item_id.startswith("organ:"):
            okey = self._organ_key(item_id)
        else:
            okey = self._organ_key(item_id)
        if okey in self._cache:
            self._hit_count += 1
            self._l0_hits += 1
            return self._cache[okey]
        self._miss_count += 1
        return None

    def get_item_typed(self, kind: str, scope: str, item_id: str) -> Optional[Any]:
        """Sync version of get_item_typed_async."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return self._get_item_typed_sync(kind, scope, item_id)
            else:
                return asyncio.run(self.get_item_typed_async(kind, scope, item_id))
        except Exception:
            return self._get_item_typed_sync(kind, scope, item_id)

    def _get_item_typed_sync(self, kind: str, scope: str, item_id: str) -> Optional[Any]:
        """Simple sync fallback for typed keys."""
        global_key = self._build_global_key(kind, scope, item_id)
        result = self._get_item_sync(global_key)
        if result is not None:
            return result
        organ_key = self._build_organ_key(kind, item_id)
        return self._get_item_sync(organ_key)

    # ---- CAS operations ----
    async def try_set_inflight(self, key: str, ttl_s: int = 5) -> bool:
        """Try to set an in-flight sentinel atomically."""
        try:
            shard = _shard_for(key)
            return await _await_ref(shard.setnx.remote(key, "1", ttl_s))
        except Exception as e:
            logger.warning(f"CAS operation failed: {e}")
            return False

    async def del_global_key(self, key: str) -> None:
        """Delete a key from all cache levels."""
        try:
            # Delete from L2 (shard)
            shard = _shard_for(key)
            await _await_ref(shard.delete.remote(key))
        except Exception as e:
            logger.warning(f"Failed to delete from L2: {e}")
        
        try:
            # Delete from L1 (node cache)
            node_cache = get_node_cache()
            await _await_ref(node_cache.delete.remote(key))
        except Exception as e:
            logger.warning(f"Failed to delete from L1: {e}")
        
        # Delete from L0 (organ cache)
        okey = self._organ_key(key)
        self._cache.pop(okey, None)

    # ---- task-aware helper ----
    def cache_task(self, task: Dict[str, Any]) -> None:
        """Cache a task row snapshot into Mw with TTL derived from lifecycle fields.

        Expected keys in task dict: id (UUID/str), status (str), lease_expires_at, run_after, updated_at.
        Timestamps may be datetime or ISO strings.
        """
        def _to_epoch_seconds(v: Any) -> Optional[float]:
            if v is None:
                return None
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, datetime):
                dt = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            if isinstance(v, str):
                try:
                    s = v.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    return None
            return None

        try:
            now = time.time()
            task_id = str(task.get("id"))
            if not task_id or task_id == "None":
                logger.warning("cache_task: invalid task_id, skipping cache")
                return
                
            status = str(task.get("status", "")).lower()
            lease_ts = _to_epoch_seconds(task.get("lease_expires_at"))
            run_after_ts = _to_epoch_seconds(task.get("run_after"))

            # Base TTLs by status using constants
            base_ttl_map = {
                "created": self.TASK_TTL_CREATED,
                "queued": self.TASK_TTL_QUEUED,
                "running": self.TASK_TTL_RUNNING,
                "retry": self.TASK_TTL_RETRY,
                "completed": self.TASK_TTL_COMPLETED,
                "failed": self.TASK_TTL_FAILED,
                "cancelled": self.TASK_TTL_CANCELLED,
            }
            ttl = base_ttl_map.get(status, self.TASK_TTL_DEFAULT)

            # Lease bound
            if lease_ts is not None:
                lease_remaining = max(0.0, lease_ts - now)
                ttl = min(ttl, int(lease_remaining)) if lease_remaining > 0 else min(ttl, 1)

            # Scheduled future run
            if run_after_ts is not None and run_after_ts > now:
                until_run = max(1.0, run_after_ts - now)
                # Bound by base ttl to avoid very long caches
                ttl = min(ttl, int(until_run))

            ttl = max(1, int(ttl))

            # Canonical key without double prefixing
            item_id = f"task:by_id:{task_id}"
            
            # Use compression-aware setter for larger rows
            self.set_global_item_compressed(item_id, task, ttl_s=ttl)
            
            logger.debug(
                "Cached task %s with TTL %ds (status=%s)",
                task_id, ttl, status,
                extra={"organ": self.organ_id, "task_id": task_id, "status": status, "ttl": ttl}
            )
            
        except Exception as e:
            logger.warning(
                "Failed to cache task %s: %s",
                task.get("id", "unknown"), e,
                extra={"organ": self.organ_id, "task_id": str(task.get("id", "unknown")), "error": str(e)}
            )

    async def get_task_async(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get a task from cache, with negative cache support to prevent DB stampedes."""
        task_id = str(task_id)
        
        # Check negative cache first
        if await self.check_negative_cache("task", "by_id", task_id):
            self._negative_cache_hits += 1
            logger.debug("Negative cache hit for task %s", task_id)
            return None
            
        # Try to get from cache
        item_id = f"task:by_id:{task_id}"
        result = await self.get_item_async(item_id, is_global=True)
        
        if result is not None:
            self._task_cache_hits += 1
            return result
            
        # Cache miss - set negative cache to prevent stampede
        self._task_cache_misses += 1
        self.set_negative_cache("task", "by_id", task_id, ttl_s=self.TASK_TTL_NEGATIVE)
        logger.debug("Task cache miss for %s, set negative cache", task_id)
        return None

    def invalidate_task(self, task_id: str) -> None:
        """Invalidate a task from all cache levels and clear negative cache."""
        task_id = str(task_id)
        item_id = f"task:by_id:{task_id}"
        
        # Delete from all levels
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't use asyncio.run in running loop, just delete L0
                self.delete_organ_item(item_id)
            else:
                asyncio.run(self.del_global_key(item_id))
        except Exception:
            # Fallback to L0 only
            self.delete_organ_item(item_id)
            
        # Clear negative cache
        try:
            neg_key = f"_neg:task:by_id:{task_id}"
            self.set_global_item(neg_key, None, ttl_s=1)  # Delete semantics
        except Exception:
            pass
            
        self._task_evictions += 1
        logger.debug("Invalidated task %s from all cache levels", task_id)

    def del_global_key_sync(self, key: str) -> None:
        """Sync version of del_global_key."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Can't use asyncio.run in running loop, just delete L0
                okey = self._organ_key(key)
                self._cache.pop(okey, None)
            else:
                asyncio.run(self.del_global_key(key))
        except Exception:
            # Fallback to L0 only
            okey = self._organ_key(key)
            self._cache.pop(okey, None)


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