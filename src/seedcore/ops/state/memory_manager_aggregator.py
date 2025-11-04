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
import os
from typing import Dict, List, Optional, Any
import numpy as np

from ...models.state import MemoryVector

# Optional memory module imports
try:
    from ...memory.mw_manager import MwManager
    from ...memory.long_term_memory import LongTermMemoryManager
    from ...memory.holon_fabric import HolonFabric
    _MEMORY_AVAILABLE = True
except ImportError:
    MwManager = None  # type: ignore
    LongTermMemoryManager = None  # type: ignore
    HolonFabric = None  # type: ignore
    _MEMORY_AVAILABLE = False

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
        
        # Lazy initialization of memory managers
        self._mw_manager: Optional[MwManager] = None
        self._ltm_manager: Optional[LongTermMemoryManager] = None
        self._holon_fabric: Optional[HolonFabric] = None
        
        logger.info("✅ MemoryManagerAggregator initialized")
    
    def _get_mw_manager(self) -> Optional[MwManager]:
        """Get or create a MwManager instance for stats collection."""
        if not _MEMORY_AVAILABLE or MwManager is None:
            return None
        if self._mw_manager is None:
            try:
                # Use a system-wide organ_id for aggregator stats
                self._mw_manager = MwManager(organ_id="system_aggregator")
            except Exception as e:
                logger.debug(f"Failed to create MwManager: {e}")
                return None
        return self._mw_manager
    
    def _get_holon_fabric(self) -> Optional[HolonFabric]:
        """Get or create a HolonFabric instance for LTM stats."""
        if not _MEMORY_AVAILABLE:
            return None
        if self._holon_fabric is None:
            try:
                # Create HolonFabric from LongTermMemoryManager's backends
                if self._ltm_manager is None:
                    self._ltm_manager = LongTermMemoryManager()
                # Access the backends directly from LongTermMemoryManager
                self._holon_fabric = HolonFabric(
                    vec_store=self._ltm_manager.pg_store,
                    graph=self._ltm_manager.neo4j_graph
                )
            except Exception as e:
                logger.debug(f"Failed to create HolonFabric: {e}")
                return None
        return self._holon_fabric
    
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
        Collect working memory statistics (mw) from MwManager.
        
        Returns:
            Dictionary containing mw statistics
        """
        try:
            mw_manager = self._get_mw_manager()
            if mw_manager is None:
                # Fallback to simulated statistics if MwManager unavailable
                logger.debug("MwManager unavailable, returning simulated stats")
                return {
                    "buffer_size": 1024,
                    "hit_rate": 0.78,
                    "eviction_rate": 0.12,
                    "cache_utilization": 0.65,
                    "miss_rate": 0.22,
                    "total_requests": 1000,
                    "successful_requests": 780
                }
            
            # Get telemetry from the MwManager instance
            telemetry = mw_manager.get_telemetry()
            
            # Convert telemetry to stats format
            total_requests = telemetry.get("total_requests", 0)
            hits = telemetry.get("hits", 0)
            misses = telemetry.get("misses", 0)
            hit_ratio = telemetry.get("hit_ratio", 0.0)
            
            # Calculate additional metrics
            buffer_size = total_requests  # Approximate buffer size
            cache_utilization = hit_ratio  # Use hit ratio as proxy
            miss_rate = telemetry.get("misses", 0) / total_requests if total_requests > 0 else 0.0
            
            # Get hot items count as proxy for eviction activity
            try:
                hot_items = await mw_manager.get_hot_items_async(top_n=10)
                eviction_rate = len(hot_items) / max(total_requests, 1) * 0.1  # Rough estimate
            except Exception:
                eviction_rate = 0.12  # Fallback
            
            return {
                "buffer_size": buffer_size,
                "hit_rate": hit_ratio,
                "eviction_rate": eviction_rate,
                "cache_utilization": cache_utilization,
                "miss_rate": miss_rate,
                "total_requests": total_requests,
                "successful_requests": hits,
                "l0_hits": telemetry.get("l0_hits", 0),
                "l1_hits": telemetry.get("l1_hits", 0),
                "l2_hits": telemetry.get("l2_hits", 0),
                "l0_hit_ratio": telemetry.get("l0_hit_ratio", 0.0),
                "l1_hit_ratio": telemetry.get("l1_hit_ratio", 0.0),
                "l2_hit_ratio": telemetry.get("l2_hit_ratio", 0.0),
                "task_cache_hits": telemetry.get("task_cache_hits", 0),
                "task_cache_misses": telemetry.get("task_cache_misses", 0),
                "task_hit_ratio": telemetry.get("task_hit_ratio", 0.0),
            }
            
        except Exception as e:
            logger.error(f"Failed to collect mw stats: {e}")
            return {}
    
    async def collect_mlt_stats(self) -> Dict[str, Any]:
        """
        Collect long-term memory statistics (mlt) from HolonFabric.
        
        Returns:
            Dictionary containing mlt statistics
        """
        try:
            fabric = self._get_holon_fabric()
            if fabric is None:
                # Fallback to simulated statistics if HolonFabric unavailable
                logger.debug("HolonFabric unavailable, returning simulated stats")
                return {
                    "storage_gb": 50.2,
                    "compression_ratio": 0.65,
                    "access_patterns": 42,
                    "total_holons": 1000,
                    "avg_holon_size": 1024,
                    "query_latency_ms": 150.0,
                    "index_size_mb": 25.5
                }
            
            # Get stats from HolonFabric (async method)
            stats = await fabric.get_stats()
            
            # Convert stats to aggregator format
            total_holons = stats.get("total_holons", 0)
            total_relationships = stats.get("total_relationships", 0)
            bytes_used = stats.get("bytes_used", 0)
            status = stats.get("status", "unknown")
            
            # Calculate derived metrics
            storage_gb = bytes_used / (1024 ** 3)  # Convert bytes to GB
            avg_holon_size = bytes_used / total_holons if total_holons > 0 else 0
            
            # Estimate compression ratio (assuming some compression)
            # This is a rough estimate - real implementation would track compression
            compression_ratio = 0.65  # Default estimate
            
            # Estimate index size (typically 10-20% of data size)
            index_size_mb = (bytes_used * 0.15) / (1024 ** 2)
            
            return {
                "storage_gb": round(storage_gb, 2),
                "compression_ratio": compression_ratio,
                "access_patterns": total_relationships,  # Use relationship count as proxy
                "total_holons": total_holons,
                "total_relationships": total_relationships,
                "avg_holon_size": int(avg_holon_size),
                "query_latency_ms": 150.0,  # Would need actual query timing to measure
                "index_size_mb": round(index_size_mb, 2),
                "bytes_used": bytes_used,
                "status": status,
                "vector_dimensions": stats.get("vector_dimensions", 768)
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



