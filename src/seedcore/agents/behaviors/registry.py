#!/usr/bin/env python3
"""
Behavior Registry for managing and instantiating agent behaviors.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Type

from .base import AgentBehavior
from .chat_history import ChatHistoryBehavior
from .background_loop import BackgroundLoopBehavior
from .task_filter import TaskFilterBehavior
from .tool_registration import ToolRegistrationBehavior
from .dedup import DedupBehavior
from .safety_check import SafetyCheckBehavior
from .tool_auto_injection import ToolAutoInjectionBehavior

logger = logging.getLogger(__name__)


class BehaviorRegistry:
    """
    Registry for agent behaviors.
    
    Maps behavior names to behavior classes and manages instantiation.
    """

    # Built-in behavior classes
    _BEHAVIOR_CLASSES: Dict[str, Type[AgentBehavior]] = {
        "chat_history": ChatHistoryBehavior,
        "background_loop": BackgroundLoopBehavior,
        "task_filter": TaskFilterBehavior,
        "tool_registration": ToolRegistrationBehavior,
        "dedup": DedupBehavior,
        "safety_check": SafetyCheckBehavior,
        "tool_auto_injection": ToolAutoInjectionBehavior,
    }

    def __init__(self):
        """Initialize registry with built-in behaviors."""
        self._behaviors: Dict[str, Type[AgentBehavior]] = dict(self._BEHAVIOR_CLASSES)

    def register(self, name: str, behavior_class: Type[AgentBehavior]) -> None:
        """
        Register a custom behavior class.
        
        Args:
            name: Behavior name (e.g., "custom_behavior")
            behavior_class: Behavior class (subclass of AgentBehavior)
        """
        if not issubclass(behavior_class, AgentBehavior):
            raise TypeError(f"Behavior class must subclass AgentBehavior, got {behavior_class}")
        self._behaviors[name] = behavior_class
        logger.info(f"Registered behavior: {name} -> {behavior_class.__name__}")

    def get(self, name: str) -> Optional[Type[AgentBehavior]]:
        """Get behavior class by name."""
        return self._behaviors.get(name)

    def create_behaviors(
        self,
        agent: Any,
        behavior_names: List[str],
        behavior_configs: Dict[str, Dict[str, Any]],
    ) -> List[AgentBehavior]:
        """
        Create behavior instances for an agent.
        
        Args:
            agent: BaseAgent instance
            behavior_names: List of behavior names to instantiate
            behavior_configs: Dict mapping behavior name -> config dict
            
        Returns:
            List of initialized AgentBehavior instances
        """
        behaviors = []
        for name in behavior_names:
            behavior_class = self.get(name)
            if not behavior_class:
                logger.warning(
                    f"Unknown behavior '{name}' for agent {agent.agent_id}. Skipping."
                )
                continue

            config = behavior_configs.get(name, {})
            try:
                behavior = behavior_class(agent, config)
                behaviors.append(behavior)
                logger.debug(
                    f"Created behavior '{name}' for agent {agent.agent_id} with config {config}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to create behavior '{name}' for agent {agent.agent_id}: {e}",
                    exc_info=True,
                )
        return behaviors

    def list_available(self) -> List[str]:
        """List all available behavior names."""
        return list(self._behaviors.keys())


# Global registry instance
_default_registry: Optional[BehaviorRegistry] = None


def create_behavior_registry() -> BehaviorRegistry:
    """Get or create the default behavior registry (singleton)."""
    global _default_registry
    if _default_registry is None:
        _default_registry = BehaviorRegistry()
    return _default_registry
