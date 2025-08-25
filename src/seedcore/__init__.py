# src/seedcore/__init__.py
"""
SeedCore - Scalable, database-backed task management system.

This package provides database models and utilities for task management.
Runtime dependencies like Ray are imported only when needed.
"""

__version__ = "1.0.0"
__author__ = "SeedCore Team"

# Database models - these are safe to import as they only contain SQLAlchemy models
from .models.task import Task, TaskStatus, Base as TaskBase
from .models.fact import Fact, Base as FactBase

__all__ = [
    "__version__",
    "__author__",
    # Database models
    "Task",
    "TaskStatus", 
    "TaskBase",
    "Fact",
    "FactBase",
]
