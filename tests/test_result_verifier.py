from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

import seedcore.services.coordinator_service as cs
from seedcore.coordinator.result_verifier_dao import (
    DEFAULT_RESULT_VERIFIER_WATERMARK_ID,
    result_verifier_backoff_seconds,
)
from seedcore.models.replay import ReplayVerificationStatus
from seedcore.models.result_verifier_outcome import ResultVerifierOutcome
from seedcore.services.digital_twin_service import (
    DigitalTwinService,
    build_result_verifier_gate_failure_verdict,
)
from seedcore.services.result_verifier_engine import (
    ResultVerifierRetryableError,
    is_restricted_custody_transfer_record,
    map_replay_verification_to_outcome,
    verify_governed_audit_record,
)
from seedcore.services.result_verifier_runtime import ResultVerifierRuntime


class _AsyncContext:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _StubSession:
    def begin(self):
        return _AsyncContext(object())


class _StubSessionFactory:
    def __init__(self, session):
        self._session = session

    def __call__(self):
        return _AsyncContext(self._session)


def _build_runtime(metrics: MagicMock | None = None) -> ResultVerifierRuntime:
    coordinator = SimpleNamespace(
        _session_factory=_StubSessionFactory(_StubSession()),
        digital_twin_service=SimpleNamespace(),
        metrics=metrics,
    )
    return ResultVerifierRuntime(coordinator)


def test_backoff_sequence_matches_spec() -> None:
    assert result_verifier_backoff_seconds(0) == 30
    assert result_verifier_backoff_seconds(1) == 120
    assert result_verifier_backoff_seconds(2) == 600
    assert result_verifier_backoff_seconds(3) == 1800
    assert result_verifier_backoff_seconds(4) == 7200
    assert result_verifier_backoff_seconds(99) == 7200


def test_map_replay_verification_integrity_vs_trust() -> None:
    record = {
        "policy_receipt": {"policy_receipt_id": "pr1"},
        "action_intent": {"resource": {"asset_id": "a1"}},
    }
    eb = {"evidence_bundle_id": "eb1", "evidence_inputs": {"transition_receipts": []}}

    integrity = ReplayVerificationStatus(
        verified=False,
        tamper_status="signature_invalid",
        issues=["signature_bad"],
    )
    o1 = map_replay_verification_to_outcome(
        integrity, record=record, evidence_bundle=eb, transition_receipts=[]
    )
    assert o1.failure_class == "integrity"
    assert o1.twin_event_type == "verification_failed"
    assert o1.gate_reason_code == "result_verifier_verification_failed"

    trust = ReplayVerificationStatus(
        verified=False,
        tamper_status="incomplete",
        issues=["missing_policy_receipt"],
    )
    o2 = map_replay_verification_to_outcome(
        trust, record=record, evidence_bundle=eb, transition_receipts=[]
    )
    assert o2.failure_class == "trust"
    assert o2.twin_event_type == "verification_quarantined"
    assert o2.failure_code == "missing_policy_receipt"
    assert o2.gate_reason_code == "result_verifier_quarantined"


def test_map_replay_verification_promotes_explicit_replay_mismatch_reason() -> None:
    record = {
        "policy_receipt": {"policy_receipt_id": "pr1"},
        "action_intent": {"resource": {"asset_id": "a1"}},
    }
    eb = {"evidence_bundle_id": "eb1", "evidence_inputs": {"transition_receipts": []}}

    mismatch = ReplayVerificationStatus(
        verified=False,
        tamper_status="payload_mismatch",
        issues=["decision_graph_snapshot:snapshot_hash_mismatch"],
    )
    outcome = map_replay_verification_to_outcome(
        mismatch,
        record=record,
        evidence_bundle=eb,
        transition_receipts=[],
    )
    assert outcome.failure_class == "integrity"
    assert outcome.failure_code == "replay_mismatch"
    assert outcome.gate_reason_code == "result_verifier_replay_mismatch"


