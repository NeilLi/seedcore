#!/usr/bin/env python3
"""
Policy Knowledge Graph (PKG) Manager

Manages the lifecycle of active policy snapshots.
- Loads initial policy from DB.
- Subscribes to hot-swap events via Redis.
- Provides thread-safe access to the active Evaluator.
"""

import asyncio
import logging
import time
import threading
from typing import Optional, Dict, Any, Tuple

# Models
from .evaluator import PKGEvaluator
from .client import PKGClient
from .dao import PKGSnapshotData  # Assuming legacy DAO mapped to new models

logger = logging.getLogger(__name__)

# Constants
PKG_REDIS_CHANNEL = "pkg_updates"
MAX_EVALUATOR_CACHE_SIZE = 3
MAX_RECONNECT_BACKOFF = 60

class PKGManager:
    """
    Singleton manager for Policy Knowledge Graph state.
    """
    
    def __init__(self, pkg_client: PKGClient, redis_client: Any):
        self._client = pkg_client
        self._redis_client = redis_client
        
        # Evaluator Registry: {version: (Evaluator, timestamp)}
        self._evaluators: Dict[str, Tuple[PKGEvaluator, float]] = {}
        self._active_version: Optional[str] = None
        
        # Lock for atomic swaps
        self._swap_lock = threading.Lock()
        
        # Async task tracking
        self._redis_task: Optional[asyncio.Task] = None
        self._status = {"healthy": False, "error": None, "version": None}

    async def start(self):
        """Initialize state and start listeners."""
        logger.info("PKGManager starting...")
        
        # 1. Initial Load (Blocking for safety)
        await self._load_initial_snapshot()
        
        # 2. Start Background Listener
        if self._redis_client:
            self._redis_task = asyncio.create_task(self._redis_listen_loop())
            logger.info("PKG hot-swap listener started")
        else:
            logger.warning("Redis unavailable; PKG hot-swap disabled")

    async def stop(self):
        """Cleanup resources."""
        if self._redis_task:
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
        logger.info("PKGManager stopped")

    # --- Core Logic: Hot Swap ---

    async def _load_and_activate_snapshot(self, snapshot: PKGSnapshotData, source: str):
        """
        Loads a snapshot into memory and atomically swaps it as active.
        """
        version = snapshot.version
        start = time.perf_counter()
        
        try:
            # 1. Create Evaluator (Heavy Operation)
            # This compiles WASM/Rego or loads native rules
            new_evaluator = PKGEvaluator(snapshot)
            
            # 2. Atomic Swap
            with self._swap_lock:
                # Store in cache
                self._evaluators[version] = (new_evaluator, time.time())
                self._active_version = version
                
                # Prune Cache (LRU)
                if len(self._evaluators) > MAX_EVALUATOR_CACHE_SIZE:
                    oldest = min(self._evaluators.keys(), key=lambda k: self._evaluators[k][1])
                    if oldest != self._active_version:
                        del self._evaluators[oldest]
            
            duration = (time.perf_counter() - start) * 1000
            logger.info(f"Activated PKG {version} (src={source}) in {duration:.1f}ms")
            self._status.update({"healthy": True, "error": None, "version": version})

        except Exception as e:
            logger.error(f"Failed to activate PKG {version}: {e}")
            self._status.update({"healthy": False, "error": str(e)})

    # --- Public Accessors ---

    def get_active_evaluator(self) -> Optional[PKGEvaluator]:
        """Thread-safe access to the current policy engine."""
        with self._swap_lock:
            if self._active_version and self._active_version in self._evaluators:
                return self._evaluators[self._active_version][0]
            return None

    def get_metadata(self) -> Dict[str, Any]:
        """Operational metadata for /status endpoints."""
        with self._swap_lock:
            return {
                "active_version": self._active_version,
                "cached_versions": list(self._evaluators.keys()),
                "status": self._status
            }

    # --- Internals ---

    async def _load_initial_snapshot(self):
        try:
            snap = await self._client.get_active_snapshot()
            if snap:
                await self._load_and_activate_snapshot(snap, source="startup")
            else:
                logger.warning("No active PKG snapshot found in DB")
        except Exception as e:
            logger.error(f"Initial load failed: {e}")

    async def _redis_listen_loop(self):
        """Subscribe to updates."""
        pubsub = self._redis_client.pubsub()
        await pubsub.subscribe(PKG_REDIS_CHANNEL)
        
        try:
            async for msg in pubsub.listen():
                if msg['type'] == 'message':
                    data = msg['data'].decode('utf-8') if isinstance(msg['data'], bytes) else msg['data']
                    
                    if data.startswith("activate:"):
                        version = data.split(":", 1)[1]
                        logger.info(f"Hot-swap requested for {version}")
                        
                        snap = await self._client.get_snapshot_by_version(version)
                        if snap:
                            await self._load_and_activate_snapshot(snap, source="redis")
        except Exception as e:
            logger.error(f"Redis listener died: {e}")
        finally:
            await pubsub.close()

# --- Global Singleton ---
_global_manager: Optional[PKGManager] = None

async def initialize_global_pkg_manager(pkg_client, redis_client) -> PKGManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = PKGManager(pkg_client, redis_client)
        await _global_manager.start()
    return _global_manager

def get_global_pkg_manager() -> Optional[PKGManager]:
    return _global_manager