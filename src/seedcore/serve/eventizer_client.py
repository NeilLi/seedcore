#!/usr/bin/env python3
"""
Eventizer Service Client for SeedCore (Optimized — v2.1)

Aligned with the new OpsGateway unified endpoints:
    POST /ops/eventizer/process
    GET  /ops/eventizer/health

Key Features:
- Multimodal-aware cache keys (Text + Media URI)
- Circuit Breaker with 30s probe mode
- Content-hash based LRU memoization
- Connection pooling for sub-ms gateway overhead
"""

import asyncio
import hashlib
import logging
import time
from typing import Dict, Any, Optional

import httpx  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Performance & Connection Tuning
# ----------------------------------------------------------------------

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=0.25,  # 250ms connect
    read=0.8,  # 800ms read (allows for complex pattern matching)
    write=0.25,
    pool=0.25,
)

DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

# ----------------------------------------------------------------------
# Simple LRU-like memo cache
# ----------------------------------------------------------------------


class EventizerCache:
    def __init__(self, max_size: int = 4096, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._cache.get(key)
        if not entry:
            return None

        value, ts = entry
        if time.time() - ts > self.ttl:
            self._cache.pop(key, None)
            return None

        return value

    def put(self, key: str, value: Dict[str, Any]):
        if len(self._cache) >= self.max_size:
            # Cheap eviction (FIFO fallback) for speed
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (value, time.time())


# ----------------------------------------------------------------------
# Eventizer Client
# ----------------------------------------------------------------------


class EventizerServiceClient:
    """
    High-performance client for EventizerService via OpsGateway.
    Handles the bridge between raw sensory events and the Unified Memory View.
    """

    def __init__(self, base_url: str = None):
        # Unified gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY

                base_url = SERVE_GATEWAY
            except Exception:
                base_url = "http://127.0.0.1:8000"

        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

        self._cache = EventizerCache()

        # Circuit Breaker State
        self._failures = 0
        self._last_fail_time = 0.0
        self._circuit_open = False

    async def _ensure_client(self):
        if self._client:
            return
        async with self._client_lock:
            if not self._client:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=DEFAULT_TIMEOUT,
                    limits=DEFAULT_LIMITS,
                )

    def _get_cache_key(self, payload: Dict[str, Any]) -> str:
        """
        Generates a multimodal-aware cache key.
        Includes media_uri to differentiate different audio/vision inputs with same text.
        """
        text = payload.get("text", "")
        domain = payload.get("domain", "")
        # v2.5 Multimodal support: Include media pointer in cache key
        media_uri = payload.get("multimodal", {}).get("media_uri", "")

        raw = f"{text}|{domain}|{media_uri}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entrypoint for classification.

        Flow:
        1. Cache Check
        2. Circuit Breaker Check
        3. RPC to EventizerService
        4. Fallback on Failure
        """
        text = payload.get("text", "")
        if not text:
            return self._fallback_response("", "empty_text")

        cache_key = self._get_cache_key(payload)

        # 1. Check Cache
        cached = self._cache.get(cache_key)
        if cached:
            return {**cached, "cached": True}

        # 2. Check Circuit Breaker
        if self._circuit_open:
            if time.time() - self._last_fail_time > 30.0:
                logger.info("Eventizer circuit entering probe mode (resetting).")
                self._circuit_open = False
            else:
                return self._fallback_response(text, "circuit_open")

        # 3. Remote Call via OpsGateway
        try:
            await self._ensure_client()
            # Explicit path for OpsGateway routing
            resp = await self._client.post("/ops/eventizer/process", json=payload)
            resp.raise_for_status()

            data = resp.json()
            self._cache.put(cache_key, data)

            # Success: Reset failure counter
            self._failures = 0
            return data

        except Exception as e:
            self._failures += 1
            if self._failures >= 5:
                self._circuit_open = True
                self._last_fail_time = time.time()
                logger.error(f"Eventizer Circuit OPENED due to error: {e}")

            logger.warning(
                f"Eventizer remote call failed (attempts: {self._failures}): {e}"
            )
            return self._fallback_response(text, str(e))

    def _fallback_response(self, text: str, reason: str) -> Dict[str, Any]:
        """
        Safe, minimal result that forces the Coordinator into the Cognitive Path.
        """
        return {
            "event_tags": {
                "priority": 0,
                "event_types": [],
                "urgency": "normal",
                "resolved_type": "routine",
            },
            "attributes": {"routing_hints": {"fallback": True, "reason": reason}},
            "confidence": {
                "overall_confidence": 0.0,
                "needs_ml_fallback": True,  # Triggers System 2 Deep Reasoning
                "fallback_reason": reason,
            },
            "processing_time_ms": 0.0,
            "processed_text": text,
            "pii_redacted": False,
            "path": "client_fallback",
        }

    async def health(self) -> Dict[str, Any]:
        await self._ensure_client()
        resp = await self._client.get("/ops/eventizer/health")
        resp.raise_for_status()
        return resp.json()

    async def is_healthy(self) -> bool:
        try:
            status_data = await self.health()
            return status_data.get("status") == "healthy"
        except Exception:
            return False

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
