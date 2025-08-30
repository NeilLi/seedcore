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
from typing import Any, Dict, List, Optional, Tuple

import ray
from ray import serve
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, CollectorRegistry
try:
    import psutil  # for RSS telemetry if available
except Exception:
    psutil = None

log = logging.getLogger(__name__)

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
RAY_NS               = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

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

# --------- SQL (asyncpg-style $1 params) ----------
CLAIM_BATCH_SQL = f"""
WITH c AS (
  SELECT id
  FROM tasks
  WHERE status IN ('queued','retry')
    AND (run_after IS NULL OR run_after <= NOW())
  ORDER BY created_at
  FOR UPDATE SKIP LOCKED
  LIMIT $1
)
UPDATE tasks t
SET status='running',
    locked_by=$2,
    locked_at=NOW(),
    attempts = t.attempts + 1
FROM c
WHERE t.id = c.id
RETURNING t.id, t.type, t.description, t.params, t.domain, t.drift_score, t.attempts;
"""

COMPLETE_SQL = """
UPDATE tasks
SET status='completed', result=$1, error=NULL, updated_at=NOW()
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

REAP_STUCK_SQL = f"""
UPDATE tasks
SET status='retry',
    run_after = NOW(),
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE status='running'
  AND locked_at < NOW() - INTERVAL '{LEASE_SECONDS} seconds'
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

