#!/usr/bin/env python3
"""
Eventizer Service Client for SeedCore

This client provides a clean interface to the deployed eventizer service
for text processing, classification, and PKG policy evaluation.

Optimized for performance with:
- HTTP connection pooling and keep-alive
- Content-hash memoization with LRU cache
- Circuit breaker and fast fallback
- Tuned timeouts for sub-10ms p95
"""

import asyncio
import hashlib
import json
import logging
import time
from functools import lru_cache
from typing import Dict, Any, Optional, List
import httpx

logger = logging.getLogger(__name__)

# Performance-optimized HTTP client configuration
DEFAULT_TIMEOUT = httpx.Timeout(
    connect=0.25,  # 250ms connect timeout
    read=0.6,      # 600ms read timeout  
    write=0.25,    # 250ms write timeout
    pool=0.25      # 250ms pool timeout
)

DEFAULT_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0
)

# Cache configuration
CACHE_SIZE = 4096
CACHE_TTL_SECONDS = 300  # 5 minutes

class EventizerCache:
    """LRU cache for eventizer results with TTL."""
    
    def __init__(self, max_size: int = CACHE_SIZE, ttl: int = CACHE_TTL_SECONDS):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: Dict[str, tuple[Dict[str, Any], float]] = {}
        self._access_order: List[str] = []
    
    def _cleanup_expired(self):
        """Remove expired entries."""
        current_time = time.time()
        expired_keys = [
            key for key, (_, timestamp) in self._cache.items()
            if current_time - timestamp > self.ttl
        ]
        for key in expired_keys:
            self._cache.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)
    
    def _evict_lru(self):
        """Evict least recently used entry."""
        if self._access_order:
            oldest_key = self._access_order.pop(0)
            self._cache.pop(oldest_key, None)
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached result if not expired."""
        self._cleanup_expired()
        
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp <= self.ttl:
                # Move to end (most recently used)
                self._access_order.remove(key)
                self._access_order.append(key)
                return result
            else:
                # Expired, remove it
                self._cache.pop(key, None)
                if key in self._access_order:
                    self._access_order.remove(key)
        
        return None
    
    def put(self, key: str, value: Dict[str, Any]):
        """Store result in cache."""
        self._cleanup_expired()
        
        # Remove if already exists
        if key in self._cache:
            self._cache.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)
        
        # Evict LRU if at capacity
        if len(self._cache) >= self.max_size:
            self._evict_lru()
        
        # Add new entry
        self._cache[key] = (value, time.time())
        self._access_order.append(key)
    
    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()
        self._access_order.clear()
    
    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        self._cleanup_expired()
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "hit_rate": getattr(self, '_hits', 0) / max(getattr(self, '_requests', 1), 1),
            "ttl_seconds": self.ttl
        }

class EventizerServiceClient:
    """
    Optimized client for the deployed eventizer service.
    
    Features:
    - HTTP/2 with connection pooling and keep-alive
    - Content-hash memoization with LRU cache
    - Circuit breaker with fast fallback to fast-path
    - Tuned timeouts for sub-10ms p95
    - Concurrency limits to prevent head-of-line blocking
    """
    
    def __init__(self, 
                 base_url: str = None,
                 timeout: httpx.Timeout = DEFAULT_TIMEOUT,
                 limits: httpx.Limits = DEFAULT_LIMITS,
                 cache_size: int = CACHE_SIZE,
                 cache_ttl: int = CACHE_TTL_SECONDS,
                 max_concurrent: int = 100):
        
        # Use centralized gateway discovery (eventizer service now under /ops)
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import SERVE_GATEWAY
                base_url = f"{SERVE_GATEWAY}/ops"
            except Exception:
                base_url = "http://127.0.0.1:8000/ops"
        
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.limits = limits
        self.max_concurrent = max_concurrent
        
        # Initialize HTTP client (lazy)
        self._client: Optional[httpx.AsyncClient] = None
        self._client_lock = asyncio.Lock()
        
        # Initialize cache
        self._cache = EventizerCache(max_size=cache_size, ttl=cache_ttl)
        
        # Concurrency control
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # Circuit breaker state
        self._failure_count = 0
        self._last_failure_time = 0
        self._circuit_open = False
        self._failure_threshold = 5
        self._recovery_timeout = 30.0
        
        # Metrics
        self._requests_total = 0
        self._requests_success = 0
        self._requests_failed = 0
        self._cache_hits = 0
        self._fallback_count = 0
        self._latency_sum = 0.0
        self._latency_count = 0
    
    async def _ensure_client(self):
        """Ensure HTTP client is initialized (singleton pattern)."""
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    self._client = httpx.AsyncClient(
                        base_url=self.base_url,
                        http2=True,
                        timeout=self.timeout,
                        limits=self.limits,
                        headers={
                            "Accept-Encoding": "gzip",
                            "Content-Type": "application/json",
                            "User-Agent": "seedcore-eventizer-client/1.0"
                        }
                    )
    
    @staticmethod
    @lru_cache(maxsize=8192)
    def _cache_key(text: str, task_type: str = "", domain: str = "") -> str:
        """Generate cache key from normalized text and context."""
        # Simple normalization for cache efficiency
        normalized = text.strip().lower()
        context = f"{task_type}:{domain}".lower()
        combined = f"{normalized}|{context}"
        return hashlib.sha256(combined.encode("utf-8")).hexdigest()
    
    def _should_use_fast_path(self, text: str) -> bool:
        """Determine if we should use fast-path processing."""
        # Use fast-path for very short texts
        if len(text.strip()) < 50:
            return True
        
        # Use fast-path if circuit breaker is open
        if self._circuit_open:
            return True
        
        # Use fast-path if failure rate is too high
        if self._requests_total > 10 and self._failure_count > self._requests_total * 0.3:
            return True
        
        return False
    
    async def _fallback_to_fast_path(self, text: str, task_type: str = "", domain: str = "") -> Dict[str, Any]:
        """Fallback to fast-path processing."""
        try:
            from ..ops.eventizer.fast_eventizer import process_text_fast
            self._fallback_count += 1
            logger.debug("Using fast-path fallback for eventizer processing")
            return process_text_fast(text, task_type, domain)
        except Exception as e:
            logger.warning(f"Fast-path fallback failed: {e}")
            # Return minimal response
            return {
                "event_tags": {"priority": 2, "event_types": ["normal"], "confidence": 0.1, "needs_ml_fallback": True},
                "attributes": {"has_urgency": False, "has_location": False, "has_timestamp": False, "text_length": len(text), "word_count": len(text.split())},
                "confidence": {"overall_confidence": 0.1, "needs_ml_fallback": True},
                "processing_time_ms": 0.1,
                "patterns_applied": 0,
                "pii_redacted": False,
                "original_text": text,
                "processed_text": text,
                "processing_log": ["Fast-path fallback"],
                "fast_path": True,
                "fallback_reason": str(e)
            }
    
    async def process_eventizer_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a complete EventizerRequest payload with optimizations.
        
        Features:
        - Content-hash memoization
        - Circuit breaker with fast fallback
        - Concurrency limits
        - Performance metrics
        """
        start_time = time.perf_counter()
        self._requests_total += 1
        
        text = payload.get("text", "")
        task_type = payload.get("task_type", "")
        domain = payload.get("domain", "")
        
        # Check if we should use fast-path
        if self._should_use_fast_path(text):
            result = await self._fallback_to_fast_path(text, task_type, domain)
            self._latency_sum += time.perf_counter() - start_time
            self._latency_count += 1
            return result
        
        # Check cache first
        cache_key = self._cache_key(text, task_type, domain)
        cached_result = self._cache.get(cache_key)
        if cached_result:
            self._cache_hits += 1
            self._latency_sum += time.perf_counter() - start_time
            self._latency_count += 1
            cached_result["cached"] = True
            return cached_result
        
        # Check circuit breaker
        current_time = time.time()
        if self._circuit_open:
            if current_time - self._last_failure_time > self._recovery_timeout:
                self._circuit_open = False
                self._failure_count = 0
                logger.info("Circuit breaker reset - attempting remote call")
            else:
                logger.debug("Circuit breaker open - using fast-path fallback")
                result = await self._fallback_to_fast_path(text, task_type, domain)
                self._latency_sum += time.perf_counter() - start_time
                self._latency_count += 1
                return result
        
        # Make remote call with concurrency control
        async with self._semaphore:
            try:
                await self._ensure_client()
                
                # Truncate very long texts for performance
                if len(text) > 8000:  # 8KB limit
                    payload = payload.copy()
                    payload["text"] = text[:4000] + "..." + text[-4000:]
                    payload["truncated"] = True
                
                response = await self._client.post("/eventizer/process", json=payload)
                response.raise_for_status()
                
                result = response.json()
                
                # Cache successful results
                self._cache.put(cache_key, result)
                
                # Update metrics
                self._requests_success += 1
                self._failure_count = max(0, self._failure_count - 1)  # Reduce failure count on success
                
                self._latency_sum += time.perf_counter() - start_time
                self._latency_count += 1
                
                return result
                
            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as e:
                logger.warning(f"Eventizer timeout: {e}")
                self._requests_failed += 1
                self._failure_count += 1
                self._last_failure_time = current_time
                
                if self._failure_count >= self._failure_threshold:
                    self._circuit_open = True
                    logger.warning(f"Circuit breaker opened after {self._failure_count} failures")
                
                # Fallback to fast-path
                result = await self._fallback_to_fast_path(text, task_type, domain)
                result["timeout_fallback"] = True
                
                self._latency_sum += time.perf_counter() - start_time
                self._latency_count += 1
                
                return result
                
            except Exception as e:
                logger.error(f"Eventizer request failed: {e}")
                self._requests_failed += 1
                self._failure_count += 1
                self._last_failure_time = current_time
                
                if self._failure_count >= self._failure_threshold:
                    self._circuit_open = True
                    logger.warning(f"Circuit breaker opened after {self._failure_count} failures")
                
                # Fallback to fast-path
                result = await self._fallback_to_fast_path(text, task_type, domain)
                result["error_fallback"] = True
                result["error"] = str(e)
                
                self._latency_sum += time.perf_counter() - start_time
                self._latency_count += 1
                
                return result
    
    async def process_text(self, text: str, **kwargs) -> Dict[str, Any]:
        """
        Process text through the eventizer pipeline (convenience method).
        
        Args:
            text: Input text to process
            **kwargs: Additional parameters for EventizerRequest
            
        Returns:
            EventizerResponse with classification results, tags, and PKG hints
        """
        payload = {
            "text": text,
            **kwargs
        }
        return await self.process_eventizer_request(payload)
    
    # Metrics and Monitoring
    def get_metrics(self) -> Dict[str, Any]:
        """Get performance and health metrics."""
        avg_latency = self._latency_sum / max(self._latency_count, 1)
        
        return {
            "requests_total": self._requests_total,
            "requests_success": self._requests_success,
            "requests_failed": self._requests_failed,
            "cache_hits": self._cache_hits,
            "fallback_count": self._fallback_count,
            "average_latency_ms": avg_latency * 1000,
            "success_rate": self._requests_success / max(self._requests_total, 1),
            "cache_hit_rate": self._cache_hits / max(self._requests_total, 1),
            "circuit_breaker_open": self._circuit_open,
            "failure_count": self._failure_count,
            "cache_stats": self._cache.stats()
        }
    
    async def close(self):
        """Close the HTTP client and cleanup resources."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    # Convenience methods for common use cases
    async def classify_emergency(self, text: str) -> Dict[str, Any]:
        """
        Classify text for emergency events.
        
        Args:
            text: Text to classify
            
        Returns:
            Classification results with emergency-specific tags
        """
        return await self.process_text(text, priority=10, event_types=["emergency"])
    
    async def classify_security(self, text: str) -> Dict[str, Any]:
        """
        Classify text for security events.
        
        Args:
            text: Text to classify
            
        Returns:
            Classification results with security-specific tags
        """
        return await self.process_text(text, priority=8, event_types=["security"])
    
    async def extract_tags(self, text: str) -> Dict[str, Any]:
        """
        Extract tags and attributes from text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Extracted tags, attributes, and metadata
        """
        result = await self.process_text(text)
        return {
            "tags": result.get("tags", {}),
            "attributes": result.get("attributes", {}),
            "metadata": result.get("metadata", {})
        }
    
    async def get_pkg_hints(self, text: str) -> Dict[str, Any]:
        """
        Get PKG policy hints for text processing.
        
        Args:
            text: Text to evaluate against PKG policies
            
        Returns:
            PKG hints, subtasks, and policy evaluation results
        """
        result = await self.process_text(text)
        return {
            "pkg_hint": result.get("pkg_hint", {}),
            "pkg_snapshot_version": result.get("pkg_snapshot_version"),
            "pkg_snapshot_id": result.get("pkg_snapshot_id"),
            "pkg_validation_status": result.get("pkg_validation_status"),
            "pkg_deployment_info": result.get("pkg_deployment_info", {})
        }
    
    # Batch processing (if supported by the service)
    async def process_batch(self, texts: List[str]) -> List[Dict[str, Any]]:
        """
        Process multiple texts in batch.
        
        Args:
            texts: List of texts to process
            
        Returns:
            List of EventizerResponse results
        """
        results = []
        for text in texts:
            try:
                result = await self.process_text(text)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process text in batch: {e}")
                results.append({
                    "error": str(e),
                    "text": text[:100] + "..." if len(text) > 100 else text
                })
        return results
    
    # Configuration and validation
    async def validate_config(self) -> Dict[str, Any]:
        """
        Validate eventizer service configuration.
        
        Returns:
            Configuration validation results
        """
        health = await self.health_check()
        return {
            "service_healthy": health.get("status") == "healthy",
            "initialized": health.get("initialized", False),
            "service_name": health.get("service", "eventizer"),
            "configuration_valid": True  # Add actual validation logic if needed
        }
    
    # Pattern matching utilities
    async def test_patterns(self, text: str, patterns: List[str] = None) -> Dict[str, Any]:
        """
        Test pattern matching against text.
        
        Args:
            text: Text to test
            patterns: Optional list of specific patterns to test
            
        Returns:
            Pattern matching results
        """
        payload = {
            "text": text,
            "test_patterns": patterns or []
        }
        return await self.process_eventizer_request(payload)
