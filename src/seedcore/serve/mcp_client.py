#!/usr/bin/env python3
"""
MCP Service Client for SeedCore

This client provides an interface to the deployed MCP-over-HTTP service.
It is a thin wrapper that maps 1:1 to the MCP JSON-RPC endpoints,
primarily /tools/execute, while retaining the resilience patterns
of the BaseServiceClient.
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

# ASSUMPTION: This import exists in your codebase.
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

# A single, shared thread pool for all sync calls
# (Copied from baseline architecture)
_SYNC_EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)


class MCPServiceClient(BaseServiceClient):
    """
    Client for the unified MCP /tools/execute endpoint.
    
    This client adapts the CognitiveServiceClient's patterns for
    calling a standard MCP-over-HTTP server.
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

    # ---------------------------
    # The Main Tool-Calling Method
    # ---------------------------

    async def call_tool_async(
        self,
        *,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        The primary method for all MCP tool requests.
        It calls the /tools/execute endpoint.

        Args:
            tool_name: The name of the tool (e.g., "internet.fetch").
            arguments: The payload for the specific tool (e.g., {"url": "..."}).
            timeout: Optional override for this specific call.

        Returns:
            The full JSON response dictionary from the MCP service.
            The actual tool result is usually in a 'result' key.
        """
        
        # This is the JSON payload for the /tools/execute endpoint
        payload: Dict[str, Any] = {
            "tool_name": tool_name,
            "arguments": arguments,
        }

        effective_timeout = timeout if timeout is not None else self.timeout
        
        logger.debug(
            f"MCPServiceClient calling tool: name={tool_name}"
        )
        
        # Call the specific MCP endpoint
        return await self.post("/tools/execute", json=payload, timeout=effective_timeout)

    # ---------------------------
    # Service info / health
    # ---------------------------

    async def list_tools_async(self) -> Dict[str, Any]:
        """
        Wraps the /tools/list MCP endpoint to get all tool schemas.
        
        Returns:
            The full JSON response dictionary from the MCP service.
            The tools are typically in a 'tools' key as a list.
        """
        logger.debug("MCPServiceClient fetching /tools/list")
        # Per the MCP spec, /tools/list is a POST with an empty JSON body
        return await self.post("/tools/list", json={})

    async def get_mcp_schema(self) -> Dict[str, Any]:
        """
        Wraps the /.well-known/mcp.json endpoint for service discovery
        and to retrieve the list of available tools and resources.
        """
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
        
        This method is safe to call from both sync and async code.
        (Logic is copied from the baseline's execute_sync)
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