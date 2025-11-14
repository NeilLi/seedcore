# seedcore/dispatcher/dispatcher_actor.py

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import ray  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.persistence.interfaces import TaskRepositoryProtocol
from seedcore.dispatcher.router import CoordinatorHttpRouter
from seedcore.models import TaskPayload

logger = logging.getLogger("seedcore.dispatcher")

AGENT_NAMESPACE = "seedcore-dev"


@ray.remote(
    lifetime="detached",
    num_cpus=0.1,
    max_restarts=1,
    namespace=AGENT_NAMESPACE,
)
class Dispatcher:
    """
    A Ray-remote version of the Dispatcher Loop.

    - Manages its own asyncio loop
    - Claims tasks from repository
    - Routes via CoordinatorHttpRouter
    - Renews leases
    - Requeues stuck tasks
    """

    # ----------------------------
    # INIT
    # ----------------------------
    def __init__(self, dsn: str, name: str = "dispatcher"):
        self.dsn = dsn
        self.name = name

        self._repo: Optional[TaskRepositoryProtocol] = None
        self._router: Optional[CoordinatorHttpRouter] = None

        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._lease_task: Optional[asyncio.Task] = None
        self._requeue_task: Optional[asyncio.Task] = None

        self._tasks_in_progress: Dict[str, asyncio.Task] = {}

        self.claim_batch = 10
        self.lease_interval = 10
        self.requeue_interval = 30
        self.main_interval = 0.25

        self._startup_status = "initializing"

    # ----------------------------
    # ACTOR API
    # ----------------------------
    async def ready(self, timeout_s=30.0, interval_s=0.5) -> bool:
        """
        Bootstrap DB pool and router before returning.
        The bootstrap script uses this.
        """
        try:
            from seedcore.dispatcher.persistence.task_repository import TaskRepository
            self._repo = TaskRepository(self.dsn, dispatcher_name=self.name)
            await self._repo.init()

            self._router = CoordinatorHttpRouter()

            self._startup_status = "ready"
            return True

        except Exception as e:
            logger.exception("[%s] Dispatcher init error: %s", self.name, e)
            self._startup_status = f"error: {e}"
            return False

    def get_startup_status(self):
        return self._startup_status

    async def get_status(self):
        return {
            "name": self.name,
            "running": self._running,
            "tasks_in_progress": len(self._tasks_in_progress),
            "startup_status": self._startup_status,
        }

    async def ping(self):
        return "pong"

    # ----------------------------
    # MAIN ENTRYPOINT
    # ----------------------------
    async def run(self):
        """
        Fire-and-forget run requested by the bootstrap script.
        """
        if self._running:
            return "already_running"

        self._running = True

        logger.info("[%s] 🚀 Dispatcher run loop starting", self.name)

        loop = asyncio.get_event_loop()

        self._loop_task = loop.create_task(self._main_loop())
        self._lease_task = loop.create_task(self._lease_daemon())
        self._requeue_task = loop.create_task(self._requeue_daemon())

        return "started"

    # ----------------------------
    # MAIN LOOP
    # ----------------------------
    async def _main_loop(self):
        logger.info("[%s] 🔄 Entering main loop", self.name)

        while self._running:
            try:
                await asyncio.sleep(self.main_interval)

                batch = await self._repo.claim_batch(self.claim_batch)
                if not batch:
                    continue

                for row in batch:
                    task_id = row["id"]
                    coro = self._process_task(row)

                    t = asyncio.create_task(coro)
                    self._tasks_in_progress[task_id] = t

                    t.add_done_callback(
                        lambda _f, tid=task_id: self._tasks_in_progress.pop(tid, None)
                    )

            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[%s] Main loop error: %s", self.name, e, exc_info=True)

    # ----------------------------
    # EXECUTE ONE TASK
    # ----------------------------
    async def _process_task(self, row: Dict[str, Any]):
        task_id = row["id"]
        started = datetime.now(timezone.utc)

        try:
            payload = TaskPayload.from_db(row)
            result = await self._router.route_and_execute(payload)

            if result.get("success"):
                await self._repo.complete(task_id, json.dumps(result))
                logger.info("[%s] ✅ Completed task %s", self.name, task_id)
            else:
                err = result.get("error") or "unknown"
                await self._repo.retry(task_id, err, delay_s=15)
                logger.warning("[%s] 🔁 Retrying task %s", self.name, task_id)

        except Exception as e:
            await self._repo.fail(task_id, str(e))
            logger.error("[%s] ❌ Failed task %s: %s", self.name, task_id, e)

        finally:
            elapsed = (datetime.now(timezone.utc) - started).total_seconds()
            logger.debug("[%s] ⏱ %s done in %.3fs", self.name, task_id, elapsed)

    # ----------------------------
    # LEASE RENEW
    # ----------------------------
    async def _lease_daemon(self):
        logger.info("[%s] 🫀 Lease daemon started", self.name)
        while self._running:
            try:
                await asyncio.sleep(self.lease_interval)
                for task_id in list(self._tasks_in_progress.keys()):
                    try:
                        await self._repo.renew_lease(task_id)
                    except Exception as e:
                        logger.warning("[%s] Lease renew failed: %s", self.name, e)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[%s] Lease daemon error: %s", self.name, e, exc_info=True)

    # ----------------------------
    # STUCK REQUEUE
    # ----------------------------
    async def _requeue_daemon(self):
        logger.info("[%s] ♻️ Requeue daemon started", self.name)
        while self._running:
            try:
                await asyncio.sleep(self.requeue_interval)
                count = await self._repo.requeue_stuck(self.requeue_interval)
                if count:
                    logger.warning("[%s] ♻️ Requeued %s stuck tasks", self.name, count)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error("[%s] Requeue daemon error: %s", self.name, e, exc_info=True)

