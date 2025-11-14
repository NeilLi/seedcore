# ops/pkg/manager.py

import asyncio
import threading
import logging
import time
import random
from typing import Any, Dict, Optional

# --- Core Dependencies ---
from .evaluator import PKGEvaluator
from .client import PKGClient
from .dao import PKGSnapshotData


# --- Configuration Constants ---
PKG_REDIS_CHANNEL = "pkg_updates"
MAX_EVALUATOR_CACHE_SIZE = 3  # Keep last 3 versions for quick rollback
MAX_RECONNECT_BACKOFF = 60  # Maximum backoff in seconds


class PKGManager:
    """
    Manages the lifecycle of Policy Knowledge Graph (PKG) snapshots.
    
    This class loads the active policy from the database on startup,
    listens to a Redis channel for hot-swap updates,
    and provides a thread-safe method to access the currently active
    policy evaluator.
    
    Supports multi-version evaluator caching for A/B testing and quick rollback.
    Implements async context manager protocol for clean resource management.
    """

    def __init__(self, pkg_client: Any, redis_client: Any):
        """
        Initializes the PKGManager.
        
        Args:
            pkg_client: An initialized database client (e.g., PKGClient).
            redis_client: An initialized Redis client.
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self._client = pkg_client
        self._redis_client = redis_client
        
        # Multi-version evaluator registry (for A/B testing and rollback)
        # Stores (evaluator, load_timestamp) tuples for LRU eviction
        self._evaluators: Dict[str, tuple[PKGEvaluator, float]] = {}  # keyed by version
        self._active_version: Optional[str] = None
        
        # Legacy single evaluator (for backward compatibility)
        self._active_evaluator: Optional[PKGEvaluator] = None
        
        # A thread-safe lock to protect the atomic pointer swap
        # This is a threading.Lock, not asyncio.Lock, to ensure
        # thread-safety across sync/async boundaries.
        self._swap_lock = threading.Lock()
        
        # Health and status tracking
        self._status = {
            "healthy": True,
            "last_error": None,
            "last_activation": None,
            "degraded_mode": False
        }
        
        self._redis_task: Optional[asyncio.Task] = None
        self._pubsub_channel = PKG_REDIS_CHANNEL 

    async def start(self):
        """
        Starts the manager: loads the initial snapshot and starts the
        Redis listener for hot-swaps.
        """
        self.logger.info("PKGManager starting...")
        
        try:
            await self._load_initial_snapshot()
            self._status["healthy"] = True
            self._status["last_error"] = None
        except Exception as e:
            self.logger.error(f"Failed to load initial snapshot: {e}", exc_info=True)
            self._status["healthy"] = False
            self._status["degraded_mode"] = True
            self._status["last_error"] = str(e)
            # Continue startup even if snapshot load fails (degraded mode)
        
        if self._redis_client is not None:
            self.logger.info("Starting Redis hot-swap listener task...")
            self._redis_task = asyncio.create_task(self._redis_listen_loop())
        else:
            self.logger.warning("Redis client not available, hot-swap will be disabled")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()
        return False

    async def stop(self):
        """Shuts down the Redis listener task."""
        self.logger.info("PKGManager stopping...")
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                self.logger.info("Redis listener task cancelled.")

    async def _load_initial_snapshot(self):
        """
        Queries Postgres for the active snapshot on startup[cite: 48].
        """
        start_time = time.perf_counter()
        self.logger.info("Performing initial load of active PKG snapshot...")
        
        try:
            snapshot = await self._client.get_active_snapshot()
            if snapshot:
                await self._load_and_activate_snapshot(snapshot, source="startup")
            else:
                self.logger.warning("No active PKG snapshot found on startup. Manager will start with no policy.")
                self._status["degraded_mode"] = True
        except Exception as e:
            self.logger.error(f"Failed to load initial snapshot: {e}", exc_info=True)
            self._status["degraded_mode"] = True
            self._status["last_error"] = str(e)
        
        elapsed = time.perf_counter() - start_time
        self.logger.info(f"Initial snapshot load completed in {elapsed:.3f}s")

    async def _redis_listen_loop(self):
        """
        The background asyncio task that listens for Redis Pub/Sub messages.
        
        Uses exponential backoff with jitter for reconnection resilience.
        Implements proper cleanup for pubsub connections.
        """
        pubsub = None
        backoff = 1.0  # Start with 1 second
        
        while True:
            try:
                if not pubsub:
                    pubsub = await self._redis_client.pubsub()
                    await pubsub.subscribe(self._pubsub_channel)
                    self.logger.info(f"Subscribed to Redis channel: {self._pubsub_channel}")
                    backoff = 1.0  # Reset backoff on successful connection
                    self._status["healthy"] = True
                    self._status["last_error"] = None

                # Use async iteration pattern (aioredis v2+ compatible)
                # Falls back to get_message() if listen() is not available
                try:
                    async for message in pubsub.listen():
                        if message and message.get('type') == 'message':
                            data = message.get('data')
                            if isinstance(data, bytes):
                                data = data.decode('utf-8')
                            
                            self.logger.info({
                                "event": "redis_message_received",
                                "channel": self._pubsub_channel,
                                "data": data,
                                "timestamp": time.time()
                            })
                            
                            # Implements: "PUBLISH pkg_updates ""activate:rules@1.4.0""" 
                            if data.startswith("activate:"):
                                version_id = data.split(":", 1)[-1]
                                snapshot = await self._client.get_snapshot_by_version(version_id)
                                if snapshot:
                                    # Use asyncio.shield() to prevent cancellation during shutdown
                                    asyncio.create_task(
                                        asyncio.shield(
                                            self._load_and_activate_snapshot(snapshot, source="redis")
                                        )
                                    )
                                else:
                                    self.logger.error(f"Hot-Swap: Snapshot '{version_id}' not found in database.")
                except AttributeError:
                    # Fallback to get_message() for older aioredis versions
                    message = await pubsub.get_message(timeout=1.0)
                    if message and message.get('type') == 'message':
                        data = message.get('data')
                        if isinstance(data, bytes):
                            data = data.decode('utf-8')
                        
                        self.logger.info({
                            "event": "redis_message_received",
                            "channel": self._pubsub_channel,
                            "data": data,
                            "timestamp": time.time()
                        })
                        
                        if data.startswith("activate:"):
                            version_id = data.split(":", 1)[-1]
                            snapshot = await self._client.get_snapshot_by_version(version_id)
                            if snapshot:
                                # Use asyncio.shield() to prevent cancellation during shutdown
                                asyncio.create_task(
                                    asyncio.shield(
                                        self._load_and_activate_snapshot(snapshot, source="redis")
                                    )
                                )
                            else:
                                self.logger.error(f"Hot-Swap: Snapshot '{version_id}' not found in database.")

            except asyncio.CancelledError:
                # Cleanup pubsub on cancellation
                if pubsub:
                    try:
                        await pubsub.unsubscribe(self._pubsub_channel)
                        await pubsub.close()
                    except Exception as cleanup_error:
                        self.logger.warning(f"Error cleaning up pubsub: {cleanup_error}")
                raise  # Propagate cancellation
            except Exception as e:
                self.logger.error({
                    "event": "redis_listener_error",
                    "error": str(e),
                    "backoff_seconds": backoff,
                    "timestamp": time.time()
                }, exc_info=True)
                
                # Update health status
                self._status["healthy"] = False
                self._status["last_error"] = str(e)
                
                # Cleanup pubsub before reconnecting
                if pubsub:
                    try:
                        await pubsub.unsubscribe(self._pubsub_channel)
                        await pubsub.close()
                    except Exception as cleanup_error:
                        self.logger.debug(f"Error cleaning up pubsub during reconnect: {cleanup_error}")
                    pubsub = None
                
                # Exponential backoff with jitter
                backoff = min(MAX_RECONNECT_BACKOFF, backoff * 2 + random.uniform(0, 1))
                await asyncio.sleep(backoff)

    def _validate_snapshot(self, snapshot: PKGSnapshotData) -> None:
        """
        Validate snapshot before activation.
        
        Args:
            snapshot: Snapshot to validate
            
        Raises:
            ValueError: If snapshot is invalid
        """
        if snapshot.engine == 'wasm' and not snapshot.wasm_artifact:
            raise ValueError(f"Snapshot {snapshot.version} has engine 'wasm' but no 'wasm_artifact'.")
        
        if snapshot.engine == 'native' and not snapshot.rules:
            self.logger.warning(f"Snapshot {snapshot.version} has engine 'native' but no rules.")
        
        # Additional validation could include:
        # - Checksum verification
        # - Rule count validation
        # - Test evaluation against fixtures
        
    async def _load_and_activate_snapshot(
        self, 
        snapshot: PKGSnapshotData, 
        source: str = "unknown"
    ):
        """
        The full hot-swap sequence [cite: 51-52].
        
        Fetches, validates, and loads the new snapshot into memory,
        then performs an atomic pointer swap.
        
        Supports multi-version caching for A/B testing and rollback.
        
        Args:
            snapshot: Snapshot data to load
            source: Source of the activation ("startup", "redis", "api", etc.)
        """
        version_id = snapshot.version
        start_time = time.perf_counter()
        
        self.logger.info({
            "event": "snapshot_load_start",
            "version": version_id,
            "source": source,
            "timestamp": time.time()
        })
        
        try:
            # Validate snapshot before loading
            self._validate_snapshot(snapshot)
            
            # 4️⃣ "loads its WASM artifact into a secondary memory buffer"
            self.logger.debug(f"Loading snapshot {version_id} into secondary buffer...")
            
            # PKGEvaluator now accepts PKGSnapshotData directly
            new_evaluator = PKGEvaluator(snapshot)
            
            # 5️⃣ "Validation runs (checksum, test evaluation)"
            # (Validation is done in _validate_snapshot and PKGEvaluator)
            load_duration = time.perf_counter() - start_time
            self.logger.info({
                "event": "snapshot_validated",
                "version": version_id,
                "load_duration_ms": load_duration * 1000,
                "timestamp": time.time()
            })

            # 6️⃣ "Atomic pointer swap"
            load_timestamp = time.time()
            with self._swap_lock:
                old_version = self._active_version
                old_evaluator = self._active_evaluator
                
                # Update multi-version registry (store evaluator with timestamp for LRU eviction)
                self._evaluators[version_id] = (new_evaluator, load_timestamp)
                self._active_version = version_id
                
                # Legacy single evaluator (for backward compatibility)
                self._active_evaluator = new_evaluator
                
                # Manage cache size using LRU eviction (keep last N versions)
                if len(self._evaluators) > MAX_EVALUATOR_CACHE_SIZE:
                    # Remove least recently used (oldest timestamp) non-active evaluator
                    versions_to_remove = [
                        (v, data[1]) for v, data in self._evaluators.items()
                        if v != version_id
                    ]
                    if versions_to_remove:
                        # Sort by timestamp (oldest first) and remove the first one
                        versions_to_remove.sort(key=lambda x: x[1])
                        oldest_version = versions_to_remove[0][0]
                        del self._evaluators[oldest_version]
                        self.logger.debug(
                            f"Removed cached evaluator version {oldest_version} "
                            f"(LRU eviction, cache size limit: {MAX_EVALUATOR_CACHE_SIZE})"
                        )
            
            swap_duration = time.perf_counter() - start_time
            
            # Update status
            self._status["last_activation"] = time.time()
            self._status["healthy"] = True
            self._status["last_error"] = None
            self._status["degraded_mode"] = False
            
            # Structured logging for audit
            if old_evaluator and old_version:
                self.logger.info({
                    "event": "snapshot_activated",
                    "version": version_id,
                    "previous_version": old_version,
                    "source": source,
                    "swap_duration_ms": swap_duration * 1000,
                    "timestamp": time.time()
                })
            else:
                self.logger.info({
                    "event": "snapshot_activated",
                    "version": version_id,
                    "previous_version": None,
                    "source": source,
                    "swap_duration_ms": swap_duration * 1000,
                    "timestamp": time.time()
                })
        
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            self._status["healthy"] = False
            self._status["last_error"] = str(e)
            
            self.logger.error({
                "event": "snapshot_activation_failed",
                "version": version_id,
                "source": source,
                "error": str(e),
                "error_type": type(e).__name__,
                "duration_ms": elapsed * 1000,
                "timestamp": time.time()
            }, exc_info=True)

    # --- Public API ---

    def get_active_evaluator(self) -> Optional[PKGEvaluator]:
        """
        Returns the currently active, thread-safe evaluator instance.
        
        Uses multi-version registry if available, falls back to legacy single evaluator.
        
        Returns:
            The active PKGEvaluator, or None if no policy is loaded.
        """
        # This lock ensures we don't grab the evaluator
        # in the middle of a pointer swap.
        with self._swap_lock:
            if self._active_version and self._active_version in self._evaluators:
                # Extract evaluator from (evaluator, timestamp) tuple
                return self._evaluators[self._active_version][0]
            return self._active_evaluator
    
    def get_evaluator_by_version(self, version: str) -> Optional[PKGEvaluator]:
        """
        Get a cached evaluator by version (for A/B testing or rollback).
        
        Args:
            version: Snapshot version string
            
        Returns:
            The cached PKGEvaluator, or None if not found
        """
        with self._swap_lock:
            cached = self._evaluators.get(version)
            if cached:
                # Extract evaluator from (evaluator, timestamp) tuple
                return cached[0]
            return None
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Returns governance metadata about the active snapshot and manager status.
        """
        with self._swap_lock:
            if self._active_evaluator:
                metadata = {
                    "version": self._active_evaluator.version,
                    "loaded_at": self._active_evaluator.loaded_at,
                    "engine": self._active_evaluator.engine_type,
                    "loaded": True,
                    "error": None,
                    "last_activation": self._status["last_activation"],
                    "cached_versions": list(self._evaluators.keys()),
                    "cache_size": len(self._evaluators),
                    "cache_limit": MAX_EVALUATOR_CACHE_SIZE
                }
            else:
                metadata = {
                    "version": None,
                    "loaded": False,
                    "error": "No active snapshot loaded",
                    "last_activation": self._status["last_activation"],
                    "cached_versions": [],
                    "cache_size": 0
                }
            
            # Add health status
            metadata.update({
                "healthy": self._status["healthy"],
                "degraded_mode": self._status["degraded_mode"],
                "last_error": self._status["last_error"]
            })
            
            return metadata
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Get manager health status for monitoring.
        
        Returns:
            Dictionary with health indicators
        """
        with self._swap_lock:
            return {
                "healthy": self._status["healthy"],
                "degraded_mode": self._status["degraded_mode"],
                "last_error": self._status["last_error"],
                "last_activation": self._status["last_activation"],
                "active_version": self._active_version,
                "cached_versions_count": len(self._evaluators),
                "redis_connected": self._redis_client is not None and self._redis_task and not self._redis_task.done()
            }

