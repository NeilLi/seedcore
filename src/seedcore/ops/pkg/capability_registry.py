#!/usr/bin/env python3
"""
Capability Registry (PKG DNA -> executor hints).

This module treats `pkg_subtask_types` as a snapshot-scoped "DNA registry":
it loads subtask type definitions (name + default_params) and provides helpers
to enrich PKG-emitted subtasks with executor hints for downstream orchestration.

Design constraints:
- Keep core (OrganismCore) abstract; no domain-specific hard-coding here.
- Use late-binding: executor hints live in DB JSON (`default_params`), not code.
- Be robust: if a capability is missing, fall back gracefully.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .client import PKGClient

# Optional import for specialization validation (graceful degradation if not available)
try:
    from seedcore.agents.roles.specialization import (
        SpecializationManager,
        get_specialization,
    )
    HAS_ROLES = True
except ImportError:
    HAS_ROLES = False

logger = logging.getLogger(__name__)


def _shallow_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Shallow merge dicts: base keys overwritten by override keys.
    """
    out = dict(base or {})
    out.update(dict(override or {}))
    return out


@dataclass(frozen=True)
class CapabilityDef:
    """
    In-memory representation of a subtask type definition.
    """

    name: str
    subtask_type_id: Optional[str]
    snapshot_id: int
    default_params: Dict[str, Any]


