#!/usr/bin/env python3
"""
Cognitive Service Client for SeedCore (Refactored v2)

This client provides a clean, unified interface to the deployed
cognitive service's single /execute endpoint.

It is a thin wrapper that maps 1:1 to the CognitiveContext.
The CALLER (e.g., Coordinator) is responsible for setting the
'cog_type', 'decision_kind', and 'input_data'.
"""

import os
import logging
import asyncio
from typing import Dict, Any, Optional, List, Union
from concurrent.futures import ThreadPoolExecutor

from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig
from seedcore.models.cognitive import CognitiveType, DecisionKind

logger = logging.getLogger(__name__)

# A single, shared thread pool for all sync calls
_SYNC_EXECUTOR = ThreadPoolExecutor(max_workers=os.cpu_count() or 4)


class CognitiveServiceClient(BaseServiceClient):
    """
    Client for the unified /execute cognitive endpoint.

    This client is a thin messenger. It has one main method, 'execute_async',
    which sends a CognitiveContext to the server.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = None,
    ):
        # Centralized gateway discovery
        if base_url is None:
            base_url = os.getenv("COG_BASE_URL")
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import COG
                base_url = COG  # already includes /cognitive
            except Exception:
                base_url = "http://127.0.0.1:8000/cognitive"

        # Resolve effective timeout
        if timeout is None:
            try:
                timeout = float(os.getenv("COG_CLIENT_TIMEOUT", "75.0"))
            except Exception:
                timeout = 75.0

        try:
            retries = int(os.getenv("COG_CLIENT_RETRIES", "1"))
        except Exception:
            retries = 1

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
            service_name="cognitive_service",
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config,
        )

    @staticmethod
    def _resolve_cog_type(task_type: Union[str, CognitiveType]) -> CognitiveType:
        """Helper to safely convert a string to a CognitiveType enum."""
        if isinstance(task_type, CognitiveType):
            return task_type
        if isinstance(task_type, str):
            normalized = task_type.strip()
            if not normalized:
                raise ValueError("cog_type must not be empty")
            try:
                return CognitiveType(normalized)
            except ValueError:
                try:
                    return CognitiveType[normalized.upper()]
                except KeyError as exc:
                    raise ValueError(f"Unsupported cog_type '{task_type}'") from exc
        raise TypeError(f"Unsupported cog_type type: {type(task_type)!r}")

    # ---------------------------
    # The New, Unified Execute Method
    # ---------------------------

    async def execute_async(
        self,
        *,
        agent_id: str,
        cog_type: Union[str, CognitiveType],
        decision_kind: DecisionKind,
        input_data: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        llm_provider_override: Optional[str] = None,
        llm_model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        The primary method for all cognitive requests.
        It calls the single /execute endpoint.

        Args:
            agent_id: The ID of the agent making the request.
            cog_type: The *specific job* to perform (e.g., TASK_PLANNING).
            decision_kind: The *workflow pipeline* to use (e.g., COGNITIVE).
            input_data: The payload for the specific cog_type.
            meta: Additional metadata.
            timeout: Optional override for this specific call.
            llm_provider_override: Optional LLM provider override.
            llm_model_override: Optional LLM model override.

        Returns:
            The full response dictionary from the cognitive service.
        """
        resolved_type = self._resolve_cog_type(cog_type)

        # The caller is responsible for setting the decision_kind.
        # It's merged into the meta object.
        request_meta = dict(meta or {})
        request_meta.setdefault("decision_kind", decision_kind.value)

        # Build the V2 payload
        payload: Dict[str, Any] = {
            "agent_id": agent_id,
            "cog_type": resolved_type.value,
            "input_data": dict(input_data or {}),
            "meta": request_meta,
        }

        # Add optional overrides
        if llm_provider_override:
            payload["llm_provider_override"] = (llm_provider_override or "").strip().lower()
        if llm_model_override:
            payload["llm_model_override"] = llm_model_override

        effective_timeout = timeout if timeout is not None else self.timeout
        
        logger.debug(
            f"CognitiveClient executing: agent={agent_id}, "
            f"cog_type={resolved_type.value}, decision_kind={decision_kind.value}"
        )
        
        # Call the single, unified endpoint
        return await self.post("/execute", json=payload, timeout=effective_timeout)

    # ---------------------------
    # Service info / health
    # ---------------------------

    async def get_service_info(self) -> Dict[str, Any]:
        """Wraps the /info endpoint for service discovery."""
        return await self.get("/info")

    async def health_check(self) -> Dict[str, Any]:
        """Wraps the /health endpoint for service monitoring."""
        return await self.get("/health")

    async def is_healthy(self) -> bool:
        """Boolean check against the /health endpoint."""
        try:
            health = await self.health_check()
            return str(health.get("status", "")).lower() == "healthy"
        except Exception:
            return False

    # ---------------------------
    # Sync Wrapper
    # ---------------------------

    def execute_sync(
        self,
        *,
        agent_id: str,
        cog_type: Union[str, CognitiveType],
        decision_kind: DecisionKind,
        input_data: Dict[str, Any],
        meta: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        llm_provider_override: Optional[str] = None,
        llm_model_override: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Synchronous wrapper for execute_async.
        
        This method is safe to call from both sync and async code.
        """
        
        # We need a new, clean event loop to run our async call.
        # Submitting `asyncio.run()` to a thread pool is the
        # safest way to do this from any context (sync or async).
        
        async def _runner():
            return await self.execute_async(
                agent_id=agent_id,
                cog_type=cog_type,
                decision_kind=decision_kind,
                input_data=input_data,
                meta=meta,
                timeout=timeout,
                llm_provider_override=llm_provider_override,
                llm_model_override=llm_model_override,
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