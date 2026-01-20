# agents/behaviors/__init__.py
"""
Behavior Plugin System for SeedCore Agents.

Behaviors are pluggable capabilities that can be dynamically configured via:
- RoleProfile.default_behaviors (specialization-level defaults)
- organs.yaml agent config
- pkg_subtask_types.default_params.executor.behaviors (DNA registry)

This enables dynamic agent generation without code changes.
"""

from .base import AgentBehavior
from .registry import BehaviorRegistry, create_behavior_registry
from .chat_history import ChatHistoryBehavior
from .background_loop import BackgroundLoopBehavior
from .task_filter import TaskFilterBehavior
from .tool_registration import ToolRegistrationBehavior
from .dedup import DedupBehavior
from .safety_check import SafetyCheckBehavior
from .tool_auto_injection import ToolAutoInjectionBehavior

__all__ = [
    # Base
    "AgentBehavior",
    "BehaviorRegistry",
    "create_behavior_registry",
    # Behaviors
    "ChatHistoryBehavior",
    "BackgroundLoopBehavior",
    "TaskFilterBehavior",
    "ToolRegistrationBehavior",
    "DedupBehavior",
    "SafetyCheckBehavior",
    "ToolAutoInjectionBehavior",
]
