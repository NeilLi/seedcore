#!/usr/bin/env python3
import httpx
import pytest
from unittest.mock import AsyncMock

from seedcore.serve.mcp_client import MCPServiceClient, MCPProtocolError


def _mk_response(
    *,
    status_code: int = 200,
    payload: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    request = httpx.Request("POST", "http://testserver/mcp")
    if payload is None:
        return httpx.Response(
            status_code=status_code,
            headers=headers or {},
            request=request,
            content=b"",
        )
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        request=request,
        json=payload,
    )


@pytest.mark.asyncio
async def test_mcp_call_tool_uses_initialize_and_headers():
    client = MCPServiceClient(base_url="http://testserver/mcp", timeout=5.0)

    responses = [
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "1.0.0"},
                },
            },
            headers={"MCP-Session-Id": "session-123"},
        ),
        _mk_response(status_code=202),
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": "ok"}]},
            }
        ),
    ]

    sent_payloads = []
    sent_headers = []

    async def fake_post(url, json=None, headers=None, timeout=None):
        sent_payloads.append(json or {})
        sent_headers.append(headers or {})
        return responses.pop(0)

    client.http.post = fake_post  # type: ignore[method-assign]

    result = await client.call_tool_async(
        tool_name="internet.fetch",
        arguments={"url": "https://example.com"},
    )

    assert result["result"] == "ok"
    assert sent_payloads[0]["method"] == "initialize"
    assert sent_payloads[1]["method"] == "notifications/initialized"
    assert sent_payloads[2]["method"] == "tools/call"
    assert sent_payloads[2]["params"]["name"] == "internet.fetch"
    assert sent_payloads[2]["params"]["arguments"]["url"] == "https://example.com"

    assert "MCP-Protocol-Version" not in sent_headers[0]
    assert sent_headers[1]["MCP-Protocol-Version"] == "2025-11-25"
    assert sent_headers[2]["MCP-Protocol-Version"] == "2025-11-25"
    assert sent_headers[1]["MCP-Session-Id"] == "session-123"
    assert sent_headers[2]["MCP-Session-Id"] == "session-123"

    await client.close()


@pytest.mark.asyncio
async def test_mcp_list_tools_jsonrpc():
    client = MCPServiceClient(base_url="http://testserver/mcp", timeout=5.0)

    responses = [
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "1.0.0"},
                },
            }
        ),
        _mk_response(status_code=202),
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"tools": [{"name": "internet.fetch"}]},
            }
        ),
    ]

    async def fake_post(url, json=None, headers=None, timeout=None):
        return responses.pop(0)

    client.http.post = fake_post  # type: ignore[method-assign]

    result = await client.list_tools_async()
    assert result["tools"] == [{"name": "internet.fetch"}]

    await client.close()


@pytest.mark.asyncio
async def test_mcp_call_tool_maps_is_error_result():
    client = MCPServiceClient(base_url="http://testserver/mcp", timeout=5.0)
    responses = [
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "test", "version": "1.0.0"},
                },
            }
        ),
        _mk_response(status_code=202),
        _mk_response(
            payload={
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "denied"}],
                },
            }
        ),
    ]

    async def fake_post(url, json=None, headers=None, timeout=None):
        return responses.pop(0)

    client.http.post = fake_post  # type: ignore[method-assign]
    result = await client.call_tool_async(tool_name="fs.read", arguments={"filename": "a"})
    assert "error" in result
    assert "denied" in result["error"]["message"]
    await client.close()


@pytest.mark.asyncio
async def test_mcp_call_tool_falls_back_to_legacy_endpoint():
    client = MCPServiceClient(base_url="http://testserver/mcp", timeout=5.0)
    client._jsonrpc_request = AsyncMock(side_effect=MCPProtocolError("bad transport"))  # type: ignore[method-assign]
    client.post = AsyncMock(return_value={"result": "legacy-ok"})  # type: ignore[method-assign]

    result = await client.call_tool_async(
        tool_name="internet.fetch",
        arguments={"url": "https://example.com"},
    )

    assert result["result"] == "legacy-ok"
    client.post.assert_awaited_once()
    call_args = client.post.await_args
    assert call_args.args[0] == "/tools/execute"

    await client.close()
