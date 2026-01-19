import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock database dependencies before importing Dispatcher
# This allows database imports to work without real database connections
# The import has side effects (modifies sys.modules), so it must be imported
import mock_database_dependencies  # noqa: F401

# Mock Ray dependencies before importing Dispatcher
# This allows @ray.remote decorated classes to be instantiated directly
# The import has side effects (modifies sys.modules), so it must be imported
import mock_ray_dependencies  # noqa: F401

# IMPORTANT:
# Import the module, not just the class, so we can monkeypatch module-level symbols like MAX_ATTEMPTS
from seedcore.dispatcher.queue_dispatcher import Dispatcher


@pytest.mark.asyncio
async def test_ready_success_creates_pool_repo_and_router():
    d = Dispatcher(name="test-dispatcher")

    fake_pool = MagicMock()

    # mock get_asyncpg_pool + TaskRepository constructor
    # Note: patch where it's used (queue_dispatcher), not where it's defined (database)
    with patch("seedcore.dispatcher.queue_dispatcher.get_asyncpg_pool", new=AsyncMock(return_value=fake_pool)), \
         patch("seedcore.dispatcher.queue_dispatcher.CoordinatorHttpRouter") as RouterMock, \
         patch("seedcore.dispatcher.persistence.task_repository.TaskRepository") as RepoMock:

        ok = await d.ready(timeout_s=1.0)

        assert ok is True
        assert d._pool == fake_pool
        assert d._repo is not None
        assert d._router is not None
        assert d._startup_status == "ready"

        RepoMock.assert_called_once()
        RouterMock.assert_called_once()


@pytest.mark.asyncio
async def test_ready_timeout_sets_error_status():
    d = Dispatcher(name="test-dispatcher")

    async def slow_pool(*args, **kwargs):
        await asyncio.sleep(999)

    # Note: patch where it's used (queue_dispatcher), not where it's defined (database)
    with patch("seedcore.dispatcher.queue_dispatcher.get_asyncpg_pool", new=slow_pool):
        ok = await d.ready(timeout_s=0.01)

        assert ok is False
        assert d._startup_status.startswith("error: timeout creating pool")


@pytest.mark.asyncio
async def test_ensure_snapshot_id_for_batch_calls_repo_when_missing_snapshot():
    d = Dispatcher(name="test-dispatcher")
    d._repo = AsyncMock()

    batch = [
        {"id": "t1", "snapshot_id": None},
        {"id": "t2", "snapshot_id": "snap-123"},
        {"id": "t3", "snapshot_id": None},
    ]

    d._repo.enforce_snapshot_id_for_batch = AsyncMock(return_value=2)

    await d._ensure_snapshot_id_for_batch(batch)

    d._repo.enforce_snapshot_id_for_batch.assert_awaited_once_with(["t1", "t3"])


@pytest.mark.asyncio
async def test_ensure_snapshot_id_for_batch_no_repo_noop():
    d = Dispatcher(name="test-dispatcher")
    d._repo = None

    batch = [{"id": "t1", "snapshot_id": None}]
    await d._ensure_snapshot_id_for_batch(batch)  # should not crash


