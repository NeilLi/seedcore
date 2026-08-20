"""Deterministic replay validation for recorded rare-shoe visual evidence."""

from __future__ import annotations

from collections.abc import Iterable

from seedcore.models.visual_evidence import (
    VisualEvidenceComparisonV0,
    VisualEvidenceDisposition,
    VisualEvidenceObservationV0,
    VisualEvidenceOutcome,
    VisualEvidenceReplayContextV0,
    VisualEvidenceReplayResultV0,
    compute_capture_binding_hash,
    compute_comparison_payload_hash,
)


def _result(
    comparison: VisualEvidenceComparisonV0,
    disposition: VisualEvidenceDisposition,
    reason_codes: Iterable[str],
    *,
    binding_verified: bool,
) -> VisualEvidenceReplayResultV0:
    return VisualEvidenceReplayResultV0(
        evidence_disposition=disposition,
        reason_codes=tuple(dict.fromkeys(reason_codes)),
        observation_outcome=comparison.outcome,
        binding_verified=binding_verified,
    )


def _capture_integrity_failure(
    observation: VisualEvidenceObservationV0,
    comparison: VisualEvidenceComparisonV0,
) -> tuple[VisualEvidenceDisposition, tuple[str, ...]] | None:
    """Return the first fail-closed integrity result for either capture phase."""

    if observation.client_integrity.verifier_disposition != "verified":
        return (
            VisualEvidenceDisposition.DENY,
            ("VISUAL_CAPTURE_BINDING_INVALID",),
        )

    if (
        observation.physical_anchor_ref.required
        and observation.physical_anchor_ref.binding_disposition != "verified"
    ):
        return (
            VisualEvidenceDisposition.QUARANTINE,
            ("DYNAMIC_NFC_PROOF_INVALID",),
        )

    quality_values = (
        observation.capture_quality.coverage_disposition,
        observation.capture_quality.blur_disposition,
        observation.capture_quality.scale_disposition,
        observation.capture_quality.calibration_disposition,
    )
    if "fail" in quality_values or "unknown" in quality_values:
        return (
            VisualEvidenceDisposition.REVIEW_REQUIRED,
            tuple(
                dict.fromkeys(
                    (
                        "VISUAL_CAPTURE_INSUFFICIENT_COVERAGE",
                        *comparison.reason_codes,
                    )
                )
            ),
        )

    return None


