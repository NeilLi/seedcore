from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

from .compiler import CompiledAuthzIndex
from .service import AuthzGraphProjectionService, AuthzProjectionResult

logger = logging.getLogger(__name__)


class AuthzGraphManager:
    """
    Manages the active compiled authorization graph snapshot associated with the
    currently active PKG snapshot.
    """

    def __init__(self, projection_service: AuthzGraphProjectionService):
        self._projection_service = projection_service
        self._lock = threading.Lock()
        self._active_compiled_index: Optional[CompiledAuthzIndex] = None
        self._active_projection: Optional[AuthzProjectionResult] = None
        self._status: Dict[str, Any] = {
            "healthy": False,
            "active_snapshot_id": None,
            "active_snapshot_version": None,
            "graph_nodes_count": 0,
            "graph_edges_count": 0,
            "error": None,
        }

    async def activate_snapshot(
        self,
        *,
        snapshot_id: int,
        snapshot_version: str,
        snapshot_ref: Optional[str] = None,
    ) -> CompiledAuthzIndex:
        ref = snapshot_ref or f"authz_graph@{snapshot_version}"
        compiled, result = await self._projection_service.build_compiled_index(
            snapshot_ref=ref,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
        )
        with self._lock:
            self._active_compiled_index = compiled
            self._active_projection = result
            self._status = {
                "healthy": True,
                "active_snapshot_id": snapshot_id,
                "active_snapshot_version": snapshot_version,
                "graph_nodes_count": result.stats.get("graph_nodes_count", 0),
                "graph_edges_count": result.stats.get("graph_edges_count", 0),
                "error": None,
            }
        logger.info(
            "Activated authz graph snapshot %s (id=%s) with %s nodes / %s edges",
            snapshot_version,
            snapshot_id,
            result.stats.get("graph_nodes_count", 0),
            result.stats.get("graph_edges_count", 0),
        )
        return compiled

    def get_active_compiled_index(self) -> Optional[CompiledAuthzIndex]:
        with self._lock:
            return self._active_compiled_index

    def get_active_projection(self) -> Optional[AuthzProjectionResult]:
        with self._lock:
            return self._active_projection

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)
