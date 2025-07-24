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
Simplified Tier 0 (Ma): Per-Agent Memory Implementation
Ray actor-based stateful agents without numpy dependency.
"""

import ray
import time
import asyncio
from typing import Dict, Any, List, Optional
import logging
import random

logger = logging.getLogger(__name__)

@ray.remote
class SimpleRayAgent:
    """
    Simplified stateful Ray actor for Tier 0 per-agent memory (Ma).
    No numpy dependency for remote cluster compatibility.
    """
    
    def __init__(self, agent_id: str, initial_role_probs: Optional[Dict[str, float]] = None):
        # 1. Agent Identity and State
        self.agent_id = agent_id
        
        # 2. State Vector (h) - 128-dimensional as per COA specification
        # Use list instead of numpy array
        self.state_embedding = [random.random() for _ in range(128)]
        
        # 3. Role Probabilities
        self.role_probs = initial_role_probs or {'E': 0.9, 'S': 0.1, 'O': 0.0}
        
        # 4. Performance Tracking Metrics
        self.tasks_processed = 0
        self.successful_tasks = 0
        self.quality_scores: List[float] = []
        self.task_history: List[Dict[str, Any]] = []
        
        # 5. Capability Score (c_i) with EWMA smoothing
        self.capability_score: float = 0.5
        self.smoothing_factor: float = 0.1
        
        # 6. Memory Utilization
        self.mem_util: float = 0.0
        
        # 7. Memory Interaction Tracking
        self.memory_writes: int = 0
        self.memory_hits_on_writes: int = 0
        self.salient_events_logged: int = 0
        self.total_compression_gain: float = 0.0
        
        # 8. Local Skill Deltas
        self.skill_deltas: Dict[str, float] = {}
        
        # 9. Peer Stats
        self.peer_interactions: Dict[str, int] = {}
        
        # 10. Timestamps
        self.created_at = time.time()
        self.last_heartbeat = time.time()
        
        logger.info(f"✅ SimpleRayAgent {self.agent_id} created with initial state")
    
    def get_id(self) -> str:
        """Returns the agent's ID."""
        return self.agent_id
    
    def get_state_embedding(self) -> List[float]:
        """Returns the current state embedding vector."""
        return self.state_embedding.copy()
    
    def update_state_embedding(self, new_embedding: List[float]):
        """Updates the state embedding vector."""
        if len(new_embedding) == 128:
            self.state_embedding = new_embedding.copy()
            logger.debug(f"Agent {self.agent_id} state embedding updated")
        else:
            logger.warning(f"Invalid embedding length: {len(new_embedding)}, expected 128")
    
    def update_performance(self, success: bool, quality: float, task_metadata: Optional[Dict] = None):
        """Updates the agent's performance metrics after a task."""
        self.tasks_processed += 1
        if success:
            self.successful_tasks += 1
        
        self.quality_scores.append(quality)
        # Keep only the last 20 scores
        if len(self.quality_scores) > 20:
            self.quality_scores.pop(0)
        
        # Store task in history
        task_record = {
            "timestamp": time.time(),
            "success": success,
            "quality": quality,
            "metadata": task_metadata or {}
        }
        self.task_history.append(task_record)
        
        # Keep only last 100 tasks
        if len(self.task_history) > 100:
            self.task_history.pop(0)
        
        # Calculate current success rate and average quality
        success_rate = (self.successful_tasks / self.tasks_processed) if self.tasks_processed > 0 else 0
        avg_quality = sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0
        
        # Update capability score using EWMA formula
        w_s = 0.6
        w_q = 0.4
        current_performance = (w_s * success_rate) + (w_q * avg_quality)
        
        self.capability_score = (
            (1 - self.smoothing_factor) * self.capability_score + 
            self.smoothing_factor * current_performance
        )
        
        logger.info(f"📈 Agent {self.agent_id} performance updated: Capability={self.capability_score:.3f}")
    
    def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a task and update performance metrics."""
        logger.info(f"🤖 Agent {self.agent_id} executing task: {task_data.get('task_id', 'unknown')}")
        
        # Simulate task execution
        success = random.choice([True, False])
        quality = random.uniform(0.5, 1.0)
        
        # Update memory utilization based on task complexity
        task_complexity = task_data.get('complexity', 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)
        
        # Update memory interaction tracking
        self.memory_writes += 1
        if random.random() < 0.3:
            self.memory_hits_on_writes += 1
        
        # Update internal performance metrics
        self.update_performance(success, quality, task_data)
        
        return {
            "agent_id": self.agent_id,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util
        }
    
    def update_skill_delta(self, skill_name: str, delta: float):
        """Update local skill delta."""
        self.skill_deltas[skill_name] = self.skill_deltas.get(skill_name, 0.0) + delta
        logger.debug(f"Agent {self.agent_id} skill delta updated: {skill_name} += {delta}")
    
    def record_peer_interaction(self, peer_id: str):
        """Record interaction with another agent."""
        self.peer_interactions[peer_id] = self.peer_interactions.get(peer_id, 0) + 1
        logger.debug(f"Agent {self.agent_id} recorded interaction with {peer_id}")
    
    def get_heartbeat(self) -> Dict[str, Any]:
        """Gathers the agent's current state and performance into a heartbeat."""
        success_rate = (self.successful_tasks / self.tasks_processed) if self.tasks_processed > 0 else 0
        current_quality = self.quality_scores[-1] if self.quality_scores else 0.0
        
        heartbeat_data = {
            "timestamp": time.time(),
            "agent_id": self.agent_id,
            "state_embedding_h": self.state_embedding,  # Already a list
            "role_probs": self.role_probs,
            "performance_metrics": {
                "success_rate": success_rate,
                "quality_score": current_quality,
                "capability_score_c": self.capability_score,
                "mem_util": self.mem_util,
                "tasks_processed": self.tasks_processed,
                "successful_tasks": self.successful_tasks
            },
            "memory_metrics": {
                "memory_writes": self.memory_writes,
                "memory_hits_on_writes": self.memory_hits_on_writes,
                "salient_events_logged": self.salient_events_logged,
                "total_compression_gain": self.total_compression_gain
            },
            "local_state": {
                "skill_deltas": self.skill_deltas,
                "peer_interactions": self.peer_interactions,
                "recent_quality_scores": self.quality_scores[-5:] if self.quality_scores else []
            },
            "lifecycle": {
                "created_at": self.created_at,
                "last_heartbeat": self.last_heartbeat,
                "uptime": time.time() - self.created_at
            }
        }
        
        self.last_heartbeat = time.time()
        return heartbeat_data
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Get a summary of agent statistics."""
        return {
            "agent_id": self.agent_id,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "tasks_processed": self.tasks_processed,
            "success_rate": (self.successful_tasks / self.tasks_processed) if self.tasks_processed > 0 else 0,
            "avg_quality": sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0,
            "memory_writes": self.memory_writes,
            "peer_interactions_count": len(self.peer_interactions)
        }
    
    def reset_metrics(self):
        """Reset all performance metrics."""
        self.tasks_processed = 0
        self.successful_tasks = 0
        self.quality_scores.clear()
        self.task_history.clear()
        self.capability_score = 0.5
        self.mem_util = 0.0
        self.memory_writes = 0
        self.memory_hits_on_writes = 0
        self.salient_events_logged = 0
        self.total_compression_gain = 0.0
        self.skill_deltas.clear()
        self.peer_interactions.clear()
        logger.info(f"🔄 Agent {self.agent_id} metrics reset") 