def replay_visual_evidence(
    *,
    baseline: VisualEvidenceObservationV0,
    observed: VisualEvidenceObservationV0,
    comparison: VisualEvidenceComparisonV0,
    context: VisualEvidenceReplayContextV0,
) -> VisualEvidenceReplayResultV0:
    """Replay exact recorded artifacts without rerunning probabilistic models.

    The returned record is evidence-only and always has ``authority_effect``
    set to ``none`` and ``action_authorized`` set to ``False``.
    """

    expected_assets = {baseline.asset_id, observed.asset_id, comparison.asset_id}
    expected_workflows = {
        baseline.workflow_join_key,
        observed.workflow_join_key,
        comparison.workflow_join_key,
    }
    if expected_assets != {context.expected_asset_id} or expected_workflows != {
        context.expected_workflow_join_key
    }:
        return _result(
            comparison,
            VisualEvidenceDisposition.QUARANTINE,
            ("CROSS_ASSET_REPLAY",),
            binding_verified=False,
        )

    phase_and_time_valid = (
        baseline.capture_phase.value == "registration"
        and observed.capture_phase.value in {"handoff", "delivery"}
        and observed.observed_at >= baseline.observed_at
    )
    if not phase_and_time_valid:
        return _result(
            comparison,
            VisualEvidenceDisposition.DENY,
            ("VISUAL_CAPTURE_BINDING_INVALID",),
            binding_verified=False,
        )

    refs_match = (
        comparison.baseline_evidence_ref == baseline.evidence_id
        and comparison.observed_evidence_ref == observed.evidence_id
    )
    hashes_match = (
        compute_capture_binding_hash(baseline) == baseline.capture_binding_hash
        and compute_capture_binding_hash(observed) == observed.capture_binding_hash
        and compute_comparison_payload_hash(comparison) == comparison.payload_sha256
    )
    if not refs_match or not hashes_match:
        return _result(
            comparison,
            VisualEvidenceDisposition.DENY,
            ("VISUAL_CAPTURE_BINDING_INVALID",),
            binding_verified=False,
        )

    if (
        not baseline.raw_capture_manifest.raw_preserved
        or not observed.raw_capture_manifest.raw_preserved
    ):
        return _result(
            comparison,
            VisualEvidenceDisposition.QUARANTINE,
            ("VISUAL_RAW_CAPTURE_MISSING",),
            binding_verified=True,
        )

    if (
        baseline.processing.generative_fill_used
        or observed.processing.generative_fill_used
    ):
        return _result(
            comparison,
            VisualEvidenceDisposition.QUARANTINE,
            ("VISUAL_GENERATIVE_TRANSFORM_DETECTED",),
            binding_verified=True,
        )

    capture_profiles = {
        baseline.capture_quality.profile_ref,
        observed.capture_quality.profile_ref,
    }
    segmentation_profiles = {
        baseline.processing.segmentation_profile,
        observed.processing.segmentation_profile,
    }
    reconstruction_profiles = {
        baseline.processing.reconstruction_profile,
        observed.processing.reconstruction_profile,
    }
    fingerprint_profiles = {
        baseline.fingerprint.fingerprint_profile_ref,
        observed.fingerprint.fingerprint_profile_ref,
    }
    admitted_profiles = (
        capture_profiles <= context.admitted_capture_profiles
        and segmentation_profiles <= context.admitted_segmentation_profiles
        and reconstruction_profiles <= context.admitted_reconstruction_profiles
        and fingerprint_profiles <= context.admitted_fingerprint_profiles
        and comparison.comparison_profile_ref in context.admitted_comparison_profiles
    )
    if not admitted_profiles:
        return _result(
            comparison,
            VisualEvidenceDisposition.DENY,
            ("VISUAL_PIPELINE_PROFILE_NOT_ADMITTED",),
            binding_verified=True,
        )

    calibrated = (
        comparison.confidence_summary.calibration_profile_ref
        in context.admitted_calibration_profiles
        and comparison.confidence_summary.threshold_profile_ref
        in context.admitted_threshold_profiles
    )
    if not calibrated:
        return _result(
            comparison,
            VisualEvidenceDisposition.REVIEW_REQUIRED,
            ("VISUAL_COMPARISON_UNCALIBRATED",),
            binding_verified=True,
        )

    capture_age = (context.evaluated_at - observed.observed_at).total_seconds()
    if capture_age < 0 or capture_age > context.max_capture_age_seconds:
        return _result(
            comparison,
            VisualEvidenceDisposition.DENY,
            ("TELEMETRY_STALE",),
            binding_verified=True,
        )

    for observation in (baseline, observed):
        integrity_failure = _capture_integrity_failure(observation, comparison)
        if integrity_failure is not None:
            disposition, reason_codes = integrity_failure
            return _result(
                comparison,
                disposition,
                reason_codes,
                binding_verified=True,
            )

    if comparison.outcome == VisualEvidenceOutcome.MISMATCH:
        return _result(
            comparison,
            VisualEvidenceDisposition.QUARANTINE,
            comparison.reason_codes or ("SPATIAL_FINGERPRINT_MISMATCH",),
            binding_verified=True,
        )
    if comparison.outcome in {
        VisualEvidenceOutcome.INSUFFICIENT_COVERAGE,
        VisualEvidenceOutcome.ANOMALY_FLAGGED,
    }:
        return _result(
            comparison,
            VisualEvidenceDisposition.REVIEW_REQUIRED,
            comparison.reason_codes or ("VISUAL_CAPTURE_INSUFFICIENT_COVERAGE",),
            binding_verified=True,
        )

    if not context.non_visual_authority_valid:
        return _result(
            comparison,
            VisualEvidenceDisposition.DENY,
            context.non_visual_reason_codes,
            binding_verified=True,
        )

    return _result(
        comparison,
        VisualEvidenceDisposition.ACCEPTED,
        (),
        binding_verified=True,
    )


__all__ = ["replay_visual_evidence"]
