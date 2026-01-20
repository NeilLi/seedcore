#!/usr/bin/env python3
"""
Base class for Agent Behaviors.

Behaviors are pluggable capabilities that extend BaseAgent functionality
without requiring code changes. They can be configured via:
- RoleProfile.default_behaviors
- organs.yaml
- pkg_subtask_types.default_params.executor.behaviors
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class AgentBehavior(ABC):
    """
    Base class for all agent behaviors.
    
    Behaviors extend BaseAgent functionality in a modular, configurable way.
    Each behavior can hook into agent lifecycle events:
    - initialize: Called during agent __init__
    - execute_task_pre: Called before task execution
    - execute_task_post: Called after task execution
    - shutdown: Called during agent shutdown
    
    Behaviors are configured via behavior_config dict passed during initialization.
    """

    def __init__(self, agent: Any, config: Optional[Dict[str, Any]] = None):
        """
        Initialize behavior with agent instance and configuration.
        
        Args:
            agent: BaseAgent instance (or subclass)
            config: Behavior-specific configuration dict
        """
        self.agent = agent
        self.config = config or {}
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> None:
        """
        Initialize behavior (called during agent initialization).
        
        This is where behaviors set up their state, register hooks, etc.
        """
        pass

    async def execute_task_pre(
        self, task: Any, task_dict: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Hook called before task execution.
        
        Args:
            task: Task object (TaskPayload or dict)
            task_dict: Task as dict (for easy manipulation)
            
        Returns:
            Modified task_dict or None (None means no changes)
        """
        return None

    async def execute_task_post(
        self, task: Any, task_dict: Dict[str, Any], result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Hook called after task execution.
        
        Args:
            task: Task object (TaskPayload or dict)
            task_dict: Task as dict
            result: Execution result dict
            
        Returns:
            Modified result dict or None (None means no changes)
        """
        return None

    async def shutdown(self) -> None:
        """
        Cleanup on agent shutdown.
        
        Behaviors should clean up resources, cancel background tasks, etc.
        """
        pass

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value with optional default."""
        return self.config.get(key, default)

    def is_enabled(self) -> bool:
        """Check if behavior is enabled (default: True unless config says otherwise)."""
        return self.config.get("enabled", True)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(enabled={self.is_enabled()})"
