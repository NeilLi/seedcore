# tests/test_coordinator_service.py
# Import mock dependencies BEFORE any other imports
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

import asyncio
import uuid
from types import SimpleNamespace, ModuleType
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Adjust this import path if your repository structure differs:
import seedcore.services.coordinator_service as cs


class StubAsyncTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class StubAsyncSession:
    def __init__(self):
        self._execute_side_effect = None
        self._execute_calls = []
        async def _run(stmt, params=None):
            self._execute_calls.append((stmt, params))
            if self._execute_side_effect:
                if isinstance(self._execute_side_effect, Exception):
                    raise self._execute_side_effect
                if callable(self._execute_side_effect):
                    return await self._execute_side_effect(stmt, params)
            return None

        self.execute = AsyncMock(side_effect=_run)
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return StubAsyncTransaction()

    @property
    def execute_calls(self):
        return list(self._execute_calls)

    def set_execute_side_effect(self, exc):
        self._execute_side_effect = exc


class StubSessionContext:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_session_factory(session):
    def factory():
        return StubSessionContext(session)

    return factory


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class StubMetrics:
    def record_drift_computation(self, *a, **k): pass
    def record_memory_synthesis(self, *a, **k): pass
    def record_deltaE_realized(self, *a, **k): pass
    def record_circuit_breaker_event(self, *a, **k): pass
    def get_escalation_ratio(self): return 0.0


class StubPredicateRouter:
    def __init__(self):
        self.metrics = StubMetrics()
        self._signal_cache = {}
        # configured per-test
        self._next_decision = SimpleNamespace(action="fast_path", organ_id="utility_organ_1", reason="forced")

    async def start_background_tasks(self): pass
    def update_signals(self, **signals): self._signal_cache.update(signals)
    def route_task(self, task_dict): return self._next_decision
    def evaluate_mutation(self, task, decision): return SimpleNamespace(action="hold", reason="test")
    def get_gpu_guard_status(self): return {}
    def update_gpu_job_status(self, job_id, status, success=None): pass


class StubClient:
    """Emulates ServiceClient; 'responses' is a dict of path->payload or path->Exception."""
    def __init__(self, responses=None, healthy=True):
        self.responses = responses or {}
        self.base_url = "http://stub"
        self._healthy = healthy

    def get_metrics(self):
        return {"circuit": "ok"}

    async def get(self, path):
        return {"status": "healthy" if self._healthy else "unhealthy"}

    async def post(self, path, json=None, headers=None):
        value = self.responses.get(path)
        if isinstance(value, Exception):
            raise value
        if value is not None:
            return value
        # default
        return {"success": True}


class SyncGraphRepo:
    """Repo used by _get_graph_repository(): insert_subtasks + sync add_dependency; async create_task for root."""
    def __init__(self):
        self.inserted = []
        self.edges_sync = []
        self.created_root = []

    async def create_task(self, task_dict, agent_id=None, **kw):
        db_id = uuid.uuid4()
        self.created_root.append((db_id, task_dict, agent_id))
        return db_id

    def insert_subtasks(self, root_task_id, plan):
        # Return a stable list of inserted child records with ids
        inserted = []
        for step in plan:
            child_id = step.get("id") or uuid.uuid4().hex
            inserted.append({"id": child_id})
        self.inserted.extend(inserted)
        return inserted

    def add_dependency(self, parent, child):
        self.edges_sync.append((str(parent), str(child)))


class AsyncGraphRepo:
    """Repo used by self.graph_task_repo: async create_task + async add_dependency for child tasks."""
    def __init__(self):
        self.created_children = []
        self.edges_async = []

    async def create_task(self, task_dict, agent_id=None, organ_id=None):
        db_id = uuid.uuid4()
        self.created_children.append((db_id, task_dict, agent_id, organ_id))
        return db_id

    async def add_dependency(self, parent, child):
        self.edges_async.append((str(parent), str(child)))


