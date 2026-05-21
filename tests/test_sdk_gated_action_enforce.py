from __future__ import annotations

import pytest
import threading

from seedcore.sdk import (
    gated_action,
    reset_evaluator,
    using_evaluator,
    GatedActionEvaluationError,
)
from tests.test_gated_action_sdk import _make_valid_intent


@pytest.fixture(autouse=True)
def clean_evaluator_state():
    """Automatically resets the registered evaluator and executor between test runs."""
    reset_evaluator()
    yield
    reset_evaluator()


def test_shadow_mode_forces_no_execute_and_skips_business_logic():
    execution_counter = 0

    def mock_evaluator(payload):
        assert payload["options"]["no_execute"] is True
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "governed_receipt": {"audit_id": "audit-shadow"},
        }

    @gated_action(policy="strict_custody", mode="shadow")
    def shadow_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "business_success"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator):
        result = shadow_action(intent)
        assert result.decision == "allow"
        assert result.audit_id == "audit-shadow"
        assert result.execution_token_id is None
        assert result.execution_result is None
        assert execution_counter == 0


def test_enforce_mode_sets_no_execute_false_and_executes_business_logic_on_allow():
    execution_counter = 0

    def mock_evaluator(payload):
        assert payload["options"]["no_execute"] is False
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "governed_receipt": {"audit_id": "audit-enforce"},
            "execution_token": {"token_id": "token-enforce-123"},
        }

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "business_success"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator, lambda payload: None):
        result = enforce_action(intent)
        assert result.decision == "allow"
        assert result.audit_id == "audit-enforce"
        assert result.execution_token_id == "token-enforce-123"
        assert result.execution_result == "business_success"
        assert execution_counter == 1


def test_enforce_mode_requires_execution_token_before_business_logic():
    execution_counter = 0

    def mock_evaluator(payload):
        assert payload["options"]["no_execute"] is False
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "governed_receipt": {"audit_id": "audit-missing-token"},
        }

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "should_not_run"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator, lambda payload: None):
        with pytest.raises(GatedActionEvaluationError, match="requires an ExecutionToken"):
            enforce_action(intent)

    assert execution_counter == 0


def test_enforce_mode_requires_executor_before_business_logic():
    execution_counter = 0

    def mock_evaluator(payload):
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "execution_token": {"token_id": "token-ok"},
        }

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "should_not_run"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator):
        with pytest.raises(GatedActionEvaluationError, match="requires an executor"):
            enforce_action(intent)

    assert execution_counter == 0


def test_enforce_mode_does_not_execute_business_logic_on_deny_or_quarantine():
    execution_counter = 0

    def mock_evaluator(payload):
        return {
            "decision": {"disposition": "quarantine", "reason_code": "trust_gap_detected"},
            "governed_receipt": {"audit_id": "audit-quarantine"},
        }

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "should_not_run"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator):
        result = enforce_action(intent)
        assert result.decision == "quarantine"
        assert result.execution_token_id is None
        assert result.execution_result is None
        assert execution_counter == 0


def test_enforce_mode_triggers_executor_closure_on_allow():
    execution_counter = 0
    executor_called = False
    captured_payload = None

    def mock_evaluator(payload):
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "execution_token": {"token_id": "token-ok"},
        }

    def mock_executor(payload):
        nonlocal executor_called, captured_payload
        executor_called = True
        captured_payload = payload

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        nonlocal execution_counter
        execution_counter += 1
        return "done"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator, mock_executor):
        result = enforce_action(intent)
        assert result.decision == "allow"
        assert result.execution_result == "done"
        assert execution_counter == 1
        assert executor_called is True
        assert captured_payload is not None
        assert captured_payload["options"]["no_execute"] is False


def test_enforce_mode_raises_error_if_closure_fails():
    def mock_evaluator(payload):
        return {
            "decision": {"disposition": "allow", "reason_code": "allowed"},
            "execution_token": {"token_id": "token-ok"},
        }

    def failing_executor(payload):
        raise RuntimeError("Gateway connection failed during closure")

    @gated_action(policy="strict_custody", mode="enforce")
    def enforce_action(intent: dict):
        return "done"

    intent = _make_valid_intent()

    with using_evaluator(mock_evaluator, failing_executor):
        with pytest.raises(GatedActionEvaluationError, match="Post-execution closure failed"):
            enforce_action(intent)


def test_context_manager_thread_local_executor_isolation():
    barrier = threading.Barrier(2)
    execution_results = {}

    def run_thread(name: str, evaluator_disposition: str, should_call_executor: bool):
        executor_called = False

        def eval_fn(payload):
            return {
                "decision": {"disposition": evaluator_disposition, "reason_code": name},
                "execution_token": {"token_id": f"token-{name}"},
            }

        def exec_fn(payload):
            nonlocal executor_called
            executor_called = True

        @gated_action(policy="strict_custody", mode="enforce")
        def governed_fn(intent: dict):
            return f"res-{name}"

        with using_evaluator(eval_fn, exec_fn):
            barrier.wait(timeout=5)
            result = governed_fn(_make_valid_intent())
            execution_results[name] = {
                "decision": result.decision,
                "execution_result": result.execution_result,
                "executor_called": executor_called,
            }

    t1 = threading.Thread(target=run_thread, args=("thread-allow", "allow", True))
    t2 = threading.Thread(target=run_thread, args=("thread-deny", "deny", False))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert execution_results["thread-allow"] == {
        "decision": "allow",
        "execution_result": "res-thread-allow",
        "executor_called": True,
    }
    assert execution_results["thread-deny"] == {
        "decision": "deny",
        "execution_result": None,
        "executor_called": False,
    }