class CapabilityRegistry:
    """
    Snapshot-scoped cache of `pkg_subtask_types`.

    Primary use:
    - Given a PKG-emitted subtask `{type, params, rule_id, ...}`,
      enrich it using `default_params` and return a step-task dict
      suitable for Coordinator/Organism execution.
    """

    def __init__(self, pkg_client: PKGClient):
        self._client = pkg_client
        self._lock = asyncio.Lock()

        self._active_snapshot_id: Optional[int] = None
        self._by_name: Dict[str, CapabilityDef] = {}

    @property
    def active_snapshot_id(self) -> Optional[int]:
        return self._active_snapshot_id

    async def refresh(
        self,
        snapshot_id: int,
        *,
        register_dynamic_specs: bool = False,
    ) -> int:
        """
        Load/refresh registry entries for the snapshot id.

        Args:
            snapshot_id: The PKG snapshot ID to load capabilities for.
            register_dynamic_specs: If True, automatically register dynamic specializations
                                   found in executor.specialization fields.

        Returns:
            Number of capabilities loaded.
        """
        async with self._lock:
            rows = await self._client.get_subtask_types(snapshot_id)
            by_name: Dict[str, CapabilityDef] = {}

            for row in rows or []:
                try:
                    name = str(row.get("name") or "").strip()
                    if not name:
                        continue
                    default_params = row.get("default_params") or {}
                    if not isinstance(default_params, dict):
                        # Keep it safe; do not explode on unexpected driver behavior.
                        default_params = {"_raw_default_params": default_params}
                    by_name[name] = CapabilityDef(
                        name=name,
                        subtask_type_id=row.get("id"),
                        snapshot_id=int(row.get("snapshot_id") or snapshot_id),
                        default_params=default_params,
                    )
                except Exception:
                    continue

            self._by_name = by_name
            self._active_snapshot_id = snapshot_id

            logger.info(
                "[PKG] CapabilityRegistry refreshed (snapshot_id=%s, count=%d)",
                snapshot_id,
                len(self._by_name),
            )
            
            # Optionally register dynamic specializations
            if register_dynamic_specs:
                dynamic_count = self.register_dynamic_specializations()
                if dynamic_count > 0:
                    logger.info(
                        "[PKG] CapabilityRegistry registered %d dynamic specializations",
                        dynamic_count,
                    )
            
            return len(self._by_name)

    def get(self, capability_name: str) -> Optional[CapabilityDef]:
        if not capability_name:
            return None
        return self._by_name.get(capability_name)

    async def get_with_guest_overlay(
        self,
        capability_name: str,
        guest_id: Optional[str] = None,
        persona_name: Optional[str] = None,
    ) -> Optional[CapabilityDef]:
        """
        Get capability with guest overlay if available.
        
        Resolution order:
        1. Check guest_capabilities for active guest overlay (if guest_id provided)
        2. Merge guest custom_params with base system capability
        3. Fall back to system layer only if no guest overlay
        
        Args:
            capability_name: Base capability name (e.g., "reachy_actuator")
            guest_id: Optional guest UUID for guest layer lookup
            persona_name: Optional persona name filter
            
        Returns:
            CapabilityDef with merged params, or system-only capability, or None
        """
        # 1. Try guest layer first (if guest_id provided)
        if guest_id:
            merged = await self._client.get_merged_capability(
                guest_id=guest_id,
                persona_name=persona_name,
                base_capability_name=capability_name,
                snapshot_id=self._active_snapshot_id,
            )
            
            if merged and merged.get("source") in ("guest_overlay", "guest_only"):
                # Return merged capability as CapabilityDef
                return CapabilityDef(
                    name=merged.get("base_capability_name") or capability_name,
                    subtask_type_id=merged.get("base_capability_id"),
                    snapshot_id=self._active_snapshot_id or 0,
                    default_params=merged.get("default_params", {}),
                )
        
        # 2. Fall back to system layer
        return self.get(capability_name)

    def list_capabilities(self) -> List[CapabilityDef]:
        """List all registered capabilities for the active snapshot."""
        return list(self._by_name.values())

    def get_routing_hints(self, capability_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract routing hints for a capability (for introspection/debugging).
        
        Returns:
            Dict with 'required_specialization', 'specialization', 'skills', 'tools', etc.
            None if capability not found.
        """
        cap_def = self.get(capability_name)
        if not cap_def:
            return None
        
        routing = {}
        executor = cap_def.default_params.get("executor") or {}
        routing_hints = cap_def.default_params.get("routing") or {}
        
        # Extract from executor
        if isinstance(executor, dict) and executor.get("specialization"):
            routing["required_specialization"] = str(executor["specialization"])
        
        # Merge routing hints
        if isinstance(routing_hints, dict):
            routing.update(routing_hints)
        
        return routing if routing else None

    def get_executor_config(self, capability_name: str) -> Optional[Dict[str, Any]]:
        """
        Extract executor configuration for a capability (for agent creation).
        
        Returns:
            Dict with 'specialization', 'agent_class', 'behaviors', 'behavior_config', etc.
            None if capability not found.
        """
        cap_def = self.get(capability_name)
        if not cap_def:
            return None
        
        executor = cap_def.default_params.get("executor") or {}
        if not isinstance(executor, dict):
            return None
        
        # Extract executor config (preserve all fields for agent creation)
        executor_config = {
            "specialization": executor.get("specialization"),
            "agent_class": executor.get("agent_class", "BaseAgent"),
            "kind": executor.get("kind"),
            "behaviors": executor.get("behaviors", []),
            "behavior_config": executor.get("behavior_config", {}),
        }
        
        # Remove None values
        executor_config = {k: v for k, v in executor_config.items() if v is not None}
        
        return executor_config if executor_config else None

    def register_dynamic_specializations(self) -> int:
        """
        Optionally register dynamic specializations from capability definitions.
        
        This scans all capabilities and registers any specializations found in
        executor.specialization that aren't in the static Specialization enum.
        
        Returns:
            Number of dynamic specializations registered.
        """
        if not HAS_ROLES:
            logger.debug(
                "[CapabilityRegistry] SpecializationManager not available, skipping dynamic registration"
            )
            return 0
        
        registered = 0
        spec_manager = SpecializationManager.get_instance()
        
        for cap_def in self._by_name.values():
            executor = cap_def.default_params.get("executor") or {}
            if not isinstance(executor, dict):
                continue
            
            spec_str = executor.get("specialization")
            if not spec_str:
                continue
            
            spec_str = str(spec_str).strip().lower()
            if not spec_str:
                continue
            
            # Check if already registered (static or dynamic)
            if spec_manager.is_registered(spec_str):
                continue
            
            # Register as dynamic specialization
            try:
                metadata = {
                    "source": "pkg_subtask_types",
                    "capability": cap_def.name,
                    "snapshot_id": cap_def.snapshot_id,
                }
                spec_manager.register_dynamic(
                    value=spec_str,
                    name=cap_def.name.replace("_", " ").title(),
                    metadata=metadata,
                )
                registered += 1
                logger.info(
                    "[CapabilityRegistry] Registered dynamic specialization '%s' from capability '%s'",
                    spec_str,
                    cap_def.name,
                )
            except Exception as e:
                logger.warning(
                    "[CapabilityRegistry] Failed to register dynamic specialization '%s' from capability '%s': %s",
                    spec_str,
                    cap_def.name,
                    e,
                )
        
        return registered

    def build_step_task_from_subtask(
        self,
        subtask: Dict[str, Any],
        *,
        default_task_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert a PKG-emitted subtask into an executable task dict.

        Input subtask shape today (from PKGEvaluator._process_emissions):
            {
              "name": "<subtask_name>",
              "type": "<subtask_type_name>",  # this maps to pkg_subtask_types.name
              "params": {...},                # emission params or default_params
              "rule_id": ...,
              "rule_name": ...,
            }

        Output task dict shape:
            {
              "task_id": (optional; Coordinator will ensure one),
              "description": "...",
              "params": {
                "capability": "<subtask_type_name>",
                "capability_params": {... merged params ...},
                "routing": {
                  "required_specialization": "...",  # HARD constraint (from executor.specialization)
                  "specialization": "...",          # SOFT hint (if executor.specialization but not required)
                  "skills": {...},                  # From routing.skills
                  "tools": [...],                   # From routing.tools
                  "hints": {...},                   # From routing.hints
                },
                "executor": {                       # Preserved for JIT agent spawning
                  "specialization": "...",
                  "agent_class": "...",
                  "kind": "...",
                  "service": {...},
                },
                ...
              },
              # NOTE: we intentionally DO NOT force "type" here unless the capability
              # defines it; leaving it absent allows coordinator to default to ACTION.
            }

        Expected `default_params` format in `pkg_subtask_types`:
            {
              "task_type": "action",  # Optional: task type hint
              "executor": {
                "specialization": "precision_graphics",  # Maps to Specialization enum or DynamicSpecialization
                "agent_class": "BaseAgent",  # Optional: agent class name (default: "BaseAgent")
                "kind": "agent",  # Optional: executor kind (agent, service, etc.)
                "behaviors": ["chat_history", "background_loop"],  # Optional: list of behavior names
                "behavior_config": {  # Optional: behavior-specific configuration
                  "chat_history": {"limit": 50},
                  "background_loop": {
                    "interval_s": 10.0,
                    "method": "sense_environment",
                    "max_errors": 3
                  },
                  "task_filter": {
                    "allowed_types": ["env.tick", "environment.tick"]
                  }
                }
              },
              "routing": {
                "required_specialization": "precision_graphics",  # Optional: HARD constraint
                "specialization": "precision_graphics",  # Optional: SOFT hint
                "skills": {"three_js": 0.9, "rendering": 0.8},  # Optional: skill requirements
                "tools": ["render_mockup", "generate_3d"],  # Optional: required tools
                "hints": {
                  "priority": 5,
                  "deadline_at": "...",
                  "ttl_seconds": 300,
                },
              },
            }

        Wiring logic:
        - If `executor.specialization` exists → sets `params.routing.required_specialization` (HARD)
        - If `routing.*` exists → merges into `params.routing.*` (emission params can override)
        - `executor.*` is preserved in `params.executor` for downstream JIT agent spawning
          - `executor.agent_class` → agent class name (defaults to "BaseAgent" if not specified)
          - `executor.behaviors` → list of behavior names for Behavior Plugin System
          - `executor.behavior_config` → behavior-specific configuration dict
        - Specializations are validated against SpecializationManager (if available)
        
        Behavior Plugin System Integration:
        - Agent class can be defined in `pkg_subtask_types.default_params.executor.agent_class`
        - Behaviors can be defined in `pkg_subtask_types.default_params.executor.behaviors`
        - Behavior configs can be defined in `pkg_subtask_types.default_params.executor.behavior_config`
        - These are preserved in `params.executor` for agent creation
        - Agent creation code can use these to dynamically configure agent behaviors and class
        """
        st = dict(subtask or {})
        capability = st.get("type") or st.get("subtask_type") or st.get("capability")
        capability = str(capability) if capability is not None else ""

        # Merge default_params from DNA registry with emission params (emission wins).
        emission_params = st.get("params") or {}
        if not isinstance(emission_params, dict):
            emission_params = {"_raw_params": emission_params}

        default_params: Dict[str, Any] = {}
        cap_def = self.get(capability)
        if cap_def and isinstance(cap_def.default_params, dict):
            default_params = cap_def.default_params

        merged = _shallow_merge(default_params, emission_params)

        # Optional convention: capability can define:
        # - task_type: "action" | "query" | custom (Organism router rules)
        # - executor: {"kind": "...", "specialization": "...", "agent_class": "...", "service": {...}}
        # - routing: {...}  (directly mapped into params.routing)
        task_type = merged.get("task_type")
        if task_type is None and default_task_type:
            task_type = default_task_type

        # Extract executor and routing hints from merged params
        executor_hints = merged.get("executor") or {}
        routing_hints = merged.get("routing") or {}
        
        # Build routing dict for TaskPayload (maps to params.routing)
        routing: Dict[str, Any] = {}
        
        # 1. Wire executor.specialization -> routing.required_specialization (HARD constraint)
        #    This ensures the routing system can find the right organ/agent
        executor_spec = executor_hints.get("specialization") if isinstance(executor_hints, dict) else None
        if executor_spec:
            spec_str = str(executor_spec).strip()
            if spec_str:
                # Validate specialization exists (optional, but helpful for debugging)
                if HAS_ROLES:
                    try:
                        spec_obj = get_specialization(spec_str)
                        spec_str = spec_obj.value if hasattr(spec_obj, 'value') else spec_str
                        logger.debug(
                            "[CapabilityRegistry] Validated specialization '%s' for capability '%s'",
                            spec_str,
                            capability,
                        )
                    except (KeyError, Exception) as e:
                        logger.warning(
                            "[CapabilityRegistry] Specialization '%s' not found in registry for capability '%s': %s. "
                            "Will use as-is (may be dynamic specialization).",
                            spec_str,
                            capability,
                            e,
                        )
                routing["required_specialization"] = spec_str
        
        # 2. Merge explicit routing hints from default_params (emission can override)
        #    This includes: required_specialization, specialization, skills, tools, hints, etc.
        if isinstance(routing_hints, dict):
            # Merge routing hints (emission params can override default_params)
            emission_routing = emission_params.get("routing") or {}
            if isinstance(emission_routing, dict):
                routing.update(routing_hints)  # Start with defaults
                routing.update(emission_routing)  # Emission overrides
            else:
                routing.update(routing_hints)
        
        # 3. If executor.specialization exists but routing.required_specialization wasn't set,
        #    use executor.specialization as a soft hint (specialization, not required_specialization)
        if executor_spec and "required_specialization" not in routing and "specialization" not in routing:
            spec_str = str(executor_spec).strip()
            if spec_str:
                routing["specialization"] = spec_str  # SOFT hint
        
        # Build params payload
        params: Dict[str, Any] = {}
        params["capability"] = capability
        params["capability_params"] = merged

        # Preserve executor as first-class for JIT agent spawning / dynamic agent creation
        # This includes agent_class, behaviors, and behavior_config for Behavior Plugin System
        if isinstance(executor_hints, dict) and executor_hints:
            params["executor"] = dict(executor_hints)
            # Ensure behaviors and behavior_config are preserved if present
            # (agent_class is automatically preserved via dict copy above)
            if "behaviors" in executor_hints:
                params["executor"]["behaviors"] = executor_hints["behaviors"]
            if "behavior_config" in executor_hints:
                params["executor"]["behavior_config"] = executor_hints["behavior_config"]
        
        # Set routing (may be empty dict, that's fine - TaskPayload handles it)
        if routing:
            params["routing"] = routing

        # Preserve PKG provenance for debugging/audit
        params["pkg"] = {
            "rule_id": st.get("rule_id"),
            "rule_name": st.get("rule_name"),
            "subtask_name": st.get("name"),
            "subtask_type": capability,
            "subtask_type_id": getattr(cap_def, "subtask_type_id", None) if cap_def else None,
            "snapshot_id": getattr(cap_def, "snapshot_id", None) if cap_def else None,
        }

        # Minimal task dict
        task: Dict[str, Any] = {
            "description": st.get("name") or capability or "pkg_subtask",
            "params": params,
        }

        # Only set task.type if capability definition explicitly provides it.
        if task_type:
            task["type"] = str(task_type)

        return task

