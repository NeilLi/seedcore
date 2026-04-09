"""Optional live-backend checks for semantic runtime (CI/host lane).

Set ``SEEDCORE_LIVE_MEMORY_BACKENDS=1`` and valid ``PG_DSN`` / Neo4j env vars to run.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("SEEDCORE_LIVE_MEMORY_BACKENDS", "").strip().lower()
    not in {"1", "true", "yes", "on"},
    reason="SEEDCORE_LIVE_MEMORY_BACKENDS not enabled",
)


@pytest.mark.asyncio
async def test_connect_default_memory_runtime_health_smoke():
    from seedcore.memory.runtime import connect_default_memory_runtime

    rt = await connect_default_memory_runtime(pool_size=1)
    try:
        h = await rt.health()
        assert "semantic" in h
        assert "graph" in h
    finally:
        await rt.close()


@pytest.mark.asyncio
async def test_live_semantic_search_executes_pgvector_path():
    """Exercises HolonFabric → PgVectorStore search (1024-d holons schema)."""
    from seedcore.memory.contracts import SemanticSearchQuery
    from seedcore.memory.runtime import connect_default_memory_runtime

    rt = await connect_default_memory_runtime(pool_size=1)
    try:
        q = SemanticSearchQuery(
            embedding=[0.0] * 1024,
            scopes=["global"],
            limit=3,
            hydrate_neighbors=False,
        )
        rows = await rt.semantic.search(q)
        assert isinstance(rows, list)
    finally:
        await rt.close()
