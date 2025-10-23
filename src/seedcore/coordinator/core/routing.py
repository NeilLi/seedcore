"""Core routing functionality for bulk route resolution and cache management."""

import time
import asyncio
import random
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Callable, Tuple, NamedTuple, Literal

logger = logging.getLogger(__name__)


class RouteEntry(NamedTuple):
    """Cached route entry with metadata."""
    logical_id: str
    epoch: str
    resolved_from: Literal['cache', 'bulk', 'fallback']
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

    @asynccontextmanager
    async def singleflight(self, key: Tuple[str, Optional[str]]):
        """Async single-flight: the first caller becomes leader and returns (future, True).
        Followers get the same future and (future, False). Leader must set result/exception."""
        async with self._lock:
            fut = self._inflight.get(key)
            is_leader = False
            if fut is None:
                fut = asyncio.get_event_loop().create_future()
                self._inflight[key] = fut
                is_leader = True
        try:
            yield fut, is_leader
            # NOTE: the leader must call fut.set_result(value) or fut.set_exception(err)
        finally:
            # Ensure cleanup only once; if leader failed to resolve, cancel to unblock followers.
            if is_leader:
                if not fut.done():
                    fut.cancel()
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


def bulk_resolve_routes_cached(
    steps: List[Dict[str, Any]], 
    cid: str,
    route_cache: "RouteCache",
    resolve_func: Callable[[List[Dict[str, Any]]], Dict[str, Any]],
    organism_client: Any,
    static_route_fallback: Callable[[str, Optional[str]], str]
) -> Dict[int, str]:
    """
    Given HGNN steps (each has step['task'] with type/domain),
    return a mapping: { step_index -> logical_id }.
    De-duplicates (type, domain) pairs to minimize network calls.
    
    Args:
        steps: List of HGNN steps
        cid: Correlation ID
        route_cache: Route cache instance
        resolve_func: Function to resolve routes via HTTP
        organism_client: Organism client for fallback
        static_route_fallback: Static routing fallback function
        
    Returns:
        Mapping of step index to logical ID
    """
    mapping: Dict[int, str] = {}
    pairs: Dict[Tuple[str, Optional[str]], List[int]] = {}
    to_resolve: List[Dict[str, Any]] = []

    # 1) Group and apply cache hits
    for idx, step in enumerate(steps):
        subtask = step.get("task") or {}
        t = subtask.get("type")
        d = subtask.get("domain")
        pair = _norm_pair(t, d)
        if not pair[0]:
            continue  # executor will fallback for missing type
        pairs.setdefault(pair, []).append(idx)

        cached = route_cache.get(pair)
        if cached:
            for j in pairs[pair]:
                mapping[j] = cached.logical_id
        else:
            to_resolve.append({"key": _pair_key(pair), "type": pair[0], "domain": pair[1], "cid": cid})

    if not to_resolve:
        return mapping

    # 2) Bulk resolve
    start = time.time()
    try:
        resp = resolve_func(to_resolve)  # expected: {"epoch": "...", "results": [ {...}, ... ]}
    except Exception as e:
        logger.exception("[Coordinator] bulk resolve failed; falling back per-item")
        resp = {"epoch": None, "results": []}

    # 3) Epoch rotation handling
    epoch = resp.get("epoch")
    if epoch:
        # If the server signals a new epoch value that differs from cached entries' epoch,
        # consider a targeted flush (this example fully clears for simplicity).
        route_cache.clear()

    res_by_key = {r.get("key"): r for r in resp.get("results", []) if r.get("key")}

    # 4) Fan-out and fallback per pair
    for pair, idxs in pairs.items():
        if all(i in mapping for i in idxs):
            continue  # already filled from cache
        k = _pair_key(pair)
        r = res_by_key.get(k) or {}
        status = r.get("status", "error")
        logical = r.get("logical_id")

        if status == "ok" and logical:
            entry = RouteEntry(logical_id=logical, epoch=(epoch or ""), resolved_from="bulk")
            route_cache.set(pair, entry)
            for j in idxs:
                mapping[j] = logical
            continue

        # Fallback: organism client
        logical_fallback = None
        try:
            if organism_client is not None and hasattr(organism_client, 'resolve'):
                logical_fallback = organism_client.resolve(pair[0], pair[1], cid=cid)
        except Exception as e:
            logger.debug("[Coordinator] organism fallback failed for %s: %s", pair, e)

        if not logical_fallback:
            logical_fallback = static_route_fallback(pair[0], pair[1])

        entry = RouteEntry(logical_id=logical_fallback, epoch=(epoch or ""), resolved_from="fallback")
        route_cache.set(pair, entry)
        for j in idxs:
            mapping[j] = logical_fallback

    latency_ms = (time.time() - start) * 1000
    logger.info("[Coordinator] bulk mapped %d pairs (%d steps) in %.1fms", len(pairs), len(steps), latency_ms)
    return mapping


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


def static_route_fallback(task_type: str, domain: Optional[str]) -> str:
    """
    Static route fallback when organism is unavailable.
    
    Args:
        task_type: Normalized task type
        domain: Normalized domain (can be None)
        
    Returns:
        Static route identifier
    """
    t = (task_type or "").strip().lower()
    d = (domain or "").strip().lower()

    # Domain-based routing (higher priority)
    domain_rules = {
        "payments": "payments",
        "billing": "billing", 
        "checkout": "checkout",
        "search": "search",
        "catalog": "catalog",
        "recommendations": "recommendations",
        "fraud": "fraud",
        "support": "support",
        "operations": "operations",
        "maintenance": "maintenance",
        "security": "security",
        "food_service": "food_service",
        "housekeeping": "housekeeping",
        "concierge": "concierge",
        "guest_experience": "guest_experience",
        "guest_relations": "guest_relations",
        "hospitality": "hospitality_service",
        "customer_service": "customer_service"
    }
    if d in domain_rules:
        return domain_rules[d]

    # Type-based routing
    type_rules = {
        "anomaly_triage": "cognitive",
        "execute": "organism",
        "graph_fact_embed": "graph",
        "graph_fact_query": "graph",
        "graph_embed": "graph",
        "graph_rag_query": "graph",
        "graph_embed_v2": "graph",
        "graph_rag_query_v2": "graph",
        "artifact_manage": "storage",
        "capability_manage": "registry",
        "memory_cell_manage": "memory",
        "model_manage": "ml",
        "policy_manage": "policy",
        "service_manage": "service",
        "skill_manage": "skill"
    }
    if t in type_rules:
        return type_rules[t]

    # Generic type defaults
    type_defaults = {
        "retrieval": "search",
        "ranking": "recommendations", 
        "generation": "support",
        "routing": "operations",
        "orchestration": "operations",
    }
    if t in type_defaults:
        return type_defaults[t]

    # Default fallback
    return "default"
