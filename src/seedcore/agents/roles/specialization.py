# agents/roles/specialization.py
"""
Specialization taxonomy, role profiles, and RoleRegistry.
Aligned with SeedCore v2 TaskPayload and Organism Configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, Iterable, Optional, List, Any
import json

# Define keys here to avoid circular imports with state.py
ROLE_KEYS = ["E", "S", "O"]

class Specialization(str, Enum):
    """
    Agent specialization taxonomy for AI-driven smart habitats.
    Aligned with SeedCore v2 Organ Configuration.
    """

    # =============================================================
    #  USER EXPERIENCE & INTERACTION
    # =============================================================
    USER_LIAISON = "user_liaison"
    MOOD_INFERENCE_AGENT = "mood_inference_agent"
    SCHEDULE_ORACLE = "schedule_oracle"
    PREFERENCE_MODEL = "preference_model"

    # =============================================================
    #  ENVIRONMENT UNDERSTANDING
    # =============================================================
    ENVIRONMENT_MODEL = "environment_model"
    ANOMALY_DETECTOR = "anomaly_detector"
    FORECASTER = "forecaster"
    SAFETY_MONITOR = "safety_monitor"

    # =============================================================
    #  DEVICE & ROBOT ORCHESTRATION
    # =============================================================
    DEVICE_ORCHESTRATOR = "device_orchestrator"
    ROBOT_COORDINATOR = "robot_coordinator"
    HVAC_CONTROLLER = "hvac_controller"
    LIGHTING_CONTROLLER = "lighting_controller"
    ENERGY_MANAGER = "energy_manager"
    CLEANING_MANAGER = "cleaning_manager"
    SECURITY_DRONE_MANAGER = "security_drone_manager"
    MAINTENANCE_MANAGER = "maintenance_manager"

    # =============================================================
    #  ROBOT EXECUTION (Physical Layer)
    # =============================================================
    EXECUTION_ROBOT = "execution_robot" # Base/Abstract
    CLEANING_ROBOT = "cleaning_robot"
    DELIVERY_ROBOT = "delivery_robot"
    SECURITY_DRONE = "security_drone"
    INSPECTION_ROBOT = "inspection_robot"

    # =============================================================
    #  VERIFICATION & FEEDBACK
    # =============================================================
    ENVIRONMENT_VERIFIER = "environment_verifier"
    RESULT_VALIDATOR = "result_validator"
    FEEDBACK_INTEGRATOR = "feedback_integrator"

    # =============================================================
    #  LEARNING & ADAPTATION
    # =============================================================
    CRITIC = "critic"
    ADAPTIVE_LEARNER = "adaptive_learner"
    FAILURE_ANALYZER = "failure_analyzer"
    PLAN_REFINER = "plan_refiner"

    # =============================================================
    #  SPECIALIST / UTILITY
    # =============================================================
    GENERALIST = "generalist"
    OBSERVER = "observer"
    UTILITY = "utility"


@dataclass(frozen=True)
class RoleProfile:
    """
    RoleProfile encodes the operational policy for a specialization.
    Used by Router to check if an agent has the default skills/tools required.
    """
    name: Specialization
    default_skills: Dict[str, float] = field(default_factory=dict)
    allowed_tools: Set[str] = field(default_factory=set)
    visibility_scopes: Set[str] = field(default_factory=set)
    routing_tags: Set[str] = field(default_factory=set)
    safety_policies: Dict[str, float] = field(default_factory=dict)

    def materialize_skills(self, deltas: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Combine default_skills with agent deltas, clamped to [0,1]."""
        deltas = deltas or {}
        out: Dict[str, float] = {}
        for k, base in self.default_skills.items():
            val = float(base) + float(deltas.get(k, 0.0))
            out[k] = max(0.0, min(1.0, val))
        for k, d in deltas.items():
            if k not in out:
                out[k] = max(0.0, min(1.0, float(d)))
        return out

    def has_tool(self, tool: str) -> bool:
        return tool in self.allowed_tools

    def to_p_dict(self) -> Dict[str, float]:
        """Bridge method to E/S/O probability format."""
        # This logic is usually centralized in RoleRegistry, but provided here for convenience
        return RoleRegistry.specialization_to_p_dict_static(self.name)

    def to_context(
        self,
        agent_id: str,
        organ_id: Optional[str],
        skill_deltas: Optional[Dict[str, float]] = None,
        capability: Optional[float] = None,
        mem_util: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Compact context for ML/LLM calls."""
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
    In-memory registry for RoleProfile objects.
    Acts as the source of truth for Agent Capabilities before they report their own.
    """
    def __init__(self, profiles: Optional[Iterable[RoleProfile]] = None) -> None:
        self._profiles: Dict[Specialization, RoleProfile] = {}
        if profiles:
            for p in profiles:
                self.register(p)

    @staticmethod
    def specialization_to_p_dict_static(spec: Specialization) -> Dict[str, float]:
        """
        Static helper for E/S/O mapping to allow usage without a registry instance.
        """
        spec_name = spec.value.lower()
        
        # 1. Execution (Action, Physical, Control)
        execution_kw = [
            "execution", "robot", "device", "orchestrator", "controller", 
            "manager", "coordinator", "drone", "actuator", "action"
        ]
        # 2. Synthesis (Planning, Reasoning, Learning, Social)
        synthesis_kw = [
            "planner", "synthesizer", "critic", "analyzer", "refiner",
            "learner", "model", "preference", "liaison", "reasoning", "social"
        ]
        # 3. Observation (Sensing, Verification, Prediction)
        observation_kw = [
            "observer", "monitor", "detector", "forecaster", "verifier",
            "validator", "inference", "oracle", "integrator"
        ]
        
        e_score = sum(1.0 for kw in execution_kw if kw in spec_name)
        s_score = sum(1.0 for kw in synthesis_kw if kw in spec_name)
        o_score = sum(1.0 for kw in observation_kw if kw in spec_name)
        
        # Fallback
        if e_score == 0 and s_score == 0 and o_score == 0:
            e_score, s_score, o_score = 1.0, 1.0, 1.0
        
        total = e_score + s_score + o_score
        p_dict = {
            "E": e_score / total,
            "S": s_score / total,
            "O": o_score / total,
        }
        
        return {k: p_dict.get(k, 0.0) for k in ROLE_KEYS}

    def specialization_to_p_dict(self, spec: Specialization) -> Dict[str, float]:
        """Instance method wrapper."""
        return self.specialization_to_p_dict_static(spec)

    def get(self, spec: Specialization) -> RoleProfile:
        if spec not in self._profiles:
            raise KeyError(f"RoleRegistry: specialization not registered: {spec}")
        return self._profiles[spec]

    def get_safe(self, spec: Specialization) -> Optional[RoleProfile]:
        return self._profiles.get(spec)

    def register(self, profile: RoleProfile) -> None:
        self._profiles[profile.name] = profile

    def to_json(self, indent: Optional[int] = 2) -> str:
        payload = {
            p.name.value: {
                "default_skills": p.default_skills,
                "allowed_tools": sorted(p.allowed_tools),
            }
            for p in self._profiles.values()
        }
        return json.dumps(payload, indent=indent)


# ---------------------------------------------------------------------
# Graph-aware specifications (Future V2 / Legacy)
# ---------------------------------------------------------------------

@dataclass
class AgentSpec:
    """
    Specification for a Ray agent based on graph state.
    Used for Graph-Driven Deployment (alternative to Config-Driven).
    """
    agent_id: str
    organ_id: Optional[str] = None
    skills: List[str] = field(default_factory=list)
    models: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    resources: Dict[str, float] = field(default_factory=dict)
    namespace: Optional[str] = None
    lifetime: str = "detached"
    name: Optional[str] = None
    metadata: Dict[str, str] = field(default_factory=dict)

class GraphClient:
    def list_agent_specs(self) -> List[AgentSpec]:
        raise NotImplementedError