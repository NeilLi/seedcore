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
- PersistentAgent: Stateful wrapper with memory (Mw/Mlt) and checkpointing
- ObserverAgent: Proactive cache warmer
- UtilityLearningAgent: System observer and tuner
"""

from __future__ import annotations

import os
import uuid
import ray  # pyright: ignore[reportMissingImports]
import asyncio
import random
import time
from typing import Dict, Any, Optional, List, TYPE_CHECKING, Tuple

# --- Core SeedCore Imports ---
from ..logging_setup import ensure_serve_logger

# Runtime imports for things used in code
from ..agents.roles.specialization import Specialization  # ← needed at runtime

# Type alias for readability (after ray import)
AgentHandle = ray.actor.ActorHandle

if TYPE_CHECKING:
    from ..agents.roles.specialization import RoleRegistry
    from ..agents.roles.skill_vector import SkillStoreProtocol
    from ..tools.manager import ToolManager
    from ..serve.cognitive_client import CognitiveServiceClient
    # --- Add imports for stateful dependencies ---
    from ..memory.mw_manager import MwManager
    from ..memory.holon_fabric import HolonFabric

logger = ensure_serve_logger("seedcore.Organ", level="DEBUG")

# Target namespace for agent actors
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))


class AgentIDFactory:
    """
    Factory for generating agent IDs based on organ_id and specialization.
    
    Provides consistent ID generation across the system. OrganismCore typically
    uses this factory to generate IDs before calling Organ.create_agent().
    
    IMPORTANT: agent_id is a permanent, immutable identity. It includes organ_id
    only as part of the creation context, but agent_id does NOT imply current organ
    residence after migration. Agents can be transferred between organs via
    register_agent() without changing their ID.
    """
    
    def new(self, organ_id: str, spec: Specialization) -> str:
        """
        Generate a stable, unique agent ID.
        
        NOTE: agent_id is a permanent identity. It includes organ_id only
        as part of the creation context, but agent_id does NOT imply
        current organ residence after migration.
        
        Args:
            organ_id: ID of the organ this agent belongs to (at creation time)
            spec: Agent specialization
            
        Returns:
            Generated agent ID string (format: agent_{organ_id}_{spec_safe}_{unique12})
        """
        # Use short UUID hex (12 chars) for readability, similar to ULID length
        # Collision probability: 16^12 ≈ 2^48 space → extremely safe even at millions of agents
        # Can be swapped for actual ULID library if time-sorted IDs are needed
        unique_id = uuid.uuid4().hex[:12]
        
        # Normalize specialization value to be safe in Ray actor names
        # Replace potentially unsafe characters: / . - → _
        spec_safe = spec.value.replace("/", "_").replace(".", "_").replace("-", "_")
        
        return f"agent_{organ_id}_{spec_safe}_{unique_id}"


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
        tool_handler: Any,  # Can be ToolManager or List[ToolManagerShard]
        cognitive_client: "CognitiveServiceClient",
        # --- Optional stateful dependencies (for PersistentAgent) ---
        mw_manager: Optional["MwManager"] = None,
        holon_fabric: Optional["HolonFabric"] = None,
        checkpoint_cfg: Optional[Dict[str, Any]] = None,
        # --- Optional AgentIDFactory for ID generation ---
        agent_id_factory: Optional[AgentIDFactory] = None,
    ):
        self.organ_id = organ_id
        
        # Injected global singletons
        self.role_registry = role_registry
        self.skill_store = skill_store
        self.tool_handler = tool_handler
        # We store the *client*, not just the URL, for consistency
        self.cognitive_client = cognitive_client 

        # --- Store stateful dependencies to pass to agents ---
        self.mw_manager = mw_manager
        self.holon_fabric = holon_fabric
        self.checkpoint_cfg = checkpoint_cfg or {"enabled": False}
        
        # --- Optional AgentIDFactory for ID generation ---
        # NOTE: Currently unused - OrganismCore generates IDs before calling create_agent().
        # This is kept for future use cases where Organ might need to generate IDs dynamically.
        self.agent_id_factory = agent_id_factory

        # Agent registry: { agent_id -> ActorHandle }
        self.agents: Dict[str, AgentHandle] = {}
        # Agent metadata: { agent_id -> AgentInfo }
        self.agent_info: Dict[str, Dict[str, Any]] = {}
        
        logger.info(f"✅ Organ actor {self.organ_id} created.")

    async def health_check(self) -> bool:
        """Called by OrganismCore on startup."""
        # Check that shared dependencies are configured
        return (
            self.tool_handler is not None
            and self.role_registry is not None
            and self.skill_store is not None
            and self.cognitive_client is not None
        )
        
    async def ping(self) -> bool:
        """Lightweight liveness check for OrganismCore's health loop."""
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
        Creates, registers, and stores a new BaseAgent or PersistentAgent actor.
        
        Args:
            agent_id: Unique identifier for the agent
            specialization: Agent specialization (GEA, AAC, etc.)
            organ_id: ID of the organ (for verification)
            agent_class_name: Type of agent to create. Options:
                - "BaseAgent" (default): Stateless, generic executor
                - "PersistentAgent": Stateful wrapper with memory and checkpointing
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
            if agent_class_name == "PersistentAgent":
                from ..agents.persistent_agent import PersistentAgent as AgentToCreate
                
                # Parameters for the STATEFUL PersistentAgent
                agent_params = {
                    "agent_id": agent_id,
                    "tool_handler": self.tool_handler,
                    "specialization": specialization,
                    "role_registry": self.role_registry,
                    "skill_store": self.skill_store,
                    "cognitive_client": self.cognitive_client,
                    "organ_id": self.organ_id,
                    "mw_manager": self.mw_manager,
                    "holon_fabric": self.holon_fabric,
                    "checkpoint_cfg": self.checkpoint_cfg
                }
            elif agent_class_name == "ObserverAgent":
                from ..agents.observer_agent import ObserverAgent as AgentToCreate
                
                # Parameters for ObserverAgent (extends BaseAgent)
                agent_params = {
                    "agent_id": agent_id,
                    "tool_handler": self.tool_handler,
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
                    "tool_handler": self.tool_handler,
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
                    "tool_handler": self.tool_handler,
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
                "specialization": specialization.name,  # Store enum name for matching
                "specialization_value": specialization.value,  # Also store value for compatibility
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
        
        # Update status to indicate this is a respawned agent
        if agent_id in self.agent_info:
            self.agent_info[agent_id]["status"] = "respawned"

    async def register_agent(
        self,
        agent_id: str,
        handle: AgentHandle,
        info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Register an existing agent handle into this organ.
        
        Used by OrganismCore during organ merge/retire operations to transfer
        agents between organs without recreating them.
        
        Args:
            agent_id: Unique identifier for the agent
            handle: Ray actor handle for the existing agent
            info: Optional metadata dict. If not provided, a minimal stub is created.
        """
        if agent_id in self.agents:
            logger.warning(
                f"[{self.organ_id}] Agent {agent_id} already exists, overwriting registration."
            )
        
        self.agents[agent_id] = handle

        # Preserve existing info if provided, otherwise create a stub.
        existing = self.agent_info.get(agent_id, {})
        info = info or existing or {
            "agent_id": agent_id,
            "specialization": "GENERALIST",
            "specialization_value": "generalist",
            "class": "BaseAgent",
            "created_at": time.time(),
            "status": "registered",
        }
        self.agent_info[agent_id] = info

        logger.info(
            f"[{self.organ_id}] Registered existing agent {agent_id} via register_agent()"
        )
        
    # ==========================================================
    # Introspection (Called by OrganismCore & StateService)
    # ==========================================================
    
    async def get_agent_handle(self, agent_id: str) -> Optional[AgentHandle]:
        """Returns the handle for a specific agent."""
        return self.agents.get(agent_id)

    async def get_agent_handles(self) -> Dict[str, AgentHandle]:
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
        
        Actually pings agents to determine liveness, so OrganismCore's
        reconciliation loop can detect and respawn dead agents.
        """
        agent_statuses = {}

        for agent_id, handle in self.agents.items():
            alive = True
            try:
                # Try to ping the agent via get_heartbeat (most agents implement this)
                if hasattr(handle, "get_heartbeat"):
                    ref = handle.get_heartbeat.remote()
                    # Small timeout to avoid hanging
                    await asyncio.wait_for(
                        asyncio.to_thread(ray.get, ref),
                        timeout=2.0,
                    )
                else:
                    # Fallback: try a lightweight ping if available
                    # If Ray can't talk to the actor, an exception will be raised
                    # This is a best-effort check
                    try:
                        # Try accessing actor metadata as a lightweight check
                        _ = handle.__class__.__name__
                    except Exception:
                        alive = False
            except Exception:
                alive = False

            agent_statuses[agent_id] = {
                "status": "registered" if alive else "unreachable",
                "alive": alive,
            }
                
        return {
            "organ_id": self.organ_id,
            "status": "healthy",  # organ-level; could down-rank if many agents are dead
            "agent_count": len(self.agents),
            "agents": agent_statuses,
        }

    # ==========================================================
    # Telemetry & Stats (Per-Organ Agent Statistics)
    # ==========================================================

    async def collect_agent_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect summary statistics from all agents in this organ.
        
        Returns:
            Dictionary mapping agent_id -> stats dict (whatever agent.get_summary_stats() returns)
        """
        if not self.agents:
            return {}

        timeout = float(os.getenv("ORGAN_STATS_TIMEOUT", "2.5"))
        items = list(self.agents.items())
        stats: Dict[str, Dict[str, Any]] = {}

        async def _get_stats(agent_id: str, handle: AgentHandle):
            try:
                ref = handle.get_summary_stats.remote()
                res = await asyncio.wait_for(
                    asyncio.to_thread(ray.get, ref),
                    timeout=timeout,
                )
                stats[agent_id] = res
            except Exception as e:
                logger.debug(f"[{self.organ_id}] Stats error for {agent_id}: {e}")

        tasks = [_get_stats(agent_id, handle) for agent_id, handle in items]
        await asyncio.gather(*tasks, return_exceptions=True)

        logger.debug(f"[{self.organ_id}] ✅ Collected stats: {len(stats)}/{len(items)}")
        
        # Warn if we have agents but collected no stats
        if len(items) > 0 and len(stats) == 0:
            logger.warning(
                f"[{self.organ_id}] No stats collected from {len(items)} agents - "
                "agents may not support get_summary_stats() or may be unreachable"
            )
        
        return stats

    async def get_summary(self) -> Dict[str, Any]:
        """
        Compute a simple per-organ summary over agent stats.
        
        Returns:
            Dictionary with organ-level aggregated statistics
        """
        stats = await self.collect_agent_stats()
        if not stats:
            return {
                "organ_id": self.organ_id,
                "agent_count": len(self.agents),
                "status": "no_agents",
            }

        total_agents = len(stats)
        total_tasks = sum(s.get("tasks_processed", 0) for s in stats.values())
        avg_cap = (
            sum(s.get("capability_score", 0.0) for s in stats.values()) / total_agents
            if total_agents > 0 else 0.0
        )
        avg_mem = (
            sum(s.get("mem_util", 0.0) for s in stats.values()) / total_agents
            if total_agents > 0 else 0.0
        )

        # Calculate organ-level metrics
        total_memory_writes = sum(s.get("memory_writes", 0) for s in stats.values())
        total_peer_interactions = sum(
            s.get("peer_interactions_count", 0) for s in stats.values()
        )

        return {
            "organ_id": self.organ_id,
            "agent_count": total_agents,
            "total_tasks_processed": total_tasks,
            "average_capability_score": avg_cap,
            "average_memory_utilization": avg_mem,
            "total_memory_writes": total_memory_writes,
            "total_peer_interactions": total_peer_interactions,
            "status": "active",
        }

    async def get_agent_private_memory(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch private memory vector & telemetry for a single agent in this organ.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Dictionary with 'h' (memory vector) and 'telemetry', or None if not found
        """
        handle = self.agents.get(agent_id)
        if not handle:
            logger.warning(
                f"[{self.organ_id}] Agent {agent_id} not found for private memory fetch"
            )
            return None
        try:
            h_ref = handle.get_private_memory_vector.remote()
            tel_ref = handle.get_private_memory_telemetry.remote()
            # Fetch both concurrently to reduce latency (single RPC instead of two sequential)
            h, tel = await asyncio.to_thread(lambda: ray.get(h_ref, tel_ref))
            return {"h": h, "telemetry": tel}
        except Exception:
            # Legacy fallback
            try:
                state_ref = handle.get_state.remote()
                state = await asyncio.to_thread(ray.get, state_ref)
                return {"h": state.get("h")}
            except Exception as e:
                logger.error(
                    f"[{self.organ_id}] Failed to get private memory for {agent_id}: {e}"
                )
                return None

    async def fetch_agent_memory_with_cache(
        self, agent_id: str, item_id: str
    ) -> Optional[Any]:
        """
        Full cache → LTM fetch via the agent.
        
        Args:
            agent_id: Agent identifier
            item_id: Item identifier to fetch
            
        Returns:
            Fetched data or None if not found
        """
        handle = self.agents.get(agent_id)
        if not handle:
            logger.warning(
                f"[{self.organ_id}] Agent {agent_id} not found for memory fetch"
            )
            return None
        try:
            ref = handle.fetch_with_cache.remote(item_id)
            data = await asyncio.to_thread(ray.get, ref)
            return data
        except Exception as e:
            logger.error(
                f"[{self.organ_id}] Failed to fetch memory via agent {agent_id}: {e}"
            )
            return None

    async def reset_agent_metrics(self, agent_id: str) -> bool:
        """
        Reset metrics for a specific agent in this organ.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            True if successful, False otherwise
        """
        handle = self.agents.get(agent_id)
        if not handle:
            return False
        try:
            ref = handle.reset_metrics.remote()
            await asyncio.to_thread(ray.get, ref)
            logger.info(f"[{self.organ_id}] 🔄 Reset metrics for agent {agent_id}")
            return True
        except Exception as e:
            logger.error(
                f"[{self.organ_id}] Failed to reset metrics for agent {agent_id}: {e}"
            )
            return False

    def generate_agent_id(self, specialization: "Specialization") -> str:
        """
        Generate a new agent ID using AgentIDFactory if available.
        
        NOTE: Currently unused - OrganismCore generates IDs before calling create_agent(),
        and respawn_agent() reuses the same agent_id. This method is kept for future
        use cases where Organ might need to generate IDs dynamically.
        
        Args:
            specialization: Agent specialization
            
        Returns:
            Generated agent ID string
        """
        if self.agent_id_factory:
            return self.agent_id_factory.new(self.organ_id, specialization)
        # Fallback: simple ID generation if factory not available
        unique_id = uuid.uuid4().hex[:12]
        return f"agent_{self.organ_id}_{specialization.value}_{unique_id}"

    # ==========================================================
    # Routing (Called by OrganismCore)
    # ==========================================================

    async def pick_random_agent(self) -> Tuple[Optional[str], Optional[AgentHandle]]:
        """Returns a random agent_id and handle from this organ."""
        if not self.agents:
            return None, None
        try:
            agent_id = random.choice(list(self.agents.keys()))
            return agent_id, self.agents[agent_id]
        except Exception:
            return None, None  # Race condition if dict empty

    async def pick_agent_by_specialization(self, spec_name: str) -> Tuple[Optional[str], Optional[AgentHandle]]:
        """
        Finds an agent matching the specialization.
        
        Accepts either enum name (e.g., "DEVICE_ORCHESTRATOR") or value (e.g., "device_orchestrator").
        Matching is case-insensitive for robustness.
        
        This is a simple, non-load-balanced lookup.
        """
        spec_norm = spec_name.lower()
        
        # Try to match against stored specialization name (enum name)
        for agent_id, info in self.agent_info.items():
            stored_name = info.get("specialization", "").lower()
            stored_value = info.get("specialization_value", "").lower()
            
            # Match against either name or value (case-insensitive)
            if stored_name == spec_norm or stored_value == spec_norm:
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

    
