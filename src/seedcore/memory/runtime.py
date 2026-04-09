# Copyright 2024 SeedCore Contributors
#
# SPDX-License-Identifier: Apache-2.0
"""Single ownership boundary for working, semantic, and optional incident memory."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from seedcore.memory.backends.neo4j_graph import Neo4jGraph
from seedcore.memory.backends.pgvector_backend import PgVectorStore
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.memory.incident_memory import IncidentMemoryService
from seedcore.memory.semantic_memory import SemanticMemoryService
from seedcore.memory.working_memory import MwWorkingMemoryAdapter
from seedcore.memory.mw_manager import MwManager

logger = logging.getLogger(__name__)


def _host_local_default_pg_dsn() -> str:
    user = os.getenv("POSTGRES_USER") or os.getenv("USER") or "postgres"
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "seedcore")
    auth = user if not password else f"{user}:{password}"
    return f"postgresql://{auth}@{host}:{port}/{db}"


def _host_local_default_neo4j_uri() -> str:
    host = os.getenv("NEO4J_HOST", "127.0.0.1")
    port = os.getenv("NEO4J_BOLT_PORT", "7687")
    return f"bolt://{host}:{port}"


class MemoryRuntime:
    """Owns backend lifecycles and exposes service facades."""

    def __init__(
        self,
        *,
        vec_store: PgVectorStore,
        graph_store: Neo4jGraph,
        fabric: HolonFabric,
        semantic: SemanticMemoryService,
        incident: Optional[IncidentMemoryService] = None,
    ) -> None:
        self._vec = vec_store
        self._graph = graph_store
        self._fabric = fabric
        self.semantic = semantic
        self.incident = incident
        self.working: Optional[MwWorkingMemoryAdapter] = None
        self._closed = False

    @property
    def holon_fabric(self) -> HolonFabric:
        """Prefer ``semantic`` for new code; this remains for compatibility."""
        return self._fabric

    def bind_working_memory(self, mw: MwManager) -> None:
        self.working = MwWorkingMemoryAdapter(mw)

    async def health(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "semantic": "unknown",
            "graph": "unknown",
            "vector_pool": self._vec._pool is not None,
        }
        try:
            _ = await self._vec.get_count()
            out["semantic"] = "ok"
        except Exception as e:
            out["semantic"] = f"error:{e}"
        try:
            await self._graph.ping()
            out["graph"] = "ok"
        except Exception as e:
            out["graph"] = f"error:{e}"
        return out

    async def close(self) -> None:
        """Idempotent shutdown of vector and graph pools (safe across duplicate calls)."""
        if self._closed:
            return
        self._closed = True
        try:
            await self._vec.close()
        except Exception as e:
            logger.debug("PgVector close: %s", e)
        try:
            await self._graph.close()
        except Exception as e:
            logger.debug("Neo4j close: %s", e)

    @staticmethod
    async def connect_storage(
        *,
        pg_dsn: str,
        neo4j_uri: str,
        neo4j_auth: Tuple[str, str],
        pool_size: int = 2,
        pool_min_size: int = 1,
        embedder: Any = None,
        incident: Optional[IncidentMemoryService] = None,
    ) -> "MemoryRuntime":
        vec = PgVectorStore(
            pg_dsn, pool_size=pool_size, pool_min_size=pool_min_size
        )
        graph = Neo4jGraph(neo4j_uri, auth=neo4j_auth)
        await vec._get_pool()
        fabric = HolonFabric(vec_store=vec, graph=graph, embedder=embedder)
        semantic = SemanticMemoryService(fabric)
        return MemoryRuntime(
            vec_store=vec,
            graph_store=graph,
            fabric=fabric,
            semantic=semantic,
            incident=incident,
        )


async def connect_default_memory_runtime(
    *,
    pg_dsn: Optional[str] = None,
    neo4j_uri: Optional[str] = None,
    neo4j_user: Optional[str] = None,
    neo4j_password: Optional[str] = None,
    pool_size: int = 2,
    embedder: Any = None,
) -> MemoryRuntime:
    """Build a runtime from environment defaults (used by organism / agents)."""
    default_pg = (
        "postgresql://postgres:password@postgresql:5432/seedcore"
        if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        else _host_local_default_pg_dsn()
    )
    default_neo4j = (
        "bolt://neo4j:7687"
        if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        else _host_local_default_neo4j_uri()
    )
    dsn = pg_dsn or os.getenv(
        "PG_DSN", default_pg
    )
    uri = neo4j_uri or os.getenv("NEO4J_URI") or os.getenv(
        "NEO4J_BOLT_URL", default_neo4j
    )
    user = neo4j_user or os.getenv("NEO4J_USER", "neo4j")
    password = neo4j_password or os.getenv("NEO4J_PASSWORD", "password")
    return await MemoryRuntime.connect_storage(
        pg_dsn=dsn,
        neo4j_uri=uri,
        neo4j_auth=(user, password),
        pool_size=pool_size,
        pool_min_size=1,
        embedder=embedder,
    )
