from __future__ import annotations

import os
import traceback
import json
import gc
import asyncio
import logging
import contextlib
import random
import time
import datetime
from typing import Any, Dict, List, Optional, Tuple

import ray
from ray import serve
from pydantic import BaseModel, field_validator, Field
from prometheus_client import Counter, Gauge, CollectorRegistry
try:
    import psutil  # for RSS telemetry if available
except Exception:
    psutil = None

from seedcore.logging_setup import ensure_serve_logger
from seedcore.models import TaskPayload
from seedcore.dispatcher.router import RouterFactory, Router

logger = ensure_serve_logger("seedcore.dispatchers", level="DEBUG")

# --------- JSON (fast path if orjson is present) ----------
try:
    import orjson  # type: ignore
    def _dumps(obj: Any) -> str:
        return orjson.dumps(obj, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode("utf-8")
except Exception:  # pragma: no cover
    def _dumps(obj: Any) -> str:
        return json.dumps(obj, default=str)

#
# ---- Observability metrics ----
#
# Note: Metrics are now created inside the Dispatcher class with a per-actor registry
# to avoid default-registry growth across restarts in the same worker process.

# --------- ENV / Defaults ----------
PG_DSN               = os.getenv("PG_DSN") or os.getenv("SEEDCORE_PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore")
AGENT_NAMESPACE      = os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev"))

DISPATCHER_COUNT     = int(os.getenv("DISPATCHER_COUNT", "2"))
CLAIM_BATCH_SIZE     = int(os.getenv("CLAIM_BATCH_SIZE", "8"))
MAX_CONCURRENCY      = int(os.getenv("DISPATCHER_CONCURRENCY", "16"))
EMPTY_SLEEP_SECONDS  = float(os.getenv("EMPTY_SLEEP_SECONDS", "0.05"))
LEASE_SECONDS        = int(os.getenv("LEASE_SECONDS", "90"))
USE_LISTEN_NOTIFY    = os.getenv("USE_LISTEN_NOTIFY", "0") == "1"
NOTIFY_CHANNEL       = os.getenv("TASKS_NOTIFY_CHANNEL", "tasks_new")
WATCHDOG_INTERVAL    = int(os.getenv("WATCHDOG_INTERVAL", "30"))  # seconds
MEMORY_SOFT_LIMIT_MB = int(os.getenv("DISPATCHER_MEMORY_SOFT_LIMIT_MB", "0"))  # 0 disables
FORCE_GC_EVERY_N     = int(os.getenv("DISPATCHER_FORCE_GC_EVERY_N", "2000"))
RECYCLE_AFTER_TASKS  = int(os.getenv("DISPATCHER_RECYCLE_AFTER_TASKS", "0"))  # 0 disables recycling
RESULT_MAX_BYTES     = int(os.getenv("DISPATCHER_RESULT_MAX_BYTES", "0"))     # 0 disables truncation
ASYNC_PG_STMT_CACHE  = int(os.getenv("ASYNC_PG_STATEMENT_CACHE", "128"))
ASYNC_PG_IDLE_LIFETIME = float(os.getenv("ASYNC_PG_IDLE_LIFETIME_S", "300"))

# Router configuration
DISPATCHER_ROUTER_TYPE = os.getenv("DISPATCHER_ROUTER_TYPE", "coordinator_http")

# Task lease and stale recovery configuration
TASK_STALE_S   = int(os.getenv("TASK_STALE_S", "900"))   # 15m default
MAX_REQUEUE    = int(os.getenv("TASK_MAX_REQUEUE", "3")) # cap retries
REAP_BATCH     = int(os.getenv("TASK_REAP_BATCH", "200"))
RUN_LEASE_S    = int(os.getenv("TASK_LEASE_S", "600"))   # 10m default

# --------- SQL (asyncpg-style $1 params) ----------
# Exclude all graph task types handled by GraphDispatcher
GRAPH_TASK_TYPES_EXCLUSION = (
    'graph_embed', 'graph_rag_query', 'graph_embed_v2', 'graph_rag_query_v2',
    'graph_fact_embed', 'graph_fact_query', 'nim_task_embed', 'graph_sync_nodes'
)
CLAIM_BATCH_SQL = f"""
WITH c AS (
  SELECT id
  FROM tasks
  WHERE status IN ('queued','retry')
    AND (run_after IS NULL OR run_after <= NOW())
    AND NOT (type = ANY($3::text[]))  -- Exclude graph tasks (handled by GraphDispatcher)
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $1
)
UPDATE tasks t
SET status='running',
    locked_by=$2,
    locked_at=NOW(),
    owner_id=$2,
    lease_expires_at = NOW() + ({RUN_LEASE_S} || ' seconds')::interval,
    last_heartbeat = NOW(),
    attempts = t.attempts + 1
FROM c
WHERE t.id = c.id
RETURNING t.id, t.type, t.description, t.params, t.domain, t.drift_score, t.attempts;
"""

COMPLETE_SQL = """
UPDATE tasks
SET status='completed', result=$1::jsonb, error=NULL, updated_at=NOW()
WHERE id=$2
"""

FAIL_SQL = """
UPDATE tasks
SET status='failed', error=$1, updated_at=NOW()
WHERE id=$2
"""

RETRY_SQL = """
UPDATE tasks
SET status='retry',
    error=$1,
    run_after = NOW() + ($2 || ' seconds')::interval,
    updated_at=NOW()
WHERE id=$3
"""

REAP_STUCK_SQL = """
UPDATE tasks
SET status='retry',
    run_after = NOW() + INTERVAL '15 seconds',
    owner_id = NULL,
    lease_expires_at = NULL,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE status='running'
  AND attempts < $2
  AND (
        (lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
        OR
        (last_heartbeat IS NOT NULL AND last_heartbeat < NOW() - ($1 || ' seconds')::interval)
      )
RETURNING id, locked_by
"""

REAP_FAILED_SQL = """
UPDATE tasks
SET status='failed',
    error = COALESCE(error,'') || ' | watchdog: attempts exceeded',
    owner_id = NULL,
    lease_expires_at = NULL,
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE status='running'
  AND attempts >= $2
  AND (
        (lease_expires_at IS NOT NULL AND lease_expires_at < NOW())
        OR
        (last_heartbeat IS NOT NULL AND last_heartbeat < NOW() - ($1 || ' seconds')::interval)
      )
RETURNING id, locked_by
"""

CHECK_DUPLICATE_SQL = """
SELECT id
FROM tasks
WHERE status IN ('queued', 'running', 'retry')
  AND type = $1
  AND description = $2
  AND params = $3
  AND domain = $4
  AND created_at > NOW() - INTERVAL '1 hour'
ORDER BY created_at DESC
LIMIT 1
"""

# ------------- Dispatcher (PG -> OrganismManager Serve Deployment -> PG) -------------

@ray.remote(lifetime="detached", num_cpus=0.1, namespace=AGENT_NAMESPACE)
class Dispatcher:
    def __init__(self, dsn: str, name: str):
        self.dsn = dsn
        self.name = name
        self.pool = None
        self.sema = asyncio.Semaphore(MAX_CONCURRENCY)
        self._stop = asyncio.Event()
        self._next_watchdog_ts = 0.0
        # record last pool creation error for diagnostics
        self._last_pool_error: Optional[str] = None
        self._tasks_since_gc = 0
        self._tasks_total = 0
        self._proc = psutil.Process() if psutil is not None else None
        self._last_pool_log = 0.0
        self._last_mem_check = 0.0
        # Track inflight tasks manually for safer metrics (avoid accessing private semaphore attributes)
        self._inflight_count = 0
        # Router for task execution (replaces direct Serve handle)
        self.router: Optional[Router] = None
        # Flag to only log free_size unavailability once
        self._free_size_warning_logged = False
        
        # --- Prometheus per-actor registry to prevent default REGISTRY growth ---
        self._metrics_registry = CollectorRegistry(auto_describe=True)
        # counters
        self.tasks_claimed = Counter(
            "seedcore_tasks_claimed_total",
            "Number of tasks claimed from DB",
            registry=self._metrics_registry,
        )
        self.tasks_completed = Counter(
            "seedcore_tasks_completed_total",
            "Number of tasks successfully completed",
            registry=self._metrics_registry,
        )
        self.tasks_failed = Counter(
            "seedcore_tasks_failed_total",
            "Number of tasks permanently failed",
            registry=self._metrics_registry,
        )
        self.tasks_retried = Counter(
            "seedcore_tasks_retried_total",
            "Number of tasks marked for retry",
            registry=self._metrics_registry,
        )
        # gauges
        self.dispatcher_inflight = Gauge(
            "seedcore_dispatcher_inflight",
            "Current inflight tasks per dispatcher",
            ["dispatcher"],
            registry=self._metrics_registry,
        )
        self.process_rss_bytes = Gauge(
            "seedcore_dispatcher_process_rss_bytes",
            "Dispatcher process resident set size (bytes)",
            ["dispatcher"],
            registry=self._metrics_registry,
        )
        # cache labeled gauge child
        self._g_inflight = self.dispatcher_inflight.labels(self.name)
        self._g_rss = self.process_rss_bytes.labels(self.name)

    def _is_pool_closed(self) -> bool:
        """Check if pool is closed - handle asyncpg version compatibility."""
        if not self.pool:
            return True
        
        try:
            # asyncpg 0.29.0+ has is_closed method
            return self.pool.is_closed()
        except AttributeError:
            # Fallback for older versions - check if pool is accessible
            try:
                # Try to get a basic pool attribute to see if it's working
                _ = self.pool.get_size()
                return False
            except Exception:
                return True
        except Exception:
            return True

    async def _create_pool(self, min_size=1, max_size=4):
        """Unified pool creation with consistent tuning parameters."""
        import asyncpg
        return await asyncpg.create_pool(
            dsn=self.dsn,
            min_size=min_size,
            max_size=max_size,
            max_inactive_connection_lifetime=ASYNC_PG_IDLE_LIFETIME,
            statement_cache_size=ASYNC_PG_STMT_CACHE,
            command_timeout=60.0,
        )

    async def _ensure_pool(self):
        if self.pool is None:
            try:
                # Tighten memory behavior of asyncpg:
                #  - bounded statement cache (to avoid growth if queries vary)
                #  - finite idle lifetime (reap idle connections)
                #  - command timeout prevents stuck connections
                self.pool = await self._create_pool(min_size=1, max_size=max(4, MAX_CONCURRENCY))
                logger.info(f"Dispatcher {self.name}: Created connection pool with max_size={max(4, MAX_CONCURRENCY)}")
                self._last_pool_error = None
            except Exception as e:
                logger.error(f"Dispatcher {self.name}: Failed to create connection pool: {e}")
                try:
                    self._last_pool_error = f"{e.__class__.__name__}: {e}"
                except Exception:
                    self._last_pool_error = str(e)
                raise
        elif self._is_pool_closed():
            logger.warning(f"Dispatcher {self.name}: Connection pool was closed, recreating...")
            self.pool = None
            await self._ensure_pool()

    async def _ensure_router(self):
        """Initialize router if not already created."""
        if self.router is None:
            try:
                logger.info(f"Dispatcher {self.name}: Creating router of type {DISPATCHER_ROUTER_TYPE}")
                self.router = RouterFactory.create_router(DISPATCHER_ROUTER_TYPE)
                logger.info(f"Dispatcher {self.name}: Created router of type {DISPATCHER_ROUTER_TYPE}")
                
                # Log router details for debugging
                if hasattr(self.router, 'client') and hasattr(self.router.client, 'base_url'):
                    logger.info(f"Dispatcher {self.name}: Router base_url: {self.router.client.base_url}")
                if hasattr(self.router, 'config'):
                    logger.info(f"Dispatcher {self.name}: Router config: {self.router.config}")
                    
            except Exception as e:
                logger.error(f"Dispatcher {self.name}: Failed to create router: {e}")
                logger.error(f"Dispatcher {self.name}: Router type: {DISPATCHER_ROUTER_TYPE}")
                logger.error(f"Dispatcher {self.name}: Exception type: {type(e)}")
                logger.error(f"Dispatcher {self.name}: Exception traceback:", exc_info=True)
                raise

    async def _monitor_pool_health(self):
        """Monitor connection pool health to detect potential leaks."""
        if self.pool:
            try:
                # Get pool statistics
                pool_stats = {
                    "min_size": self.pool.get_min_size(),
                    "max_size": self.pool.get_max_size(),
                    "size": self.pool.get_size(),
                }
                
                # Try to get free size if available (not available in asyncpg >= 0.30)
                try:
                    free_size = self.pool.get_free_size()
                    pool_stats["free_size"] = free_size
                    
                    # Log warning if pool is getting full
                    if free_size == 0:
                        logger.warning(f"🚨 Dispatcher {self.name}: Connection pool is full! size={pool_stats['size']}, max_size={pool_stats['max_size']}")
                    elif free_size <= 1:
                        logger.warning(f"⚠️ Dispatcher {self.name}: Connection pool nearly full! free_size={free_size}, size={pool_stats['size']}")
                except AttributeError:
                    # free_size not available in newer asyncpg versions
                    pool_stats["free_size"] = "unavailable"
                    if not self._free_size_warning_logged:
                        logger.debug(f"ℹ️ Dispatcher {self.name}: free_size not available in this asyncpg version")
                        self._free_size_warning_logged = True
                except Exception as e:
                    pool_stats["free_size"] = f"error: {e}"
                    logger.debug(f"ℹ️ Dispatcher {self.name}: free_size check failed: {e}")
                
                # Log pool stats periodically for debugging (every 5 minutes)
                now = time.monotonic()
                if now - self._last_pool_log > 300.0:
                    logger.info(f"📊 Dispatcher {self.name}: Pool stats - {pool_stats}")
                    self._last_pool_log = now

                # Memory telemetry (RSS) if psutil is available
                if self._proc is not None:
                    try:
                        rss = float(self._proc.memory_info().rss)
                        self._g_rss.set(rss)
                    except Exception:
                        pass

                # Soft memory guard (checked at most every 3s)
                if MEMORY_SOFT_LIMIT_MB > 0 and (now - self._last_mem_check) > 3.0:
                    self._last_mem_check = now
                    
            except Exception as e:
                logger.error(f"Failed to monitor pool health: {e}")

    # --- NEW: explicit warmup/ready probes so bootstrap can block until DB is ready ---
    async def warmup(self) -> Dict[str, Any]:
        """
        Ensure the DB pool and router exist; return status dict (never raises to caller).
        Useful for synchronous readiness gating before starting run().
        """
        try:
            await self._ensure_pool()
            await self._ensure_router()
        except Exception:
            # _last_pool_error already set in _ensure_pool
            pass
        return await self.status_async()

    async def ready(self, timeout_s: float = 20.0, interval_s: float = 0.5) -> bool:
        """
        Poll until pool and router are created or timeout. Returns True if ready, False otherwise.
        """
        deadline = time.monotonic() + max(0.1, timeout_s)
        while time.monotonic() < deadline:
            try:
                await self._ensure_pool()
                await self._ensure_router()
                return True
            except Exception:
                await asyncio.sleep(interval_s)
        return False

    async def status_async(self) -> Dict[str, Any]:
        """Async version to safely read pool stats after warmup/ensure."""
        _ = None
        if self.pool:
            # acquiring/releasing a conn validates pool liveness cheaply
            async with self.pool.acquire() as _:
                pass
        return self.get_status()

    async def _claim_batch(self, con) -> List[Dict[str, Any]]:
        """Claim tasks, skipping true duplicates but preserving legitimate retries."""
        rows = await con.fetch(CLAIM_BATCH_SQL, CLAIM_BATCH_SIZE, self.name, list(GRAPH_TASK_TYPES_EXCLUSION))
        batch = []
        seen = set()

        for r in rows:
            key = (
                r["type"] or "",
                r["description"] or "",
                json.dumps(r["params"] or {}, sort_keys=True, separators=(",", ":")),
                r["domain"] or "",
            )
            if key in seen:
                # Cancel duplicate only within the same claim batch (not across retries)
                await con.execute("""
                    UPDATE tasks
                    SET status='cancelled',
                        error='Duplicate task cancelled in same batch',
                        updated_at=NOW()
                    WHERE id=$1
                """, r["id"])
                logger.info("🔄 Cancelled in-batch duplicate task %s (type=%s)", r["id"], r["type"])
                continue
            seen.add(key)
            batch.append({
                "id": r["id"],
                "type": r["type"],
                "description": r["description"],
                "params": r["params"] or {},
                "domain": r["domain"],
                "drift_score": float(r["drift_score"] or 0.0),
                "attempts": int(r["attempts"] or 0),
            })

        if batch:
            self.tasks_claimed.inc(len(batch))
            # Log all claimed tasks with their IDs
            task_ids = [str(task["id"]) for task in batch]
            logger.info(f"[QueueDispatcher] 📦 Claimed batch of {len(batch)} tasks: {task_ids}")
            logger.info(f"[QueueDispatcher] 🎯 Task IDs: {', '.join(task_ids)}")
        return batch

    async def _renew_task_lease(self, con, task_id: str):
        """Renew the lease for a running task."""
        try:
            await con.execute("""
                UPDATE tasks
                SET lease_expires_at = NOW() + ($1 || ' seconds')::interval,
                    last_heartbeat = NOW(),
                    updated_at = NOW()
                WHERE id = $2
                  AND status = 'running'
                  AND owner_id = $3
            """, str(RUN_LEASE_S), task_id, self.name)
            logger.debug(f"[QueueDispatcher] Renewed lease for task {task_id}")
        except Exception as e:
            logger.warning(f"[QueueDispatcher] Failed to renew lease for task {task_id}: {e}")

    async def _recover_mine(self):
        """Recover any RUNNING tasks owned by this dispatcher on startup."""
        try:
            async with self.pool.acquire() as con:
                result = await con.execute("""
                    UPDATE tasks
                    SET status = 'queued',
                        owner_id = NULL,
                        lease_expires_at = NULL,
                        updated_at = NOW(),
                        error = COALESCE(error,'') || ' | recovered on owner restart'
                    WHERE status = 'running'
                      AND owner_id = $1
                      AND (last_heartbeat IS NULL OR last_heartbeat < NOW() - INTERVAL '2 minutes')
                """, self.name)
                if result != "UPDATE 0":
                    logger.info(f"[QueueDispatcher] Recovered {result} tasks owned by {self.name} on startup")
        except Exception as e:
            logger.warning(f"[QueueDispatcher] Failed to recover tasks for {self.name}: {e}")

    # TaskPayload is now imported from centralized models

    async def _process_one(self, item: Dict[str, Any]):
        """Bounded-concurrency task runner for a single task."""
        async with self.sema:
            # Track inflight tasks manually
            self._inflight_count += 1
            # update inflight gauge
            try:
                self._g_inflight.set(self._inflight_count)
            except Exception:
                pass
            
            # Memory management: increment task counters
            self._tasks_total += 1
            self._tasks_since_gc += 1
            tid = item["id"]
            
            # Force logging task_id early with comprehensive info
            logger.info(f"[QueueDispatcher] 🚀 Processing task {tid} (type={item['type']}, domain={item['domain']}, attempts={item.get('attempts', 0)})")
            logger.info(f"[QueueDispatcher] 📋 Task ID: {tid} | Type: {item['type']} | Domain: {item['domain']} | Attempts: {item.get('attempts', 0)}")
            logger.info(f"[QueueDispatcher] 🔍 Raw item data: {item}")
            logger.info(f"[QueueDispatcher] 🔍 Item types: params={type(item.get('params'))}, domain={type(item.get('domain'))}")
            
            task_row = {**item, "id": tid}
            payload = TaskPayload.from_db(task_row)
            logger.info(f"[QueueDispatcher] ✅ Task payload created for {tid}: {payload.model_dump()}")
            logger.info(f"[QueueDispatcher] 🔧 Router type: {type(self.router)}")
            
            try:
                # Start lease renewal task for long-running tasks
                lease_renewal_task = None
                try:
                    # Create a background task to renew the lease every 30 seconds
                    async def renew_lease_periodically():
                        while not self._stop.is_set():
                            try:
                                await asyncio.sleep(30)  # Renew every 30 seconds
                                if self._stop.is_set():
                                    break
                                async with self.pool.acquire() as con:
                                    await self._renew_task_lease(con, tid)
                            except Exception as e:
                                logger.debug(f"Lease renewal failed for task {tid}: {e}")
                                break
                    
                    lease_renewal_task = asyncio.create_task(renew_lease_periodically())
                except Exception as e:
                    logger.debug(f"Failed to start lease renewal for task {tid}: {e}")

                # Ensure router is available
                await self._ensure_router()
                
                # Route and execute task using router interface
                logger.info(f"[QueueDispatcher] 📤 About to route task {tid} via router")
                logger.info(f"[QueueDispatcher] 🎯 Task ID: {tid} | Executing task type: {item['type']}")
                logger.info(f"[QueueDispatcher] 📋 Task payload: {payload.dict()}")
                logger.info(f"[QueueDispatcher] 🔧 Router: {self.router}")
                
                try:
                    # Add timeout to prevent hanging on router calls
                    CALL_TIMEOUT_S = int(os.getenv("SERVE_CALL_TIMEOUT_S", "120"))
                    logger.info(f"[QueueDispatcher] 🚀 Calling router.route_and_execute() for task {tid} (timeout={CALL_TIMEOUT_S}s)")
                    
                    result: Dict[str, Any] = await asyncio.wait_for(
                        self.router.route_and_execute(payload, correlation_id=str(tid)), 
                        timeout=CALL_TIMEOUT_S
                    )
                    logger.info(f"[QueueDispatcher] ✅ Received result from router for task {tid}: {result}")
                    
                except asyncio.TimeoutError:
                    logger.warning(f"[QueueDispatcher] ⏰ Router call timeout for task {tid} after {CALL_TIMEOUT_S}s")
                    # Mark as RETRY with backoff, exit cleanly; do NOT stall the loop
                    async with self.pool.acquire() as conw:
                        delay = min(10 * (2 ** item["attempts"]), 300)
                        await conw.execute(RETRY_SQL, "dispatcher: router call timeout", str(delay), tid)
                        logger.info(f"[QueueDispatcher] 🔄 Task {tid} marked for retry due to timeout (delay={delay}s)")
                        self.tasks_retried.inc()
                    return
                    
                except Exception as e:
                    logger.error(f"[QueueDispatcher] ❌ Failed to get result from router for task {tid}: {e}")
                    logger.error(f"[QueueDispatcher] 🔧 Exception type: {type(e)}")
                    logger.error(f"[QueueDispatcher] 📋 Exception details: {str(e)}")
                    logger.error(f"[QueueDispatcher] 🔧 Router type: {type(self.router)}")
                    logger.error(f"[QueueDispatcher] 🔧 Router config: {getattr(self.router, 'config', 'No config')}")
                    logger.error(f"[QueueDispatcher] 🔧 Router base_url: {getattr(self.router, 'client', {}).get('base_url', 'No base_url') if hasattr(self.router, 'client') else 'No client'}")
                    logger.error(f"[QueueDispatcher] 🔧 Exception traceback:", exc_info=True)
                    raise

                # Persist results via pooled connection
                async with self.pool.acquire() as conw:
                    if result.get("success"):
                        # Task completed successfully
                        # FIX: The coordinator returns a unified result envelope directly
                        # It has {kind, payload, success, version, metadata, created_at}
                        # We should persist the entire envelope, not try to extract result.get("result")
                        result_data = result
                        
                        # CRITICAL GUARD: Ensure result_data is not None and is a dict
                        if result_data is None or not isinstance(result_data, dict):
                            logger.warning(f"⚠️ Task {tid} returned invalid result_data: {type(result_data)}. Creating minimal result envelope.")
                            from seedcore.models.result_schema import create_fast_path_result
                            result_data = create_fast_path_result(
                                routed_to="unknown",
                                organ_id="unknown",
                                result={"status": "completed", "warning": "Invalid result data returned from coordinator"}
                            ).model_dump()
                        
                        # Memory management: limit result size if configured
                        if RESULT_MAX_BYTES > 0:
                            try:
                                # Optimize: use orjson.dumps directly to bytes to avoid .encode() call
                                if 'orjson' in globals():
                                    result_bytes = orjson.dumps(result_data, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)
                                    if len(result_bytes) > RESULT_MAX_BYTES:
                                        logger.warning(f"⚠️ Task {tid} result truncated: {len(result_bytes)} bytes > {RESULT_MAX_BYTES} bytes")
                                        result_data = {"_truncated": True, "original_size": len(result_bytes), "truncated_at": time.time()}
                                else:
                                    # Fallback to json if orjson not available
                                    result_json = _dumps(result_data)
                                    if len(result_json.encode('utf-8')) > RESULT_MAX_BYTES:
                                        logger.warning(f"⚠️ Task {tid} result truncated: {len(result_json)} bytes > {RESULT_MAX_BYTES} bytes")
                                        result_data = {"_truncated": True, "original_size": len(result_json), "truncated_at": time.time()}
                            except Exception as e:
                                logger.debug(f"Task {tid} result size check failed: {e}")
                        
                        # Convert result_data to JSON string for PostgreSQL jsonb column
                        # asyncpg expects a string for $1::jsonb, not a dict
                        result_json_str = _dumps(result_data)
                        
                        await conw.execute(COMPLETE_SQL, result_json_str, tid)
                        logger.info(f"[QueueDispatcher] ✅ Task {tid} completed successfully")
                        logger.info(f"[QueueDispatcher] 🎉 Task ID: {tid} | Status: COMPLETED | Type: {item['type']}")
                        self.tasks_completed.inc()
                    else:
                        # Task failed - check if we should retry or mark as failed
                        error_msg = result.get("error") or "Unknown error"
                        attempts = item["attempts"] + 1
                        
                        # Limit retry attempts to prevent infinite loops
                        max_attempts = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
                        
                        if attempts >= max_attempts:
                            # Mark as failed after max attempts
                            await conw.execute(FAIL_SQL, f"Max attempts ({max_attempts}) exceeded: {error_msg}", tid)
                            logger.warning(f"[QueueDispatcher] ❌ Task {tid} failed after {attempts} attempts: {error_msg}")
                            logger.warning(f"[QueueDispatcher] 💀 Task ID: {tid} | Status: FAILED | Attempts: {attempts}/{max_attempts} | Error: {error_msg}")
                            self.tasks_failed.inc()
                        else:
                            # Retry with exponential backoff
                            delay = min(10 * (2 ** (attempts - 1)), 300)  # Exponential backoff: 10s, 20s, 40s, 80s, 160s, 300s max
                            await conw.execute(RETRY_SQL, error_msg, str(delay), tid)
                            logger.info(f"[QueueDispatcher] 🔄 Task {tid} marked for retry (attempt {attempts}/{max_attempts}) in {delay}s: {error_msg}")
                            logger.info(f"[QueueDispatcher] 🔁 Task ID: {tid} | Status: RETRY | Attempts: {attempts}/{max_attempts} | Delay: {delay}s")
                            self.tasks_retried.inc()

            except Exception as e:
                logger.error(f"[QueueDispatcher] ❌ CRITICAL: Dispatcher {self.name} task {tid} failed with exception: {e}")
                logger.error(f"[QueueDispatcher] 🔧 Exception type: {type(e)}")
                logger.error(f"[QueueDispatcher] 📋 Exception details: {str(e)}")
                logger.exception(f"[QueueDispatcher] 🔧 Full exception traceback:")
                attempts = item["attempts"] + 1
                max_attempts = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
                
                async with self.pool.acquire() as conw:
                    if attempts >= max_attempts:
                        # Mark as failed after max attempts
                        await conw.execute(FAIL_SQL, f"Dispatcher error after {max_attempts} attempts: {e}", tid)
                        logger.warning(f"[QueueDispatcher] ❌ Task {tid} failed after {attempts} attempts due to dispatcher error: {e}")
                        logger.warning(f"[QueueDispatcher] 💀 Task ID: {tid} | Status: FAILED | Dispatcher Error | Attempts: {attempts}/{max_attempts}")
                        self.tasks_failed.inc()
                    else:
                        # Retry with exponential backoff, but add jitter to avoid retry storms
                        base_delay = min(10 * (2 ** (attempts - 1)), 300)
                        delay = base_delay + random.randint(0, 5)
                        await conw.execute(RETRY_SQL, f"dispatcher error: {e}", str(delay), tid)
                        logger.info(f"[QueueDispatcher] 🔄 Task {tid} retry (attempt {attempts}/{max_attempts}) in {delay}s with jitter due to dispatcher error: {e}")
                        logger.info(f"[QueueDispatcher] 🔁 Task ID: {tid} | Status: RETRY | Dispatcher Error | Attempts: {attempts}/{max_attempts} | Delay: {delay}s")
                        self.tasks_retried.inc()
            finally:
                # Cancel lease renewal task
                if lease_renewal_task:
                    lease_renewal_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await lease_renewal_task
                
                # help GC drop references quickly
                try:
                    del payload
                except Exception:
                    pass
                try:
                    result  # may not exist on failure
                    del result
                except Exception:
                    pass
                # Decrement inflight count and refresh gauge on exit
                self._inflight_count = max(0, self._inflight_count - 1)
                try:
                    self._g_inflight.set(self._inflight_count)
                except Exception:
                    pass
                
                # Memory management: periodic GC and memory checks
                if self._tasks_since_gc >= FORCE_GC_EVERY_N:
                    self._tasks_since_gc = 0
                    # Use lighter GC collection (0) for routine cleanup
                    collected = gc.collect(0)
                    if collected > 0:
                        logger.debug(f"Dispatcher {self.name}: GC collected {collected} objects after {FORCE_GC_EVERY_N} tasks")
                
                # Check memory limits and potentially recycle
                if MEMORY_SOFT_LIMIT_MB > 0:
                    try:
                        if self._proc is not None:
                            rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                            if rss_mb > MEMORY_SOFT_LIMIT_MB:
                                logger.warning(f"🚨 Dispatcher {self.name}: Memory limit exceeded! RSS: {rss_mb:.1f}MB > {MEMORY_SOFT_LIMIT_MB}MB")
                                # Use full GC collection (2) when memory pressure is detected
                                gc.collect(2)
                                if RECYCLE_AFTER_TASKS > 0 and self._tasks_total >= RECYCLE_AFTER_TASKS:
                                    logger.info(f"🔄 Dispatcher {self.name}: Recycling after {self._tasks_total} tasks due to memory pressure")
                                    # Reset counters and force cleanup
                                    self._tasks_total = 0
                                    self._tasks_since_gc = 0
                    except Exception as e:
                        logger.debug(f"Dispatcher {self.name}: Memory check failed: {e}")

    async def _watchdog_check(self):
        """Detect and return stuck 'running' tasks back to 'retry'."""
        try:
            async with self.pool.acquire() as con:
                # Use a grace period of 90 seconds for heartbeat checks (as string for SQL)
                grace_period = "90"
                max_attempts = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
                
                # First, mark tasks that exceeded attempt budget as failed
                failed = await con.fetch(REAP_FAILED_SQL, grace_period, max_attempts)
                if failed:
                    failed_ids = [str(r["id"]) for r in failed]
                    logger.warning(f"[QueueDispatcher] 💀 Watchdog: marked {len(failed_ids)} tasks as FAILED (attempts exceeded): {failed_ids}")
                
                # Then, requeue tasks that are still within attempt budget
                stuck = await con.fetch(REAP_STUCK_SQL, grace_period, max_attempts)
                if stuck:
                    ids = [str(r["id"]) for r in stuck]
                    owners = [r.get("locked_by") for r in stuck]
                    logger.warning(f"[QueueDispatcher] 🚨 Watchdog: returned {len(ids)} stuck tasks to RETRY: {ids} (locked_by={owners})")
        except Exception as e:
            logger.error(f"[QueueDispatcher] ❌ Watchdog check failed: {e}")

    async def _listen_loop(self, con):
        """LISTEN/NOTIFY loop using a coalescing event (no unbounded growth)."""
        notify_event = asyncio.Event()

        def _cb(*_args):
            # coalesce multiple notifies into a single set flag
            try:
                notify_event.set()
            except Exception:
                pass

        await con.add_listener(NOTIFY_CHANNEL, _cb)
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(notify_event.wait(), timeout=1.0)
                    # clear immediately to coalesce future notifies
                    notify_event.clear()
                except asyncio.TimeoutError:
                    pass
        finally:
            with contextlib.suppress(Exception):
                await con.remove_listener(NOTIFY_CHANNEL, _cb)

    async def run(self):
        await self._ensure_pool()
        await self._ensure_router()

        # Recover any tasks owned by this dispatcher on startup
        await self._recover_mine()

        # ✅ Router is now initialized and ready for task processing
        logger.info(f"[QueueDispatcher] 🔍 Router initialized successfully: {type(self.router)}")
        logger.info(f"[QueueDispatcher] 🏥 Router is ready for task processing")

        # LISTEN/NOTIFY connection (better batching)
        listen_task = None
        if USE_LISTEN_NOTIFY:
            listen_con = await self.pool.acquire()
            try:
                await listen_con.execute(f"LISTEN {NOTIFY_CHANNEL}")
                listen_task = asyncio.create_task(self._listen_loop(listen_con))
            except Exception:
                await self.pool.release(listen_con)
                listen_task = None

        try:
            self._next_watchdog_ts = time.monotonic() + WATCHDOG_INTERVAL

            while not self._stop.is_set():
                try:
                    async with self.pool.acquire() as con:
                        batch = await self._claim_batch(con)

                    if not batch:
                        await asyncio.sleep(EMPTY_SLEEP_SECONDS)
                    else:
                        # Process concurrently; each worker acquires its own write connection.
                        # Use fire-and-forget tasks to prevent one bad task from blocking the entire batch
                        logger.info(f"[QueueDispatcher] Starting concurrent processing of {len(batch)} tasks")
                        for item in batch:
                            asyncio.create_task(self._process_one(item))
                        # Brief pause to let tasks start
                        await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"Dispatcher {self.name}: Error in main loop: {e}")
                    # Brief pause before retrying to avoid tight error loops
                    await asyncio.sleep(1)

                # Periodic watchdog
                now = time.monotonic()
                if now >= self._next_watchdog_ts:
                    await self._watchdog_check()
                    self._next_watchdog_ts = now + WATCHDOG_INTERVAL
                
                # Monitor pool health to detect potential leaks
                await self._monitor_pool_health()

        finally:
            self._stop.set()
            if listen_task:
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task
            # --- FIX: ENSURE LISTEN CONNECTION IS RELEASED ON EXIT ---
            if 'listen_con' in locals() and listen_con:
                await self.pool.release(listen_con)

    async def stop(self):
        self._stop.set()
        # Ensure connection pool is properly closed
        if self.pool and not self._is_pool_closed():
            await self.pool.close()
            logger.info(f"Dispatcher {self.name}: Connection pool closed")
        # Close router if it exists
        if self.router:
            await self.router.close()
            logger.info(f"Dispatcher {self.name}: Router closed")

    def ping(self) -> str:
        return "pong"

    def get_status(self) -> Dict[str, Any]:
        pool_info = {}
        if self.pool:
            try:
                pool_info = {
                    "pool_size": self.pool.get_size(),
                    "pool_max_size": self.pool.get_max_size(),
                }
                
                # Check if pool is closed - handle asyncpg version compatibility
                try:
                    # asyncpg 0.29.0+ has is_closed method
                    pool_info["pool_closed"] = self.pool.is_closed()
                except AttributeError:
                    # Fallback for older versions - check if pool is accessible
                    try:
                        # Try to get a basic pool attribute to see if it's working
                        _ = self.pool.get_size()
                        pool_info["pool_closed"] = False
                    except Exception:
                        pool_info["pool_closed"] = True
                except Exception as e:
                    pool_info["pool_closed"] = f"error: {e}"
                
                # Try to get free size if available (not available in asyncpg >= 0.30)
                try:
                    pool_info["pool_free_size"] = self.pool.get_free_size()
                except AttributeError:
                    pool_info["pool_free_size"] = "unavailable"
                except Exception as e:
                    pool_info["pool_free_size"] = f"error: {e}"
            except Exception as e:
                pool_info = {"pool_error": str(e)}
        
        # Determine health status based on pool and overall state
        if self._stop.is_set():
            health_status = "stopped"
        elif not self.pool:
            health_status = "no_pool"
        elif self._last_pool_error:
            health_status = "pool_error"
        else:
            health_status = "healthy"
        
        return {
            "name": self.name,
            "dsn": self.dsn,
            "status": health_status,  # Add explicit health status
            "pool_initialized": self.pool is not None,
            "pool_info": pool_info,
            "last_pool_error": self._last_pool_error,
            "stopped": self._stop.is_set(),
            "semaphore_count": getattr(self.sema, "_value", "unknown"),
            "inflight_tasks": self._inflight_count,
            "last_heartbeat": time.time(),
            "router_type": type(self.router).__name__ if self.router else None,
            "router_initialized": self.router is not None,
        }

    def heartbeat(self) -> Dict[str, Any]:
        """Enhanced heartbeat with detailed health information."""
        try:
            # Basic health check
            pool_ok = self.pool is not None and not self._is_pool_closed()
            semaphore_ok = self.sema._value >= 0  # Check if semaphore is in valid state
            router_ok = self.router is not None
            
            health_status = "healthy"
            if self._stop.is_set():
                health_status = "stopped"
            elif not pool_ok:
                health_status = "pool_issue"
            elif not semaphore_ok:
                health_status = "semaphore_issue"
            elif not router_ok:
                health_status = "router_issue"
            elif self._last_pool_error:
                health_status = "pool_error"
            
            return {
                "status": health_status,
                "timestamp": time.time(),
                "pool_ok": pool_ok,
                "semaphore_ok": semaphore_ok,
                "router_ok": router_ok,
                "inflight_tasks": self._inflight_count,
                "last_pool_error": self._last_pool_error,
            }
        except Exception as e:
            return {
                "status": "error",
                "timestamp": time.time(),
                "error": str(e),
            }

