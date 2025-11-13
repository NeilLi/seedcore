# agents/roles/specialization.py
"""
Specialization taxonomy, role profiles, and a simple in-memory RoleRegistry.

This module formalizes "roles" (specializations) as first-class operational policy:
- Default skill priors (0..1) that combine with per-agent skill deltas
- RBAC for tools and data visibility
- Routing hints for the meta-controller
- Safety envelopes for autonomy/cost/risk constraints

Usage:
    from rayagent.roles.specialization import Specialization, RoleProfile, RoleRegistry
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, Set, Iterable, Optional, List, Any
import json


class Specialization(str, Enum):
    """Agent specialization taxonomy for AI-driven smart habitats."""

    # -------------------------------------------------------------
    # META-CONTROL & GLOBAL PLANNING
    # -------------------------------------------------------------
    CONTEXTUAL_PLANNER = "contextual_planner"
    GOAL_SYNTHESIZER = "goal_synthesizer"              # translates user intent → actionable goals
    ROUTING_META_AGENT = "routing_meta_agent"          # organ-level routing / cross-organ coordination

    # -------------------------------------------------------------
    # USER INTERACTION & PREFERENCE MANAGEMENT
    # -------------------------------------------------------------
    USER_LIAISON = "user_liaison"                      # natural dialog, clarification, negotiation
    MOOD_INFERENCE_AGENT = "mood_inference_agent"      # detects user state from sensors
    SCHEDULE_ORACLE = "schedule_oracle"                # plans around calendars, routines, guests
    PREFERENCE_MODEL = "preference_model"              # long-term user preference learning

    # -------------------------------------------------------------
    # ENVIRONMENT MODELING & UNDERSTANDING
    # -------------------------------------------------------------
    ENVIRONMENT_MODEL = "environment_model"            # unified world state from multi-sensor fusion
    ANOMALY_DETECTOR = "anomaly_detector"              # detects unusual patterns, failures, risks
    FORECASTER = "forecaster"                          # predicts air quality, energy, occupancy
    SAFETY_MONITOR = "safety_monitor"                  # detects hazards, emergencies

    # -------------------------------------------------------------
    # DEVICE & ROBOT ORCHESTRATION
    # -------------------------------------------------------------
    DEVICE_ORCHESTRATOR = "device_orchestrator"        # maps goals → device commands
    ROBOT_COORDINATOR = "robot_coordinator"            # multi-robot path & task orchestration
    HVAC_CONTROLLER = "hvac_controller"
    LIGHTING_CONTROLLER = "lighting_controller"
    ENERGY_MANAGER = "energy_manager"
    CLEANING_MANAGER = "cleaning_manager"
    SECURITY_DRONE_MANAGER = "security_drone_manager"
    MAINTENANCE_MANAGER = "maintenance_manager"

    # -------------------------------------------------------------
    # EXECUTION AGENTS (physical robots / device drivers)
    # -------------------------------------------------------------
    EXECUTION_ROBOT = "execution_robot"                # base type
    CLEANING_ROBOT = "cleaning_robot"
    DELIVERY_ROBOT = "delivery_robot"
    SECURITY_DRONE = "security_drone"
    INSPECTION_ROBOT = "inspection_robot"

    # -------------------------------------------------------------
    # VERIFICATION, QA, SELF-CORRECTION
    # -------------------------------------------------------------
    ENVIRONMENT_VERIFIER = "environment_verifier"      # compares goals vs reality
    RESULT_VALIDATOR = "result_validator"              # checks "was task done properly?"
    FEEDBACK_INTEGRATOR = "feedback_integrator"        # integrates user or sensor feedback

    # -------------------------------------------------------------
    # LEARNING, CRITIC, ADAPTATION
    # -------------------------------------------------------------
    CRITIC = "critic"                                  # identifies suboptimal plans
    ADAPTIVE_LEARNER = "adaptive_learner"              # improves future strategies
    FAILURE_ANALYZER = "failure_analyzer"
    PLAN_REFINER = "plan_refiner"

    # -------------------------------------------------------------
    # GENERALIST / FLEX ROLES
    # -------------------------------------------------------------
    GENERALIST = "generalist"
    OBSERVER = "observer"


@dataclass(frozen=True)
class RoleProfile:
    """
    RoleProfile encodes the operational policy for a specialization.

    Fields:
        name: Specialization enum
        default_skills: Baseline skills (0..1). Agent-specific deltas will be added and clamped.
        allowed_tools: Tool identifiers permitted for this role (RBAC).
        visibility_scopes: Data partitions/indices this role can read/write.
        routing_tags: Meta-controller hints for task routing.
        safety_policies: Soft/hard limits (e.g., max_autonomy, review thresholds).

    Methods:
        materialize_skills(deltas): Combine default_skills with agent deltas, clamped to [0,1].
        has_tool(tool): Quick RBAC check.
        to_context(...): Compact context dict for cognition/ML calls.
    """
    name: Specialization
    default_skills: Dict[str, float] = field(default_factory=dict)
    allowed_tools: Set[str] = field(default_factory=set)
    visibility_scopes: Set[str] = field(default_factory=set)
    routing_tags: Set[str] = field(default_factory=set)
    safety_policies: Dict[str, float] = field(default_factory=dict)

    def materialize_skills(self, deltas: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        deltas = deltas or {}
        # Merge defaults + deltas (additive), clamp to [0,1]
        out: Dict[str, float] = {}
        for k, base in self.default_skills.items():
            val = float(base) + float(deltas.get(k, 0.0))
            out[k] = max(0.0, min(1.0, val))
        # Include new skills that don't exist in defaults
        for k, d in deltas.items():
            if k not in out:
                out[k] = max(0.0, min(1.0, float(d)))
        return out

    def has_tool(self, tool: str) -> bool:
        return tool in self.allowed_tools

    def to_context(
        self,
        agent_id: str,
        organ_id: Optional[str],
        skill_deltas: Optional[Dict[str, float]] = None,
        capability: Optional[float] = None,
        mem_util: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compact role context for ML/LLM calls."""
        return {
            "agent_id": agent_id,
            "organ_id": organ_id,
            "specialization": self.name.value,
            "skills": self.materialize_skills(skill_deltas),
            "capability": float(capability) if capability is not None else None,
            "mem_util": float(mem_util) if mem_util is not None else None,
            "routing_tags": sorted(self.routing_tags),
            "safety": self.safety_policies.copy(),
        }


