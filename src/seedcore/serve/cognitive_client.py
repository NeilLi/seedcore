#!/usr/bin/env python3
"""
Cognitive Service Client for SeedCore
src/seedcore/serve/cognitive_client.py

This client provides a clean interface to the deployed cognitive service
that matches the entrypoint interface.
"""

import logging
import time
import random
import asyncio
from typing import Dict, Any, Optional, List

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
BASE_RETRY_DELAY = 0.15  # Base delay in seconds
MAX_RETRY_DELAY = 1.0    # Max delay in seconds

async def _retry(async_fn, *, attempts=3, base_delay=0.15, max_delay=1.0, retriable=(httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError, httpx.HTTPStatusError)):
    """Generic retry helper with exponential backoff and jitter."""
    last_exc = None
    for i in range(attempts):
        try:
            return await async_fn()
        except retriable as e:
            last_exc = e
            # 5xx are retriable; 4xx are not (except 409/429 optionally)
            if isinstance(e, httpx.HTTPStatusError) and not (500 <= e.response.status_code < 600 or e.response.status_code in (409, 429)):
                break
            delay = min(max_delay, base_delay * (2 ** i)) + random.uniform(0, 0.25)
            await asyncio.sleep(delay)
    raise last_exc

class CognitiveServiceClient:
    """
    Client for the deployed cognitive service that matches the entrypoint interface.
    """
    def __init__(self, base_url: str = None, timeout_s: float = 8.0):
        # Prefer centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import COG
                self.base_url = COG
            except Exception:
                # Fallback to localhost if utils unavailable
                self.base_url = "http://127.0.0.1:8000"
        else:
            self.base_url = base_url
        self.timeout_s = timeout_s
        self._client = None
        
    def _get_client(self):
        """Get or create httpx client."""
        if not HTTPX_AVAILABLE:
            raise ImportError("httpx is required for CognitiveServiceClient")
            
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client
        
    async def solve_problem(self, **payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the cognitive service's /solve-problem endpoint.
        Returns the raw service response.
        """
        client = self._get_client()

        agent_id = payload.get("agent_id", f"hgnn_planner_{payload.get('task_id', 'unknown')}")
        problem_statement = payload.get("problem_statement", payload.get("description", str(payload)))

        # Prefer explicitly provided available_tools; otherwise adapt from available_organs list if present
        available_tools: Dict[str, Any] = {}
        if isinstance(payload.get("available_tools"), dict):
            available_tools = payload.get("available_tools") or {}
        elif isinstance(payload.get("available_organs"), list):
            available_tools = {organ: {"type": "organ"} for organ in payload.get("available_organs", [])}

        request_data = {
            "agent_id": agent_id,
            "problem_statement": problem_statement,
            "constraints": payload.get("constraints", {}) or {},
            "available_tools": available_tools,
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/solve-problem",
                json=request_data,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}

    async def reason_about_failure(self, agent_id: str, incident_context: Dict[str, Any], knowledge_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call /reason-about-failure."""
        client = self._get_client()

        body = {
            "agent_id": agent_id,
            "incident_context": incident_context,
            "knowledge_context": knowledge_context or {},
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/reason-about-failure",
                json=body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}

    async def plan_task(self, agent_id: str, task_description: str, current_capabilities: Optional[Dict[str, Any]] = None, available_tools: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call /plan-task."""
        client = self._get_client()

        body = {
            "agent_id": agent_id,
            "task_description": task_description,
            "current_capabilities": current_capabilities or {},
            "available_tools": available_tools or {},
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/plan-task",
                json=body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}

    async def make_decision(self, agent_id: str, decision_context: Dict[str, Any], historical_data: Optional[Dict[str, Any]] = None, knowledge_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Call /make-decision."""
        client = self._get_client()

        body = {
            "agent_id": agent_id,
            "decision_context": decision_context,
            "historical_data": historical_data or {},
            "knowledge_context": knowledge_context or {},
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/make-decision",
                json=body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}

    async def synthesize_memory(self, agent_id: str, memory_fragments: List[Dict[str, Any]], synthesis_goal: str) -> Dict[str, Any]:
        """Call /synthesize-memory."""
        client = self._get_client()

        body = {
            "agent_id": agent_id,
            "memory_fragments": memory_fragments or [],
            "synthesis_goal": synthesis_goal,
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/synthesize-memory",
                json=body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}

    async def assess_capabilities(self, agent_id: str, performance_data: Dict[str, Any], current_capabilities: Dict[str, Any], target_capabilities: Dict[str, Any]) -> Dict[str, Any]:
        """Call /assess-capabilities."""
        client = self._get_client()

        body = {
            "agent_id": agent_id,
            "performance_data": performance_data or {},
            "current_capabilities": current_capabilities or {},
            "target_capabilities": target_capabilities or {},
        }

        async def _do():
            response = await client.post(
                f"{self.base_url}/cognitive/assess-capabilities",
                json=body,
                timeout=self.timeout_s,
            )
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.warning(f"Cognitive service call failed: {e}")
            return {"success": False, "agent_id": agent_id, "result": {}, "error": str(e)}
            
    async def ping(self) -> bool:
        """Health check to verify the service is reachable with retry logic."""
        client = self._get_client()

        async def _do():
            response = await client.get(f"{self.base_url}/cognitive/health", timeout=2.0)
            return response.status_code == 200

        try:
            return await _retry(_do, attempts=MAX_RETRIES, base_delay=BASE_RETRY_DELAY, max_delay=MAX_RETRY_DELAY)
        except Exception as e:
            logger.debug(f"Cognitive health check failed: {e}")
            return False

    async def info(self) -> Optional[Dict[str, Any]]:
        """Fetch /info for debugging/discovery."""
        client = self._get_client()

        async def _do():
            response = await client.get(f"{self.base_url}/cognitive/info", timeout=self.timeout_s)
            response.raise_for_status()
            return response

        try:
            response = await _retry(
                _do,
                attempts=MAX_RETRIES,
                base_delay=BASE_RETRY_DELAY,
                max_delay=MAX_RETRY_DELAY,
            )
            return response.json()
        except Exception as e:
            logger.debug(f"Cognitive info call failed: {e}")
            return None
            
    def is_healthy(self) -> bool:
        """Check if the client can reach the service (cached)."""
        # For now, always return True to avoid blocking
        # In production, you might want to implement proper health checking
        return True
        
    async def close(self):
        """Close the httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None
