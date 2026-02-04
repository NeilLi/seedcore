# seedcore/dispatcher/dispatcher_actor.py

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
import os
from typing import Dict, Any, Optional, List

import ray  # pyright: ignore[reportMissingImports]

from seedcore.dispatcher.persistence.interfaces import TaskRepositoryProtocol
from seedcore.dispatcher.router import CoordinatorHttpRouter, OrganismRouter
from seedcore.models import TaskPayload
from seedcore.models.result_schema import make_envelope, normalize_envelope
from seedcore.database import get_asyncpg_pool, PG_DSN
from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.dispatcher.config import MAX_ATTEMPTS

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
    # 0. Snapshot Scoping Enforcement (Server-Side)
    # ----------------------------
    async def _ensure_snapshot_id_for_batch(self, batch: List[Dict[str, Any]]) -> None:
        """
        Ensure all tasks in the batch have snapshot_id set (server-side enforcement).
        
        This is called by the Dispatcher (server-side) to enforce snapshot scoping
        for reproducible runs and multi-world isolation. Tasks without snapshot_id
        are updated with the active snapshot.
        
        Delegates to TaskRepository for database operations (DAO pattern).
        """
        if not batch or not self._repo:
            return
        
        try:
            # Extract task IDs without snapshot_id
            task_ids_without_snapshot = [
                str(row["id"]) for row in batch 
                if row.get("snapshot_id") is None
            ]
            
            if task_ids_without_snapshot:
                # Delegate to repository (DAO pattern)
                updated_count = await self._repo.enforce_snapshot_id_for_batch(task_ids_without_snapshot)
                if updated_count > 0:
                    logger.debug(
                        "[%s] Enforced snapshot_id for %d tasks in batch",
                        self.name,
                        updated_count
                    )
        except Exception as e:
            logger.warning(
                "[%s] Failed to enforce snapshot_id for batch: %s (non-fatal)",
                self.name,
                e
            )
            # Non-fatal - continue processing tasks even if snapshot update fails

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

                # 2. Ensure snapshot_id for claimed tasks (server-side enforcement)
                await self._ensure_snapshot_id_for_batch(batch)

                # 3. Spawn Workers
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
        # Get current attempt count (attempts is incremented when task is claimed)
        current_attempts = int(row.get("attempts", 0))

        try:
            # A. Parse
            payload = TaskPayload.from_db(row)
            conversation_id = payload.conversation_id
            mode = payload.interaction_mode
            
            # B. Check if this is a long-running planning task that needs immediate ACK
            # Planning tasks can take 60+ seconds and would timeout the dispatcher
            # EXCEPTION: Action tasks with required_specialization should use fast path, not planning
            routing = payload.params.get("routing", {}) if payload.params else {}
            has_required_specialization = bool(routing.get("required_specialization"))
            is_action_with_fast_path = (
                payload.type == "action" and has_required_specialization
            )
            
            is_planning_task = (
                not is_action_with_fast_path  # Fast-path action tasks are NOT planning tasks
                and (
                    payload.params.get("cognitive", {}).get("cog_type") == "task_planning"
                    or payload.params.get("cognitive", {}).get("decision_kind") == "planner"
                    or payload.params.get("cognitive", {}).get("decision_kind") == "cognitive"
                )
            )
            
            # C. Route and Execute
            # Use OrganismRouter for tasks with conversation_id (sticky sessions)
            # Otherwise use CoordinatorHttpRouter (standard routing)
            try:
                if mode == "agent_tunnel" or conversation_id:
                    # Lazy initialization: create OrganismRouter only when first needed
                    if self._organism_router is None:
                        self._organism_router = OrganismRouter()
                    raw_result = await self._organism_router.route_and_execute(payload)
                else:
                    # For planning tasks, use longer timeout or immediate ACK pattern
                    if is_planning_task:
                        logger.info(
                            f"[{self.name}] 🧠 Planning task {task_id} detected - "
                            "using extended timeout for cognitive processing"
                        )
                        # Planning tasks get extended timeout via router config
                        # Router timeout is already 90s, which should be sufficient
                        # If still timing out, we can implement async ACK pattern here
                    elif is_action_with_fast_path:
                        logger.info(
                            f"[{self.name}] ⚡ Fast-path action task {task_id} detected (type=action, "
                            f"required_specialization={routing.get('required_specialization')}) - "
                            "routing directly to fast path"
                        )
                    
                    # Standard routing through Coordinator
                    raw_result = await self._router.route_and_execute(payload)
                
                # Normalize router result to canonical envelope format
                result = normalize_envelope(raw_result, task_id=task_id, path="dispatcher")
                
            except asyncio.TimeoutError as timeout_error:
                # Router call timed out - this is a retryable error
                logger.warning(
                    "[%s] ⏱️ Router timeout for task %s: %s",
                    self.name, task_id, timeout_error
                )
                result = make_envelope(
                    task_id=task_id,
                    success=False,
                    error=f"Router timeout: {str(timeout_error)}",
                    error_type="timeout",
                    retry=True,
                    path="router_timeout",
                )
            except asyncio.CancelledError as cancelled_error:
                # Router call was cancelled - likely due to agent respawning or upstream cancellation
                logger.warning(
                    "[%s] 🛑 Router call cancelled for task %s: %s",
                    self.name, task_id, cancelled_error
                )
                result = make_envelope(
                    task_id=task_id,
                    success=False,
                    error=f"Router call cancelled: {str(cancelled_error)}",
                    error_type="cancelled",
                    retry=True,
                    meta={"agent_status": "cancelled_or_respawning"},
                    path="router_cancelled",
                )
            except Exception as router_error:
                # Catch any other exceptions from routers and convert to error result
                # This ensures the dispatcher never crashes due to router errors
                logger.error(
                    "[%s] ❌ Router exception for task %s: %s",
                    self.name, task_id, router_error, exc_info=True
                )
                result = make_envelope(
                    task_id=task_id,
                    success=False,
                    error=f"Router exception: {str(router_error)}",
                    error_type="router_exception",
                    path="router_exception",
                )
            
            # Now safely access result.get() - normalize_envelope guarantees canonical format
            success = result.get("success")
            
            # Defensive check: log if success field is missing (shouldn't happen after normalization)
            if success is None:
                logger.error(
                    "[%s] ❌ Result missing 'success' field after normalization for task %s. "
                    "Result keys: %s, Result sample: %s",
                    self.name, task_id, list(result.keys())[:10], str(result)[:500]
                )
                # Treat missing success as failure
                success = False
                result["success"] = False
                if "error" not in result:
                    result["error"] = "result_missing_success_field"
            
            if success:
                # Mark task as completed with result
                await self._repo.complete(task_id, result)
                logger.info("[%s] ✅ Task %s done", self.name, task_id)
            else:
                err = str(result.get("error") or "unknown_error")
                # agent_status is stored in meta dict, not top-level
                agent_status = result.get("meta", {}).get("agent_status")
                should_retry = result.get("retry", True)  # Default to retry unless explicitly False
                
                # Check if max attempts reached - fail immediately if exceeded
                if current_attempts >= MAX_ATTEMPTS:
                    final_error = f"Max attempts ({MAX_ATTEMPTS}) exceeded: {err}"
                    logger.error(
                        "[%s] ❌ Task %s failed after %d attempts (max: %d): %s",
                        self.name, task_id, current_attempts, MAX_ATTEMPTS, err
                    )
                    await self._repo.fail(task_id, final_error)
                    return  # Exit early, don't retry
                
                # Determine retry delay based on error type and agent status
                if agent_status == "respawning_or_unavailable":
                    # Agent is respawning - use longer delay to allow respawn to complete
                    delay_seconds = 30
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (attempt %d/%d, agent respawning, delay=%ds)",
                        self.name, task_id, err, current_attempts, MAX_ATTEMPTS, delay_seconds
                    )
                elif agent_status == "cancelled_or_respawning":
                    # Task was cancelled, likely due to respawning - use longer delay
                    delay_seconds = 30
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (attempt %d/%d, cancelled/respawning, delay=%ds)",
                        self.name, task_id, err, current_attempts, MAX_ATTEMPTS, delay_seconds
                    )
                elif result.get("error_type") == "timeout":
                    # Timeout errors - use moderate delay
                    delay_seconds = 20
                    logger.info(
                        "[%s] 🔁 Task %s failed: %s (attempt %d/%d, timeout, delay=%ds)",
                        self.name, task_id, err, current_attempts, MAX_ATTEMPTS, delay_seconds
                    )
                elif not should_retry:
                    # Explicitly marked as non-retryable - fail the task
                    logger.warning(
                        "[%s] ❌ Task %s failed and marked as non-retryable (attempt %d/%d): %s",
                        self.name, task_id, current_attempts, MAX_ATTEMPTS, err
                    )
                    await self._repo.fail(task_id, err)
                    return  # Exit early, don't retry
                else:
                    # Default retry delay for other errors
                    delay_seconds = 15
                    logger.warning(
                        "[%s] 🔁 Task %s failed logic: %s (attempt %d/%d, result keys: %s, delay=%ds)",
                        self.name, task_id, err, current_attempts, MAX_ATTEMPTS, list(result.keys())[:10], delay_seconds
                    )
                
                # Only retry if should_retry is True and we haven't exceeded max attempts
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
            logger.error("[%s] ❌ Task %s crashed: %s (attempt %d/%d)", self.name, task_id, e, current_attempts, MAX_ATTEMPTS)
            try:
                # Check if max attempts reached before retrying crash
                if current_attempts >= MAX_ATTEMPTS:
                    final_error = f"Max attempts ({MAX_ATTEMPTS}) exceeded after crash: {e}"
                    logger.error(
                        "[%s] ❌ Task %s failed after %d attempts due to crash: %s",
                        self.name, task_id, current_attempts, e
                    )
                    await self._repo.fail(task_id, final_error)
                else:
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
