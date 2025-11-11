# agents/roles/__init__.py
"""
Agents Roles Package

This package formalizes agent specialization, skills, RBAC, salience-aware routing,
and learning/evolution policies.

Exposed modules:
- specialization: Specialization enum, RoleProfile dataclass, RoleRegistry
- role_registry_defaults: DEFAULT_ROLE_REGISTRY and builder
- skill_vector: SkillVector and simple persistence protocol
- skill_learning: Outcome-driven skill updates and promotion/demotion policy
- rbac: Tool/data access enforcement based on RoleProfile
- routing: Capability advertisement and meta-controller routing
"""

from .specialization import (
    Specialization,
    RoleProfile,
    RoleRegistry,
)
from .role_registry_defaults import (
    DEFAULT_ROLE_REGISTRY,
    build_default_role_registry,
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
    # defaults
    "DEFAULT_ROLE_REGISTRY",
    "build_default_role_registry",
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


def make_default_roles() -> RoleRegistry:
    """
    Convenience factory that returns a fresh RoleRegistry populated with
    the default hotel-scenario profiles. Equivalent to build_default_role_registry().
    """
    return build_default_role_registry()
