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
SystemStateAggregator - Lightweight aggregator for system-level state collection

Efficiently collects and aggregates system-level state:
- h_hgnn: System-level embeddings from organism state
- E patterns: Real-time escalation patterns from HGNNPatternShim
- w_mode: Mode weights from system configuration

Implements Paper §3.1 requirements for light aggregators from system state.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
import numpy as np

from ...energy.state import SystemState
from ...hgnn.pattern_shim import HGNNPatternShim

logger = logging.getLogger(__name__)


class SystemStateAggregator:
    """
    Lightweight aggregator for collecting system-level state.
    
    Features:
    - Real-time E_patterns collection from HGNNPatternShim
    - System-level embedding computation
    - Mode weight collection from system configuration
    - Smart caching to reduce overhead
    """
    
    def __init__(self, organism_manager, cache_ttl: float = 5.0):
        """
        Initialize the system state aggregator.
        
        Args:
            organism_manager: Reference to the OrganismManager instance
            cache_ttl: Cache time-to-live in seconds
        """
        self.organism = organism_manager
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._last_update = 0.0
        
        # Initialize HGNN pattern shim for E_patterns
        self.pattern_shim = HGNNPatternShim()
        
        logger.info("✅ SystemStateAggregator initialized")
    
    async def collect_system_state(self) -> SystemState:
        """
        Collect complete system state.
        
        Returns:
            SystemState containing system-level information
        """
        # Check cache first
        cache_key = "system_state"
        if self._is_cache_valid(cache_key):
            logger.debug("Using cached system state")
            return self._cache[cache_key]
        
        try:
            # Collect all system components in parallel
            h_hgnn, E_patterns, w_mode = await asyncio.gather(
                self.collect_h_hgnn(),
                self.collect_E_patterns(),
                self.collect_w_mode(),
                return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(h_hgnn, Exception):
                logger.error(f"Failed to collect h_hgnn: {h_hgnn}")
                h_hgnn = np.zeros(128, dtype=np.float32)
            
            if isinstance(E_patterns, Exception):
                logger.error(f"Failed to collect E_patterns: {E_patterns}")
                E_patterns = np.array([])
            
            if isinstance(w_mode, Exception):
                logger.error(f"Failed to collect w_mode: {w_mode}")
                w_mode = np.zeros(3, dtype=np.float32)
            
            system_state = SystemState(
                h_hgnn=h_hgnn,
                E_patterns=E_patterns,
                w_mode=w_mode
            )
            
            # Cache the results
            self._cache[cache_key] = system_state
            self._last_update = time.time()
            
            logger.debug(f"System state collected: E_patterns shape={E_patterns.shape if E_patterns is not None else 'None'}")
            return system_state
            
        except Exception as e:
            logger.error(f"Failed to collect system state: {e}")
            return SystemState()
    
    async def collect_h_hgnn(self) -> np.ndarray:
        """
        Collect system-level embeddings (h_hgnn).
        
        Returns:
            System-level embedding vector
        """
        try:
            # Get all agent embeddings and compute system-level representation
            agent_ids = list(self.organism.agent_to_organ_map.keys())
            if not agent_ids:
                return np.zeros(128, dtype=np.float32)
            
            # Sample agents for performance
            sample_size = min(20, len(agent_ids))
            sample_agents = agent_ids[:sample_size]
            
            agent_embeddings = []
            for agent_id in sample_agents:
                try:
                    # Get agent handle
                    organ_id = self.organism.agent_to_organ_map.get(agent_id)
                    if not organ_id:
                        continue
                    
                    organ_handle = self.organism.get_organ_handle(organ_id)
                    if not organ_handle:
                        continue
                    
                    agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                    agent_handle = agent_handles.get(agent_id)
                    if not agent_handle:
                        continue
                    
                    # Get agent embedding
                    heartbeat = await self._async_ray_get(agent_handle.get_heartbeat.remote())
                    state_embedding = heartbeat.get('state_embedding_h', heartbeat.get('state_embedding', []))
                    
                    if state_embedding:
                        agent_embeddings.append(np.array(state_embedding, dtype=np.float32))
                    
                except Exception as e:
                    logger.warning(f"Failed to get embedding for agent {agent_id}: {e}")
                    continue
            
            if not agent_embeddings:
                return np.zeros(128, dtype=np.float32)
            
            # Compute system-level embedding as weighted average
            # Weight by agent capability and memory utilization
            weights = []
            for agent_id in sample_agents[:len(agent_embeddings)]:
                try:
                    organ_id = self.organism.agent_to_organ_map.get(agent_id)
                    if not organ_id:
                        weights.append(1.0)
                        continue
                    
                    organ_handle = self.organism.get_organ_handle(organ_id)
                    if not organ_handle:
                        weights.append(1.0)
                        continue
                    
                    agent_handles = await self._async_ray_get(organ_handle.get_agent_handles.remote())
                    agent_handle = agent_handles.get(agent_id)
                    if not agent_handle:
                        weights.append(1.0)
                        continue
                    
                    heartbeat = await self._async_ray_get(agent_handle.get_heartbeat.remote())
                    perf_metrics = heartbeat.get('performance_metrics', {})
                    capability = float(perf_metrics.get('capability_score_c', 0.5))
                    mem_util = float(perf_metrics.get('mem_util', 0.0))
                    
                    # Weight by capability and memory utilization
                    weight = capability * (1.0 + mem_util)
                    weights.append(weight)
                    
                except Exception as e:
                    logger.warning(f"Failed to get weight for agent {agent_id}: {e}")
                    weights.append(1.0)
            
            # Normalize weights
            weights = np.array(weights, dtype=np.float32)
            if np.sum(weights) > 0:
                weights = weights / np.sum(weights)
            else:
                weights = np.ones(len(agent_embeddings), dtype=np.float32) / len(agent_embeddings)
            
            # Compute weighted average
            h_hgnn = np.average(agent_embeddings, axis=0, weights=weights)
            
            logger.debug(f"h_hgnn computed from {len(agent_embeddings)} agent embeddings")
            return h_hgnn
            
        except Exception as e:
            logger.error(f"Failed to collect h_hgnn: {e}")
            return np.zeros(128, dtype=np.float32)
    
    async def collect_E_patterns(self) -> np.ndarray:
        """
        Collect E patterns from HGNNPatternShim.
        
        Returns:
            E patterns array
        """
        try:
            E_vec, E_map = self.pattern_shim.get_E_patterns()
            logger.debug(f"E_patterns collected: shape={E_vec.shape if E_vec is not None else 'None'}")
            return E_vec if E_vec is not None else np.array([])
            
        except Exception as e:
            logger.error(f"Failed to collect E_patterns: {e}")
            return np.array([])
    
    async def collect_w_mode(self) -> np.ndarray:
        """
        Collect mode weights from system configuration.
        
        Returns:
            Mode weights array
        """
        try:
            # TODO: Implement proper mode weight collection from system configuration
            # For now, return a simple default based on organ distribution
            organ_count = len(self.organism.organs)
            if organ_count == 0:
                return np.zeros(3, dtype=np.float32)
            
            # Simple mode weights based on organ types
            # This is a placeholder - should be replaced with actual system configuration
            w_mode = np.array([0.4, 0.3, 0.3], dtype=np.float32)  # [E, S, O] roles
            
            logger.debug(f"w_mode collected: {w_mode}")
            return w_mode
            
        except Exception as e:
            logger.error(f"Failed to collect w_mode: {e}")
            return np.zeros(3, dtype=np.float32)
    
    async def get_system_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive system statistics.
        
        Returns:
            Dictionary containing system statistics
        """
        try:
            system_state = await self.collect_system_state()
            
            return {
                "h_hgnn_available": system_state.h_hgnn is not None,
                "h_hgnn_norm": float(np.linalg.norm(system_state.h_hgnn)) if system_state.h_hgnn is not None else 0.0,
                "E_patterns_available": system_state.E_patterns is not None,
                "E_patterns_shape": system_state.E_patterns.shape if system_state.E_patterns is not None else None,
                "E_patterns_count": len(system_state.E_patterns) if system_state.E_patterns is not None else 0,
                "w_mode_available": system_state.w_mode is not None,
                "w_mode_values": system_state.w_mode.tolist() if system_state.w_mode is not None else None,
                "organism_initialized": self.organism._initialized,
                "organ_count": len(self.organism.organs),
                "agent_count": len(self.organism.agent_to_organ_map),
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Failed to get system statistics: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
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
                    import ray
                    return await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ray.get(refs, timeout=15.0)
                    )
        except Exception as e:
            logger.warning(f"Failed to resolve Ray reference: {e}")
            raise



