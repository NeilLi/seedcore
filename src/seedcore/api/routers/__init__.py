"""
Router registry for the supported SeedCore API surface.
"""

from __future__ import annotations

import sys
from importlib import import_module

ACTIVE_ROUTER_SPECS = (
    ("Tasks", "tasks_router"),
    ("Replay", "replay_router"),
    ("Agent Actions", "agent_actions_router"),
    ("Source Registrations", "source_registrations_router"),
    ("Tracking Events", "tracking_events_router"),
    ("Identity", "identity_router"),
    ("Transfer Approvals", "transfer_approvals_router"),
    ("Custody", "custody_router"),
    ("Control", "control_router"),
    ("Advisory", "advisory_router"),
    ("PKG", "pkg_router"),
    ("Capabilities", "capabilities_router"),
)

LEGACY_ROUTER_NAMES = (
    "dspy_router",
    "energy_router",
    "holon_router",
    "mfb_router",
    "ocps_router",
    "organism_router",
    "salience_router",
)

_ROUTER_MODULES = {
    "tasks_router": ".tasks_router",
    "replay_router": ".replay_router",
    "agent_actions_router": ".agent_actions_router",
    "source_registrations_router": ".source_registrations_router",
    "tracking_events_router": ".tracking_events_router",
    "identity_router": ".identity_router",
    "transfer_approvals_router": ".transfer_approvals_router",
    "custody_router": ".custody_router",
    "control_router": ".control_router",
    "advisory_router": ".advisory_router",
    "pkg_router": ".pkg_router",
    "capabilities_router": ".capabilities_router",
    "dspy_router": ".legacy.dspy_router",
    "energy_router": ".legacy.energy_router",
    "holon_router": ".legacy.holon_router",
    "mfb_router": ".legacy.mfb_router",
    "ocps_router": ".legacy.ocps_router",
    "organism_router": ".legacy.organism_router",
    "salience_router": ".legacy.salience_router",
}

ACTIVE_ROUTER_NAMES = tuple(name for _, name in ACTIVE_ROUTER_SPECS)

__all__ = [
    *ACTIVE_ROUTER_NAMES,
    *LEGACY_ROUTER_NAMES,
    "ACTIVE_ROUTER_NAMES",
    "ACTIVE_ROUTER_SPECS",
    "LEGACY_ROUTER_NAMES",
    "get_active_routers",
]


def __getattr__(name: str):
    module_name = _ROUTER_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    attr_candidates = ("mfb_router", "router") if name == "mfb_router" else ("router", name)
    for attr_name in attr_candidates:
        if hasattr(module, attr_name):
            return getattr(module, attr_name)
    module_label = getattr(module, "__name__", type(module).__name__)
    raise AttributeError(f"router module {module_label!r} has no export for {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


def get_active_routers():
    module = sys.modules[__name__]
    return tuple((tag, getattr(module, name)) for tag, name in ACTIVE_ROUTER_SPECS)
