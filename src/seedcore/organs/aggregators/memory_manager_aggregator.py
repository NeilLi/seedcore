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
MemoryManagerAggregator - Lightweight aggregator for memory manager statistics

Efficiently collects and aggregates statistics from all memory managers:
- ma: Per-agent memory statistics from RayAgent instances
- mw: Working memory stats from MwManager instances
- mlt: Long-term memory metrics from LongTermMemoryManager
- mfb: Flashbulb memory stats from FlashbulbClient usage

Implements Paper §3.1 requirements for light aggregators from memory managers.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
import numpy as np

from ...energy.state import MemoryVector

logger = logging.getLogger(__name__)


class MemoryManagerAggregator:
    """
    Lightweight aggregator for collecting memory manager statistics.
    
    Features:
    - Efficient collection from all memory tiers
    - Smart caching to reduce overhead
    - Error handling and graceful degradation
    - Support for all memory managers (ma, mw, mlt, mfb)
    """
    
    def __init__(self, organism_manager, cache_ttl: float = 5.0):
        """
        Initialize the memory manager aggregator.
        
        Args:
            organism_manager: Reference to the OrganismManager instance
            cache_ttl: Cache time-to-live in seconds
        """
        self.organism = organism_manager
        self.cache_ttl = cache_ttl
        self._cache = {}
        self._last_update = 0.0
        
        logger.info("✅ MemoryManagerAggregator initialized")
    
    async def collect_memory_vector(self) -> MemoryVector:
        """
        Collect complete memory vector from all memory managers.
        
        Returns:
            MemoryVector containing aggregated memory statistics
        """
        # Check cache first
        cache_key = "memory_vector"
        if self._is_cache_valid(cache_key):
            logger.debug("Using cached memory vector")
            return self._cache[cache_key]
        
        try:
            # Collect from all memory tiers in parallel
            ma_stats, mw_stats, mlt_stats, mfb_stats = await asyncio.gather(
                self.collect_ma_stats(),
                self.collect_mw_stats(),
                self.collect_mlt_stats(),
                self.collect_mfb_stats(),
                return_exceptions=True
            )
            
            # Handle any exceptions
            if isinstance(ma_stats, Exception):
                logger.error(f"Failed to collect ma stats: {ma_stats}")
                ma_stats = {"count": 0, "error": str(ma_stats)}
            
            if isinstance(mw_stats, Exception):
                logger.error(f"Failed to collect mw stats: {mw_stats}")
                mw_stats = {}
            
            if isinstance(mlt_stats, Exception):
                logger.error(f"Failed to collect mlt stats: {mlt_stats}")
                mlt_stats = {}
            
            if isinstance(mfb_stats, Exception):
                logger.error(f"Failed to collect mfb stats: {mfb_stats}")
                mfb_stats = {}
            
            memory_vector = MemoryVector(
                ma=ma_stats,
                mw=mw_stats,
                mlt=mlt_stats,
                mfb=mfb_stats
            )
            
            # Cache the results
            self._cache[cache_key] = memory_vector
            self._last_update = time.time()
            
            logger.debug("Memory vector collected successfully")
            return memory_vector
            
        except Exception as e:
            logger.error(f"Failed to collect memory vector: {e}")
            return MemoryVector(ma={}, mw={}, mlt={}, mfb={})
    
    async def collect_ma_stats(self) -> Dict[str, Any]:
        """
        Collect per-agent memory statistics (ma).
        
        Returns:
            Dictionary containing ma statistics
        """
        try:
            # Get agent count and basic statistics
            agent_count = len(self.organism.agent_to_organ_map)
            
            if agent_count == 0:
                return {
                    "count": 0,
                    "avg_capability": 0.0,
                    "avg_mem_util": 0.0,
                    "total_memory_writes": 0,
                    "total_memory_hits": 0
                }
            
            # Collect detailed agent statistics
            agent_stats = await self._collect_agent_memory_stats()
            
            return {
                "count": agent_count,
                "avg_capability": agent_stats.get("avg_capability", 0.0),
                "avg_mem_util": agent_stats.get("avg_mem_util", 0.0),
                "total_memory_writes": agent_stats.get("total_memory_writes", 0),
                "total_memory_hits": agent_stats.get("total_memory_hits", 0),
                "memory_efficiency": agent_stats.get("memory_efficiency", 0.0),
                "active_agents": agent_stats.get("active_agents", 0)
            }
            
        except Exception as e:
            logger.error(f"Failed to collect ma stats: {e}")
            return {"count": 0, "error": str(e)}
    
    async def collect_mw_stats(self) -> Dict[str, Any]:
        """
        Collect working memory statistics (mw).
        
        Returns:
            Dictionary containing mw statistics
        """
        try:
            # TODO: Integrate with actual MwManager instances
            # For now, return simulated statistics
            return {
                "buffer_size": 1024,
                "hit_rate": 0.78,
                "eviction_rate": 0.12,
                "cache_utilization": 0.65,
                "miss_rate": 0.22,
                "total_requests": 1000,
                "successful_requests": 780
            }
            
        except Exception as e:
            logger.error(f"Failed to collect mw stats: {e}")
            return {}
    
    async def collect_mlt_stats(self) -> Dict[str, Any]:
        """
        Collect long-term memory statistics (mlt).
        
        Returns:
            Dictionary containing mlt statistics
        """
        try:
            # TODO: Integrate with actual LongTermMemoryManager instances
            # For now, return simulated statistics
            return {
                "storage_gb": 50.2,
                "compression_ratio": 0.65,
                "access_patterns": 42,
                "total_holons": 1000,
                "avg_holon_size": 1024,
                "query_latency_ms": 150.0,
                "index_size_mb": 25.5
            }
            
        except Exception as e:
            logger.error(f"Failed to collect mlt stats: {e}")
            return {}
    
    async def collect_mfb_stats(self) -> Dict[str, Any]:
        """
        Collect flashbulb memory statistics (mfb).
        
        Returns:
            Dictionary containing mfb statistics
        """
        try:
            # TODO: Integrate with actual FlashbulbClient instances
            # For now, return simulated statistics
            return {
                "incidents": 0,
                "queue_size": 128,
                "avg_weight": 0.73,
                "decay_rate": 0.15,
                "total_events": 500,
                "processed_events": 450,
                "pending_events": 50
            }
            
        except Exception as e:
            logger.error(f"Failed to collect mfb stats: {e}")
            return {}
    
    async def _collect_agent_memory_stats(self) -> Dict[str, Any]:
        """
        Collect detailed memory statistics from agents.
        
        Returns:
            Dictionary containing aggregated agent memory statistics
        """
        try:
            agent_ids = list(self.organism.agent_to_organ_map.keys())
            if not agent_ids:
                return {}
            
            # Sample a subset of agents for performance
            sample_size = min(10, len(agent_ids))
            sample_agents = agent_ids[:sample_size]
            
            total_memory_writes = 0
            total_memory_hits = 0
            total_capability = 0.0
            total_mem_util = 0.0
            active_agents = 0
            
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
                    
                    # Get agent heartbeat
                    heartbeat = await self._async_ray_get(agent_handle.get_heartbeat.remote())
                    
                    # Extract memory statistics
                    total_memory_writes += heartbeat.get('memory_writes', 0)
                    total_memory_hits += heartbeat.get('memory_hits_on_writes', 0)
                    
                    # Extract performance metrics
                    perf_metrics = heartbeat.get('performance_metrics', {})
                    capability = float(perf_metrics.get('capability_score_c', 0.0))
                    mem_util = float(perf_metrics.get('mem_util', 0.0))
                    
                    total_capability += capability
                    total_mem_util += mem_util
                    
                    # Check if agent is active
                    last_heartbeat = heartbeat.get('last_heartbeat', 0)
                    if last_heartbeat > time.time() - 300:  # Active in last 5 minutes
                        active_agents += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to get memory stats for agent {agent_id}: {e}")
                    continue
            
            # Calculate averages
            avg_capability = total_capability / sample_size if sample_size > 0 else 0.0
            avg_mem_util = total_mem_util / sample_size if sample_size > 0 else 0.0
            
            # Calculate memory efficiency
            memory_efficiency = 0.0
            if total_memory_writes > 0:
                memory_efficiency = total_memory_hits / total_memory_writes
            
            return {
                "avg_capability": avg_capability,
                "avg_mem_util": avg_mem_util,
                "total_memory_writes": total_memory_writes,
                "total_memory_hits": total_memory_hits,
                "memory_efficiency": memory_efficiency,
                "active_agents": active_agents
            }
            
        except Exception as e:
            logger.error(f"Failed to collect agent memory stats: {e}")
            return {}
    
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

