#!/usr/bin/env python3
"""
Eventizer Service Client for SeedCore (Optimized)

Client for the Eventizer service (under /ops gateway) with:
- Content-hash memoization
- Circuit breaker with fast-path fallback
- Tuned timeouts for sub-10ms p95
"""

import asyncio
import hashlib
import logging
import time
from typing import Dict, Any, Optional
import httpx  # pyright: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

# Performance-optimized HTTP client configuration
DEFAULT_TIMEOUT = httpx.Timeout(
    connect=0.25, read=0.6, write=0.25, pool=0.25
)

DEFAULT_LIMITS = httpx.Limits(
    max_connections=100, max_keepalive_connections=20, keepalive_expiry=30.0
)

class EventizerCache:
    """Simple LRU cache wrapper."""
    def __init__(self, max_size: int = 4096, ttl: int = 300):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if key in self._cache:
            res, ts = self._cache[key]
            if time.time() - ts < self.ttl: return res
            del self._cache[key]
        return None
    
    def put(self, key: str, val: Dict[str, Any]):
        if len(self._cache) >= self.max_size:
            # Simple eviction (pop random/first) for speed
            self._cache.pop(next(iter(self._cache)), None)
        self._cache[key] = (val, time.time())

class EventizerServiceClient:
    def __init__(self, base_url: str = None):
        # Centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/ops"
            except ImportError:
                base_url = "http://127.0.0.1:8000/ops"
        
        self.base_url = base_url.rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        self._cache = EventizerCache()
        
        # Circuit Breaker State
        self._failures = 0
        self._last_fail = 0
        self._circuit_open = False

    async def _ensure_client(self):
        if self._client: return
        async with self._client_lock:
            if not self._client:
                self._client = httpx.AsyncClient(
                    base_url=self.base_url,
                    http2=True,
                    timeout=DEFAULT_TIMEOUT,
                    limits=DEFAULT_LIMITS
                )

    def _get_cache_key(self, text: str, **kwargs) -> str:
        raw = f"{text}|{kwargs.get('domain','')}|{kwargs.get('task_type','')}"
        return hashlib.sha256(raw.encode()).hexdigest()

    async def process_eventizer_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process text with caching and fallback protection.
        """
        text = payload.get("text", "")
        if not text: return {}

        # 1. Cache Check
        key = self._get_cache_key(text, **payload)
        cached = self._cache.get(key)
        if cached: return {**cached, "cached": True}  # noqa: E701

        # 2. Circuit Breaker Check
        if self._circuit_open:
            if time.time() - self._last_fail > 30.0:
                self._circuit_open = False # Retry probe
            else:
                return self._fallback_response(text, "circuit_open")

        # 3. Remote Call
        try:
            await self._ensure_client()
            resp = await self._client.post("/eventizer/process", json=payload)
            resp.raise_for_status()
            result = resp.json()
            
            self._cache.put(key, result)
            self._failures = 0 # Reset health
            return result
            
        except Exception as e:
            self._failures += 1
            if self._failures > 5: 
                self._circuit_open = True
                self._last_fail = time.time()
            
            logger.warning(f"Eventizer remote failed: {e}")
            return self._fallback_response(text, str(e))

    def _fallback_response(self, text: str, reason: str) -> Dict[str, Any]:
        """Minimal valid response to keep pipeline moving."""
        # We removed FastEventizer, so we return a safe 'unknown' structure
        # The Coordinator will likely see low confidence and re-try or use heuristics
        return {
            "event_tags": {"priority": 0, "event_types": [], "urgency": "normal"},
            "attributes": {},
            "confidence": {"overall_confidence": 0.0, "needs_ml_fallback": True},
            "processing_time_ms": 0.0,
            "pii_redacted": False,
            "processed_text": text, # Pass-through
            "fallback_reason": reason
        }

    async def close(self):
        if self._client: await self._client.aclose()  # noqa: E701
