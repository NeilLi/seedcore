"""
API package for SeedCore.
"""

__all__ = ["tasks_router", "source_registrations_router"]


def __getattr__(name):
    if name == "tasks_router":
        from .routers import tasks_router

        return tasks_router
    if name == "source_registrations_router":
        from .routers import source_registrations_router

        return source_registrations_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
