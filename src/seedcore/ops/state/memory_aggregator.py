# Copyright 2024 SeedCore Contributors
# ... (Apache License) ...

"""
MemoryAggregator - Proactive aggregator for memory manager stats.

This service runs a continuous background loop to poll all central memory
managers (working, semantic, and incident memory) for system-wide telemetry.

It provides a real-time, cached view of the organism's memory system health,
excluding per-agent ('ma') stats, which are handled by the AgentAggregator.
"""

import asyncio
import logging
import time
from typing import Awaitable, Callable, Dict, Any, Optional

# Import the data model. Note: 'ma' will be empty from this aggregator.

# Optional memory module imports
try:
    from ...memory.mw_manager import MwManager
    from ...memory.runtime import connect_default_memory_runtime
    from ...memory.incident_memory import IncidentMemoryService
    from ...memory.semantic_memory import SemanticMemoryService
    _MEMORY_AVAILABLE = True
except ImportError:
    MwManager = None  # type: ignore
    connect_default_memory_runtime = None  # type: ignore
    IncidentMemoryService = None  # type: ignore
    SemanticMemoryService = None  # type: ignore
    _MEMORY_AVAILABLE = False

logger = logging.getLogger(__name__)


class MemoryAggregator:
    """
    Runs a background loop to proactively collect and cache memory stats
    from working-memory, semantic-memory, and incident-memory systems.
    """

    def __init__(
        self,
        poll_interval: float = 5.0,
        *,
        semantic_memory: Optional[Any] = None,
        incident_memory: Optional[Any] = None,
        memory_runtime: Any = None,
        mw_manager: Optional[MwManager] = None,
        organism_telemetry_fetch: Optional[
            Callable[[], Awaitable[Dict[str, Any]]]
        ] = None,
    ):
        """
        Initialize the proactive memory aggregator.

        Args:
            poll_interval: How often (in seconds) to poll memory managers.
            semantic_memory: Optional injected :class:`SemanticMemoryService` (skips lazy runtime).
            incident_memory: Optional injected :class:`IncidentMemoryService` (skips runtime lookup).
            memory_runtime: Optional injected :class:`MemoryRuntime` (uses ``.semantic``; not closed on stop).
            mw_manager: Optional injected ``MwManager`` for MW stats (skips default organ_id instance).
            organism_telemetry_fetch: When set, poll memory stats via this async callable first
                (HTTP/RPC to OrganismService). Must return a dict with ``ok: True`` and ``mw`` / ``mlt`` / ``mfb``
                keys on success. On failure or missing ``ok``, falls back to local polling.
        """
        self.poll_interval = poll_interval
        self._inject_semantic = semantic_memory
        self._inject_incident = incident_memory
        self._inject_runtime = memory_runtime
        self._inject_mw = mw_manager
        self._organism_telemetry_fetch = organism_telemetry_fetch

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
        self._incident_memory: Optional[IncidentMemoryService] = None

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
                self._incident_memory = None
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

                # 1. Prefer organism-owned telemetry (single MemoryRuntime / pools) when configured.
                org_batch = await self._try_organism_telemetry()
                if org_batch is not None:
                    mw_stats, mlt_stats, mfb_stats = org_batch
                else:
                    results = await asyncio.gather(
                        self._poll_mw_stats(),
                        self._poll_mlt_stats(),
                        self._poll_mfb_stats(),
                        return_exceptions=True,
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
                    logger.error(f"Failed to poll semantic memory: {mlt_stats}")
                    new_stats["mlt"] = self._stats_cache.get("mlt", {}) # Keep old
                else:
                    new_stats["mlt"] = mlt_stats

                if isinstance(mfb_stats, Exception):
                    logger.error(f"Failed to poll incident memory: {mfb_stats}")
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

    async def _try_organism_telemetry(
        self,
    ) -> Optional[tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]]:
        if self._organism_telemetry_fetch is None:
            return None
        try:
            raw = await self._organism_telemetry_fetch()
        except Exception as e:
            logger.debug("Organism memory telemetry fetch failed: %s", e)
            return None
        if not isinstance(raw, dict):
            return None
        mw = raw.get("mw")
        mlt = raw.get("mlt")
        mfb = raw.get("mfb")
        if not isinstance(mw, dict) or not isinstance(mlt, dict) or not isinstance(mfb, dict):
            return None
        if raw.get("ok") is not True:
            logger.debug(
                "Organism memory telemetry returned degraded payload: %s",
                raw.get("error") or raw.get("reason") or "unknown",
            )
        return (mw, mlt, mfb)

    async def _poll_mw_stats(self) -> Dict[str, Any]:
        """Poll working memory statistics (mw) from MwManager via WorkingMemory contract."""
        from ...memory.telemetry import working_memory_stats_dict

        return await working_memory_stats_dict(self._get_mw_manager())

    async def _poll_mlt_stats(self) -> Dict[str, Any]:
        """Poll semantic memory statistics through the caller-facing contract."""
        from ...memory.telemetry import semantic_memory_stats_dict

        semantic = await self._get_semantic_memory()
        return await semantic_memory_stats_dict(semantic)

    async def _poll_mfb_stats(self) -> Dict[str, Any]:
        """Poll flashbulb / incident memory (optional subsystem)."""
        from ...memory.telemetry import incident_memory_stats_dict

        incident = await self._get_incident_memory()
        return await incident_memory_stats_dict(incident)

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

    async def _get_incident_memory(self) -> Optional[IncidentMemoryService]:
        """Get injected incident memory or runtime-backed incident service."""
        if self._inject_incident is not None:
            return self._inject_incident
        if self._incident_memory is not None:
            return self._incident_memory
        if self._inject_runtime is not None:
            self._incident_memory = getattr(self._inject_runtime, "incident", None)
            return self._incident_memory
        if self._memory_runtime is not None:
            self._incident_memory = getattr(self._memory_runtime, "incident", None)
            return self._incident_memory
        return None
