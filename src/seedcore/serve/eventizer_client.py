#!/usr/bin/env python3
"""
Eventizer Service Client for SeedCore (Optimized — v2)

Aligned with the new OpsGateway unified endpoints:
    POST /ops/eventizer/process
    GET  /ops/eventizer/health

This client includes:
- High-performance httpx.AsyncClient with tuned timeouts
- LRU-like memoization cache (content-hash based)
- Circuit breaker with retry probe mode
- Fast-path avoidance under load/failure
"""

import asyncio
import hashlib
import logging
import time
from typing import Dict, Any, Optional

import httpx  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Performance Optimizations
# ----------------------------------------------------------------------

DEFAULT_TIMEOUT = httpx.Timeout(
    connect=0.25,
    read=0.6,
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
            # Cheap eviction for speed
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (value, time.time())


# ----------------------------------------------------------------------
# Eventizer Client
# ----------------------------------------------------------------------

class EventizerServiceClient:
    """
    High-performance client for EventizerService via OpsGateway.

    API surface (OpsGateway):
        POST /ops/eventizer/process
        GET  /ops/eventizer/health
    """

    def __init__(self, base_url: str = None):
        # Unified gateway discovery (consistent with other clients)
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = SERVE_GATEWAY  # e.g.: http://127.0.0.1:8000
            except Exception:
                base_url = "http://127.0.0.1:8000"

        # IMPORTANT: Do *not* append /ops here.
        # All calls will use explicit paths: /ops/eventizer/xxx
        self.base_url = base_url.rstrip("/")

        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()

        self._cache = EventizerCache()

        # Circuit Breaker
        self._failures = 0
        self._last_fail_time = 0.0
        self._circuit_open = False

    # ------------------------------------------------------------------
    # Internal HTTP client setup
    # ------------------------------------------------------------------

    async def _ensure_client(self):
        if self._client:
            return
        async with self._client_lock:
            if not self._client:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    http2=True,
                    timeout=DEFAULT_TIMEOUT,
                    limits=DEFAULT_LIMITS,
                )

    # ------------------------------------------------------------------
    # Utility: Cache Key
    # ------------------------------------------------------------------

    def _get_cache_key(self, payload: Dict[str, Any]) -> str:
        text = payload.get("text", "")
        domain = payload.get("domain", "")
        task_type = payload.get("task_type", "")
        raw = f"{text}|{domain}|{task_type}"
        return hashlib.sha256(raw.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Main Method: Eventizer Processing
    # ------------------------------------------------------------------

    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        High-performance text processing with caching and circuit breaker fallback.

        Matches:
            POST /ops/eventizer/process
        """
        text = payload.get("text", "")
        if not text:
            return self._fallback_response("", "empty_text")

        cache_key = self._get_cache_key(payload)

        # 1. Fast-path cache
        cached = self._cache.get(cache_key)
        if cached:
            return {**cached, "cached": True}

        # 2. Circuit breaker short-circuit
        if self._circuit_open:
            # Re-open after 30s delay
            if time.time() - self._last_fail_time > 30.0:
                self._circuit_open = False
            else:
                return self._fallback_response(text, "circuit_open")

        # 3. Remote call
        try:
            await self._ensure_client()
            resp = await self._client.post("/ops/eventizer/process", json=payload)
            resp.raise_for_status()

            data = resp.json()
            self._cache.put(cache_key, data)

            # Success → reset circuit breaker
            self._failures = 0
            return data

        except Exception as e:
            self._failures += 1
            if self._failures >= 5:
                self._circuit_open = True
                self._last_fail_time = time.time()

            logger.warning(f"Eventizer error: {e}")
            return self._fallback_response(text, str(e))

    # ------------------------------------------------------------------
    # Fallback Response (safe minimal result)
    # ------------------------------------------------------------------

    def _fallback_response(self, text: str, reason: str) -> Dict[str, Any]:
        return {
            "event_tags": {
                "priority": 0,
                "event_types": [],
                "urgency": "normal",
            },
            "attributes": {},
            "confidence": {
                "overall_confidence": 0.0,
                "needs_ml_fallback": True,
            },
            "processing_time_ms": 0.0,
            "processed_text": text,
            "pii_redacted": False,
            "fallback_reason": reason,
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """
        Check health via:
            GET /ops/eventizer/health
        """
        await self._ensure_client()
        resp = await self._client.get("/ops/eventizer/health")
        resp.raise_for_status()
        return resp.json()

    async def is_healthy(self) -> bool:
        try:
            return (await self.health()).get("status") == "healthy"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self):
        if self._client:
            await self._client.aclose()