def test_map_replay_verification_does_not_promote_generic_rust_failure_to_replay_mismatch() -> None:
    record = {
        "policy_receipt": {"policy_receipt_id": "pr1"},
        "action_intent": {"resource": {"asset_id": "a1"}},
    }
    eb = {"evidence_bundle_id": "eb1", "evidence_inputs": {"transition_receipts": []}}

    transient = ReplayVerificationStatus(
        verified=False,
        tamper_status="incomplete",
        issues=["rust_replay_chain:rust_verify_replay_chain_timeout"],
        artifact_results={"rust_replay_chain": {"verified": False, "error_code": "rust_verify_replay_chain_timeout"}},
    )
    outcome = map_replay_verification_to_outcome(
        transient,
        record=record,
        evidence_bundle=eb,
        transition_receipts=[],
    )
    assert outcome.failure_class == "trust"
    assert outcome.failure_code == "rust_replay_chain:rust_verify_replay_chain_timeout"
    assert outcome.gate_reason_code == "result_verifier_quarantined"


def test_verify_governed_audit_record_raises_retryable_on_rust_timeout() -> None:
    record = {
        "policy_receipt": {"policy_receipt_id": "pr1"},
        "evidence_bundle": {"evidence_bundle_id": "eb1"},
        "action_intent": {"resource": {"asset_id": "a1"}},
    }
    status = ReplayVerificationStatus(
        verified=False,
        tamper_status="incomplete",
        issues=["rust_replay_chain:rust_verify_replay_chain_timeout"],
        artifact_results={"rust_replay_chain": {"verified": False, "error_code": "rust_verify_replay_chain_timeout"}},
    )

    with patch("seedcore.services.result_verifier_engine.ReplayService") as replay_cls:
        replay = replay_cls.return_value
        replay.verify_audit_record_for_result_verifier.return_value = (status, record["evidence_bundle"], record["policy_receipt"], [])
        with pytest.raises(ResultVerifierRetryableError, match="rust_verify_replay_chain_timeout"):
            verify_governed_audit_record(record)


@pytest.mark.asyncio
async def test_evaluate_result_verifier_gate_fail_closed_without_session_factory() -> None:
    svc = DigitalTwinService(session_factory=None, dao=MagicMock(), event_dao=MagicMock())
    verdict = await svc.evaluate_result_verifier_gate(twin_refs=[("asset", "asset:x1")])
    assert verdict["blocked"] is True
    assert verdict["reason_code"] == "result_verifier_gate_session_unavailable"
    assert verdict["checked_refs"] == 1


@pytest.mark.asyncio
async def test_evaluate_result_verifier_gate_fail_closed_when_dao_raises() -> None:
    dao = SimpleNamespace(
        get_authoritative_snapshots=AsyncMock(side_effect=RuntimeError("db unavailable")),
    )
    svc = DigitalTwinService(session_factory=_StubSessionFactory(_StubSession()), dao=dao, event_dao=MagicMock())
    verdict = await svc.evaluate_result_verifier_gate(twin_refs=[("asset", "asset:x1")])
    assert verdict["blocked"] is True
    assert verdict["reason_code"] == "result_verifier_gate_lookup_failed"


@pytest.mark.asyncio
async def test_evaluate_result_verifier_gate_uses_replay_mismatch_lockout_reason() -> None:
    dao = SimpleNamespace(
        get_authoritative_snapshots=AsyncMock(
            return_value={
                ("asset", "asset:x1"): {
                    "snapshot": {
                        "twin_kind": "asset",
                        "twin_id": "asset:x1",
                        "lifecycle_state": "VERIFICATION_FAILED",
                        "governance": {
                            "last_event_type": "verification_failed",
                            "lockouts": ["result_verifier_lockout"],
                            "result_verifier_lockout": {
                                "failure_code": "replay_mismatch",
                                "gate_reason_code": "result_verifier_replay_mismatch",
                            },
                        },
                    }
                }
            }
        ),
    )
    svc = DigitalTwinService(session_factory=_StubSessionFactory(_StubSession()), dao=dao, event_dao=MagicMock())
    verdict = await svc.evaluate_result_verifier_gate(twin_refs=[("asset", "asset:x1")])
    assert verdict["blocked"] is True
    assert verdict["reason_code"] == "result_verifier_replay_mismatch"
    assert "replay mismatch" in verdict["reason"].lower()


