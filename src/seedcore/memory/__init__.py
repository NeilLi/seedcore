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

"""Memory subpackage.

This package provides the memory system for SeedCore, including:
- Working memory (Mw) via MwManager
- Long-term memory via HolonFabric (unified vector + graph storage)
- HolonClient for persisting cognitive facts to HolonFabric
- Adaptive memory control loops
- Memory consolidation utilities
"""

# Core memory classes
from .holon_fabric import HolonFabric, Embedder
from .holon_client import HolonClient
from .mw_manager import MwManager
from .system import SharedMemorySystem, MemoryTier

# Adaptive memory loop functions
from .adaptive_loop import (
    calculate_dynamic_mem_util,
    adaptive_mem_update,
    get_memory_metrics,
    estimate_memory_gradient,
)

# CostVQ calculation - export the new async version from cost_vq.py
# Note: adaptive_loop.py also has a legacy sync version for backward compatibility
from .cost_vq import calculate_cost_vq

# Backend classes (commonly used)
from .backends.pgvector_backend import PgVectorStore, Holon
from .backends.neo4j_graph import Neo4jGraph

# Shard classes (for distributed caching)
try:
    from .shared_cache_shard import SharedCacheShard
except ImportError:
    SharedCacheShard = None  # type: ignore

try:
    from .mw_store_shard import MwStoreShard
except ImportError:
    MwStoreShard = None  # type: ignore

# Consolidation functions (if available)
try:
    from .flashbulb_client import FlashbulbClient
except ImportError:
    FlashbulbClient = None  # type: ignore

__all__ = [
    # Core classes
    "HolonFabric",
    "HolonClient",
    "Embedder",
    "MwManager",
    "SharedMemorySystem",
    "MemoryTier",
    # Adaptive loop functions
    "calculate_dynamic_mem_util",
    "calculate_cost_vq",
    "adaptive_mem_update",
    "get_memory_metrics",
    "estimate_memory_gradient",
    # Backend classes
    "PgVectorStore",
    "Holon",
    "Neo4jGraph",
    # Shard classes
    "SharedCacheShard",
    "MwStoreShard",
    # FlashbulbClient
    "FlashbulbClient"
]
