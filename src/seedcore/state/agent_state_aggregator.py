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
AgentStateAggregator - Lightweight aggregator for agent state collection

Efficiently collects and aggregates state from distributed RayAgent instances:
- h vectors (state embeddings)
- P matrix (role probabilities)
- Capability scores and memory utilization
- Lifecycle state transitions

Implements Paper §3.1 requirements for light aggregators from live Ray actors.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import ray

from ..models.state import AgentSnapshot

logger = logging.getLogger(__name__)


class AgentStateAggregator:
    """
    Lightweight aggregator for collecting agent state from Ray actors.
    
    Features:
    - Batch Ray calls for efficiency
    - Smart caching to reduce overhead
    - Error handling and graceful degradation
    - Support for H matrix and P matrix construction
    - Lifecycle state tracking
    """
    
    def __init__(self, organism_manager, cache_ttl: float = 5.0):
        """
        Initialize the agent state aggregator.
        
        Args:
            organism_manager: Reference to the OrganismManager instance
            cache_ttl: Cache time-to-live in seconds
        """
        self.organism = organism_manager
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._last_update = 0.0
        
        logger.info("✅ AgentStateAggregator initialized")
    
    async def collect_agent_snapshots(self, agent_ids: List[str]) -> Dict[str, AgentSnapshot]:
        """
        Collect agent snapshots from Ray actors.
        
        Args:
            agent_ids: List of agent IDs to collect state for
            
        Returns:
            Dictionary mapping agent_id to AgentSnapshot
        """
        if not agent_ids:
            return {}
        
        logger.debug(f"Collecting agent snapshots for {len(agent_ids)} agents")
        
        # Check cache first
        cache_key = f"agent_snapshots_{hash(tuple(sorted(agent_ids)))}"
        if self._is_cache_valid(cache_key):
            logger.debug("Using cached agent snapshots")
            return self._cache[cache_key]
        
        # Collect agent handles efficiently
        agent_handles = await self._get_agent_handles(agent_ids)
        if not agent_handles:
            logger.warning("No valid agent handles found")
            return {}
        
        # Batch collect heartbeats from all agents
        try:
            heartbeat_refs = [agent.get_heartbeat.remote() for agent in agent_handles]
            heartbeats = await self._async_ray_get(heartbeat_refs)
            
            # Build agent snapshots
            agent_snapshots = {}
            for i, agent_id in enumerate(agent_handles.keys()):
                try:
                    hb = heartbeats[i] if i < len(heartbeats) else {}
                    agent_snapshots[agent_id] = self._build_agent_snapshot(agent_id, hb)
                except Exception as e:
                    logger.warning(f"Failed to process agent {agent_id}: {e}")
                    continue
            
            # Cache the results
            self._cache[cache_key] = agent_snapshots
            self._last_update = time.time()
            
            logger.debug(f"Successfully collected {len(agent_snapshots)} agent snapshots")
            return agent_snapshots
            
        except Exception as e:
            logger.error(f"Failed to collect agent heartbeats: {e}")
            return {}
    
    async def collect_h_vectors(self, agent_ids: List[str]) -> Dict[str, np.ndarray]:
        """
        Collect h vectors (state embeddings) from agents.
        
        Args:
            agent_ids: List of agent IDs to collect h vectors for
            
        Returns:
            Dictionary mapping agent_id to h vector
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        return {
            agent_id: snapshot.h
            for agent_id, snapshot in agent_snapshots.items()
        }
    
    async def collect_p_matrix(self, agent_ids: List[str]) -> np.ndarray:
        """
        Collect and aggregate role probabilities into P matrix.
        
        Args:
            agent_ids: List of agent IDs to collect role probabilities for
            
        Returns:
            P matrix with shape (n_agents, 3) for [E, S, O] roles
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        
        if not agent_snapshots:
            return np.zeros((0, 3), dtype=np.float32)
        
        p_vectors = []
        for snapshot in agent_snapshots.values():
            p_vector = [
                float(snapshot.p.get("E", 0.0)),
                float(snapshot.p.get("S", 0.0)),
                float(snapshot.p.get("O", 0.0))
            ]
            p_vectors.append(p_vector)
        
        return np.array(p_vectors, dtype=np.float32)
    
    async def collect_capability_scores(self, agent_ids: List[str]) -> Dict[str, float]:
        """
        Collect capability scores from agents.
        
        Args:
            agent_ids: List of agent IDs to collect capability scores for
            
        Returns:
            Dictionary mapping agent_id to capability score
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        return {
            agent_id: snapshot.c
            for agent_id, snapshot in agent_snapshots.items()
        }
    
    async def collect_memory_utilization(self, agent_ids: List[str]) -> Dict[str, float]:
        """
        Collect memory utilization from agents.
        
        Args:
            agent_ids: List of agent IDs to collect memory utilization for
            
        Returns:
            Dictionary mapping agent_id to memory utilization
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        return {
            agent_id: snapshot.mem_util
            for agent_id, snapshot in agent_snapshots.items()
        }
    
    async def collect_lifecycle_states(self, agent_ids: List[str]) -> Dict[str, str]:
        """
        Collect lifecycle states from agents.
        
        Args:
            agent_ids: List of agent IDs to collect lifecycle states for
            
        Returns:
            Dictionary mapping agent_id to lifecycle state
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        return {
            agent_id: snapshot.lifecycle
            for agent_id, snapshot in agent_snapshots.items()
        }
    
    async def get_agent_statistics(self, agent_ids: List[str]) -> Dict[str, Any]:
        """
        Get comprehensive agent statistics.
        
        Args:
            agent_ids: List of agent IDs to get statistics for
            
        Returns:
            Dictionary containing aggregated agent statistics
        """
        agent_snapshots = await self.collect_agent_snapshots(agent_ids)
        
        if not agent_snapshots:
            return {
                "total_agents": 0,
                "avg_capability": 0.0,
                "avg_memory_util": 0.0,
                "lifecycle_distribution": {},
                "capability_range": (0.0, 0.0),
                "memory_util_range": (0.0, 0.0)
            }
        
        capabilities = [snapshot.c for snapshot in agent_snapshots.values()]
        memory_utils = [snapshot.mem_util for snapshot in agent_snapshots.values()]
        lifecycles = [snapshot.lifecycle for snapshot in agent_snapshots.values()]
        
        # Calculate statistics
        lifecycle_dist = {}
        for lifecycle in lifecycles:
            lifecycle_dist[lifecycle] = lifecycle_dist.get(lifecycle, 0) + 1
        
        return {
            "total_agents": len(agent_snapshots),
            "avg_capability": np.mean(capabilities) if capabilities else 0.0,
            "avg_memory_util": np.mean(memory_utils) if memory_utils else 0.0,
            "lifecycle_distribution": lifecycle_dist,
            "capability_range": (min(capabilities), max(capabilities)) if capabilities else (0.0, 0.0),
            "memory_util_range": (min(memory_utils), max(memory_utils)) if memory_utils else (0.0, 0.0),
            "std_capability": np.std(capabilities) if capabilities else 0.0,
            "std_memory_util": np.std(memory_utils) if memory_utils else 0.0
        }
    
    async def _get_agent_handles(self, agent_ids: List[str]) -> Dict[str, Any]:
        """
        Get Ray actor handles for the specified agents.
        
        Args:
            agent_ids: List of agent IDs to get handles for
            
        Returns:
            Dictionary mapping agent_id to Ray actor handle
        """
        agent_handles = {}
        
        for agent_id in agent_ids:
            # Get agent handle from organism's agent-to-organ mapping
            organ_id = self.organism.agent_to_organ_map.get(agent_id)
            if not organ_id:
                logger.warning(f"Agent {agent_id} not found in organism mapping")
                continue
                
            organ_handle = self.organism.get_organ_handle(organ_id)
            if not organ_handle:
                logger.warning(f"Organ {organ_id} not found for agent {agent_id}")
                continue
            
            try:
                # Get agent handle from organ
                agent_handles_dict = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                agent_handle = agent_handles_dict.get(agent_id)
                if agent_handle:
                    agent_handles[agent_id] = agent_handle
            except Exception as e:
                logger.warning(f"Failed to get agent handle for {agent_id}: {e}")
                continue
        
        return agent_handles
    
    def _build_agent_snapshot(self, agent_id: str, heartbeat: Dict[str, Any]) -> AgentSnapshot:
        """
        Build an AgentSnapshot from a heartbeat.
        
        Args:
            agent_id: Agent ID
            heartbeat: Heartbeat data from Ray actor
            
        Returns:
            AgentSnapshot object
        """
        # Extract state embedding (h vector)
        state_embedding = heartbeat.get('state_embedding_h', [])
        if not state_embedding:
            # Fallback to legacy field
            state_embedding = heartbeat.get('state_embedding', [])
        
        # Convert to numpy array
        h_vector = np.array(state_embedding, dtype=np.float32) if state_embedding else np.zeros(128, dtype=np.float32)
        
        # Extract role probabilities (p vector)
        role_probs = heartbeat.get('role_probs', {})
        
        # Extract capability and memory utilization
        perf_metrics = heartbeat.get('performance_metrics', {})
        capability = float(perf_metrics.get('capability_score_c', 0.0))
        mem_util = float(perf_metrics.get('mem_util', 0.0))
        
        # Extract lifecycle state
        lifecycle = heartbeat.get('lifecycle', {}).get('state', 'Employed')
        
        return AgentSnapshot(
            h=h_vector,
            p=role_probs,
            c=capability,
            mem_util=mem_util,
            lifecycle=str(lifecycle)
        )
    
    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if cache entry is valid."""
        if cache_key not in self._cache:
            return False
        return (time.time() - self._last_update) < self.cache_ttl
    
    async def _async_ray_get(self, refs) -> Any:
        """
        Safely resolve Ray references with proper error handling.
        
        Args:
            refs: Ray ObjectRef or list of ObjectRefs
            
        Returns:
            Resolved result(s)
        """
        try:
            if isinstance(refs, list):
                return await asyncio.gather(*[self._async_ray_get(ref) for ref in refs])
            else:
                # Single reference
                if hasattr(refs, 'result'):
                    # DeploymentResponse
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: refs.result(timeout_s=15.0)
                    )
                else:
                    # ObjectRef
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ray.get(refs, timeout=15.0)
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve Ray reference: {e}")
            raise