def test_build_result_verifier_gate_failure_verdict_includes_reason() -> None:
    v = build_result_verifier_gate_failure_verdict(
        reason_code="result_verifier_gate_eval_failed",
        checked_refs=2,
    )
    assert v["blocked"] is True
    assert v["reason_code"] == "result_verifier_gate_eval_failed"
    assert v["checked_refs"] == 2
    assert "fails closed" in v["reason"].lower()


def test_is_restricted_custody_transfer_record_gateway() -> None:
    rec = {
        "action_intent": {
            "action": {
                "parameters": {
                    "gateway": {"workflow_type": "restricted_custody_transfer"},
                }
            }
        }
    }
    assert is_restricted_custody_transfer_record(rec) is True


@pytest.mark.asyncio
async def test_apply_result_verifier_outcome_uses_session_for_authoritative_read() -> None:
    session = MagicMock()
    get_snap = AsyncMock(
        return_value={
            "snapshot": {
                "twin_kind": "asset",
                "twin_id": "asset:x1",
                "lifecycle_state": "IN_TRANSIT",
                "revision_stage": "AUTHORITATIVE",
                "identity": {"asset_id": "x1"},
                "custody": {"asset_id": "x1"},
                "governance": {},
                "evidence_refs": [],
            }
        }
    )
    dao = SimpleNamespace(get_authoritative_snapshot=get_snap, upsert_snapshot=AsyncMock(return_value={"ok": True}))
    event_dao = SimpleNamespace(append_event=AsyncMock())
    svc = DigitalTwinService(
        session_factory=MagicMock(),
        dao=dao,
        event_dao=event_dao,
    )

    outcome = ResultVerifierOutcome(
        verified=False,
        failure_code="sig",
        failure_class="integrity",
        twin_event_type="verification_failed",
        asset_id="x1",
        issues=["tamper"],
    )
    await svc.apply_result_verifier_outcome(
        outcome,
        task_id="550e8400-e29b-41d4-a716-446655440000",
        intent_id="intent-1",
        session=session,
    )
    get_snap.assert_awaited_once()
    assert get_snap.await_args.kwargs.get("twin_id") == "asset:x1"
    dao.upsert_snapshot.assert_awaited()


@pytest.mark.asyncio
async def test_apply_result_verifier_outcome_fallback_writes_transaction_twin() -> None:
    session = MagicMock()
    get_snap = AsyncMock(return_value=None)
    dao = SimpleNamespace(
        get_authoritative_snapshot=get_snap,
        upsert_snapshot=AsyncMock(return_value={"changed": True}),
    )
    event_dao = SimpleNamespace(append_event=AsyncMock())
    svc = DigitalTwinService(
        session_factory=MagicMock(),
        dao=dao,
        event_dao=event_dao,
    )
    outcome = ResultVerifierOutcome(
        verified=False,
        failure_code="sig",
        failure_class="integrity",
        twin_event_type="verification_failed",
        asset_id=None,
        issues=["tamper"],
    )
    result = await svc.apply_result_verifier_outcome_fallback(
        outcome,
        task_id="550e8400-e29b-41d4-a716-446655440000",
        intent_id="intent-x",
        session=session,
    )
    assert result["updated"] == 1
    assert get_snap.await_args.kwargs.get("twin_type") == "transaction"
    assert get_snap.await_args.kwargs.get("twin_id") == "transaction:intent-x"


