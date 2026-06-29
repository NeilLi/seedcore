from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from seedcore.ml.distillation.governance_dataset import FEATURE_NAMES
from seedcore.ml.distillation.governance_shadow_eval import GovernanceShadowEvalMetrics
from seedcore.ml.distillation import sample_store
from seedcore.ml.ml_service import (
    predict_governance_advisory,
    train_governance_shadow_student,
)
from seedcore.ml.models.governance_student import GovernanceShadowStudent, set_active_shadow_student
from seedcore.models.governance_learning import (
    GovernanceEvidenceSummary,
    GovernanceFeatureVector,
    GovernanceLearningSampleV1,
)
from seedcore.models.pdp_hot_path import HotPathEvaluateRequest
from seedcore.ops import pdp_hot_path
from seedcore.ops.governance_learning.shadow_parity_log import (
    get_governance_shadow_advisory_logger,
    governance_shadow_db_file_path,
    governance_shadow_log_file_path,
    reset_governance_shadow_advisory_logger_for_tests,
)


@pytest.fixture(autouse=True)
def reset_shadow_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SEEDCORE_GOVERNANCE_SHADOW_LOG", str(tmp_path / "governance-shadow.jsonl"))
    monkeypatch.setenv("SEEDCORE_GOVERNANCE_SHADOW_DB", str(tmp_path / "governance-shadow.db"))
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_DB", str(tmp_path / "hot-path-parity.db"))
    monkeypatch.setenv("SEEDCORE_HOT_PATH_PARITY_LOG", str(tmp_path / "hot-path-parity.jsonl"))
    monkeypatch.setattr(sample_store, "DISTILLATION_DIR", tmp_path)
    monkeypatch.setattr(sample_store, "GOVERNANCE_SAMPLES_FILE", tmp_path / "governance_learning_samples.jsonl")
    reset_governance_shadow_advisory_logger_for_tests()
    pdp_hot_path._reset_governance_shadow_queue_for_tests()
    set_active_shadow_student(GovernanceShadowStudent())
    yield
    pdp_hot_path._reset_governance_shadow_queue_for_tests()
    reset_governance_shadow_advisory_logger_for_tests()
    set_active_shadow_student(GovernanceShadowStudent())


def test_governance_shadow_log_is_isolated_from_hot_path_parity_db(tmp_path) -> None:
    event = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed",
        "request_id": "req-shadow-1",
        "asset_ref": "asset-1",
        "false_safe_advisory": False,
        "student_final_authority_usage": 0,
    }

    get_governance_shadow_advisory_logger().append(event)

    assert governance_shadow_log_file_path().is_file()
    assert governance_shadow_db_file_path().is_file()
    assert not (tmp_path / "hot-path-parity.db").exists()
    stats = get_governance_shadow_advisory_logger().window_stats()
    assert stats["window_events"] == 1
    assert stats["completed"] == 1


@pytest.mark.asyncio
async def test_governance_advisory_endpoint_validates_feature_contract() -> None:
    prediction = await predict_governance_advisory({"features": [0.0] * len(FEATURE_NAMES)})

    assert prediction.shadow_only is True
    assert prediction.final_authority is False
    assert prediction.student_final_authority_usage == 0
    assert prediction.abstain is True

    with pytest.raises(HTTPException) as excinfo:
        await predict_governance_advisory({"features": [0.0] * (len(FEATURE_NAMES) - 1)})
    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_explicit_training_endpoint_accepts_safe_conservative_student() -> None:
    _write_governance_samples(
        [
            _sample("clean-a", "allow", "allowed", "verified", "clean_allow"),
            _sample("deny-b", "deny", "coordinate_mismatch", "verified", "clean_deny"),
            _sample("stale-c", "quarantine", "stale_telemetry", "verified", "stale_context"),
        ]
    )

    result = await train_governance_shadow_student({"eval_fraction": 0.34})

    assert result["accepted"] is True
    assert result["backend"] == "conservative_exact_row"
    assert result["metrics"]["authority_usage_count"] == 0
    assert result["metrics"]["false_safe_advisory_count"] == 0
    stats = get_governance_shadow_advisory_logger().window_stats()
    assert stats["completed"] == 1


@pytest.mark.asyncio
async def test_explicit_training_endpoint_refuses_false_safe_metrics(monkeypatch) -> None:
    _write_governance_samples([_sample("deny-only", "deny", "coordinate_mismatch", "verified", "clean_deny")])

    def _false_safe_eval(_student, _rows):
        return GovernanceShadowEvalMetrics(
            total=1,
            exact_reason_matches=0,
            taxonomy_valid_predictions=1,
            trust_gap_true_positive=0,
            trust_gap_false_positive=0,
            trust_gap_false_negative=0,
            abstention_matches=0,
            false_safe_advisory_count=1,
            authority_usage_count=0,
        )

    monkeypatch.setattr(
        "seedcore.ml.distillation.governance_shadow_eval.evaluate_shadow_student",
        _false_safe_eval,
    )

    with pytest.raises(HTTPException) as excinfo:
        await train_governance_shadow_student({"eval_fraction": 0.5})
    assert excinfo.value.status_code == 409
    assert get_governance_shadow_advisory_logger().window_stats()["failed"] == 1


