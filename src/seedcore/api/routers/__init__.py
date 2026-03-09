"""
Router package for SeedCore API.
"""

__all__ = ["tasks_router"]


def __getattr__(name):
    if name == "tasks_router":
        from .tasks_router import router as tasks_router

        return tasks_router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
