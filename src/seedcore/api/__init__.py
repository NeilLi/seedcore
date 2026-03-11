"""
API package exports for the supported SeedCore router surface.
"""

from __future__ import annotations

from .routers import ACTIVE_ROUTER_NAMES, get_active_routers

__all__ = [*ACTIVE_ROUTER_NAMES, "get_active_routers"]


def __getattr__(name: str):
    if name in ACTIVE_ROUTER_NAMES:
        from . import routers

        return getattr(routers, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