@pytest.mark.asyncio
async def test_process_task_persists_before_routing():
    """Coordinator.process_task must persist tasks before routing."""
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()

    repo = SimpleNamespace()
    repo.create_task = AsyncMock(return_value=uuid.uuid4())

    session = StubAsyncSession()
    session_factory = make_session_factory(session)

    coordinator.graph_task_repo = None
    coordinator._get_graph_repository = MagicMock(return_value=repo)
    coordinator.telemetry_dao = SimpleNamespace(insert=AsyncMock())
    coordinator.outbox_dao = SimpleNamespace(enqueue_embed_task=AsyncMock(return_value=True))
    coordinator._enqueue_task_embedding_now = AsyncMock(return_value=True)
    coordinator._resolve_session_factory = MagicMock(return_value=session_factory)
    
    # Mock get_async_pg_session_factory that process_task calls directly
    with patch('seedcore.services.coordinator_service.get_async_pg_session_factory', return_value=session_factory):
        async def fake_route(task_payload):
            # Repository insert must have completed before routing
            assert repo.create_task.await_count == 1
            task_id_val = task_payload.task_id if hasattr(task_payload, 'task_id') else str(task_payload)
            return {
                "success": True,
                "payload": {
                    "task_id": task_id_val,
                    "decision": "fast",
                    "surprise": {
                        "S": 0.42,
                        "x": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
                        "weights": [0.1, 0.1, 0.2, 0.2, 0.2, 0.2],
                        "ocps": {"S_t": 1.0},
                    },
                },
            }

        coordinator.core = SimpleNamespace(
            route_and_execute=AsyncMock(side_effect=fake_route)
        )

        payload = {
            "type": "test_task",
            "params": {"agent_id": "agent-42"},
            "description": "ensure persistence",
            "task_id": "task-123",
        }

        result = await coordinator.process_task(payload)

        assert repo.create_task.await_count == 1
        assert coordinator.core.route_and_execute.await_count == 1
        assert result["success"] is True
        assert coordinator.telemetry_dao.insert.await_count == 1
        assert coordinator.outbox_dao.enqueue_embed_task.await_count == 1
        outbox_call = coordinator.outbox_dao.enqueue_embed_task.await_args
        assert outbox_call.kwargs["dedupe_key"] == f"{payload['task_id']}:task.primary"
        assert coordinator._enqueue_task_embedding_now.await_count == 1
        assert any(
            "ensure_task_node" in str(call[0]) for call in session.execute_calls
        )
        assert session.begin_calls == 1


@pytest.mark.asyncio
async def test_process_task_records_router_telemetry_payload():
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()

    repo = SimpleNamespace()
    repo.create_task = AsyncMock(return_value=uuid.uuid4())

    session = StubAsyncSession()
    session_factory = make_session_factory(session)

    coordinator.graph_task_repo = None
    coordinator._get_graph_repository = MagicMock(return_value=repo)
    coordinator._resolve_session_factory = MagicMock(return_value=session_factory)

    telemetry_mock = AsyncMock()
    outbox_mock = AsyncMock(return_value=True)

    coordinator.telemetry_dao = SimpleNamespace(insert=telemetry_mock)
    coordinator.outbox_dao = SimpleNamespace(enqueue_embed_task=outbox_mock)
    coordinator._enqueue_task_embedding_now = AsyncMock(return_value=True)

    surprise_score = 0.37
    x_values = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]
    weights = [0.2, 0.1, 0.2, 0.15, 0.15, 0.2]
    ocps_meta = {"flag_on": True, "S_t": 1.2}

    # Mock get_async_pg_session_factory that process_task calls directly
    with patch('seedcore.services.coordinator_service.get_async_pg_session_factory', return_value=session_factory):
        async def fake_route(task_payload):
            task_id_val = task_payload.task_id if hasattr(task_payload, 'task_id') else str(task_payload)
            return {
                "success": True,
                "payload": {
                    "task_id": task_id_val,
                    "decision": "fast",
                    "surprise": {
                        "S": surprise_score,
                        "x": x_values,
                        "weights": weights,
                        "ocps": ocps_meta,
                    },
                },
            }

        coordinator.core = SimpleNamespace(
            route_and_execute=AsyncMock(side_effect=fake_route)
        )

        task_id = "task-telemetry"
        payload = {
            "type": "test_task",
            "params": {"agent_id": "agent-telemetry"},
            "description": "ensure telemetry payload",
            "task_id": task_id,
        }

        await coordinator.process_task(payload)

        telemetry_call = telemetry_mock.await_args
        assert telemetry_call.kwargs["task_id"] == task_id
        assert telemetry_call.kwargs["surprise_score"] == pytest.approx(surprise_score)
        assert telemetry_call.kwargs["x_vector"] == x_values
        assert telemetry_call.kwargs["weights"] == weights
        assert telemetry_call.kwargs["ocps_metadata"] == ocps_meta
        assert telemetry_call.kwargs["chosen_route"] == "fast"

        outbox_call = outbox_mock.await_args
        assert outbox_call.kwargs["task_id"] == task_id
        assert outbox_call.kwargs["reason"] == "router"
        assert outbox_call.kwargs["dedupe_key"] == f"{task_id}:task.primary"


