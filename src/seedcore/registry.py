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
Runtime registry client for PostgreSQL-based instance management.

This module provides a client for interacting with the runtime registry
data layer defined by SQL migrations, including cluster metadata, instance
registration, and heartbeat management.
"""

import os
import uuid
import socket
import asyncio
import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import text
from .database import get_async_pg_session_factory

logger = logging.getLogger(__name__)

__all__ = [
    "RegistryClient",
    "list_active_instances",
]


class RegistryClient:
    """
    Client for runtime registry operations.
    
    Handles instance registration, status updates, and heartbeat management
    using the PostgreSQL-based registry data layer.
    """
    
    def __init__(
        self, 
        logical_id: str, 
        *, 
        actor_name: Optional[str] = None,
        serve_route: Optional[str] = None, 
        cluster_epoch: Optional[str] = None
    ):
        """
        Initialize registry client.
        
        Args:
            logical_id: Logical identifier for this instance
            actor_name: Ray actor name (if applicable)
            serve_route: Serve route (if applicable)
            cluster_epoch: Cluster epoch (if None, will be read from DB)
        """
        self.instance_id = str(uuid.uuid4())
        self.logical_id = logical_id
        self.actor_name = actor_name
        self.serve_route = serve_route
        self.cluster_epoch = cluster_epoch  # if None, we'll read from cluster_metadata
        self.node_id = os.getenv("RAY_NODE_ID", "")      # fill if available
        self.ip = os.getenv("POD_IP", "") or socket.gethostbyname(socket.gethostname())
        self.pid = os.getpid()
        self._sf = get_async_pg_session_factory()

    async def _ensure_epoch(self):
        """Ensure cluster epoch is set, reading from DB if needed."""
        if self.cluster_epoch:
            return
        async with self._sf() as s:
            # read current epoch from cluster_metadata (id=1)
            res = await s.execute(text("SELECT current_epoch FROM cluster_metadata WHERE id = 1"))
            row = res.first()
            if not row or not row[0]:
                # optional: rotate a new epoch on empty (requires your bootstrap to set it normally)
                raise RuntimeError("No current_epoch set; bootstrap not complete")
            self.cluster_epoch = str(row[0])

    async def register(self):
        """Register this instance in the runtime registry."""
        await self._ensure_epoch()
        async with self._sf() as s:
            await s.execute(text("""
                SELECT register_instance(
                  :instance_id, :logical_id, :cluster_epoch,
                  :actor_name, :serve_route, :node_id, :ip, :pid
                )
            """), {
                "instance_id": self.instance_id,
                "logical_id": self.logical_id,
                "cluster_epoch": self.cluster_epoch,
                "actor_name": self.actor_name,
                "serve_route": self.serve_route,
                "node_id": self.node_id,
                "ip": self.ip,
                "pid": self.pid
            })
            await s.commit()

    async def set_status(self, status: str):
        """Set instance status in the registry.
        
        Args:
            status: One of 'starting', 'alive', 'draining', 'dead'
        """
        async with self._sf() as s:
            await s.execute(text("SELECT set_instance_status(:id, :st)"),
                            {"id": self.instance_id, "st": status})
            await s.commit()

    async def beat(self):
        """Send heartbeat to the registry."""
        async with self._sf() as s:
            await s.execute(text("SELECT beat(:id)"), {"id": self.instance_id})
            await s.commit()


async def list_active_instances() -> List[Dict[str, Any]]:
    """
    List active instances from the registry.
    
    Uses the active_instance view that returns one best instance per logical_id.
    
    Returns:
        List of active instance dictionaries
    """
    sf = get_async_pg_session_factory()
    async with sf() as s:
        res = await s.execute(text("""
            SELECT logical_id, actor_name, serve_route, node_id, ip_address, pid
            FROM active_instance
        """))
        return [dict(r._mapping) for r in res]
