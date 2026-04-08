"""MemoryRuntime.close delegates to underlying stores."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.memory.runtime import MemoryRuntime
from seedcore.memory.semantic_memory import SemanticMemoryService


@pytest.mark.asyncio
async def test_memory_runtime_close_calls_vec_and_graph():
    vec = MagicMock()
    vec.close = AsyncMock()
    graph = MagicMock()
    graph.close = AsyncMock()
    fabric = MagicMock()
    sem = SemanticMemoryService(fabric)  # type: ignore[arg-type]
    rt = MemoryRuntime(
        vec_store=vec,
        graph_store=graph,
        fabric=fabric,  # type: ignore[arg-type]
        semantic=sem,
    )
    await rt.close()
    vec.close.assert_awaited_once()
    graph.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_memory_runtime_close_is_idempotent():
    vec = MagicMock()
    vec.close = AsyncMock()
    graph = MagicMock()
    graph.close = AsyncMock()
    fabric = MagicMock()
    sem = SemanticMemoryService(fabric)  # type: ignore[arg-type]
    rt = MemoryRuntime(
        vec_store=vec,
        graph_store=graph,
        fabric=fabric,  # type: ignore[arg-type]
        semantic=sem,
    )
    await rt.close()
    await rt.close()
    vec.close.assert_awaited_once()
    graph.close.assert_awaited_once()
