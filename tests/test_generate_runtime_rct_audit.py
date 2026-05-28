from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts" / "host") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts" / "host"))

import generate_runtime_rct_audit as generator  # noqa: E402


class _BeginCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _SessionCtx:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _allow_response(payload: dict) -> dict:
    request_id = payload["request_id"]
    snapshot = payload["policy_snapshot_ref"]
    return {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": request_id,
        "decided_at": "2026-05-28T10:00:01Z",
        "latency_ms": 1,
        "decision": {
            "allowed": True,
            "disposition": "allow",
            "reason_code": "restricted_custody_transfer_allowed",
            "reason": "all mandatory checks passed",
            "policy_snapshot_ref": snapshot,
            "policy_snapshot_hash": "sha256:" + "1" * 64,
        },
        "required_approvals": [],
        "trust_gaps": [],
        "obligations": [],
        "minted_artifacts": ["PolicyReceipt"],
        "governed_receipt": {
            "audit_id": "11111111-1111-4111-8111-111111111111",
            "asset_ref": payload["asset"]["asset_id"],
            "policy_receipt_id": f"policy-receipt:{request_id}",
            "decision_hash": "sha256:" + "2" * 64,
            "snapshot_hash": "sha256:" + "1" * 64,
            "policy_snapshot_hash": "sha256:" + "1" * 64,
            "decision_graph_snapshot_hash": "sha256:" + "1" * 64,
        },
    }


def test_build_payloads_are_deterministic_and_unique() -> None:
    now = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc)
    first_id = generator.build_run_id(prefix="local-rct-test", index=1)
    second_id = generator.build_run_id(prefix="local-rct-test", index=2)

    assert first_id == "local-rct-test-001"
    assert second_id == "local-rct-test-002"

    first = generator.build_evaluate_payload(
        run_id=first_id,
        policy_snapshot_ref="snapshot:test",
        now=now,
    )
    repeated = generator.build_evaluate_payload(
        run_id=first_id,
        policy_snapshot_ref="snapshot:test",
        now=now,
    )
    second = generator.build_evaluate_payload(
        run_id=second_id,
        policy_snapshot_ref="snapshot:test",
        now=now,
    )

    assert first == repeated
    assert first["request_id"] != second["request_id"]
    assert first["idempotency_key"] != second["idempotency_key"]

    closure = generator.build_closure_payload(run_id=first_id, evaluate_payload=first, now=now)
    assert closure["request_id"] == first["request_id"]
    assert closure["closure_id"] == "closure-local-rct-test-001"


def test_require_allow_evaluate_rejects_missing_or_non_allow_decisions() -> None:
    with pytest.raises(generator.RuntimeRctAuditError):
        generator.require_allow_evaluate({})
    with pytest.raises(generator.RuntimeRctAuditError):
        generator.require_allow_evaluate({"decision": {"disposition": "quarantine"}})

    generator.require_allow_evaluate({"decision": {"disposition": "allow"}})


@pytest.mark.asyncio
async def test_dao_fallback_writes_replay_fields(monkeypatch) -> None:
    captured: dict = {}

    class _FakeAuditDAO:
        async def append_record(self, session, **kwargs):
            captured.update(kwargs)
            return {"entry_id": "22222222-2222-4222-8222-222222222222"}

    session = SimpleNamespace(begin=lambda: _BeginCtx())
    session.execute = AsyncMock()
    payload = generator.build_evaluate_payload(
        run_id="local-rct-test-001",
        policy_snapshot_ref="snapshot:test",
        now=datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
    )
    closure = generator.build_closure_payload(
        run_id="local-rct-test-001",
        evaluate_payload=payload,
        now=datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc),
    )

    result = await generator.append_dao_fallback(
        evaluate_payload=payload,
        evaluate_response=_allow_response(payload),
        closure_payload=closure,
        run_id="local-rct-test-001",
        session_factory=lambda: _SessionCtx(session),
        audit_dao=_FakeAuditDAO(),
    )

    assert result["audit_id"] == "22222222-2222-4222-8222-222222222222"
    assert captured["record_type"] == "execution_receipt"
    assert captured["intent_id"] == payload["request_id"]
    assert captured["policy_receipt"]["policy_receipt_id"]
    assert captured["evidence_bundle"]["evidence_bundle_id"] == closure["evidence_bundle_id"]
    assert captured["policy_decision"]["governed_receipt"]["decision_hash"]
    assert captured["policy_case"]["workflow_hints"] == {
        "workflow_type": "restricted_custody_transfer",
        "strict_state_transition_fields": True,
    }
    session.execute.assert_awaited_once()
