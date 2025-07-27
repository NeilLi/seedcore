import os
import logging
from typing import List, Tuple
import ray
from src.seedcore.memory.mw_store import MwStore
from collections import defaultdict

logger = logging.getLogger(__name__)

@ray.remote
class MissTracker:
    """Ray actor to track miss counts across all agents."""
    def __init__(self):
        self.miss_counts = defaultdict(int)
    
    def incr(self, item_id: str):
        self.miss_counts[item_id] += 1
    
    def get_top_n(self, n: int):
        sorted_items = sorted(self.miss_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:n]

@ray.remote
class SharedCache:
    """Ray actor to share cache across all MwManager instances."""
    def __init__(self):
        self.cache = {}
    
    def get(self, key: str):
        return self.cache.get(key)
    
    def set(self, key: str, value: str):
        self.cache[key] = value
    
    def get_all(self):
        return self.cache

# Global miss tracker actor
_miss_tracker = None
_shared_cache = None
_mw_store = None

def get_miss_tracker():
    """
    Get the singleton MissTracker actor that was created at cluster bootstrap.
    """
    global _miss_tracker
    if _miss_tracker is None:
        _miss_tracker = ray.get_actor("miss_tracker", namespace="seedcore")
    return _miss_tracker

def get_shared_cache():
    """
    Get the singleton SharedCache actor that was created at cluster bootstrap.
    """
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = ray.get_actor("shared_cache", namespace="seedcore")
    return _shared_cache

def get_mw_store():
    """
    Get the singleton MwStore actor that was created at cluster bootstrap.
    """
    global _mw_store
    if _mw_store is None:
        _mw_store = ray.get_actor("mw", namespace="seedcore")
    return _mw_store

class MwManager:
    def __init__(self, organ_id: str):
        self.organ_id = organ_id
        # Connect to Ray and get or create the MwStore actor using helper function
        self.mw_store = get_mw_store()
        self._cache = {}  # Simple in-memory cache for this organ
        self.miss_log_key = "mw:miss_counts"  # For compatibility, not used
        logger.info(f"✅ MwManager for Organ '{self.organ_id}' initialized.")

    def _get_organ_key(self, item_id: str) -> str:
        return f"organ:{self.organ_id}:item:{item_id}"

    def _get_global_key(self, item_id: str) -> str:
        return f"global:item:{item_id}"

    async def get_item_async(self, item_id: str) -> str | None:
        shared_cache = get_shared_cache()
        global_key = self._get_global_key(item_id)
        global_value = await shared_cache.get.remote(global_key)
        if global_value:
            logger.info(f"[{self.organ_id}] Mw HIT for '{item_id}' in GLOBAL cache.")
            return global_value
        key = self._get_organ_key(item_id)
        value = self._cache.get(key)
        if value is not None:
            logger.info(f"[{self.organ_id}] Mw HIT for '{item_id}' in ORGAN cache.")
            return value
        logger.warning(f"[{self.organ_id}] Mw MISS for '{item_id}'. Logging miss.")
        self.mw_store.incr.remote(item_id)
        miss_tracker = get_miss_tracker()
        miss_tracker.incr.remote(item_id)
        return None

    def set_item(self, item_id: str, value: str):
        key = self._get_organ_key(item_id)
        self._cache[key] = value
        # Optionally, implement TTL logic if needed

    def set_global_item(self, item_id: str, value: str):
        """NEW: Writes to the global cache for all agents to see."""
        shared_cache = get_shared_cache()
        key = self._get_global_key(item_id)
        shared_cache.set.remote(key, value)
        # Optionally, implement TTL logic if needed

    async def get_hot_items_async(self, top_n: int = 3):
        """Async version of get_hot_items to avoid blocking ray.get()."""
        # Return the top N items with the most misses from the Ray actor
        miss_tracker = get_miss_tracker()
        try:
            # Use await directly on the remote call
            return await miss_tracker.get_top_n.remote(top_n)
        except Exception as e:
            logger.error(f"Error getting hot items: {e}")
            return []

    def get_hot_items(self, top_n: int = 3):
        # Return the top N items with the most misses from the Ray actor
        miss_tracker = get_miss_tracker()
        try:
            # Use ray.get to get the actual value, not an ObjectRef
            return ray.get(miss_tracker.get_top_n.remote(top_n))
        except Exception as e:
            logger.error(f"Error getting hot items: {e}")
            return [] 