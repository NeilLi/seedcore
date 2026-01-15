#!/usr/bin/env python3
"""
Enhanced Policy Knowledge Graph (PKG) Manager (v2.6)

Manages the lifecycle of active policy snapshots with Semantic Context Hydration.
- Loads initial policy from DB.
- Subscribes to hot-swap events via Redis.
- Provides thread-safe access to the active Evaluator.
- Supports Unified Memory integration for hydrated policy evaluation.

Control PKG Compliance:
- P0: Explicit ok/meta return values (no "empty means fine")
- P0: Mode enforcement (control vs advisory) with hydration blocking
- P0: Strict task_facts schema validation
- P1: Async evaluator creation with thread pool
- P1: Redis reconnection with exponential backoff
- P2: True LRU cache with access tracking
- P2: Snapshot integrity checks (checksum validation)
"""

import asyncio
import hashlib
import logging
import time
import threading
from enum import Enum
from typing import Optional, Dict, Any, Tuple, List
from collections import OrderedDict

# Redis exceptions for better error handling
try:
    import redis.exceptions as redis_exceptions  # pyright: ignore[reportMissingImports]
except ImportError:
    redis_exceptions = None  # type: ignore

# Models
from .evaluator import PKGEvaluator
from .client import PKGClient
from .dao import PKGSnapshotData  # Assuming legacy DAO mapped to new models

logger = logging.getLogger(__name__)

# Constants
PKG_REDIS_CHANNEL = "pkg_updates"
MAX_EVALUATOR_CACHE_SIZE = 3
MAX_RECONNECT_BACKOFF = 60
REDIS_RECONNECT_BASE_DELAY = 1.0
REDIS_RECONNECT_MAX_DELAY = 60.0
REDIS_RECONNECT_MULTIPLIER = 2.0

# P0: Control PKG Mode
class PKGMode(str, Enum):
    """PKG execution mode."""
    CONTROL = "control"  # Strict: deny-by-default, no hydration
    ADVISORY = "advisory"  # Permissive: allows hydration, graceful degradation


# P0: Task Facts Schema (Closed-World Contract)
ALLOWED_TASK_FACTS_KEYS = {
    "tags",  # List[str] - Policy tags
    "signals",  # Dict[str, float] - Signal values (x1..x6)
    "context",  # Dict[str, Any] - Task context (domain, type, task_id, etc.)
    # Note: semantic_context is injected by hydration, not part of input schema
}

