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
    Core agent specialization taxonomy for AI-driven smart habitats.
    
    This enum defines only the most essential, commonly-used specializations.
    Additional specializations are dynamically registered from pkg_subtask_types
    via CapabilityMonitor, which takes precedence over static configurations.
    """

    # =============================================================
    #  CORE SPECIALIZATIONS (Most Common Cases)
    # =============================================================
    
    # User Experience
    USER_LIAISON = "user_liaison"
    
    # Environment Intelligence
    ENVIRONMENT = "environment"
    ANOMALY_DETECTOR = "anomaly_detector"
    
    # Orchestration
    DEVICE_ORCHESTRATOR = "device_orchestrator"
    
    # Execution
    CLEANING_ROBOT = "cleaning_robot"
    
    # Verification
    RESULT_VERIFIER = "result_verifier"
    
    # Learning
    CRITIC = "critic"
    ADAPTIVE_LEARNER = "adaptive_learner"
    
    # Utility (Fallback/Default)
    GENERALIST = "generalist"
    OBSERVER = "observer"
    UTILITY = "utility"


@dataclass(frozen=True)
class RoleProfile:
    """
    RoleProfile encodes the operational policy for a specialization.
    Used by Router to check if an agent has the default skills/tools required.
    
    Supports both static (Enum) and dynamic specializations.
    
    Behaviors define runtime capabilities that can be dynamically configured:
    - chat_history: Manages conversation history ring buffer
    - background_loop: Runs periodic background tasks
    - task_filter: Filters tasks by type/pattern
    - tool_registration: Registers tools dynamically
    - dedup: Manages idempotency cache
    - safety_check: Performs safety validation
    
    Behavior configs are merged from:
    1. RoleProfile.default_behaviors (specialization-level defaults)
    2. Agent config (organs.yaml or pkg_subtask_types)
    3. Runtime overrides (executor.behavior_config)
    
    Zone affinity and environment constraints enable zone-scoped role profiles:
    - zone_affinity: Preferred zones (e.g., ["magic_atelier", "journey_studio"])
    - environment_constraints: Physical/environmental constraints (e.g., {"max_temperature": 30, "requires_ventilation": true})
    """
    name: Union[Specialization, DynamicSpecialization]
    default_skills: Dict[str, float] = field(default_factory=dict)
    allowed_tools: Set[str] = field(default_factory=set)
    visibility_scopes: Set[str] = field(default_factory=set)
    routing_tags: Set[str] = field(default_factory=set)
    safety_policies: Dict[str, float] = field(default_factory=dict)
    # Behavior Plugin System support
    default_behaviors: List[str] = field(default_factory=list)  # e.g., ["chat_history", "background_loop"]
    behavior_config: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # e.g., {"chat_history": {"limit": 50}}
    # Zone-scoped role profiles (for 2030+ Hotel scenario)
    zone_affinity: List[str] = field(default_factory=list)  # Preferred zones (e.g., ["magic_atelier", "journey_studio"])
    environment_constraints: Dict[str, Any] = field(default_factory=dict)  # Physical constraints (e.g., {"max_temperature": 30, "requires_ventilation": True})

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
            "behaviors": self.default_behaviors.copy(),
            "zone_affinity": self.zone_affinity.copy(),
            "environment_constraints": self.environment_constraints.copy(),
        }
    
    def get_behavior_config(self, behavior_name: str) -> Dict[str, Any]:
        """Get configuration for a specific behavior."""
        return self.behavior_config.get(behavior_name, {}).copy()
    
    def merge_behavior_config(self, override_config: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Merge behavior configs with overrides (override wins).
        
        Args:
            override_config: Behavior configs to merge (e.g., from executor.behavior_config)
            
        Returns:
            Merged behavior config dict
        """
        merged = dict(self.behavior_config)
        for behavior_name, config in override_config.items():
            if behavior_name in merged:
                # Merge nested configs
                merged[behavior_name] = {**merged[behavior_name], **config}
            else:
                merged[behavior_name] = dict(config)
        return merged


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
        
        Priority order:
        1. Check DynamicSpecialization.metadata["eso_weights"] if available (explicit override)
        2. Fall back to keyword-based heuristic
        3. Fall back to uniform distribution (1/1/1) if no keywords match
        """
        # Check for explicit ESO weights in metadata (for dynamic specializations)
        if isinstance(spec, DynamicSpecialization):
            meta = spec.metadata
            if isinstance(meta, dict) and "eso_weights" in meta:
                eso_weights = meta["eso_weights"]
                if isinstance(eso_weights, dict):
                    # Use explicit weights if provided: {"E": 0.8, "S": 0.2, "O": 0.0}
                    # Normalize to ensure they sum to 1.0
                    e_val = float(eso_weights.get("E", 0.0))
                    s_val = float(eso_weights.get("S", 0.0))
                    o_val = float(eso_weights.get("O", 0.0))
                    total = e_val + s_val + o_val
                    if total > 0:
                        return {
                            "E": e_val / total,
                            "S": s_val / total,
                            "O": o_val / total,
                        }
                    # If all zeros, fall through to keyword heuristic
        
        # Normalize to string value for keyword matching
        if isinstance(spec, str):
            spec_name = spec.lower()
        elif isinstance(spec, DynamicSpecialization):
            spec_name = spec.value.lower()
        else:
            spec_name = spec.value.lower()
        
        # 1. Execution (Action, Physical, Control)
        execution_kw = [
            "execution", "robot", "device", "orchestrator", "controller", 
            "manager", "coordinator", "drone", "actuator", "action", "renderer"
        ]
        # 2. Synthesis (Planning, Reasoning, Learning, Social)
        synthesis_kw = [
            "planner", "synthesizer", "critic", "analyzer", "refiner",
            "learner", "model", "preference", "liaison", "reasoning", "social",
            "director", "promoter", "design"
        ]
        # 3. Observation (Sensing, Verification, Prediction)
        observation_kw = [
            "observer", "monitor", "detector", "forecaster", "verifier",
            "validator", "inference", "oracle", "integrator", "guardian"
        ]
        
        e_score = sum(1.0 for kw in execution_kw if kw in spec_name)
        s_score = sum(1.0 for kw in synthesis_kw if kw in spec_name)
        o_score = sum(1.0 for kw in observation_kw if kw in spec_name)
        
        # Fallback: uniform distribution if no keywords match
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

    def update(
        self,
        spec: Union[Specialization, DynamicSpecialization, str],
        **updates: Any,
    ) -> RoleProfile:
        """
        Update a role profile by creating a new instance with merged values.
        Since RoleProfile is frozen, this creates a new instance.
        
        Args:
            spec: Specialization to update
            **updates: Fields to update (default_skills, allowed_tools, etc.)
            
        Returns:
            Updated RoleProfile instance
        """
        existing = self.get(spec)
        
        # Merge updates with existing values
        new_default_skills = {**existing.default_skills, **updates.get("default_skills", {})}
        new_allowed_tools = existing.allowed_tools | updates.get("allowed_tools", set())
        new_visibility_scopes = existing.visibility_scopes | updates.get("visibility_scopes", set())
        new_routing_tags = existing.routing_tags | updates.get("routing_tags", set())
        new_safety_policies = {**existing.safety_policies, **updates.get("safety_policies", {})}
        new_default_behaviors = updates.get("default_behaviors", existing.default_behaviors)
        new_behavior_config = {**existing.behavior_config, **updates.get("behavior_config", {})}
        new_zone_affinity = updates.get("zone_affinity", existing.zone_affinity)
        new_environment_constraints = {**existing.environment_constraints, **updates.get("environment_constraints", {})}
        
        updated = RoleProfile(
            name=existing.name,
            default_skills=new_default_skills,
            allowed_tools=new_allowed_tools,
            visibility_scopes=new_visibility_scopes,
            routing_tags=new_routing_tags,
            safety_policies=new_safety_policies,
            default_behaviors=new_default_behaviors,
            behavior_config=new_behavior_config,
            zone_affinity=new_zone_affinity,
            environment_constraints=new_environment_constraints,
        )
        
        self.register(updated)
        return updated

    def to_json(self, indent: Optional[int] = 2) -> str:
        payload = {
            p.name.value: {
                "default_skills": p.default_skills,
                "allowed_tools": sorted(p.allowed_tools),
                "default_behaviors": p.default_behaviors,
                "behavior_config": p.behavior_config,
                "zone_affinity": p.zone_affinity,
                "environment_constraints": p.environment_constraints,
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
    
    Registry Synchronization (Distributed Systems):
    In a distributed Ray cluster, dynamic role registrations on one node may not
    immediately propagate to other nodes. Consider implementing:
    - Redis-backed store for dynamic specializations (shared state)
    - Registry Sync subtask that periodically syncs SpecializationManager across nodes
    - Event-driven sync via Ray pub/sub or similar mechanism
    - Or ensure all dynamic registrations happen on the Control Plane and are
      broadcast to all Organs via Organ.update_role_registry()
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
                # Preserve all fields including default_behaviors, behavior_config, zone_affinity, and environment_constraints
                profile = RoleProfile(
                    name=actual_spec,
                    default_skills=role_profile.default_skills,
                    allowed_tools=role_profile.allowed_tools,
                    visibility_scopes=role_profile.visibility_scopes,
                    routing_tags=role_profile.routing_tags,
                    safety_policies=role_profile.safety_policies,
                    default_behaviors=list(role_profile.default_behaviors),
                    behavior_config=dict(role_profile.behavior_config),
                    zone_affinity=list(role_profile.zone_affinity),
                    environment_constraints=dict(role_profile.environment_constraints),
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
        
        # Handle case where dynamic_specializations is None or empty (e.g., empty YAML section)
        dynamic_specs = config.get('dynamic_specializations')
        if not dynamic_specs or not isinstance(dynamic_specs, dict):
            return 0
        
        loaded = 0
        for value, spec_config in dynamic_specs.items():
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
                        # Behavior Plugin System: Load default_behaviors and behavior_config from YAML
                        default_behaviors=list(role_profile_data.get('default_behaviors', [])),
                        behavior_config=dict(role_profile_data.get('behavior_config', {})),
                        # Zone-scoped role profiles
                        zone_affinity=list(role_profile_data.get('zone_affinity', [])),
                        environment_constraints=dict(role_profile_data.get('environment_constraints', {})),
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
                        'default_behaviors': profile.default_behaviors,
                        'behavior_config': profile.behavior_config,
                        'zone_affinity': profile.zone_affinity,
                        'environment_constraints': profile.environment_constraints,
                    }
                
                config['dynamic_specializations'][value] = spec_config
        
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        
        self._config_path = config_path
    
    def get_role_profile(self, spec: Union[Specialization, DynamicSpecialization, str]) -> Optional[RoleProfile]:
        """
        Get role profile for a specialization (static or dynamic).
        
        Args:
            spec: Specialization enum, DynamicSpecialization, or string value
            
        Returns:
            RoleProfile if found, None otherwise
        """
        with self._lock:
            if isinstance(spec, str):
                spec = self.get_safe(spec)
                if not spec:
                    return None
            
            # Normalize to lowercase value for lookup
            if hasattr(spec, 'value'):
                value = spec.value.lower()
            else:
                value = str(spec).lower()
            
            # Check dynamic specializations (stored in _role_profiles)
            if value in self._role_profiles:
                return self._role_profiles[value]
            
            # Static specializations don't store profiles here
            # Caller should check DEFAULT_ROLE_REGISTRY
            return None
    
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