@pytest.mark.asyncio
async def test_persist_terminal_counts_quarantine_metric_only_on_confirmed_mutation() -> None:
    metrics = MagicMock()
    runtime = _build_runtime(metrics=metrics)
    runtime._job_dao = SimpleNamespace(
        insert_outcome=AsyncMock(),
        mark_job_done=AsyncMock(),
    )
    dts = SimpleNamespace(
        apply_result_verifier_outcome=AsyncMock(return_value={"updated": 1}),
        apply_result_verifier_outcome_fallback=AsyncMock(return_value={"updated": 0}),
    )
    outcome = ResultVerifierOutcome(
        verified=False,
        failure_code="sig",
        failure_class="integrity",
        twin_event_type="verification_failed",
        asset_id="asset-1",
        issues=["tamper"],
    )
    await runtime._persist_terminal(
        session=MagicMock(),
        job_id=str(uuid.uuid4()),
        event_journal_id=str(uuid.uuid4()),
        outcome=outcome,
        dts=dts,
        apply_twin=True,
        task_id=str(uuid.uuid4()),
        intent_id="intent-1",
    )
    runtime._job_dao.insert_outcome.assert_awaited_once()
    runtime._job_dao.mark_job_done.assert_awaited_once()
    dts.apply_result_verifier_outcome_fallback.assert_not_called()
    metrics.increment_counter.assert_called_once_with("result_verifier_quarantine_mutations_total")


@pytest.mark.asyncio
async def test_persist_terminal_uses_fallback_when_asset_mutation_missing() -> None:
    metrics = MagicMock()
    runtime = _build_runtime(metrics=metrics)
    runtime._job_dao = SimpleNamespace(
        insert_outcome=AsyncMock(),
        mark_job_done=AsyncMock(),
    )
    dts = SimpleNamespace(
        apply_result_verifier_outcome=AsyncMock(return_value={"updated": 0, "reason": "missing_asset_id"}),
        apply_result_verifier_outcome_fallback=AsyncMock(return_value={"updated": 1}),
    )
    outcome = ResultVerifierOutcome(
        verified=False,
        failure_code="sig",
        failure_class="trust",
        twin_event_type="verification_quarantined",
        asset_id=None,
        issues=["missing_asset"],
    )
    await runtime._persist_terminal(
        session=MagicMock(),
        job_id=str(uuid.uuid4()),
        event_journal_id=str(uuid.uuid4()),
        outcome=outcome,
        dts=dts,
        apply_twin=True,
        task_id=str(uuid.uuid4()),
        intent_id="intent-fallback",
    )
    dts.apply_result_verifier_outcome_fallback.assert_awaited_once()
    runtime._job_dao.mark_job_done.assert_awaited_once()
    metrics.increment_counter.assert_called_once_with("result_verifier_quarantine_mutations_total")


@pytest.mark.asyncio
async def test_persist_terminal_hard_fails_when_no_subject_for_fail_closed() -> None:
    runtime = _build_runtime(metrics=MagicMock())
    runtime._job_dao = SimpleNamespace(
        insert_outcome=AsyncMock(),
        mark_job_done=AsyncMock(),
    )
    dts = SimpleNamespace(
        apply_result_verifier_outcome=AsyncMock(return_value={"updated": 0, "reason": "missing_asset_id"}),
        apply_result_verifier_outcome_fallback=AsyncMock(return_value={"updated": 0, "reason": "missing_subject_for_fail_closed"}),
    )
    outcome = ResultVerifierOutcome(
        verified=False,
        failure_code="sig",
        failure_class="integrity",
        twin_event_type="verification_failed",
        asset_id=None,
        issues=["missing_asset"],
    )
    with pytest.raises(RuntimeError, match="missing_subject_for_fail_closed"):
        await runtime._persist_terminal(
            session=MagicMock(),
            job_id=str(uuid.uuid4()),
            event_journal_id=str(uuid.uuid4()),
            outcome=outcome,
            dts=dts,
            apply_twin=True,
            task_id=str(uuid.uuid4()),
            intent_id=None,
        )
    runtime._job_dao.insert_outcome.assert_not_awaited()
    runtime._job_dao.mark_job_done.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_job_sets_terminal_missing_subject_error_code() -> None:
    metrics = MagicMock()
    runtime = _build_runtime(metrics=metrics)
    runtime._max_attempts = 6
    runtime._governance_dao = SimpleNamespace(
        get_latest_for_task=AsyncMock(
            return_value={
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "intent_id": "intent-1",
                "evidence_bundle": {"evidence_bundle_id": "eb1"},
                "action_intent": {"action": {"parameters": {"gateway": {"workflow_type": "restricted_custody_transfer"}}}},
            }
        ),
        get_latest_for_intent=AsyncMock(return_value=None),
    )
    runtime._job_dao = SimpleNamespace(
        schedule_retry=AsyncMock(),
    )
    runtime._persist_terminal = AsyncMock(side_effect=RuntimeError("missing_subject_for_fail_closed"))
    job = {
        "id": str(uuid.uuid4()),
        "event_journal_id": str(uuid.uuid4()),
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "intent_id": "intent-1",
        "attempt_count": 0,
    }
    dts = SimpleNamespace()
    with patch("seedcore.services.result_verifier_runtime.verify_governed_audit_record") as verify:
        verify.return_value = ResultVerifierOutcome(
            verified=False,
            failure_code="sig",
            failure_class="integrity",
            twin_event_type="verification_failed",
            asset_id=None,
            issues=["missing_asset"],
        )
        await runtime._process_one_job(MagicMock(), job, dts)
    runtime._job_dao.schedule_retry.assert_awaited_once()
    kwargs = runtime._job_dao.schedule_retry.await_args.kwargs
    assert kwargs["terminal"] is True
    assert kwargs["error_code"] == "missing_subject_for_fail_closed"


