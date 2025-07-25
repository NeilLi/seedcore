import ray
import time
import logging
import json
from ..memory.working_memory import MwManager
from ..memory.long_term_memory import LongTermMemoryManager
import asyncio

logger = logging.getLogger(__name__)

@ray.remote
class ObserverAgent:
    """
    An agent that monitors memory patterns and performs optimizations,
    like proactive caching.
    """
    def __init__(self):
        self.agent_id = "Observer-Agent"
        # The observer still needs its own MwManager to read the miss logs
        self.mw_manager = MwManager(organ_id="system_observer")
        self.mlt_manager = LongTermMemoryManager()
        logger.info(f"✅ {self.agent_id} initialized.")

    async def run_proactive_caching(self):
        """
        The core logic for the observer. It finds hot items and caches them.
        """
        logger.info(f"[{self.agent_id}] --- Running proactive caching cycle ---")
        
        # 1. Detect hot items from Mw miss logs
        hot_items = self.mw_manager.get_hot_items(top_n=1)
        if not hot_items:
            logger.info(f"[{self.agent_id}] No hot items detected in this cycle.")
            return

        hot_item_id, miss_count = hot_items[0]
        logger.warning(f"[{self.agent_id}] Hot item detected: '{hot_item_id}' with {miss_count} misses.")
        # Debug: print the hot_item_id to ensure it's a real UUID
        logger.info(f"[{self.agent_id}] Using hot_item_id for query: {hot_item_id}")

        # 2. Retrieve the full data for the hot item from Mlt
        item_data = self.mlt_manager.query_holon_by_id(hot_item_id)
        logger.info(f"[{self.agent_id}] Retrieved item_data for '{hot_item_id}': {item_data}")

        if item_data:
            # 3. Proactively write the item back to Mw to keep it "warm"
            logger.info(f"[{self.agent_id}] Proactively caching '{hot_item_id}' to GLOBAL Mw...")
            self.mw_manager.set_global_item(hot_item_id, json.dumps(item_data))
            logger.info(f"[{self.agent_id}] ✅ Successfully cached '{hot_item_id}' to global cache.")
        else:
            logger.error(f"[{self.agent_id}] Could not find hot item '{hot_item_id}' in Mlt to cache it.")

    async def start_monitoring_loop(self, interval_seconds: int = 10):
        """
        A continuous loop that runs the caching logic periodically.
        """
        logger.info(f"[{self.agent_id}] Starting monitoring loop. Cycle interval: {interval_seconds}s.")
        while True:
            await self.run_proactive_caching()
            await asyncio.sleep(interval_seconds) 