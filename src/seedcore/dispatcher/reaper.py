# seedcore/dispatcher/reaper_actor.py

from __future__ import annotations

import asyncio
import os
from typing import Optional

import ray  # pyright: ignore[reportMissingImports]
import asyncpg  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.config import (
    ASYNC_PG_IDLE_LIFETIME,
    ASYNC_PG_STMT_CACHE,
    TASK_STALE_S,    # e.g., 300 seconds
    MAX_ATTEMPTS,    # e.g., 5
)

from .persistence.task_sql import (
    REAP_FAILED_SQL,
    REAP_STUCK_SQL,
    CHECK_DUPLICATE_SQL,
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.reaper")
logger = ensure_serve_logger("seedcore.reaper")

RAY_NAMESPACE = (
    os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev")).strip()
    or "seedcore-dev"
)

@ray.remote(
    name="seedcore_reaper",
    lifetime="detached",
    namespace=RAY_NAMESPACE,
    num_cpus=0.05,
    max_restarts=1,
)
class Reaper:
    """
    Reaper Actor (Singleton Janitor)
    
    Responsible for enforcing Lease Contracts using pure SQL logic.
    """

    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: Optional[asyncpg.Pool] = None
        self._stop = asyncio.Event()
        self.reap_interval = 15
        self.name = "seedcore_reaper"
        self._startup_status = "initializing"

    async def _ensure_pool(self):
        if self.pool is None:
            logger.info("[Reaper] Connecting to DB...")
            self.pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=1,
                max_size=2,
                max_inactive_connection_lifetime=ASYNC_PG_IDLE_LIFETIME,
                statement_cache_size=ASYNC_PG_STMT_CACHE,
                command_timeout=60.0,
            )

    # ---------------------------------------------------------------------
    # CORE LOGIC
    # ---------------------------------------------------------------------
    async def _run_reap_cycle(self, con):
        """
        Executes the two-phase reap strategy:
        1. Fail tasks that have tried too many times.
        2. Recover tasks that still have a chance.
        """
        
        # Phase 1: Fail Exhausted
        # $1 = Stale Seconds (used for heartbeat calc), $2 = Max Attempts
        failed_rows = await con.fetch(
            REAP_FAILED_SQL, 
            str(TASK_STALE_S), 
            MAX_ATTEMPTS
        )
        
        if failed_rows:
            ids = [str(r['id']) for r in failed_rows]
            logger.error(f"[Reaper] 💀 Permanently failed {len(ids)} tasks (Max Retries): {ids}")

        # Phase 2: Recover Stuck
        stuck_rows = await con.fetch(
            REAP_STUCK_SQL, 
            str(TASK_STALE_S), 
            MAX_ATTEMPTS
        )

        if stuck_rows:
            ids = [str(r['id']) for r in stuck_rows]
            logger.warning(f"[Reaper] ♻️ Recovered {len(ids)} stuck tasks (Retrying): {ids}")

        return len(failed_rows) + len(stuck_rows)

    # ---------------------------------------------------------------------
    # UTILITY API (Can be called by other actors)
    # ---------------------------------------------------------------------
    async def check_is_duplicate(self, type_: str, desc: str, params: dict, domain: str) -> Optional[str]:
        """
        Check if a similar task exists. 
        Note: Usually this logic belongs in the Dispatcher/Repository at insertion time.
        """
        if not self.pool:
            return None
            
        async with self.pool.acquire() as con:
            # We assume params is passed as a Dict, but DB expects JSONB.
            # Depending on driver setup, might need json.dumps(params).
            # asyncpg usually handles dict->jsonb automatically if configured, 
            # otherwise cast explicitly:
            import json
            params_json = json.dumps(params)
            
            val = await con.fetchval(CHECK_DUPLICATE_SQL, type_, desc, params_json, domain)
            return str(val) if val else None

    # ---------------------------------------------------------------------
    # MAIN LOOP
    # ---------------------------------------------------------------------
    async def run(self):
        logger.info("[Reaper] 🚀 Loop starting")
        await self._ensure_pool()
        self._startup_status = "ready"

        while not self._stop.is_set():
            try:
                await asyncio.sleep(self.reap_interval)
                
                async with self.pool.acquire() as con:
                    await self._run_reap_cycle(con)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[Reaper] Cycle error: %s", e)
                await asyncio.sleep(5.0)

        logger.info("[Reaper] Stopped.")

    async def stop(self):
        self._stop.set()
        if self.pool:
            await self.pool.close()