@pytest.mark.asyncio
async def test_process_job_retries_on_retryable_verifier_failure() -> None:
    metrics = MagicMock()
    runtime = _build_runtime(metrics=metrics)
    runtime._max_attempts = 6
    runtime._governance_dao = SimpleNamespace(
        get_latest_for_task=AsyncMock(
            return_value={
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "intent_id": "intent-1",
                "evidence_bundle": {"evidence_bundle_id": "eb1"},
                "action_intent": {"action": {"parameters": {"gateway": {"workflow_type": "restricted_custody_transfer"}}}},
            }
        ),
        get_latest_for_intent=AsyncMock(return_value=None),
    )
    runtime._job_dao = SimpleNamespace(
        schedule_retry=AsyncMock(),
    )
    runtime._persist_terminal = AsyncMock()
    job = {
        "id": str(uuid.uuid4()),
        "event_journal_id": str(uuid.uuid4()),
        "task_id": "550e8400-e29b-41d4-a716-446655440000",
        "intent_id": "intent-1",
        "attempt_count": 0,
    }
    dts = SimpleNamespace()
    with patch(
        "seedcore.services.result_verifier_runtime.verify_governed_audit_record",
        side_effect=ResultVerifierRetryableError("rust_verify_replay_chain_timeout"),
    ):
        await runtime._process_one_job(MagicMock(), job, dts)
    runtime._persist_terminal.assert_not_awaited()
    runtime._job_dao.schedule_retry.assert_awaited_once()
    kwargs = runtime._job_dao.schedule_retry.await_args.kwargs
    assert kwargs["terminal"] is False
    assert kwargs["error_code"] == "rust_verify_replay_chain_timeout"