# --- Global Instance Management ---

_global_pkg_manager: Optional[PKGManager] = None


def get_global_pkg_manager() -> Optional[PKGManager]:
    """
    Get the global PKG manager instance.
    
    Returns:
        The global PKGManager instance, or None if not initialized.
    """
    return _global_pkg_manager


async def initialize_global_pkg_manager(
    pkg_client: Optional[PKGClient] = None,
    redis_client: Optional[Any] = None
) -> PKGManager:
    """
    Initialize and register the global PKGManager instance.
    
    This should be called once at application startup.
    
    Args:
        pkg_client: An initialized PKGClient instance. If None, creates a new one.
        redis_client: An initialized Redis client. If None, attempts to get from environment.
    
    Returns:
        The initialized PKGManager instance.
    """
    global _global_pkg_manager
    
    if _global_pkg_manager is None:
        logger = logging.getLogger(__name__)
        logger.info("Initializing global PKGManager...")
        
        # Create PKG client if not provided
        if pkg_client is None:
            pkg_client = PKGClient()
    
        # Create Redis client if not provided
        if redis_client is None:
            try:
                import redis.asyncio as aioredis
                import os
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
                redis_client = aioredis.from_url(redis_url, decode_responses=False)
            except ImportError:
                logger.warning("redis.asyncio not available, PKG hot-swap will be disabled")
                redis_client = None
        
        _global_pkg_manager = PKGManager(pkg_client=pkg_client, redis_client=redis_client)
        await _global_pkg_manager.start()
        
        logger.info("Global PKGManager initialized successfully")
    
    return _global_pkg_manager