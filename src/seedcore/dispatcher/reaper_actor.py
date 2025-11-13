# seedcore/dispatcher/reaper_actor.py

from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import Dict, Any, Optional

import ray  # pyright: ignore[reportMissingImports]
import asyncpg  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.config import (
    TASK_STALE_S,
    ASYNC_PG_IDLE_LIFETIME,
    ASYNC_PG_STMT_CACHE,
    MAX_REQUEUE,
    REAP_BATCH,
)

logger = logging.getLogger("seedcore.reaper")
AGENT_NAMESPACE = "seedcore-dev"


@ray.remote(
    name="seedcore_reaper",
    lifetime="detached",
    namespace=AGENT_NAMESPACE,
    num_cpus=0.05,
    max_restarts=1,
)
class Reaper:
    """
    Reaper Actor

    Responsible for:
    - Detecting stale tasks stuck in RUNNING
    - Detecting dead Dispatcher owners
    - Requeuing tasks or marking permanently failed
    - Maintaining its own connection pool
    """

    def __init__(self, dsn: str):
        self.dsn = dsn

        self.pool: Optional[asyncpg.Pool] = None
        self._stop = asyncio.Event()

        self.reap_interval = 15  # seconds
        self.name = "seedcore_reaper"
        self._startup_status = "initializing"

    # ---------------------------------------------------------------------
    # Utility Methods
    # ---------------------------------------------------------------------
    def _now(self):
        return datetime.datetime.now(datetime.timezone.utc)

    # ---------------------------------------------------------------------
    # DB Pool Management
    # ---------------------------------------------------------------------
    async def _ensure_pool(self):
        """Ensure asyncpg pool exists and is alive."""
        if self.pool is None:
            logger.info("[Reaper] Creating DB pool")
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=1,
                max_size=2,
                max_inactive_connection_lifetime=ASYNC_PG_IDLE_LIFETIME,
                statement_cache_size=ASYNC_PG_STMT_CACHE,
                command_timeout=60.0,
            )
        else:
            try:
                # Attempt a no-op acquire to validate pool health
                async with self.pool.acquire():
                    pass
            except Exception:
                logger.warning("[Reaper] Pool invalid, recreating...")
                self.pool = None
                await self._ensure_pool()

    # ---------------------------------------------------------------------
    # Actor API
    # ---------------------------------------------------------------------
    async def ping(self) -> str:
        return "pong"

    async def get_startup_status(self):
        return self._startup_status

    async def get_status(self) -> Dict[str, Any]:
        pool_info = {}
        if self.pool:
            try:
                pool_info = {
                    "size": self.pool.get_size(),
                    "max_size": self.pool.get_max_size(),
                    "free": getattr(self.pool, "get_free_size", lambda: "n/a")(),
                }
            except Exception as e:
                pool_info = {"error": str(e)}

        return {
            "name": self.name,
            "status": "running" if not self._stop.is_set() else "stopped",
            "pool": pool_info,
            "startup_status": self._startup_status,
            "timestamp": time.time(),
        }

    async def heartbeat(self) -> Dict[str, Any]:
        """Simple health endpoint."""
        pool_ok = self.pool is not None
        return {
            "status": "healthy" if pool_ok else "pool_issue",
            "pool": pool_ok,
            "timestamp": time.time(),
        }

    # ---------------------------------------------------------------------
    # Internal Reaping Logic
    # ---------------------------------------------------------------------
    async def _reap_once(self, con) -> Dict[str, Any]:
        now = self._now()
        inspected = 0
        requeued = 0

        rows = await con.fetch(
            """
            SELECT id, owner_id, last_heartbeat, updated_at, attempts
            FROM tasks
            WHERE status = 'running'
            ORDER BY updated_at ASC
            LIMIT $1
            """,
            REAP_BATCH,
        )

        for r in rows:
            inspected += 1
            tid = r["id"]

            ts = (
                r["last_heartbeat"]
                or r["updated_at"]
                or (now - datetime.timedelta(seconds=TASK_STALE_S + 1))
            )

            # Normalize timezone
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)

            age_s = (now - ts).total_seconds()
            stale = age_s >= TASK_STALE_S

            # Check owner liveness
            owner_id = r["owner_id"]
            owner_dead = False
            if owner_id:
                try:
                    a = ray.get_actor(owner_id, namespace=AGENT_NAMESPACE)
                    pong = await a.ping.remote()
                    owner_dead = pong != "pong"
                except Exception:
                    owner_dead = True

            if not stale and not owner_dead:
                continue

            attempts = r["attempts"] or 0

            if attempts >= MAX_REQUEUE:
                # mark permanently failed
                await con.execute(
                    """
                    UPDATE tasks
                    SET status='failed',
                        error = COALESCE(error,'') || ' | reaper: max attempts exceeded',
                        updated_at = NOW()
                    WHERE id=$1
                    """,
                    tid,
                )
                continue

            await con.execute(
                """
                UPDATE tasks
                SET status='queued',
                    attempts = attempts + 1,
                    owner_id = NULL,
                    lease_expires_at = NULL,
                    updated_at = NOW(),
                    error = COALESCE(error,'') || ' | reaper: stale or owner dead'
                WHERE id=$1
                """,
                tid,
            )

            requeued += 1

        return {"inspected": inspected, "requeued": requeued}

    # ---------------------------------------------------------------------
    # Main Loop
    # ---------------------------------------------------------------------
    async def run(self):
        """
        Long-running loop. Bootstrap uses fire-and-forget `.remote()`.
        """
        logger.info("[Reaper] 🚀 Starting reaper loop")
        await self._ensure_pool()
        self._startup_status = "ready"

        while not self._stop.is_set():
            try:
                await asyncio.sleep(self.reap_interval)
                async with self.pool.acquire() as con:
                    res = await self._reap_once(con)
                    if res["requeued"] > 0:
                        logger.warning(
                            "[Reaper] ♻️ Requeued %d stale tasks (inspected=%d)",
                            res["requeued"],
                            res["inspected"],
                        )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("[Reaper] Error during reaping: %s", e)

        logger.info("[Reaper] Stopped.")

    # ---------------------------------------------------------------------
    async def stop(self):
        """Stop loop + close pool."""
        self._stop.set()
        if self.pool:
            try:
                await self.pool.close()
            except Exception:
                pass
        return True

