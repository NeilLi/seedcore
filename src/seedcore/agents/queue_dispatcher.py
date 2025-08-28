# src/seedcore/organs/queue_dispatcher.py
from __future__ import annotations

import os
import json
import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence

import ray

log = logging.getLogger(__name__)

# --------- ENV / Defaults ----------
PG_DSN               = os.getenv("PG_DSN", "postgresql://postgres:postgres@postgresql:5432/seedcore")
RAY_NS               = os.getenv("RAY_NAMESPACE", os.getenv("SEEDCORE_NS", "seedcore-dev"))

DISPATCHER_COUNT     = int(os.getenv("DISPATCHER_COUNT", "2"))
CLAIM_BATCH_SIZE     = int(os.getenv("CLAIM_BATCH_SIZE", "8"))           # how many tasks per claim batch
MAX_CONCURRENCY      = int(os.getenv("DISPATCHER_CONCURRENCY", "16"))    # per-dispatcher concurrent in-flight tasks
EMPTY_SLEEP_SECONDS  = float(os.getenv("EMPTY_SLEEP_SECONDS", "0.05"))   # idle sleep when queue empty
LEASE_SECONDS        = int(os.getenv("LEASE_SECONDS", "90"))             # how long until RUNNING is considered stuck
USE_LISTEN_NOTIFY    = os.getenv("USE_LISTEN_NOTIFY", "0") == "1"
NOTIFY_CHANNEL       = os.getenv("TASKS_NOTIFY_CHANNEL", "tasks_new")

# --------- SQL (asyncpg-style $1 params) ----------
# One round-trip: claim + return payloads (no second SELECT)
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
    run_after = NOW(),          -- requeue immediately; you can add backoff here if you want
    locked_by = NULL,
    locked_at = NULL,
    updated_at = NOW()
WHERE status='running'
  AND locked_at < NOW() - INTERVAL '{LEASE_SECONDS} seconds'
