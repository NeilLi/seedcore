# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""Contract-shaped memory telemetry dicts (shared by OrganismCore and MemoryAggregator)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from seedcore.memory.contracts import MemorySubsystemStatus

logger = logging.getLogger(__name__)


async def working_memory_stats_dict(mw_manager: Optional[Any]) -> Dict[str, Any]:
    """Snapshot working-memory stats for state aggregation (MwManager + WorkingMemory adapter)."""
    try:
        from seedcore.memory.working_memory import MwWorkingMemoryAdapter
    except ImportError:
        MwWorkingMemoryAdapter = None  # type: ignore

    if mw_manager is None or MwWorkingMemoryAdapter is None:
        st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
        return {
            "status": st.value if st else "unavailable",
            "reason": "mw_manager_unavailable",
        }

    snap = await MwWorkingMemoryAdapter(mw_manager).stats_snapshot()
    total_requests = snap.total_requests
    miss_rate = snap.misses / total_requests if total_requests > 0 else 0.0
    try:
        hot_items = await mw_manager.get_hot_items_async(top_n=10)
        eviction_rate = len(hot_items) / max(total_requests, 1) * 0.1
    except Exception:
        eviction_rate = 0.0

    return {
        "status": snap.health.status.value,
        "reason": snap.health.reason,
        "buffer_size": total_requests,
        "hit_rate": snap.hit_ratio,
        "eviction_rate": eviction_rate,
        "cache_utilization": snap.hit_ratio,
        "miss_rate": miss_rate,
        "total_requests": total_requests,
        "successful_requests": snap.hits,
        "l0_hits": snap.l0_hits,
        "l1_hits": snap.l1_hits,
        "l2_hits": snap.l2_hits,
        "task_hit_ratio": snap.task_hit_ratio,
    }


async def semantic_memory_stats_dict(semantic: Optional[Any]) -> Dict[str, Any]:
    """Snapshot semantic-memory stats (SemanticMemoryService / protocol with stats_snapshot)."""
    if semantic is None:
        st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
        return {
            "status": st.value if st else "unavailable",
            "reason": "semantic_memory_unavailable",
        }

    try:
        snap = await semantic.stats_snapshot()
        total_holons = int(snap.total_holons)
        total_relationships = int(snap.total_relationships)
        bytes_used = int(snap.bytes_used)
    except Exception as e:
        logger.error("SemanticMemory stats_snapshot failed: %s", e)
        st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
        return {
            "status": st.value if st else "unavailable",
            "reason": str(e),
        }

    storage_gb = bytes_used / (1024**3)
    avg_holon_size = bytes_used // total_holons if total_holons > 0 else 0
    index_size_mb = (bytes_used * 0.15) / (1024**2)

    return {
        "status": snap.health.status.value,
        "reason": snap.health.reason,
        "storage_gb": round(storage_gb, 2),
        "compression_ratio": None,
        "access_patterns": total_relationships,
        "total_holons": total_holons,
        "total_relationships": total_relationships,
        "avg_holon_size": int(avg_holon_size),
        "index_size_mb": round(index_size_mb, 2),
        "bytes_used": bytes_used,
        "vector_dimensions": None,
    }


async def incident_memory_stats_dict(incident: Optional[Any]) -> Dict[str, Any]:
    """Snapshot incident-memory stats or return explicit unavailable when not wired."""
    if incident is not None:
        try:
            snap = await incident.stats_snapshot()
            return {
                "status": snap.health.status.value,
                "reason": snap.health.reason,
                "incidents": int(snap.incidents_recorded),
                "queue_size": None,
                "avg_weight": None,
                "decay_rate": None,
                "total_events": int(snap.incidents_recorded),
            }
        except Exception as e:
            st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
            return {
                "status": st.value if st else "unavailable",
                "reason": str(e),
                "incidents": 0,
                "queue_size": None,
                "avg_weight": None,
                "decay_rate": None,
                "total_events": 0,
            }
    st = getattr(MemorySubsystemStatus, "UNAVAILABLE", None)
    return {
        "status": st.value if st else "unavailable",
        "reason": "incident_memory_not_configured",
        "incidents": 0,
        "queue_size": 0,
        "avg_weight": None,
        "decay_rate": None,
        "total_events": 0,
    }
