from __future__ import annotations

import os
from typing import Any

import httpx  # pyright: ignore[reportMissingImports]


class SeedcorePluginError(RuntimeError):
    """Raised when the plugin-facing runtime surface is unavailable or invalid."""


def normalize_runtime_base_url(base_url: str | None = None) -> str:
    resolved = (base_url or os.getenv("SEEDCORE_API") or "http://127.0.0.1:8002").strip()
    return resolved.rstrip("/")


class SeedcoreRuntimeClient:
    """Thin HTTP adapter over the public SeedCore API surface."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = normalize_runtime_base_url(base_url)
        self.api_v1_base_url = f"{self.base_url}/api/v1"
        self.timeout = timeout if timeout is not None else float(os.getenv("SEEDCORE_PLUGIN_TIMEOUT", "15.0"))
        self._owns_http_client = http_client is None
        self.http = http_client or httpx.AsyncClient(timeout=self.timeout)

    def root_url(self, path: str) -> str:
        return f"{self.base_url}{path if path.startswith('/') else f'/{path}'}"

    def api_url(self, path: str) -> str:
        return f"{self.api_v1_base_url}{path if path.startswith('/') else f'/{path}'}"

    async def close(self) -> None:
        if self._owns_http_client:
            await self.http.aclose()

    async def _request_json(
        self,
        *,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = await self.http.request(method, url, json=payload, params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise SeedcorePluginError(f"{method} {url} failed with status {status}") from exc
        except httpx.HTTPError as exc:
            raise SeedcorePluginError(f"SeedCore runtime unavailable at {url}: {exc}") from exc
        except ValueError as exc:
            raise SeedcorePluginError(f"{method} {url} returned non-JSON response") from exc

        if not isinstance(data, dict):
            raise SeedcorePluginError(f"{method} {url} returned unexpected payload type")
        return data

    async def health(self) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.root_url("/health"))

    async def readyz(self) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.root_url("/readyz"))

    async def pkg_status(self) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/pkg/status"))

    async def pkg_authz_graph_status(self) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/pkg/authz-graph/status"))

    async def hotpath_status(self) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/pdp/hot-path/status"))

    async def evidence_verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="POST", url=self.api_url("/verify"), payload=payload)

    async def replay(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/replay"), params=params)

    async def replay_timeline(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/replay/timeline"), params=params)

    async def replay_artifacts(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/replay/artifacts"), params=params)

    async def replay_jsonld(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url("/replay/jsonld"), params=params)

    async def trust_page(self, public_id: str) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url(f"/trust/{public_id}"))

    async def trust_jsonld(self, public_id: str) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url(f"/trust/{public_id}/jsonld"))

    async def trust_certificate(self, public_id: str) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url(f"/trust/{public_id}/certificate"))

    async def register_did(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="POST", url=self.api_url("/identities/dids"), payload=payload)

    async def update_did(self, did: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="PATCH", url=self.api_url(f"/identities/dids/{did}"), payload=payload)

    async def get_did(self, did: str) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url(f"/identities/dids/{did}"))

    async def grant_delegation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(method="POST", url=self.api_url("/delegations"), payload=payload)

    async def get_delegation(self, delegation_id: str) -> dict[str, Any]:
        return await self._request_json(method="GET", url=self.api_url(f"/delegations/{delegation_id}"))

    async def revoke_delegation(self, delegation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request_json(
            method="POST",
            url=self.api_url(f"/delegations/{delegation_id}/revoke"),
            payload=payload or {},
        )

    async def evaluate_agent_action(
        self,
        payload: dict[str, Any],
        *,
        debug: bool = False,
        no_execute: bool = False,
    ) -> dict[str, Any]:
        params = {
            "debug": "true" if debug else "false",
            "no_execute": "true" if no_execute else "false",
        }
        return await self._request_json(
            method="POST",
            url=self.api_url("/agent-actions/evaluate"),
            payload=payload,
            params=params,
        )
