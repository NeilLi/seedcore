# seedcore/dispatcher/dispatcher_actor.py

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
import os
from typing import Dict, Any, Optional

import ray  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.persistence.interfaces import TaskRepositoryProtocol
from seedcore.dispatcher.router import CoordinatorHttpRouter, OrganismRouter
from seedcore.models import TaskPayload
from seedcore.database import get_asyncpg_pool, PG_DSN
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
        self._pool = None  # Will be asyncpg.Pool when initialized
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

            # Create asyncpg connection pool using centralized database utility
            if self._pool is None:
                logger.info("[%s] Creating database connection pool...", self.name)
                try:
                    self._pool = await asyncio.wait_for(
                        get_asyncpg_pool(
                            min_size=1,
                            max_size=4,
                            command_timeout=60.0,
                        ),
                        timeout=timeout_s
                    )
                    logger.info("[%s] Database connection pool created", self.name)
                except asyncio.TimeoutError:
                    logger.error("[%s] Timeout creating database connection pool", self.name)
                    self._startup_status = "error: timeout creating pool"
                    return False

            # Create TaskRepository with the pool (not DSN)
            self._repo = TaskRepository(self._pool, dispatcher_name=self.name)

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

        # Try to initialize if not ready, but don't fail if it doesn't succeed immediately
        # The main loop will retry initialization and skip task processing until ready
        if self._startup_status != "ready":
            logger.info("[%s] Initializing before starting loop...", self.name)
            # Try initialization, but don't block - main loop will retry if needed
            try:
                await self.ready()
            except Exception as e:
                logger.warning("[%s] Initial initialization attempt failed, main loop will retry: %s", self.name, e)
                self._startup_status = "initializing"

        self._running = True
        logger.info("[%s] 🚀 Dispatcher loop starting (status: %s)", self.name, self._startup_status)

        loop = asyncio.get_event_loop()

        # Create daemons
        # Main loop will skip task processing until _startup_status == "ready"
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
                # Skip task processing until fully initialized
                if self._startup_status != "ready":
                    # Try to initialize if not already attempted
                    if self._startup_status == "initializing":
                        logger.debug("[%s] Still initializing, skipping task processing...", self.name)
                        await asyncio.sleep(2.0)  # Check every 2 seconds
                        continue
                    # If initialization failed, try again periodically
                    elif self._startup_status.startswith("error"):
                        logger.warning("[%s] Initialization failed (%s), retrying...", self.name, self._startup_status)
                        self._startup_status = "initializing"
                        if not await self.ready():
                            await asyncio.sleep(5.0)  # Wait longer before retry
                            continue
                    else:
                        # Unknown status, try to initialize
                        self._startup_status = "initializing"
                        if not await self.ready():
                            await asyncio.sleep(2.0)
                            continue

                # 1. Claim Batch (only if ready)
                batch = await self._repo.claim_batch(batch_size=self.claim_batch)

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
            try:
                if mode == "agent_tunnel" or conversation_id:
                    # Lazy initialization: create OrganismRouter only when first needed
                    if self._organism_router is None:
                        self._organism_router = OrganismRouter()
                    result = await self._organism_router.route_and_execute(payload)
                else:
                    # Standard routing through Coordinator
                    result = await self._router.route_and_execute(payload)
            except asyncio.TimeoutError as timeout_error:
                # Router call timed out - this is a retryable error
                logger.warning(
                    "[%s] ⏱️ Router timeout for task %s: %s",
                    self.name, task_id, timeout_error
                )
                result = {
                    "success": False,
                    "error": f"Router timeout: {str(timeout_error)}",
                    "kind": "timeout",
                    "path": "router_timeout",
                    "retry": True,  # Timeouts are retryable
                }
            except asyncio.CancelledError as cancelled_error:
                # Router call was cancelled - likely due to agent respawning or upstream cancellation
                logger.warning(
                    "[%s] 🛑 Router call cancelled for task %s: %s",
                    self.name, task_id, cancelled_error
                )
                result = {
                    "success": False,
                    "error": f"Router call cancelled: {str(cancelled_error)}",
                    "kind": "cancelled",
                    "path": "router_cancelled",
                    "retry": True,  # Cancellations due to respawning are retryable
                    "agent_status": "cancelled_or_respawning",
                }
            except Exception as router_error:
                # Catch any other exceptions from routers and convert to error result
                # This ensures the dispatcher never crashes due to router errors
                logger.error(
                    "[%s] ❌ Router exception for task %s: %s",
                    self.name, task_id, router_error, exc_info=True
                )
                result = {
                    "success": False,
                    "error": f"Router exception: {str(router_error)}",
                    "kind": "error",
                    "path": "router_exception"
                }

            # C. Normalize result to dict (defensive check)
            # Handle case where router returns a string, None, or other non-dict type
            # This is a critical safety check to prevent AttributeError on .get() calls
            # The router should always return a dict, but we defensively handle edge cases
            if not isinstance(result, dict):
                logger.error(
                    "[%s] ❌ Router returned non-dict result (type=%s, value=%s) for task %s",
                    self.name, type(result).__name__, str(result)[:200], task_id
                )
                # Convert any non-dict result to proper error dict format
                result = {
                    "success": False,
                    "error": str(result) if result is not None else "Router returned None",
                    "kind": "error",
                    "path": "router_type_error"
                }
            
            # D. Settle - Additional safeguard: ensure result is dict before accessing
            # This final check protects against any edge cases where result might not be a dict
            if not isinstance(result, dict):
                # This should never happen after normalization, but handle it defensively
                logger.critical(
                    "[%s] ❌ CRITICAL: Result is not a dict before access (type=%s) for task %s",
                    self.name, type(result).__name__, task_id
                )
                result = {
                    "success": False,
                    "error": f"Critical: Result is not a dict (type={type(result).__name__})",
                    "kind": "error",
                    "path": "result_type_critical_error"
                }
            
            # Now safely access result.get() - we've guaranteed result is a dict
            success = result.get("success")
            
            # Defensive check: log if success field is missing or invalid
            if success is None:
                logger.error(
                    "[%s] ❌ Coordinator returned result without 'success' field for task %s. "
                    "Result keys: %s, Result sample: %s",
                    self.name, task_id, list(result.keys())[:10], str(result)[:500]
                )
                # Treat missing success as failure
                success = False
                result["success"] = False
                if "error" not in result:
                    result["error"] = "coordinator_response_missing_success_field"
            
            if success:
                # Mark task as completed with result
                await self._repo.complete(task_id, result)
                logger.info("[%s] ✅ Task %s done", self.name, task_id)
            else:
                err = str(result.get("error") or "unknown_error")
                agent_status = result.get("agent_status")
                should_retry = result.get("retry", True)  # Default to retry unless explicitly False
                
                # Determine retry delay based on error type and agent status
                if agent_status == "respawning_or_unavailable":
                    # Agent is respawning - use longer delay to allow respawn to complete
                    delay_seconds = 30
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (agent respawning, delay=%ds)",
                        self.name, task_id, err, delay_seconds
                    )
                elif agent_status == "cancelled_or_respawning":
                    # Task was cancelled, likely due to respawning - use longer delay
                    delay_seconds = 30
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (cancelled/respawning, delay=%ds)",
                        self.name, task_id, err, delay_seconds
                    )
                elif result.get("kind") == "timeout":
                    # Timeout errors - use moderate delay
                    delay_seconds = 20
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (timeout, delay=%ds)",
                        self.name, task_id, err, delay_seconds
                    )
                elif not should_retry:
                    # Explicitly marked as non-retryable - fail the task
                    logger.warning(
                        "[%s] ❌ Task %s failed and marked as non-retryable: %s",
                        self.name, task_id, err
                    )
                    await self._repo.fail(task_id, err)
                    return  # Exit early, don't retry
                else:
                    # Default retry delay for other errors
                    delay_seconds = 15
                    logger.warning(
                        "[%s] 🔁 Task %s failed logic: %s (result keys: %s, delay=%ds)",
                        self.name, task_id, err, list(result.keys())[:10], delay_seconds
                    )
                
                # Only retry if should_retry is True
                if should_retry:
                    await self._repo.retry(task_id, err, delay_seconds=delay_seconds)
                else:
                    await self._repo.fail(task_id, err)

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

                # Skip lease renewal if not ready (no repo available)
                if self._startup_status != "ready" or self._repo is None:
                    continue

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
                
                # Skip requeue if not ready (no repo available)
                if self._startup_status != "ready" or self._repo is None:
                    continue
                
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
