from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException  # pyright: ignore[reportMissingImports]
from pydantic import BaseModel, Field  # pyright: ignore[reportMissingImports]

from ...database import get_async_pg_session_factory
from ...ops.pkg.dao import PKGSnapshotsDAO

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class BehaviorConfig(BaseModel):
    """Behavior-specific configuration."""
    motion: Optional[Dict[str, float]] = Field(default_factory=dict, description="Motion behavior config (e.g., velocity_multiplier, smoothness)")
    llm: Optional[Dict[str, float]] = Field(default_factory=dict, description="LLM behavior config (e.g., temperature)")
    background_loop: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Background loop config")
    chat_history: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Chat history config")
    task_filter: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Task filter config")


class ExecutorConfig(BaseModel):
    """Executor configuration for agent spawning."""
    specialization: str = Field(..., description="Specialization identifier (e.g., 'reachy_actuator')")
    behaviors: Optional[List[str]] = Field(default_factory=list, description="List of behavior names")
    behavior_config: Optional[BehaviorConfig] = Field(default_factory=BehaviorConfig, description="Behavior-specific configuration")
    agent_class: Optional[str] = Field(default="BaseAgent", description="Agent class name")
    kind: Optional[str] = Field(default="agent", description="Executor kind (agent, service, etc.)")
    tools: Optional[List[str]] = Field(default_factory=list, description="Required tools")


class RoutingConfig(BaseModel):
    """Routing configuration for task assignment."""
    skills: Optional[Dict[str, float]] = Field(default_factory=dict, description="Skill requirements (skill_name -> weight 0.0-1.0)")
    routing_tags: Optional[List[str]] = Field(default_factory=list, description="Routing tags for matching")
    required_specialization: Optional[str] = Field(default=None, description="HARD constraint specialization")
    specialization: Optional[str] = Field(default=None, description="SOFT hint specialization")
    tools: Optional[List[str]] = Field(default_factory=list, description="Required tool identifiers")


class RoleProfile(BaseModel):
    """Role profile from the initialization payload."""
    skills: Optional[Dict[str, float]] = Field(default_factory=dict, description="Custom skills")
    behaviors: Optional[List[str]] = Field(default_factory=list, description="Behaviors")
    tools: Optional[List[str]] = Field(default_factory=list, description="Tools")


class CapabilityRegistrationRequest(BaseModel):
    """Request payload for guest capability registration."""
    guest_id: UUID = Field(..., description="Guest UUID (required for guest-level overlay)")
    persona_name: str = Field(..., description="Persona name (e.g., 'Mimi', 'Reachy Companion')")
    base_capability_name: Optional[str] = Field(
        default=None, 
        description="Optional base capability name from pkg_subtask_types (e.g., 'reachy_actuator'). "
                    "If not provided, will be derived from executor.specialization."
    )
    role_profile: Optional[RoleProfile] = Field(default_factory=RoleProfile, description="Role profile with skills, behaviors, tools")
    executor: Optional[ExecutorConfig] = Field(default=None, description="Executor configuration")
    routing: Optional[RoutingConfig] = Field(default=None, description="Routing configuration")
    valid_from: Optional[datetime] = Field(default=None, description="When capability becomes active (default: now)")
    valid_to: datetime = Field(..., description="When capability expires (typically guest checkout time)")
    snapshot_id: Optional[int] = Field(default=None, description="Optional snapshot ID for base capability lookup (defaults to active snapshot)")


class CapabilityRegistrationResponse(BaseModel):
    """Response from guest capability registration."""
    success: bool
    guest_capability_id: str
    guest_id: UUID
    persona_name: str
    base_subtask_type_id: Optional[str]
    base_capability_name: Optional[str]
    custom_params: Dict[str, Any]
    valid_from: datetime
    valid_to: datetime
    updated: bool
    message: str


# ============================================================================
# Endpoint Implementation
# ============================================================================

