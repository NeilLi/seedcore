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
import copy
import hashlib
import json
import logging
import os
import time
import threading
from datetime import datetime, timezone
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
from .capability_registry import CapabilityRegistry
from .authz_graph import AuthzGraphManager, AuthzGraphProjectionService
from .rct_publish_validation import gather_rct_publish_validation_errors

logger = logging.getLogger(__name__)

# Constants
PKG_REDIS_CHANNEL = "pkg_updates"
PKG_UPDATE_ACTIVATE_KIND = "activate"
PKG_UPDATE_AUTHZ_REFRESH_KIND = "authz_graph_refresh"
MAX_EVALUATOR_CACHE_SIZE = 3
MAX_RECONNECT_BACKOFF = 60
REDIS_RECONNECT_BASE_DELAY = 1.0
REDIS_RECONNECT_MAX_DELAY = 60.0
REDIS_RECONNECT_MULTIPLIER = 2.0

# Phase 3 (RCT publish-time validation): set SEEDCORE_PKG_RCT_PUBLISH_VALIDATE=1 to block
# activate_snapshot_version until compiled graph, manifest row, taxonomies, and typed
# transition_requirements pass authoring checks (dry-run compile; does not swap runtime).

# Phase 2 (RCT activation hardening): set SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE=1 to fail closed
# when the compiled graph is not RCT-ready, contract artifacts are incomplete, the snapshot
# manifest row is missing, or snapshot-scoped taxonomies are empty. Optional
# SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT=1 requires an existing pkg_snapshot_manifests row
# before authz graph compilation (strict publish-time contract).

