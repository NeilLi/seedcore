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
    finally:
        await rt.close()
