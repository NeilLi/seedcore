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
import random
import ast
import operator
import uuid
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

# Safe arithmetic evaluator to replace unsafe eval()
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _safe_eval_arith(expr: str) -> float:
    """
    Evaluate simple arithmetic safely via AST (no names, no calls).
    Supports + - * / // % ** and unary +/- on numbers.
    """
    def _eval(node):
        if isinstance(node, ast.Num):  # py<3.8
            return node.n
        if isinstance(node, ast.Constant):  # py>=3.8
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numeric constants allowed")
        if isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op: raise ValueError("Operator not allowed")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op: raise ValueError("Unary operator not allowed")
            return op(_eval(node.operand))
        raise ValueError("Unsupported expression")
    tree = ast.parse(expr, mode="eval")
    return float(_eval(tree.body))

# NEW: Import the FlashbulbClient
from ..memory.flashbulb_client import FlashbulbClient

# NEW: Import the Cognitive Core
from .cognitive_core import (
    CognitiveCore, 
    CognitiveContext, 
    CognitiveTaskType,
    initialize_cognitive_core,
    get_cognitive_core
)

# === COA §6/§8: agent-private memory vector h_i ∈ R^128 ===
from .private_memory import AgentPrivateMemory, PeerEvent
from .checkpoint_store import CheckpointStoreFactory, CheckpointStore, NullStore

@dataclass
class AgentState:
    """Holds the local state for an agent."""
    h: Any  # Embedding (kept JSON-safe as Python list)
    p: Dict[str, float]  # Role probabilities
    c: float = 0.5  # Capability
    mem_util: float = 0.0  # Memory Utility

