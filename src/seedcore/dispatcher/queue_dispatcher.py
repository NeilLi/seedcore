# seedcore/dispatcher/dispatcher_actor.py

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, time
import os
from typing import Dict, Any, Optional

import ray  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.persistence.interfaces import TaskRepositoryProtocol
from seedcore.dispatcher.router import CoordinatorHttpRouter, OrganismRouter
from seedcore.models import TaskPayload

from seedcore.database import PG_DSN
from seedcore.logging_setup import setup_logging, ensure_serve_logger

setup_logging(app_name="seedcore.dispatcher")
logger = ensure_serve_logger("seedcore.dispatcher")

RAY_NAMESPACE = (
    os.getenv("SEEDCORE_NS", os.getenv("RAY_NAMESPACE", "seedcore-dev")).strip()
    or "seedcore-dev"
)


@ray.remote(
    lifetime="detached",
    num_cpus=0.1,
    max_restarts=1,
    namespace=RAY_NAMESPACE,
)
class Dispatcher:
    """
    A Ray-remote version of the Dispatcher Loop.
    Implements Zombie Worker Protection and Graceful Shutdown.
    """

    def __init__(self, name: str = "queue_dispatcher"):
        logger.info("🚀 QueueDispatcher '%s' initializing...", name)

        # 1. Config
        self.dsn = PG_DSN
        self.name = name

        # 2. Dependencies (Injected or Lazily Loaded in run())
        self._repo: Optional[TaskRepositoryProtocol] = None
        self._router: Optional[CoordinatorHttpRouter] = None
        self._organism_router: Optional[OrganismRouter] = None

        # 3. Control Plane
        self._running = False
        self._stop_event = asyncio.Event()  # Better than bool for async loops
        self._startup_status = "initializing"

        # 4. Concurrency Management
        self._daemons: list[asyncio.Task] = []
        self._tasks_in_progress: Dict[str, asyncio.Task] = {}

        # 5. Tuning parameters
        self.claim_batch = 10
        self.lease_interval = 10
        self.requeue_interval = 30
        self.main_interval = 0.25

        # 6. Observability
        self._metrics = {
            "tasks_processed": 0,
            "tasks_succeeded": 0,
            "tasks_failed": 0,
            "active_coroutines": 0,
            "last_heartbeat": time.time(),
        }

        logger.info("✅ QueueDispatcher '%s' initialized", name)

    # ----------------------------
    # ACTOR API
    # ----------------------------
    async def ready(self, timeout_s=30.0) -> bool:
        """Initialize connections."""
        try:
            # Local import to avoid circular dependencies
            from seedcore.dispatcher.persistence.task_repository import TaskRepository

            self._repo = TaskRepository(self.dsn, dispatcher_name=self.name)
            await self._repo.init()

            self._router = CoordinatorHttpRouter()
            # Lazy initialization of OrganismRouter (only created when needed)
            # This avoids unnecessary initialization if no conversation tasks are processed

            self._startup_status = "ready"
            return True

        except Exception as e:
            logger.exception("[%s] Init failed: %s", self.name, e)
            self._startup_status = f"error: {e}"
            return False

    async def get_status(self):
        return {
            "name": self.name,
            "running": self._running,
            "active_tasks": len(self._tasks_in_progress),
            "status": self._startup_status,
        }

    async def stop(self):
        """Graceful shutdown trigger."""
        logger.info("[%s] 🛑 Stopping dispatcher...", self.name)
        self._running = False

        # Cancel daemons
        for task in self._daemons:
            task.cancel()

        # Wait for active tasks to finish or cancel them?
        # Usually, we let them finish or timeout. For now, we return.
        logger.info("[%s] 🛑 Stopped.", self.name)

    # ----------------------------
    # MAIN ENTRYPOINT
    # ----------------------------
    async def run(self):
        if self._running:
            return "already_running"

        if self._startup_status != "ready":
            # Auto-initialize if not ready
            if not await self.ready():
                return "failed_init"

        self._running = True
        logger.info("[%s] 🚀 Dispatcher loop starting", self.name)

        loop = asyncio.get_event_loop()

        # Create daemons
        self._daemons = [
            loop.create_task(self._main_loop()),
            loop.create_task(self._lease_daemon()),
            loop.create_task(self._requeue_daemon()),
        ]

        return "started"

    # ----------------------------
    # 1. MAIN LOOP (Claim & Spawn)
    # ----------------------------
    async def _main_loop(self):
        while self._running:
            try:
                # 1. Claim Batch
                batch = await self._repo.claim_batch(self.claim_batch)

                if not batch:
                    await asyncio.sleep(self.main_interval)
                    continue

                # 2. Spawn Workers
                for row in batch:
                    task_id = str(row["id"])

                    # Create async task for this specific job
                    t = asyncio.create_task(self._process_task(row))
                    self._tasks_in_progress[task_id] = t

                    # Cleanup callback
                    t.add_done_callback(
                        lambda _f, tid=task_id: self._tasks_in_progress.pop(tid, None)
                    )

                # Small yield to let tasks start
                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Loop error: %s", self.name, e)
                await asyncio.sleep(1.0)  # Backoff on DB error

    # ----------------------------
    # 2. TASK EXECUTION (The Worker)
    # ----------------------------
    async def _process_task(self, row: Dict[str, Any]):
        task_id = str(row["id"])
        started = datetime.now(timezone.utc)

        try:
            # A. Parse
            payload = TaskPayload.from_db(row)
            conversation_id = payload.conversation_id
            mode = payload.interaction_mode
            
            # B. Route and Execute
            # Use OrganismRouter for tasks with conversation_id (sticky sessions)
            # Otherwise use CoordinatorHttpRouter (standard routing)
            if mode == "agent_tunnel" or conversation_id:
                # Lazy initialization: create OrganismRouter only when first needed
                if self._organism_router is None:
                    self._organism_router = OrganismRouter()
                result = await self._organism_router.route_and_execute(payload)
            else:
                # Standard routing through Coordinator
                result = await self._router.route_and_execute(payload)

            # C. Settle
            if result.get("success"):
                # Use updated method name 'complete_task'
                await self._repo.complete_task(task_id, result)
                logger.info("[%s] ✅ Task %s done", self.name, task_id)
            else:
                err = str(result.get("error") or "unknown_error")
                await self._repo.retry(task_id, err, delay_seconds=15)
                logger.warning(
                    "[%s] 🔁 Task %s failed logic: %s", self.name, task_id, err
                )

        except asyncio.CancelledError:
            logger.warning("[%s] 🛑 Task %s cancelled (Lease Lost)", self.name, task_id)
            # Do NOT call retry here; the lease is already lost/stolen.
            # Just exit cleanly.

        except Exception as e:
            # Unexpected crashes (Parse error, Network down)
            logger.error("[%s] ❌ Task %s crashed: %s", self.name, task_id, e)
            try:
                await self._repo.retry(task_id, f"crash: {e}", delay_seconds=30)
            except Exception:
                pass  # Repo might be down, nothing we can do

        finally:
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            logger.debug("[%s] ⏱ %s finished in %.3fs", self.name, task_id, elapsed)

    # ----------------------------
    # 3. LEASE DAEMON (Zombie Protection)
    # ----------------------------
    async def _lease_daemon(self):
        """
        Periodically renews leases.
        CRITICAL: If renewal fails (returns False), it means we lost the lock.
        We must CANCEL the local task immediately to stop 'Zombie' work.
        """
        while self._running:
            try:
                await asyncio.sleep(self.lease_interval)

                # Copy keys to avoid 'dictionary changed size during iteration'
                active_ids = list(self._tasks_in_progress.keys())

                for tid in active_ids:
                    # RENEW
                    still_owned = await self._repo.renew_lease(tid)

                    if not still_owned:
                        # ZOMBIE DETECTED!
                        logger.error(
                            "[%s] 🧟 Zombie detected! Lost lease for %s. Cancelling.",
                            self.name,
                            tid,
                        )

                        task = self._tasks_in_progress.get(tid)
                        if task and not task.done():
                            task.cancel()  # Raises CancelledError in _process_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Lease daemon error: %s", self.name, e)

    # ----------------------------
    # 4. REQUEUE DAEMON
    # ----------------------------
    async def _requeue_daemon(self):
        while self._running:
            try:
                await asyncio.sleep(self.requeue_interval)
                # timeout_s parameter removed based on SQL review
                count = await self._repo.requeue_stuck()
                if count:
                    logger.warning(
                        "[%s] 🧹 Janitor recovered %s stuck tasks", self.name, count
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("[%s] Janitor error: %s", self.name, e)
