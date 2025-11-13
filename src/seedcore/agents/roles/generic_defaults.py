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


def build_default_role_registry() -> RoleRegistry:
    """
    Build a generic, domain-agnostic default role registry.
    
    This registry provides minimal role profiles suitable for any domain.
    Domain-specific registries (e.g., hospitality) can override or extend
    these defaults at startup.
    """
    reg = RoleRegistry()

    # --- GENERALIST ---
    reg.register(
        RoleProfile(
            name=Specialization.GENERALIST,
            default_skills={
                "analysis": 0.6,
                "planning": 0.6,
                "communication": 0.6,
            },
            allowed_tools={
                T["mem_read"],
                T["mem_write"],
                T["notify"],
            },
            visibility_scopes={"global"},
            routing_tags={"default"},
            safety_policies={
                "max_autonomy": 0.5,
                "requires_human_review": 0.3,
            },
        )
    )

    return reg


# Export a ready-to-use default registry
DEFAULT_ROLE_REGISTRY: RoleRegistry = build_default_role_registry()

