#!/usr/bin/env python3
"""
Observer Agent - Monitors memory patterns and performs proactive caching.
"""

import logging, sys, os
import asyncio
import json
import ray

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger.addHandler(handler)

from ..bootstrap import get_miss_tracker, get_shared_cache
from ..memory.long_term_memory import LongTermMemoryManager

@ray.remote
class ObserverAgent:
    """
    A pure-async agent that monitors memory patterns and performs optimizations,
    like proactive caching.
    """
    
    def __init__(self):
        """Synchronous constructor - no awaits here."""
        # Configure logging for this actor
        ROOT = logging.getLogger()
        if not ROOT.handlers or os.getenv("FORCE_STDOUT_HANDLER", "1") == "1":
            h = logging.StreamHandler(sys.stdout)
            
            # Optional: tag every line with the Ray actor-ID
            class RayContextFilter(logging.Filter):
                def filter(self, record):
                    import ray, os
                    # pid is cheap; actor‑id is available only inside a task/actor.
                    try:
                        actor = getattr(ray.get_runtime_context(), 'actor_id', '') \
                                 if ray.is_initialized() else ""
                        record.actor_id = actor[:8] if actor else "-"
                    except:
                        record.actor_id = "-"
                    record.pid = os.getpid()
                    return True

            h.addFilter(RayContextFilter())      # add filter to the StreamHandler
            h.setFormatter(logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(actor_id)s | %(name)s | %(message)s"
            ))
            ROOT.setLevel(logging.INFO)      # show INFO and above
            ROOT.handlers = [h]              # replace Ray's minimal handler
        
        self.agent_id = "Observer-Agent"
        self.miss_threshold = int(os.getenv("MISS_THRESHOLD", 2))
        # placeholders – no awaits here
        self._ltm = None
        self._miss = None
        self._cache = None
        self._loop = None
        logger.info("%s created, awaiting ready()", self.agent_id)

    async def ready(self):
        """Async bootstrap, must be called once from the driver."""
        # Safe to await here
        from ..memory.long_term_memory import LongTermMemoryManager
        from ..bootstrap import get_miss_tracker, get_shared_cache

        self._ltm = LongTermMemoryManager()
        self._miss = get_miss_tracker()
        self._cache = get_shared_cache()
        self._loop = asyncio.create_task(self._monitor())
        logger.info("%s ready – monitoring loop started", self.agent_id)

    async def _monitor(self):
        """The main monitoring loop. This runs continuously in the background."""
        logger.info("[%s] Starting monitoring loop...", self.agent_id)
        while True:
            try:
                await self._proactive_pass()
            except Exception as e:
                logger.error("[%s] Error in monitoring loop: %s", self.agent_id, e, exc_info=True)
            # The loop runs every 2 seconds
            await asyncio.sleep(2)

    async def _proactive_pass(self):
        """Performs a single pass of proactive caching logic."""
        if not self._miss:
            logger.warning("[%s] Miss tracker not available.", self.agent_id)
            print(f"DEBUG: {self.agent_id} - Miss tracker not available.")
            return

        # Get the top N most frequently missed items
        hot_items = await self._miss.get_top_n.remote(1)
        if not hot_items:
            return

        # The first item is the "hottest"
        uuid, miss_count = hot_items[0]

        if miss_count > self.miss_threshold:
            logger.info(
                "[%s] Hot item detected: %s (misses: %d)",
                self.agent_id,
                uuid,
                miss_count,
            )
            print(f"DEBUG: {self.agent_id} - Hot item detected: {uuid} (misses: {miss_count})")
            
            # Check if the item is already in the working memory cache
            global_key = f"global:item:{uuid}"
            existing_value = await self._cache.get.remote(global_key)
            if existing_value:
                logger.info("[%s] Item %s is already in cache. Skipping.", self.agent_id, uuid)
                print(f"DEBUG: {self.agent_id} - Item {uuid} is already in cache. Skipping.")
                return

            # Fetch the full data from Long-Term Memory (LTM)
            logger.info("[%s] Fetching item %s from LTM for proactive caching.", self.agent_id, uuid)
            print(f"DEBUG: {self.agent_id} - Fetching item {uuid} from LTM for proactive caching.")
            data = await self._ltm.query_holon_by_id_async(uuid)

            if not data:
                logger.warning("[%s] LTM returned no data for %s", self.agent_id, uuid)
                print(f"DEBUG: {self.agent_id} - LTM returned no data for {uuid}")
                return

            # Write the fetched data to the shared working memory cache
            await self._cache.set.remote(global_key, json.dumps(data))
            logger.info("✅ [%s] Proactively cached item %s", self.agent_id, uuid)
            print(f"DEBUG: ✅ {self.agent_id} - Proactively cached item {uuid}")

    async def get_status(self):
        """Returns the current status of the agent."""
        return {
            "agent_id": self.agent_id,
            "is_ready": self._loop is not None and not self._loop.done(),
            "miss_threshold": self.miss_threshold,
        }

    def code_hash(self):
        """Returns a hash of the current code file for version tracking."""
        import hashlib
        return hashlib.md5(__file__.encode()).hexdigest()[:8] 