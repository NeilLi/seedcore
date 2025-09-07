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
StateAggregator - Lightweight state aggregator for UnifiedState construction

This module implements efficient state collection from distributed Ray actors
and memory managers, providing a unified view of the system state for energy
calculations and monitoring.

Implements Paper §3.1 requirements for light aggregators from live Ray actors
and memory managers (H, P, h_hgnn, E, w_m, and [ma,mw,mlt,mfb]).
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import ray

from ..energy.state import (
    UnifiedState, 
    AgentSnapshot, 
    OrganState, 
    SystemState, 
    MemoryVector
)
from .aggregators import (
    AgentStateAggregator,
    MemoryManagerAggregator,
    SystemStateAggregator
)

logger = logging.getLogger(__name__)


class StateAggregator:
    """
    Lightweight state aggregator for UnifiedState construction.
    
    Efficiently collects state from distributed Ray actors and memory managers,
    implementing the light aggregator pattern described in Paper §3.1.
    
    Features:
    - Batch Ray calls for efficiency
    - Smart caching to reduce overhead
    - Error handling and graceful degradation
    - Support for all memory tiers (ma, mw, mlt, mfb)
    - Real-time E_patterns collection
    """
    
    def __init__(self, organism_manager, cache_ttl: float = 5.0):
        """
        Initialize the state aggregator.
        
        Args:
            organism_manager: Reference to the OrganismManager instance
            cache_ttl: Cache time-to-live in seconds
        """
        self.organism = organism_manager
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._last_update = 0.0
        
        # Initialize specialized aggregators
        self.agent_aggregator = AgentStateAggregator(organism_manager, cache_ttl)
        self.memory_aggregator = MemoryManagerAggregator(organism_manager, cache_ttl)
        self.system_aggregator = SystemStateAggregator(organism_manager, cache_ttl)
        
        logger.info("✅ StateAggregator initialized with specialized aggregators")
    
    async def get_agent_snapshots(self, agent_ids: List[str]) -> Dict[str, AgentSnapshot]:
        """
        Efficiently collect agent state from Ray actors.
        
        Delegates to AgentStateAggregator for efficient collection.
        
        Args:
            agent_ids: List of agent IDs to collect state for
            
        Returns:
            Dictionary mapping agent_id to AgentSnapshot
        """
        return await self.agent_aggregator.collect_agent_snapshots(agent_ids)
    
    async def get_organ_states(self) -> Dict[str, OrganState]:
        """
        Collect organ-level state information.
        
        Returns:
            Dictionary mapping organ_id to OrganState
        """
        organ_states = {}
        
        for organ_id, organ_handle in self.organism.organs.items():
            try:
                # Get organ status
                status = await self._async_ray_get(organ_handle.get_status.remote())
                
                # Get agent handles for this organ
                agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                
                if not agent_handles:
                    # Empty organ
                    organ_states[organ_id] = OrganState(
                        h=np.zeros(128, dtype=np.float32),
                        P=np.zeros((0, 3), dtype=np.float32)
                    )
                    continue
                
                # Collect agent states for this organ
                agent_heartbeats = []
                for agent_handle in agent_handles.values():
                    try:
                        hb = await self._async_ray_get(agent_handle.get_heartbeat.remote())
                        agent_heartbeats.append(hb)
                    except Exception as e:
                        logger.warning(f"Failed to get heartbeat from agent in organ {organ_id}: {e}")
                        continue
                
                if not agent_heartbeats:
                    organ_states[organ_id] = OrganState(
                        h=np.zeros(128, dtype=np.float32),
                        P=np.zeros((0, 3), dtype=np.float32)
                    )
                    continue
                
                # Compute organ-level state
                # H matrix: stack all agent embeddings
                h_vectors = []
                p_vectors = []
                
                for hb in agent_heartbeats:
                    state_embedding = hb.get('state_embedding_h', hb.get('state_embedding', []))
                    if state_embedding:
                        h_vectors.append(np.array(state_embedding, dtype=np.float32))
                    
                    role_probs = hb.get('role_probs', {})
                    p_vector = [
                        float(role_probs.get('E', 0.0)),
                        float(role_probs.get('S', 0.0)),
                        float(role_probs.get('O', 0.0))
                    ]
                    p_vectors.append(p_vector)
                
                if h_vectors:
                    h_matrix = np.vstack(h_vectors)
                    h_organ = np.mean(h_matrix, axis=0)  # Average agent embedding
                else:
                    h_organ = np.zeros(128, dtype=np.float32)
                
                if p_vectors:
                    P_matrix = np.array(p_vectors, dtype=np.float32)
                else:
                    P_matrix = np.zeros((0, 3), dtype=np.float32)
                
                organ_states[organ_id] = OrganState(
                    h=h_organ,
                    P=P_matrix
                )
                
            except Exception as e:
                logger.warning(f"Failed to collect state for organ {organ_id}: {e}")
                continue
        
        logger.debug(f"Successfully collected {len(organ_states)} organ states")
        return organ_states
    
    async def get_system_state(self) -> SystemState:
        """
        Collect system-level state including E_patterns and h_hgnn.
        
        Delegates to SystemStateAggregator for efficient collection.
        
        Returns:
            SystemState containing system-level information
        """
        return await self.system_aggregator.collect_system_state()
    
    async def get_memory_stats(self) -> MemoryVector:
        """
        Collect memory manager statistics from all memory tiers.
        
        Delegates to MemoryManagerAggregator for efficient collection.
        
        Returns:
            MemoryVector containing aggregated memory statistics
        """
        return await self.memory_aggregator.collect_memory_vector()
    
    # ============================================================================
    # Convenience methods for accessing specialized aggregator functionality
    # ============================================================================
    
    async def get_h_vectors(self, agent_ids: List[str]) -> Dict[str, np.ndarray]:
        """Get h vectors from agents."""
        return await self.agent_aggregator.collect_h_vectors(agent_ids)
    
    async def get_p_matrix(self, agent_ids: List[str]) -> np.ndarray:
        """Get P matrix from agent role probabilities."""
        return await self.agent_aggregator.collect_p_matrix(agent_ids)
    
    async def get_capability_scores(self, agent_ids: List[str]) -> Dict[str, float]:
        """Get capability scores from agents."""
        return await self.agent_aggregator.collect_capability_scores(agent_ids)
    
    async def get_memory_utilization(self, agent_ids: List[str]) -> Dict[str, float]:
        """Get memory utilization from agents."""
        return await self.agent_aggregator.collect_memory_utilization(agent_ids)
    
    async def get_lifecycle_states(self, agent_ids: List[str]) -> Dict[str, str]:
        """Get lifecycle states from agents."""
        return await self.agent_aggregator.collect_lifecycle_states(agent_ids)
    
    async def get_agent_statistics(self, agent_ids: List[str]) -> Dict[str, Any]:
        """Get comprehensive agent statistics."""
        return await self.agent_aggregator.get_agent_statistics(agent_ids)
    
    async def get_memory_statistics(self) -> Dict[str, Any]:
        """Get comprehensive memory statistics."""
        memory_vector = await self.memory_aggregator.collect_memory_vector()
        return {
            "ma": memory_vector.ma,
            "mw": memory_vector.mw,
            "mlt": memory_vector.mlt,
            "mfb": memory_vector.mfb,
            "timestamp": time.time()
        }
    
    async def get_system_statistics(self) -> Dict[str, Any]:
        """Get comprehensive system statistics."""
        return await self.system_aggregator.get_system_statistics()
    
    async def build_unified_state(self, agent_ids: Optional[List[str]] = None) -> UnifiedState:
        """
        Main entry point for unified state construction.
        
        Orchestrates collection from all aggregators to build a complete
        UnifiedState object for energy calculations and monitoring.
        
        Args:
            agent_ids: List of agent IDs to include, or None for all agents
            
        Returns:
            Complete UnifiedState object
        """
        if agent_ids is None:
            agent_ids = list(self.organism.agent_to_organ_map.keys())
        
        logger.info(f"Building unified state for {len(agent_ids)} agents")
        
        try:
            # Collect all state components in parallel for efficiency
            agent_snapshots_task = self.get_agent_snapshots(agent_ids)
            organ_states_task = self.get_organ_states()
            system_state_task = self.get_system_state()
            memory_stats_task = self.get_memory_stats()
            
            # Wait for all tasks to complete
            agent_snapshots, organ_states, system_state, memory_stats = await asyncio.gather(
                agent_snapshots_task,
                organ_states_task,
                system_state_task,
                memory_stats_task,
                return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(agent_snapshots, Exception):
                logger.error(f"Failed to collect agent snapshots: {agent_snapshots}")
                agent_snapshots = {}
            
            if isinstance(organ_states, Exception):
                logger.error(f"Failed to collect organ states: {organ_states}")
                organ_states = {}
            
            if isinstance(system_state, Exception):
                logger.error(f"Failed to collect system state: {system_state}")
                system_state = SystemState()
            
            if isinstance(memory_stats, Exception):
                logger.error(f"Failed to collect memory stats: {memory_stats}")
                memory_stats = MemoryVector(ma={}, mw={}, mlt={}, mfb={})
            
            # Build unified state
            unified_state = UnifiedState(
                agents=agent_snapshots,
                organs=organ_states,
                system=system_state,
                memory=memory_stats
            )
            
            logger.info(f"✅ Unified state built: {len(agent_snapshots)} agents, {len(organ_states)} organs")
            return unified_state
            
        except Exception as e:
            logger.error(f"Failed to build unified state: {e}")
            # Return empty state on failure
            return UnifiedState(
                agents={},
                organs={},
                system=SystemState(),
                memory=MemoryVector(ma={}, mw={}, mlt={}, mfb={})
            )
    
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
