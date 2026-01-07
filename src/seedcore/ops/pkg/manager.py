#!/usr/bin/env python3
"""
Enhanced Policy Knowledge Graph (PKG) Manager (v2.5)

Manages the lifecycle of active policy snapshots with Semantic Context Hydration.
- Loads initial policy from DB.
- Subscribes to hot-swap events via Redis.
- Provides thread-safe access to the active Evaluator.
- Supports Unified Memory integration for hydrated policy evaluation.
"""

import asyncio
import logging
import time
import threading
from typing import Optional, Dict, Any, Tuple, List

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
    Singleton manager for PKG state and Semantic Context orchestration.
    
    Evolved from a simple "Snapshot Swapper" into a "Semantic Context Orchestrator"
    that bridges Perception (Current Task) with Policy (Historical Context/KG).
    """
    
    def __init__(self, pkg_client: PKGClient, redis_client: Any):
        self._client = pkg_client  # Now used for both Snapshots AND Cortex queries
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
        
        ENHANCEMENT: Injects PKGClient into evaluator for Cortex context access.
        This enables semantic context hydration during policy evaluation.
        """
        version = snapshot.version
        start = time.perf_counter()
        
        try:
            # 1. Create Evaluator (Heavy Operation)
            # This compiles WASM/Rego or loads native rules
            # ENHANCEMENT: Pass the PKGClient to the Evaluator so it can 
            # reach out to the Cortex DAO during hydration.
            new_evaluator = PKGEvaluator(snapshot, pkg_client=self._client)
            
            # 2. Atomic Swap
            with self._swap_lock:
                # Store in cache
                self._evaluators[version] = (new_evaluator, time.time())
                self._active_version = version
                
                # Prune Cache (LRU) - exclude active version from pruning
                if len(self._evaluators) > MAX_EVALUATOR_CACHE_SIZE:
                    candidates = [
                        k for k in self._evaluators.keys() 
                        if k != self._active_version
                    ]
                    if candidates:
                        oldest = min(candidates, key=lambda k: self._evaluators[k][1])
                        del self._evaluators[oldest]
            
            duration = (time.perf_counter() - start) * 1000
            logger.info(f"Activated PKG {version} (src={source}) with Cortex-support in {duration:.1f}ms")
            self._status.update({"healthy": True, "error": None, "version": version})

        except Exception as e:
            logger.error(f"Failed to activate PKG {version}: {e}")
            self._status.update({"healthy": False, "error": str(e)})

    # --- Core Evaluation Chain (The Enhanced Entrypoint) ---

    async def evaluate_task(
        self, 
        task_facts: Dict[str, Any], 
        embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        The primary 'Living System' evaluation entrypoint.
        
        Performs:
        1. Evaluator retrieval (Thread-safe)
        2. Semantic Hydration (Async I/O via Cortex DAO)
        3. Policy Execution (Logic Engine)
        
        Architecture: This bridges Perception (Current Task) with Policy (Historical Context/KG).
        The embedding enables semantic similarity search across Unified Memory, allowing policies
        to make grounded decisions based on historical context.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            embedding: Optional 1024d embedding vector for semantic similarity search.
                      If provided, enables semantic context hydration from Unified Memory.
        
        Returns:
            Policy evaluation result with subtasks, dag, provenance, and snapshot version.
        """
        evaluator = self.get_active_evaluator()
        if not evaluator:
            logger.error("No active PKG evaluator available for task evaluation")
            return {
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "error", "error": "no_active_policy"}],
                "snapshot": None
            }

        # Use the Asynchronous pipeline we built in the Evaluator
        # This performs: Hydration -> Injection -> Execution
        return await evaluator.evaluate_async(task_facts, embedding)

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
                "status": self._status,
                "cortex_enabled": self._client is not None
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