@pytest.mark.asyncio
async def test_poll_journal_uses_durable_watermark_with_overlap_and_advances() -> None:
    runtime = _build_runtime(metrics=MagicMock())
    wm_ts = datetime(2026, 4, 7, 0, 0, 10, tzinfo=timezone.utc)
    wm_id = uuid.UUID("00000000-0000-0000-0000-000000000010")
    runtime._overlap_seconds = 5
    runtime._max_scan_pages = 4
    runtime._batch_size = 2
    runtime._job_dao = SimpleNamespace(
        get_runtime_watermark=AsyncMock(
            return_value={
                "stream_key": "digital_twin_event_journal",
                "watermark_recorded_at": wm_ts,
                "watermark_event_id": wm_id,
                "updated_at": None,
            }
        ),
        enqueue_job=AsyncMock(return_value=str(uuid.uuid4())),
        upsert_runtime_watermark=AsyncMock(),
    )
    page1 = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "task_id": str(uuid.uuid4()),
            "intent_id": "intent-1",
            "payload": {"snapshot": {"custody": {"asset_id": "asset-1"}}},
            "recorded_at": "2026-04-07T00:00:06+00:00",
            "twin_id": "asset:asset-1",
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "task_id": str(uuid.uuid4()),
            "intent_id": "intent-1",
            "payload": {"snapshot": {"custody": {"asset_id": "asset-1"}}},
            "recorded_at": "2026-04-07T00:00:09+00:00",
            "twin_id": "asset:asset-1",
        },
    ]
    page2 = [
        {
            "id": "00000000-0000-0000-0000-000000000020",
            "task_id": str(uuid.uuid4()),
            "intent_id": "intent-2",
            "payload": {"snapshot": {"custody": {"asset_id": "asset-2"}}},
            "recorded_at": "2026-04-07T00:00:11+00:00",
            "twin_id": "asset:asset-2",
        }
    ]
    runtime._event_dao = SimpleNamespace(
        list_events_for_result_verifier_poll=AsyncMock(side_effect=[page1, page2]),
    )
    await runtime._poll_journal_once(runtime._coordinator._session_factory)
    assert runtime._job_dao.enqueue_job.await_count == 3
    first_poll_kwargs = runtime._event_dao.list_events_for_result_verifier_poll.await_args_list[0].kwargs
    assert first_poll_kwargs["after_recorded_at"] == datetime(2026, 4, 7, 0, 0, 5, tzinfo=timezone.utc)
    assert first_poll_kwargs["after_id"] == DEFAULT_RESULT_VERIFIER_WATERMARK_ID
    runtime._job_dao.upsert_runtime_watermark.assert_awaited_once_with(
        ANY,
        stream_key="digital_twin_event_journal",
        watermark_recorded_at=datetime(2026, 4, 7, 0, 0, 11, tzinfo=timezone.utc),
        watermark_event_id=uuid.UUID("00000000-0000-0000-0000-000000000020"),
    )


@pytest.mark.asyncio
async def test_start_runtime_services_is_idempotent() -> None:
    runtime_stub = SimpleNamespace(start=MagicMock(), stop=AsyncMock())
    fake = SimpleNamespace(
        _runtime_services_lock=asyncio.Lock(),
        _runtime_services_started=False,
        _start_capability_monitor=AsyncMock(),
        _result_verifier_runtime=runtime_stub,
    )
    await cs.Coordinator.start_runtime_services(fake)
    await cs.Coordinator.start_runtime_services(fake)
    assert fake._runtime_services_started is True
    fake._start_capability_monitor.assert_awaited_once()
    runtime_stub.start.assert_called_once()


@pytest.mark.asyncio
async def test_stop_runtime_services_stops_runtime_and_resets_state() -> None:
    monitor_stub = SimpleNamespace(stop=AsyncMock())
    runtime_stub = SimpleNamespace(start=MagicMock(), stop=AsyncMock())
    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    fake = SimpleNamespace(
        _runtime_services_lock=asyncio.Lock(),
        _runtime_services_started=True,
        _result_verifier_runtime=runtime_stub,
        _capability_monitor=monitor_stub,
        _capability_monitor_task=done_task,
        _capability_retry_task=None,
    )
    fake._cancel_background_task = cs.Coordinator._cancel_background_task.__get__(fake, type(fake))
    await cs.Coordinator.stop_runtime_services(fake)
    runtime_stub.stop.assert_awaited_once()
    monitor_stub.stop.assert_awaited_once()
    assert fake._runtime_services_started is False
    assert fake._result_verifier_runtime is None
    assert fake._capability_monitor is None
    assert fake._capability_monitor_task is None


@pytest.mark.asyncio
async def test_call_backstops_runtime_start_when_lifespan_not_fired() -> None:
    request = SimpleNamespace(scope={}, receive=AsyncMock(), send=AsyncMock())
    fake = SimpleNamespace(
        start_runtime_services=AsyncMock(),
        app=AsyncMock(),
    )
    await cs.Coordinator.__call__(fake, request)
    fake.start_runtime_services.assert_awaited_once()
    fake.app.assert_awaited_once_with(request.scope, request.receive, request.send)
