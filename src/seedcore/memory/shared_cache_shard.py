"""
SharedCacheShard: L2 sharded global cache with LRU eviction and TTL.

This module contains the SharedCacheShard actor class, which implements the
L2 (cluster-wide) cache tier. It provides:
- Sharded storage for scalability
- LRU eviction for memory management
- TTL-based expiration
- Atomic CAS operations (setnx)
"""

from __future__ import annotations

import heapq
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple


class SharedCacheShard:
    """
    L2 cache: sharded global cache with LRU eviction and TTL.
    
    This actor stores actual cache values (or ObjectRefs to the data) and
    manages memory through LRU eviction and TTL-based expiration.
    """
    def __init__(self, max_items: int = 100000, default_ttl_s: int = 3600) -> None:
        self._map: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expire_ts)
        self._lru: OrderedDict[str, bool] = OrderedDict()
        self._heap: List[Tuple[float, str]] = []  # (expire_ts, key)
        self._max_items = max_items
        self._ttl = default_ttl_s

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache, checking expiration and updating LRU."""
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
        """Set a value in the cache with optional TTL."""
        ttl = ttl_s or self._ttl
        exp = time.time() + ttl
        self._map[key] = (val, exp)
        self._lru[key] = True
        heapq.heappush(self._heap, (exp, key))
        await self._evict_if_needed()

    async def delete(self, key: str) -> None:
        """Delete a key from the cache."""
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
        """Evict expired items and LRU items if cache is too large."""
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

