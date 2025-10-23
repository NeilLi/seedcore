# src/seedcore/__init__.py
"""
SeedCore - Scalable, database-backed task management system.

This package provides database models and utilities for task management.
Runtime dependencies like Ray are imported only when needed.

For model imports, use:
    from seedcore.models import Task, DatabaseTask, TaskPayload, TaskStatus, etc.
"""

__version__ = "1.0.0"
__author__ = "SeedCore Team"

__all__ = [
    "__version__",
    "__author__",
]
