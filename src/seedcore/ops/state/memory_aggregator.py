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
    from ...memory.runtime import connect_default_memory_runtime
    from ...memory.semantic_memory import SemanticMemoryService
    from ...memory.working_memory import MwWorkingMemoryAdapter
    from ...memory.contracts import MemorySubsystemStatus
    _MEMORY_AVAILABLE = True
except ImportError:
    MwManager = None  # type: ignore
    connect_default_memory_runtime = None  # type: ignore
    SemanticMemoryService = None  # type: ignore
    MwWorkingMemoryAdapter = None  # type: ignore
    MemorySubsystemStatus = None  # type: ignore
    _MEMORY_AVAILABLE = False

logger = logging.getLogger(__name__)


class MemoryAggregator:
    """
    Runs a background loop to proactively collect and cache memory stats
    from MwManager, HolonFabric, and Flashbulb systems.
    """

    def __init__(
        self,
        poll_interval: float = 5.0,
        *,
        semantic_memory: Optional[Any] = None,
        memory_runtime: Any = None,
        mw_manager: Optional[MwManager] = None,
    ):
        """
        Initialize the proactive memory aggregator.

        Args:
            poll_interval: How often (in seconds) to poll memory managers.
            semantic_memory: Optional injected :class:`SemanticMemoryService` (skips lazy runtime).
            memory_runtime: Optional injected :class:`MemoryRuntime` (uses ``.semantic``; not closed on stop).
            mw_manager: Optional injected ``MwManager`` for MW stats (skips default organ_id instance).
        """
        self.poll_interval = poll_interval
        self._inject_semantic = semantic_memory
        self._inject_runtime = memory_runtime
        self._inject_mw = mw_manager

        # Internal state cache
        # We cache the raw dicts for mw, mlt, and mfb
        self._stats_cache: Dict[str, Dict] = {
            "mw": {},
            "mlt": {},
            "mfb": {},
        }
        self._last_update_time: float = 0.0

        # Lazy initialization of memory managers
        self._mw_manager: Optional[MwManager] = mw_manager
        self._memory_runtime = None
        self._semantic_memory: Optional[SemanticMemoryService] = None

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
        # Only close a runtime this aggregator created via lazy connect — not injected owners.
        if (
            self._memory_runtime is not None
            and self._inject_semantic is None
            and self._inject_runtime is None
        ):
            try:
                await self._memory_runtime.close()
            except Exception as e:
                logger.debug("MemoryAggregator runtime close failed: %s", e)
            finally:
                self._memory_runtime = None
                self._semantic_memory = None
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
        """Poll working memory statistics (mw) from MwManager via WorkingMemory contract."""
        mw_manager = self._get_mw_manager()
        if mw_manager is None or MwWorkingMemoryAdapter is None:
            st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
            return {
                "status": st.value if st else "unavailable",
                "reason": "mw_manager_unavailable",
            }

        snap = await MwWorkingMemoryAdapter(mw_manager).stats_snapshot()
        total_requests = snap.total_requests
        miss_rate = snap.misses / total_requests if total_requests > 0 else 0.0
        try:
            hot_items = await mw_manager.get_hot_items_async(top_n=10)
            eviction_rate = len(hot_items) / max(total_requests, 1) * 0.1
        except Exception:
            eviction_rate = 0.0

        return {
            "status": snap.health.status.value,
            "reason": snap.health.reason,
            "buffer_size": total_requests,
            "hit_rate": snap.hit_ratio,
            "eviction_rate": eviction_rate,
            "cache_utilization": snap.hit_ratio,
            "miss_rate": miss_rate,
            "total_requests": total_requests,
            "successful_requests": snap.hits,
            "l0_hits": snap.l0_hits,
            "l1_hits": snap.l1_hits,
            "l2_hits": snap.l2_hits,
            "task_hit_ratio": snap.task_hit_ratio,
        }

    async def _poll_mlt_stats(self) -> Dict[str, Any]:
        """Poll semantic memory statistics through the caller-facing contract."""
        semantic = await self._get_semantic_memory()
        if semantic is None:
            st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
            return {
                "status": st.value if st else "unavailable",
                "reason": "semantic_memory_unavailable",
            }

        try:
            snap = await semantic.stats_snapshot()
            total_holons = int(snap.total_holons)
            total_relationships = int(snap.total_relationships)
            bytes_used = int(snap.bytes_used)
        except Exception as e:
            logger.error("Failed to query SemanticMemory stats: %s", e)
            st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
            return {
                "status": st.value if st else "unavailable",
                "reason": str(e),
            }

        storage_gb = bytes_used / (1024**3)
        avg_holon_size = bytes_used // total_holons if total_holons > 0 else 0
        index_size_mb = (bytes_used * 0.15) / (1024**2)

        return {
            "status": snap.health.status.value,
            "reason": snap.health.reason,
            "storage_gb": round(storage_gb, 2),
            "compression_ratio": None,
            "access_patterns": total_relationships,
            "total_holons": total_holons,
            "total_relationships": total_relationships,
            "avg_holon_size": int(avg_holon_size),
            "index_size_mb": round(index_size_mb, 2),
            "bytes_used": bytes_used,
            "vector_dimensions": None,
        }

    async def _poll_mfb_stats(self) -> Dict[str, Any]:
        """Poll flashbulb / incident memory (optional subsystem)."""
        st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
        return {
            "status": st.value if st else "unavailable",
            "reason": "incident_memory_not_configured",
            "incidents": 0,
            "queue_size": 0,
            "avg_weight": None,
            "decay_rate": None,
            "total_events": 0,
        }

    # --- Lazy-init Helpers (copied from legacy) ---

    def _get_mw_manager(self) -> Optional[MwManager]:
        """Get or create a MwManager instance for stats collection."""
        if self._inject_mw is not None:
            return self._inject_mw
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

    async def _get_semantic_memory(self) -> Optional[SemanticMemoryService]:
        """Get or create SemanticMemory via the unified runtime boundary."""
        if self._inject_semantic is not None:
            return self._inject_semantic
        if self._inject_runtime is not None:
            return getattr(self._inject_runtime, "semantic", None)
        if (
            not _MEMORY_AVAILABLE
            or connect_default_memory_runtime is None
            or SemanticMemoryService is None
        ):
            return None
        if self._semantic_memory is None:
            try:
                self._memory_runtime = await connect_default_memory_runtime(
                    pool_size=2,
                    embedder=None,
                )
                self._semantic_memory = self._memory_runtime.semantic
            except Exception as e:
                logger.debug(f"Failed to create SemanticMemory runtime: {e}")
                return None
        return self._semantic_memory