def test_pdp_shadow_hook_does_not_change_authoritative_response(monkeypatch) -> None:
    req = _stale_hot_path_request()
    monkeypatch.delenv("SEEDCORE_ENABLE_GOVERNANCE_SHADOW_ADVISORY", raising=False)
    baseline = pdp_hot_path.evaluate_pdp_hot_path(req)

    monkeypatch.setenv("SEEDCORE_ENABLE_GOVERNANCE_SHADOW_ADVISORY", "true")
    monkeypatch.setenv("SEEDCORE_GOVERNANCE_SHADOW_ADVISORY_URL", "http://127.0.0.1:1/unavailable")
    shadowed = pdp_hot_path.evaluate_pdp_hot_path(req)

    assert shadowed.decision.model_dump() == baseline.decision.model_dump()
    assert shadowed.execution_token == baseline.execution_token
    assert shadowed.trust_gaps == baseline.trust_gaps
    assert shadowed.obligations == baseline.obligations


def test_pdp_shadow_queue_full_is_logged(monkeypatch) -> None:
    req = _stale_hot_path_request()
    response = pdp_hot_path.evaluate_pdp_hot_path(req)
    monkeypatch.setenv("SEEDCORE_ENABLE_GOVERNANCE_SHADOW_ADVISORY", "true")
    monkeypatch.setenv("SEEDCORE_GOVERNANCE_SHADOW_QUEUE_SIZE", "1")
    queue_obj = pdp_hot_path._get_governance_shadow_queue()
    queue_obj.put_nowait({"held": True})

    pdp_hot_path._enqueue_governance_shadow_advisory(request=req, response=response)

    stats = get_governance_shadow_advisory_logger().window_stats()
    assert stats["queue_full"] == 1


def test_pdp_shadow_job_logs_failure_and_false_safe(monkeypatch) -> None:
    item = {
        "request_id": "req-shadow-job",
        "asset_ref": "asset-shadow",
        "advisory_url": "http://shadow.test",
        "features": [0.0] * len(FEATURE_NAMES),
        "pdp": {"disposition": "quarantine", "reason_code": "stale_telemetry", "trust_gaps": ["stale_telemetry"]},
    }

    def _false_safe_post(*, url, features):
        return {"reason_code": "student_allow", "abstain": False}

    monkeypatch.setattr(pdp_hot_path, "_post_governance_shadow_advisory", _false_safe_post)
    pdp_hot_path._run_governance_shadow_advisory_job(item)
    assert get_governance_shadow_advisory_logger().window_stats()["false_safe_advisory_count"] == 1

    def _malformed_post(*, url, features):
        return {"reason_code": ""}

    monkeypatch.setattr(pdp_hot_path, "_post_governance_shadow_advisory", _malformed_post)
    pdp_hot_path._run_governance_shadow_advisory_job(item)
    assert get_governance_shadow_advisory_logger().window_stats()["failed"] == 1


def _write_governance_samples(samples: list[GovernanceLearningSampleV1]) -> None:
    sample_store.GOVERNANCE_SAMPLES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sample_store.GOVERNANCE_SAMPLES_FILE.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.model_dump(mode="json"), separators=(",", ":")) + "\n")


def _sample(
    sample_id: str,
    pdp_disposition: str,
    reason_code: str,
    verifier_outcome: str,
    verdict: str,
) -> GovernanceLearningSampleV1:
    return GovernanceLearningSampleV1(
        sample_id=sample_id,
        request_id=f"req-{sample_id}",
        intent_id=f"intent-{sample_id}",
        replay_ref=f"replay://{sample_id}",
        evidence_bundle_id=f"bundle-{sample_id}",
        policy_snapshot_hash="sha256:policy",
        decision_graph_snapshot_hash="sha256:graph",
        pdp_disposition=pdp_disposition,
        reason_code=reason_code,
        verifier_outcome=verifier_outcome,
        verdict=verdict,  # type: ignore[arg-type]
        features=GovernanceFeatureVector(
            telemetry_age_seconds=10.0,
            has_valid_coordinates=pdp_disposition != "deny",
            has_valid_signature=True,
            has_matching_assets=True,
            device_enrolled=True,
            is_approved_zone=pdp_disposition != "deny",
            approval_envelope_present=True,
            declared_value_usd=100.0,
            distance_to_boundary=290.0,
        ),
        evidence_summary=GovernanceEvidenceSummary(
            has_transition_receipts=True,
            has_policy_receipt=True,
            has_asset_fingerprint=True,
            signer_profile="production-profile",
            telemetry_count=1,
        ),
        created_at="2026-06-29T00:00:00Z",
    )


def _stale_hot_path_request() -> HotPathEvaluateRequest:
    return HotPathEvaluateRequest(
        contract_version="pdp.hot_path.asset_transfer.v1",
        request_id="req-stale-shadow",
        requested_at="2026-06-29T00:00:00Z",
        policy_snapshot_ref="snapshot:test",
        action_intent={
            "intent_id": "intent-stale-shadow",
            "timestamp": "2026-06-29T00:00:00Z",
            "valid_until": "2026-06-29T00:05:00Z",
            "principal": {
                "agent_id": "agent-test",
                "role_profile": "TRANSFER_COORDINATOR",
                "session_token": "session-test",
            },
            "action": {
                "type": "TRANSFER_CUSTODY",
                "operation": "MOVE",
                "parameters": {"approval_context": {"approval_envelope_id": "approval-1"}},
                "security_contract": {"hash": "sha256:contract", "version": "v1"},
            },
            "resource": {
                "asset_id": "asset-shadow",
                "target_zone": "zone-b",
                "provenance_hash": "sha256:prov",
            },
        },
        asset_context={
            "asset_ref": "asset-shadow",
            "current_custodian_ref": "custodian-a",
            "current_zone": "zone-a",
        },
        telemetry_context={
            "observed_at": "2026-06-29T00:00:00Z",
            "freshness_seconds": 999,
            "max_allowed_age_seconds": 10,
            "current_zone": "zone-a",
            "current_coordinate_ref": "coord-a",
            "evidence_refs": ["telemetry-1"],
        },
    )
