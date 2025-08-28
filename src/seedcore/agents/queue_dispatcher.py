from __future__ import annotations

import os
import json
import asyncio
import logging
import contextlib
from typing import Any, Dict, List, Optional

import ray
from ray import serve

log = logging.getLogger(__name__)

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

    async def _process_one(self, item: Dict[str, Any], coord_handle):
        """Bounded-concurrency task runner for a single task."""
        async with self.sema:
            tid = item["id"]
            payload = {
                "type": item["type"],
                "params": item["params"],
                "description": item["description"] or "",
                "domain": item["domain"],
                "drift_score": item["drift_score"],
                "task_id": str(tid),
            }
            try:
                # ✅ Use Serve deployment handle; Ray Serve handles are awaitable.
                result: Dict[str, Any] = await coord_handle.handle_incoming_task.remote(payload)

                # Persist using a fresh pooled connection (DO NOT share 'con' concurrently)
                async with self.pool.acquire() as conw:
                    if result.get("success"):
                        await conw.execute(COMPLETE_SQL, json.dumps(result.get("result"), default=str), tid)
                    else:
                        delay = min(10 * (item["attempts"] + 1), 300)
                        await conw.execute(RETRY_SQL, result.get("error") or "Unknown error", delay, tid)

            except Exception as e:
                log.exception("Dispatcher %s task %s failed: %s", self.name, tid, e)
                delay = min(10 * (item["attempts"] + 1), 300)
                async with self.pool.acquire() as conw:
                    await conw.execute(RETRY_SQL, f"dispatcher error: {e}", delay, tid)

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
        """Optional LISTEN/NOTIFY to wake quickly on new tasks."""
        await con.add_listener(NOTIFY_CHANNEL, lambda *args: None)
        try:
            while not self._stop.is_set():
                await con.wait_for_notify(timeout=1.0)
                if self._stop.is_set():
                    break
        finally:
            with contextlib.suppress(Exception):
                await con.remove_listener(NOTIFY_CHANNEL, lambda *args: None)

    async def run(self):
        await self._ensure_pool()

        # ✅ Get a handle to the OrganismManager deployment inside the 'organism' app.
        coord_handle = serve.get_deployment_handle("OrganismManager", app_name="organism")

        # Optional LISTEN/NOTIFY connection
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
            import time
            self._next_watchdog_ts = time.monotonic() + WATCHDOG_INTERVAL

            while not self._stop.is_set():
                async with self.pool.acquire() as con:
                    batch = await self._claim_batch(con)

                if not batch:
                    await asyncio.sleep(EMPTY_SLEEP_SECONDS)
                else:
                    # Process concurrently; each worker acquires its own write connection.
                    await asyncio.gather(*(self._process_one(item, coord_handle) for item in batch))

                # Periodic watchdog
                now = time.monotonic()
                if now >= self._next_watchdog_ts:
                    await self._watchdog_check()
                    self._next_watchdog_ts = now + WATCHDOG_INTERVAL

        finally:
            self._stop.set()
            if listen_task:
                listen_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await listen_task

    async def stop(self):
        self._stop.set()

    def ping(self) -> str:
        return "pong"

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "dsn": self.dsn,
            "pool_initialized": self.pool is not None,
            "stopped": self._stop.is_set(),
            "semaphore_count": getattr(self.sema, "_value", "unknown"),
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
        return "pong"

    def get_status(self) -> Dict[str, Any]:
        return {
            "dsn": self.dsn,
            "pool_initialized": self.pool is not None,
            "stopped": self._stop.is_set(),
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
