# Copyright 2024 SeedCore Contributors
# ... (license) ...

"""
Organ Actor (v2 - Lightweight Registry for Multiple Agent Types)

This class acts as an 'Organ' within the Organism. It is a stateful
Ray actor spawned by the OrganismCore and is responsible for:

- Spawning and managing a pool of agent actors (BaseAgent by default).
- Injecting shared resources (Tools, Memory Managers, Checkpointing) into its agents.
- Responding to calls from the OrganismCore (e.g., get_agent_handles).

THIS ACTOR IS PASSIVE. It does not run its own loops for polling or routing.
That logic is centralized in the OrganismCore and StateService.

The Organ supports multiple agent types:
- BaseAgent (default): Stateless, generic executor
- RayAgent: Stateful wrapper with memory (Mw/Mlt) and checkpointing
- ObserverAgent: Proactive cache warmer
- UtilityLearningAgent: System observer and tuner
"""

from __future__ import annotations

import os
import ray  # pyright: ignore[reportMissingImports]
import asyncio
import random
import time
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Tuple

# --- Core SeedCore Imports ---
from ..logging_setup import ensure_serve_logger

if TYPE_CHECKING:
    from ..agents.roles import (
        Specialization,
        RoleRegistry,
        SkillStoreProtocol
    )
    from ..tools.manager import ToolManager
    from ..serve.cognitive_client import CognitiveServiceClient
    # --- Add imports for stateful dependencies ---
    from ..memory.mw_manager import MwManager
    from ..memory.long_term_memory import LongTermMemoryManager

logger = ensure_serve_logger("seedcore.Organ", level="DEBUG")

# Target namespace for agent actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


