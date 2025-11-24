# Copyright 2024 SeedCore Contributors
# ... (Apache License) ...

"""
MemoryAggregator - Proactive aggregator for memory manager stats.

This service runs a continuous background loop to poll all central memory
managers (MwManager, HolonFabric) for their system-wide telemetry.

It provides a real-time, cached view of the organism's memory system health,
excluding per-agent ('ma') stats, which are handled by the AgentAggregator.
"""

import asyncio
import logging
import time
from typing import Dict, Any, Optional

# Import the data model. Note: 'ma' will be empty from this aggregator.

# Optional memory module imports
try:
    from ...memory.mw_manager import MwManager
    from ...memory.holon_fabric import HolonFabric
    from ...memory.backends.pgvector_backend import PgVectorStore
    from ...memory.backends.neo4j_graph import Neo4jGraph
    _MEMORY_AVAILABLE = True
except ImportError:
    MwManager = None  # type: ignore
    HolonFabric = None  # type: ignore
    PgVectorStore = None  # type: ignore
    Neo4jGraph = None  # type: ignore
    _MEMORY_AVAILABLE = False

logger = logging.getLogger(__name__)


class MemoryAggregator:
    """
    Runs a background loop to proactively collect and cache memory stats
    from MwManager, HolonFabric, and Flashbulb systems.
    """

    def __init__(self, poll_interval: float = 5.0):
        """
        Initialize the proactive memory aggregator.

        Args:
            poll_interval: How often (in seconds) to poll memory managers.
        """
        self.poll_interval = poll_interval

        # Internal state cache
        # We cache the raw dicts for mw, mlt, and mfb
        self._stats_cache: Dict[str, Dict] = {
            "mw": {},
            "mlt": {},
            "mfb": {},
        }
        self._last_update_time: float = 0.0

        # Lazy initialization of memory managers
        self._mw_manager: Optional[MwManager] = None
        self._holon_fabric: Optional[HolonFabric] = None

        # Control
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._is_running = asyncio.Event()

        logger.info("✅ MemoryAggregator initialized")

    async def start(self):
        """Start the proactive polling loop."""
        if self._loop_task is None or self._loop_task.done():
            logger.info(f"Starting proactive memory poll loop (interval: {self.poll_interval}s)")
            self._loop_task = asyncio.create_task(self._poll_loop())
        else:
            logger.warning("Memory poll loop is already running.")

    async def stop(self):
        """Stop the proactive polling loop."""
        if self.is_running() and self._loop_task:
            logger.info("Stopping proactive memory poll loop...")
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        self._is_running.clear()
        logger.info("Proactive memory poll loop stopped.")

    def is_running(self) -> bool:
        """Check if the loop is running and has data."""
        return self._is_running.is_set()

    async def wait_for_first_poll(self, timeout: float = 10.0):
        """Waits for the first data poll to complete."""
        try:
            await asyncio.wait_for(self._is_running.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Timeout: Memory aggregator failed to get first poll data.")
            raise

    # --- Main Proactive Loop ---

    async def _poll_loop(self):
        """The main background task that continuously polls memory managers."""
        while True:
            try:
                start_time = time.monotonic()

                # 1. Poll all memory tiers in parallel
                results = await asyncio.gather(
                    self._poll_mw_stats(),
                    self._poll_mlt_stats(),
                    self._poll_mfb_stats(),
                    return_exceptions=True
                )
                
                mw_stats, mlt_stats, mfb_stats = results
                
                # 2. Handle exceptions and update the new stats dict
                new_stats = {}
                if isinstance(mw_stats, Exception):
                    logger.error(f"Failed to poll MwManager: {mw_stats}")
                    new_stats["mw"] = self._stats_cache.get("mw", {}) # Keep old
                else:
                    new_stats["mw"] = mw_stats

                if isinstance(mlt_stats, Exception):
                    logger.error(f"Failed to poll HolonFabric: {mlt_stats}")
                    new_stats["mlt"] = self._stats_cache.get("mlt", {}) # Keep old
                else:
                    new_stats["mlt"] = mlt_stats

                if isinstance(mfb_stats, Exception):
                    logger.error(f"Failed to poll MfbManager: {mfb_stats}")
                    new_stats["mfb"] = self._stats_cache.get("mfb", {}) # Keep old
                else:
                    new_stats["mfb"] = mfb_stats

                # 3. Atomically update the internal state
                await self._update_state(new_stats)
                
                # 4. Signal that we have data
                self._is_running.set()

                # Account for processing time in sleep
                duration = time.monotonic() - start_time
                await asyncio.sleep(max(0, self.poll_interval - duration))

            except asyncio.CancelledError:
                logger.info("Memory poll loop cancelled.")
                break
            except Exception as e:
                logger.error(f"Critical error in memory poll loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _update_state(self, new_stats: Dict[str, Dict]):
        """Atomically update the shared state."""
        async with self._lock:
            self._stats_cache = new_stats
            self._last_update_time = time.time()

    # --- Public API (Getters) ---

    async def get_memory_stats(self) -> Dict[str, Dict]:
        """
        Get all cached memory manager stats (mw, mlt, mfb). (O(1) lookup)
        Note: This does *not* include 'ma' (agent) stats.
        """
        if not self.is_running():
            logger.warning("get_memory_stats called before first poll.")
            return {}
            
        async with self._lock:
            return self._stats_cache.copy()

    async def get_last_update_time(self) -> float:
        """Get the timestamp of the last successful poll."""
        return self._last_update_time

    # --- Internal Polling Methods ---

    async def _poll_mw_stats(self) -> Dict[str, Any]:
        """Poll working memory statistics (mw) from MwManager."""
        mw_manager = self._get_mw_manager()
        if mw_manager is None:
            logger.debug("MwManager unavailable, returning simulated stats")
            return self._get_simulated_mw_stats()
        
        # Get telemetry from the MwManager instance
        # Use async method if available, else fall back to sync
        get_telemetry_fn = getattr(mw_manager, "get_telemetry_async", mw_manager.get_telemetry)
        
        if asyncio.iscoroutinefunction(get_telemetry_fn):
            telemetry = await get_telemetry_fn()
        else:
            telemetry = get_telemetry_fn()
            
        # --- Process Telemetry (copied from legacy) ---
        total_requests = telemetry.get("total_requests", 0)
        hits = telemetry.get("hits", 0)
        hit_ratio = telemetry.get("hit_ratio", 0.0)
        
        buffer_size = total_requests  # Approximate
        cache_utilization = hit_ratio  # Proxy
        miss_rate = telemetry.get("misses", 0) / total_requests if total_requests > 0 else 0.0
        
        try:
            hot_items = await mw_manager.get_hot_items_async(top_n=10)
            eviction_rate = len(hot_items) / max(total_requests, 1) * 0.1  # Rough estimate
        except Exception:
            eviction_rate = 0.12  # Fallback
        
        return {
            "buffer_size": buffer_size,
            "hit_rate": hit_ratio,
            "eviction_rate": eviction_rate,
            "cache_utilization": cache_utilization,
            "miss_rate": miss_rate,
            "total_requests": total_requests,
            "successful_requests": hits,
            "l0_hits": telemetry.get("l0_hits", 0),
            "l1_hits": telemetry.get("l1_hits", 0),
            "l2_hits": telemetry.get("l2_hits", 0),
            "task_hit_ratio": telemetry.get("task_hit_ratio", 0.0),
        }

    async def _poll_mlt_stats(self) -> Dict[str, Any]:
        """Poll long-term memory statistics (mlt) from HolonFabric."""
        fabric = self._get_holon_fabric()
        if fabric is None:
            logger.debug("HolonFabric unavailable, returning simulated stats")
            return self._get_simulated_mlt_stats()
        
        try:
            # Query stats directly from backends
            total_holons = await fabric.vec.get_count()
            total_relationships = await fabric.graph.get_count()
            
            # Get bytes_used from pgvector store
            bytes_query = "SELECT pg_total_relation_size('holons')"
            bytes_used = await fabric.vec.execute_scalar_query(bytes_query)
            bytes_used = int(bytes_used) if bytes_used is not None else 0
            
            status = "active"  # Assume active if we can query
            
        except Exception as e:
            logger.error(f"Failed to query HolonFabric stats: {e}")
            return self._get_simulated_mlt_stats()
        
        # --- Process Stats (copied from legacy) ---
        storage_gb = bytes_used / (1024 ** 3)
        avg_holon_size = bytes_used / total_holons if total_holons > 0 else 0
        compression_ratio = 0.65  # Default estimate
        index_size_mb = (bytes_used * 0.15) / (1024 ** 2)
        
        return {
            "storage_gb": round(storage_gb, 2),
            "compression_ratio": compression_ratio,
            "access_patterns": total_relationships,
            "total_holons": total_holons,
            "total_relationships": total_relationships,
            "avg_holon_size": int(avg_holon_size),
            "index_size_mb": round(index_size_mb, 2),
            "bytes_used": bytes_used,
            "status": status,
            "vector_dimensions": 768  # Default, can be made configurable
        }

    async def _poll_mfb_stats(self) -> Dict[str, Any]:
        """Poll flashbulb memory statistics (mfb)."""
        # TODO: Integrate with actual FlashbulbClient instances
        # For now, return simulated statistics
        return self._get_simulated_mfb_stats()

    # --- Lazy-init Helpers (copied from legacy) ---

    def _get_mw_manager(self) -> Optional[MwManager]:
        """Get or create a MwManager instance for stats collection."""
        if not _MEMORY_AVAILABLE or MwManager is None:
            return None
        if self._mw_manager is None:
            try:
                # Use a system-wide organ_id for aggregator stats
                self._mw_manager = MwManager(organ_id="system_aggregator")
            except Exception as e:
                logger.debug(f"Failed to create MwManager: {e}")
                return None
        return self._mw_manager

    def _get_holon_fabric(self) -> Optional[HolonFabric]:
        """Get or create a HolonFabric instance for LTM stats."""
        if not _MEMORY_AVAILABLE or HolonFabric is None:
            return None
        if self._holon_fabric is None:
            try:
                import os
                # Create backend stores directly
                pg_store = PgVectorStore(
                    os.getenv("PG_DSN", "postgresql://postgres:password@postgresql:5432/seedcore"),
                    pool_size=10
                )
                neo4j_graph = Neo4jGraph(
                    os.getenv("NEO4J_URI") or os.getenv("NEO4J_BOLT_URL", "bolt://neo4j:7687"),
                    auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "password"))
                )
                
                # Create HolonFabric instance
                self._holon_fabric = HolonFabric(
                    vec_store=pg_store,
                    graph=neo4j_graph,
                    embedder=None  # No embedder needed for stats collection
                )
            except Exception as e:
                logger.debug(f"Failed to create HolonFabric: {e}")
                return None
        return self._holon_fabric

    # --- Simulated Data Fallbacks (copied from legacy) ---

    def _get_simulated_mw_stats(self) -> Dict[str, Any]:
        return {
            "buffer_size": 1024,
            "hit_rate": 0.78,
            "eviction_rate": 0.12,
            "cache_utilization": 0.65,
            "miss_rate": 0.22,
            "total_requests": 1000,
            "successful_requests": 780
        }

    def _get_simulated_mlt_stats(self) -> Dict[str, Any]:
        return {
            "storage_gb": 50.2,
            "compression_ratio": 0.65,
            "access_patterns": 42,
            "total_holons": 1000,
            "avg_holon_size": 1024,
            "query_latency_ms": 150.0,
            "index_size_mb": 25.5
        }
    
    def _get_simulated_mfb_stats(self) -> Dict[str, Any]:
        return {
            "incidents": 0,
            "queue_size": 128,
            "avg_weight": 0.73,
            "decay_rate": 0.15,
            "total_events": 500
        }