import ray
import time
import logging
import json
import os
from ..memory.working_memory import MwManager
from ..memory.long_term_memory import LongTermMemoryManager
import asyncio
import traceback
import sys

logger = logging.getLogger(__name__)

def _fmt(exc):
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

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
        # Lower threshold for testing
        self.MISS_THRESHOLD = int(os.getenv("MISS_THRESHOLD", 2))  # was 10, now 2 for testing
        logger.info(f"✅ {self.agent_id} initialized with MISS_THRESHOLD={self.MISS_THRESHOLD}.")
        
        # Start the monitoring loop automatically
        self._start_monitoring_loop()

    def _start_monitoring_loop(self):
        """Start the monitoring loop in a background thread."""
        import threading
        import time
        
        def run_loop():
            logger.info(f"[{self.agent_id}] Starting monitoring loop in background thread.")
            cycle_count = 0
            while True:
                try:
                    cycle_count += 1
                    logger.info(f"[{self.agent_id}] Monitoring cycle #{cycle_count} starting...")
                    # Run the proactive caching logic synchronously
                    self.run_proactive_caching_sync()
                    logger.info(f"[{self.agent_id}] Monitoring cycle #{cycle_count} completed, sleeping for 5s...")
                    time.sleep(5)
                except Exception as e:
                    logger.error(f"[{self.agent_id}] Error in monitoring loop: {e}")
                    time.sleep(5)
        
        # Start the monitoring loop in a background thread
        thread = threading.Thread(target=run_loop, daemon=True)
        thread.start()
        logger.info(f"[{self.agent_id}] Monitoring loop started in background thread.")

    def run_proactive_caching_sync(self):
        """
        Synchronous version of the proactive caching logic.
        """
        try:
            logger.info(f"[{self.agent_id}] --- Running proactive caching pass")

            # 1. Detect hot items from Mw miss logs
            logger.info(f"[{self.agent_id}] Getting hot items from Mw")
            hot_items = self.mw_manager.get_hot_items(top_n=1)
            logger.info(f"[{self.agent_id}] Hot items found: {hot_items}")
            
            if not hot_items:
                logger.info(f"[{self.agent_id}] No hot items detected in this cycle.")
                return

            hot_item_id, miss_count = hot_items[0]
            logger.info(f"[{self.agent_id}] misses={miss_count} threshold={self.MISS_THRESHOLD}")
            
            if miss_count < self.MISS_THRESHOLD:
                logger.info(f"[{self.agent_id}] Miss count {miss_count} below threshold {self.MISS_THRESHOLD}, skipping.")
                return
                
            logger.warning(f"[{self.agent_id}] Hot item detected: '{hot_item_id}' with {miss_count} misses.")
            logger.info(f"[{self.agent_id}] Using hot_item_id for query: {hot_item_id}")

            # 2. Retrieve the full data for the hot item from Mlt
            logger.info(f"[{self.agent_id}] Calling query_holon_by_id({hot_item_id})...")
            item_data = self.mlt_manager.query_holon_by_id(hot_item_id)
            logger.info(f"[{self.agent_id}] query_holon_by_id result: {item_data}")
            logger.debug(f"[{self.agent_id}] DBG holon lookup for {hot_item_id} => {'HIT' if item_data else 'MISS'}")

            if item_data:
                # 3. Proactively write the item back to Mw to keep it "warm"
                logger.info(f"[{self.agent_id}] Proactively caching '{hot_item_id}' to GLOBAL Mw...")
                try:
                    self.mw_manager.set_global_item(hot_item_id, json.dumps(item_data))
                    logger.info(f"[{self.agent_id}] ✅ Successfully cached '{hot_item_id}' to global cache.")
                except Exception as e:
                    logger.error(f"[{self.agent_id}] Failed to cache '{hot_item_id}': {e}")
            else:
                logger.warning(f"[{self.agent_id}] Holon {hot_item_id} not found – skip proactive cache")

        except Exception as e:
            logger.exception(f"[{self.agent_id}] run_proactive_caching_sync crashed")
            raise 