@router.post("/capabilities/register", response_model=CapabilityRegistrationResponse)
async def register_capability(payload: CapabilityRegistrationRequest) -> CapabilityRegistrationResponse:
    """
    Register or update a guest capability overlay in guest_capabilities.
    
    This endpoint supports Phase 1: Agent Materialization using the two-layer architecture:
    - System Layer (pkg_subtask_types): Immutable, system-wide capabilities (hardware limits)
    - Guest Layer (guest_capabilities): Temporal, guest-specific persona overlays
    
    The endpoint:
    1. Resolves or creates base capability in pkg_subtask_types (system layer)
    2. Maps initialization payload to custom_params (personality/behavior overrides)
    3. Inserts/updates guest_capabilities with temporal validity bounds
    4. Returns the registered guest capability details
    
    Architecture Benefits:
    - Prevents configuration drift in system tables
    - Enables automatic cleanup via temporal bounds (valid_to)
    - Respects SeedCore v2.5 Isolation Rule
    - Supports multi-tenant/hospitality robotics
    
    Args:
        payload: CapabilityRegistrationRequest containing guest_id, persona_name, executor, routing, valid_to
        
    Returns:
        CapabilityRegistrationResponse with registered guest capability details
        
    Raises:
        HTTPException: If no active snapshot found, base capability not found, or database operation fails
    """
    session_factory = get_async_pg_session_factory()
    dao = PKGSnapshotsDAO(session_factory)
    
    # 1. Determine snapshot_id for base capability lookup
    snapshot_id = payload.snapshot_id
    if snapshot_id is None:
        # Get active snapshot
        active_snapshot = await dao.get_active_snapshot()
        if not active_snapshot:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "No active snapshot found",
                    "message": "Cannot register guest capability without an active PKG snapshot. "
                               "Please ensure at least one snapshot exists with is_active = TRUE.",
                    "suggestion": (
                        "To fix this:\n"
                        "1. Check if snapshots exist: SELECT * FROM pkg_snapshots;\n"
                        "2. Activate a snapshot: UPDATE pkg_snapshots SET is_active = TRUE WHERE id = <snapshot_id>;\n"
                        "3. Or provide snapshot_id explicitly in the request payload."
                    )
                }
            )
        snapshot_id = active_snapshot.id
    
    # 2. Resolve base capability (system layer)
    # Determine base capability name from payload
    base_capability_name = payload.base_capability_name
    if not base_capability_name:
        # Derive from executor.specialization if available
        if payload.executor and payload.executor.specialization:
            base_capability_name = payload.executor.specialization
        else:
            # Fallback: use persona_name as hint
            base_capability_name = payload.persona_name.lower().replace(" ", "_")
    
    # Look up base capability in system layer
    base_subtask_types = await dao.list_subtask_types(snapshot_id)
    base_cap = None
    for st in base_subtask_types:
        if st.get("name") == base_capability_name:
            base_cap = st
            break
    
    # If base capability doesn't exist, create it in system layer
    base_subtask_type_id = None
    if not base_cap:
        # Create minimal base capability in system layer
        # This represents the hardware/base behavior limits
        base_default_params: Dict[str, Any] = {}
        if payload.executor:
            base_default_params["executor"] = {
                "specialization": payload.executor.specialization,
                "agent_class": payload.executor.agent_class or "BaseAgent",
                "kind": payload.executor.kind or "agent",
            }
        
        try:
            base_result = await dao.upsert_subtask_type(
                snapshot_id=snapshot_id,
                name=base_capability_name,
                default_params=base_default_params,
            )
            base_subtask_type_id = base_result.get("id")
            logger.info(f"Created base capability '{base_capability_name}' in system layer (id={base_subtask_type_id})")
        except Exception as e:
            logger.warning(f"Failed to create base capability '{base_capability_name}': {e}")
            # Continue without base - guest overlay can exist standalone
    else:
        base_subtask_type_id = base_cap.get("id")
        logger.debug(f"Found base capability '{base_capability_name}' (id={base_subtask_type_id})")
    
    # 3. Build custom_params (personality/behavior overrides for guest layer)
    custom_params: Dict[str, Any] = {}
    
    # 3a. Build executor overrides
    executor_overrides: Dict[str, Any] = {}
    
    if payload.executor:
        # Only include overrides (not base hardware limits)
        if payload.executor.behaviors:
            executor_overrides["behaviors"] = payload.executor.behaviors
        
        # Merge behavior_config (personality sliders)
        if payload.executor.behavior_config:
            behavior_config_dict: Dict[str, Any] = {}
            if payload.executor.behavior_config.motion:
                behavior_config_dict["motion"] = payload.executor.behavior_config.motion
            if payload.executor.behavior_config.llm:
                behavior_config_dict["llm"] = payload.executor.behavior_config.llm
            if payload.executor.behavior_config.background_loop:
                behavior_config_dict["background_loop"] = payload.executor.behavior_config.background_loop
            if payload.executor.behavior_config.chat_history:
                behavior_config_dict["chat_history"] = payload.executor.behavior_config.chat_history
            if payload.executor.behavior_config.task_filter:
                behavior_config_dict["task_filter"] = payload.executor.behavior_config.task_filter
            
            if behavior_config_dict:
                executor_overrides["behavior_config"] = behavior_config_dict
        
        if executor_overrides:
            custom_params["executor"] = executor_overrides
    
    # 3b. Build routing overrides
    routing_overrides: Dict[str, Any] = {}
    
    if payload.routing:
        if payload.routing.skills:
            routing_overrides["skills"] = payload.routing.skills
        if payload.routing.routing_tags:
            routing_overrides["routing_tags"] = payload.routing.routing_tags
        if payload.routing.required_specialization:
            routing_overrides["required_specialization"] = payload.routing.required_specialization
        if payload.routing.specialization:
            routing_overrides["specialization"] = payload.routing.specialization
        if payload.routing.tools:
            routing_overrides["tools"] = payload.routing.tools
    elif payload.role_profile:
        # Build routing from role_profile
        if payload.role_profile.skills:
            routing_overrides["skills"] = payload.role_profile.skills
        if payload.role_profile.tools:
            routing_overrides["tools"] = payload.role_profile.tools
    
    # Merge executor specialization into routing if not explicitly set
    if payload.executor and payload.executor.specialization:
        if not routing_overrides.get("specialization"):
            routing_overrides["specialization"] = payload.executor.specialization
        if not routing_overrides.get("required_specialization"):
            routing_overrides["required_specialization"] = payload.executor.specialization
    
    if routing_overrides:
        custom_params["routing"] = routing_overrides
    
    # 4. Set temporal validity
    valid_from = payload.valid_from
    if valid_from is None:
        valid_from = datetime.now(timezone.utc)
    
    # 5. Insert/update guest capability
    try:
        result = await dao.upsert_guest_capability(
            guest_id=str(payload.guest_id),  # Convert UUID to string for SQL casting
            base_subtask_type_id=base_subtask_type_id,
            persona_name=payload.persona_name,
            custom_params=custom_params,
            valid_from=valid_from,
            valid_to=payload.valid_to,
        )
        
        action = "updated" if result.get("updated") else "registered"
        
        logger.info(
            f"Guest capability '{payload.persona_name}' for guest {payload.guest_id} {action} "
            f"(id={result.get('id')}, valid_to={payload.valid_to})"
        )
        
        # Convert guest_id from string to UUID for response
        result_guest_id = result.get("guest_id")
        if isinstance(result_guest_id, str):
            guest_id_uuid = UUID(result_guest_id)
        else:
            guest_id_uuid = UUID(str(result_guest_id)) if result_guest_id else payload.guest_id
        
        return CapabilityRegistrationResponse(
            success=True,
            guest_capability_id=str(result.get("id", "")),
            guest_id=guest_id_uuid,
            persona_name=payload.persona_name,
            base_subtask_type_id=base_subtask_type_id,
            base_capability_name=base_capability_name,
            custom_params=result.get("custom_params", {}),
            valid_from=result.get("valid_from"),
            valid_to=result.get("valid_to"),
            updated=result.get("updated", False),
            message=f"Guest capability '{payload.persona_name}' successfully {action}",
        )
        
    except Exception as e:
        logger.error(f"Failed to register guest capability '{payload.persona_name}' for guest {payload.guest_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Guest capability registration failed",
                "message": str(e),
                "guest_id": str(payload.guest_id),  # Convert UUID to string for JSON serialization
                "persona_name": payload.persona_name,
            }
        )