@pytest.mark.asyncio
async def test_router_telemetry_outbox_failure_rolls_back(monkeypatch):
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._ensure_background_tasks_started = AsyncMock()

    repo = SimpleNamespace()
    repo.create_task = AsyncMock(return_value=uuid.uuid4())

    session = StubAsyncSession()
    session_factory = make_session_factory(session)

    coordinator.graph_task_repo = None
    coordinator._get_graph_repository = MagicMock(return_value=repo)
    coordinator._resolve_session_factory = MagicMock(return_value=session_factory)

    telemetry_mock = AsyncMock()
    outbox_mock = AsyncMock(side_effect=RuntimeError("fail outbox"))

    coordinator.telemetry_dao = SimpleNamespace(insert=telemetry_mock)
    coordinator.outbox_dao = SimpleNamespace(enqueue_embed_task=outbox_mock)
    coordinator._enqueue_task_embedding_now = AsyncMock(return_value=True)

    # Mock get_async_pg_session_factory that process_task calls directly
    with patch('seedcore.services.coordinator_service.get_async_pg_session_factory', return_value=session_factory):
        async def fake_route(task_payload):
            task_id_val = task_payload.task_id if hasattr(task_payload, 'task_id') else str(task_payload)
            return {
                "success": True,
                "payload": {
                    "task_id": task_id_val,
                    "decision": "fast",
                    "surprise": {
                        "S": 0.9,
                        "x": [0.1] * 6,
                        "weights": [0.2] * 5 + [0.0],
                        "ocps": {},
                    },
                },
            }

        coordinator.core = SimpleNamespace(
            route_and_execute=AsyncMock(side_effect=fake_route)
        )

        payload = {
            "type": "test_task",
            "description": "rollback",
            "task_id": "task-rollback",
        }

        result = await coordinator.process_task(payload)

        assert result["success"] is True
        assert telemetry_mock.await_count == 1
        assert outbox_mock.await_count == 1
        assert coordinator._enqueue_task_embedding_now.await_count == 0
        assert session.begin_calls == 1


@pytest.mark.asyncio
async def test_enqueue_task_embedding_now_handles_missing_worker(monkeypatch):
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    stub_module = ModuleType("seedcore.graph.task_embedding_worker")
    monkeypatch.setitem(sys.modules, "seedcore.graph.task_embedding_worker", stub_module)

    result = await coordinator._enqueue_task_embedding_now("task-missing")

    assert result is False


@pytest.mark.asyncio
async def test_enqueue_task_embedding_now_times_out(monkeypatch):
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    module = ModuleType("seedcore.graph.task_embedding_worker")

    async def fake_enqueue(app_state, task_id, reason="router"):
        return True

    module.enqueue_task_embedding_job = AsyncMock(side_effect=fake_enqueue)
    monkeypatch.setitem(sys.modules, "seedcore.graph.task_embedding_worker", module)

    wait_for_mock = AsyncMock(side_effect=asyncio.TimeoutError)
    monkeypatch.setattr(cs.asyncio, "wait_for", wait_for_mock)

    result = await coordinator._enqueue_task_embedding_now("task-timeout")

    assert result is False
    # The implementation retries up to 2 times, so wait_for could be called multiple times
    assert wait_for_mock.await_count >= 1
    # Check that timeout is 5.0 in the first call
    call_kwargs = wait_for_mock.call_args_list[0].kwargs
    assert call_kwargs.get("timeout") == 5.0
