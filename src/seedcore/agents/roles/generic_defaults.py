"""
Generic, domain-agnostic default role registry for SeedCore.

This registry provides:
- GENERALIST role (baseline)
- Minimal RBAC tool access
- Minimal routing hints
- Safe operational policies

Domain-specific registries (e.g., hotel, retail) can override or extend
these defaults at startup.
"""

from __future__ import annotations

from .specialization import (
    Specialization,
    RoleProfile,
    RoleRegistry,
)

# A small set of universal tool names
T = {
    "mem_read": "mem.read",
    "mem_write": "mem.write",
    "notify": "notify.send",
}


# agents/roles/specialization.py

def create_default_registry() -> RoleRegistry:
    """
    Generates a RoleRegistry populated with defaults for EXECUTION-layer specializations.
    
    Architectural Note:
    - High-level planning (Goal Synthesis, Contextual Planning) happens in the 
      Control Plane (Coordinator), NOT here.
    - These agents are "Reflexive Doers" -> Interface, Sensing, Actuation.
    """
    registry = RoleRegistry()

    # =============================================================
    # 1. USER INTERFACE & REFLEXIVE CHAT
    # =============================================================
    # "The Mouth/Ears" - Handles raw I/O and 'agent_tunnel' low-latency chat.
    registry.register(RoleProfile(
        name=Specialization.USER_LIAISON,
        default_skills={"dialogue": 0.95, "empathy": 0.9, "compliance": 0.95},
        allowed_tools={"chat.reply", "user.profile.read"}
    ))
    registry.register(RoleProfile(
        name=Specialization.MOOD_INFERENCE_AGENT,
        default_skills={"sentiment_analysis": 0.9, "signal_processing": 0.8},
    ))
    # 'Oracle' here acts as a specialized tool-runner for calendar APIs
    registry.register(RoleProfile(
        name=Specialization.SCHEDULE_ORACLE,
        default_skills={"calendar_management": 0.95, "api_interaction": 0.9},
        allowed_tools={"calendar.read", "calendar.write"}
    ))

    # =============================================================
    # 2. ENVIRONMENT SENSING (DIGITAL TWIN)
    # =============================================================
    # "The Eyes/Senses" - Aggregates sensor data into state.
    registry.register(RoleProfile(
        name=Specialization.ENVIRONMENT_MODEL,
        default_skills={"data_ingestion": 0.95, "state_tracking": 0.9},
        allowed_tools={"sensors.read_all", "graph.write_state"}
    ))
    registry.register(RoleProfile(
        name=Specialization.ANOMALY_DETECTOR,
        default_skills={"pattern_matching": 0.95, "threshold_monitoring": 0.9},
        allowed_tools={"system.alert", "sensors.read_stream"}
    ))
    registry.register(RoleProfile(
        name=Specialization.SAFETY_MONITOR,
        default_skills={"compliance": 1.0, "hazard_detection": 0.95},
        allowed_tools={"system.emergency_stop", "sensors.read_critical"}
    ))

    # =============================================================
    # 3. ORCHESTRATION & DRIVERS
    # =============================================================
    # "The Hands/Nerves" - Translates commands to device protocols.
    registry.register(RoleProfile(
        name=Specialization.DEVICE_ORCHESTRATOR,
        default_skills={"iot_protocol": 0.95, "device_control": 0.9},
        allowed_tools={"iot.write", "iot.read"}
    ))
    registry.register(RoleProfile(
        name=Specialization.ROBOT_COORDINATOR,
        default_skills={"fleet_management": 0.9, "spatial_coordination": 0.85},
        allowed_tools={"robot.command", "robot.status"}
    ))
    registry.register(RoleProfile(
        name=Specialization.HVAC_CONTROLLER,
        default_skills={"thermodynamics": 0.8, "iot_control": 0.9},
        allowed_tools={"hvac.set_point", "hvac.get_status"}
    ))
    # ... (Lighting, Energy, Cleaning Managers follow similar pattern)

    # =============================================================
    # 4. PHYSICAL EXECUTION (ROBOTS)
    # =============================================================
    # "The Muscles" - Physical actuation agents.
    registry.register(RoleProfile(
        name=Specialization.CLEANING_ROBOT,
        default_skills={"navigation": 0.8, "cleaning_mechanics": 0.9},
        allowed_tools={"robot.action.clean", "robot.move"}
    ))
    # ... (Delivery, Drone, Inspection)

    # =============================================================
    # 5. GENERALIST (FALLBACK EXECUTOR)
    # =============================================================
    # Used for tasks that don't fit specific hardware profiles (e.g., generic web search)
    registry.register(RoleProfile(
        name=Specialization.GENERALIST,
        default_skills={"tool_usage": 0.8, "basic_reasoning": 0.6},
        allowed_tools={"search.web", "memory.read", "utils.*"}
    ))

    return registry

# =====================================================================
# GLOBAL EXPORT
# =====================================================================
# This is what OrganismCore imports
DEFAULT_ROLE_REGISTRY = create_default_registry()

