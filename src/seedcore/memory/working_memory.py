import os
import logging
from typing import List, Tuple
import ray
from src.seedcore.memory.mw_store import MwStore

logger = logging.getLogger(__name__)

class MwManager:
    def __init__(self, organ_id: str):
        self.organ_id = organ_id
        # Connect to Ray and get or create the MwStore actor
        ray.init(address="auto", ignore_reinit_error=True)
        try:
            self.mw_store = ray.get_actor("mw")
        except ValueError:
            self.mw_store = MwStore.options(name="mw").remote()
        self._cache = {}  # Simple in-memory cache for this organ
        self.miss_log_key = "mw:miss_counts"  # For compatibility, not used
        logger.info(f"✅ MwManager for Organ '{self.organ_id}' initialized.")

    def _get_organ_key(self, item_id: str) -> str:
        return f"organ:{self.organ_id}:item:{item_id}"

    def _get_global_key(self, item_id: str) -> str:
        return f"global:item:{item_id}"

    def get_item(self, item_id: str) -> str | None:
        # Check in-memory organ-local cache first
        key = self._get_organ_key(item_id)
        value = self._cache.get(key)
        if value is not None:
            logger.info(f"[{self.organ_id}] Mw HIT for '{item_id}' in ORGAN cache.")
            return value
        # On a miss, log the event in Ray actor
        logger.warning(f"[{self.organ_id}] Mw MISS for '{item_id}'. Logging miss.")
        ray.get(self.mw_store.incr.remote(item_id))
        return None

    def set_item(self, item_id: str, value: str):
        key = self._get_organ_key(item_id)
        self._cache[key] = value
        # Optionally, implement TTL logic if needed

    def set_global_item(self, item_id: str, value: str):
        key = self._get_global_key(item_id)
        self._cache[key] = value
        # Optionally, implement TTL logic if needed

    def get_hot_items(self, top_n: int = 3):
        return ray.get(self.mw_store.topn.remote(top_n)) 