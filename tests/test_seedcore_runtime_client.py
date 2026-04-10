from __future__ import annotations

import httpx
import pytest

from seedcore.plugin.runtime_client import SeedcorePluginError, SeedcoreRuntimeClient


@pytest.mark.asyncio
async def test_readyz_returns_payload_on_503() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/readyz"
        return httpx.Response(
            status_code=503,
            json={"status": "not_ready", "deps": {"db": "ok", "kafka": "error: broker unreachable"}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://seedcore.test") as http_client:
        client = SeedcoreRuntimeClient(base_url="http://seedcore.test", http_client=http_client)
        body = await client.readyz()

    assert body["status"] == "not_ready"
    assert body["deps"]["kafka"] == "error: broker unreachable"


@pytest.mark.asyncio
async def test_health_still_raises_on_non_200() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(status_code=503, json={"status": "not_ready"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://seedcore.test") as http_client:
        client = SeedcoreRuntimeClient(base_url="http://seedcore.test", http_client=http_client)
        with pytest.raises(SeedcorePluginError):
            await client.health()