@ray.remote(lifetime="detached", num_cpus=0.1, namespace=RAY_NS)
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
                log.info(f"Dispatcher {self.name}: Created connection pool with max_size={max(4, MAX_CONCURRENCY)}")
                self._last_pool_error = None
            except Exception as e:
                log.error(f"Dispatcher {self.name}: Failed to create connection pool: {e}")
                try:
                    self._last_pool_error = f"{e.__class__.__name__}: {e}"
                except Exception:
                    self._last_pool_error = str(e)
                raise
        elif self._is_pool_closed():
            log.warning(f"Dispatcher {self.name}: Connection pool was closed, recreating...")
            self.pool = None
            await self._ensure_pool()

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
                        log.warning(f"🚨 Dispatcher {self.name}: Connection pool is full! size={pool_stats['size']}, max_size={pool_stats['max_size']}")
                    elif free_size <= 1:
                        log.warning(f"⚠️ Dispatcher {self.name}: Connection pool nearly full! free_size={free_size}, size={pool_stats['size']}")
                except AttributeError:
                    # free_size not available in newer asyncpg versions
                    pool_stats["free_size"] = "unavailable"
                    log.debug(f"ℹ️ Dispatcher {self.name}: free_size not available in this asyncpg version")
                except Exception as e:
                    pool_stats["free_size"] = f"error: {e}"
                    log.debug(f"ℹ️ Dispatcher {self.name}: free_size check failed: {e}")
                
                # Log pool stats periodically for debugging (every 5 minutes)
                now = time.monotonic()
                if now - self._last_pool_log > 300.0:
                    log.info(f"📊 Dispatcher {self.name}: Pool stats - {pool_stats}")
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
                log.error(f"Failed to monitor pool health: {e}")

    # --- NEW: explicit warmup/ready probes so bootstrap can block until DB is ready ---
    async def warmup(self) -> Dict[str, Any]:
        """
        Ensure the DB pool exists; return status dict (never raises to caller).
        Useful for synchronous readiness gating before starting run().
        """
        try:
            await self._ensure_pool()
        except Exception:
            # _last_pool_error already set in _ensure_pool
            pass
        return await self.status_async()

    async def ready(self, timeout_s: float = 20.0, interval_s: float = 0.5) -> bool:
        """
        Poll until pool is created or timeout. Returns True if ready, False otherwise.
        """
        deadline = time.monotonic() + max(0.1, timeout_s)
        while time.monotonic() < deadline:
            try:
                await self._ensure_pool()
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
        rows = await con.fetch(CLAIM_BATCH_SQL, CLAIM_BATCH_SIZE, self.name)
        batch = []
        seen = set()

        for r in rows:
            key = (r["type"], r["description"], json.dumps(r["params"], sort_keys=True), r["domain"])
            if key in seen:
                # Cancel duplicate only within the same claim batch (not across retries)
                await con.execute("""
                    UPDATE tasks
                    SET status='cancelled',
                        error='Duplicate task cancelled in same batch',
                        updated_at=NOW()
                    WHERE id=$1
                """, r["id"])
                log.info("🔄 Cancelled in-batch duplicate task %s (type=%s)", r["id"], r["type"])
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
        return batch

    class TaskPayload(BaseModel):
        type: str
        params: Dict[str, Any] = {}
        description: str = ""
        domain: str
        drift_score: float = 0.0
        task_id: str

    async def _process_one(self, item: Dict[str, Any], coord_handle):
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
            payload = Dispatcher.TaskPayload(
                type=item["type"],
                params=item["params"],
                description=item.get("description") or "",
                domain=item["domain"],
                drift_score=item["drift_score"],
                task_id=str(tid)
            )
            try:
                # NOTE: Ray Serve returns a DeploymentResponse; awaiting it is fine.
                result: Dict[str, Any] = await coord_handle.handle_incoming_task.remote(payload.dict())

                # Persist results via pooled connection
                async with self.pool.acquire() as conw:
                    if result.get("success"):
                        # Task completed successfully
                        result_data = result.get("result")
                        
                        # Memory management: limit result size if configured
                        if RESULT_MAX_BYTES > 0:
                            try:
                                # Optimize: use orjson.dumps directly to bytes to avoid .encode() call
                                if 'orjson' in globals():
                                    result_bytes = orjson.dumps(result_data, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS)
                                    if len(result_bytes) > RESULT_MAX_BYTES:
                                        log.warning(f"⚠️ Task {tid} result truncated: {len(result_bytes)} bytes > {RESULT_MAX_BYTES} bytes")
                                        result_data = {"_truncated": True, "original_size": len(result_bytes), "truncated_at": time.time()}
                                else:
                                    # Fallback to json if orjson not available
                                    result_json = _dumps(result_data)
                                    if len(result_json.encode('utf-8')) > RESULT_MAX_BYTES:
                                        log.warning(f"⚠️ Task {tid} result truncated: {len(result_json)} bytes > {RESULT_MAX_BYTES} bytes")
                                        result_data = {"_truncated": True, "original_size": len(result_json), "truncated_at": time.time()}
                            except Exception as e:
                                log.debug(f"Task {tid} result size check failed: {e}")
                        
                        await conw.execute(COMPLETE_SQL, _dumps(result_data), tid)
                        log.info("✅ Task %s completed successfully", tid)
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
                            log.warning("❌ Task %s failed after %d attempts: %s", tid, attempts, error_msg)
                            self.tasks_failed.inc()
                        else:
                            # Retry with exponential backoff
                            delay = min(10 * (2 ** (attempts - 1)), 300)  # Exponential backoff: 10s, 20s, 40s, 80s, 160s, 300s max
                            await conw.execute(RETRY_SQL, error_msg, str(delay), tid)
                            log.info("🔄 Task %s marked for retry (attempt %d/%d) in %ds: %s", 
                                    tid, attempts, max_attempts, delay, error_msg)
                            self.tasks_retried.inc()

            except Exception as e:
                log.exception("Dispatcher %s task %s failed: %s", self.name, tid, e)
                attempts = item["attempts"] + 1
                max_attempts = int(os.getenv("MAX_TASK_ATTEMPTS", "3"))
                
                async with self.pool.acquire() as conw:
                    if attempts >= max_attempts:
                        # Mark as failed after max attempts
                        await conw.execute(FAIL_SQL, f"Dispatcher error after {max_attempts} attempts: {e}", tid)
                        log.warning("❌ Task %s failed after %d attempts due to dispatcher error: %s", tid, attempts, e)
                        self.tasks_failed.inc()
                    else:
                        # Retry with exponential backoff, but add jitter to avoid retry storms
                        base_delay = min(10 * (2 ** (attempts - 1)), 300)
                        delay = base_delay + random.randint(0, 5)
                        await conw.execute(RETRY_SQL, f"dispatcher error: {e}", str(delay), tid)
                        log.info("🔄 Task %s retry (attempt %d/%d) in %ds with jitter due to dispatcher error: %s", 
                                tid, attempts, max_attempts, delay, e)
                        self.tasks_retried.inc()
            finally:
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
                        log.debug(f"Dispatcher {self.name}: GC collected {collected} objects after {FORCE_GC_EVERY_N} tasks")
                
                # Check memory limits and potentially recycle
                if MEMORY_SOFT_LIMIT_MB > 0:
                    try:
                        if self._proc is not None:
                            rss_mb = self._proc.memory_info().rss / (1024 * 1024)
                            if rss_mb > MEMORY_SOFT_LIMIT_MB:
                                log.warning(f"🚨 Dispatcher {self.name}: Memory limit exceeded! RSS: {rss_mb:.1f}MB > {MEMORY_SOFT_LIMIT_MB}MB")
                                # Use full GC collection (2) when memory pressure is detected
                                gc.collect(2)
                                if RECYCLE_AFTER_TASKS > 0 and self._tasks_total >= RECYCLE_AFTER_TASKS:
                                    log.info(f"🔄 Dispatcher {self.name}: Recycling after {self._tasks_total} tasks due to memory pressure")
                                    # Reset counters and force cleanup
                                    self._tasks_total = 0
                                    self._tasks_since_gc = 0
                    except Exception as e:
                        log.debug(f"Dispatcher {self.name}: Memory check failed: {e}")

    async def _watchdog_check(self):
        """Detect and return stuck 'running' tasks back to 'retry'."""
        try:
            async with self.pool.acquire() as con:
                stuck = await con.fetch(REAP_STUCK_SQL)
            if stuck:
                ids = [str(r["id"]) for r in stuck]
                owners = [r.get("locked_by") for r in stuck]
                log.warning("🚨 Watchdog: returned %d stuck tasks to RETRY: %s (locked_by=%s)", len(ids), ids, owners)
        except Exception as e:
            log.error("❌ Watchdog check failed: %s", e)

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

        # ✅ Get a handle to the OrganismManager deployment inside the 'organism' app.
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")

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
                        # return_exceptions=True prevents task retention on transient errors
                        await asyncio.gather(
                            *(self._process_one(item, coord_handle) for item in batch),
                            return_exceptions=True,
                        )
                except Exception as e:
                    log.error(f"Dispatcher {self.name}: Error in main loop: {e}")
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
            log.info(f"Dispatcher {self.name}: Connection pool closed")

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
        }

    def heartbeat(self) -> Dict[str, Any]:
        """Enhanced heartbeat with detailed health information."""
        try:
            # Basic health check
            pool_ok = self.pool is not None and not self._is_pool_closed()
            semaphore_ok = self.sema._value >= 0  # Check if semaphore is in valid state
            
            health_status = "healthy"
            if self._stop.is_set():
                health_status = "stopped"
            elif not pool_ok:
                health_status = "pool_issue"
            elif not semaphore_ok:
                health_status = "semaphore_issue"
            elif self._last_pool_error:
                health_status = "pool_error"
            
            return {
                "status": health_status,
                "timestamp": time.time(),
                "pool_ok": pool_ok,
                "semaphore_ok": semaphore_ok,
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
@ray.remote(name="seedcore_reaper", lifetime="detached", num_cpus=0.05, namespace=RAY_NS)
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
                log.error(f"Reaper: Failed to create connection pool: {e}")
                raise
        elif self._is_reaper_pool_closed():
            log.warning("Reaper: Connection pool was closed, recreating...")
            self.pool = None
            await self._ensure_pool()

    async def run(self):
        await self._ensure_pool()
        while not self._stop.is_set():
            try:
                async with self.pool.acquire() as con:
                    rows = await con.fetch(REAP_STUCK_SQL)
                    if rows:
                        log.warning("Reaper returned %d stuck tasks to RETRY", len(rows))
            except Exception:
                log.exception("Reaper iteration failed")
            await asyncio.sleep(max(LEASE_SECONDS // 3, 10))

    async def stop(self):
        self._stop.set()
        # Ensure connection pool is properly closed
        if self.pool and not self._is_reaper_pool_closed():
            await self.pool.close()
            log.info("Reaper: Connection pool closed")

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
        return ray.get_actor(name, namespace=RAY_NS)
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
        "coordinator": "Serve deployment: organism/OrganismManager",
        "dispatchers": [f"seedcore_dispatcher_{i}" for i in range(dispatcher_count)],
        "reaper": "seedcore_reaper",
        "namespace": RAY_NS,
    }

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    info = start_detached_pipeline()
    print(json.dumps(info, indent=2))