RETURNING id
"""

# ------------- Coordinator (wraps OrganismManager) -------------
@ray.remote(name="seedcore_coordinator", lifetime="detached", num_cpus=0.1, namespace=RAY_NS)
class Coordinator:
    async def __init__(self):
        """
        Async initialization for Ray actor compatibility.
        
        This method is called automatically by Ray when the actor is created.
        It initializes the OrganismManager and waits for it to be ready.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            from src.seedcore.organs.organism_manager import OrganismManager
            
            logger.info("🚀 Initializing Coordinator actor...")
            
            # Create OrganismManager instance
            self.org = OrganismManager()
            
            # Initialize organism inside the actor (Ray already initialized in cluster)
            logger.info("⏳ Initializing organism...")
            await self.org.initialize_organism()
            
            logger.info("✅ Coordinator actor initialization completed successfully")
            
        except Exception as e:
            logger.error(f"❌ Coordinator initialization failed: {e}")
            # Re-raise to ensure Ray knows the actor creation failed
            raise RuntimeError(f"Coordinator initialization failed: {e}") from e

    async def handle(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming tasks by delegating to the OrganismManager.
        
        Args:
            task: Task dictionary containing type, params, description, domain, drift_score
            
        Returns:
            Task result dictionary from OrganismManager
        """
        try:
            # app_state=None; builtins optional
            return await self.org.handle_incoming_task(task, app_state=None)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"❌ Task handling failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "task_type": task.get("type", "unknown")
            }

    async def ping(self) -> str:
        """Health check method to verify the actor is responsive."""
        return "pong"
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get the current status of the Coordinator and OrganismManager.
        
        Returns:
            Status dictionary with initialization state and organism info
        """
        try:
            if hasattr(self, 'org') and self.org:
                # Check if organism is initialized
                org_status = getattr(self.org, '_initialized', False)
                return {
                    "status": "healthy" if org_status else "initializing",
                    "organism_initialized": org_status,
                    "coordinator": "available"
                }
            else:
                return {
                    "status": "unhealthy",
                    "organism_initialized": False,
                    "coordinator": "unavailable",
                    "error": "OrganismManager not initialized"
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "organism_initialized": False,
                "coordinator": "error",
                "error": str(e)
            }

    def debug_env(self, keys=None):
        """
        Debug method to verify environment variables are properly set.
        
        Args:
            keys: List of environment variable keys to check. If None, checks all integration keys.
            
        Returns:
            Dictionary of environment variable values
        """
        import os
        if keys is None:
            keys = [
                "OCPS_DRIFT_THRESHOLD",
                "COGNITIVE_TIMEOUT_S",
                "COGNITIVE_MAX_INFLIGHT", 
                "FAST_PATH_LATENCY_SLO_MS",
                "MAX_PLAN_STEPS"
            ]
        return {k: os.getenv(k) for k in keys}

# ------------- Dispatcher (PG -> Coordinator -> PG) -------------
@ray.remote(lifetime="detached", num_cpus=0.1, namespace=RAY_NS)
class Dispatcher:
    def __init__(self, dsn: str, name: str):
        self.dsn = dsn
        self.name = name
        self.pool = None
        self.sema = asyncio.Semaphore(MAX_CONCURRENCY)
        self._stop = asyncio.Event()

    async def _ensure_pool(self):
        if self.pool is None:
            import asyncpg
            self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=max(4, MAX_CONCURRENCY))

    async def _claim_batch(self, con) -> List[Dict[str, Any]]:
        rows = await con.fetch(CLAIM_BATCH_SQL, CLAIM_BATCH_SIZE, self.name)
        batch = []
        for r in rows:
            batch.append({
                "id": r["id"],
                "type": r["type"],
                "description": r["description"],
                "params": r["params"] or {},
                "domain": r["domain"],
                "drift_score": float(r["drift_score"] or 0.0),
                "attempts": int(r["attempts"] or 0),
            })
        return batch

    async def _process_one(self, item: Dict[str, Any], coord, con):
        """Bounded-concurrency task runner for a single task."""
        async with self.sema:
            tid = item["id"]
            try:
                # Dispatch to coordinator (async Ray call allowed in async actor)
                result = await coord.handle.remote({
                    "type": item["type"],
                    "params": item["params"],
                    "description": item["description"] or "",
                    "domain": item["domain"],
                    "drift_score": item["drift_score"],
                })

                if result.get("success"):
                    await con.execute(COMPLETE_SQL, json.dumps(result.get("result")), tid)
                else:
                    # Backoff: 10s * attempts (cap to e.g. 300s)
                    delay = min(10 * (item["attempts"] + 1), 300)
                    await con.execute(RETRY_SQL, result.get("error") or "Unknown", delay, tid)

            except Exception as e:
                # On unexpected error, RETRY with backoff
                delay = min(10 * (item["attempts"] + 1), 300)
                await con.execute(RETRY_SQL, f"dispatcher error: {e}", delay, tid)

    async def _listen_loop(self, con):
        """Optional LISTEN/NOTIFY to wake up quickly when new tasks arrive."""
        await con.add_listener(NOTIFY_CHANNEL, lambda *args: None)
        try:
            while not self._stop.is_set():
                # Wait up to 1s for a NOTIFY; fall back to claiming anyway
                await con.wait_for_notify(timeout=1.0)
                if self._stop.is_set():
                    break
                # No payload needed; the main loop will run another claim immediately
                # (This loop exists only to keep the connection LISTENing.)
        finally:
            try:
                await con.remove_listener(NOTIFY_CHANNEL, lambda *args: None)
            except Exception:
                pass

    async def run(self):
        await self._ensure_pool()
        coord = ray.get_actor("seedcore_coordinator", namespace=RAY_NS)

        # Optionally keep a dedicated LISTEN connection
        listen_task = None
        if USE_LISTEN_NOTIFY:
            listen_con = await self.pool.acquire()
            try:
                await listen_con.execute(f"LISTEN {NOTIFY_CHANNEL}")
                listen_task = asyncio.create_task(self._listen_loop(listen_con))
            except Exception:
                # if LISTEN fails, just continue with polling
                await self.pool.release(listen_con)
                listen_task = None

        try:
            while not self._stop.is_set():
                async with self.pool.acquire() as con:
                    batch = await self._claim_batch(con)

                    if not batch:
                        await asyncio.sleep(EMPTY_SLEEP_SECONDS)
                        continue

                    # Process batch with bounded concurrency; reuse the same connection for writes
                    await asyncio.gather(*(self._process_one(item, coord, con) for item in batch))
        finally:
            self._stop.set()
            if listen_task:
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task

    async def stop(self):
        self._stop.set()

    def ping(self) -> str:
        """Health check method that returns 'pong' if the dispatcher is alive."""
        return "pong"

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the dispatcher."""
        return {
            "name": self.name,
            "dsn": self.dsn,
            "pool_initialized": self.pool is not None,
            "stopped": self._stop.is_set(),
            "semaphore_count": self.sema._value if hasattr(self.sema, '_value') else 'unknown'
        }

# ------------- Reaper (returns stuck RUNNING tasks → RETRY) -------------
@ray.remote(name="seedcore_reaper", lifetime="detached", num_cpus=0.05, namespace=RAY_NS)
class Reaper:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool = None
        self._stop = asyncio.Event()

    async def _ensure_pool(self):
        if self.pool is None:
            import asyncpg
            self.pool = await asyncpg.create_pool(dsn=self.dsn, min_size=1, max_size=2)

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

    def ping(self) -> str:
        """Health check method that returns 'pong' if the reaper is alive."""
        return "pong"

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the reaper."""
        return {
            "dsn": self.dsn,
            "pool_initialized": self.pool is not None,
            "stopped": self._stop.is_set()
        }