@ray.remote(max_restarts=2, max_task_retries=0, max_concurrency=1)
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
    
    def __init__(self, agent_id: str, initial_role_probs: Optional[Dict[str, float]] = None,
                 organ_id: Optional[str] = None,
                 checkpoint_cfg: Optional[Dict[str, Any]] = None):
        # 1. Agent Identity and State
        self.agent_id = agent_id
        self.instance_id = uuid.uuid4().hex  # Use UUID for instance_id
        self.organ_id = organ_id or "_"  # Set organ_id properly
        
        # 2. Initialize AgentState with COA specifications
        self.state = AgentState(
            h=[0.0] * 128,  # JSON-safe list; managed by AgentPrivateMemory
            p=initial_role_probs or {'E': 0.9, 'S': 0.1, 'O': 0.0},
            c=0.5,  # Initial capability
            mem_util=0.0  # Initial memory utility
        )
        
        # 3. Backward compatibility - keep old attributes
        # Keep a separate numpy copy for legacy paths that expect ndarray
        self.state_embedding = np.array(self.state.h, dtype=np.float32)
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
        self.lifecycle_state: str = "Employed"
        self.idle_ticks: int = 0
        self.max_idle: int = 1000
        self._archived: bool = False
        
        # --- Initialize memory managers with better error handling ---
        self.mw_manager = None
        self.mlt_manager = None
        self.mfb_client = None
        
        # --- Initialize cognitive core ---
        self.cognitive_core = None

        # --- Initialize private memory (lifetime-only persistence) ---
        self._privmem = AgentPrivateMemory(agent_id=self.agent_id, alpha=0.1)
        # Optional checkpoint store (disabled by default)
        self._ckpt_cfg = checkpoint_cfg or {"enabled": False}
        self._ckpt_store: CheckpointStore = CheckpointStoreFactory.from_config(self._ckpt_cfg)
        self._ckpt_key = f"{self.organ_id}/{self.agent_id}"
        self._maybe_restore()
        
        # Initialize memory managers asynchronously to avoid hanging
        try:
            # Only initialize basic components, defer complex initialization
            logger.info(f"✅ RayAgent {self.agent_id} created with basic state")
            
            # Initialize memory managers later if needed
            self._initialize_memory_managers()
            
            # Initialize cognitive systems
            self._initialize_cognitive_systems()
            
        except Exception as e:
            logger.warning(f"⚠️ RayAgent {self.agent_id} created with limited functionality: {e}")
    
    def _initialize_memory_managers(self):
        """Initialize memory managers with proper error handling."""
        try:
            from ..memory.working_memory import MwManager
            from ..memory.long_term_memory import LongTermMemoryManager
            
            # Use provided organ_id or fallback to generated one
            organ_id = self.organ_id or f"organ_for_{self.agent_id}"
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
    
    def _initialize_cognitive_systems(self):
        """Initialize cognitive reasoning systems."""
        try:
            # Get or initialize the global cognitive core
            self.cognitive_core = get_cognitive_core()
            if self.cognitive_core is None:
                # Initialize with default settings
                self.cognitive_core = initialize_cognitive_core()
            
            logger.info(f"✅ Agent {self.agent_id} initialized with cognitive core")
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize cognitive core for {self.agent_id}: {e}")
            self.cognitive_core = None
    
    def _mw_put_json(self, key: str, obj: Dict[str, Any], ttl_s: int = 600) -> bool:
        """Put JSON object to Mw with TTL."""
        if not self.mw_manager:
            return False
        try:
            self.mw_manager.set_item(key, json.dumps(obj), ttl=ttl_s)  # supports ttl if your MwManager does
            self.memory_writes += 1
            self._mw_puts = getattr(self, "_mw_puts", 0) + 1
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mw put failed for {key}: {e}")
            return False

    def _promote_to_mlt(self, key: str, obj: Dict[str, Any], compression: bool = True) -> bool:
        """Promote object to Mlt with optional compression."""
        if not self.mlt_manager:
            return False
        try:
            payload = obj
            if compression and isinstance(obj, dict):
                # toy "compression": drop large fields & keep summary size
                pruned = {k: v for k, v in obj.items() if k not in ("raw", "tokens", "trace")}
                if "raw" in obj:
                    pruned["raw_size"] = len(str(obj["raw"]))  # track size
                payload = pruned
                self.total_compression_gain += max(0.0, len(str(obj)) - len(str(pruned)))
            self.mlt_manager.store_holon(key, payload)  # consistent with your mlt API
            self._mlt_promotions = getattr(self, "_mlt_promotions", 0) + 1
            return True
        except Exception as e:
            logger.debug(f"[{self.agent_id}] Mlt promote failed for {key}: {e}")
            return False

    def _energy_slice(self) -> float:
        """A simple local scalar we can use as 'E' proxy: norm(h) + capability + 0.1*mem_util."""
        try:
            norm = float(np.linalg.norm(self.state_embedding))
        except Exception:
            norm = float(np.linalg.norm(np.array(self.state.h, dtype=np.float32)))
        return norm + float(self.capability_score) + 0.1 * float(self.mem_util)

    def build_memory_fragments(self, *, anomalies=None, reason=None, decision=None) -> List[Dict[str, Any]]:
        """
        Return canonical fragments for best-effort synthesis. Pure data; no I/O.
        """
        frags = []
        if anomalies is not None:
            frags.append({"anomalies": anomalies})
        if reason is not None:
            frags.append({"reason": reason})
        if decision is not None:
            frags.append({"decision": decision})
        # include a tiny local context snapshot
        frags.append({"agent_snapshot": {
            "agent_id": self.agent_id,
            "capability": self.capability_score,
            "mem_util": self.mem_util,
            "h_norm": float(np.linalg.norm(self.state_embedding)),
            "ts": time.time(),
        }})
        return frags
    
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

    def ping(self) -> Dict[str, Any]:
        """Cheap liveness RPC used by Tier-0 to detect/prune dead handles."""
        return {"id": self.agent_id, "ts": time.time()}
    
    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status information for the agent."""
        current_time = time.time()
        uptime = current_time - self.created_at
        
        return {
            "agent_id": self.agent_id,
            "organ_id": self.organ_id,
            "instance_id": self.instance_id,
            "uptime_s": round(uptime, 3),
            "status": "healthy",
            "lifecycle_state": self.lifecycle_state,
            "capability_score": round(self.capability_score, 3),
            "memory_utilization": round(self.mem_util, 3),
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks,
            "success_rate": round(self.successful_tasks / max(self.tasks_processed, 1), 3),
            "role_probabilities": self.role_probs.copy(),
            "energy_state": self.energy_state.copy(),
            "memory_writes": self.memory_writes,
            "memory_hits_on_writes": self.memory_hits_on_writes,
            "salient_events_logged": self.salient_events_logged,
            "idle_ticks": self.idle_ticks,
            "archived": self._archived,
            "last_heartbeat": self.last_heartbeat,
            "created_at": self.created_at,
        }
    
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
        
        # Update state for backward compatibility
        self.state.capability_score = self.capability_score
        
        # Update memory utility if memory stats are provided
        if task_metadata and 'memory_stats' in task_metadata:
            from .lifecycle import update_agent_metrics
            mem_stats = task_metadata['memory_stats']
            update_agent_metrics(self.state, success, quality, mem_stats)
            self.mem_util = self.state.mem_util
        
        # Update task record with capability and memory utility
        task_record['capability_score'] = self.capability_score
        task_record['mem_util'] = self.mem_util
        
        logger.info(f"📈 Agent {self.agent_id} performance updated: Capability={self.capability_score:.3f}, MemUtil={self.mem_util:.3f}")
    
    def execute_task(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a task and update performance metrics with energy tracking.
        
        Args:
            task_data: Task information and payload
            
        Returns:
            Task execution result with performance metrics
        """
        logger.info(f"🤖 Agent {self.agent_id} executing task: {task_data.get('task_id', 'unknown')}")
        
        # Capture energy before task execution
        E_before = self._energy_slice()
        
        # --- TASK EXECUTION LOGIC ---
        task_type = task_data.get('type', 'unknown')
        task_description = task_data.get('description', '')
        
        # Handle specific task types with real implementations
        if task_type == 'general_query':
            result = self._handle_general_query(task_description, task_data)
        else:
            # Fallback to simulation for other task types
            result = self._simulate_task_execution(task_data)
        
        # Update memory utilization based on task complexity
        task_complexity = task_data.get('complexity', 0.5)
        self.mem_util = min(1.0, self.mem_util + task_complexity * 0.1)
        
        # Update memory interaction tracking
        self.memory_writes += 1
        if random.random() < 0.3:  # 30% chance of being read by others
            self.memory_hits_on_writes += 1
        
        # Update local metrics using the new energy-aware method
        self.update_local_metrics(result.get('success', False), result.get('quality', 0.5), result.get('mem_hits', 0))
        
        # Calculate energy after task execution
        E_after = self._energy_slice()
        delta_e = E_after - E_before
        result["delta_e_realized"] = delta_e
        result["E_before"] = E_before
        result["E_after"] = E_after
        
        # --- Mw/Mlt write path and promotion ---
        artifact_key = f"task:{task_data.get('task_id','unknown')}"
        artifact = {
            "agent_id": self.agent_id,
            "type": task_type,
            "ts": time.time(),
            "result": result.get("result"),
            "success": result.get("success", False),
            "quality": result.get("quality", 0.5),
        }
        self._mw_put_json(artifact_key, artifact, ttl_s=600)

        # simple policy: promote successes with quality>=0.8, or failures with salience >= 0.7 (if present)
        should_promote = artifact["success"] and artifact["quality"] >= 0.8
        sal = result.get("salience_score")
        if sal is not None:
            should_promote = should_promote or (not artifact["success"] and sal >= 0.7)
        if should_promote:
            self._promote_to_mlt(artifact_key, artifact, compression=True)
        
        return result

    def _handle_general_query(self, description: str, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle general_query tasks with real implementations.
        
        Args:
            description: Task description
            task_data: Full task data
            
        Returns:
            Task execution result
        """
        try:
            description_lower = description.lower()
            
            # Handle time-related queries
            if any(word in description_lower for word in ['time', 'what time', 'current time', 'utc', 'gmt']):
                import datetime
                utc_time = datetime.datetime.utcnow()
                local_time = datetime.datetime.now()
                
                result = {
                    "query_type": "time_query",
                    "utc_time": utc_time.isoformat(),
                    "local_time": local_time.isoformat(),
                    "timezone": "UTC",
                    "formatted": f"Current UTC time: {utc_time.strftime('%Y-%m-%d %H:%M:%S')} UTC",
                    "description": description
                }
                
                logger.info(f"✅ Agent {self.agent_id} handled time query: {result['formatted']}")
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 1.0,
                    "capability_score": self.capability_score,
                    "mem_util": self.mem_util,
                    "result": result,
                    "mem_hits": 1
                }
            
            # Handle date-related queries
            elif any(word in description_lower for word in ['date', 'today', 'what date', 'current date']):
                import datetime
                today = datetime.datetime.now()
                
                result = {
                    "query_type": "date_query",
                    "current_date": today.strftime('%Y-%m-%d'),
                    "day_of_week": today.strftime('%A'),
                    "formatted": f"Today is {today.strftime('%A, %B %d, %Y')}",
                    "description": description
                }
                
                logger.info(f"✅ Agent {self.agent_id} handled date query: {result['formatted']}")
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 1.0,
                    "capability_score": self.capability_score,
                    "mem_util": self.mem_util,
                    "result": result,
                    "mem_hits": 1
                }
            
            # Handle system status queries
            elif any(word in description_lower for word in ['status', 'health', 'system', 'how are you', 'are you working']):
                result = {
                    "query_type": "system_status",
                    "agent_status": "healthy",
                    "agent_id": self.agent_id,
                    "capability_score": self.capability_score,
                    "memory_utilization": self.mem_util,
                    "formatted": f"Agent {self.agent_id} is healthy and operational. Capability: {self.capability_score:.3f}, Memory: {self.mem_util:.3f}",
                    "description": description
                }
                
                logger.info(f"✅ Agent {self.agent_id} handled system status query")
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 1.0,
                    "capability_score": self.capability_score,
                    "mem_util": self.mem_util,
                    "result": result,
                    "mem_hits": 1
                }
            
            # Handle mathematical queries
            elif any(word in description_lower for word in ['calculate', 'math', 'compute', 'what is', 'solve']):
                try:
                    # Simple mathematical expression evaluation
                    import re
                    import ast
                    
                    # Extract mathematical expressions (basic pattern)
                    math_pattern = r'(\d+\s*[\+\-\*\/]\s*\d+)'
                    matches = re.findall(math_pattern, description)
                    
                    if matches:
                        expression = matches[0]
                        # Safe evaluation using our custom arithmetic evaluator
                        try:
                            value = _safe_eval_arith(expression)
                            result = {
                                "query_type": "math_query",
                                "expression": expression,
                                "result": value,
                                "formatted": f"The result of {expression} is {value}",
                                "description": description
                            }
                        except Exception as e:
                            result = {
                                "query_type": "math_query",
                                "error": f"Failed to evaluate expression: {str(e)}",
                                "formatted": f"I couldn't evaluate the expression '{expression}': {str(e)}",
                                "description": description
                            }
                    else:
                        result = {
                            "query_type": "math_query",
                            "error": "No mathematical expression found in query",
                            "formatted": "I couldn't find a mathematical expression to evaluate in your query.",
                            "description": description
                        }
                    
                    logger.info(f"✅ Agent {self.agent_id} handled math query: {result.get('formatted', '')}")
                    return {
                        "agent_id": self.agent_id,
                        "task_processed": True,
                        "success": True,
                        "quality": 0.9,
                        "capability_score": self.capability_score,
                        "mem_util": self.mem_util,
                        "result": result,
                        "mem_hits": 1
                    }
                except Exception as e:
                    result = {
                        "query_type": "math_query",
                        "error": f"Failed to evaluate mathematical expression: {str(e)}",
                        "formatted": "I encountered an error while trying to evaluate the mathematical expression.",
                        "description": description
                    }
                    
                    logger.warning(f"⚠️ Agent {self.agent_id} failed math query: {e}")
                    return {
                        "agent_id": self.agent_id,
                        "task_processed": True,
                        "success": False,
                        "quality": 0.0,
                        "capability_score": self.capability_score,
                        "mem_util": self.mem_util,
                        "result": result,
                        "mem_hits": 1
                    }
            
            # Default response for unrecognized queries
            else:
                result = {
                    "query_type": "general_query",
                    "message": "I received your query but don't have a specific handler for it yet.",
                    "query": description,
                    "formatted": f"Query: '{description}'. This is a general query that I'm still learning to handle.",
                    "description": description
                }
                
                logger.info(f"ℹ️ Agent {self.agent_id} handled general query (no specific handler)")
                return {
                    "agent_id": self.agent_id,
                    "task_processed": True,
                    "success": True,
                    "quality": 0.7,
                    "capability_score": self.capability_score,
                    "mem_util": self.mem_util,
                    "result": result,
                    "mem_hits": 1
                }
                
        except Exception as e:
            logger.error(f"❌ Agent {self.agent_id} failed to handle general query: {e}")
            return {
                "agent_id": self.agent_id,
                "task_processed": True,
                "success": False,
                "quality": 0.0,
                "capability_score": self.capability_score,
                "mem_util": self.mem_util,
                "error": str(e),
                "result": {
                    "query_type": "general_query",
                    "error": f"Task execution failed: {str(e)}",
                    "formatted": "I encountered an error while processing your query.",
                    "description": description
                },
                "mem_hits": 0
            }

    def _simulate_task_execution(self, task_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Simulate task execution for non-general_query tasks.
        This maintains backward compatibility for other task types.
        """
        import random
        
        # Simulate task execution with some randomness
        success = random.choice([True, False])
        quality = random.uniform(0.5, 1.0)
        
        # Simulate memory hits for energy tracking
        mem_hits = random.randint(0, 5)
        
        return {
            "agent_id": self.agent_id,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "mem_hits": mem_hits
        }
    
    # === Telemetry surfaces for Tier-0 / Meta-learning ===
    def get_private_memory_vector(self) -> List[float]:
        return self._privmem.get_vector().tolist()

    def get_private_memory_telemetry(self) -> Dict[str, Any]:
        return self._privmem.telemetry()

    def reset_private_memory(self) -> bool:
        self._privmem.reset()
        self.state.h[:] = 0.0
        return True

    def _export_tier0_summary(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "embedding": self.state.h,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "tasks_processed": self.tasks_processed,
            "success_rate": (self.successful_tasks / self.tasks_processed) if self.tasks_processed else 0.0,
            "skill_deltas": self.skill_deltas,
            "peer_interactions": self.peer_interactions,
        }

    def archive(self) -> bool:
        """Move Tier-0 summaries to Mlt and mark this actor as archived."""
        try:
            summary = self._export_tier0_summary()
            if self.mlt_manager and hasattr(self.mlt_manager, "store_agent_summary"):
                self.mlt_manager.store_agent_summary(self.agent_id, summary)  # type: ignore[attr-defined]
            if self.mw_manager and hasattr(self.mw_manager, "evict_agent"):
                self.mw_manager.evict_agent(self.agent_id)  # type: ignore[attr-defined]
            if self.mfb_client and hasattr(self.mfb_client, "log_incident"):
                try:
                    self.mfb_client.log_incident({"archive": True, "summary": summary}, salience=0.3)
                except Exception:
                    pass
            self._archived = True
            self.lifecycle_state = "Archived"
            return True
        except Exception as e:
            logger.exception(f"Archive failed for {self.agent_id}: {e}")
            return False

    # ---------- Checkpointing ----------
    def _maybe_restore(self):
        try:
            if self._ckpt_cfg.get("enabled") and hasattr(self._privmem, "load"):
                blob = self._ckpt_store.load(self._ckpt_key)
                if blob:
                    self._privmem.load(blob)
                    self.state.h = self._privmem.get_vector_list()
                    self.state_embedding = np.array(self.state.h, dtype=np.float32)
        except Exception as e:
            logger.warning(f"[{self.agent_id}] restore failed: {e}")

    def _post_task_housekeeping(self):
        try:
            if self._ckpt_cfg.get("enabled") and hasattr(self._privmem, "dump"):
                self._ckpt_store.save(self._ckpt_key, self._privmem.dump())
        except Exception as e:
            logger.warning(f"[{self.agent_id}] checkpoint failed: {e}")
    
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
                "total_compression_gain": self.total_compression_gain,
                "mw_puts": getattr(self, "_mw_puts", 0),
                "mlt_promotions": getattr(self, "_mlt_promotions", 0),
            },
            "local_state": {
                "skill_deltas": self.skill_deltas,
                "peer_interactions": self.peer_interactions,
                "recent_quality_scores": self.quality_scores[-5:] if self.quality_scores else []
            },
            "lifecycle": {
                "state": self.lifecycle_state,
                "created_at": self.created_at,
                "last_heartbeat": self.last_heartbeat,
                "uptime": time.time() - self.created_at,
                "capability_c": self.capability_score,
                "mem_util": self.mem_util,
                "idle_ticks": self.idle_ticks,
                "archived": self._archived,
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
        This is an async method that uses non-blocking calls with negative caching and single-flight guards.
        
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

        # Check negative cache first (avoid stampede on cold misses)
        if await self.mw_manager.check_negative_cache("fact", "global", fact_id):
            logger.info(f"[{self.agent_id}] NEG-HIT for {fact_id}; skipping Mlt lookup")
            return None

        # Try to acquire single-flight sentinel atomically
        sentinel_key = f"_inflight:fact:global:{fact_id}"
        sentinel_acquired = await self.mw_manager.try_set_inflight(sentinel_key, ttl_s=5)
        if not sentinel_acquired:
            logger.info(f"[{self.agent_id}] Another worker is fetching {fact_id}, waiting briefly...")
            # Wait briefly for the other worker to complete
            await asyncio.sleep(0.05)  # Brief backoff
            # Try to get the result that might have been cached
            cached_data = await self.mw_manager.get_item_typed_async("fact", "global", fact_id)
            if cached_data:
                logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' after waiting (cache hit).")
                try:
                    return json.loads(cached_data) if isinstance(cached_data, str) else cached_data
                except json.JSONDecodeError:
                    logger.warning(f"[{self.agent_id}] ⚠️ Failed to parse cached data as JSON")
                    return {"raw_data": cached_data}
            return None

        try:
            # 1. Query Working Memory (Mw) first using typed key format
            logger.info(f"[{self.agent_id}] 📋 Querying Working Memory (Mw)...")
            try:
                cached_data = await self.mw_manager.get_item_typed_async("fact", "global", fact_id)
                
                if cached_data:
                    logger.info(f"[{self.agent_id}] ✅ Found '{fact_id}' in Mw (cache hit).")
                    try:
                        return json.loads(cached_data) if isinstance(cached_data, str) else cached_data
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
                    
                    # 3. Cache the retrieved data back into Mw for future use using global write-through
                    logger.info(f"[{self.agent_id}] 💾 Caching '{fact_id}' back to Mw...")
                    try:
                        # Use set_global_item for cluster-wide visibility with TTL
                        self.mw_manager.set_global_item_typed("fact", "global", fact_id, json.dumps(long_term_data), ttl_s=900)
                        logger.info(f"[{self.agent_id}] ✅ Successfully cached to Mw (global)")
                    except Exception as e:
                        logger.error(f"[{self.agent_id}] ❌ Failed to cache to Mw: {e}")
                    
                    return long_term_data
                else:
                    # On total miss: write short-lived negative cache (30s)
                    logger.info(f"[{self.agent_id}] ❌ '{fact_id}' not found in Mlt. Setting negative cache.")
                    try:
                        self.mw_manager.set_negative_cache("fact", "global", fact_id, ttl_s=30)
                    except Exception as e:
                        logger.error(f"[{self.agent_id}] ❌ Failed to set negative cache: {e}")
                    
                    return None
            except Exception as e:
                logger.error(f"[{self.agent_id}] ❌ Error querying Mlt: {e}")
        finally:
            # Always clear in-flight sentinel
            try:
                await self.mw_manager.del_global_key(sentinel_key)
            except Exception:
                pass
        
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
        
        # Capture energy before task execution
        E_before = self._energy_slice()
        
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
        
        # Calculate energy after task execution
        E_after = self._energy_slice()
        delta_e = E_after - E_before
        
        result = {
            "agent_id": self.agent_id,
            "task_name": task_name,
            "task_processed": True,
            "success": success,
            "quality": quality,
            "capability_score": self.capability_score,
            "mem_util": self.mem_util,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get('content', None) if knowledge else None,
            "delta_e_realized": delta_e,
            "E_before": E_before,
            "E_after": E_after
        }
        
        # --- Mw/Mlt write path and promotion ---
        artifact_key = f"task:{task_info.get('task_id', task_name)}"
        artifact = {
            "agent_id": self.agent_id,
            "type": "collab_task",
            "ts": time.time(),
            "required_fact": required_fact,
            "knowledge_found": knowledge is not None,
            "knowledge_content": knowledge.get('content') if knowledge else None,
            "success": success,
            "quality": quality,
        }
        self._mw_put_json(artifact_key, artifact, ttl_s=900)
        if success and quality >= 0.8:
            self._promote_to_mlt(artifact_key, artifact, compression=True)
        
        return result

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
                    
                    # Also drop a compact pointer in Mw with a short TTL
                    if self.mw_manager:
                        try:
                            ptr_key = f"incident:{task_info.get('id', 'unknown')}"
                            self.mw_manager.set_global_item_typed("incident", "global", ptr_key, 
                                                                {"mfb_id": incident_logged}, ttl_s=1800)
                            logger.debug(f"[{self.agent_id}] Incident pointer cached in Mw")
                        except Exception as e:
                            logger.debug(f"[{self.agent_id}] Failed to cache incident pointer: {e}")
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
                
                # Light-touch hot-item prewarming with rate limiting
                if self.mw_manager and random.random() < 0.1:
                    # Reset rate limit counter every minute
                    now = time.time()
                    if now - self._prewarm_reset_time > 60:
                        self._prewarm_count = 0
                        self._prewarm_reset_time = now
                    
                    # Check rate limit
                    if self._prewarm_count < self._max_prewarm_per_minute:
                        try:
                            hot_items = await self.mw_manager.get_hot_items_async(top_n=5)
                            for item_id, _cnt in hot_items:
                                # Touch into L0 via get_item_async (promotes if present in L1/L2)
                                _ = await self.mw_manager.get_item_async(item_id)
                                self._prewarm_count += 1
                            if hot_items:
                                logger.debug(f"[{self.agent_id}] Pre-warmed {len(hot_items)} hot items")
                        except Exception as e:
                            logger.debug(f"[{self.agent_id}] Hot-item prewarming failed: {e}")
                
                # Log cache telemetry every 10th heartbeat
                if self.mw_manager and self.tasks_processed % 10 == 0:
                    try:
                        telemetry = self.mw_manager.get_telemetry()
                        logger.info(f"[{self.agent_id}] Cache telemetry: {telemetry}")
                    except Exception as e:
                        logger.debug(f"[{self.agent_id}] Telemetry logging failed: {e}")
                
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
        
        # Rate limiting for prewarm
        self._prewarm_count = 0
        self._prewarm_reset_time = time.time()
        self._max_prewarm_per_minute = 10
        logger.info(f"🔄 Agent {self.agent_id} metrics reset")
    
    # =============================================================================
    # Cognitive Reasoning Methods
    # =============================================================================
    
    async def reason_about_failure(self, incident_id: str) -> Dict[str, Any]:
        """
        Analyze agent failures using cognitive reasoning.
        
        Args:
            incident_id: ID of the incident to analyze
            
        Returns:
            Dictionary containing analysis results
        """
        if not self.cognitive_core:
            return {"success": False, "reason": "Cognitive core not initialized."}
        if not self.mfb_client:
            return {"success": False, "reason": "Memory client not available."}

        try:
            # Get incident context from memory
            incident_context_dict = self.mfb_client.get_incident(incident_id)
            if not incident_context_dict:
                return {"success": False, "reason": "Incident not found."}
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=self.agent_id,
                task_type=CognitiveTaskType.FAILURE_ANALYSIS,
                input_data=incident_context_dict,
                memory_context=self._get_memory_context(),
                energy_context=self.get_energy_state(),
                lifecycle_context=self._get_lifecycle_context()
            )
            
            # Perform cognitive reasoning
            reasoning_result = self.cognitive_core(context)
            
            # Calculate energy cost for reasoning
            reg_delta = 0.01 * len(reasoning_result.get("thought", ""))
            
            # Update energy state
            current_energy = self.get_energy_state()
            current_energy["cognitive_cost"] = current_energy.get("cognitive_cost", 0.0) + reg_delta
            self.update_energy_state(current_energy)
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "thought_process": reasoning_result.get("thought", ""),
                "proposed_solution": reasoning_result.get("proposed_solution", ""),
                "confidence_score": reasoning_result.get("confidence_score", 0.0),
                "energy_cost": reg_delta
            }
            
        except Exception as e:
            logger.error(f"Error in failure reasoning for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "incident_id": incident_id,
                "error": str(e)
            }
    
    async def plan_complex_task(self, task_description: str, available_resources: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Plan complex tasks using cognitive reasoning.
        
        Args:
            task_description: Description of the task to plan
            available_resources: Available resources and constraints
            
        Returns:
            Dictionary containing task plan
        """
        if not self.cognitive_core:
            return {"success": False, "reason": "Cognitive core not initialized."}

        try:
            # Prepare input data
            input_data = {
                "task_description": task_description,
                "agent_capabilities": self._get_agent_capabilities(),
                "available_resources": available_resources or {}
            }
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=self.agent_id,
                task_type=CognitiveTaskType.TASK_PLANNING,
                input_data=input_data,
                memory_context=self._get_memory_context(),
                energy_context=self.get_energy_state(),
                lifecycle_context=self._get_lifecycle_context()
            )
            
            # Perform cognitive reasoning
            planning_result = self.cognitive_core(context)
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "task_description": task_description,
                "step_by_step_plan": planning_result.get("step_by_step_plan", ""),
                "estimated_complexity": planning_result.get("estimated_complexity", ""),
                "risk_assessment": planning_result.get("risk_assessment", "")
            }
            
        except Exception as e:
            logger.error(f"Error in task planning for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "task_description": task_description,
                "error": str(e)
            }
    
    async def make_decision(self, decision_context: Dict[str, Any], historical_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make decisions using cognitive reasoning.
        
        Args:
            decision_context: Context for the decision
            historical_data: Historical data to inform the decision
            
        Returns:
            Dictionary containing decision results
        """
        if not self.cognitive_core:
            return {"success": False, "reason": "Cognitive core not initialized."}

        try:
            # Prepare input data
            input_data = {
                "decision_context": decision_context,
                "historical_data": historical_data or {}
            }
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=self.agent_id,
                task_type=CognitiveTaskType.DECISION_MAKING,
                input_data=input_data,
                memory_context=self._get_memory_context(),
                energy_context=self.get_energy_state(),
                lifecycle_context=self._get_lifecycle_context()
            )
            
            # Perform cognitive reasoning
            decision_result = self.cognitive_core(context)
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "reasoning": decision_result.get("reasoning", ""),
                "decision": decision_result.get("decision", ""),
                "confidence": decision_result.get("confidence", 0.0),
                "alternative_options": decision_result.get("alternative_options", "")
            }
            
        except Exception as e:
            logger.error(f"Error in decision making for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": str(e)
            }
    
    async def synthesize_memory(self, memory_fragments: List[Dict[str, Any]], synthesis_goal: str) -> Dict[str, Any]:
        """
        Synthesize information from multiple memory sources.
        
        Args:
            memory_fragments: List of memory fragments to synthesize
            synthesis_goal: Goal of the synthesis
            
        Returns:
            Dictionary containing synthesis results
        """
        if not self.cognitive_core:
            return {"success": False, "reason": "Cognitive core not initialized."}

        try:
            # Prepare input data
            input_data = {
                "memory_fragments": memory_fragments,
                "synthesis_goal": synthesis_goal
            }
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=self.agent_id,
                task_type=CognitiveTaskType.MEMORY_SYNTHESIS,
                input_data=input_data,
                memory_context=self._get_memory_context(),
                energy_context=self.get_energy_state(),
                lifecycle_context=self._get_lifecycle_context()
            )
            
            # Perform cognitive reasoning
            synthesis_result = self.cognitive_core(context)
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "synthesized_insight": synthesis_result.get("synthesized_insight", ""),
                "confidence_level": synthesis_result.get("confidence_level", 0.0),
                "related_patterns": synthesis_result.get("related_patterns", "")
            }
            
        except Exception as e:
            logger.error(f"Error in memory synthesis for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": str(e)
            }
    
    async def assess_capabilities(self, target_capabilities: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Assess agent capabilities and suggest improvements.
        
        Args:
            target_capabilities: Target capabilities to assess against
            
        Returns:
            Dictionary containing assessment results
        """
        if not self.cognitive_core:
            return {"success": False, "reason": "Cognitive core not initialized."}

        try:
            # Prepare input data
            input_data = {
                "performance_data": self._get_performance_data(),
                "current_capabilities": self._get_agent_capabilities(),
                "target_capabilities": target_capabilities or {}
            }
            
            # Create cognitive context
            context = CognitiveContext(
                agent_id=self.agent_id,
                task_type=CognitiveTaskType.CAPABILITY_ASSESSMENT,
                input_data=input_data,
                memory_context=self._get_memory_context(),
                energy_context=self.get_energy_state(),
                lifecycle_context=self._get_lifecycle_context()
            )
            
            # Perform cognitive reasoning
            assessment_result = self.cognitive_core(context)
            
            return {
                "success": True,
                "agent_id": self.agent_id,
                "capability_gaps": assessment_result.get("capability_gaps", ""),
                "improvement_plan": assessment_result.get("improvement_plan", ""),
                "priority_recommendations": assessment_result.get("priority_recommendations", "")
            }
            
        except Exception as e:
            logger.error(f"Error in capability assessment for agent {self.agent_id}: {e}")
            return {
                "success": False,
                "agent_id": self.agent_id,
                "error": str(e)
            }
    
    # =============================================================================
    # Helper Methods for Cognitive Context
    # =============================================================================
    
    def _get_memory_context(self) -> Dict[str, Any]:
        """Get memory context for cognitive tasks."""
        return {
            "memory_utilization": self.mem_util,
            "memory_writes": self.memory_writes,
            "memory_hits": self.memory_hits_on_writes,
            "compression_gain": self.total_compression_gain,
            "skill_deltas": self.skill_deltas.copy()
        }
    
    def _get_lifecycle_context(self) -> Dict[str, Any]:
        """Get lifecycle context for cognitive tasks."""
        return {
            "agent_id": self.agent_id,
            "created_at": self.created_at,
            "last_heartbeat": self.last_heartbeat,
            "capability_score": self.capability_score,
            "role_probabilities": self.role_probs.copy(),
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks
        }
    
    def _get_agent_capabilities(self) -> Dict[str, Any]:
        """Get current agent capabilities."""
        return {
            "capability_score": self.capability_score,
            "role_probabilities": self.role_probs.copy(),
            "skill_deltas": self.skill_deltas.copy(),
            "performance_history": {
                "tasks_processed": self.tasks_processed,
                "successful_tasks": self.successful_tasks,
                "avg_quality": sum(self.quality_scores) / len(self.quality_scores) if self.quality_scores else 0.0
            }
        }
    
    def _get_performance_data(self) -> Dict[str, Any]:
        """Get performance data for capability assessment."""
        return {
            "tasks_processed": self.tasks_processed,
            "successful_tasks": self.successful_tasks,
            "quality_scores": self.quality_scores.copy(),
            "capability_score": self.capability_score,
            "memory_utilization": self.mem_util,
            "peer_interactions": self.peer_interactions.copy()
        } 