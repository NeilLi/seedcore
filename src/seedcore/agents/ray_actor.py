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
Tier 0 (Ma): Per-Agent Memory Implementation
Ray actor-based stateful agents with private memory and performance tracking.
"""

import ray
import numpy as np
import time
import asyncio
import json
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)

# NEW: Import the FlashbulbClient
from ..memory.flashbulb_client import FlashbulbClient

@ray.remote
class RayAgent:
    """
    Stateful Ray actor for Tier 0 per-agent memory (Ma).
    
    Each agent maintains:
    - 128-dimensional state vector (h)
    - Performance metrics and capability score
    - Task history and quality scores
    - Memory interaction tracking
    - Memory managers for Mw and Mlt access
    """
    
    def __init__(self, agent_id: str, initial_role_probs: Optional[Dict[str, float]] = None):
        # 1. Agent Identity and State
        self.agent_id = agent_id
        
        # 2. State Vector (h) - 128-dimensional as per COA specification
        self.state_embedding: np.ndarray = np.random.randn(128)
        
        # 3. Role Probabilities (from original Agent)
        self.role_probs = initial_role_probs or {'E': 0.9, 'S': 0.1, 'O': 0.0}
        
        # 4. Performance Tracking Metrics
        self.tasks_processed = 0
        self.successful_tasks = 0
        self.quality_scores: List[float] = []
        self.task_history: List[Dict[str, Any]] = []
        
        # 5. Capability Score (c_i) with EWMA smoothing
        self.capability_score: float = 0.5  # Initial capability
        self.smoothing_factor: float = 0.1   # η_c smoothing parameter
        
        # 6. Memory Utilization (mem_util) for lifecycle transitions
        self.mem_util: float = 0.0
        
        # 7. Memory Interaction Tracking (from original Agent)
        self.memory_writes: int = 0
        self.memory_hits_on_writes: int = 0
        self.salient_events_logged: int = 0
        self.total_compression_gain: float = 0.0
        
        # 8. Local Skill Deltas (per-agent scratch memory)
        self.skill_deltas: Dict[str, float] = {}
        
        # 9. Peer Stats (local tracking of interactions)
        self.peer_interactions: Dict[str, int] = {}
        
        # 10. Timestamps for tracking
        self.created_at = time.time()
        self.last_heartbeat = time.time()
        
        # --- NEW: Memory Managers for Mw and Mlt access ---
        # Initialize memory managers within the actor
        try:
            from ..memory.working_memory import WorkingMemoryManager
            from ..memory.long_term_memory import LongTermMemoryManager
            
            # Create organ_id for this agent (you might want to make this configurable)
            organ_id = f"organ_for_{agent_id}"
            self.mw_manager = WorkingMemoryManager(organ_id=organ_id)
            self.mlt_manager = LongTermMemoryManager()
            
            logger.info(f"✅ Agent {self.agent_id} initialized with memory managers")
        except Exception as e:
            logger.error(f"❌ Failed to initialize memory managers for {self.agent_id}: {e}")
            self.mw_manager = None
            self.mlt_manager = None
        
        # --- Add Flashbulb Client to the agent's tools ---
        try:
            self.mfb_client = FlashbulbClient()
            logger.info(f"✅ Agent {self.agent_id} initialized with FlashbulbClient")
        except Exception as e:
            logger.error(f"❌ Failed to initialize FlashbulbClient for {self.agent_id}: {e}")
            self.mfb_client = None
        
        logger.info(f"✅ RayAgent {self.agent_id} created with initial state")
    
    def get_id(self) -> str:
        """Returns the agent's ID."""
        return self.agent_id
    
    def get_state_embedding(self) -> np.ndarray:
        """Returns the current state embedding vector."""
        return self.state_embedding.copy()
    
    def update_state_embedding(self, new_embedding: np.ndarray):
        """Updates the state embedding vector."""
        if new_embedding.shape == (128,):
            self.state_embedding = new_embedding.copy()
            logger.debug(f"Agent {self.agent_id} state embedding updated")
        else:
            logger.warning(f"Invalid embedding shape: {new_embedding.shape}, expected (128,)")
    
    def update_performance(self, success: bool, quality: float, task_metadata: Optional[Dict] = None):
        """
        Updates the agent's performance metrics after a task.
        
        Args:
            success: Whether the task was successful
            quality: Quality score (0.0 to 1.0)
            task_metadata: Optional metadata about the task
        """
        self.tasks_processed += 1
        if success:
            self.successful_tasks += 1
        
        self.quality_scores.append(quality)
        # Keep only the last 20 scores for rolling average
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
        
        # Keep only last 100 tasks in history
        if len(self.task_history) > 100:
            self.task_history.pop(0)
        
        # Calculate current success rate and average quality
        success_rate = (self.successful_tasks / self.tasks_processed) if self.tasks_processed > 0 else 0
        avg_quality = sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0
        
        # Update capability score using EWMA formula
        w_s = 0.6  # Weight for success rate
        w_q = 0.4  # Weight for quality
        current_performance = (w_s * success_rate) + (w_q * avg_quality)
        
        self.capability_score = (
            (1 - self.smoothing_factor) * self.capability_score + 
            self.smoothing_factor * current_performance
        )
        
        logger.info(f"📈 Agent {self.agent_id} performance updated: Capability={self.capability_score:.3f}")
    
    def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task and update performance metrics.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result with performance metrics
        """
        logger.info(f"🤖 Agent {self.agent_id} executing task: {task_data.get('task_id', 'unknown')}")
        
        # --- TASK EXECUTION LOGIC ---
        # This is where you'll implement your actual task logic
        # For now, we'll simulate task execution
        
        import random
        
        # Simulate task execution with some randomness
        success = random.choice([True, False])
        quality = random.uniform(0.5, 1.0)
        
        # Update memory utilization based on task complexity
        task_complexity = task_data.get('complexity', 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)
        
        # Update memory interaction tracking
        self.memory_writes += 1
        if random.random() < 0.3:  # 30% chance of being read by others
            self.memory_hits_on_writes += 1
        
        # --- END TASK LOGIC ---
        
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
        """
        Update local skill delta (per-agent scratch memory).
        
        Args:
            skill_name: Name of the skill
            delta: Change in skill level
        """
        self.skill_deltas[skill_name] = self.skill_deltas.get(skill_name, 0.0) + delta
        logger.debug(f"Agent {self.agent_id} skill delta updated: {skill_name} += {delta}")
    
    def record_peer_interaction(self, peer_id: str):
        """
        Record interaction with another agent.
        
        Args:
            peer_id: ID of the peer agent
        """
        self.peer_interactions[peer_id] = self.peer_interactions.get(peer_id, 0) + 1
        logger.debug(f"Agent {self.agent_id} recorded interaction with {peer_id}")
    
    def get_heartbeat(self) -> Dict[str, Any]:
        """
        Gathers the agent's current state and performance into a heartbeat.
        This will be serialized to JSON for the meta-controller.
        
        Returns:
            Dictionary containing agent state and metrics
        """
        success_rate = (self.successful_tasks / self.tasks_processed) if self.tasks_processed > 0 else 0
        current_quality = self.quality_scores[-1] if self.quality_scores else 0.0
        
        heartbeat_data = {
            "timestamp": time.time(),
            "agent_id": self.agent_id,
            "state_embedding_h": self.state_embedding.tolist(),  # Convert numpy array for JSON
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
        """
        Get a summary of agent statistics for monitoring.
        
        Returns:
            Dictionary with key performance indicators
        """
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
    
    # --- NEW: Knowledge Finding Method for Scenario 1 ---
    def find_knowledge(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Attempts to find a piece of knowledge, implementing the Mw -> Mlt escalation.
        This is a synchronous method.
        
        Args:
            fact_id: The ID of the fact to find
            
        Returns:
            Optional[Dict[str, Any]]: The found knowledge or None if not found
        """
        logger.info(f"[{self.agent_id}] 🔍 Searching for '{fact_id}'...")

        # Check if memory managers are available
        if not self.mw_manager or not self.mlt_manager:
            logger.error(f"[{self.agent_id}] ❌ Memory managers not available")
            return None

        # 1. Query Working Memory (Mw) first
        logger.info(f"[{self.agent_id}] 📋 Querying Working Memory (Mw)...")
        try:
            cached_data = self.mw_manager.get_item(fact_id)
            
            if cached_data:
                logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' in Mw (cache hit).")
                try:
                    return json.loads(cached_data)  # Deserialize from JSON string
                except json.JSONDecodeError:
                    logger.warning(f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON")
                    return {"raw_data": cached_data}
        except Exception as e:
            logger.error(f"[{self.agent_id}] ❌ Error querying Mw: {e}")

        # 2. On a miss, escalate to Long-Term Memory (Mlt)
        logger.info(f"[{self.agent_id}] ⚠️ '{fact_id}' not in Mw (cache miss). Escalating to Mlt...")
        try:
            long_term_data = self.mlt_manager.query_holon_by_id(fact_id)  # No await needed

            if long_term_data:
                logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' in Mlt.")
                
                # 3. Cache the retrieved data back into Mw for future use
                logger.info(f"[{self.agent_id}] 💾 Caching '{fact_id}' back to Mw...")
                try:
                    self.mw_manager.set_item(fact_id, json.dumps(long_term_data))
                    logger.info(f"[{self.agent_id}] ✅ Successfully cached to Mw")
                except Exception as e:
                    logger.error(f"[{self.agent_id}] ❌ Failed to cache to Mw: {e}")
                
                return long_term_data
            else:
                logger.warning(f"[{self.agent_id}] ❌ '{fact_id}' not found in Mlt either.")
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] ❌ Error querying Mlt: {e}")
        
        logger.warning(f"[{self.agent_id}] 🚨 Could not find '{fact_id}' in any memory tier.")
        return None

    def execute_collaborative_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulates executing a collaborative task that may require finding knowledge.
        This method implements the core logic for Scenario 1.
        
        Args:
            task_info: Dictionary containing task information including required_fact
            
        Returns:
            Dict[str, Any]: Task execution result with success status and details
        """
        task_name = task_info.get('name', 'Unknown Task')
        required_fact = task_info.get('required_fact')
        
        logger.info(f"[{self.agent_id}] 🚀 Starting collaborative task '{task_name}'...")
        
        knowledge = None
        if required_fact:
            logger.info(f"[{self.agent_id}] 📚 Task requires fact: {required_fact}")
            knowledge = self.find_knowledge(required_fact)  # No await needed
        
        # Determine task success based on knowledge availability
        if required_fact and not knowledge:
            success = False
            quality = 0.1
            logger.error(f"[{self.agent_id}] 🚨 Task failed: could not find required fact '{required_fact}'.")
        else:
            success = True
            quality = 0.9 if knowledge else 0.7  # Higher quality if knowledge was found
            logger.info(f"[{self.agent_id}] ✅ Task completed successfully.")
            if knowledge:
                logger.info(f"[{self.agent_id}] 📖 Used knowledge: {knowledge.get('content', 'Unknown content')}")
        
        # 4. Update internal performance metrics (Ma)
        self.update_performance(success=success, quality=quality, task_metadata=task_info)
        
        # Update memory utilization based on task complexity
        task_complexity = task_info.get('complexity', 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)
        
        return {
            "agent_id": self.agent_id,
            "task_name": task_name,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get('content', None) if knowledge else None
        }

    def execute_high_stakes_task(self, task_info: dict) -> dict:
        """
        Simulates a high-stakes task that fails, potentially triggering a
        flashbulb memory incident.
        """
        logger.info(f"[{self.agent_id}] Attempting high-stakes task: {task_info.get('name')}")
        
        # --- 1. Simulate an unexpected failure ---
        success = False
        error_context = {"reason": "External API timeout", "code": 504}
        logger.warning(f"[{self.agent_id}] Task failed! Reason: {error_context['reason']}")
        
        # --- 2. Calculate Salience Score ---
        # A simple calculation based on task risk and failure severity
        risk = task_info.get('risk', 0.5)
        severity = 1.0 # Max severity for this type of failure
        salience_score = risk * severity  # This will be between 0 and 1
        logger.info(f"[{self.agent_id}] Calculated salience score: {salience_score:.2f}")

        # --- 3. Trigger Flashbulb Logging if threshold is met ---
        SALIENCE_THRESHOLD = 0.7  # Changed from 7.0 to 0.7
        incident_logged = False
        
        if salience_score >= SALIENCE_THRESHOLD:
            logger.warning(f"[{self.agent_id}] Salience threshold met! Logging to Flashbulb Memory (Mfb)...")
            
            if self.mfb_client:
                # Prepare the full event data payload
                incident_data = {
                    "agent_state": self.get_heartbeat(), # Capture agent's full state (Ma)
                    "failed_task": task_info,
                    "error_context": error_context
                }
                
                # Log the incident using the client
                incident_logged = self.mfb_client.log_incident(incident_data, salience_score)
                
                if incident_logged:
                    logger.info(f"[{self.agent_id}] ✅ Incident successfully logged to Flashbulb Memory")
                else:
                    logger.error(f"[{self.agent_id}] ❌ Failed to log incident to Flashbulb Memory")
            else:
                logger.error(f"[{self.agent_id}] ❌ FlashbulbClient not available")
        
        # Update agent's internal performance metrics
        self.update_performance(success=False, quality=0.0, task_metadata=task_info)
        
        return {
            "agent_id": self.agent_id,
            "success": success,
            "salience_score": salience_score,
            "incident_logged": incident_logged,
            "error_context": error_context
        }
    
    async def start_heartbeat_loop(self, interval_seconds: int = 10):
        """
        Starts a loop to periodically emit heartbeats.
        This runs as a background task within the actor.
        
        Args:
            interval_seconds: Interval between heartbeats
        """
        logger.info(f"❤️ Agent {self.agent_id} starting heartbeat loop every {interval_seconds}s")
        
        while True:
            try:
                heartbeat = self.get_heartbeat()
                # In a real system, you would publish this to Redis Pub/Sub
                # or send it to a central telemetry service
                logger.info(f"HEARTBEAT from {self.agent_id}: capability={heartbeat['performance_metrics']['capability_score_c']:.3f}")
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Error in heartbeat loop for {self.agent_id}: {e}")
                await asyncio.sleep(interval_seconds)
    
    def reset_metrics(self):
        """Reset all performance metrics (for testing/debugging)."""
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