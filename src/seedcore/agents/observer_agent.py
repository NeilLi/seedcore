#!/usr/bin/env python3
"""
Observer Agent - Monitors memory patterns and performs proactive caching.
"""

import asyncio
import json
import logging
import os
import ray
import sys
logging.basicConfig(
    stream=sys.stdout,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
    force=True,  # Overwrites Ray’s default handlers (Python ≥3.8)
)

from ..memory.working_memory import get_miss_tracker, get_shared_cache
from ..memory.long_term_memory import LongTermMemoryManager

logger = logging.getLogger(__name__)

@ray.remote
class ObserverAgent:
    """
    A pure-async agent that monitors memory patterns and performs optimizations,
    like proactive caching.
    """
    
    # ---------- sync bootstrap ----------
    def __init__(self):
        self.agent_id = "Observer-Agent"
        self.MISS_THRESHOLD = int(os.getenv("MISS_THRESHOLD", 2))
        # flag so we do the async part exactly once
        self._started = False
        logger.info("🚀 %s created, waiting for event-loop …", self.agent_id)

    # ---------- one-shot async bootstrap ----------
    async def _async_init(self):
        if self._started:              # idempotent
            logger.info("[%s] _async_init already started, skipping", self.agent_id)
            return
        self._started = True
        logger.info("[%s] Starting _async_init", self.agent_id)

        # singleton actors
        self.miss_tracker = get_miss_tracker()
        self.mw           = get_shared_cache()

        # DB client
        self.ltm_manager  = LongTermMemoryManager()
        logger.info("✅ %s fully initialised (MISS_THRESHOLD=%s)",
                    self.agent_id, self.MISS_THRESHOLD)

        # start background task *inside* the actor's loop
        logger.info("[%s] Starting monitor loop", self.agent_id)
        asyncio.create_task(self.monitor())

    # ---------- public no-op used only to kick the async init ----------
    async def ready(self):
        """Ray call that triggers async bootstrap exactly once."""
        logger.info("[%s] ready() called", self.agent_id)
        await self._async_init()

    # ---------- background monitor ----------
    async def monitor(self):
        logger.info("[%s] monitor loop started.", self.agent_id)
        while True:
            try:
                logger.info("[%s] About to call _proactive_pass", self.agent_id)
                await self._proactive_pass()
                logger.info("[%s] _proactive_pass completed successfully", self.agent_id)
            except Exception as e:
                logger.exception("[%s] monitor pass crashed: %s", self.agent_id, e)
            logger.info("[%s] Sleeping for 2 seconds", self.agent_id)
            await asyncio.sleep(2)

    async def _proactive_pass(self):
        logger.info("[%s] Starting _proactive_pass", self.agent_id)
        
        try:
            hot_items = await self.miss_tracker.get_top_n.remote(1)
            logger.info("[%s] Got hot_items: %s", self.agent_id, hot_items)
        except Exception as e:
            logger.exception("[%s] Error getting hot items: %s", self.agent_id, e)
            return
        
        if not hot_items:
            logger.info("[%s] No hot items found", self.agent_id)
            return
            
        uuid, miss_cnt = hot_items[0]
        logger.info("[%s] Processing item %s with %s misses (threshold: %s)", 
                   self.agent_id, uuid, miss_cnt, self.MISS_THRESHOLD)
        
        if miss_cnt < self.MISS_THRESHOLD:
            logger.info("[%s] Miss count %s below threshold %s, skipping", 
                       self.agent_id, miss_cnt, self.MISS_THRESHOLD)
            return

        logger.warning("[%s] Hot item detected: %s (%s misses)",
                       self.agent_id, uuid, miss_cnt)
        
        # Query the database for the hot item
        try:
            logger.info("[%s] Querying LTM for %s", self.agent_id, uuid)
            data = await self.ltm_manager.query_holon_by_id_async(uuid)
            logger.info("[%s] LTM query result type: %s, value: %s", 
                       self.agent_id, type(data), str(data)[:100] if data else "None")
            
            if not data:
                logger.warning("[%s] LTM returned no data for %s", self.agent_id, uuid)
                return

            # Proactively cache the item using the correct global key format
            global_key = f"global:item:{uuid}"
            logger.info("[%s] Attempting to cache with key: %s", self.agent_id, global_key)
            
            await self.mw.set.remote(global_key, json.dumps(data))
            logger.info("[%s] ✅ Proactively cached %s", self.agent_id, uuid)
            
        except Exception as e:
            logger.exception("[%s] Error in _proactive_pass for %s: %s", self.agent_id, uuid, e) 