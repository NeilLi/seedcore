"""Core routing functionality for bulk route resolution and cache management."""

import time
import asyncio
import random
import uuid
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Callable, Tuple, NamedTuple

from seedcore.serve.base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)


class RouteEntry(NamedTuple):
    """Cached route entry with metadata."""
    logical_id: str
    epoch: str
    resolved_from: str  # 'cache', 'bulk', 'fallback', 'unknown', etc.
    instance_id: Optional[str] = None
    cached_at: float = 0.0


class RouteCache:
    """Thread-safe route cache with TTL and jitter."""
    
    def __init__(self, ttl_s: float = 3.0, jitter_s: float = 0.5):
        self.ttl_s = ttl_s
        self.jitter_s = jitter_s
        self._cache: Dict[Tuple[str, Optional[str]], Tuple[RouteEntry, float]] = {}
        self._lock = asyncio.Lock()
        self._inflight: Dict[Tuple[str, Optional[str]], asyncio.Future] = {}

    def _expired(self, expires_at: float) -> bool:
        return time.monotonic() > expires_at

    def _expires_at(self) -> float:
        return time.monotonic() + self.ttl_s + random.uniform(0, self.jitter_s)

    def get(self, key: Tuple[str, Optional[str]]) -> Optional[RouteEntry]:
        """Get cached route entry if not expired."""
        v = self._cache.get(key)
        if not v:
            return None
        entry, expires_at = v
        if self._expired(expires_at):
            self._cache.pop(key, None)
            return None
        return entry

    def set(self, key: Tuple[str, Optional[str]], entry: RouteEntry) -> None:
        """Set cached route entry with TTL."""
        self._cache[key] = (entry, self._expires_at())

    async def singleflight(self, key: Tuple[str, Optional[str]]):
        """Ensure only one resolve for a given key at a time (prevents dogpiles).

        Yields a tuple (future, is_leader). Exactly one caller per key will
        have is_leader=True and is responsible for computing the result and
        completing the future. All others should await the future result.
        """
        async with self._lock:
            fut = self._inflight.get(key)
            is_leader = False
            if fut is None:
                fut = asyncio.get_event_loop().create_future()
                self._inflight[key] = fut
                is_leader = True
        try:
            yield fut, is_leader
        finally:
            # Only the leader clears the inflight map entry after completion
            if is_leader:
                async with self._lock:
                    self._inflight.pop(key, None)

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics for observability."""
        now = time.monotonic()
        active_entries = 0
        expired_entries = 0
        
        for entry, expires_at in self._cache.values():
            if now > expires_at:
                expired_entries += 1
            else:
                active_entries += 1
        
        return {
            "active_entries": active_entries,
            "expired_entries": expired_entries,
            "total_entries": len(self._cache),
            "inflight_requests": len(self._inflight),
            "ttl_s": self.ttl_s,
            "jitter_s": self.jitter_s
        }


def _norm_pair(t: Optional[str], d: Optional[str]) -> Tuple[str, Optional[str]]:
    """Normalize type and domain pair for consistent key generation."""
    t = (t or "").strip().lower()
    d = (d or None)
    if d is not None:
        d = d.strip().lower() or None
    return t, d


def _corr_headers(target: str, cid: str) -> Dict[str, str]:
    """Create correlation headers for cross-service communication."""
    return {
        "Content-Type": "application/json",
        "X-Service": "coordinator",
        "X-Source-Service": "coordinator",
        "X-Target-Service": target,
        "X-Correlation-ID": cid,
    }


def _pair_key(pair: Tuple[str, Optional[str]]) -> str:
    """Convert (type, domain) pair to string key for API calls."""
    t, d = pair
    return f"{t}|{d or ''}"


def get_cached_route(task_type: str, domain: Optional[str], route_cache: "RouteCache") -> Optional[str]:
    """Get cached route for a single task type/domain pair."""
    if not route_cache:
        return None
    pair = _norm_pair(task_type, domain)
    e = route_cache.get(pair)
    return e.logical_id if e else None


async def bulk_resolve_routes_cached(
    steps: List[Dict[str, Any]], 
    cid: str,
    route_cache: "RouteCache",
    normalize_func: Callable[[Optional[str]], Optional[str]],
    normalize_domain_func: Callable[[Optional[str]], Optional[str]],
    static_route_fallback_func: Callable[[str, Optional[str]], str],
    organism_client: BaseServiceClient,
    metrics: Optional[Any] = None,
    last_seen_epoch: Optional[str] = None,
) -> Tuple[Dict[int, str], Optional[str]]:
    """
    Given HGNN steps (each has step['task'] with type/domain),
    return a mapping: { step_index -> logical_id }.
    De-duplicates (type, domain) pairs to minimize network calls.
    
    Args:
        steps: List of HGNN steps
        cid: Correlation ID
        route_cache: Route cache instance
        normalize_func: Function to normalize task type
        normalize_domain_func: Function to normalize domain
        static_route_fallback_func: Static routing fallback function
        organism_client: BaseServiceClient instance for HTTP calls to organism service
        metrics: Optional metrics tracker
        last_seen_epoch: Last seen epoch for cache invalidation
        
    Returns:
        Tuple of (mapping of step index to logical ID, new epoch or None)
    """
    # 1) Group indices by unique (type, domain) pairs and check cache
    pairs: Dict[Tuple[str, Optional[str]], List[int]] = {}
    mapping: Dict[int, str] = {}  # final result
    to_resolve = []

    for idx, step in enumerate(steps):
        subtask = step.get("task") or {}
        t = normalize_func(subtask.get("type"))
        d = normalize_domain_func(subtask.get("domain"))  # Use domain normalizer
        key = (t, d)
        
        if not t:
            continue  # skip; executor will fallback
        
        if key not in pairs:
            pairs[key] = []
        pairs[key].append(idx)

        # Check cache for this (type, domain) pair
        cached = route_cache.get(key)
        if cached:
            # Apply cached result to all indices with this (type, domain)
            for step_idx in pairs[key]:
                mapping[step_idx] = cached.logical_id
        else:
            # Only add to resolve list if not already added
            if key not in [item.get("key") for item in to_resolve]:
                to_resolve.append({
                    "key": f"{t}|{d}",
                    "type": t, 
                    "domain": d,
                    "preferred_logical_id": step.get("organ_hint")  # Forward hints
                })

    if not to_resolve:
        return mapping, None  # all from cache

    # 2) Remote bulk resolve
    start_time = time.time()
    new_epoch = None
    try:
        # Clamp bulk resolve timeout (allow more time for bulk operations)
        bulk_timeout = min(0.1, organism_client.timeout)  # 100ms max for bulk
        resp = await organism_client.post(
            "/resolve-routes",
            json={"tasks": to_resolve},
            headers=_corr_headers("organism", cid),
            timeout=bulk_timeout
        )
        
        # Track bulk resolve metrics
        latency_ms = (time.time() - start_time) * 1000
        if metrics:
            metrics.increment_counter("bulk_resolve_items", value=len(to_resolve))
        logger.info(f"[Coordinator] Bulk resolve completed: {len(to_resolve)} items in {latency_ms:.1f}ms")
        # resp: { epoch, results: [ {key, logical_id, status, ...}, ... ] }
        new_epoch = resp.get("epoch")
        if new_epoch and last_seen_epoch and new_epoch != last_seen_epoch:
            # epoch rotated => flush stale cache
            route_cache.clear()
        
        # Create mapping from key to result
        key_to_result = {}
        for r in resp.get("results", []):
            key = r.get("key")
            if key:
                key_to_result[key] = r

        # Fan-out results to all indices with matching (type, domain)
        for item in to_resolve:
            key = item["key"]
            result = key_to_result.get(key, {})
            status = result.get("status", "error")
            
            if status == "ok" and result.get("logical_id"):
                logical_id = result["logical_id"]
                # Parse key back to (type, domain)
                t, d = key.split("|", 1)
                d = d if d else None
                
                # Backfill cache
                route_cache.set((t, d), RouteEntry(
                    logical_id=logical_id,
                    epoch=result.get("epoch", new_epoch or ""),
                    resolved_from=result.get("resolved_from", "bulk"),
                    instance_id=result.get("instance_id"),
                    cached_at=time.time()
                ))
                
                # Apply to all indices with this (type, domain)
                for step_idx in pairs[(t, d)]:
                    mapping[step_idx] = logical_id
            else:
                # Fallback for this (type, domain) pair
                t, d = key.split("|", 1)
                d = d if d else None
                logical_id = static_route_fallback_func(t, d)
                for step_idx in pairs[(t, d)]:
                    mapping[step_idx] = logical_id
                    
        return mapping, new_epoch

    except Exception as e:
        # Complete fallback: local rules for all unresolved
        if metrics:
            metrics.increment_counter("bulk_resolve_failed_items", value=len(to_resolve))
        logger.warning(f"[Coordinator] Bulk route resolution failed, using fallback: {e}")
        for item in to_resolve:
            t, d = item["key"].split("|", 1)
            d = d if d else None
            logical_id = static_route_fallback_func(t, d)
            for step_idx in pairs[(t, d)]:
                mapping[step_idx] = logical_id
        return mapping, None


def resolve_route_cached(task_type: str, domain: Optional[str], route_cache: Any) -> Optional[str]:
    """
    Resolve route for a single task type/domain pair with caching.
    
    Args:
        task_type: Normalized task type
        domain: Normalized domain (can be None)
        route_cache: Route cache instance
        
    Returns:
        Cached route if available, None otherwise
    """
    return get_cached_route(task_type, domain, route_cache)


async def resolve_route_cached_async(
    task_type: str,
    domain: Optional[str],
    *,
    route_cache: "RouteCache",
    normalize_func: Callable[[Optional[str]], Optional[str]],
    static_route_fallback_func: Callable[[str, Optional[str]], str],
    organism_client: BaseServiceClient,
    routing_remote_enabled: bool,
    routing_remote_types: set,
    preferred_logical_id: Optional[str] = None,
    cid: Optional[str] = None,
    metrics: Optional[Any] = None,
    last_seen_epoch: Optional[str] = None,
) -> str:
    """
    Resolve route with caching and single-flight.
    
    This is the primary async route resolution function that:
    1. Checks cache first
    2. Uses single-flight to prevent dogpiling
    3. Calls organism service for remote resolution
    4. Falls back to static rules if needed
    5. Tracks metrics and epoch changes
    
    Args:
        task_type: Task type string
        domain: Domain string (optional)
        route_cache: RouteCache instance
        normalize_func: Function to normalize task type
        static_route_fallback_func: Function for static fallback routing
        organism_client: BaseServiceClient instance for HTTP calls to organism service
        routing_remote_enabled: Feature flag for remote routing
        routing_remote_types: Set of task types that should use remote routing
        preferred_logical_id: Optional preferred logical ID hint
        cid: Correlation ID
        metrics: Optional metrics tracker
        last_seen_epoch: Last seen epoch for cache invalidation
        
    Returns:
        Logical ID string (route identifier)
    """
    t = normalize_func(task_type)
    d = normalize_func(domain)
    key = (t, d)

    # Check feature flag
    if not routing_remote_enabled or t not in routing_remote_types:
        return static_route_fallback_func(t, d)

    # 1) Try cache
    cached = route_cache.get(key)
    if cached:
        if metrics:
            metrics.increment_counter("route_cache_hit_total")
        logger.info(f"[Coordinator] Route cache hit for ({t}, {d}): {cached.logical_id} from={cached.resolved_from} epoch={cached.epoch}")
        return cached.logical_id

    # 2) Single-flight: if another coroutine is already resolving this key, await it
    async for (fut, is_leader) in route_cache.singleflight(key):
        # double-check cache after acquiring the singleflight slot
        cached = route_cache.get(key)
        if cached:
            if is_leader and not fut.done():
                fut.set_result(cached.logical_id)
            return cached.logical_id

        # 3) Remote resolve (primary)
        start_time = time.time()
        try:
            payload = {"task": {"type": t, "domain": d, "params": {}}}
            if preferred_logical_id:
                payload["preferred_logical_id"] = preferred_logical_id

            # Clamp resolve timeout to keep fast-path SLO (30-50ms budget)
            resolve_timeout = min(0.05, organism_client.timeout)  # 50ms max
            resp = await organism_client.post(
                "/resolve-route", json=payload,
                headers=_corr_headers("organism", cid or uuid.uuid4().hex),
                timeout=resolve_timeout
            )
            # Expected response: { logical_id, resolved_from, epoch, instance_id? }
            # CONTRACT: logical_id is required for execution; instance_id is telemetry only
            # Execution uses logical_id and Organism chooses healthy instance at call time
            logical_id = resp["logical_id"] if "logical_id" in resp else resp.get("organ_id")
            epoch = resp.get("epoch", "")
            resolved_from = resp.get("resolved_from", "unknown")
            instance_id = resp.get("instance_id")  # Telemetry only - don't pin instances

            # Track metrics
            latency_ms = (time.time() - start_time) * 1000
            if metrics:
                metrics.increment_counter("route_remote_total")
                metrics.append_latency("route_remote_latency_ms", latency_ms)

            entry = RouteEntry(logical_id=logical_id, epoch=epoch,
                             resolved_from=resolved_from, instance_id=instance_id,
                             cached_at=time.time())
            route_cache.set(key, entry)

            # Optional epoch-aware invalidation: if epoch changes suddenly, clear cache
            if last_seen_epoch and epoch and epoch != last_seen_epoch:
                # Epoch rotated; keep the new entry but clear older keys
                route_cache.clear()
            # Note: epoch should be tracked by caller (last_seen_epoch should be updated)

            logger.info(f"[Coordinator] Route resolved for ({t}, {d}): {logical_id} from={resolved_from} epoch={epoch} latency={latency_ms:.1f}ms")
            if is_leader and not fut.done():
                fut.set_result(logical_id)
            return logical_id

        except Exception as e:
            # 4) Fallback: use static defaults
            if metrics:
                metrics.increment_counter("route_remote_fail_total")
            logical_id = static_route_fallback_func(t, d)
            # Always complete the future - either with result or exception
            if is_leader and not fut.done():
                fut.set_result(logical_id)
            logger.warning(f"[Coordinator] Route resolution failed for ({t}, {d}), using fallback: {e}")
            return logical_id


def static_route_fallback(task_type: str, domain: Optional[str]) -> str:
    """
    Static route fallback when organism is unavailable.
    
    This implements fallback routing using static rules when the organism service
    is unavailable. It checks domain-specific rules first, then type-based rules.
    
    Args:
        task_type: Normalized task type
        domain: Normalized domain (can be None)
        
    Returns:
        Static route identifier (logical_id)
    """
    t = (task_type or "").strip().lower()
    d = (domain or "").strip().lower()
    
    # Domain-specific overrides (restore any domain-specific rules that were removed)
    STATIC_DOMAIN_RULES = {
        # Add any domain-specific overrides here
        # Example: ("execute", "robot_arm"): "actuator_organ_2",
        # Example: ("graph_rag_query", "facts"): "graph_dispatcher",
    }
    
    # Check domain-specific rules first
    if (t, d) in STATIC_DOMAIN_RULES:
        return STATIC_DOMAIN_RULES[(t, d)]
    
    # Generic task type rules
    if t in ["general_query", "health_check", "fact_search", "fact_store",
            "artifact_manage", "capability_manage", "memory_cell_manage",
            "model_manage", "policy_manage", "service_manage", "skill_manage"]:
        return "utility_organ_1"
    if t == "execute":
        return "actuator_organ_1"
    if t in ["graph_embed", "graph_rag_query", "graph_embed_v2", "graph_rag_query_v2",
            "graph_sync_nodes", "graph_fact_embed", "graph_fact_query"]:
        return "graph_dispatcher"
    return "utility_organ_1"  # Ultimate fallback