class RoleRegistry:
    """
    Simple in-memory registry for RoleProfile objects.

    - get(spec): retrieve profile (raises KeyError if missing)
    - get_safe(spec): retrieve profile or None
    - register(profile): add/replace a RoleProfile
    - update(spec, **fields): shallow update to an existing profile
    - all_profiles(): iterate over all RoleProfile
    - to_json(): export registry to JSON (for debugging/telemetry)
    """
    def __init__(self, profiles: Optional[Iterable[RoleProfile]] = None) -> None:
        self._profiles: Dict[Specialization, RoleProfile] = {}
        if profiles:
            for p in profiles:
                self.register(p)

    def get(self, spec: Specialization) -> RoleProfile:
        if spec not in self._profiles:
            raise KeyError(f"RoleRegistry: specialization not registered: {spec}")
        return self._profiles[spec]

    def get_safe(self, spec: Specialization) -> Optional[RoleProfile]:
        return self._profiles.get(spec)

    def register(self, profile: RoleProfile) -> None:
        self._profiles[profile.name] = profile

    def update(self, spec: Specialization, **fields: Any) -> RoleProfile:
        existing = self.get(spec)
        # dataclasses are frozen? RoleProfile is frozen=True, so rebuild
        merged_kwargs = asdict(existing)
        merged_kwargs.update(fields)
        updated = RoleProfile(
            name=existing.name,
            default_skills=dict(merged_kwargs["default_skills"]),
            allowed_tools=set(merged_kwargs["allowed_tools"]),
            visibility_scopes=set(merged_kwargs["visibility_scopes"]),
            routing_tags=set(merged_kwargs["routing_tags"]),
            safety_policies=dict(merged_kwargs["safety_policies"]),
        )
        self.register(updated)
        return updated

    def all_profiles(self) -> List[RoleProfile]:
        return list(self._profiles.values())

    def to_json(self, indent: Optional[int] = 2) -> str:
        payload = {
            p.name.value: {
                "default_skills": p.default_skills,
                "allowed_tools": sorted(p.allowed_tools),
                "visibility_scopes": sorted(p.visibility_scopes),
                "routing_tags": sorted(p.routing_tags),
                "safety_policies": p.safety_policies,
            }
            for p in self._profiles.values()
        }
        return json.dumps(payload, indent=indent)
