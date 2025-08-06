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
logger.setLevel(logging.INFO)
logger.propagate = True
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logger.addHandler(handler)

# NEW: Import the FlashbulbClient
from ..memory.flashbulb_client import FlashbulbClient

@dataclass
class AgentState:
    """Holds the local state for an agent."""
    h: np.ndarray  # Embedding
    p: Dict[str, float]  # Role probabilities
    c: float = 0.5  # Capability
    mem_util: float = 0.0  # Memory Utility

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
        
        # 2. Initialize AgentState with COA specifications
        self.state = AgentState(
            h=np.random.randn(128),  # 128-dimensional embedding
            p=initial_role_probs or {'E': 0.9, 'S': 0.1, 'O': 0.0},
            c=0.5,  # Initial capability
            mem_util=0.0  # Initial memory utility
        )
        
        # 3. Backward compatibility - keep old attributes
        self.state_embedding = self.state.h
        self.role_probs = self.state.p
        
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
        
        # 11. Energy State Tracking (NEW)
        self.energy_state: Dict[str, float] = {}
        
        # --- Initialize memory managers with better error handling ---
        self.mw_manager = None
        self.mlt_manager = None
        self.mfb_client = None
        
        # Initialize memory managers asynchronously to avoid hanging
        try:
            # Only initialize basic components, defer complex initialization
            logger.info(f"✅ RayAgent {self.agent_id} created with basic state")
            
            # Initialize memory managers later if needed
            self._initialize_memory_managers()
            
        except Exception as e:
            logger.warning(f"⚠️ RayAgent {self.agent_id} created with limited functionality: {e}")
    
    def _initialize_memory_managers(self):
        """Initialize memory managers with proper error handling."""
        try:
            from ..memory.working_memory import MwManager
            from ..memory.long_term_memory import LongTermMemoryManager
            
            # Create organ_id for this agent
            organ_id = f"organ_for_{self.agent_id}"
            self.mw_manager = MwManager(organ_id=organ_id)
            self.mlt_manager = LongTermMemoryManager()
            
            logger.info(f"✅ Agent {self.agent_id} initialized with memory managers")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize memory managers for {self.agent_id}: {e}")
            self.mw_manager = None
            self.mlt_manager = None
        
        # Initialize Flashbulb Client
        try:
            self.mfb_client = FlashbulbClient()
            logger.info(f"✅ Agent {self.agent_id} initialized with FlashbulbClient")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize FlashbulbClient for {self.agent_id}: {e}")
            self.mfb_client = None
    
    def get_id(self) -> str:
        """Returns the agent's ID."""
        return self.agent_id
    
    def get_state_embedding(self) -> np.ndarray:
        """Returns the current state embedding vector."""
        return self.state_embedding.copy()
    
    def update_energy_state(self, energy_data: Dict[str, float]):
        """Updates the agent's knowledge of its energy contribution."""
        self.energy_state = energy_data.copy()
        
    def get_energy_state(self) -> Dict[str, float]:
        """Returns the current energy state."""
        return self.energy_state.copy()
    
    def update_role_probs(self, new_role_probs: Dict[str, float]):
        """Updates the agent's role probabilities."""
        # Validate that probabilities sum to 1.0
        total_prob = sum(new_role_probs.values())
        if abs(total_prob - 1.0) > 1e-6:
            logger.warning(f"Role probabilities don't sum to 1.0 (sum={total_prob}), normalizing")
            # Normalize
            for role in new_role_probs:
                new_role_probs[role] /= total_prob
        
        self.role_probs = new_role_probs.copy()
        self.state.p = new_role_probs.copy()  # Update AgentState
        logger.debug(f"Agent {self.agent_id} role probabilities updated: {self.role_probs}")
    
    def update_local_metrics(self, success: float, quality: float, mem_hits: int):
        """
        Update capability and memory utility using EWMA after a task.
        """
        # Update Capability (c) using EWMA
        self.state.c = (1 - 0.1) * self.state.c + 0.1 * (0.6 * success + 0.4 * quality)
        
        # Update Memory Utility (mem_util) using EWMA
        self.state.mem_util = (1 - 0.1) * self.state.mem_util + 0.1 * mem_hits
        
        # Update backward compatibility attributes
        self.capability_score = self.state.c
        self.mem_util = self.state.mem_util
        
        logger.debug(f"Agent {self.agent_id} metrics updated - capability: {self.state.c:.3f}, mem_util: {self.state.mem_util:.3f}")
    
    def get_energy_proxy(self) -> Dict[str, float]:
        """
        Returns the agent's expected contribution to energy terms.
        This is a lightweight local estimate.
        """
        return {
            'capability': self.state.c,
            'entropy_contribution': -sum(p * np.log2(p + 1e-9) for p in self.state.p.values()),
            'mem_util': self.state.mem_util,
            'state_norm': np.linalg.norm(self.state.h)
        }
    
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
        Execute a task and update performance metrics with energy tracking.
        
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
        
        # Simulate memory hits for energy tracking
        mem_hits = random.randint(0, 5)
        
        # Update memory utilization based on task complexity
        task_complexity = task_data.get('complexity', 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)
        
        # Update memory interaction tracking
        self.memory_writes += 1
        if random.random() < 0.3:  # 30% chance of being read by others
            self.memory_hits_on_writes += 1
        
        # --- END TASK LOGIC ---
        
        # Update local metrics using the new energy-aware method
        self.update_local_metrics(success, quality, mem_hits)
        
        # Update internal performance metrics for backward compatibility
        self.update_performance(success, quality, task_data)
        
        # Emit energy events for ledger updates
        try:
            # Pair success event (if this was a collaborative task)
            if task_data.get('partner_id'):
                pair_event = {
                    'type': 'pair_success',
                    'agents': [self.agent_id, task_data['partner_id']],
                    'success': success,
                    'sim': np.dot(self.state.h, task_data.get('partner_embedding', self.state.h))
                }
                logger.debug(f"Pair energy event: {pair_event}")
            
            # Role update event (if roles changed significantly)
            old_entropy = -sum(p * np.log2(p + 1e-9) for p in self.state.p.values())
            new_entropy = -sum(p * np.log2(p + 1e-9) for p in self.role_probs.values())
            if abs(new_entropy - old_entropy) > 0.1:  # Significant change
                role_event = {
                    'type': 'role_update',
                    'H_new': new_entropy,
                    'H_prev': old_entropy
                }
                logger.debug(f"Role energy event: {role_event}")
            
            # State update event (if embedding changed significantly)
            old_norm = np.linalg.norm(self.state_embedding)
            new_norm = np.linalg.norm(self.state.h)
            if abs(new_norm - old_norm) > 0.1:  # Significant change
                state_event = {
                    'type': 'state_update',
                    'norm2_new': new_norm**2,
                    'norm2_old': old_norm**2
                }
                logger.debug(f"State energy event: {state_event}")
            
            # Memory event (if memory utilization changed)
            if self.mem_util > 0:
                mem_event = {
                    'type': 'mem_event',
                    'cost_delta': self.mem_util * 0.1  # Simplified cost delta
                }
                logger.debug(f"Memory energy event: {mem_event}")
                
        except Exception as e:
            logger.warning(f"Failed to emit energy events: {e}")
        
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
            },
            "energy_state": self.energy_state  # Add energy state to heartbeat
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
    async def find_knowledge(self, fact_id: str) -> Optional[Dict[str, Any]]:
        """
        Attempts to find a piece of knowledge, implementing the Mw -> Mlt escalation.
        This is an async method that uses non-blocking calls.
        
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

        # 1. Query Working Memory (Mw) first using async method
        logger.info(f"[{self.agent_id}] 📋 Querying Working Memory (Mw)...")
        try:
            cached_data = await self.mw_manager.get_item_async(fact_id)
            
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

    async def execute_collaborative_task(self, task_info: Dict[str, Any]) -> Dict[str, Any]:
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
            knowledge = await self.find_knowledge(required_fact)  # No await needed
        
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
        
        # --- 2. Calculate Salience Score using ML Service ---
        salience_score = self._calculate_ml_salience_score(task_info, error_context)
        logger.info(f"[{self.agent_id}] Calculated ML salience score: {salience_score:.2f}")

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
    
    def _calculate_ml_salience_score(self, task_info: dict, error_context: dict) -> float:
        """Calculate salience score using ML service with circuit breaker pattern."""
        try:
            # Import the salience service client
            from src.seedcore.ml.serve_app import SalienceServiceClient
            
            # Initialize client (will be created once and reused)
            if not hasattr(self, '_salience_client'):
                self._salience_client = SalienceServiceClient()
            
            # Prepare features for ML model
            features = self._extract_salience_features(task_info, error_context)
            
            # Score using ML service
            scores = self._salience_client.score_salience([features])
            
            if scores and len(scores) > 0:
                return scores[0]
            else:
                logger.warning(f"[{self.agent_id}] No scores returned from ML service, using fallback")
                return self._fallback_salience_scorer([features])[0]
                
        except Exception as e:
            logger.error(f"[{self.agent_id}] Error in ML salience scoring: {e}, using fallback")
            return self._fallback_salience_scorer([self._extract_salience_features(task_info, error_context)])[0]
    
    def _extract_salience_features(self, task_info: dict, error_context: dict) -> dict:
        """Extract features for salience scoring from task and error context."""
        # Get current system state
        heartbeat = self.get_heartbeat()
        performance_metrics = heartbeat.get('performance_metrics', {})
        
        # Extract features for ML model
        features = {
            # Task-related features
            'task_risk': task_info.get('risk', 0.5),
            'failure_severity': 1.0,  # High severity for task failures
            'task_complexity': task_info.get('complexity', 0.5),
            'user_impact': task_info.get('user_impact', 0.5),
            'business_criticality': task_info.get('business_criticality', 0.5),
            
            # Agent-related features
            'agent_capability': performance_metrics.get('capability_score_c', 0.5),
            'agent_memory_util': performance_metrics.get('mem_util', 0.0),
            
            # System-related features (from energy state)
            'system_load': self._get_system_load(),
            'memory_usage': self._get_memory_usage(),
            'cpu_usage': self._get_cpu_usage(),
            'response_time': self._get_response_time(),
            'error_rate': self._get_error_rate(),
            
            # Error context features
            'error_code': error_context.get('code', 500),
            'error_type': self._classify_error_type(error_context.get('reason', ''))
        }
        
        return features
    
    def _get_system_load(self) -> float:
        """Get current system load from energy state."""
        try:
            energy_state = self.get_energy_state()
            # Normalize energy state to system load (0-1)
            total_energy = sum(energy_state.values())
            return min(total_energy / 10.0, 1.0)  # Normalize to 0-1 range
        except:
            return 0.5
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage."""
        try:
            return self.mem_util
        except:
            return 0.5
    
    def _get_cpu_usage(self) -> float:
        """Get current CPU usage estimate."""
        try:
            # Estimate CPU usage based on agent activity
            tasks_processed = getattr(self, 'tasks_processed', 0)
            return min(tasks_processed / 100.0, 1.0)
        except:
            return 0.5
    
    def _get_response_time(self) -> float:
        """Get current response time estimate."""
        try:
            # Estimate response time based on recent performance
            quality_scores = getattr(self, 'quality_scores', [])
            if quality_scores:
                avg_quality = sum(quality_scores) / len(quality_scores)
                # Lower quality = higher response time
                return max(0.1, 2.0 - avg_quality)
            return 1.0
        except:
            return 1.0
    
    def _get_error_rate(self) -> float:
        """Get current error rate."""
        try:
            tasks_processed = getattr(self, 'tasks_processed', 0)
            successful_tasks = getattr(self, 'successful_tasks', 0)
            if tasks_processed > 0:
                return (tasks_processed - successful_tasks) / tasks_processed
            return 0.0
        except:
            return 0.0
    
    def _classify_error_type(self, error_reason: str) -> float:
        """Classify error type for feature extraction."""
        error_reason_lower = error_reason.lower()
        
        if 'timeout' in error_reason_lower:
            return 0.8  # High severity for timeouts
        elif 'connection' in error_reason_lower:
            return 0.7  # Medium-high for connection issues
        elif 'permission' in error_reason_lower:
            return 0.6  # Medium for permission issues
        elif 'validation' in error_reason_lower:
            return 0.4  # Lower for validation errors
        else:
            return 0.5  # Default severity
    
    def _fallback_salience_scorer(self, features_list: List[dict]) -> List[float]:
        """Fallback salience scorer when ML service is unavailable."""
        scores = []
        for features in features_list:
            # Simple heuristic-based scoring (original method)
            task_risk = features.get('task_risk', 0.5)
            failure_severity = features.get('failure_severity', 0.5)
            score = task_risk * failure_severity
            
            # Add some context from other features
            agent_capability = features.get('agent_capability', 0.5)
            system_load = features.get('system_load', 0.5)
            
            # Adjust score based on agent capability and system load
            score *= (1.0 + (1.0 - agent_capability) * 0.2)  # Higher score for lower capability
            score *= (1.0 + system_load * 0.1)  # Higher score under high load
            
            scores.append(max(0.0, min(1.0, score)))
        
        return scores
    
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