# ------------- Reaper (returns stuck RUNNING tasks → RETRY) -------------
@ray.remote(name="seedcore_reaper", lifetime="detached", num_cpus=0.05, namespace=AGENT_NAMESPACE)
class Reaper:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
        self._stop = asyncio.Event()

    def _is_reaper_pool_closed(self) -> bool:
        """Check if pool is closed - handle asyncpg version compatibility."""
        if not self.pool:
            return True
        
        try:
            # asyncpg 0.29.0+ has is_closed method
            return self.pool.is_closed()
        except AttributeError:
            # Fallback for older versions - check if pool is accessible
            try:
                # Try to get a basic pool attribute to see if it's working
                _ = self.pool.get_size()
                return False
            except Exception:
                return True
        except Exception:
            return True

    async def _ensure_pool(self):
        if self.pool is None:
            try:
                import asyncpg
                # Use same pool tuning as Dispatcher for consistency
                self.pool = await asyncpg.create_pool(
                    dsn=self.dsn,
                    min_size=1,
                    max_size=2,
                    max_inactive_connection_lifetime=ASYNC_PG_IDLE_LIFETIME,
                    statement_cache_size=ASYNC_PG_STMT_CACHE,
                    command_timeout=60.0,
                )
            except Exception as e:
                logger.error(f"Reaper: Failed to create connection pool: {e}")
                raise
        elif self._is_reaper_pool_closed():
            logger.warning("Reaper: Connection pool was closed, recreating...")
            self.pool = None
            await self._ensure_pool()

    def _now(self):
        """Get current UTC time with timezone info."""
        return datetime.datetime.now(datetime.timezone.utc)

    def reap_stale_tasks(self) -> dict:
        """
        Requeue RUNNING tasks whose lease/heartbeat is stale or whose owner is gone.
        Safe to call periodically.
        """
        now = self._now()
        requeued = 0
        inspected = 0

        q_select = """
        SELECT id, status, owner_id, lease_expires_at, attempts, updated_at, last_heartbeat
        FROM tasks
        WHERE status = 'running'
        ORDER BY updated_at ASC
        LIMIT %s
        """
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            
            with psycopg2.connect(self.dsn) as con, con.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(q_select, (REAP_BATCH,))
                rows = cur.fetchall()
                for r in rows:
                    inspected += 1

                    # staleness criteria (works even if you don't have all columns)
                    last_ts = r.get("last_heartbeat") or r.get("lease_expires_at") or r.get("updated_at")
                    if not last_ts:
                        logger.debug(f"Task {r['id']}: No timestamp found for staleness check")
                        continue
                    
                    logger.debug(f"Task {r['id']}: last_ts={last_ts}, tzinfo={last_ts.tzinfo}")
                    
                    # Handle timezone-aware vs naive datetime comparison
                    try:
                        if last_ts.tzinfo is None:
                            # If last_ts is naive, assume it's UTC and make it timezone-aware
                            last_ts = last_ts.replace(tzinfo=datetime.timezone.utc)
                        
                        age_s = (now - last_ts).total_seconds()
                        stale = age_s >= TASK_STALE_S
                    except Exception as dt_error:
                        logger.debug(f"DateTime comparison failed for task {r['id']}: {dt_error}")
                        # Fallback: use updated_at for staleness check
                        updated_ts = r.get("updated_at")
                        if updated_ts and updated_ts.tzinfo is None:
                            updated_ts = updated_ts.replace(tzinfo=datetime.timezone.utc)
                        if updated_ts:
                            age_s = (now - updated_ts).total_seconds()
                            stale = age_s >= TASK_STALE_S
                        else:
                            stale = False

                    # owner liveness (best-effort)
                    owner_dead = False
                    owner_id = r.get("owner_id")
                    if owner_id:
                        try:
                            a = ray.get_actor(owner_id, namespace=AGENT_NAMESPACE)
                            pong = ray.get(a.ping.remote(), timeout=2)
                            owner_dead = (pong != "pong")  # your Dispatcher/Reaper ping returns "pong"
                        except Exception:
                            owner_dead = True  # cannot find owner -> dead

                    if not stale and not owner_dead:
                        continue

                    # retry budget check (optional)
                    attempts = r.get("attempts") or 0
                    if attempts >= MAX_REQUEUE:
                        # mark FAILED permanently
                        cur.execute("""
                            UPDATE tasks
                            SET status='failed',
                                error = COALESCE(error,'') || ' | reaper: max requeues exceeded',
                                updated_at = NOW()
                            WHERE id = %s
                        """, (r["id"],))
                        continue

                    # Requeue
                    cur.execute("""
                        UPDATE tasks
                        SET status='queued',
                            attempts = attempts + 1,
                            owner_id = NULL,
                            lease_expires_at = NULL,
                            updated_at = NOW(),
                            error = COALESCE(error,'') || ' | reaper: lease expired or owner dead'
                        WHERE id = %s
                    """, (r["id"],))
                    requeued += 1

            return {"inspected": inspected, "requeued": requeued}
        except Exception as e:
            logger.warning("reap_stale_tasks failed: %s", e)
            logger.debug("reap_stale_tasks error details: %s", traceback.format_exc())
            return {"inspected": inspected, "requeued": requeued, "error": str(e)}

    async def run(self):
        await self._ensure_pool()
        while not self._stop.is_set():
            try:
                async with self.pool.acquire() as con:
                    grace_period = str(TASK_STALE_S)          # seconds as string (matches Dispatcher watchdog)
                    max_attempts = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
                    rows = await con.fetch(REAP_STUCK_SQL, grace_period, max_attempts)
                    if rows:
                        logger.warning("Reaper returned %d stuck tasks to RETRY", len(rows))
            except Exception:
                logger.exception("Reaper iteration failed")
            await asyncio.sleep(max(LEASE_SECONDS // 3, 10))

    async def stop(self):
        self._stop.set()
        # Ensure connection pool is properly closed
        if self.pool and not self._is_reaper_pool_closed():
            await self.pool.close()
            logger.info("Reaper: Connection pool closed")

    def ping(self) -> str:
        """Simple ping for basic responsiveness check."""
        return "pong"
    
    def heartbeat(self) -> Dict[str, Any]:
        """Enhanced heartbeat with detailed health information."""
        try:
            # Basic health check
            pool_ok = self.pool is not None and not self._is_reaper_pool_closed()
            
            health_status = "healthy"
            if self._stop.is_set():
                health_status = "stopped"
            elif not pool_ok:
                health_status = "pool_issue"
            else:
                health_status = "healthy"
            
            return {
                "status": health_status,
                "timestamp": time.time(),
                "pool_ok": pool_ok,
                "last_pool_error": None,  # Reaper doesn't track pool errors
            }
        except Exception as e:
            return {
                "status": "error",
                "timestamp": time.time(),
                "error": str(e),
            }

    def get_status(self) -> Dict[str, Any]:
        pool_info = {}
        if self.pool:
            try:
                pool_info = {
                    "pool_size": self.pool.get_size(),
                    "pool_max_size": self.pool.get_max_size(),
                    "pool_closed": self._is_reaper_pool_closed(),
                }
                # Try to get free size if available (not available in asyncpg >= 0.30)
                try:
                    pool_info["pool_free_size"] = self.pool.get_free_size()
                except AttributeError:
                    pool_info["pool_free_size"] = "unavailable"
                except Exception as e:
                    pool_info["pool_free_size"] = f"error: {e}"
            except Exception as e:
                pool_info = {"pool_error": str(e)}
        
        # Determine health status based on pool and overall state
        if self._stop.is_set():
            health_status = "stopped"
        elif not self.pool:
            health_status = "no_pool"
        elif pool_info.get("pool_error"):
            health_status = "pool_error"
        else:
            health_status = "healthy"
        
        return {
            "name": "seedcore_reaper",
            "dsn": self.dsn,
            "status": health_status,  # Add explicit health status
            "pool_initialized": self.pool is not None,
            "pool_info": pool_info,
            "stopped": self._stop.is_set(),
            "last_heartbeat": time.time(),
        }

# ------------- Bootstrap helpers -------------
def _get_or_create(name: str, cls, *args, **kwargs):
    try:
        # Use explicit namespace (prefer SEEDCORE_NS)
        ns = AGENT_NAMESPACE
        return ray.get_actor(name, namespace=ns)
    except Exception:
        return cls.options(name=name).remote(*args, **kwargs)

def start_detached_pipeline(
    dsn: Optional[str] = None,
    dispatcher_count: int = DISPATCHER_COUNT
) -> Dict[str, Any]:
    """Idempotently start N Dispatchers and Reaper (Coordinator is a Serve deployment)."""
    dsn = dsn or PG_DSN

    dispatchers = []
    for i in range(dispatcher_count):
        name = f"seedcore_dispatcher_{i}"
        d = _get_or_create(name, Dispatcher, dsn, name)
        dispatchers.append(d)

    reaper = _get_or_create("seedcore_reaper", Reaper, dsn)

    # Fire-and-forget (do NOT wrap in asyncio.create_task; .remote() returns ObjectRef)
    for d in dispatchers:
        d.run.remote()
    reaper.run.remote()

    return {
        "coordinator": "Serve deployment: coordinator/Coordinator",
        "dispatchers": [f"seedcore_dispatcher_{i}" for i in range(dispatcher_count)],
        "reaper": "seedcore_reaper",
        "namespace": AGENT_NAMESPACE,
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = start_detached_pipeline()
    print(json.dumps(info, indent=2))
