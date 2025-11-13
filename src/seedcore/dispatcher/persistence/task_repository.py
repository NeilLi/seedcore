# seedcore/dispatcher/persistence/task_repository.py

from __future__ import annotations
from typing import Any, Dict, List
import asyncpg  # pyright: ignore[reportMissingImports]
import logging

from .task_sql import (
    CLAIM_BATCH_SQL,
    COMPLETE_SQL,
    RETRY_SQL,
    FAIL_SQL,
    RENEW_LEASE_SQL,
    REQUEUE_STUCK_SQL,
    CLEAR_LEASE_SQL,
)

logger = logging.getLogger(__name__)


class TaskRepository:
    """
    DAO for all task persistence operations.
    Dispatcher, Router, and Organism should NEVER speak SQL directly.

    Responsibilities:
    - Claims
    - Updates
    - State transitions
    - Lease renewal
    - Reaping stale workers
    """

    def __init__(self, pool: asyncpg.pool.Pool, dispatcher_name: str):
        self.pool = pool
        self.dispatcher_name = dispatcher_name

    # -------------------------------------------
    # Row → Domain mapping
    # -------------------------------------------
    @staticmethod
    def row_to_task(row: asyncpg.Record) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "type": row["type"],
            "params": row.get("params") or {},
            "description": row.get("description"),
            "domain": row.get("domain"),
            "priority": row.get("priority"),
            "drift_score": float(row.get("drift_score") or 0.0),
            "required_specialization": row.get("required_specialization"),
            "lease_expiry": row.get("lease_expiry"),
        }

    # -------------------------------------------
    # Claiming
    # -------------------------------------------
    async def claim_batch(
        self,
        batch_size: int,
        exclusions: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Claim up to N tasks for this dispatcher.
        """
        async with self.pool.acquire() as con:
            rows = await con.fetch(
                CLAIM_BATCH_SQL,
                batch_size,
                self.dispatcher_name,
                exclusions,
            )
        return [self.row_to_task(r) for r in rows]

    # -------------------------------------------
    # State transitions
    # -------------------------------------------
    async def complete(self, task_id: str, result_json: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(COMPLETE_SQL, result_json, task_id)

    async def retry(self, task_id: str, error: str, delay_seconds: int) -> None:
        async with self.pool.acquire() as con:
            await con.execute(RETRY_SQL, error, str(delay_seconds), task_id)

    async def fail(self, task_id: str, error: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(FAIL_SQL, error, task_id)

    # -------------------------------------------
    # Lease management
    # -------------------------------------------
    async def renew_lease(self, task_id: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(RENEW_LEASE_SQL, task_id, self.dispatcher_name)

    async def clear_lease(self, task_id: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(CLEAR_LEASE_SQL, task_id)

    # -------------------------------------------
    # Requeue stuck tasks
    # -------------------------------------------
    async def requeue_stuck(self, timeout_s: int) -> int:
        """
        Returns number of requeued tasks.
        """
        async with self.pool.acquire() as con:
            rows = await con.fetch(REQUEUE_STUCK_SQL, timeout_s)
        return len(rows)
