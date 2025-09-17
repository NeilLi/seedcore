# Copyright 2024 SeedCore Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Tier 0 Memory Manager
Manages Ray agents and collects heartbeats for the meta-controller.
"""

from seedcore.logging_setup import setup_logging
setup_logging(app_name="seedcore.Tier0MemoryManager")


import os
import ray
import time
import asyncio
from ..utils.ray_utils import ensure_ray_initialized
from typing import Dict, List, Any, Optional
from collections import defaultdict
import logging
import json

from .ray_actor import RayAgent
from ..energy.optimizer import select_best_agent, score_agent
# Avoid importing EnergyLedger at module import time to prevent circular imports.
# We'll import it inside functions that need it.

logger = logging.getLogger("seedcore.Tier0MemoryManager")

# Target namespace for agent actors (prefer SEEDCORE_NS, fallback to RAY_NAMESPACE)
AGENT_NAMESPACE = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

class Tier0MemoryManager:
    """
    Manages Tier 0 per-agent memory (Ma) using Ray actors.
    
    Responsibilities:
    - Create and manage Ray agent actors
    - Collect heartbeats from all agents
    - Provide agent statistics and monitoring
    - Handle agent lifecycle management
    """
    
    def __init__(self):
        self.agents: Dict[str, Any] = {}  # agent_id -> Ray actor handle
        self.heartbeats: Dict[str, Dict[str, Any]] = {}  # agent_id -> latest heartbeat
        self.agent_stats: Dict[str, Dict[str, Any]] = {}  # agent_id -> summary stats
        self.last_collection = time.time()
        self.collection_interval = 5.0  # seconds
        # Track transient ping failures to avoid pruning on single hiccup
        self._ping_failures: Dict[str, int] = {}
        
        logger.info("✅ Tier0MemoryManager initialized")
        
        # Best-effort auto-discovery on init so that detached Ray actors get picked up
        try:
            self._refresh_agents_from_cluster()
        except Exception as e:
            logger.debug(f"Auto-discovery on init skipped: {e}")

        # Optional environment-driven attachment of known actor names
        try:
            import os
            attach_env = os.getenv("TIER0_ATTACH_ACTORS", "").strip()
            if attach_env:
                self._ensure_ray()
                # Support comma/semicolon/space-separated lists
                raw_parts = [p for sep in [",", ";", " "] for p in attach_env.split(sep)]
                candidate_names = [p.strip() for p in raw_parts if p and p.strip()]
                attached = 0
                for actor_name in candidate_names:
                    try:
                        # Try explicit namespace first (prefer SEEDCORE_NS), then fallback
                        try:
                            ns = AGENT_NAMESPACE
                            handle = ray.get_actor(actor_name, namespace=ns)
                        except Exception:
                            # Fallback to explicit namespace (prefer SEEDCORE_NS)
                            ns = AGENT_NAMESPACE
                            handle = ray.get_actor(actor_name, namespace=ns)
                        # Sanity check
                        resolved_id = ray.get(handle.get_id.remote())
                        self.attach_existing_actor(resolved_id, handle)
                        attached += 1
                    except Exception as e:
                        logger.debug(f"Env attach failed for {actor_name}: {e}")
                if attached:
                    logger.info(f"🔗 Attached {attached} actor(s) from TIER0_ATTACH_ACTORS")
        except Exception as e:
            logger.debug(f"Env-driven attachment skipped: {e}")
    
    def create_agent(
        self,
        agent_id: str,
        role_probs: Optional[Dict[str, float]] = None,
        *,
        name: Optional[str] = None,
        lifetime: Optional[str] = None,
        num_cpus: Optional[float] = None,
        num_gpus: Optional[float] = None,
        resources: Optional[Dict[str, float]] = None,
        namespace: Optional[str] = None,
        organ_id: Optional[str] = None,
    ) -> str:
        """
        Create a new Ray agent actor.
        
        Args:
            agent_id: Unique identifier for the agent
            role_probs: Initial role probabilities
            organ_id: ID of the organ this agent belongs to
            
        Returns:
            The agent ID if successful
        """
        if agent_id in self.agents:
            logger.warning(f"Agent {agent_id} already exists")
            return agent_id
        
        try:
            # Ensure Ray is initialized before creating actors
            self._ensure_ray()
            
            # Create the Ray actor
            options_kwargs: Dict[str, Any] = {}
            # Use a stable, detached, named actor when options are provided
            # Favor stable named, detached actors by default
            effective_name = name or agent_id if (lifetime or True) else name
            if effective_name:
                options_kwargs["name"] = effective_name
            # Default to detached lifetime if not specified
            options_kwargs["lifetime"] = lifetime or "detached"
            if num_cpus is not None:
                options_kwargs["num_cpus"] = num_cpus
            if num_gpus is not None:
                options_kwargs["num_gpus"] = num_gpus
            if resources:
                options_kwargs["resources"] = resources
            
            # Set namespace if provided, otherwise use environment default
            if namespace:
                options_kwargs["namespace"] = namespace
            else:
                # Get namespace from environment
                env_namespace = AGENT_NAMESPACE
                if env_namespace:
                    options_kwargs["namespace"] = env_namespace

            if options_kwargs:
                agent_handle = RayAgent.options(**options_kwargs).remote(
                    agent_id=agent_id,
                    initial_role_probs=role_probs,
                    organ_id=organ_id,
                )
            else:
                agent_handle = RayAgent.remote(agent_id, role_probs, organ_id)
            self.agents[agent_id] = agent_handle
            
            # Initialize heartbeat and stats
            self.heartbeats[agent_id] = {}
            self.agent_stats[agent_id] = {}
            
            logger.info(f"✅ Created Ray agent: {agent_id}")
            return agent_id
            
        except Exception as e:
            logger.error(f"Failed to create agent {agent_id}: {e}")
            # Log additional debugging information
            logger.error(f"Ray initialized: {ray.is_initialized()}")
            if ray.is_initialized():
                try:
                    runtime_context = ray.get_runtime_context()
                    logger.error(f"Ray namespace: {getattr(runtime_context, 'namespace', 'unknown')}")
                    logger.error(f"Ray address: {getattr(runtime_context, 'gcs_address', 'unknown')}")
                except Exception as ctx_e:
                    logger.error(f"Failed to get Ray context: {ctx_e}")
            raise
    
    def create_agents_batch(self, agent_configs: List[Dict[str, Any]]) -> List[str]:
        """
        Create multiple agents in batch.
        
        Args:
            agent_configs: List of agent configurations
                [{"agent_id": "agent_1", "role_probs": {...}}, ...]
                
        Returns:
            List of created agent IDs
        """
        created_ids = []
        for config in agent_configs:
            agent_id = config["agent_id"]
            role_probs = config.get("role_probs")
            # Optional Ray options passthrough
            name = config.get("name")
            lifetime = config.get("lifetime")
            num_cpus = config.get("num_cpus")
            num_gpus = config.get("num_gpus")
            resources = config.get("resources")
            namespace = config.get("namespace")
            try:
                self.create_agent(
                    agent_id,
                    role_probs,
                    name=name,
                    lifetime=lifetime,
                    num_cpus=num_cpus,
                    num_gpus=num_gpus,
                    resources=resources,
                    namespace=namespace,
                )
                created_ids.append(agent_id)
            except Exception as e:
                logger.error(f"Failed to create agent {agent_id}: {e}")
        
        logger.info(f"✅ Created {len(created_ids)} agents in batch")
        return created_ids
    
    def get_agent(self, agent_id: str) -> Optional[Any]:
        """
        Get a Ray agent actor handle.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Ray actor handle or None if not found
        """
        return self.agents.get(agent_id)
    
    def list_agents(self) -> List[str]:
        """Get list of all agent IDs.
        
        If no local registrations exist, attempt to discover detached RayAgent actors
        that are already running in the Ray cluster and attach them.
        """
        # Prefer returning only alive agents and refresh if registry is empty
        try:
            if not self.agents:
                self._refresh_agents_from_cluster()
        except Exception as e:
            logger.debug(f"Agent discovery failed during list: {e}")
        alive = self.prune_and_list()
        return [a["id"] for a in alive]

    # Health-aware listing and pruning
    def _alive(self, handle: Any) -> bool:
        try:
            ray.get(handle.ping.remote(), timeout=2.0)
            return True
        except Exception:
            return False

    def prune_and_list(self) -> List[Dict[str, Any]]:
        """Remove dead handles and return a simple list of alive agent ids."""
        if not self.agents:
            try:
                self._refresh_agents_from_cluster()
            except Exception as e:
                logger.debug(f"Agent discovery failed during prune: {e}")
        live: Dict[str, Any] = {}
        for agent_id, handle in list(self.agents.items()):
            if self._alive(handle):
                live[agent_id] = handle
                self._ping_failures[agent_id] = 0
            else:
                fails = self._ping_failures.get(agent_id, 0) + 1
                self._ping_failures[agent_id] = fails
                if fails >= 3:
                    logger.warning(f"Archiving agent after {fails} consecutive ping failures: {agent_id}")
                    try:
                        handle = self.agents.get(agent_id)
                        if handle and hasattr(handle, "archive"):
                            ray.get(handle.archive.remote())
                    except Exception:
                        logger.exception("archive() failed; detaching actor reference.")
                    finally:
                        self.agents.pop(agent_id, None)
                        self.heartbeats.pop(agent_id, None)
                        self.agent_stats.pop(agent_id, None)
        return [{"id": aid} for aid in live.keys()]

    # ---------------------------------------------------------------------
    # Cluster discovery and attachment helpers
    # ---------------------------------------------------------------------
    def attach_existing_actor(self, agent_id: str, handle: Any) -> None:
        """Attach a known Ray actor handle into the manager registry."""
        if agent_id not in self.agents:
            self.agents[agent_id] = handle
            self.heartbeats.setdefault(agent_id, {})
            self.agent_stats.setdefault(agent_id, {})

    def _ensure_ray(self, ray_address: Optional[str] = None, ray_namespace: Optional[str] = None):
        """Ensure Ray is initialized with the correct address and namespace."""
        if ray.is_initialized():
            logger.debug("Ray is already initialized, skipping connection")
            return
            
        # Get namespace from environment, default to "seedcore-dev" for consistency
        if ray_namespace is None:
            ray_namespace = os.getenv("SEEDCORE_NS", os.getenv("SEEDCORE_NS", "seedcore-dev"))
        
        # Get Ray connection parameters from environment
        if ray_address is None:
            ray_host = os.getenv("RAY_HOST", "seedcore-svc-head-svc")
            ray_port = os.getenv("RAY_PORT", "10001")
            ray_address = f"ray://{ray_host}:{ray_port}"
        
        # Use the centralized Ray initialization utility
        logger.info(f"Attempting to connect to Ray cluster at: {ray_address}")
        if not ensure_ray_initialized(ray_address=ray_address, ray_namespace=ray_namespace):
            raise RuntimeError(f"Failed to initialize Ray connection (address={ray_address}, namespace={ray_namespace})")
        logger.info(f"✅ Ray connection established successfully")

    def _refresh_agents_from_cluster(self) -> None:
        """Discover and attach existing RayAgent actors from the Ray cluster.
        
        This picks up detached, named Ray actors of class RayAgent that may
        have been started by other components (e.g., organisms) and registers
        them into this manager so API endpoints can see them.
        """
        self._ensure_ray()

        discovered: Dict[str, Any] = {}

        # Prefer public Ray state API when available
        try:
            # Ray 2.x public state API
            from ray.util.state import list_actors  # type: ignore
            actor_infos = list_actors()
            for info in actor_infos:
                try:
                    # Support both object-style and dict-style info
                    state_val = getattr(info, "state", None) if not isinstance(info, dict) else info.get("state")
                    state_str = str(state_val).upper() if state_val is not None else ""
                    if state_str and "ALIVE" not in state_str:
                        continue

                    name = (
                        getattr(info, "name", None)
                        if not isinstance(info, dict)
                        else info.get("name") or info.get("actor_name")
                    )
                    class_name = (
                        getattr(info, "class_name", None)
                        if not isinstance(info, dict)
                        else info.get("class_name") or (info.get("classDescriptor") or {}).get("class_name")
                    )
                    namespace = (
                        getattr(info, "namespace", None)
                        if not isinstance(info, dict)
                        else info.get("namespace")
                    )
                    if name and class_name and str(class_name).endswith("RayAgent"):
                        try:
                            handle = None
                            # Try resolve with namespace first if present
                            if namespace:
                                try:
                                    handle = ray.get_actor(name=name, namespace=namespace)
                                except Exception:
                                    handle = None
                            # Fallback to explicit namespace (prefer SEEDCORE_NS)
                            if handle is None:
                                ns = AGENT_NAMESPACE
                                handle = ray.get_actor(name, namespace=ns)
                            discovered[name] = handle
                        except Exception:
                            # Could be in a different namespace; skip if not retrievable
                            continue
                except Exception:
                    continue
        except Exception:
            # Fallback to private API (older Ray)
            try:
                from ray._private.state import actors  # type: ignore
                actor_infos = actors()
                for _, info in actor_infos.items():
                    try:
                        # info is a dict-like
                        name = info.get("Name") or info.get("name")
                        class_name = info.get("ClassName") or info.get("class_name")
                        state = info.get("State") or info.get("state")
                        namespace = info.get("Namespace") or info.get("namespace")
                        if state != "ALIVE":
                            continue
                        if name and class_name and class_name.endswith("RayAgent"):
                            try:
                                handle = None
                                if namespace:
                                    try:
                                        handle = ray.get_actor(name=name, namespace=namespace)
                                    except Exception:
                                        handle = None
                                if handle is None:
                                    # Use explicit namespace (prefer SEEDCORE_NS)
                                    ns = AGENT_NAMESPACE
                                    handle = ray.get_actor(name, namespace=ns)
                                discovered[name] = handle
                            except Exception:
                                continue
                    except Exception:
                        continue
            except Exception as e:
                logger.debug(f"Ray private state API not available: {e}")

        # Merge discovered into registry without overriding existing entries
        newly_attached = 0
        for agent_id, handle in discovered.items():
            if agent_id not in self.agents:
                self.agents[agent_id] = handle
                # Initialize caches for newly attached
                self.heartbeats.setdefault(agent_id, {})
                self.agent_stats.setdefault(agent_id, {})
                newly_attached += 1

        if newly_attached:
            logger.info(f"🔎 Attached {newly_attached} existing RayAgent(s) from cluster: {list(discovered.keys())}")
    
    def execute_task_on_agent(self, agent_id: str, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a task on a specific agent.
        
        Args:
            agent_id: Agent to execute the task on
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if agent not found
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found")
            return None
        
        try:
            result = ray.get(agent.execute_task.remote(task_data))
            logger.info(f"✅ Task executed on agent {agent_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to execute task on agent {agent_id}: {e}")
            return None
    
    def execute_task_on_random_agent(self, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a task on a randomly selected agent.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if no agents available
        """
        if not self.agents:
            logger.warning("No agents available for task execution")
            return None
        
        import random
        agent_id = random.choice(list(self.agents.keys()))
        return self.execute_task_on_agent(agent_id, task_data)
    
    def execute_task_on_best_agent(self, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Executes a task on the most suitable agent based on energy optimization.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result or None if no agents available
        """
        if not self.agents:
            logger.warning("No agents available for task execution")
            return None
        
        # Get all agent actor handles
        agent_handles = list(self.agents.values())
        
        try:
            # Use the new energy-aware selection
            best_agent, predicted_delta_e = select_best_agent(agent_handles, task_data)
            
            if not best_agent:
                logger.error("Could not select a best agent.")
                return None
            
            # Execute the task on the selected agent
            result = ray.get(best_agent.execute_task.remote(task_data))
            agent_id = ray.get(best_agent.get_id.remote())
            
            logger.info(f"✅ Energy-aware selection: Chose agent {agent_id} with predicted ΔE of {predicted_delta_e:.4f}")
            return result
            
        except Exception as e:
            logger.warning(f"Energy optimizer failed ({e}), falling back to random selection.")
            # Fallback to old method
            return self.execute_task_on_random_agent(task_data)

    # === COA §6: Local GNN-like selection within an organ (fast path Level 4) ===
    def execute_task_on_best_of(self, candidate_agent_ids: List[str], task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Execute a task on the best agent selected from a provided candidate set.
        Supports OrganismManager's Level-4 local selection (COA §6.2).
        """
        handles = [self.agents[a] for a in candidate_agent_ids if a in self.agents]
        if not handles:
            logger.warning("No candidate agents available for constrained best-of selection")
            return None
        try:
            best_agent, predicted_delta_e = select_best_agent(handles, task_data)
            result = ray.get(best_agent.execute_task.remote(task_data))
            agent_id = ray.get(best_agent.get_id.remote())
            logger.info(f"✅ Best-of selection: {agent_id} ΔE≈{predicted_delta_e:.4f}")
            return result
        except Exception as e:
            logger.warning(f"Best-of optimizer failed ({e}); falling back to random within candidate set.")
            import random
            handle = random.choice(handles)
            return ray.get(handle.execute_task.remote(task_data))

    def execute_task_on_organ_best(self, organ_id: str, task_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Convenience: select best agent among those belonging to an organ.
        Assumes standard agent naming: f"{organ_id}_agent_{'{'}i{'}'}".
        """
        prefix = f"{organ_id}_agent_"
        candidate_ids = [aid for aid in self.agents.keys() if aid.startswith(prefix)]
        return self.execute_task_on_best_of(candidate_ids, task_data)
    
    async def collect_heartbeats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect heartbeats from all agents.
        
        Returns:
            Dictionary of agent_id -> heartbeat data
        """
        if not self.agents:
            # Try discovering live agents before giving up
            try:
                self._refresh_agents_from_cluster()
            except Exception as e:
                logger.debug(f"Discovery failed during heartbeat collection: {e}")
            return {}
        
        try:
            # Collect heartbeats from all agents in parallel
            heartbeat_futures = [
                agent.get_heartbeat.remote() 
                for agent in self.agents.values()
            ]
            
            heartbeats = ray.get(heartbeat_futures)
            
            # Update our heartbeat cache
            for agent_id, heartbeat in zip(self.agents.keys(), heartbeats):
                self.heartbeats[agent_id] = heartbeat
            
            self.last_collection = time.time()
            logger.debug(f"✅ Collected heartbeats from {len(heartbeats)} agents")
            
            return dict(zip(self.agents.keys(), heartbeats))
            
        except Exception as e:
            logger.error(f"Failed to collect heartbeats: {e}")
            return {}
    
    async def collect_agent_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect summary statistics from all agents.
        
        Returns:
            Dictionary of agent_id -> summary stats
        """
        if not self.agents:
            return {}
        
        try:
            # Collect stats from all agents in parallel
            stats_futures = [
                agent.get_summary_stats.remote() 
                for agent in self.agents.values()
            ]
            
            stats = ray.get(stats_futures)
            
            # Update our stats cache
            for agent_id, stat in zip(self.agents.keys(), stats):
                self.agent_stats[agent_id] = stat
            
            logger.debug(f"✅ Collected stats from {len(stats)} agents")
            return dict(zip(self.agents.keys(), stats))
            
        except Exception as e:
            logger.error(f"Failed to collect agent stats: {e}")
            return {}
    
    def get_system_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the entire Tier 0 memory system.
        
        Returns:
            System-wide statistics and metrics
        """
        if not self.agent_stats:
            return {"total_agents": 0, "status": "no_agents"}
        
        total_agents = len(self.agent_stats)
        total_tasks = sum(stats.get("tasks_processed", 0) for stats in self.agent_stats.values())
        avg_capability = sum(stats.get("capability_score", 0) for stats in self.agent_stats.values()) / total_agents
        avg_mem_util = sum(stats.get("mem_util", 0) for stats in self.agent_stats.values()) / total_agents
        
        # Calculate system-wide metrics
        total_memory_writes = sum(stats.get("memory_writes", 0) for stats in self.agent_stats.values())
        total_peer_interactions = sum(stats.get("peer_interactions_count", 0) for stats in self.agent_stats.values())
        
        return {
            "total_agents": total_agents,
            "total_tasks_processed": total_tasks,
            "average_capability_score": avg_capability,
            "average_memory_utilization": avg_mem_util,
            "total_memory_writes": total_memory_writes,
            "total_peer_interactions": total_peer_interactions,
            "last_heartbeat_collection": self.last_collection,
            "collection_interval": self.collection_interval,
            "status": "active"
        }

    def get_agent_private_memory(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the agent's private memory vector and telemetry if available.
        Falls back to legacy state.h when telemetry endpoints are unavailable.
        """
        agent = self.get_agent(agent_id)
        if not agent:
            logger.warning(f"Agent {agent_id} not found for private memory fetch")
            return None
        try:
            h = ray.get(agent.get_private_memory_vector.remote())
            tel = ray.get(agent.get_private_memory_telemetry.remote())
            return {"h": h, "telemetry": tel}
        except Exception:
            # Legacy fallback
            try:
                state = ray.get(agent.get_state.remote())
                return {"h": state.get("h")}
            except Exception:
                return None
    
    async def start_heartbeat_monitoring(self, interval_seconds: int = 10):
        """
        Start continuous heartbeat monitoring.
        
        Args:
            interval_seconds: Interval between heartbeat collections
        """
        logger.info(f"❤️ Starting heartbeat monitoring every {interval_seconds}s")
        
        while True:
            try:
                await self.collect_heartbeats()
                await self.collect_agent_stats()
                
                # Log system summary periodically
                summary = self.get_system_summary()
                logger.info(f"📊 Tier 0 Summary: {summary['total_agents']} agents, "
                          f"avg_cap={summary['average_capability_score']:.3f}, "
                          f"total_tasks={summary['total_tasks_processed']}")
                
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"Error in heartbeat monitoring: {e}")
                await asyncio.sleep(interval_seconds)
    
    def get_agent_heartbeat(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """
        Get the latest heartbeat for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            Heartbeat data or None if not found
        """
        return self.heartbeats.get(agent_id)
    
    def get_all_heartbeats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all cached heartbeats.
        
        Returns:
            Dictionary of all agent heartbeats
        """
        return self.heartbeats.copy()
    
    def reset_agent_metrics(self, agent_id: str) -> bool:
        """
        Reset metrics for a specific agent.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            True if successful, False otherwise
        """
        agent = self.get_agent(agent_id)
        if not agent:
            return False
        
        try:
            ray.get(agent.reset_metrics.remote())
            logger.info(f"🔄 Reset metrics for agent {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reset metrics for agent {agent_id}: {e}")
            return False
    
    def shutdown_agents(self):
        """Shutdown all agent actors."""
        if not self.agents:
            return
        
        logger.info(f"🔄 Shutting down {len(self.agents)} agents")
        
        # Clear our caches
        self.heartbeats.clear()
        self.agent_stats.clear()
        
        # The agents will be garbage collected by Ray
        self.agents.clear()
        
        logger.info("✅ All agents shut down")

# Global instance for easy access - lazy initialization
_tier0_manager_instance = None

def get_tier0_manager():
    """Get the global Tier0MemoryManager instance, creating it if needed."""
    global _tier0_manager_instance
    if _tier0_manager_instance is None:
        _tier0_manager_instance = Tier0MemoryManager()
    return _tier0_manager_instance

# For backward compatibility, create a property-like access
class Tier0ManagerProxy:
    def __getattr__(self, name):
        return getattr(get_tier0_manager(), name)

tier0_manager = Tier0ManagerProxy() 