# ------------- Bootstrap helpers -------------
def _get_or_create(name: str, cls, *args, **kwargs):
    try:
        return ray.get_actor(name, namespace=RAY_NS)
    except Exception:
        # create
        h = cls.options(name=name).remote(*args, **kwargs)
        # simple readiness check
        return h

def start_detached_pipeline(
    dsn: Optional[str] = None,
    dispatcher_count: int = DISPATCHER_COUNT
) -> Dict[str, Any]:
    """Idempotently start Coordinator, N Dispatchers, and Reaper."""
    dsn = dsn or PG_DSN

    # Coordinator
    coord = _get_or_create("seedcore_coordinator", Coordinator)

    # Dispatchers
    dispatchers = []
    for i in range(dispatcher_count):
        name = f"seedcore_dispatcher_{i}"
        d = _get_or_create(name, Dispatcher, dsn, name)
        dispatchers.append(d)

    # Reaper
    reaper = _get_or_create("seedcore_reaper", Reaper, dsn)

    # Kick off their run loops (idempotent – they may already be running)
    # Use fire-and-forget Ray tasks
    for d in dispatchers:
        # Don't await; we just start the loop
        asyncio.get_event_loop().create_task(d.run.remote())
    asyncio.get_event_loop().create_task(reaper.run.remote())

    return {
        "coordinator": "seedcore_coordinator",
        "dispatchers": [f"seedcore_dispatcher_{i}" for i in range(dispatcher_count)],
        "reaper": "seedcore_reaper",
        "namespace": RAY_NS,
    }

if __name__ == "__main__":
    import contextlib
    import asyncio
    import logging
    logging.basicConfig(level=logging.INFO)
    # If you run this as a Ray Job (recommended), Ray is already connected.
    # Otherwise, you could connect here via ray.init(address="auto")
    info = start_detached_pipeline()
    print(json.dumps(info, indent=2))

