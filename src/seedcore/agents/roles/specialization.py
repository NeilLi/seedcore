# agents/roles/specialization.py
"""
Specialization taxonomy, role profiles, and RoleRegistry.
Aligned with SeedCore v2 TaskPayload and Organism Configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Set, Iterable, Optional, List, Any, Union, Protocol
import json
import threading
import logging
from pathlib import Path
import traceback

# Optional YAML support for config loading
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)

# Define keys here to avoid circular imports with state.py
ROLE_KEYS = ["E", "S", "O"]


# Protocol for type safety (both Specialization and DynamicSpecialization satisfy this)
class SpecializationProtocol(Protocol):
    """Protocol that both Specialization enum and DynamicSpecialization satisfy."""
    value: str
    name: str
    
    def __eq__(self, other: Any) -> bool: ...
    def __hash__(self) -> int: ...

class OrganKind(str, Enum):
    """
    Top-level (hard) organ-kind.
    Stable categories used for policy hardening, RBAC, routing gates.
    Dynamic behavior lives in `Specialization`.
    """

    USER_EXPERIENCE = "user_experience"
    ENV_INTELLIGENCE = "env_intelligence"
    ORCHESTRATION = "orchestration"
    EXECUTION = "execution"
    VERIFICATION = "verification"
    LEARNING = "learning"
    BUSINESS = "business"
    UTILITY = "utility"


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
    ENVIRONMENT = "environment"
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
    RESULT_VERIFIER = "result_verifier"
    RESULT_VALIDATOR = "result_validator"
    FEEDBACK_INTEGRATOR = "feedback_integrator"
    FEEDBACK_VERIFIER = "feedback_verifier"

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
    
    Supports both static (Enum) and dynamic specializations.
    """
    name: Union[Specialization, DynamicSpecialization]
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
    
    Supports both static (Enum) and dynamic specializations.
    """
    def __init__(self, profiles: Optional[Iterable[RoleProfile]] = None) -> None:
        self._profiles: Dict[Union[Specialization, DynamicSpecialization], RoleProfile] = {}
        if profiles:
            for p in profiles:
                self.register(p)

    @staticmethod
    def specialization_to_p_dict_static(spec: Union[Specialization, DynamicSpecialization, str]) -> Dict[str, float]:
        """
        Static helper for E/S/O mapping to allow usage without a registry instance.
        Supports both static (Enum) and dynamic specializations.
        """
        # Normalize to string value
        if isinstance(spec, str):
            spec_name = spec.lower()
        elif isinstance(spec, DynamicSpecialization):
            spec_name = spec.value
        else:
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

    def specialization_to_p_dict(self, spec: Union[Specialization, DynamicSpecialization, str]) -> Dict[str, float]:
        """Instance method wrapper."""
        return self.specialization_to_p_dict_static(spec)

    def get(self, spec: Union[Specialization, DynamicSpecialization, str]) -> RoleProfile:
        if spec not in self._profiles:
            raise KeyError(f"RoleRegistry: specialization not registered: {spec}")
        return self._profiles[spec]

    def get_safe(self, spec: Union[Specialization, DynamicSpecialization, str]) -> Optional[RoleProfile]:
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


# =====================================================================
# Dynamic Specialization System (Runtime-Evolvable)
# =====================================================================

class DynamicSpecialization:
    """
    Runtime-created specialization that behaves like Specialization enum.
    Allows agents to evolve and new specializations to be registered dynamically.
    
    This class provides enum-like behavior while supporting runtime registration.
    """
    __slots__ = ('_value', '_name', '_metadata')
    
    def __init__(self, value: str, name: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None):
        """
        Create a dynamic specialization.
        
        Args:
            value: The string value (e.g., "custom_agent_v2")
            name: Optional display name (defaults to value)
            metadata: Optional metadata (category, description, etc.)
        """
        if not value or not isinstance(value, str):
            raise ValueError(f"Specialization value must be a non-empty string, got: {value}")
        self._value = value.lower()  # Normalize to lowercase
        self._name = name or value
        self._metadata = metadata or {}
    
    @property
    def value(self) -> str:
        """Return the string value (compatible with Enum.value)."""
        return self._value
    
    @property
    def name(self) -> str:
        """Return the display name."""
        return self._name
    
    @property
    def metadata(self) -> Dict[str, Any]:
        """Return metadata dictionary."""
        return self._metadata.copy()
    
    def __str__(self) -> str:
        return self._value
    
    def __repr__(self) -> str:
        return f"DynamicSpecialization(value='{self._value}', name='{self._name}')"
    
    def __eq__(self, other: Any) -> bool:
        """Compare by value for compatibility with Specialization enum."""
        if isinstance(other, DynamicSpecialization):
            return self._value == other._value
        if isinstance(other, Specialization):
            return self._value == other.value
        if isinstance(other, str):
            return self._value == other.lower()
        return False
    
    def __hash__(self) -> int:
        """Hash by value for use in sets/dicts."""
        return hash(self._value)
    
    def __lt__(self, other: Any) -> bool:
        """Ordering for sorting."""
        if isinstance(other, DynamicSpecialization):
            return self._value < other._value
        if isinstance(other, Specialization):
            return self._value < other.value
        return False


class SpecializationManager:
    """
    Centralized manager for both static (Enum) and dynamic specializations.
    Supports runtime registration, persistence, and discovery.
    
    Architecture:
    - Static specializations (from Enum) are always available
    - Dynamic specializations can be registered at runtime
    - Supports loading from config files, database, or API
    - Thread-safe for concurrent registration
    """
    
    _instance: Optional['SpecializationManager'] = None
    _lock = threading.Lock()
    
    def __init__(self):
        """Initialize the specialization manager."""
        self._static_specs: Dict[str, Specialization] = {
            spec.value: spec for spec in Specialization
        }
        self._dynamic_specs: Dict[str, DynamicSpecialization] = {}
        self._role_profiles: Dict[str, RoleProfile] = {}
        self._lock = threading.Lock()
        self._config_path: Optional[Path] = None
    
    @classmethod
    def get_instance(cls) -> 'SpecializationManager':
        """Get or create the singleton instance (thread-safe)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def register_dynamic(
        self,
        value: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        role_profile: Optional[RoleProfile] = None,
    ) -> DynamicSpecialization:
        """
        Register a new dynamic specialization at runtime.
        
        Args:
            value: The specialization value (e.g., "custom_agent_v2")
            name: Optional display name
            metadata: Optional metadata dict
            role_profile: Optional RoleProfile for this specialization
            
        Returns:
            The created DynamicSpecialization instance
            
        Raises:
            ValueError: If value conflicts with existing specialization
        """
        value_lower = value.lower()
        
        with self._lock:
            # Check for conflicts
            if value_lower in self._static_specs:
                raise ValueError(
                    f"Cannot register dynamic specialization '{value}': "
                    f"conflicts with static specialization '{self._static_specs[value_lower]}'"
                )
            
            if value_lower in self._dynamic_specs:
                # Update existing dynamic specialization
                existing = self._dynamic_specs[value_lower]
                if metadata:
                    existing._metadata.update(metadata)
                if name:
                    existing._name = name
            else:
                # Create new dynamic specialization
                spec = DynamicSpecialization(value, name, metadata)
                self._dynamic_specs[value_lower] = spec
            
            # Register role profile if provided
            if role_profile:
                # Get the actual dynamic specialization instance
                actual_spec = self._dynamic_specs[value_lower]
                
                # Create a RoleProfile with the actual dynamic specialization
                # This ensures the profile.name matches the registered spec
                profile = RoleProfile(
                    name=actual_spec,
                    default_skills=role_profile.default_skills,
                    allowed_tools=role_profile.allowed_tools,
                    visibility_scopes=role_profile.visibility_scopes,
                    routing_tags=role_profile.routing_tags,
                    safety_policies=role_profile.safety_policies,
                )
                self._role_profiles[value_lower] = profile
        
        return self._dynamic_specs[value_lower]
    
    def get(self, value: str) -> Union[Specialization, DynamicSpecialization]:
        """
        Get a specialization by value (static or dynamic).
        
        Normalizes input to lowercase for consistent lookup.
        
        Args:
            value: The specialization value (case-insensitive)
            
        Returns:
            Specialization enum or DynamicSpecialization instance
            
        Raises:
            KeyError: If specialization not found
        """
        value_lower = value.lower()
        
        # Check static first (normalize enum values for comparison)
        for spec_value, spec in self._static_specs.items():
            if spec_value.lower() == value_lower:
                return spec
        
        # Check dynamic
        if value_lower in self._dynamic_specs:
            return self._dynamic_specs[value_lower]
        
        raise KeyError(f"Specialization '{value}' not found (neither static nor dynamic)")
    
    def get_safe(self, value: str) -> Optional[Union[Specialization, DynamicSpecialization]]:
        """Get specialization safely, returning None if not found."""
        try:
            return self.get(value)
        except KeyError:
            return None
    
    def is_registered(self, value: str) -> bool:
        """Check if a specialization is registered (static or dynamic)."""
        value_lower = value.lower()
        return value_lower in self._static_specs or value_lower in self._dynamic_specs
    
    def is_dynamic(self, value: str) -> bool:
        """Check if a specialization is dynamically registered."""
        return value.lower() in self._dynamic_specs
    
    def list_all(self) -> List[Union[Specialization, DynamicSpecialization]]:
        """List all registered specializations (static + dynamic)."""
        with self._lock:
            return list(self._static_specs.values()) + list(self._dynamic_specs.values())
    
    def list_dynamic(self) -> List[DynamicSpecialization]:
        """List only dynamically registered specializations."""
        with self._lock:
            return list(self._dynamic_specs.values())
    
    def load_from_config(self, config_path: Union[str, Path]) -> int:
        """
        Load dynamic specializations from a YAML config file.
        
        Config format:
        ```yaml
        dynamic_specializations:
          custom_agent_v2:
            name: "Custom Agent V2"
            metadata:
              category: "custom"
              description: "A custom agent specialization"
            role_profile:
              default_skills:
                skill1: 0.8
                skill2: 0.6
              allowed_tools:
                - tool1
                - tool2
              routing_tags:
                - tag1
        ```
        
        Returns:
            Number of specializations loaded
            
        Raises:
            ImportError: If PyYAML is not installed
            FileNotFoundError: If config file doesn't exist
        """
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required for load_from_config. Install with: pip install pyyaml"
            )
        
        config_path = Path(config_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        if not config or 'dynamic_specializations' not in config:
            return 0
        
        loaded = 0
        for value, spec_config in config['dynamic_specializations'].items():
            try:
                metadata = spec_config.get('metadata', {})
                role_profile_data = spec_config.get('role_profile', {})
                
                # Create role profile if provided
                role_profile = None
                if role_profile_data:
                    # Create a temporary DynamicSpecialization for the profile
                    temp_spec = DynamicSpecialization(value, spec_config.get('name'))
                    role_profile = RoleProfile(
                        name=temp_spec,
                        default_skills=role_profile_data.get('default_skills', {}),
                        allowed_tools=set(role_profile_data.get('allowed_tools', [])),
                        visibility_scopes=set(role_profile_data.get('visibility_scopes', [])),
                        routing_tags=set(role_profile_data.get('routing_tags', [])),
                        safety_policies=role_profile_data.get('safety_policies', {}),
                    )
                
                self.register_dynamic(
                    value=value,
                    name=spec_config.get('name'),
                    metadata=metadata,
                    role_profile=role_profile,
                )
                loaded += 1
            except Exception as e:
                logger.warning(
                    f"Failed to load dynamic specialization '{value}': {e}\n"
                    f"Traceback: {traceback.format_exc()}"
                )
        
        self._config_path = config_path
        return loaded
    
    def save_to_config(self, config_path: Union[str, Path]) -> None:
        """
        Save dynamic specializations to a YAML config file.
        
        Raises:
            ImportError: If PyYAML is not installed
        """
        if not HAS_YAML:
            raise ImportError(
                "PyYAML is required for save_to_config. Install with: pip install pyyaml"
            )
        
        config_path = Path(config_path)
        
        config = {
            'dynamic_specializations': {}
        }
        
        with self._lock:
            for value, spec in self._dynamic_specs.items():
                spec_config = {
                    'name': spec.name,
                    'metadata': spec.metadata,
                }
                
                # Include role profile if available
                if value in self._role_profiles:
                    profile = self._role_profiles[value]
                    spec_config['role_profile'] = {
                        'default_skills': profile.default_skills,
                        'allowed_tools': sorted(profile.allowed_tools),
                        'visibility_scopes': sorted(profile.visibility_scopes),
                        'routing_tags': sorted(profile.routing_tags),
                        'safety_policies': profile.safety_policies,
                    }
                
                config['dynamic_specializations'][value] = spec_config
        
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        self._config_path = config_path
    
    def get_role_profile(self, spec: Union[Specialization, DynamicSpecialization, str]) -> Optional[RoleProfile]:
        """Get role profile for a specialization."""
        if isinstance(spec, str):
            spec = self.get_safe(spec)
            if not spec:
                return None
        
        # Normalize to lowercase value for lookup
        if hasattr(spec, 'value'):
            value = spec.value.lower()
        else:
            value = str(spec).lower()
        
        return self._role_profiles.get(value)
    
    def register_role_profile(self, profile: RoleProfile) -> None:
        """Register a role profile for a specialization."""
        spec_value = profile.name.value if hasattr(profile.name, 'value') else str(profile.name)
        self._role_profiles[spec_value.lower()] = profile


# Convenience function for backward compatibility
def get_specialization(value: str) -> Union[Specialization, DynamicSpecialization]:
    """
    Get a specialization by value (static or dynamic).
    This is the recommended way to resolve specializations in new code.
    
    Example:
        spec = get_specialization("custom_agent_v2")
        if isinstance(spec, DynamicSpecialization):
            print(f"Dynamic specialization: {spec.metadata}")
    """
    return SpecializationManager.get_instance().get(value)


def register_specialization(
    value: str,
    name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    role_profile: Optional[RoleProfile] = None,
) -> DynamicSpecialization:
    """
    Convenience function to register a new dynamic specialization.
    
    Example:
        register_specialization(
            value="custom_agent_v2",
            name="Custom Agent V2",
            metadata={"category": "custom", "version": "2.0"},
        )
    """
    return SpecializationManager.get_instance().register_dynamic(
        value=value,
        name=name,
        metadata=metadata,
        role_profile=role_profile,
    )