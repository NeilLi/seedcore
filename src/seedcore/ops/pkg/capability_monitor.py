#!/usr/bin/env python3
"""
Capability Monitor Service - Runtime Detection and Agent Management

This service monitors `pkg_subtask_types` for changes and dynamically manages
agents based on capability evolution. It bridges the gap between PKG DNA registry
and the agent ecosystem.

Architecture:
- Polls `pkg_subtask_types` periodically (configurable interval)
- Detects changes using hash-based comparison (robust to DB timestamp issues)
- Refreshes CapabilityRegistry when changes detected
- Registers new dynamic specializations automatically
- Manages agents: spawn new, update existing, optionally scale down obsolete

Integration Points:
- CapabilityRegistry: Refreshes capability definitions
- SpecializationManager: Registers dynamic specializations
- OrganismCore: Spawns/updates agents via Organ actors
- Organ.update_role_registry(): Propagates role profile updates
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .client import PKGClient
from .capability_registry import CapabilityRegistry

# Optional imports for specialization and agent management
try:
    from seedcore.agents.roles.specialization import (
        SpecializationManager,
        RoleProfile,
        DynamicSpecialization,
    )
    HAS_ROLES = True
except ImportError:
    HAS_ROLES = False

logger = logging.getLogger(__name__)


@dataclass
class CapabilityChange:
    """Represents a detected change in capabilities."""
    capability_name: str
    change_type: str  # "added", "updated", "removed"
    snapshot_id: int  # Snapshot ID for version consistency validation
    old_capability: Optional[Dict[str, Any]] = None
    new_capability: Optional[Dict[str, Any]] = None
    specialization: Optional[str] = None  # Extracted from executor.specialization


@dataclass
class CapabilitySnapshot:
    """Snapshot of current capabilities for change detection."""
    snapshot_id: int
    capabilities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    capability_hash: str = ""
    timestamp: float = field(default_factory=time.time)

    def compute_hash(self) -> str:
        """Compute hash of capabilities for change detection."""
        # Sort capabilities by name for consistent hashing
        sorted_caps = sorted(
            self.capabilities.items(),
            key=lambda x: x[0]
        )
        # Create a stable representation
        cap_repr = json.dumps(
            {
                name: {
                    "name": data.get("name"),
                    "default_params": data.get("default_params", {}),
                }
                for name, data in sorted_caps
            },
            sort_keys=True,
        )
        return hashlib.sha256(cap_repr.encode()).hexdigest()


class CapabilityMonitor:
    """
    Runtime monitor for pkg_subtask_types changes with automatic agent management.
    
    This service runs a background loop that:
    1. Polls pkg_subtask_types for the active snapshot
    2. Detects changes using hash-based comparison
    3. Refreshes CapabilityRegistry
    4. Registers dynamic specializations
    5. Manages agents (spawn/update/remove) based on changes
    """

    def __init__(
        self,
        pkg_client: PKGClient,
        capability_registry: CapabilityRegistry,
        organism_core: Optional[Any] = None,
        poll_interval: float = 30.0,
        auto_register_specs: bool = True,
        auto_manage_agents: bool = True,
        on_changes_callback: Optional[Any] = None,
    ):
        """
        Initialize the capability monitor.
        
        Args:
            pkg_client: PKGClient for database access
            capability_registry: CapabilityRegistry to refresh
            organism_core: Optional OrganismCore handle for agent management
            poll_interval: How often to poll for changes (seconds)
            auto_register_specs: If True, automatically register dynamic specializations
            auto_manage_agents: If True, automatically spawn/update agents based on changes
        """
        self._client = pkg_client
        self._registry = capability_registry
        self._organism_core = organism_core
        self.poll_interval = poll_interval
        self.auto_register_specs = auto_register_specs
        self.auto_manage_agents = auto_manage_agents
        self._on_changes_callback = on_changes_callback  # Optional callback for change notifications

        # Internal state
        self._current_snapshot: Optional[CapabilitySnapshot] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._is_running = False
        self._stop_event = asyncio.Event()

        # Statistics
        self._stats = {
            "polls": 0,
            "changes_detected": 0,
            "agents_spawned": 0,
            "agents_updated": 0,
            "agents_removed": 0,
            "specs_registered": 0,
        }

        logger.info(
            f"✅ CapabilityMonitor initialized (poll_interval={poll_interval}s, "
            f"auto_register={auto_register_specs}, auto_manage={auto_manage_agents})"
        )

    async def start(self) -> None:
        """Start the monitoring loop."""
        if self._loop_task is not None and not self._loop_task.done():
            logger.warning("CapabilityMonitor loop is already running")
            return

        self._stop_event.clear()
        self._is_running = True
        self._loop_task = asyncio.create_task(self._monitor_loop())
        logger.info("🟢 CapabilityMonitor started")

    async def stop(self) -> None:
        """Stop the monitoring loop."""
        self._is_running = False
        self._stop_event.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=self.poll_interval + 5.0)
            except asyncio.TimeoutError:
                self._loop_task.cancel()
                try:
                    await self._loop_task
                except asyncio.CancelledError:
                    pass
        logger.info("🛑 CapabilityMonitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._is_running and not self._stop_event.is_set():
            try:
                await self._poll_and_process()
            except Exception as e:
                logger.error(f"CapabilityMonitor poll error: {e}", exc_info=True)
            
            # Sleep with cancellation support
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.poll_interval,
                )
            except asyncio.TimeoutError:
                pass  # Normal timeout, continue loop

    async def _poll_and_process(self) -> None:
        """Poll for changes and process them."""
        async with self._lock:
            self._stats["polls"] += 1

            # 1. Get active snapshot
            active_snapshot = await self._client.get_active_snapshot()
            if not active_snapshot:
                logger.debug("No active PKG snapshot found, skipping poll")
                return

            snapshot_id = active_snapshot.id

            # 2. Load current capabilities
            current_caps = await self._load_capabilities(snapshot_id)
            current_hash = self._compute_capabilities_hash(current_caps)

            # 3. Check for changes
            if self._current_snapshot is None:
                # First poll - initialize snapshot AND process existing capabilities as "added"
                logger.info(
                    f"📊 Initial capability snapshot: {len(current_caps)} capabilities "
                    f"(snapshot_id={snapshot_id}). Processing existing capabilities..."
                )
                
                # Process all existing capabilities as "added" changes for initial registration
                if current_caps:
                    initial_changes = []
                    for cap_name, cap_data in current_caps.items():
                        # Extract specialization from executor.specialization
                        executor = cap_data.get("default_params", {}).get("executor", {})
                        spec = executor.get("specialization") if isinstance(executor, dict) else None
                        
                        # If no specialization in executor, derive from capability name
                        if not spec:
                            spec = cap_name.lower()
                            logger.debug(
                                f"No specialization found for '{cap_name}', "
                                f"deriving from capability name: '{spec}'"
                            )
                        
                        initial_changes.append(CapabilityChange(
                            capability_name=cap_name,
                            change_type="added",
                            snapshot_id=snapshot_id,
                            old_capability=None,
                            new_capability=cap_data,
                            specialization=str(spec) if spec else None,
                        ))
                    
                    if initial_changes:
                        logger.info(
                            f"🔄 Processing {len(initial_changes)} existing capabilities as initial 'added' changes"
                        )
                        await self._process_changes(initial_changes, snapshot_id)
                
                # Initialize snapshot after processing
                self._current_snapshot = CapabilitySnapshot(
                    snapshot_id=snapshot_id,
                    capabilities=current_caps,
                    capability_hash=current_hash,
                )
                return

            # Check if snapshot changed
            if snapshot_id != self._current_snapshot.snapshot_id:
                logger.info(
                    f"🔄 PKG snapshot changed: {self._current_snapshot.snapshot_id} → {snapshot_id}"
                )
                # Snapshot changed - treat as full refresh
                await self._handle_snapshot_change(snapshot_id, current_caps)
                return

            # Check for capability changes within same snapshot
            if current_hash != self._current_snapshot.capability_hash:
                logger.info("🔍 Capability changes detected (hash mismatch)")
                changes = self._detect_changes(
                    self._current_snapshot.capabilities,
                    current_caps,
                )
                if changes:
                    await self._process_changes(changes, snapshot_id)
                else:
                    logger.warning("Hash mismatch but no changes detected (possible hash collision)")

            # Update snapshot
            self._current_snapshot = CapabilitySnapshot(
                snapshot_id=snapshot_id,
                capabilities=current_caps,
                capability_hash=current_hash,
            )

    async def _load_capabilities(self, snapshot_id: int) -> Dict[str, Dict[str, Any]]:
        """Load capabilities from database."""
        rows = await self._client.get_subtask_types(snapshot_id)
        return {
            str(row.get("name", "")).strip(): {
                "id": row.get("id"),
                "name": str(row.get("name", "")).strip(),
                "default_params": row.get("default_params", {}),
                "snapshot_id": snapshot_id,
            }
            for row in rows or []
            if row.get("name")
        }

    def _compute_capabilities_hash(self, capabilities: Dict[str, Dict[str, Any]]) -> str:
        """Compute hash of capabilities for change detection."""
        sorted_caps = sorted(capabilities.items(), key=lambda x: x[0])
        cap_repr = json.dumps(
            {
                name: {
                    "name": data.get("name"),
                    "default_params": data.get("default_params", {}),
                }
                for name, data in sorted_caps
            },
            sort_keys=True,
        )
        return hashlib.sha256(cap_repr.encode()).hexdigest()

    def _detect_changes(
        self,
        old_caps: Dict[str, Dict[str, Any]],
        new_caps: Dict[str, Dict[str, Any]],
    ) -> List[CapabilityChange]:
        """Detect changes between old and new capabilities."""
        changes: List[CapabilityChange] = []

        old_names = set(old_caps.keys())
        new_names = set(new_caps.keys())

        # Get snapshot_id from capabilities (should be consistent)
        snapshot_id = (
            list(new_caps.values())[0].get("snapshot_id")
            if new_caps
            else (list(old_caps.values())[0].get("snapshot_id") if old_caps else 0)
        )

        # Added capabilities
        for name in new_names - old_names:
            executor = new_caps[name].get("default_params", {}).get("executor", {})
            spec = executor.get("specialization") if isinstance(executor, dict) else None
            changes.append(
                CapabilityChange(
                    capability_name=name,
                    change_type="added",
                    snapshot_id=snapshot_id,
                    new_capability=new_caps[name],
                    specialization=str(spec) if spec else None,
                )
            )

        # Removed capabilities
        for name in old_names - new_names:
            executor = old_caps[name].get("default_params", {}).get("executor", {})
            spec = executor.get("specialization") if isinstance(executor, dict) else None
            changes.append(
                CapabilityChange(
                    capability_name=name,
                    change_type="removed",
                    snapshot_id=snapshot_id,
                    old_capability=old_caps[name],
                    specialization=str(spec) if spec else None,
                )
            )

        # Updated capabilities (check if default_params changed)
        for name in old_names & new_names:
            old_params = json.dumps(old_caps[name].get("default_params", {}), sort_keys=True)
            new_params = json.dumps(new_caps[name].get("default_params", {}), sort_keys=True)
            if old_params != new_params:
                executor = new_caps[name].get("default_params", {}).get("executor", {})
                spec = executor.get("specialization") if isinstance(executor, dict) else None
                changes.append(
                    CapabilityChange(
                        capability_name=name,
                        change_type="updated",
                        snapshot_id=snapshot_id,
                        old_capability=old_caps[name],
                        new_capability=new_caps[name],
                        specialization=str(spec) if spec else None,
                    )
                )

        return changes

    async def _handle_snapshot_change(
        self,
        new_snapshot_id: int,
        new_capabilities: Dict[str, Dict[str, Any]],
    ) -> None:
        """Handle snapshot change (full refresh)."""
        logger.info(f"🔄 Handling snapshot change to {new_snapshot_id}")

        # Refresh registry
        await self._registry.refresh(
            new_snapshot_id,
            register_dynamic_specs=self.auto_register_specs,
        )

        # Update snapshot
        self._current_snapshot = CapabilitySnapshot(
            snapshot_id=new_snapshot_id,
            capabilities=new_capabilities,
            capability_hash=self._compute_capabilities_hash(new_capabilities),
        )

        # Optionally manage agents (spawn for new specializations)
        if self.auto_manage_agents:
            await self._manage_agents_for_snapshot_change(new_capabilities)

    async def _process_changes(
        self,
        changes: List[CapabilityChange],
        snapshot_id: int,
    ) -> None:
        """Process detected capability changes."""
        self._stats["changes_detected"] += len(changes)

        logger.info(
            f"📝 Processing {len(changes)} capability changes: "
            f"{sum(1 for c in changes if c.change_type == 'added')} added, "
            f"{sum(1 for c in changes if c.change_type == 'updated')} updated, "
            f"{sum(1 for c in changes if c.change_type == 'removed')} removed"
        )

        # 1. Refresh registry
        await self._registry.refresh(
            snapshot_id,
            register_dynamic_specs=self.auto_register_specs,
        )

        # 2. Register dynamic specializations (if enabled)
        if self.auto_register_specs:
            specs_registered = await self._register_specializations_from_changes(changes)
            self._stats["specs_registered"] += specs_registered

        # 3. Notify callback if provided (for external coordination)
        if self._on_changes_callback:
            try:
                if asyncio.iscoroutinefunction(self._on_changes_callback):
                    await self._on_changes_callback(changes)
                else:
                    self._on_changes_callback(changes)
            except Exception as e:
                logger.warning(f"CapabilityMonitor callback failed: {e}")

        # 4. Manage agents (if enabled)
        if self.auto_manage_agents:
            await self._manage_agents_from_changes(changes)

    async def _register_specializations_from_changes(
        self,
        changes: List[CapabilityChange],
    ) -> int:
        """Register dynamic specializations from capability changes."""
        if not HAS_ROLES:
            return 0

        registered = 0
        spec_manager = SpecializationManager.get_instance()

        for change in changes:
            if change.change_type == "added" or change.change_type == "updated":
                spec_str = change.specialization
                if not spec_str:
                    continue

                spec_str = str(spec_str).strip().lower()
                if not spec_str:
                    continue

                # Check if already registered
                if spec_manager.is_registered(spec_str):
                    continue

                # Extract metadata from capability
                default_params = change.new_capability.get("default_params", {})
                executor = default_params.get("executor", {})
                routing = default_params.get("routing", {})

                # Build metadata
                metadata = {
                    "source": "pkg_subtask_types",
                    "capability": change.capability_name,
                    "snapshot_id": change.new_capability.get("snapshot_id"),
                    "detected_at": time.time(),
                }

                # Extract ESO weights if present
                if isinstance(executor, dict) and "eso_weights" in executor:
                    metadata["eso_weights"] = executor["eso_weights"]

                # Build role profile if executor/routing hints exist
                role_profile = None
                if isinstance(executor, dict) or isinstance(routing, dict):
                    # Extract skills from routing hints
                    skills = {}
                    if isinstance(routing, dict):
                        skills = routing.get("skills", {})
                    
                    # Extract tools (from top-level allowed_tools, executor.tools, and routing.tools)
                    # **CRITICAL: Check top-level allowed_tools first (database source of truth)**
                    tools = set()
                    
                    # Priority 1: Top-level allowed_tools (direct from pkg_subtask_types)
                    if isinstance(default_params, dict):
                        top_level_tools = default_params.get("allowed_tools", [])
                        if isinstance(top_level_tools, list):
                            tools.update(top_level_tools)
                        elif isinstance(top_level_tools, str):
                            # Handle single string tool name
                            tools.add(top_level_tools)
                    
                    # Priority 2: executor.tools (legacy/alternative format)
                    if isinstance(executor, dict):
                        executor_tools = executor.get("tools", [])
                        if isinstance(executor_tools, list):
                            tools.update(executor_tools)
                        elif isinstance(executor_tools, str):
                            tools.add(executor_tools)
                    
                    # Priority 3: routing.tools (routing hints)
                    if isinstance(routing, dict):
                        routing_tools = routing.get("tools", [])
                        if isinstance(routing_tools, list):
                            tools.update(routing_tools)
                        elif isinstance(routing_tools, str):
                            tools.add(routing_tools)

                    # Extract routing tags
                    tags = set()
                    if isinstance(routing, dict):
                        routing_tags = routing.get("routing_tags", [])
                        if isinstance(routing_tags, list):
                            tags.update(routing_tags)

                    # Extract behaviors
                    behaviors = []
                    behavior_config = {}
                    if isinstance(executor, dict):
                        behaviors = executor.get("behaviors", [])
                        behavior_config = executor.get("behavior_config", {})

                    # Create temporary spec for role profile
                    temp_spec = DynamicSpecialization(spec_str, spec_str.replace("_", " ").title())
                    role_profile = RoleProfile(
                        name=temp_spec,
                        default_skills=skills,
                        allowed_tools=tools,
                        routing_tags=tags,
                        default_behaviors=list(behaviors) if isinstance(behaviors, list) else [],
                        behavior_config=dict(behavior_config) if isinstance(behavior_config, dict) else {},
                    )

                try:
                    spec_manager.register_dynamic(
                        value=spec_str,
                        name=change.capability_name.replace("_", " ").title(),
                        metadata=metadata,
                        role_profile=role_profile,
                    )
                    registered += 1
                    logger.info(
                        f"✅ Registered dynamic specialization '{spec_str}' "
                        f"from capability '{change.capability_name}'"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to register dynamic specialization '{spec_str}': {e}"
                    )

        return registered

    async def _manage_agents_from_changes(self, changes: List[CapabilityChange]) -> None:
        """Manage agents based on capability changes."""
        if not self._organism_core:
            logger.debug("OrganismCore not available, skipping agent management")
            return

        for change in changes:
            if change.change_type == "added":
                await self._handle_capability_added(change)
            elif change.change_type == "updated":
                await self._handle_capability_updated(change)
            elif change.change_type == "removed":
                await self._handle_capability_removed(change)

    async def _handle_capability_added(self, change: CapabilityChange) -> None:
        """Handle added capability - spawn agent if needed."""
        if not change.specialization:
            return

        spec_str = str(change.specialization).strip().lower()
        if not spec_str:
            return

        # Check if agents with this specialization already exist
        # (JIT spawning will handle this, but we can log it)
        logger.info(
            f"➕ Capability '{change.capability_name}' added with specialization '{spec_str}'. "
            "Agents will be spawned on-demand via JIT spawning."
        )
        # Note: We don't proactively spawn here - JIT spawning handles it more efficiently

    async def _handle_capability_updated(self, change: CapabilityChange) -> None:
        """Handle updated capability - update role profiles."""
        if not change.specialization:
            return

        spec_str = str(change.specialization).strip().lower()
        if not spec_str or not HAS_ROLES:
            return

        spec_manager = SpecializationManager.get_instance()
        
        # Get role profile if it exists
        role_profile = spec_manager.get_role_profile(spec_str)
        if not role_profile:
            logger.debug(
                f"Role profile not found for '{spec_str}', skipping agent update"
            )
            return

        # Extract updated role profile data
        default_params = change.new_capability.get("default_params", {})
        executor = default_params.get("executor", {})
        routing = default_params.get("routing", {})

        # Build updated role profile
        updated_profile = self._build_role_profile_from_capability(
            spec_str,
            change.capability_name,
            executor,
            routing,
            default_params=default_params,
        )

        if updated_profile:
            # Update role profile in manager
            spec_manager.register_role_profile(updated_profile)

            # Broadcast to all organs (they will propagate to agents)
            if self._organism_core:
                try:
                    # Get all organs
                    organs = getattr(self._organism_core, "organs", {})
                    for organ_id, organ_handle in organs.items():
                        try:
                            await organ_handle.update_role_registry.remote(updated_profile)
                            self._stats["agents_updated"] += 1
                        except Exception as e:
                            logger.warning(
                                f"Failed to update role registry in organ {organ_id}: {e}"
                            )
                except Exception as e:
                    logger.error(f"Failed to broadcast role profile update: {e}")

            logger.info(
                f"🔄 Updated role profile for specialization '{spec_str}' "
                f"(capability: {change.capability_name})"
            )

    async def _handle_capability_removed(self, change: CapabilityChange) -> None:
        """Handle removed capability - optionally scale down agents."""
        if not change.specialization:
            return

        spec_str = str(change.specialization).strip().lower()
        logger.info(
            f"➖ Capability '{change.capability_name}' removed with specialization '{spec_str}'. "
            "Consider scaling down agents if no longer needed."
        )
        # Note: We don't automatically remove agents - that's a policy decision
        # The system can continue using existing agents, or manual intervention can scale down

    def _build_role_profile_from_capability(
        self,
        spec_str: str,
        capability_name: str,
        executor: Dict[str, Any],
        routing: Dict[str, Any],
        default_params: Optional[Dict[str, Any]] = None,
    ) -> Optional[RoleProfile]:
        """Build RoleProfile from capability definition."""
        if not HAS_ROLES:
            return None

        # Extract components
        skills = routing.get("skills", {}) if isinstance(routing, dict) else {}
        
        # Extract tools (from top-level allowed_tools, executor.tools, and routing.tools)
        # **CRITICAL: Check top-level allowed_tools first (database source of truth)**
        tools = set()
        
        # Priority 1: Top-level allowed_tools (direct from pkg_subtask_types)
        if isinstance(default_params, dict):
            top_level_tools = default_params.get("allowed_tools", [])
            if isinstance(top_level_tools, list):
                tools.update(top_level_tools)
            elif isinstance(top_level_tools, str):
                # Handle single string tool name
                tools.add(top_level_tools)
        
        # Priority 2: executor.tools (legacy/alternative format)
        if isinstance(executor, dict):
            executor_tools = executor.get("tools", [])
            if isinstance(executor_tools, list):
                tools.update(executor_tools)
            elif isinstance(executor_tools, str):
                tools.add(executor_tools)
        
        # Priority 3: routing.tools (routing hints)
        if isinstance(routing, dict):
            routing_tools = routing.get("tools", [])
            if isinstance(routing_tools, list):
                tools.update(routing_tools)
            elif isinstance(routing_tools, str):
                tools.add(routing_tools)

        tags = set()
        if isinstance(routing, dict):
            routing_tags = routing.get("routing_tags", [])
            if isinstance(routing_tags, list):
                tags.update(routing_tags)

        behaviors = []
        behavior_config = {}
        if isinstance(executor, dict):
            behaviors = executor.get("behaviors", [])
            behavior_config = executor.get("behavior_config", {})

        # Create spec
        spec = DynamicSpecialization(spec_str, spec_str.replace("_", " ").title())

        return RoleProfile(
            name=spec,
            default_skills=skills,
            allowed_tools=tools,
            routing_tags=tags,
            default_behaviors=list(behaviors) if isinstance(behaviors, list) else [],
            behavior_config=dict(behavior_config) if isinstance(behavior_config, dict) else {},
        )

    async def _manage_agents_for_snapshot_change(
        self,
        capabilities: Dict[str, Dict[str, Any]],
    ) -> None:
        """Manage agents when snapshot changes (full refresh)."""
        # Extract all specializations from capabilities
        specializations: Set[str] = set()
        for cap_data in capabilities.values():
            executor = cap_data.get("default_params", {}).get("executor", {})
            if isinstance(executor, dict):
                spec = executor.get("specialization")
                if spec:
                    specializations.add(str(spec).strip().lower())

        logger.info(
            f"📊 Snapshot change: {len(specializations)} unique specializations "
            f"across {len(capabilities)} capabilities"
        )
        # Agents will be spawned on-demand via JIT spawning

    def get_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics."""
        return {
            **self._stats,
            "is_running": self._is_running,
            "current_snapshot_id": (
                self._current_snapshot.snapshot_id
                if self._current_snapshot
                else None
            ),
            "current_capability_count": (
                len(self._current_snapshot.capabilities)
                if self._current_snapshot
                else 0
            ),
        }
