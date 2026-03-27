#!/usr/bin/env python3
"""
MCP Service Client for SeedCore

This client talks to an MCP Streamable HTTP endpoint using JSON-RPC.
It implements lifecycle initialization, protocol/version headers, and
session propagation while retaining BaseServiceClient resilience patterns.
"""

import os
import logging
import asyncio
import json
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor

import httpx  # pyright: ignore[reportMissingImports]

# ASSUMPTION: This import exists in your codebase.
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

# A single, shared thread pool for all sync calls
# (Copied from baseline architecture)
_SYNC_EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)


class MCPProtocolError(Exception):
    """Raised when an MCP response is malformed or incomplete."""


class MCPServiceClient(BaseServiceClient):
    """
    Client for an MCP Streamable HTTP endpoint.

    Implements:
    - lifecycle initialization (`initialize` + `notifications/initialized`)
    - JSON-RPC `tools/list` and `tools/call`
    - `MCP-Protocol-Version` and `MCP-Session-Id` headers
    - optional legacy fallback during migration
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = None,
    ):
        # Centralized gateway discovery (following pattern from cognitive_client.py and energy_client.py)
        if base_url is None:
            # Allow explicit override via environment variable
            base_url = os.getenv("MCP_BASE_URL")
        if base_url is None:
            # Use ray_utils for gateway discovery, then append /mcp route prefix
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/mcp"
            except Exception:
                # Fallback to localhost if ray_utils unavailable
                base_url = "http://127.0.0.1:8000/mcp"

        # Resolve effective timeout
        if timeout is None:
            try:
                timeout = float(os.getenv("MCP_CLIENT_TIMEOUT", "30.0"))
            except Exception:
                timeout = 30.0

        try:
            retries = int(os.getenv("MCP_CLIENT_RETRIES", "1"))
        except Exception:
            retries = 1

        # (Circuit breaker and retry logic copied from baseline)
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )

        retry_config = RetryConfig(
            max_attempts=max(1, retries),
            base_delay=1.0,
            max_delay=5.0,
        )

        super().__init__(
            service_name="mcp_service",
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )
        self._bootstrap_protocol_state()

    def _bootstrap_protocol_state(self) -> None:
        self._protocol_version = os.getenv("MCP_PROTOCOL_VERSION", "2025-11-25")
        self._negotiated_protocol_version: str = self._protocol_version
        self._session_id: Optional[str] = None
        self._initialized = False
        self._request_seq = 0
        self._state_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._legacy_fallback_enabled = (
            os.getenv("MCP_CLIENT_ENABLE_LEGACY_FALLBACK", "1").strip().lower()
            not in {"0", "false", "no", "off"}
        )
        self._client_name = os.getenv("MCP_CLIENT_NAME", "seedcore")
        self._client_version = os.getenv("MCP_CLIENT_VERSION", "1.0.0")

    def _ensure_protocol_state(self) -> None:
        """
        BaseAgent/ToolManager actors may construct this class using object.__new__
        and call BaseServiceClient.__init__ directly. Ensure MCP protocol state
        exists even in that path.
        """
        if not hasattr(self, "_protocol_version"):
            self._bootstrap_protocol_state()

    # ---------------------------
    # MCP JSON-RPC internals
    # ---------------------------
    async def _next_request_id(self) -> int:
        self._ensure_protocol_state()
        async with self._state_lock:
            self._request_seq += 1
            return self._request_seq

    @staticmethod
    def _timeout_to_httpx(timeout: Optional[float]) -> Optional[httpx.Timeout]:
        if timeout is None:
            return None
        return httpx.Timeout(
            connect=min(timeout, 5.0),
            read=float(timeout),
            write=min(timeout, 5.0),
            pool=min(timeout, 5.0),
        )

    def _build_mcp_headers(
        self,
        *,
        include_protocol_header: bool,
    ) -> Dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if include_protocol_header:
            headers["MCP-Protocol-Version"] = self._negotiated_protocol_version
        if self._session_id:
            headers["MCP-Session-Id"] = self._session_id
        return headers

    def _capture_session_header(self, response: httpx.Response) -> None:
        session_id = response.headers.get("MCP-Session-Id") or response.headers.get(
            "Mcp-Session-Id"
        )
        if session_id:
            self._session_id = session_id

    @staticmethod
    def _parse_sse_messages(raw_text: str) -> List[dict[str, Any]]:
        """
        Parse SSE payload and extract JSON objects from data lines.
        """
        messages: List[dict[str, Any]] = []
        data_lines: List[str] = []

        def flush() -> None:
            if not data_lines:
                return
            payload = "\n".join(data_lines).strip()
            data_lines.clear()
            if not payload:
                return
            try:
                maybe_obj = json.loads(payload)
            except json.JSONDecodeError:
                return
            if isinstance(maybe_obj, dict):
                messages.append(maybe_obj)

        for line in raw_text.splitlines():
            if not line.strip():
                flush()
                continue
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        flush()
        return messages

    def _extract_jsonrpc_response(
        self,
        response: httpx.Response,
        *,
        request_id: Optional[int],
        expect_response: bool,
    ) -> Dict[str, Any]:
        if response.status_code >= 400:
            response.raise_for_status()

        if not expect_response:
            # Notifications often return 202 Accepted with no body.
            return {}

        body = response.text or ""
        if not body.strip():
            raise MCPProtocolError("MCP request expected a JSON-RPC response body")

        content_type = response.headers.get("content-type", "").lower()
        if "text/event-stream" in content_type:
            messages = self._parse_sse_messages(body)
            if not messages:
                raise MCPProtocolError("No JSON-RPC payload found in SSE response")
            if request_id is not None:
                for msg in messages:
                    if msg.get("id") == request_id and (
                        "result" in msg or "error" in msg
                    ):
                        return msg
            return messages[-1]

        payload = response.json()
        if not isinstance(payload, dict):
            raise MCPProtocolError("MCP response body is not a JSON object")
        return payload

    async def _post_jsonrpc(
        self,
        message: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
        include_protocol_header: bool = True,
        expect_response: bool = True,
    ) -> Dict[str, Any]:
        self._ensure_protocol_state()
        headers = self._build_mcp_headers(
            include_protocol_header=include_protocol_header
        )
        timeout_obj = self._timeout_to_httpx(timeout)

        async def _do_request() -> Dict[str, Any]:
            response = await self.http.post(
                self.base_url,
                json=message,
                headers=headers,
                timeout=timeout_obj or self.http.timeout,
            )
            self._capture_session_header(response)
            return self._extract_jsonrpc_response(
                response,
                request_id=message.get("id"),  # notifications have no id
                expect_response=expect_response,
            )

        if self.circuit_breaker:
            return await self.circuit_breaker.call(_do_request)
        return await _do_request()

    async def _ensure_initialized(self) -> None:
        self._ensure_protocol_state()
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            request_id = await self._next_request_id()
            initialize_request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": self._protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self._client_name,
                        "version": self._client_version,
                    },
                },
            }
            response = await self._post_jsonrpc(
                initialize_request,
                include_protocol_header=False,  # required only after initialization
                expect_response=True,
            )
            if response.get("error"):
                raise MCPProtocolError(
                    f"initialize failed: {response['error'].get('message', response['error'])}"
                )
            result = response.get("result") or {}
            if not isinstance(result, dict):
                raise MCPProtocolError("initialize result is not an object")

            negotiated = result.get("protocolVersion")
            if isinstance(negotiated, str) and negotiated.strip():
                self._negotiated_protocol_version = negotiated

            # Lifecycle requirement: send notifications/initialized after initialize.
            await self._post_jsonrpc(
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                include_protocol_header=True,
                expect_response=False,
            )
            self._initialized = True

    async def _reset_session(self) -> None:
        self._initialized = False
        self._session_id = None
        self._negotiated_protocol_version = self._protocol_version

    @staticmethod
    def _should_retry_with_new_session(exc: Exception) -> bool:
        if not isinstance(exc, httpx.HTTPStatusError):
            return False
        response = exc.response
        return response is not None and response.status_code == 404

    @staticmethod
    def _should_fallback_legacy(exc: Exception) -> bool:
        if isinstance(exc, MCPProtocolError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            response = exc.response
            if response is None:
                return False
            return response.status_code in {400, 404, 405}
        return False

    async def _jsonrpc_request(
        self,
        *,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        await self._ensure_initialized()
        req_id = await self._next_request_id()
        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params

        try:
            return await self._post_jsonrpc(
                payload,
                timeout=timeout,
                include_protocol_header=True,
                expect_response=True,
            )
        except Exception as exc:
            if self._session_id and self._should_retry_with_new_session(exc):
                # Session expired (404 with MCP-Session-Id): reinitialize and retry once.
                await self._reset_session()
                await self._ensure_initialized()
                payload["id"] = await self._next_request_id()
                return await self._post_jsonrpc(
                    payload,
                    timeout=timeout,
                    include_protocol_header=True,
                    expect_response=True,
                )
            raise

    @staticmethod
    def _extract_error_message(call_result: Dict[str, Any]) -> str:
        content = call_result.get("content")
        if isinstance(content, list):
            text_parts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        text_parts.append(text.strip())
            if text_parts:
                return " ".join(text_parts)
        return "MCP tool call failed"

    @staticmethod
    def _normalize_tool_result(call_result: Any) -> Any:
        if not isinstance(call_result, dict):
            return call_result

        if "structuredContent" in call_result:
            return call_result["structuredContent"]

        content = call_result.get("content")
        if isinstance(content, list):
            if len(content) == 1 and isinstance(content[0], dict):
                block = content[0]
                if block.get("type") == "text" and "text" in block:
                    return block["text"]
            return content

        return call_result

    async def call_tool_async(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        effective_timeout = timeout if timeout is not None else self.timeout
        logger.debug("MCPServiceClient calling tool: %s", tool_name)

        try:
            response = await self._jsonrpc_request(
                method="tools/call",
                params={"name": tool_name, "arguments": arguments},
                timeout=effective_timeout,
            )
            if response.get("error"):
                return {"error": response["error"]}

            call_result = response.get("result") or {}
            if isinstance(call_result, dict) and bool(call_result.get("isError")):
                return {
                    "error": {
                        "message": self._extract_error_message(call_result),
                        "data": call_result,
                    },
                    "mcp_result": call_result,
                }

            return {
                "result": self._normalize_tool_result(call_result),
                "mcp_result": call_result,
            }
        except Exception as exc:
            if self._legacy_fallback_enabled and self._should_fallback_legacy(exc):
                logger.warning(
                    "MCP JSON-RPC tools/call failed (%s); falling back to legacy /tools/execute",
                    exc,
                )
                payload = {"tool_name": tool_name, "arguments": arguments}
                return await self.post(
                    "/tools/execute", json=payload, timeout=effective_timeout
                )
            raise

    # ---------------------------
    # Service info / health
    # ---------------------------

    async def list_tools_async(self) -> Dict[str, Any]:
        """
        Returns available tool schemas from `tools/list`.
        """
        self._ensure_protocol_state()
        logger.debug("MCPServiceClient fetching tools/list")
        try:
            response = await self._jsonrpc_request(method="tools/list")
            if response.get("error"):
                return {"error": response["error"], "tools": []}
            result = response.get("result") or {}
            tools = result.get("tools", []) if isinstance(result, dict) else []
            return {"tools": tools, "mcp_result": result}
        except Exception as exc:
            if self._legacy_fallback_enabled and self._should_fallback_legacy(exc):
                logger.warning(
                    "MCP JSON-RPC tools/list failed (%s); falling back to legacy /tools/list",
                    exc,
                )
                return await self.post("/tools/list", json={})
            raise

    async def get_mcp_schema(self) -> Dict[str, Any]:
        """
        Best-effort schema endpoint discovery for diagnostics.
        """
        self._ensure_protocol_state()
        return await self.get("/.well-known/mcp.json")

    async def health_check(self) -> Dict[str, Any]:
        """
        Wraps the custom /health endpoint for service monitoring.
        (This is the FastAPI /health, not an MCP one)
        """
        return await self.get("/health")

    async def is_healthy(self) -> bool:
        """Boolean check against the /health endpoint."""
        try:
            health = await self.health_check()
            # The service we wrote returns {"status": "ok"}
            return str(health.get("status", "")).lower() == "ok"
        except Exception:
            return False

    # ---------------------------
    # Sync Wrapper
    # ---------------------------

    def call_tool_sync(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for call_tool_async.
        """

        async def _runner():
            return await self.call_tool_async(
                tool_name=tool_name,
                arguments=arguments,
                timeout=timeout,
            )

        try:
            # Check if we're *already* in a running event loop
            asyncio.get_running_loop()
            
            # If so, we MUST run asyncio.run() in a new thread
            # to avoid 'cannot run nested event loops' error.
            future = _SYNC_EXECUTOR.submit(lambda: asyncio.run(_runner()))
            # Use the client's default timeout as a safety net
            return future.result(timeout=self.timeout + 5.0)
            
        except RuntimeError:
            # No event loop is running. We are in a sync context.
            # It's safe to create a new event loop right here.
            return asyncio.run(_runner())
