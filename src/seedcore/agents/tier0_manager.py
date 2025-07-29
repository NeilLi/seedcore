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

import ray
import time
import asyncio
from typing import Dict, List, Any, Optional
from collections import defaultdict
import logging
import json

from .ray_actor import RayAgent
from ..energy.optimizer import select_best_agent, score_agent
from ..energy.calculator import EnergyLedger  # For fallback

logger = logging.getLogger(__name__)

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
        
        logger.info("✅ Tier0MemoryManager initialized")
    
    def create_agent(self, agent_id: str, role_probs: Optional[Dict[str, float]] = None) -> str:
        """
        Create a new Ray agent actor.
        
        Args:
            agent_id: Unique identifier for the agent
            role_probs: Initial role probabilities
            
        Returns:
            The agent ID if successful
        """
        if agent_id in self.agents:
            logger.warning(f"Agent {agent_id} already exists")
            return agent_id
        
        try:
            # Create the Ray actor
            agent_handle = RayAgent.remote(agent_id, role_probs)
            self.agents[agent_id] = agent_handle
            
            # Initialize heartbeat and stats
            self.heartbeats[agent_id] = {}
            self.agent_stats[agent_id] = {}
            
            logger.info(f"✅ Created Ray agent: {agent_id}")
            return agent_id
            
        except Exception as e:
            logger.error(f"Failed to create agent {agent_id}: {e}")
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
            try:
                self.create_agent(agent_id, role_probs)
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
        """Get list of all agent IDs."""
        return list(self.agents.keys())
    
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
    
    async def collect_heartbeats(self) -> Dict[str, Dict[str, Any]]:
        """
        Collect heartbeats from all agents.
        
        Returns:
            Dictionary of agent_id -> heartbeat data
        """
        if not self.agents:
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

# Global instance for easy access
tier0_manager = Tier0MemoryManager() 