def _pkg_env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


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
        mode: PKGMode = PKGMode.CONTROL,
        authz_graph_manager: Optional[AuthzGraphManager] = None,
    ):
        self._client = pkg_client  # Now used for both Snapshots AND Cortex queries
        self._redis_client = redis_client
        self._mode = mode  # P0: Control vs Advisory mode

        # Capability registry (DNA -> executor hints)
        # Refreshed on snapshot activation (startup + hot-swap).
        self.capabilities = CapabilityRegistry(pkg_client)
        self.authz_graph = authz_graph_manager or AuthzGraphManager(
            AuthzGraphProjectionService(
                pkg_client=pkg_client,
                session_factory=getattr(pkg_client, "_sf", None),
            )
        )
        
        # P2: True LRU Cache using OrderedDict
        # OrderedDict maintains insertion order, we move to end on access
        self._evaluators: OrderedDict[str, Tuple[PKGEvaluator, float]] = OrderedDict()
        self._active_version: Optional[str] = None
        
        # Lock for atomic swaps
        self._swap_lock = threading.Lock()
        
        # Async task tracking
        self._redis_task: Optional[asyncio.Task] = None
        self._status = {"healthy": False, "error": None, "version": None}
        self._active_contract_artifacts: Dict[str, Any] = {}

    def _rct_activation_enforce_enabled(self) -> bool:
        return _pkg_env_truthy("SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE")

    def _rct_activation_preflight_manifest_enabled(self) -> bool:
        return _pkg_env_truthy("SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT")

    def _rct_publish_validate_enabled(self) -> bool:
        return _pkg_env_truthy("SEEDCORE_PKG_RCT_PUBLISH_VALIDATE")

    def _rollback_pkg_activation_swap(
        self, version: str, prior_active_version: Optional[str]
    ) -> None:
        """Revert active evaluator swap (Phase-2 hardening failure path)."""
        with self._swap_lock:
            self._evaluators.pop(version, None)
            self._active_version = prior_active_version
            self._active_contract_artifacts = {}

    async def _validate_rct_activation_phase2_postflight(
        self,
        *,
        snapshot_id: int,
        compiled_authz_index: Optional[Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Phase-2 activation checks (pkg_snapshot_rct_alignment_research.md):
        compiled graph RCT-ready, contract artifacts persisted, manifest row present,
        snapshot-scoped taxonomies non-empty.
        """
        if not self._rct_activation_enforce_enabled():
            return True, None
        errors: List[str] = []
        if compiled_authz_index is None:
            errors.append("compiled_authz_index_missing")
        else:
            if not bool(getattr(compiled_authz_index, "restricted_transfer_ready", False)):
                errors.append("restricted_transfer_ready_false")
            if getattr(compiled_authz_index, "decision_graph_snapshot", None) is None:
                errors.append("decision_graph_snapshot_missing")
        try:
            rows = await self._client.list_snapshot_artifacts(snapshot_id)
        except Exception as e:
            errors.append(f"list_snapshot_artifacts_error:{e}")
            rows = []
        types_found = {str(r.get("artifact_type") or "") for r in (rows or [])}
        required_types = {
            "decision_graph_snapshot",
            "request_schema_bundle",
            "taxonomy_bundle",
            "activation_manifest",
        }
        missing = required_types - types_found
        if missing:
            errors.append(f"missing_artifacts:{sorted(missing)}")
        try:
            manifest_row = await self._client.get_snapshot_manifest(snapshot_id)
        except Exception as e:
            errors.append(f"get_snapshot_manifest_error:{e}")
            manifest_row = None
        if not manifest_row:
            errors.append("snapshot_manifest_missing")
        try:
            tax = await self._client.get_taxonomy_bundle(snapshot_id)
        except Exception as e:
            errors.append(f"get_taxonomy_bundle_error:{e}")
            tax = {}
        if not isinstance(tax, dict):
            tax = {}
        if not (tax.get("reason_codes") or []):
            errors.append("taxonomy_reason_codes_empty")
        if not (tax.get("trust_gap_codes") or []):
            errors.append("taxonomy_trust_gap_codes_empty")
        if not (tax.get("obligation_codes") or []):
            errors.append("taxonomy_obligation_codes_empty")
        if errors:
            return False, "; ".join(errors)
        return True, None

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
                # In ADVISORY mode, warn but continue (allows recovery from checksum mismatches)
                # In CONTROL mode, fail strictly (security requirement)
                if self._mode == PKGMode.ADVISORY:
                    logger.warning(
                        f"Snapshot integrity check failed for {version} (ADVISORY mode - continuing): {integrity_error}. "
                        f"Consider updating the checksum in the database to match the calculated value."
                    )
                else:
                    # CONTROL mode: strict enforcement
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
                prior_active_version = self._active_version
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

            # 3. Refresh capability registry outside the swap lock (async I/O)
            # This keeps snapshot activation fast and avoids blocking readers.
            try:
                await self.capabilities.refresh(snapshot.id)
            except Exception as e:
                logger.warning(
                    "CapabilityRegistry refresh failed for snapshot_id=%s: %s",
                    snapshot.id,
                    e,
                )

            if self._rct_activation_preflight_manifest_enabled():
                preflight_manifest: Optional[Dict[str, Any]] = None
                preflight_err: Optional[Exception] = None
                try:
                    preflight_manifest = await self._client.get_snapshot_manifest(snapshot.id)
                except Exception as e:
                    preflight_err = e
                if preflight_err is not None:
                    if self._mode == PKGMode.CONTROL:
                        self._rollback_pkg_activation_swap(version, prior_active_version)
                        raise ValueError(
                            f"PKG RCT activation preflight failed for {version}: "
                            f"could not load pkg_snapshot_manifests ({preflight_err})"
                        ) from preflight_err
                    logger.warning(
                        "PKG RCT preflight: get_snapshot_manifest failed (ADVISORY): %s",
                        preflight_err,
                    )
                elif not preflight_manifest:
                    msg = (
                        f"PKG RCT activation preflight failed for {version}: "
                        "pkg_snapshot_manifests row required when "
                        "SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT is enabled"
                    )
                    if self._mode == PKGMode.CONTROL:
                        self._rollback_pkg_activation_swap(version, prior_active_version)
                        raise ValueError(msg)
                    logger.warning("%s (ADVISORY mode: continuing)", msg)

            compiled_authz_index = None
            try:
                compiled_authz_index = await self.authz_graph.activate_snapshot(
                    snapshot_id=snapshot.id,
                    snapshot_version=snapshot.version,
                    snapshot_ref=f"authz_graph@{snapshot.version}",
                )
            except Exception as e:
                logger.warning(
                    "AuthzGraph activation failed for snapshot_id=%s version=%s: %s",
                    snapshot.id,
                    snapshot.version,
                    e,
                    exc_info=True,
                )
            active_contract_artifacts: Dict[str, Any] = {}
            if compiled_authz_index is not None:
                persisted = await self._persist_compiled_authz_artifacts(
                    snapshot_id=snapshot.id,
                    snapshot_version=snapshot.version,
                    compiled_authz_index=compiled_authz_index,
                )
                if isinstance(persisted, dict):
                    active_contract_artifacts = persisted

            ok_phase2, err_phase2 = await self._validate_rct_activation_phase2_postflight(
                snapshot_id=snapshot.id,
                compiled_authz_index=compiled_authz_index,
            )
            if self._rct_activation_enforce_enabled():
                if self._mode == PKGMode.CONTROL and not ok_phase2:
                    self._rollback_pkg_activation_swap(version, prior_active_version)
                    raise ValueError(
                        f"PKG RCT Phase-2 activation hardening failed: {err_phase2}"
                    )
                if self._mode == PKGMode.ADVISORY and not ok_phase2:
                    logger.warning(
                        "PKG RCT Phase-2 activation hardening (ADVISORY): %s", err_phase2
                    )
            if isinstance(active_contract_artifacts, dict):
                should_cache_contracts = (
                    not self._rct_activation_enforce_enabled()
                    or ok_phase2
                    or self._mode == PKGMode.ADVISORY
                )
                if should_cache_contracts:
                    with self._swap_lock:
                        self._active_contract_artifacts = copy.deepcopy(active_contract_artifacts)
            
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
        embedding: Optional[List[float]] = None,
        mode: Optional[PKGMode] = None
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
        
        effective_mode = mode if mode is not None else self._mode
        
        evaluator = self.get_active_evaluator()
        if not evaluator:
            logger.error("No active PKG evaluator available for task evaluation")
            return {
                "ok": False,
                "meta": {
                    "error": "no_active_policy",
                    "mode": effective_mode.value,
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
        if effective_mode == PKGMode.CONTROL:
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
            error_code: Optional[str] = None
            deny_reason: Optional[str] = None
            if effective_mode == PKGMode.CONTROL and not has_subtasks:
                ok = False
                error_code = "policy_denied"
                deny_reason = "control_mode_empty_subtasks"
                logger.debug("[PKG] CONTROL mode: empty subtasks = explicit deny")
            
            return {
                "ok": ok,
                "meta": {
                    "error": error_code,
                    "deny_reason": deny_reason,
                    "mode": effective_mode.value,
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
                "cortex_enabled": self._client is not None,
                "authz_graph": self.authz_graph.get_status(),
            }

    def get_active_contract_artifacts(self) -> Dict[str, Any]:
        """Return the active snapshot contract artifacts cached during activation."""
        with self._swap_lock:
            return copy.deepcopy(self._active_contract_artifacts)

    def get_active_request_schema_bundle(self) -> Dict[str, Any]:
        """Return the active request schema bundle if it has been published."""
        bundle = self.get_active_contract_artifacts().get("request_schema_bundle")
        return bundle if isinstance(bundle, dict) else {}

    def get_active_taxonomy_bundle(self) -> Dict[str, Any]:
        """Return the active taxonomy bundle if it has been published."""
        bundle = self.get_active_contract_artifacts().get("taxonomy_bundle")
        return bundle if isinstance(bundle, dict) else {}

    def get_active_compiled_authz_index(self):
        return self.authz_graph.get_active_compiled_index()

    async def refresh_active_authz_graph(self) -> Dict[str, Any]:
        with self._swap_lock:
            active_version = self._active_version
            evaluator_entry = self._evaluators.get(active_version) if active_version else None
        if not active_version or evaluator_entry is None:
            return {
                "success": False,
                "message": "No active PKG snapshot available for authz graph refresh",
                "error": "no_active_snapshot",
            }
        evaluator, _ = evaluator_entry
        snapshot_id = getattr(evaluator, "snapshot_id", None)
        if snapshot_id is None:
            return {
                "success": False,
                "message": f"Active evaluator for {active_version} is missing snapshot_id",
                "error": "missing_snapshot_id",
                "version": active_version,
            }
        try:
            compiled = await self.authz_graph.activate_snapshot(
                snapshot_id=snapshot_id,
                snapshot_version=active_version,
                snapshot_ref=f"authz_graph@{active_version}",
            )
            active_contract_artifacts = await self._persist_compiled_authz_artifacts(
                snapshot_id=snapshot_id,
                snapshot_version=active_version,
                compiled_authz_index=compiled,
            )
            if not isinstance(active_contract_artifacts, dict):
                active_contract_artifacts = {}
            ok_phase2, err_phase2 = await self._validate_rct_activation_phase2_postflight(
                snapshot_id=snapshot_id,
                compiled_authz_index=compiled,
            )
            if self._rct_activation_enforce_enabled():
                if self._mode == PKGMode.CONTROL and not ok_phase2:
                    logger.error(
                        "Authz graph refresh rejected by RCT Phase-2 hardening: %s",
                        err_phase2,
                    )
                    return {
                        "success": False,
                        "message": f"RCT Phase-2 activation hardening failed for {active_version}",
                        "error": err_phase2 or "phase2_activation_failed",
                        "version": active_version,
                        "snapshot_id": snapshot_id,
                    }
                if self._mode == PKGMode.ADVISORY and not ok_phase2:
                    logger.warning(
                        "Authz graph refresh: RCT Phase-2 hardening (ADVISORY): %s", err_phase2
                    )
            should_cache = (
                not self._rct_activation_enforce_enabled()
                or ok_phase2
                or self._mode == PKGMode.ADVISORY
            )
            if should_cache and isinstance(active_contract_artifacts, dict):
                with self._swap_lock:
                    self._active_contract_artifacts = copy.deepcopy(active_contract_artifacts)
            return {
                "success": True,
                "message": f"Successfully refreshed authz graph for {active_version}",
                "version": active_version,
                "snapshot_id": snapshot_id,
                "snapshot_hash": compiled.snapshot_hash,
                "compiled_at": compiled.compiled_at,
                "restricted_transfer_ready": compiled.restricted_transfer_ready,
            }
        except Exception as e:
            logger.error("Active authz graph refresh failed for %s: %s", active_version, e, exc_info=True)
            return {
                "success": False,
                "message": f"Failed to refresh authz graph for {active_version}: {e}",
                "error": str(e),
                "version": active_version,
                "snapshot_id": snapshot_id,
            }

    async def _persist_compiled_authz_artifacts(
        self,
        *,
        snapshot_id: int,
        snapshot_version: str,
        compiled_authz_index: Any,
    ) -> Dict[str, Any]:
        """
        Additive Phase 1 persistence: store compiled decision graph artifacts
        without changing activation/decision behavior.
        """
        try:
            decision_graph_snapshot = getattr(compiled_authz_index, "decision_graph_snapshot", None)
            if decision_graph_snapshot is None:
                return {}
            decision_graph_payload = (
                decision_graph_snapshot.to_dict()
                if hasattr(decision_graph_snapshot, "to_dict")
                else dict(decision_graph_snapshot)
            )
            decision_graph_artifact = await self._client.store_snapshot_artifact_json(
                snapshot_id=snapshot_id,
                artifact_type="decision_graph_snapshot",
                payload=decision_graph_payload,
                created_by="pkg_manager",
            )
            request_schema_payload = await self._build_request_schema_bundle(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
            )
            request_schema_artifact = await self._client.store_snapshot_artifact_json(
                snapshot_id=snapshot_id,
                artifact_type="request_schema_bundle",
                payload=request_schema_payload,
                created_by="pkg_manager",
            )
            taxonomy_payload = await self._build_taxonomy_bundle(
                snapshot_id=snapshot_id,
                snapshot_version=snapshot_version,
                decision_graph_payload=decision_graph_payload,
            )
            taxonomy_artifact = await self._client.store_snapshot_artifact_json(
                snapshot_id=snapshot_id,
                artifact_type="taxonomy_bundle",
                payload=taxonomy_payload,
                created_by="pkg_manager",
            )
            activation_payload = {
                "snapshot_id": snapshot_id,
                "snapshot_version": snapshot_version,
                "compiled_at": getattr(compiled_authz_index, "compiled_at", None),
                "snapshot_hash": getattr(compiled_authz_index, "snapshot_hash", None),
                "restricted_transfer_ready": bool(
                    getattr(compiled_authz_index, "restricted_transfer_ready", False)
                ),
                "hot_path_workflow": decision_graph_payload.get("hot_path_workflow"),
                "trust_gap_taxonomy": list(decision_graph_payload.get("trust_gap_taxonomy") or []),
                "decision_graph_snapshot": {
                    "artifact_type": "decision_graph_snapshot",
                    "sha256": decision_graph_artifact.get("sha256"),
                    "size_bytes": decision_graph_artifact.get("size_bytes"),
                },
                "request_schema_bundle": {
                    "artifact_type": "request_schema_bundle",
                    "sha256": request_schema_artifact.get("sha256"),
                    "size_bytes": request_schema_artifact.get("size_bytes"),
                },
                "taxonomy_bundle": {
                    "artifact_type": "taxonomy_bundle",
                    "sha256": taxonomy_artifact.get("sha256"),
                    "size_bytes": taxonomy_artifact.get("size_bytes"),
                },
                "shadow_only": True,
            }
            activation_artifact = await self._client.store_snapshot_artifact_json(
                snapshot_id=snapshot_id,
                artifact_type="activation_manifest",
                payload=activation_payload,
                created_by="pkg_manager",
            )
            manifest_payload = {
                "snapshot_id": snapshot_id,
                "snapshot_version": snapshot_version,
                "workflow_type": "restricted_custody_transfer",
                "decision_contract_version": snapshot_version,
                "request_schema_version": snapshot_version,
                "evidence_contract_version": snapshot_version,
                "reason_code_taxonomy_version": snapshot_version,
                "trust_gap_taxonomy_version": snapshot_version,
                "obligation_taxonomy_version": snapshot_version,
                "consistency_contract_version": snapshot_version,
                "safety_profile": "shadow_only_phase1",
                "requires_signed_bundle": False,
                "requires_compiled_decision_graph": bool(decision_graph_payload),
                "requires_authority_state_binding": False,
                "activation_requirements": {
                    "shadow_only": True,
                    "compiled_authz_snapshot_hash": getattr(compiled_authz_index, "snapshot_hash", None),
                    "decision_graph_snapshot_sha256": decision_graph_artifact.get("sha256"),
                    "request_schema_bundle_sha256": request_schema_artifact.get("sha256"),
                    "taxonomy_bundle_sha256": taxonomy_artifact.get("sha256"),
                    "activation_manifest_sha256": activation_artifact.get("sha256"),
                },
                "manifest_json": {
                    "activation_manifest": activation_payload,
                    "artifacts": {
                        "decision_graph_snapshot": decision_graph_artifact,
                        "request_schema_bundle": request_schema_artifact,
                        "taxonomy_bundle": taxonomy_artifact,
                        "activation_manifest": activation_artifact,
                    },
                },
            }
            await self._client.upsert_snapshot_manifest(
                snapshot_id=snapshot_id,
                workflow_type="restricted_custody_transfer",
                decision_contract_version=snapshot_version,
                request_schema_version=snapshot_version,
                evidence_contract_version=snapshot_version,
                reason_code_taxonomy_version=snapshot_version,
                trust_gap_taxonomy_version=snapshot_version,
                obligation_taxonomy_version=snapshot_version,
                consistency_contract_version=snapshot_version,
                safety_profile="shadow_only_phase1",
                requires_signed_bundle=False,
                requires_compiled_decision_graph=True,
                requires_authority_state_binding=False,
                activation_requirements=manifest_payload["activation_requirements"],
                manifest_json=manifest_payload,
            )
            return {
                "decision_graph_snapshot": decision_graph_payload,
                "request_schema_bundle": request_schema_payload,
                "taxonomy_bundle": taxonomy_payload,
                "activation_manifest": activation_payload,
            }
        except Exception as e:
            logger.warning(
                "Failed to persist compiled authz artifacts for snapshot_id=%s version=%s: %s",
                snapshot_id,
                snapshot_version,
                e,
                exc_info=True,
            )
            return {}

    async def _build_request_schema_bundle(
        self,
        *,
        snapshot_id: int,
        snapshot_version: str,
    ) -> Dict[str, Any]:
        capabilities = list(self.capabilities.list_capabilities())
        if not capabilities and hasattr(self._client, "get_subtask_types"):
            try:
                rows = await self._client.get_subtask_types(snapshot_id)
            except Exception:
                rows = []
            if not isinstance(rows, list):
                rows = []
            capabilities = [
                {
                    "id": row.get("id"),
                    "name": row.get("name"),
                    "snapshot_id": row.get("snapshot_id", snapshot_id),
                    "default_params": row.get("default_params") or {},
                }
                for row in rows or []
                if isinstance(row, dict) and str(row.get("name") or "").strip()
            ]
        normalized_caps: List[Dict[str, Any]] = []
        for cap in capabilities:
            if isinstance(cap, dict):
                name = str(cap.get("name") or "").strip()
                cap_id = cap.get("subtask_type_id") or cap.get("id")
                default_params = dict(cap.get("default_params") or {})
                cap_snapshot_id = cap.get("snapshot_id") or snapshot_id
            else:
                name = str(getattr(cap, "name", "") or "").strip()
                cap_id = getattr(cap, "subtask_type_id", None)
                default_params = dict(getattr(cap, "default_params", {}) or {})
                cap_snapshot_id = getattr(cap, "snapshot_id", snapshot_id)
            if not name:
                continue
            normalized_caps.append(
                {
                    "id": str(cap_id) if cap_id is not None else None,
                    "name": name,
                    "snapshot_id": cap_snapshot_id,
                    "default_params": default_params,
                    "routing_hints": self.capabilities.get_routing_hints(name),
                    "executor_config": self.capabilities.get_executor_config(name),
                }
            )
        return {
            "artifact_type": "request_schema_bundle",
            "snapshot_id": snapshot_id,
            "snapshot_version": snapshot_version,
            "workflow_type": "restricted_custody_transfer",
            "request_shape": {
                "required_task_fact_keys": sorted(ALLOWED_TASK_FACTS_KEYS),
                "injected_task_fact_keys": ["semantic_context"],
            },
            "capabilities": normalized_caps,
            "capability_count": len(normalized_caps),
            "shadow_only": True,
        }

    async def _build_taxonomy_bundle(
        self,
        *,
        snapshot_id: int,
        snapshot_version: str,
        decision_graph_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        taxonomy_rows: Dict[str, List[Dict[str, Any]]] = {}
        if hasattr(self._client, "get_taxonomy_bundle"):
            try:
                raw_bundle = await self._client.get_taxonomy_bundle(snapshot_id=snapshot_id)
            except Exception:
                raw_bundle = {}
            if isinstance(raw_bundle, dict):
                taxonomy_rows = raw_bundle
        return {
            "artifact_type": "taxonomy_bundle",
            "snapshot_id": snapshot_id,
            "snapshot_version": snapshot_version,
            "workflow_type": "restricted_custody_transfer",
            "decision_graph_snapshot": {
                "snapshot_hash": decision_graph_payload.get("snapshot_hash"),
                "hot_path_workflow": decision_graph_payload.get("hot_path_workflow"),
                "trust_gap_taxonomy": list(decision_graph_payload.get("trust_gap_taxonomy") or []),
            },
            "reason_codes": list(taxonomy_rows.get("reason_codes") or []),
            "trust_gap_codes": list(taxonomy_rows.get("trust_gap_codes") or []),
            "obligation_codes": list(taxonomy_rows.get("obligation_codes") or []),
            "shadow_only": True,
        }
    
    async def reload_active_snapshot(self) -> Dict[str, Any]:
        """
        Manually reload the active snapshot from the database.
        
        Useful for debugging or recovering from load failures.
        Clears the snapshot cache to force a fresh load from the database.
        Returns a dictionary with success status and details.
        """
        try:
            # Clear the snapshot cache to force fresh load
            if hasattr(self._client, 'snapshots') and hasattr(self._client.snapshots, '_cached_snapshot'):
                logger.info("Clearing snapshot cache to force fresh reload")
                self._client.snapshots._cached_snapshot = None
                self._client.snapshots._cached_snapshot_id = None
                self._client.snapshots._cached_snapshot_checksum = None
            
            snap = await self._client.get_active_snapshot()
            if snap:
                logger.info(f"Reloading active snapshot: {snap.version} (id={snap.id})")
                await self._load_and_activate_snapshot(snap, source="manual_reload")
                evaluator = self.get_active_evaluator()
                if evaluator:
                    return {
                        "success": True,
                        "message": f"Successfully reloaded snapshot {snap.version}",
                        "version": snap.version,
                        "snapshot_id": snap.id,
                    }
                else:
                    return {
                        "success": False,
                        "message": "Snapshot loaded but evaluator creation failed",
                        "version": snap.version,
                        "snapshot_id": snap.id,
                        "error": self._status.get("error"),
                    }
            else:
                return {
                    "success": False,
                    "message": "No active snapshot found in database",
                    "error": "No active snapshot",
                }
        except Exception as e:
            logger.error(f"Manual snapshot reload failed: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to reload snapshot: {str(e)}",
                "error": str(e),
            }

    async def activate_snapshot_version(
        self,
        *,
        version: str,
        actor: str = "system",
        reason: Optional[str] = None,
        target: str = "router",
        region: str = "global",
        rollout_percent: int = 100,
        publish_update: bool = True,
        edge_targets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Activate a policy snapshot and stream the update to runtime listeners.

        This is the control-plane endpoint used for hot rollout without pod restarts.
        """
        requested_version = str(version or "").strip()
        if not requested_version:
            return {
                "success": False,
                "error": "invalid_version",
                "message": "Snapshot version is required.",
            }

        try:
            snapshot = await self._client.get_snapshot_by_version(requested_version)
            if snapshot is None:
                return {
                    "success": False,
                    "error": "snapshot_not_found",
                    "message": f"Snapshot version '{requested_version}' was not found.",
                }

            if self._rct_publish_validate_enabled():
                try:
                    compiled_preview, _ = await self.authz_graph.compile_snapshot_index(
                        snapshot_id=snapshot.id,
                        snapshot_version=snapshot.version,
                        snapshot_ref=f"authz_graph@{snapshot.version}",
                    )
                    publish_errors = await gather_rct_publish_validation_errors(
                        self._client,
                        snapshot_id=snapshot.id,
                        compiled=compiled_preview,
                    )
                except Exception as exc:
                    logger.error(
                        "RCT publish validation compile failed for %s: %s",
                        snapshot.version,
                        exc,
                        exc_info=True,
                    )
                    publish_errors = [f"publish_compile_failed:{exc}"]
                if publish_errors:
                    return {
                        "success": False,
                        "error": "publish_validation_failed",
                        "message": "RCT publish-time validation failed: "
                        + "; ".join(publish_errors),
                        "validation_errors": publish_errors,
                        "snapshot_id": snapshot.id,
                        "version": snapshot.version,
                    }

            activated = await self._client.activate_snapshot(snapshot.id)
            if activated is None:
                return {
                    "success": False,
                    "error": "activation_failed",
                    "message": f"Snapshot '{requested_version}' could not be activated.",
                }

            # Update rollout lane for coordinator/router execution.
            deployment_rows: List[Dict[str, Any]] = []
            try:
                deployment_rows.append(
                    await self._client.upsert_deployment(
                        snapshot_id=snapshot.id,
                        target=str(target or "router"),
                        region=str(region or "global"),
                        percent=int(rollout_percent),
                        is_active=True,
                        activated_by=str(actor or "system"),
                    )
                )
            except Exception as deployment_exc:
                logger.warning(
                    "Failed to upsert primary deployment lane target=%s region=%s for %s: %s",
                    target,
                    region,
                    snapshot.version,
                    deployment_exc,
                    exc_info=True,
                )

            # Optional edge targets for OTA lanes (for example: edge:door, edge:robot).
            for edge_target in edge_targets or []:
                normalized_edge_target = str(edge_target or "").strip()
                if not normalized_edge_target:
                    continue
                try:
                    deployment_rows.append(
                        await self._client.upsert_deployment(
                            snapshot_id=snapshot.id,
                            target=normalized_edge_target,
                            region=str(region or "global"),
                            percent=100,
                            is_active=True,
                            activated_by=str(actor or "system"),
                        )
                    )
                except Exception as edge_deploy_exc:
                    logger.warning(
                        "Failed to upsert edge deployment lane target=%s region=%s for %s: %s",
                        normalized_edge_target,
                        region,
                        snapshot.version,
                        edge_deploy_exc,
                        exc_info=True,
                    )

            await self._load_and_activate_snapshot(snapshot, source="api_activate")

            message = {
                "kind": PKG_UPDATE_ACTIVATE_KIND,
                "version": snapshot.version,
                "snapshot_id": snapshot.id,
                "target": str(target or "router"),
                "region": str(region or "global"),
                "rollout_percent": int(max(0, min(100, int(rollout_percent)))),
                "actor": str(actor or "system"),
                "reason": str(reason).strip() if reason is not None else None,
                "edge_targets": [
                    str(item).strip()
                    for item in (edge_targets or [])
                    if str(item).strip()
                ],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            publish_result = await self.publish_update(message) if publish_update else {"published": False}

            return {
                "success": True,
                "message": f"Activated snapshot {snapshot.version}",
                "snapshot_id": snapshot.id,
                "version": snapshot.version,
                "mode": self._mode.value,
                "deployment_lanes": deployment_rows,
                "publish": publish_result,
            }
        except Exception as e:
            logger.error("Failed to activate snapshot %s: %s", requested_version, e, exc_info=True)
            return {
                "success": False,
                "error": "activation_exception",
                "message": f"Failed to activate snapshot '{requested_version}': {e}",
            }

    async def publish_update(self, payload: Dict[str, Any] | str) -> Dict[str, Any]:
        """
        Publish a PKG update event to the runtime channel.
        """
        if self._redis_client is None:
            return {
                "published": False,
                "error": "redis_unavailable",
                "channel": PKG_REDIS_CHANNEL,
            }
        try:
            message = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"), default=str)
            published_count = await self._redis_client.publish(PKG_REDIS_CHANNEL, message)
            return {
                "published": bool(published_count),
                "receivers": int(published_count or 0),
                "channel": PKG_REDIS_CHANNEL,
                "message": message,
            }
        except Exception as e:
            logger.warning("Failed to publish PKG update event: %s", e, exc_info=True)
            return {
                "published": False,
                "error": str(e),
                "channel": PKG_REDIS_CHANNEL,
            }

    # --- Approve & Promote: Tier 1 → Tier 2/3 Promotion ---

    async def approve_and_promote_seed(
        self, 
        task_id: str, 
        actor: str,
        preserve_multimodal: bool = True
    ) -> Dict[str, Any]:
        """
        Promotes a task from Tier 1 (Multimodal Event Memory) to Tier 2/3 (Knowledge Graph).
        
        This bridges the gap between short-term working perception and long-term structured knowledge.
        The promotion process follows a "Read-Transform-Write" pattern:
        
        1. **Read**: Fetch the task and its multimodal embeddings from `tasks` and `task_multimodal_embeddings`
        2. **Transform**: Ensure graph_node_map entry exists (creates BIGINT node_id)
        3. **Embed**: Copy the 1024d multimodal vector to `graph_embeddings_1024` with label 'task.primary'
        4. **Register**: Task now appears in `v_unified_cortex_memory` under Tier 2/3 (knowledge_base)
        
        Delegates to PKGClient.cortex DAO for database operations, maintaining separation of concerns.
        
        Args:
            task_id: UUID string of the task to promote
            actor: Actor identifier (e.g., 'admin', 'mother') for audit trail
            preserve_multimodal: If True, keeps the original multimodal embedding (default: True)
                               If False, removes it after promotion (not recommended)
        
        Returns:
            Dictionary with:
            - ok: bool - Success/failure status
            - msg: str - Human-readable message
            - new_node_id: Optional[int] - The BIGINT node_id from graph_node_map
            - task_id: str - The original task UUID
        """
        return await self._client.promote_task_to_knowledge_graph(
            task_id=task_id,
            actor=actor,
            preserve_multimodal=preserve_multimodal
        )

    # --- Internals ---

    async def _load_initial_snapshot(self):
        """Load the active snapshot on startup, with detailed error reporting."""
        try:
            snap = await self._client.get_active_snapshot()
            if snap:
                logger.info(f"Found active snapshot: {snap.version} (id={snap.id})")
                await self._load_and_activate_snapshot(snap, source="startup")
            else:
                logger.warning("No active PKG snapshot found in DB")
                self._status.update({
                    "healthy": False,
                    "error": "No active snapshot in database",
                    "version": None
                })
        except Exception as e:
            logger.error(f"Initial snapshot load failed: {e}", exc_info=True)
            self._status.update({
                "healthy": False,
                "error": f"Snapshot load failed: {str(e)}",
                "version": None
            })

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
                            await self._handle_pkg_update_message(data)
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

    async def _handle_pkg_update_message(self, data: Any) -> None:
        payload = self._parse_pkg_update_message(data)
        if payload is None:
            return

        kind = payload.get("kind")
        version = payload.get("version")
        if kind == PKG_UPDATE_ACTIVATE_KIND:
            if not version:
                logger.warning("Ignoring PKG activate message without version: %s", payload)
                return
            logger.info("Hot-swap requested for %s", version)
            snap = await self._client.get_snapshot_by_version(version)
            if snap:
                await self._load_and_activate_snapshot(snap, source="redis")
            return

        if kind == PKG_UPDATE_AUTHZ_REFRESH_KIND:
            if version and version != self._active_version:
                logger.info(
                    "Ignoring authz graph refresh for inactive version %s (active=%s)",
                    version,
                    self._active_version,
                )
                return
            logger.info("Authz graph refresh requested for %s", version or self._active_version)
            await self.refresh_active_authz_graph()
            return

        logger.debug("Ignoring unknown PKG update message: %s", payload)

    def _parse_pkg_update_message(self, data: Any) -> Optional[Dict[str, Any]]:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        if not isinstance(data, str):
            logger.debug("Ignoring non-string PKG update message: %r", data)
            return None

        raw = data.strip()
        if not raw:
            return None
        if raw.startswith("activate:"):
            return {"kind": PKG_UPDATE_ACTIVATE_KIND, "version": raw.split(":", 1)[1].strip()}
        if raw.startswith("authz_graph_refresh:"):
            return {"kind": PKG_UPDATE_AUTHZ_REFRESH_KIND, "version": raw.split(":", 1)[1].strip()}
        if raw == "authz_graph_refresh":
            return {"kind": PKG_UPDATE_AUTHZ_REFRESH_KIND, "version": None}
        if raw.startswith("{"):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Ignoring malformed PKG update JSON: %s", raw)
                return None
            if not isinstance(payload, dict):
                logger.warning("Ignoring non-object PKG update JSON: %s", raw)
                return None
            kind = str(payload.get("kind") or "").strip()
            version = payload.get("version")
            return {
                "kind": kind,
                "version": str(version).strip() if version is not None else None,
            }
        logger.debug("Ignoring unsupported PKG update message: %s", raw)
        return None
    
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
        allowed_keys = self._resolve_task_fact_keys()
        unknown_keys = set(task_facts.keys()) - allowed_keys
        if unknown_keys:
            return f"Unknown keys in task_facts: {unknown_keys}. Allowed keys: {allowed_keys}"
        
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

    def _resolve_task_fact_keys(self) -> set[str]:
        """Resolve the closed-world task fact allowlist from the active request schema bundle when present."""
        bundle = self.get_active_request_schema_bundle()
        request_shape = bundle.get("request_shape") if isinstance(bundle.get("request_shape"), dict) else {}
        allowed_keys = (
            request_shape.get("required_task_fact_keys")
            if isinstance(request_shape.get("required_task_fact_keys"), list)
            else None
        )
        if isinstance(allowed_keys, list):
            normalized = {
                str(key).strip()
                for key in allowed_keys
                if isinstance(key, str) and str(key).strip()
            }
            if normalized:
                return normalized
        return set(ALLOWED_TASK_FACTS_KEYS)
    
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
    mode: PKGMode = PKGMode.CONTROL
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
