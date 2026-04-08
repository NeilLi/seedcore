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

"""Memory subsystem: bounded working, semantic, and optional incident services.

Memory is advisory for cognition/tools unless promoted into typed,
freshness-aware context elsewhere. It is not an authority source for governed
PDP decisions.

Prefer :class:`MemoryRuntime` and the service protocols in :mod:`contracts`.
"""

from __future__ import annotations

import warnings
from typing import Any

from .contracts import (
    HolonRelation,
    IncidentMemory,
    IncidentMemoryStats,
    MemoryHealth,
    MemorySubsystemStatus,
    SemanticMemory,
    SemanticMemoryStats,
    SemanticSearchQuery,
    SemanticSearchResult,
    WorkingMemory,
    WorkingMemoryStats,
)
from .holon_fabric import Embedder, HolonFabric
from .incident_memory import IncidentMemoryService, InMemoryIncidentBackend
from .mw_manager import MwManager
from .runtime import MemoryRuntime, connect_default_memory_runtime
from .semantic_memory import SemanticMemoryService
from .working_memory import MwWorkingMemoryAdapter

_OPTIONAL_LEGACY_SHARD_EXPORTS = frozenset(
    {"SharedCacheShard", "MwStoreShard", "FlashbulbClient"}
)

_LEGACY_EXPORTS = frozenset(
    {
        "SharedMemorySystem",
        "MemoryTier",
        "calculate_dynamic_mem_util",
        "calculate_cost_vq",
        "adaptive_mem_update",
        "get_memory_metrics",
        "estimate_memory_gradient",
    }
)


def __getattr__(name: str) -> Any:
    if name in _OPTIONAL_LEGACY_SHARD_EXPORTS:
        warnings.warn(
            f"Importing {name} from seedcore.memory is deprecated; "
            f"import from the defining submodule under seedcore.memory instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if name == "SharedCacheShard":
            from .shared_cache_shard import SharedCacheShard as _x

            return _x
        if name == "MwStoreShard":
            from .mw_store_shard import MwStoreShard as _x

            return _x
        if name == "FlashbulbClient":
            from .flashbulb_client import FlashbulbClient as _x

            return _x
    if name in _LEGACY_EXPORTS:
        from . import legacy as _legacy

        warnings.warn(
            f"Importing {name} from seedcore.memory is deprecated; "
            f"use seedcore.memory.legacy (or update callers).",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(_legacy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "contracts",
    "Embedder",
    "HolonFabric",
    "HolonRelation",
    "MwManager",
    "MwWorkingMemoryAdapter",
    "MemoryRuntime",
    "connect_default_memory_runtime",
    "SemanticMemoryService",
    "SemanticMemory",
    "SemanticSearchQuery",
    "SemanticSearchResult",
    "SemanticMemoryStats",
    "IncidentMemory",
    "IncidentMemoryService",
    "InMemoryIncidentBackend",
    "IncidentMemoryStats",
    "WorkingMemory",
    "WorkingMemoryStats",
    "MemoryHealth",
    "MemorySubsystemStatus",
]