class PKGManager:
    """
    Singleton manager for PKG state and Semantic Context orchestration.
    
    Evolved from a simple "Snapshot Swapper" into a "Semantic Context Orchestrator"
    that bridges Perception (Current Task) with Policy (Historical Context/KG).
    
    Control PKG Compliance:
    - Enforces closed-world execution model (strict schema validation)
    - Supports control mode (deny-by-default, no hydration)
    - Provides explicit ok/meta return values
    """
    
    def __init__(
        self, 
        pkg_client: PKGClient, 
        redis_client: Any,
        mode: PKGMode = PKGMode.ADVISORY  # P0: Default to advisory for backward compatibility
    ):
        self._client = pkg_client  # Now used for both Snapshots AND Cortex queries
        self._redis_client = redis_client
        self._mode = mode  # P0: Control vs Advisory mode
        
        # P2: True LRU Cache using OrderedDict
        # OrderedDict maintains insertion order, we move to end on access
        self._evaluators: OrderedDict[str, Tuple[PKGEvaluator, float]] = OrderedDict()
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

    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit."""
        await self.stop()

    # --- Core Logic: Hot Swap ---

    async def _load_and_activate_snapshot(self, snapshot: PKGSnapshotData, source: str):
        """
        Loads a snapshot into memory and atomically swaps it as active.
        
        P2: Validates snapshot integrity (checksum matches artifact).
        P1: Offloads heavy evaluator creation to thread pool.
        
        ENHANCEMENT: Injects PKGClient into evaluator for Cortex context access.
        This enables semantic context hydration during policy evaluation.
        """
        version = snapshot.version
        start = time.perf_counter()
        
        try:
            # P2: Validate snapshot integrity before loading
            integrity_ok, integrity_error = await self._validate_snapshot_integrity(snapshot)
            if not integrity_ok:
                raise ValueError(f"Snapshot integrity check failed: {integrity_error}")
            
            # P1: Offload evaluator creation to thread pool (heavy operation)
            # This compiles WASM/Rego or loads native rules
            # ENHANCEMENT: Pass the PKGClient to the Evaluator so it can 
            # reach out to the Cortex DAO during hydration.
            def _create_evaluator():
                return PKGEvaluator(snapshot, pkg_client=self._client)
            
            new_evaluator = await asyncio.to_thread(_create_evaluator)
            
            # 2. Atomic Swap
            with self._swap_lock:
                # P2: Update LRU cache - move to end if exists, else add
                if version in self._evaluators:
                    # Move to end (most recently used)
                    self._evaluators.move_to_end(version)
                    # Update timestamp
                    self._evaluators[version] = (new_evaluator, time.time())
                else:
                    # Add new entry at end
                    self._evaluators[version] = (new_evaluator, time.time())
                
                self._active_version = version
                
                # P2: Prune Cache (True LRU) - exclude active version from pruning
                # Remove oldest entries (from front) until under limit
                while len(self._evaluators) > MAX_EVALUATOR_CACHE_SIZE:
                    # Get oldest (first) key that's not active
                    oldest_key = None
                    for key in self._evaluators.keys():
                        if key != self._active_version:
                            oldest_key = key
                            break
                    if oldest_key:
                        del self._evaluators[oldest_key]
                    else:
                        break  # Only active version remains
            
            duration = (time.perf_counter() - start) * 1000
            logger.info(f"Activated PKG {version} (src={source}, mode={self._mode.value}) with Cortex-support in {duration:.1f}ms")
            self._status.update({"healthy": True, "error": None, "version": version})

        except Exception as e:
            logger.error(f"Failed to activate PKG {version}: {e}", exc_info=True)
            self._status.update({"healthy": False, "error": str(e)})

    # --- Core Evaluation Chain (The Enhanced Entrypoint) ---

    async def evaluate_task(
        self, 
        task_facts: Dict[str, Any], 
        embedding: Optional[List[float]] = None
    ) -> Dict[str, Any]:
        """
        The primary 'Living System' evaluation entrypoint.
        
        P0: Enforces closed-world execution model with strict schema validation.
        P0: Blocks semantic hydration in CONTROL mode.
        P0: Returns explicit ok/meta instead of "empty means fine".
        
        Performs:
        1. Schema validation (P0: strict allowlist)
        2. Evaluator retrieval (Thread-safe)
        3. Semantic Hydration (P0: blocked in CONTROL mode)
        4. Policy Execution (Logic Engine)
        
        Architecture: This bridges Perception (Current Task) with Policy (Historical Context/KG).
        The embedding enables semantic similarity search across Unified Memory, allowing policies
        to make grounded decisions based on historical context.
        
        Args:
            task_facts: Input facts dictionary with tags, signals, context
            embedding: Optional 1024d embedding vector for semantic similarity search.
                      If provided, enables semantic context hydration from Unified Memory.
                      P0: Ignored in CONTROL mode.
        
        Returns:
            Dictionary with:
            - ok: bool - Explicit success/failure status (P0)
            - meta: Dict[str, Any] - Metadata (mode, version, hydration_blocked, etc.)
            - subtasks: List[Dict] - Policy output subtasks (empty if ok=False)
            - dag: List[Dict] - DAG edges
            - rules: List[Dict] - Rule provenance
            - snapshot: str - Snapshot version used
        """
        # P0: Validate task_facts schema (closed-world contract)
        validation_error = self._validate_task_facts(task_facts)
        if validation_error:
            logger.error(f"Task facts validation failed: {validation_error}")
            return {
                "ok": False,
                "meta": {
                    "error": validation_error,
                    "mode": self._mode.value,
                    "version": None,
                    "hydration_blocked": False,
                },
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "validation_error", "error": validation_error}],
                "snapshot": None
            }
        
        evaluator = self.get_active_evaluator()
        if not evaluator:
            logger.error("No active PKG evaluator available for task evaluation")
            return {
                "ok": False,
                "meta": {
                    "error": "no_active_policy",
                    "mode": self._mode.value,
                    "version": None,
                    "hydration_blocked": False,
                },
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "error", "error": "no_active_policy"}],
                "snapshot": None
            }

        # P0: Block hydration in CONTROL mode
        hydration_blocked = False
        if self._mode == PKGMode.CONTROL:
            if embedding is not None:
                logger.debug("[PKG] Hydration blocked in CONTROL mode (embedding provided but ignored)")
                hydration_blocked = True
            # Force embedding to None to prevent hydration
            embedding = None

        # Use the Asynchronous pipeline we built in the Evaluator
        # This performs: Hydration -> Injection -> Execution (hydration skipped in CONTROL mode)
        try:
            result = await evaluator.evaluate_async(task_facts, embedding)
            
            # P0: Convert to explicit ok/meta format
            # Empty subtasks means DENY in CONTROL mode, but may be OK in ADVISORY mode
            subtasks = result.get("subtasks", [])
            has_subtasks = len(subtasks) > 0
            
            # P0: In CONTROL mode, empty subtasks = explicit deny (ok=False)
            # In ADVISORY mode, empty subtasks = no-op (ok=True, but no work to do)
            ok = True
            if self._mode == PKGMode.CONTROL and not has_subtasks:
                ok = False
                logger.debug("[PKG] CONTROL mode: empty subtasks = explicit deny")
            
            return {
                "ok": ok,
                "meta": {
                    "mode": self._mode.value,
                    "version": result.get("snapshot"),
                    "hydration_blocked": hydration_blocked,
                    "has_subtasks": has_subtasks,
                    "subtasks_count": len(subtasks),
                    "rules_matched": len(result.get("rules", [])),
                },
                "subtasks": subtasks,
                "dag": result.get("dag", []),
                "rules": result.get("rules", []),
                "snapshot": result.get("snapshot")
            }
        except Exception as e:
            logger.error(f"PKG evaluation failed: {e}", exc_info=True)
            return {
                "ok": False,
                "meta": {
                    "error": str(e),
                    "mode": self._mode.value,
                    "version": evaluator.version if evaluator else None,
                    "hydration_blocked": hydration_blocked,
                },
                "subtasks": [],
                "dag": [],
                "rules": [{"rule_id": "evaluation_error", "error": str(e), "error_type": type(e).__name__}],
                "snapshot": evaluator.version if evaluator else None
            }

    # --- Public Accessors ---

    def get_active_evaluator(self) -> Optional[PKGEvaluator]:
        """
        Thread-safe access to the current policy engine.
        
        P2: Updates LRU cache access time (moves to end of OrderedDict).
        """
        with self._swap_lock:
            if self._active_version and self._active_version in self._evaluators:
                evaluator, _ = self._evaluators[self._active_version]
                # P2: Update access time (move to end for LRU)
                self._evaluators.move_to_end(self._active_version)
                self._evaluators[self._active_version] = (evaluator, time.time())
                return evaluator
            return None

    def get_evaluator_by_version(self, version: str) -> Optional[PKGEvaluator]:
        """
        Thread-safe access to a specific evaluator by version.
        
        P2: Updates LRU cache access time (moves to end of OrderedDict).
        
        Args:
            version: Snapshot version string
            
        Returns:
            PKGEvaluator if found, None otherwise
        """
        with self._swap_lock:
            entry = self._evaluators.get(version)
            if not entry:
                return None
            
            evaluator, _ = entry
            # P2: Update access time (move to end for LRU)
            self._evaluators.move_to_end(version)
            self._evaluators[version] = (evaluator, time.time())
            return evaluator

    def get_metadata(self) -> Dict[str, Any]:
        """Operational metadata for /status endpoints."""
        with self._swap_lock:
            return {
                "active_version": self._active_version,
                "cached_versions": list(self._evaluators.keys()),
                "cache_size": len(self._evaluators),
                "status": self._status,
                "mode": self._mode.value,
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
        """
        Subscribe to updates with exponential backoff reconnection.
        
        P1: Implements exponential backoff reconnection loop.
        """
        if self._redis_client is None:
            logger.warning("Redis client is None; PKG hot-swap listener disabled")
            return
        
        backoff_delay = REDIS_RECONNECT_BASE_DELAY
        
        while True:
            try:
                pubsub = self._redis_client.pubsub()
                if pubsub is None:
                    raise ValueError("Redis pubsub() returned None")
                await pubsub.subscribe(PKG_REDIS_CHANNEL)
                
                # Reset backoff on successful connection
                backoff_delay = REDIS_RECONNECT_BASE_DELAY
                logger.info(f"Redis listener connected to channel {PKG_REDIS_CHANNEL}")
                
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
                except asyncio.CancelledError:
                    # Normal shutdown
                    raise
                except (TimeoutError, ConnectionError, OSError) as e:
                    # Network/timeout errors - reconnect
                    logger.warning(f"Redis listener connection error (will reconnect): {e}")
                    # Break inner loop to reconnect
                    break
                except Exception as e:
                    # Check if it's a Redis-specific timeout error
                    if redis_exceptions and isinstance(e, redis_exceptions.TimeoutError):
                        logger.warning(f"Redis timeout error (will reconnect): {e}")
                    else:
                        logger.error(f"Redis listener error: {e}", exc_info=True)
                    # Break inner loop to reconnect
                    break
                finally:
                    try:
                        await pubsub.close()
                    except Exception:
                        pass
                        
            except asyncio.CancelledError:
                # Normal shutdown
                logger.info("Redis listener cancelled")
                break
            except Exception as e:
                logger.error(f"Redis connection failed: {e}. Reconnecting in {backoff_delay:.1f}s...", exc_info=True)
                await asyncio.sleep(backoff_delay)
                # Exponential backoff with max cap
                backoff_delay = min(
                    backoff_delay * REDIS_RECONNECT_MULTIPLIER,
                    REDIS_RECONNECT_MAX_DELAY
                )
    
    # --- P0: Schema Validation ---
    
    def _validate_task_facts(self, task_facts: Dict[str, Any]) -> Optional[str]:
        """
        Validate task_facts against closed-world schema.
        
        P0: Enforces strict allowlist - only declared inputs exist.
        This is critical for control PKG safety.
        
        Args:
            task_facts: Input facts dictionary
            
        Returns:
            None if valid, error message if invalid
        """
        if not isinstance(task_facts, dict):
            return f"task_facts must be a dict, got {type(task_facts).__name__}"
        
        # Check for unknown keys (closed-world enforcement)
        unknown_keys = set(task_facts.keys()) - ALLOWED_TASK_FACTS_KEYS
        if unknown_keys:
            return f"Unknown keys in task_facts: {unknown_keys}. Allowed keys: {ALLOWED_TASK_FACTS_KEYS}"
        
        # Validate tags
        if "tags" in task_facts:
            if not isinstance(task_facts["tags"], list):
                return f"tags must be a list, got {type(task_facts['tags']).__name__}"
            if not all(isinstance(tag, str) for tag in task_facts["tags"]):
                return "tags must be a list of strings"
        
        # Validate signals
        if "signals" in task_facts:
            if not isinstance(task_facts["signals"], dict):
                return f"signals must be a dict, got {type(task_facts['signals']).__name__}"
            if not all(isinstance(k, str) and isinstance(v, (int, float)) 
                      for k, v in task_facts["signals"].items()):
                return "signals must be a dict[str, float]"
        
        # Validate context
        if "context" in task_facts:
            if not isinstance(task_facts["context"], dict):
                return f"context must be a dict, got {type(task_facts['context']).__name__}"
        
        return None  # Valid
    
    # --- P2: Integrity Validation ---
    
    async def _validate_snapshot_integrity(self, snapshot: PKGSnapshotData) -> Tuple[bool, Optional[str]]:
        """
        Validate snapshot integrity by verifying checksum matches artifact.
        
        P2: Ensures WASM/rules bundle matches declared checksum.
        This prevents tampering and ensures replayability.
        
        Args:
            snapshot: PKGSnapshotData to validate
            
        Returns:
            (is_valid, error_message)
        """
        if not snapshot.checksum:
            return False, "Snapshot missing checksum"
        
        if len(snapshot.checksum) != 64:
            return False, f"Invalid checksum length: {len(snapshot.checksum)} (expected 64)"
        
        try:
            if snapshot.engine == "wasm":
                if not snapshot.wasm_artifact:
                    return False, "WASM snapshot missing artifact"
                
                # Calculate SHA256 of WASM bytes
                calculated_checksum = hashlib.sha256(snapshot.wasm_artifact).hexdigest()
                
                if calculated_checksum != snapshot.checksum:
                    return False, (
                        f"Checksum mismatch: calculated {calculated_checksum[:16]}... "
                        f"but snapshot has {snapshot.checksum[:16]}..."
                    )
                
                logger.debug(f"WASM checksum validated: {snapshot.checksum[:16]}...")
                
            elif snapshot.engine == "native":
                # For native rules, we need to validate the rules bundle
                # Serialize rules to JSON and hash
                import json
                rules_json = json.dumps(
                    snapshot.rules or [],
                    sort_keys=True,  # Deterministic ordering
                    default=str  # Handle non-serializable values
                ).encode('utf-8')
                
                calculated_checksum = hashlib.sha256(rules_json).hexdigest()
                
                if calculated_checksum != snapshot.checksum:
                    return False, (
                        f"Native rules checksum mismatch: calculated {calculated_checksum[:16]}... "
                        f"but snapshot has {snapshot.checksum[:16]}..."
                    )
                
                logger.debug(f"Native rules checksum validated: {snapshot.checksum[:16]}...")
            else:
                return False, f"Unknown engine type: {snapshot.engine}"
            
            return True, None
            
        except Exception as e:
            return False, f"Integrity check failed: {e}"

# --- Global Singleton ---
_global_manager: Optional[PKGManager] = None

async def initialize_global_pkg_manager(
    pkg_client, 
    redis_client, 
    mode: PKGMode = PKGMode.ADVISORY
) -> PKGManager:
    """
    Initialize global PKG manager singleton.
    
    Args:
        pkg_client: PKGClient instance
        redis_client: Redis client instance
        mode: PKG execution mode (CONTROL or ADVISORY)
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = PKGManager(pkg_client, redis_client, mode=mode)
        await _global_manager.start()
    return _global_manager

def get_global_pkg_manager() -> Optional[PKGManager]:
    return _global_manager