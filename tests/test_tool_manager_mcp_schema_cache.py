"""ToolManager MCP wiring and bounded get_tool_schema introspection."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from seedcore.serve.mcp_client import mcp_service_client_from_config
from seedcore.tools.manager import ToolManager


@pytest.mark.asyncio
async def test_get_tool_schema_uses_mcp_index_without_repeated_list_tools():
    mcp = MagicMock()
    mcp.list_tools_async = AsyncMock(
        return_value={
            "tools": [
                {"name": "internet.fetch", "description": "fetch"},
                {"name": "fs.read", "description": "read"},
            ]
        }
    )
    manager = ToolManager(mcp_client=mcp)

    s1 = await manager.get_tool_schema("internet.fetch")
    s2 = await manager.get_tool_schema("fs.read")
    assert s1 and s1.get("name") == "internet.fetch"
    assert s2 and s2.get("name") == "fs.read"
    assert mcp.list_tools_async.await_count == 1

    await manager.get_tool_schema("internet.fetch")
    assert mcp.list_tools_async.await_count == 1


@pytest.mark.asyncio
async def test_list_tools_refreshes_mcp_index():
    mcp = MagicMock()
    mcp.list_tools_async = AsyncMock(
        side_effect=[
            {"tools": [{"name": "a", "description": "1"}]},
            {"tools": [{"name": "a", "description": "2"}]},
        ]
    )
    manager = ToolManager(mcp_client=mcp)

    first = await manager.list_tools()
    assert first["a"]["description"] == "1"
    second = await manager.list_tools()
    assert second["a"]["description"] == "2"
    assert mcp.list_tools_async.await_count == 2


@pytest.mark.asyncio
async def test_get_tool_schema_internal_without_mcp_round_trip():
    mcp = MagicMock()
    mcp.list_tools_async = AsyncMock(return_value={"tools": []})

    class _T:
        def schema(self):
            return {"name": "local.tool", "description": "x"}

    manager = ToolManager(mcp_client=mcp)
    await manager.register_internal(_T())

    sch = await manager.get_tool_schema("local.tool")
    assert sch and sch["name"] == "local.tool"
    mcp.list_tools_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_tool_schema_no_mcp_client_skips_network():
    manager = ToolManager(mcp_client=None)
    assert await manager.get_tool_schema("anything") is None


def test_mcp_service_client_from_config_empty_url_returns_none():
    assert mcp_service_client_from_config(None) is None
    assert mcp_service_client_from_config({"base_url": ""}) is None
    assert mcp_service_client_from_config({"base_url": "   "}) is None


@pytest.mark.asyncio
async def test_mcp_service_client_from_config_builds_client():
    cfg = {
        "base_url": "http://127.0.0.1:8000/mcp",
        "timeout": 12.0,
        "circuit_breaker": {"failure_threshold": 3, "recovery_timeout": 10.0},
        "retry_config": {
            "max_attempts": 2,
            "base_delay": 0.5,
            "max_delay": 2.0,
        },
    }
    client = mcp_service_client_from_config(cfg)
    assert client is not None
    try:
        assert client.base_url == "http://127.0.0.1:8000/mcp"
        assert client.timeout == 12.0
        assert client.circuit_breaker.failure_threshold == 3
        assert client.retry_config.max_attempts == 2
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_service_client_from_config_strips_base_url():
    cfg = {
        "base_url": "http://gateway/mcp/",
        "timeout": 30.0,
        "circuit_breaker": {"failure_threshold": 5, "recovery_timeout": 30.0},
        "retry_config": {
            "max_attempts": 1,
            "base_delay": 1.0,
            "max_delay": 5.0,
        },
    }
    client = mcp_service_client_from_config(cfg)
    assert client is not None
    try:
        assert client.base_url == "http://gateway/mcp"
        assert client.service_name == "mcp_service"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_get_tool_schema_retries_after_transient_mcp_failure():
    mcp = MagicMock()
    mcp.list_tools_async = AsyncMock(
        side_effect=[
            RuntimeError("temporary outage"),
            {"tools": [{"name": "internet.fetch", "description": "fetch"}]},
        ]
    )
    manager = ToolManager(mcp_client=mcp)

    first = await manager.get_tool_schema("internet.fetch")
    assert first is None

    second = await manager.get_tool_schema("internet.fetch")
    assert second and second.get("name") == "internet.fetch"
    assert mcp.list_tools_async.await_count == 2
