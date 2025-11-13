# Copyright 2024 SeedCore Contributors
# ... (license) ...

"""
WorkerAgent (Ray Actor)

This class is the standard, spawnable "worker" for the organism.
It is a thin Ray wrapper around the BaseAgent, which contains all
the core logic for specialization, RBAC, and task execution.
"""

from __future__ import annotations

import ray  # pyright: ignore[reportMissingImports]
from typing import Optional

from .base import BaseAgent
from .roles import Specialization, RoleRegistry, SkillStoreProtocol
from ..tools.manager import ToolManager

# Note: MwManager and LongTermMemoryManager are no longer imported here.
# This agent interacts with memory *only* through its injected ToolManager.

# The @ray.remote decorator turns the BaseAgent "blueprint"
# into a "worker" that can be spawned on the cluster.
@ray.remote
class WorkerAgent(BaseAgent):
    """
    This is the Ray-enabled BaseAgent.
    The Organ (new Tier0) spawns this class.
    """
    
    def __init__(
        self,
        agent_id: str,
        *,
        tool_manager: ToolManager,
        specialization: Specialization,
        role_registry: RoleRegistry,
        skill_store: SkillStoreProtocol,
        cognitive_base_url: Optional[str] = None,
        organ_id: Optional[str] = None,
        initial_capability: float = 0.5,
        initial_mem_util: float = 0.0,
    ):
        """
        Initializes the BaseAgent logic with all injected dependencies.
        
        This worker is "memory-blind" and only knows about its ToolManager.
        Memory access is handled by calling tools like 'mem.read'.
        """
        super().__init__(
            agent_id=agent_id,
            tool_manager=tool_manager,
            specialization=specialization,
            role_registry=role_registry,
            skill_store=skill_store,
            cognitive_base_url=cognitive_base_url,
            initial_capability=initial_capability,
            initial_mem_util=initial_mem_util,
            organ_id=organ_id,
        )
        
        # The legacy properties for mw_manager and ltm_manager
        # have been removed to ensure this is a "clean" agent.

    def get_id(self) -> str:
        """Helper to confirm the agent's ID."""
        return self.agent_id