"""Contract tests for HolonFabric <-> backend alignment (mocked)."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import numpy as np
import pytest

from seedcore.memory.backends.neo4j_graph import Neo4jGraph
from seedcore.memory.backends.pgvector_backend import Holon as VecHolon, PgVectorStore
from seedcore.memory.holon_fabric import HolonFabric
from seedcore.memory.semantic_memory import SemanticMemoryService
from seedcore.models.holon import Holon, HolonScope, HolonType


class _StubVec:
    def __init__(self) -> None:
        self.rows: Dict[str, VecHolon] = {}
        self.deleted: List[str] = []

    async def upsert(self, holon: VecHolon) -> bool:
        self.rows[holon.uuid] = holon
        return True

    async def search(
        self,
        emb: Optional[np.ndarray] = None,
        k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        *,
        query_vec: Optional[np.ndarray] = None,
    ) -> List[Dict[str, Any]]:
        vec = query_vec if query_vec is not None else emb
        assert vec is not None
        out = []
        for u, h in self.rows.items():
            out.append({"uuid": u, "meta": dict(h.meta), "dist": 0.1})
        return out[:k]

    async def get_by_id(self, holon_id: str) -> Optional[VecHolon]:
        return self.rows.get(holon_id)

    async def delete(self, uuid: str) -> bool:
        self.deleted.append(uuid)
        self.rows.pop(uuid, None)
        return True

    async def get_count(self) -> int:
        return len(self.rows)

    async def execute_scalar_query(self, query: str) -> Any:
        return 1024

    async def close(self) -> None:
        pass


class _StubGraph:
    def __init__(self) -> None:
        self.nodes: Dict[str, Dict[str, Any]] = {}
        self.edges: List[tuple] = []
        self.deleted: List[str] = []

    async def upsert_node(
        self,
        uuid: str,
        holon_type: str,
        summary: str,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.nodes[uuid] = {
            "uuid": uuid,
            "holon_type": holon_type,
            "summary": summary,
            "props": dict(props or {}),
        }

    async def upsert_edge(
        self,
        src_uuid: str,
        rel: str,
        dst_uuid: str,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.edges.append((src_uuid, rel, dst_uuid, props))

    async def delete_node(self, uuid: str) -> None:
        self.deleted.append(uuid)
        self.nodes.pop(uuid, None)

    async def get_neighbors(
        self,
        uuid: str,
        rel: Optional[str] = None,
        k: int = 20,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        lim = int(limit if limit is not None else k)
        out = []
        for s, r, d, _ in self.edges:
            if s == uuid and len(out) < lim:
                n = self.nodes.get(d, {})
                out.append(
                    {
                        "uuid": d,
                        "holon_type": n.get("holon_type", "fact"),
                        "summary": n.get("summary", ""),
                        "rel_type": r,
                        "props": dict(n.get("props") or {}),
                    }
                )
        return out

    async def get_count(self) -> int:
        return len(self.edges)

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_holon_fabric_insert_uses_vec_holon_and_graph_props():
    vec = _StubVec()  # type: ignore[assignment]
    graph = _StubGraph()  # type: ignore[assignment]
    fabric = HolonFabric(vec_store=vec, graph=graph)  # type: ignore[arg-type]

    h = Holon(
        id="h1",
        type=HolonType.FACT,
        scope=HolonScope.GLOBAL,
        content={"k": 1},
        summary="hello",
        embedding=[0.0] * 1024,
        links=[{"rel": "LINKS", "target_id": "h2"}],
    )
    await fabric.insert_holon(h)

    assert "h1" in vec.rows
    assert graph.nodes["h1"]["summary"] == "hello"
    assert any(e[0] == "h1" and e[1] == "LINKS" and e[2] == "h2" for e in graph.edges)


@pytest.mark.asyncio
async def test_semantic_memory_search_round_trip():
    vec = _StubVec()  # type: ignore[assignment]
    graph = _StubGraph()  # type: ignore[assignment]
    fabric = HolonFabric(vec_store=vec, graph=graph)  # type: ignore[arg-type]
    sem = SemanticMemoryService(fabric)

    h = Holon(
        id="x1",
        type=HolonType.EPISODE,
        scope=HolonScope.GLOBAL,
        content={},
        summary="episode",
        embedding=[0.0] * 1024,
    )
    await sem.upsert_holon(h)

    from seedcore.memory.contracts import SemanticSearchQuery

    q = SemanticSearchQuery(embedding=[0.0] * 1024, scopes=["global"], limit=3)
    hits = await sem.search(q)
    assert len(hits) >= 1
    assert hits[0].holon_id == "x1"


def test_pgvector_store_accepts_query_vec_alias():
    """Signature-level check without a live DB."""
    import inspect

    sig = inspect.signature(PgVectorStore.search)
    assert "query_vec" in sig.parameters


def test_neo4j_graph_upsert_node_accepts_props_kwonly():
    import inspect

    sig = inspect.signature(Neo4jGraph.upsert_node)
    assert "props" in sig.parameters
