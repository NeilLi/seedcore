"""
HAL Adapters
============

Converters between SeedCore JSON task payloads and SDK-native types.

Adapters handle the translation between:
- SeedCore TaskPayload v2.5 JSON structures
- SDK-specific types (NumPy arrays, SDK pose objects, etc.)
- Motion parameters (Energy, Warmth) -> driver configuration

This separation allows SeedCore core logic to remain SDK-agnostic while
supporting any robot platform through adapter implementations.
"""

from .pose_adapter import PoseAdapter, PoseFormat
from .motion_adapter import MotionAdapter
from .reachy_adapter import ReachyAdapter

__all__ = [
    "PoseAdapter",
    "PoseFormat",
    "MotionAdapter",
    "ReachyAdapter",
]
