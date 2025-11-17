#!/usr/bin/env python
#seedcore/tools/__init__.py

"""
SeedCore Tools Module

Provides the ToolManager and tool implementations for the Habitat Intelligence Organism.

Key components:
    - ToolManager: Enhanced tool manager with namespaces, RBAC, metrics, and tracing
    - Memory tools: Integration with MwManager and LongTermMemoryManager
    - Training tools: Agent skill progression and behavior training
"""

from .manager import Tool, ToolError, ToolManager
from . import memory_tools
from . import training_tools
from . import calculator_tool
from . import query_tools

__all__ = [
    "Tool",
    "ToolError",
    "ToolManager",
    "memory_tools",
    "training_tools",
    "calculator_tool",
    "query_tools",
]

