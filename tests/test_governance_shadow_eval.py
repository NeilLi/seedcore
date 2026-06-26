from __future__ import annotations

import pytest
from pydantic import ValidationError

from seedcore.ml.distillation.governance_dataset import (
    FEATURE_NAMES,
    build_governance_dataset_rows,
    encode_governance_features,
    load_governance_advisory_dataset,
)
from seedcore.ml.distillation.governance_shadow_eval import (
    evaluate_predictions,
    evaluate_shadow_student,
)
from seedcore.ml.models.governance_student import GovernanceShadowStudent
from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1
from seedcore.models.governance_learning import (
    GovernanceEvidenceSummary,
    GovernanceFeatureVector,
    GovernanceLearningSampleV1,
)
from seedcore.ops.governance_learning.labeler import GovernanceAdvisoryLabeler


def test_teacher_label_mapping_for_core_window_h_cases() -> None:
    labeler = GovernanceAdvisoryLabeler()

    clean_allow = labeler.label(_sample("clean", "allow", "allowed", "verified", "clean_allow"))
    assert clean_allow.abstain is False
    assert clean_allow.abstain_reasons == []
    assert clean_allow.student_final_authority_usage == 0

    stale = labeler.label(
        _sample(
            "stale",
            "allow",
            "stale_context",
            "verified",
            "stale_context",
            telemetry_age_seconds=900,
        )
    )
    assert stale.abstain is True
    assert "fresh_context" in stale.missing_authority_context
    assert "stale_context" in stale.evidence_risk_flags

    mismatch = labeler.label(
        _sample("mismatch", "allow", "allowed", "verification_mismatch", "verification_mismatch")
    )
    assert mismatch.abstain is True
    assert "verified_result_closure" in mismatch.missing_authority_context
    assert "verification_mismatch" in mismatch.evidence_risk_flags

    missing_evidence = labeler.label(
        _sample(
            "missing-evidence",
            "quarantine",
            "missing_required_evidence",
            "verified",
            "quarantine",
        )
    )
    assert "evidence_closure" in missing_evidence.missing_authority_context
    assert "evidence_closure_risk" in missing_evidence.evidence_risk_flags

    missing_cosignature = labeler.label(
        _sample(
            "missing-cosignature",
            "quarantine",
            "missing_required_cosignature",
            "verified",
            "quarantine",
            requires_co_signature=True,
        )
    )
    assert "co_signature" in missing_cosignature.missing_authority_context

    coordinate = labeler.label(
        _sample(
            "coordinate",
            "deny",
            "coordinate_mismatch",
            "verified",
            "clean_deny",
            has_valid_coordinates=False,
        )
    )
    assert "authorized_location_scope" in coordinate.missing_authority_context
    assert "location_scope_risk" in coordinate.evidence_risk_flags


def test_governance_advisory_output_rejects_authority_usage() -> None:
    with pytest.raises(ValidationError):
        GovernanceAdvisoryOutputV1(
            reason_code="bad_authority",
            shadow_only=False,
        )
    with pytest.raises(ValidationError):
        GovernanceAdvisoryOutputV1(
            reason_code="bad_authority",
            final_authority=True,
        )
    with pytest.raises(ValidationError):
        GovernanceAdvisoryOutputV1(
            reason_code="bad_authority",
            student_final_authority_usage=1,
        )


def test_dataset_encoder_has_stable_feature_order_and_split() -> None:
    samples = [
        _sample("sample-a", "allow", "allowed", "verified", "clean_allow"),
        _sample("sample-b", "deny", "coordinate_mismatch", "verified", "clean_deny"),
        _sample("sample-c", "quarantine", "missing_required_evidence", "verified", "quarantine"),
    ]
    rows = build_governance_dataset_rows(samples)

    assert len(FEATURE_NAMES) == len(rows[0].features)
    assert rows[0].features == encode_governance_features(samples[0])

    split_a = load_governance_advisory_dataset(samples=samples, eval_fraction=0.5)
    split_b = load_governance_advisory_dataset(samples=samples, eval_fraction=0.5)
    assert split_a.feature_names == FEATURE_NAMES
    assert [row.sample_id for row in split_a.train] == [row.sample_id for row in split_b.train]
    assert [row.sample_id for row in split_a.eval] == [row.sample_id for row in split_b.eval]
    assert len(split_a.train) + len(split_a.eval) == len(samples)


