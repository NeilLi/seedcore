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
OrganismManager - Manages the lifecycle of organs and the distribution of agents within them.
This implements the COA framework's "swarm-of-swarms" model where organs act as specialized 
containers for pools of agents.
"""

import yaml
import logging
import asyncio
import time
from pathlib import Path
from typing import Dict, List, Any, Optional

import ray
from .base import Organ
from ..agents.ray_actor import RayAgent

logger = logging.getLogger(__name__)

class OrganismManager:
    """
    Manages the lifecycle of organs and the distribution of agents within them.
    
    This class implements the COA framework's organ-based architecture where:
    - Organs are specialized containers for pools of agents
    - Each organ has a distinct type and role
    - Agents are distributed across organs based on configuration
    - The entire organism can be managed as a cohesive unit
    """

    def __init__(self, config_path: str = "src/seedcore/config/defaults.yaml"):
        self.organs: Dict[str, ray.actor.ActorHandle] = {}
        self.agent_to_organ_map: Dict[str, str] = {}
        self.organ_configs: List[Dict[str, Any]] = []
        self._load_config(config_path)
        self._initialized = False

    def _load_config(self, config_path: str):
        """Loads the organism configuration from a YAML file."""
        try:
            path = Path(config_path)
            with open(path, 'r') as f:
                config = yaml.safe_load(f)
                self.organ_configs = config['seedcore']['organism']['organ_types']
                logger.info(f"Loaded organism configuration with {len(self.organ_configs)} organ types")
        except FileNotFoundError:
            logger.error(f"Configuration file not found at {config_path}")
            self.organ_configs = []
        except KeyError as e:
            logger.error(f"Missing required configuration key: {e}")
            self.organ_configs = []
        except Exception as e:
            logger.error(f"Error loading organism configuration: {e}")
            self.organ_configs = []

    async def initialize_organism(self):
        """Creates all organs and populates them with agents based on the config."""
        if self._initialized:
            logger.warning("Organism already initialized. Skipping re-initialization.")
            return
            
        logger.info("🚀 Initializing the Cognitive Organism...")
        
        try:
            # Clean up dead actors first
            await self._cleanup_dead_actors()
            
            self._create_organs()
            await self._create_and_distribute_agents()
            self._initialized = True
            logger.info("✅ Organism initialization complete.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize organism: {e}")
            raise

    async def _cleanup_dead_actors(self):
        """Clean up dead Ray actors to prevent accumulation."""
        try:
            import ray
            from ray.util.state import list_actors
            
            # Get all actors
            actors = list_actors()
            dead_actors = [actor for actor in actors if actor.state == "DEAD"]
            
            if dead_actors:
                logger.info(f"🧹 Found {len(dead_actors)} dead actors, cleaning up...")
                
                for actor in dead_actors:
                    try:
                        if hasattr(actor, 'actor_id'):
                            # Try to kill the dead actor
                            ray.kill(actor.actor_id)
                            logger.debug(f"🗑️ Cleaned up dead actor: {actor.actor_id}")
                    except Exception as e:
                        logger.debug(f"Could not clean up dead actor {actor.actor_id}: {e}")
                        
                logger.info(f"✅ Cleaned up {len(dead_actors)} dead actors")
            else:
                logger.info("✅ No dead actors found")
                
        except Exception as e:
            logger.warning(f"Could not clean up dead actors: {e}")

    def _create_organs(self):
        """Creates the organ actors as defined in the configuration."""
        for config in self.organ_configs:
            organ_id = config['id']
            organ_type = config['type']
            
            if organ_id not in self.organs:
                try:
                    # Try to get existing organ first
                    try:
                        existing_organ = ray.get_actor(organ_id)
                        self.organs[organ_id] = existing_organ
                        logger.info(f"✅ Retrieved existing Organ: {organ_id} (Type: {organ_type})")
                    except ValueError:
                        # Create new organ if it doesn't exist
                        self.organs[organ_id] = Organ.options(
                            name=organ_id, 
                            lifetime="detached"
                        ).remote(
                            organ_id=organ_id,
                            organ_type=organ_type
                        )
                        logger.info(f"✅ Created new Organ: {organ_id} (Type: {organ_type})")
                except Exception as e:
                    logger.error(f"❌ Failed to create/get organ {organ_id}: {e}")
                    raise

    async def _create_and_distribute_agents(self):
        """Creates agents and registers them with their designated organs."""
        agent_count = 0
        
        for organ_config in self.organ_configs:
            organ_id = organ_config['id']
            num_agents = organ_config['agent_count']
            organ_handle = self.organs.get(organ_id)

            if not organ_handle:
                logger.warning(f"Organ '{organ_id}' not found. Skipping agent creation.")
                continue

            logger.info(f"Creating {num_agents} agents for organ {organ_id}...")
            
            # First, clean up excess agents if needed
            await self._cleanup_excess_agents(organ_handle, organ_id, num_agents)
            
            for i in range(num_agents):
                agent_id = f"{organ_id}_agent_{i}"
                
                try:
                    # Check if agent already exists in the organ
                    existing_agents = await organ_handle.get_agent_handles.remote()
                    
                    if agent_id in existing_agents:
                        # Reuse existing agent
                        logger.info(f"✅ Reusing existing agent: {agent_id}")
                        self.agent_to_organ_map[agent_id] = organ_id
                        agent_count += 1
                        continue
                    
                    # Create the agent actor with appropriate role probabilities based on organ type
                    initial_role_probs = self._get_role_probs_for_organ_type(organ_config['type'])
                    
                    # Create agent with stable name (no timestamp) to enable reuse
                    agent_handle = RayAgent.options(
                        name=agent_id,  # Use stable name without timestamp
                        lifetime="detached"  # Make it persistent
                    ).remote(
                        agent_id=agent_id,
                        initial_role_probs=initial_role_probs
                    )
                    
                    # Register the agent with its organ
                    await organ_handle.register_agent.remote(agent_id, agent_handle)
                    self.agent_to_organ_map[agent_id] = organ_id
                    agent_count += 1
                    
                    logger.info(f"✅ Created new agent: {agent_id}")
                    
                except Exception as e:
                    logger.error(f"❌ Failed to create agent {agent_id}: {e}")
                    continue
        
        logger.info(f"✅ Created and distributed {agent_count} agents across {len(self.organs)} organs.")

    async def _cleanup_excess_agents(self, organ_handle, organ_id: str, target_count: int):
        """Remove excess agents from an organ to match the target count."""
        try:
            existing_agents = await organ_handle.get_agent_handles.remote()
            current_count = len(existing_agents)
            
            if current_count > target_count:
                excess_count = current_count - target_count
                logger.info(f"🧹 Cleaning up {excess_count} excess agents from {organ_id}")
                
                # Remove excess agents (keep the first target_count)
                agent_ids = list(existing_agents.keys())
                for agent_id in agent_ids[target_count:]:
                    try:
                        await organ_handle.remove_agent.remote(agent_id)
                        logger.info(f"🗑️ Removed excess agent: {agent_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to remove agent {agent_id}: {e}")
                        
        except Exception as e:
            logger.error(f"❌ Error during agent cleanup for {organ_id}: {e}")

    def _get_role_probs_for_organ_type(self, organ_type: str) -> Dict[str, float]:
        """Returns appropriate role probabilities based on organ type."""
        if organ_type == "Cognitive":
            return {'E': 0.3, 'S': 0.6, 'O': 0.1}  # High S for reasoning
        elif organ_type == "Actuator":
            return {'E': 0.7, 'S': 0.2, 'O': 0.1}  # High E for action
        elif organ_type == "Utility":
            return {'E': 0.2, 'S': 0.3, 'O': 0.5}  # High O for observation
        else:
            return {'E': 0.33, 'S': 0.33, 'O': 0.34}  # Default balanced

    async def get_organism_status(self) -> List[Dict[str, Any]]:
        """Collects and returns the status of all organs."""
        if not self._initialized:
            return [{"error": "Organism not initialized"}]
            
        try:
            status_futures = [organ.get_status.remote() for organ in self.organs.values()]
            statuses = await asyncio.gather(*status_futures)
            return statuses
        except Exception as e:
            logger.error(f"Error getting organism status: {e}")
            return [{"error": str(e)}]

    def get_organ_handle(self, organ_id: str) -> Optional[ray.actor.ActorHandle]:
        """Returns the handle to a specific organ."""
        return self.organs.get(organ_id)

    def get_agent_organ(self, agent_id: str) -> Optional[str]:
        """Returns the organ ID that contains a specific agent."""
        return self.agent_to_organ_map.get(agent_id)

    def get_total_agent_count(self) -> int:
        """Returns the total number of agents across all organs."""
        return len(self.agent_to_organ_map)

    def get_organ_count(self) -> int:
        """Returns the number of organs."""
        return len(self.organs)

    def is_initialized(self) -> bool:
        """Returns whether the organism has been initialized."""
        return self._initialized

    async def execute_task_on_organ(self, organ_id: str, task: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a task on a specific organ."""
        if not self._initialized:
            raise RuntimeError("Organism not initialized")
            
        organ_handle = self.organs.get(organ_id)
        if not organ_handle:
            raise ValueError(f"Organ {organ_id} not found")
            
        try:
            result = await organ_handle.run_task.remote(task)
            return {"success": True, "result": result, "organ_id": organ_id}
        except Exception as e:
            logger.error(f"Error executing task on organ {organ_id}: {e}")
            return {"success": False, "error": str(e), "organ_id": organ_id}

    async def execute_task_on_random_organ(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Executes a task on a randomly selected organ."""
        if not self.organs:
            raise RuntimeError("No organs available")
            
        import random
        organ_id = random.choice(list(self.organs.keys()))
        return await self.execute_task_on_organ(organ_id, task)

    def shutdown_organism(self):
        """Shuts down the organism and cleans up resources."""
        logger.info("🛑 Shutting down organism...")
        
        # Note: Ray actors with lifetime="detached" will persist until explicitly terminated
        # In a production system, you might want to add explicit cleanup here
        self._initialized = False
        logger.info("✅ Organism shutdown complete")

# Global instance for easy access from the API server
organism_manager = OrganismManager() 