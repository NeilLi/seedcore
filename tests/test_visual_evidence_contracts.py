from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from seedcore.models.visual_evidence import (
    VisualEvidenceComparisonV0,
    VisualEvidenceObservationV0,
    VisualEvidenceReplayContextV0,
    canonical_json_sha256,
    compute_capture_binding_hash,
    compute_comparison_payload_hash,
)
from seedcore.services.visual_evidence_replay import replay_visual_evidence

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "visual_evidence_v0" / "cases.json"
)


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _observation(
    payload: dict[str, Any], *, preserve_hash: bool = False
) -> VisualEvidenceObservationV0:
    observation = VisualEvidenceObservationV0.model_validate(payload)
    if preserve_hash:
        return observation
    return observation.model_copy(
        update={"capture_binding_hash": compute_capture_binding_hash(observation)}
    )


def _comparison(payload: dict[str, Any]) -> VisualEvidenceComparisonV0:
    comparison = VisualEvidenceComparisonV0.model_validate(payload)
    return comparison.model_copy(
        update={"payload_sha256": compute_comparison_payload_hash(comparison)}
    )


def test_canonical_hash_vector_is_stable() -> None:
    assert canonical_json_sha256({"b": 2, "a": 1}) == (
        "sha256:43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )


def test_visual_contracts_are_strict_and_timezone_bound(
    manifest: dict[str, Any],
) -> None:
    invalid = deepcopy(manifest["observed_observation"])
    invalid["unexpected_authority"] = True
    with pytest.raises(ValidationError):
        VisualEvidenceObservationV0.model_validate(invalid)

    invalid_comparison = deepcopy(manifest["comparison"])
    invalid_comparison["reason_codes"] = ["MODEL_SAYS_PROBABLY_FINE"]
    with pytest.raises(ValidationError):
        VisualEvidenceComparisonV0.model_validate(invalid_comparison)

    invalid_comparison = deepcopy(manifest["comparison"])
    invalid_comparison["quality_disposition"] = "insufficient"
    with pytest.raises(ValidationError):
        VisualEvidenceComparisonV0.model_validate(invalid_comparison)

    invalid_comparison = deepcopy(manifest["comparison"])
    invalid_comparison.update(
        {
            "outcome": "MISMATCH",
            "reason_codes": ["TELEMETRY_STALE"],
        }
    )
    with pytest.raises(ValidationError, match="stable mismatch reason code"):
        VisualEvidenceComparisonV0.model_validate(invalid_comparison)

    invalid_comparison = deepcopy(manifest["comparison"])
    invalid_comparison.update(
        {
            "outcome": "INSUFFICIENT_COVERAGE",
            "quality_disposition": "insufficient",
            "reason_codes": [],
        }
    )
    with pytest.raises(ValidationError, match="requires its stable reason code"):
        VisualEvidenceComparisonV0.model_validate(invalid_comparison)

    invalid = deepcopy(manifest["observed_observation"])
    invalid["observed_at"] = "2026-08-20T10:10:00"
    with pytest.raises(ValidationError):
        VisualEvidenceObservationV0.model_validate(invalid)


def test_fixture_manifest_freezes_all_fifteen_review_cases(
    manifest: dict[str, Any],
) -> None:
    case_ids = [case["case_id"] for case in manifest["cases"]]
    assert len(case_ids) == 15
    assert len(set(case_ids)) == 15
    assert case_ids[0] == "happy_match"
    assert case_ids[-1] == "visual_match_with_expired_approval"


@pytest.mark.parametrize("case_index", range(15))
def test_visual_replay_fixture_matrix(
    manifest: dict[str, Any],
    case_index: int,
) -> None:
    case = manifest["cases"][case_index]
    baseline_payload = _deep_merge(
        manifest["baseline_observation"], case.get("baseline_patch", {})
    )
    observed_payload = _deep_merge(
        manifest["observed_observation"], case.get("observed_patch", {})
    )
    comparison_payload = _deep_merge(
        manifest["comparison"], case.get("comparison_patch", {})
    )
    context_payload = _deep_merge(manifest["context"], case.get("context_patch", {}))

    baseline = _observation(baseline_payload)
    observed = _observation(
        observed_payload,
        preserve_hash=bool(case.get("preserve_capture_binding")),
    )
    comparison = _comparison(comparison_payload)
    context = VisualEvidenceReplayContextV0.model_validate(context_payload)

    result = replay_visual_evidence(
        baseline=baseline,
        observed=observed,
        comparison=comparison,
        context=context,
    )

    assert result.evidence_disposition.value == case["expected_disposition"], case[
        "case_id"
    ]
    assert list(result.reason_codes) == case["expected_reason_codes"], case["case_id"]
    assert result.authority_effect == "none"
    assert result.action_authorized is False
    assert result.model_rerun_required is False


def test_valid_match_is_evidence_only(manifest: dict[str, Any]) -> None:
    baseline = _observation(manifest["baseline_observation"])
    observed = _observation(manifest["observed_observation"])
    comparison = _comparison(manifest["comparison"])
    context = VisualEvidenceReplayContextV0.model_validate(manifest["context"])

    result = replay_visual_evidence(
        baseline=baseline,
        observed=observed,
        comparison=comparison,
        context=context,
    )

    assert result.evidence_disposition.value == "accepted"
    assert result.binding_verified is True
    assert result.action_authorized is False


@pytest.mark.parametrize(
    ("baseline_patch", "expected_disposition", "expected_reason_code"),
    (
        (
            {"client_integrity": {"verifier_disposition": "invalid"}},
            "deny",
            "VISUAL_CAPTURE_BINDING_INVALID",
        ),
        (
            {"physical_anchor_ref": {"binding_disposition": "invalid"}},
            "quarantine",
            "DYNAMIC_NFC_PROOF_INVALID",
        ),
        (
            {"capture_quality": {"coverage_disposition": "unknown"}},
            "review_required",
            "VISUAL_CAPTURE_INSUFFICIENT_COVERAGE",
        ),
    ),
)
def test_registration_baseline_integrity_is_fail_closed(
    manifest: dict[str, Any],
    baseline_patch: dict[str, Any],
    expected_disposition: str,
    expected_reason_code: str,
) -> None:
    baseline = _observation(
        _deep_merge(manifest["baseline_observation"], baseline_patch)
    )
    observed = _observation(manifest["observed_observation"])
    comparison = _comparison(manifest["comparison"])
    context = VisualEvidenceReplayContextV0.model_validate(manifest["context"])

    result = replay_visual_evidence(
        baseline=baseline,
        observed=observed,
        comparison=comparison,
        context=context,
    )

    assert result.evidence_disposition.value == expected_disposition
    assert result.reason_codes[0] == expected_reason_code
    assert result.action_authorized is False