def test_student_predictions_validate_and_unknown_rows_abstain() -> None:
    train_rows = build_governance_dataset_rows(
        [_sample("known-clean", "allow", "allowed", "verified", "clean_allow")]
    )
    student = GovernanceShadowStudent().fit(train_rows)

    known_prediction = student.predict_one(train_rows[0].features)
    assert isinstance(known_prediction, GovernanceAdvisoryOutputV1)
    assert known_prediction.abstain is False

    unknown_prediction = student.predict_one(tuple(value + 1000.0 for value in train_rows[0].features))
    assert isinstance(unknown_prediction, GovernanceAdvisoryOutputV1)
    assert unknown_prediction.abstain is True
    assert unknown_prediction.student_final_authority_usage == 0


def test_shadow_eval_flags_no_false_safe_on_critical_cases_and_zero_authority() -> None:
    rows = build_governance_dataset_rows(
        [
            _sample("clean-known", "allow", "allowed", "verified", "clean_allow"),
            _sample(
                "critical-coordinate",
                "deny",
                "coordinate_mismatch",
                "verified",
                "clean_deny",
                has_valid_coordinates=False,
            ),
            _sample(
                "critical-mismatch",
                "allow",
                "allowed",
                "verification_mismatch",
                "verification_mismatch",
                telemetry_age_seconds=20.0,
            ),
        ]
    )
    student = GovernanceShadowStudent().fit(rows)

    metrics = evaluate_shadow_student(student, rows)
    assert metrics.taxonomy_valid_rate == 1.0
    assert metrics.exact_reason_match_rate == 1.0
    assert metrics.false_safe_advisory_count == 0
    assert metrics.authority_usage_count == 0
    assert metrics.abstention_match_rate == 1.0


def test_shadow_eval_rejects_invalid_or_authority_bearing_predictions() -> None:
    row = build_governance_dataset_rows(
        [_sample("critical-missing", "quarantine", "missing_required_evidence", "verified", "quarantine")]
    )[0]

    with pytest.raises(ValueError, match="prediction is not a valid"):
        evaluate_predictions([row], [{"reason_code": ""}])

    with pytest.raises(ValidationError):
        GovernanceAdvisoryOutputV1(
            reason_code="bad_false_safe",
            abstain=False,
            final_authority=True,
        )


def _sample(
    sample_id: str,
    pdp_disposition: str,
    reason_code: str,
    verifier_outcome: str,
    verdict: str,
    *,
    trust_gap_codes: list[str] | None = None,
    obligations: list[dict] | None = None,
    telemetry_age_seconds: float = 10.0,
    has_valid_coordinates: bool = True,
    has_valid_signature: bool = True,
    requires_co_signature: bool = False,
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
        trust_gap_codes=trust_gap_codes or [],
        obligations=obligations or [],
        verifier_outcome=verifier_outcome,
        verdict=verdict,  # type: ignore[arg-type]
        features=GovernanceFeatureVector(
            telemetry_age_seconds=telemetry_age_seconds,
            has_valid_coordinates=has_valid_coordinates,
            has_valid_signature=has_valid_signature,
            has_matching_assets=True,
            device_enrolled=True,
            is_approved_zone=has_valid_coordinates,
            approval_envelope_present=True,
            declared_value_usd=100.0,
            requires_co_signature=requires_co_signature,
            trust_gap_count=len(trust_gap_codes or []),
            distance_to_boundary=300.0 - telemetry_age_seconds,
        ),
        evidence_summary=GovernanceEvidenceSummary(
            has_transition_receipts=True,
            has_policy_receipt=True,
            has_asset_fingerprint=True,
            signer_profile="production-profile",
            telemetry_count=1,
            media_count=0,
        ),
        created_at="2026-06-26T00:00:00Z",
    )