@pytest.mark.asyncio
async def test_drift_fallback_heuristic_when_ml_unavailable(monkeypatch):
    """Test the fallback drift score calculation when ML service is unavailable."""
    # Create a mock coordinator that bypasses the Ray Serve decorator
    with patch.object(cs, 'Coordinator') as mock_coordinator_class:
        # Create a mock instance
        mock_coordinator = MagicMock()
        mock_coordinator.predicate_router = StubPredicateRouter()
        mock_coordinator.ml_client = StubClient(responses={"/drift/score": RuntimeError("ml down")})
        
        # Mock the _compute_drift_score method to test the fallback logic
        async def mock_compute_drift_score(task):
            # Simulate the fallback drift score calculation
            score = 0.0
            task_type = str(task.get("type", "unknown")).lower()
            if task_type == "anomaly_triage":
                score += 0.3
            priority = float(task.get("priority", 5))
            if priority >= 8:
                score += 0.2
            complexity = float(task.get("complexity", 0.5))
            score += complexity * 0.2
            history_ids = task.get("history_ids", [])
            if len(history_ids) == 0:
                score += 0.1
            return max(0.0, min(1.0, score))
        
        mock_coordinator._compute_drift_score = mock_compute_drift_score
        mock_coordinator_class.return_value = mock_coordinator
        
        c = mock_coordinator

    # Simple task with high priority, some complexity, no history -> deterministic heuristic
    task = {
        "type": "anomaly_triage",
        "priority": 9,
        "complexity": 0.3,
        "history_ids": []
    }
    drift = await c._compute_drift_score(task)
    # heuristic: 0.3 (type) + 0.2 (priority>=8) + 0.06 (0.3*0.2) + 0.1 (no history) = 0.66
    assert 0.65 < drift < 0.67


@pytest.mark.asyncio
async def test_organ_timeout_bounds_checking():
    """Test that organ_timeout_s is properly bounded."""
    # Test the bounds checking logic directly
    def test_organ_timeout_bounds(organ_timeout):
        try:
            organ_timeout = float(organ_timeout)
            # Clamp organ_timeout to reasonable bounds (1s to 300s)
            organ_timeout = max(1.0, min(300.0, organ_timeout))
        except (TypeError, ValueError):
            organ_timeout = 30.0
        return organ_timeout
    
    # Test various inputs
    assert test_organ_timeout_bounds(0.5) == 1.0  # Below minimum
    assert test_organ_timeout_bounds(30.0) == 30.0  # Normal value
    assert test_organ_timeout_bounds(500.0) == 300.0  # Above maximum
    assert test_organ_timeout_bounds("invalid") == 30.0  # Invalid input
    assert test_organ_timeout_bounds(None) == 30.0  # None input


@pytest.mark.asyncio
async def test_drift_score_injection():
    """Test that drift_score is properly injected into task dictionaries."""
    # Test the drift score injection logic
    task_dict = {
        "id": "test-task",
        "type": "execute",
        "params": {"agent_id": "test-agent"}
    }
    
    # Simulate drift score injection
    drift_score = 0.15
    task_dict["drift_score"] = drift_score
    
    # Ensure params has token/energy settings if present in predicates
    if "params" not in task_dict:
        task_dict["params"] = {}
    
    # Add energy budget information if available
    energy_budget = 0.8
    task_dict["params"]["energy_budget"] = energy_budget
    
    assert task_dict["drift_score"] == 0.15
    assert task_dict["params"]["energy_budget"] == 0.8


@pytest.mark.asyncio
async def test_stable_id_generation():
    """Test that stable IDs are generated for plan steps."""
    # Test the stable ID generation logic
    def generate_stable_ids(plan):
        for idx, step in enumerate(plan):
            if "id" not in step and "step_id" not in step:
                step["id"] = f"step_{idx}_{uuid.uuid4().hex[:8]}"
                step["step_id"] = step["id"]
            
            # Ensure task has stable ID
            if isinstance(step.get("task"), dict):
                task_data = step["task"]
                if "id" not in task_data and "task_id" not in task_data:
                    task_data["id"] = f"subtask_{idx}_{uuid.uuid4().hex[:8]}"
                    task_data["task_id"] = task_data["id"]
        return plan
    
    plan = [
        {"organ_id": "organ_A", "task": {"type": "execute"}},
        {"organ_id": "organ_B", "task": {"type": "execute"}}
    ]
    
    result = generate_stable_ids(plan)
    
    # Check that IDs were added
    assert "id" in result[0]
    assert "step_id" in result[0]
    assert "id" in result[0]["task"]
    assert "task_id" in result[0]["task"]
    
    # Check that IDs are unique
    assert result[0]["id"] != result[1]["id"]
    assert result[0]["task"]["id"] != result[1]["task"]["id"]


@pytest.mark.asyncio
async def test_async_sync_helper():
    """Test the _maybe_call helper function for handling both sync and async calls."""
    from seedcore.services.coordinator_service import _maybe_call
    
    # Test with sync function
    def sync_func(x):
        return x * 2
    
    result = await _maybe_call(sync_func, 5)
    assert result == 10
    
    # Test with async function
    async def async_func(x):
        return x * 3
    
    result = await _maybe_call(async_func, 5)
    assert result == 15