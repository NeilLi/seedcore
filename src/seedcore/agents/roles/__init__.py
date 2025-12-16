# agents/roles/__init__.py
"""
Agents Roles Package

This package formalizes agent specialization, skills, RBAC, salience-aware routing,
and learning/evolution policies.

Exposed modules:
- specialization: Specialization enum, RoleProfile dataclass, RoleRegistry
- role_registry_hospitality: HOSPITALITY_ROLE_REGISTRY and builder
- generic_defaults: DEFAULT_ROLE_REGISTRY (generic/minimal defaults)
- skill_vector: SkillVector and simple persistence protocol
- skill_learning: Outcome-driven skill updates and promotion/demotion policy
- rbac: Tool/data access enforcement based on RoleProfile
- routing: Capability advertisement and meta-controller routing
"""

from .specialization import (
    Specialization,
    RoleProfile,
    RoleRegistry,
    AgentSpec,
    GraphClient,
)
from .generic_defaults import (
    DEFAULT_ROLE_REGISTRY,
    create_default_registry,
)
from .role_registry_hospitality import (
    HOSPITALITY_ROLE_REGISTRY,
    build_hospitality_role_registry,
)
from .skill_vector import (
    SkillVector,
    SkillStoreProtocol,
    NullSkillStore,
)
from .skill_learning import (
    LearningConfig,
    PromotionPolicy,
    Outcome,
    SkillLearner,
)
from .rbac import (
    RbacEnforcer,
    AccessDecision,
)
from .routing import (
    AgentAdvertisement,
    Router,
    build_advertisement,
)

__all__ = [
    # specialization
    "Specialization",
    "RoleProfile",
    "RoleRegistry",
    "AgentSpec",
    "GraphClient",
    # generic defaults
    "DEFAULT_ROLE_REGISTRY",
    "create_default_registry",
    # hospitality registry
    "HOSPITALITY_ROLE_REGISTRY",
    "build_hospitality_role_registry",
    # skills
    "SkillVector",
    "SkillStoreProtocol",
    "NullSkillStore",
    # learning
    "LearningConfig",
    "PromotionPolicy",
    "Outcome",
    "SkillLearner",
    # rbac
    "RbacEnforcer",
    "AccessDecision",
    # routing
    "AgentAdvertisement",
    "Router",
    "build_advertisement",
]


def make_hospitality_roles() -> RoleRegistry:
    """
    Convenience factory that returns a fresh RoleRegistry populated with
    the hospitality hotel-scenario profiles. Equivalent to build_hospitality_role_registry().
    """
    return build_hospitality_role_registry()
