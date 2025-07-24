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
Simplified Tier 0 Memory Manager
Uses SimpleRayAgent for remote cluster compatibility.
"""

import ray
import time
import asyncio
from typing import Dict, List, Any, Optional
from collections import defaultdict
import logging
import json

from .ray_actor_simple import SimpleRayAgent

logger = logging.getLogger(__name__)

class SimpleTier0MemoryManager:
    """
    Simplified Tier 0 memory manager using SimpleRayAgent.
    
    Responsibilities:
    - Create and manage SimpleRayAgent actors
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
        
        logger.info("✅ SimpleTier0MemoryManager initialized")
    
    def create_agent(self, agent_id: str, role_probs: Optional[Dict[str, float]] = None) -> str:
        """
        Create a new SimpleRayAgent actor.
        
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
            agent_handle = SimpleRayAgent.remote(agent_id, role_probs)
            self.agents[agent_id] = agent_handle
            
            # Initialize heartbeat and stats
            self.heartbeats[agent_id] = {}
            self.agent_stats[agent_id] = {}
            
            logger.info(f"✅ Created SimpleRayAgent: {agent_id}")
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
simple_tier0_manager = SimpleTier0MemoryManager() 