@ray.remote
class Organ:
    """
    A Ray actor that serves as a simple agent registry and health tracker.
    
    This class implements all the `.remote()` methods that the
    OrganismCore needs to manage its pool of agents.
    """
    
    def __init__(
        self,
        organ_id: str,
        # --- Injected Dependencies from OrganismCore ---
        role_registry: "RoleRegistry",
        skill_store: "SkillStoreProtocol",
        tool_manager: "ToolManager",
        cognitive_client: "CognitiveServiceClient",
        # --- Optional stateful dependencies (for RayAgent) ---
        mw_manager: Optional["MwManager"] = None,
        ltm_manager: Optional["LongTermMemoryManager"] = None,
        checkpoint_cfg: Optional[Dict[str, Any]] = None,
    ):
        self.organ_id = organ_id
        
        # Injected global singletons
        self.role_registry = role_registry
        self.skill_store = skill_store
        self.tool_manager = tool_manager
        # We store the *client*, not just the URL, for consistency
        self.cognitive_client = cognitive_client 

        # --- Store stateful dependencies to pass to agents ---
        self.mw_manager = mw_manager
        self.ltm_manager = ltm_manager
        self.checkpoint_cfg = checkpoint_cfg or {"enabled": False}

        # Agent registry: { agent_id -> ActorHandle }
        self.agents: Dict[str, ray.actor.ActorHandle] = {}
        # Agent metadata: { agent_id -> AgentInfo }
        self.agent_info: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"✅ Organ actor {self.organ_id} created.")

    async def health_check(self) -> bool:
        """Called by OrganismCore on startup."""
        await asyncio.sleep(0)  # Be async
        return True
        
    async def ping(self) -> bool:
        """Lightweight liveness check for OrganismCore's health loop."""
        await asyncio.sleep(0)  # Be async
        return True

    # ==========================================================
    # Agent Lifecycle (Called by OrganismCore)
    # ==========================================================
    
    async def create_agent(
        self,
        agent_id: str,
        specialization: "Specialization",
        organ_id: str,  # Passed for verification
        agent_class_name: str = "BaseAgent",
        **agent_actor_options
    ) -> None:
        """
        Creates, registers, and stores a new BaseAgent or RayAgent actor.
        
        Args:
            agent_id: Unique identifier for the agent
            specialization: Agent specialization (GEA, AAC, etc.)
            organ_id: ID of the organ (for verification)
            agent_class_name: Type of agent to create. Options:
                - "BaseAgent" (default): Stateless, generic executor
                - "RayAgent": Stateful wrapper with memory and checkpointing
                - "ObserverAgent": Proactive cache warmer
                - "UtilityLearningAgent": System observer and tuner
            **agent_actor_options: Ray actor options (name, num_cpus, lifetime, etc.)
        """
        if agent_id in self.agents:
            logger.warning(f"[{self.organ_id}] Agent {agent_id} already exists.")
            return

        if self.organ_id != organ_id:
             logger.error(f"Organ ID mismatch! Expected {self.organ_id}, got {organ_id}")
             raise ValueError("Organ ID mismatch")

        try:
            logger.info(f"🚀 [{self.organ_id}] Creating {agent_class_name} '{agent_id}'...")
            
            # --- Dynamically choose agent class and params ---
            if agent_class_name == "RayAgent":
                from ..agents.ray_agent import RayAgent as AgentToCreate
                
                # Parameters for the STATEFUL RayAgent
                agent_params = {
                    "agent_id": agent_id,
                    "tool_manager": self.tool_manager,
                    "specialization": specialization,
                    "role_registry": self.role_registry,
                    "skill_store": self.skill_store,
                    "cognitive_client": self.cognitive_client,
                    "organ_id": self.organ_id,
                    "mw_manager": self.mw_manager,
                    "ltm_manager": self.ltm_manager,
                    "checkpoint_cfg": self.checkpoint_cfg
                }
            elif agent_class_name == "ObserverAgent":
                from ..agents.observer_agent import ObserverAgent as AgentToCreate
                
                # Parameters for ObserverAgent (extends BaseAgent)
                agent_params = {
                    "agent_id": agent_id,
                    "tool_manager": self.tool_manager,
                    "specialization": specialization,
                    "role_registry": self.role_registry,
                    "skill_store": self.skill_store,
                    "cognitive_client": self.cognitive_client,
                    "organ_id": self.organ_id
                }
            elif agent_class_name == "UtilityLearningAgent":
                from ..agents.ula_agent import UtilityLearningAgent as AgentToCreate
                
                # Parameters for UtilityLearningAgent (extends BaseAgent)
                agent_params = {
                    "agent_id": agent_id,
                    "tool_manager": self.tool_manager,
                    "specialization": specialization,
                    "role_registry": self.role_registry,
                    "skill_store": self.skill_store,
                    "cognitive_client": self.cognitive_client,
                    "organ_id": self.organ_id
                }
            else:
                # Default to BaseAgent
                from ..agents.base import BaseAgent as AgentToCreate
                
                # Parameters for the STATELESS BaseAgent
                agent_params = {
                    "agent_id": agent_id,
                    "tool_manager": self.tool_manager,
                    "specialization": specialization,
                    "role_registry": self.role_registry,
                    "skill_store": self.skill_store,
                    "cognitive_client": self.cognitive_client,
                    "organ_id": self.organ_id
                }

            # Create the agent actor
            handle = AgentToCreate.options(
                namespace=AGENT_NAMESPACE,
                get_if_exists=True,  # Re-attach if name already exists
                **agent_actor_options
            ).remote(**agent_params)

            # Store the handle and metadata
            self.agents[agent_id] = handle
            self.agent_info[agent_id] = {
                "agent_id": agent_id,
                "specialization": specialization.name,
                "class": agent_class_name,  # Track which class was created
                "created_at": time.time(),
                "status": "initializing",
            }
            logger.info(f"✅ [{self.organ_id}] Registered agent {agent_id} (class: {agent_class_name}).")
        except Exception as e:
            logger.error(f"[{self.organ_id}] Failed to create agent {agent_id}: {e}")
            raise

    async def remove_agent(self, agent_id: str) -> bool:
        """
        Removes an agent from the registry and terminates it.
        This is called by OrganismCore's `evolve` (scale_down).
        """
        logger.info(f"[{self.organ_id}] Removing agent {agent_id}...")
        self.agent_info.pop(agent_id, None)
        agent_handle = self.agents.pop(agent_id, None)
        
        if agent_handle:
            try:
                # Asynchronously terminate the actor
                ray.kill(agent_handle, no_restart=True)
                logger.info(f"[{self.organ_id}] Terminated agent {agent_id}.")
                return True
            except Exception as e:
                logger.warning(f"Failed to kill agent {agent_id}: {e}")
                # Still return True because it's gone from the registry
                return True
        return False  # Agent was not found in the registry

    async def respawn_agent(self, agent_id: str) -> None:
        """
        Recreates a dead agent with its previous info.
        This is called by OrganismCore's `_reconciliation_loop`.
        """
        info = self.agent_info.get(agent_id, {})
        if not info:
            raise ValueError(f"Cannot respawn {agent_id}: no info retained.")
            
        spec_name = info.get("specialization", "GENERALIST")
        spec = Specialization[spec_name.upper()]
        agent_class_name = info.get("class", "BaseAgent")  # Get the class
        
        # Re-run creation logic with preserved agent class
        await self.create_agent(
            agent_id=agent_id,
            specialization=spec,
            organ_id=self.organ_id,
            agent_class_name=agent_class_name,  # Pass the class
            name=agent_id,  # Re-use original name
            num_cpus=0.1,
            lifetime="detached"
        )
        
    # ==========================================================
    # Introspection (Called by OrganismCore & StateService)
    # ==========================================================
    
    async def get_agent_handle(self, agent_id: str) -> Optional[ray.actor.ActorHandle]:
        """Returns the handle for a specific agent."""
        return self.agents.get(agent_id)

    async def get_agent_handles(self) -> Dict[str, ray.actor.ActorHandle]:
        """
        Returns all agent handles managed by this organ.
        This is the main method used by OrganismCore to poll for the StateService.
        """
        return self.agents.copy()
        
    async def list_agents(self) -> List[str]:
        """Returns all agent IDs managed by this organ."""
        return list(self.agents.keys())
        
    async def get_agent_info(self, agent_id: str) -> Dict[str, Any]:
        """Returns the metadata for a specific agent."""
        return self.agent_info.get(agent_id, {"error": "not_found"})

    async def get_status(self) -> Dict[str, Any]:
        """
        Returns the health status of this organ and all its agents.
        (Called by OrganismCore's health loop)
        """
        # This is now a lightweight check.
        # The OrganismCore's health loop is responsible for
        # checking the Organ, and the StateService's aggregator
        # is responsible for checking all Agents.
        agent_statuses = {}

        for agent_id in self.agents.keys():
            # We report agents as "alive" if they're registered.
            # The StateService aggregator will do actual health checking via heartbeats.
            # OrganismCore's health loop uses the "alive" flag to detect unhealthy agents.
            agent_statuses[agent_id] = {
                "status": "registered",
                "alive": True  # Registered agents are assumed alive until proven otherwise
            }
                
        return {
            "organ_id": self.organ_id,
            "status": "healthy",
            "agent_count": len(self.agents),
            "agents": agent_statuses,
        }

    # ==========================================================
    # Routing (Called by OrganismCore)
    # ==========================================================

    async def pick_random_agent(self) -> Tuple[Optional[str], Optional[ray.actor.ActorHandle]]:
        """Returns a random agent_id and handle from this organ."""
        if not self.agents:
            return None, None
        try:
            agent_id = random.choice(list(self.agents.keys()))
            return agent_id, self.agents[agent_id]
        except Exception:
            return None, None  # Race condition if dict empty

    async def pick_agent_by_specialization(self, spec_name: str) -> Tuple[Optional[str], Optional[ray.actor.ActorHandle]]:
        """
        Finds an agent matching the specialization.
        This is a simple, non-load-balanced lookup.
        """
        for agent_id, info in self.agent_info.items():
            if info.get("specialization") == spec_name:
                handle = self.agents.get(agent_id)
                if handle:
                    return agent_id, handle
        
        # Fallback if no specific agent matches
        return await self.pick_random_agent()

    # ==========================================================
    # Shutdown
    # ==========================================================

    async def shutdown(self) -> None:
        """
        Terminates all agents owned by this organ.
        Called by OrganismCore's shutdown.
        """
        logger.info(f"[{self.organ_id}] Shutting down, terminating {len(self.agents)} agents...")
        agent_ids = list(self.agents.keys())
        tasks = []

        for agent_id in agent_ids:
            tasks.append(self.remove_agent(agent_id))
        
        await asyncio.gather(*tasks)
        logger.info(f"[{self.organ_id}] Shutdown complete.")

    # ==========================================================
    # REMOVED METHODS (Logic moved to other services)
    # ==========================================================
    
    # - execute_task_on_best_agent: REMOVED
    #   (Routing logic is now in OrganismCore, which calls agents directly)
    
    # - _heartbeat_loop: REMOVED
    #   (OrganismCore's health loop is responsible for polling organs)
    
    # - _collect_advertisements_loop: REMOVED
    #   (StateService's ProactiveAgentAggregator is responsible for polling agents)
    
    # - _repo_lazy: REMOVED
    #   (Organs no longer register themselves in the database)
    
    # - start: REMOVED
    #   (No background loops to start)
