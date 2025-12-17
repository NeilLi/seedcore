# seedcore/dispatcher/persistence/task_repository.py

from __future__ import annotations
import json
import os
from typing import Any, Dict, List
import asyncpg  # pyright: ignore[reportMissingImports]

from seedcore.models.task import TaskType

from .task_sql import (
    CLAIM_BATCH_SQL,
    COMPLETE_TASK_SQL,
    RETRY_TASK_SQL,
    RELEASE_TASK_SQL,
    RENEW_LEASE_SQL,
    RECOVER_STALE_SQL,
)

from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(
    app_name="seedcore.dispatcher.persistence"
)  # centralized stdout logging only
logger = ensure_serve_logger("seedcore.dispatcher.persistence")

CLAIM_BATCH_SIZE = int(os.getenv("CLAIM_BATCH_SIZE", "8"))
RUN_LEASE_S = int(os.getenv("TASK_LEASE_S", "600"))  # 10m default

GRAPH_TASK_TYPES_EXCLUSION = (TaskType.GRAPH.value,)


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
    async def claim_batch(self, batch_size: int = None, exclusions: List[str] = None) -> List[Dict[str, Any]]:
        """
        Public method to claim a batch of tasks.
        
        Args:
            batch_size: Number of tasks to claim (defaults to CLAIM_BATCH_SIZE)
            exclusions: List of task types to exclude (defaults to GRAPH_TASK_TYPES_EXCLUSION)
        
        Returns:
            List of claimed task dictionaries
        """
        batch_size = batch_size or CLAIM_BATCH_SIZE
        exclusions = exclusions or list(GRAPH_TASK_TYPES_EXCLUSION)
        
        async with self.pool.acquire() as con:
            return await self._claim_batch_internal(con, batch_size, exclusions)
    
    async def _claim_batch_internal(self, con, batch_size: int, exclusions: List[str]) -> List[Dict[str, Any]]:
        """
        Internal method to claim tasks, skipping in-batch duplicates.

        Args:
            con: asyncpg connection
            batch_size: Number of tasks to claim
            exclusions: List of task types to exclude
        """
        # Pass RUN_LEASE_S as a parameter ($4)
        # Ensure exclusion list is a list, not tuple, for asyncpg
        rows = await con.fetch(
            CLAIM_BATCH_SQL,
            batch_size,
            self.dispatcher_name,
            list(exclusions),
            str(RUN_LEASE_S),
        )

        batch = []
        seen = set()

        for r in rows:
            # Create a robust hash key for deduplication
            # sort_keys=True is CRITICAL for JSON comparison
            key = (
                r["type"] or "",
                r["description"] or "",
                json.dumps(r["params"] or {}, sort_keys=True, separators=(",", ":")),
                r["domain"] or "",
            )

            if key in seen:
                # OPTIMIZATION: Fire-and-forget the cancellation.
                # We don't need to await this inside the loop unless strict consistency is required.
                # However, awaiting ensures we don't return if the DB fails.
                logger.warning(
                    "♻️  Duplicate detected in batch. Cancelling Task ID %s (Type: %s)",
                    r["id"],
                    r["type"],
                )

                await con.execute(
                    """
                    UPDATE tasks
                    SET status='cancelled',
                        error='Duplicate task cancelled in same batch',
                        updated_at=NOW()
                    WHERE id=$1
                """,
                    r["id"],
                )
                continue

            seen.add(key)

            # Explicit dict construction is safer than passing raw Record objects
            batch.append(
                {
                    "id": r["id"],
                    "type": r["type"],
                    "description": r["description"],
                    "params": r["params"] or {},
                    "domain": r["domain"],
                    "drift_score": float(r["drift_score"] or 0.0),
                    "attempts": int(r["attempts"] or 0),
                }
            )

        if batch:
            # Only log if tasks_claimed metric exists (it might not be initialized)
            if hasattr(self, 'tasks_claimed'):
                self.tasks_claimed.inc(len(batch))
            task_ids = [str(task["id"]) for task in batch]
            # Consolidated logging
            logger.info(
                f"[{self.dispatcher_name}] 📦 Claimed {len(batch)} tasks: {', '.join(task_ids)}"
            )

        return batch

    # -------------------------------------------
    # State transitions
    # -------------------------------------------
    async def complete(self, task_id: str, result: dict = None) -> bool:
        """
        Mark task as successfully completed.
        Returns False if the task was stolen (zombie worker).
        """
        async with self.pool.acquire() as con:
            # Check rowcount to ensure we actually owned the task
            outcome = await con.execute(
                COMPLETE_TASK_SQL, 
                task_id, 
                self.dispatcher_name,
                json.dumps(result) if result else None
            )
            
            if outcome == "UPDATE 0":
                logger.warning(f"⚠️ [Task {task_id}] Finished task, but lease was already lost.")
                return False
                
            return True

    async def retry(self, task_id: str, error: str, delay_seconds: int) -> bool:
        """
        Release task back to queue with a delay.
        Returns False if lock was lost (zombie worker).
        """
        async with self.pool.acquire() as con:
            # Check rowcount to see if we actually updated anything
            result = await con.execute(
                RETRY_TASK_SQL, 
                error, 
                str(delay_seconds), 
                task_id, 
                self.dispatcher_name # Must verify ownership!
            )
            
            # "UPDATE 1" -> Success, "UPDATE 0" -> Zombie
            if result == "UPDATE 0":
                logger.error(f"❌ [Task {task_id}] Failed to retry: Lock lost/stolen.")
                return False
                
            return True

    async def fail(self, task_id: str, error_msg: str) -> None:
        async with self.pool.acquire() as con:
            await con.execute(RELEASE_TASK_SQL, task_id, self.dispatcher_name, error_msg)

    # -------------------------------------------
    # Lease management
    # -------------------------------------------
    async def renew_lease(self, task_id: str) -> bool:
        """
        Heartbeat to extend task lease.
        Returns True if successful, False if lease was lost/stolen.
        """
        # Use the same config constant as your claim logic, or a specific heartbeat duration
        extension_seconds = str(RUN_LEASE_S)

        async with self.pool.acquire() as con:
            val = await con.fetchval(
                RENEW_LEASE_SQL, task_id, self.dispatcher_name, extension_seconds
            )

            if not val:
                logger.error(
                    "❌ [Task %s] Failed to renew lease! Task was likely stolen or completed.",
                    task_id,
                )
                # You should probably raise an exception here to stop processing
                return False

            return True

    # -------------------------------------------
    # Requeue stuck tasks
    # -------------------------------------------
    async def requeue_stuck(self) -> int:
        """
        Finds tasks that have exceeded their lease time (worker crashed?)
        and returns them to the queue.
        """
        async with self.pool.acquire() as con:
            # No arguments needed; strictly time-based
            rows = await con.fetch(RECOVER_STALE_SQL)
            
        count = len(rows)
        if count > 0:
            logger.warning(f"🧹 [Janitor] Recovered {count} stale tasks: {[r['id'] for r in rows]}")
            
        return count
