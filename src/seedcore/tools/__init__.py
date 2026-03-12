#!/usr/bin/env python
# seedcore/tools/__init__.py

"""
SeedCore Tools Module.

Keep optional tool namespaces lazy so default API/runtime services do not pull
in ML-only integrations during package import.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from .manager import Tool, ToolError, ToolManager

_LAZY_SUBMODULES = {
    "memory_tools",
    "training_tools",
    "calculator_tool",
    "query_tools",
    "vla_discovery_tools",
    "vla_analysis_tools",
    "distillation_tools",
    "vla_tools",
}

__all__ = ["Tool", "ToolError", "ToolManager", *_LAZY_SUBMODULES]


def __getattr__(name: str) -> Any:
    if name in _LAZY_SUBMODULES:
        module = import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(list(globals().keys()) + list(_LAZY_SUBMODULES))