@pytest.mark.asyncio
async def test_process_task_success_marks_complete():
    d = Dispatcher(name="test-dispatcher")
    d._repo = AsyncMock()
    d._router = AsyncMock()

    # Mock payload parsing
    fake_payload = MagicMock()
    fake_payload.conversation_id = None
    fake_payload.interaction_mode = None

    row = {"id": "task-1", "attempts": 0}

    with patch("seedcore.dispatcher.queue_dispatcher.TaskPayload.from_db", return_value=fake_payload), \
         patch("seedcore.dispatcher.queue_dispatcher.normalize_envelope",
               return_value={"task_id": "task-1", "success": True}):

        d._router.route_and_execute = AsyncMock(return_value={"success": True})

        await d._process_task(row)

        d._repo.complete.assert_awaited_once()
        d._repo.retry.assert_not_awaited()
        d._repo.fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_task_router_timeout_retries_with_delay_20():
    d = Dispatcher(name="test-dispatcher")
    d._repo = AsyncMock()
    d._router = AsyncMock()

    fake_payload = MagicMock()
    fake_payload.conversation_id = None
    fake_payload.interaction_mode = None

    row = {"id": "task-2", "attempts": 1}

    with patch("seedcore.dispatcher.queue_dispatcher.TaskPayload.from_db", return_value=fake_payload), \
         patch("seedcore.dispatcher.queue_dispatcher.make_envelope") as make_env:

        # router throws timeout
        d._router.route_and_execute = AsyncMock(side_effect=asyncio.TimeoutError("boom"))

        # emulate make_envelope output
        make_env.return_value = {
            "task_id": "task-2",
            "success": False,
            "error": "Router timeout: boom",
            "error_type": "timeout",
            "retry": True,
            "meta": {},
        }

        await d._process_task(row)

        d._repo.retry.assert_awaited_once()
        args, kwargs = d._repo.retry.await_args
        assert args[0] == "task-2"
        assert kwargs["delay_seconds"] == 20


@pytest.mark.asyncio
async def test_process_task_non_retryable_failure_calls_fail():
    d = Dispatcher(name="test-dispatcher")
    d._repo = AsyncMock()
    d._router = AsyncMock()

    fake_payload = MagicMock()
    fake_payload.conversation_id = None
    fake_payload.interaction_mode = None

    row = {"id": "task-3", "attempts": 0}

    with patch("seedcore.dispatcher.queue_dispatcher.TaskPayload.from_db", return_value=fake_payload), \
         patch("seedcore.dispatcher.queue_dispatcher.normalize_envelope",
               return_value={
                   "task_id": "task-3",
                   "success": False,
                   "error": "bad input",
                   "retry": False,
                   "meta": {},
               }):

        d._router.route_and_execute = AsyncMock(return_value={"error": "bad input"})

        await d._process_task(row)

        d._repo.fail.assert_awaited_once_with("task-3", "bad input")
        d._repo.retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_task_max_attempts_exceeded_fails_immediately(monkeypatch):
    """
    If current_attempts >= MAX_ATTEMPTS, dispatcher should fail immediately and not retry.
    """
    d = Dispatcher(name="test-dispatcher")
    d._repo = AsyncMock()
    d._router = AsyncMock()

    # Force MAX_ATTEMPTS low for the test
    monkeypatch.setattr("seedcore.dispatcher.queue_dispatcher.MAX_ATTEMPTS", 2)

    fake_payload = MagicMock()
    fake_payload.conversation_id = None
    fake_payload.interaction_mode = None

    row = {"id": "task-4", "attempts": 2}

    with patch("seedcore.dispatcher.queue_dispatcher.TaskPayload.from_db", return_value=fake_payload), \
         patch("seedcore.dispatcher.queue_dispatcher.normalize_envelope",
               return_value={
                   "task_id": "task-4",
                   "success": False,
                   "error": "still failing",
                   "retry": True,
                   "meta": {},
               }):

        d._router.route_and_execute = AsyncMock(return_value={"error": "still failing"})

        await d._process_task(row)

        d._repo.fail.assert_awaited_once()
        d._repo.retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_lease_daemon_cancels_task_when_lease_lost():
    d = Dispatcher(name="test-dispatcher")
    d._running = True
    d._startup_status = "ready"
    d.lease_interval = 0.01

    d._repo = AsyncMock()
    d._repo.renew_lease = AsyncMock(return_value=False)

    # Create a long-running task and register it
    async def long_work():
        await asyncio.sleep(999)

    t = asyncio.create_task(long_work())
    d._tasks_in_progress["task-lease"] = t

    daemon_task = asyncio.create_task(d._lease_daemon())

    # Let daemon run once
    await asyncio.sleep(0.05)

    # stop daemon
    d._running = False
    daemon_task.cancel()

    assert t.cancelled() or t.cancelled() is True or t.done()

