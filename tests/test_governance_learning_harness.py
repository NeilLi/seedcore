from __future__ import annotations

import pytest
from pydantic import ValidationError

from seedcore.drills.agent_self_regulation import build_self_regulation_intent
from seedcore.ml.curriculum.governance_scenarios import GovernanceScenarioGenerator
from seedcore.ml.distillation import sample_store
from seedcore.ml.reward.governance_reward import GovernanceRewardObservation, GovernanceRewardScorer
from seedcore.models.evidence_bundle import EvidenceBundle, SignerMetadata
from seedcore.models.governance_learning import (
    GovernanceEvidenceSummary,
    GovernanceFeatureVector,
    GovernanceLearningSampleV1,
)
from seedcore.ops.governance_learning.exporter import GovernanceLearningSampleExporter


@pytest.fixture(autouse=True)
def patch_sample_store_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_store, "DISTILLATION_DIR", tmp_path)
    monkeypatch.setattr(sample_store, "GOVERNANCE_SAMPLES_FILE", tmp_path / "governance_learning_samples.jsonl")


def test_schema_validation_rejects_missing_or_empty_required_fields() -> None:
    # Missing required fields like pdp_disposition, replay_ref, etc.
    with pytest.raises(ValidationError):
        GovernanceLearningSampleV1(
            sample_id="sample-123",
            request_id="req-123",
            intent_id="intent-123",
            replay_ref="",  # empty
            evidence_bundle_id="bundle-123",
            policy_snapshot_hash="sha256:policy",
            decision_graph_snapshot_hash="sha256:graph",
            pdp_disposition="allow",
            reason_code="allowed",
            verifier_outcome="verified",
            verdict="clean_allow",
            features=GovernanceFeatureVector(),
            evidence_summary=GovernanceEvidenceSummary(),
            created_at="2026-06-22T13:00:00Z",
        )


def test_schema_validation_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        GovernanceLearningSampleV1(
            sample_id="sample-123",
            request_id="req-123",
            intent_id="intent-123",
            replay_ref="replay://workflow/req-123",
            evidence_bundle_id="bundle-123",
            policy_snapshot_hash="sha256:policy",
            decision_graph_snapshot_hash="sha256:graph",
            pdp_disposition="allow",
            reason_code="allowed",
            verifier_outcome="verified",
            verdict="clean_allow",
            features=GovernanceFeatureVector(),
            evidence_summary=GovernanceEvidenceSummary(),
            created_at="2026-06-22T13:00:00Z",
            unexpected_authority_hint="should-not-be-accepted",
        )


@pytest.mark.asyncio
async def test_exporter_emits_valid_jsonl_samples() -> None:
    exporter = GovernanceLearningSampleExporter()

    # Test linked near-miss allow with persisted learning context.
    intent_payload = {
        "telemetry": {
            "freshness_seconds": 12.5,
            "max_allowed_age_seconds": 300,
            "current_zone": "approved_warehouse_zone",
            "current_coordinate_ref": "gazebo://warehouse/coord/A1",
        },
        "principal": {
            "session_token": "token-123",
            "hardware_fingerprint": {"device_id": "dev-123"},
        },
        "asset": {
            "asset_id": "asset-123",
            "declared_value_usd": 150.0,
        },
    }

    signer_meta = SignerMetadata(
        signer_type="kms",
        signer_id="signer-123",
        signing_scheme="ECDSA",
        config_profile="production-profile",
    )
    bundle = EvidenceBundle(
        evidence_bundle_id="bundle-123",
        task_id="task-123",
        intent_id="intent-123",
        signer_metadata=signer_meta,
        signature="signature-mock",
        created_at="2026-06-22T13:00:00Z",
        telemetry_refs=[{"ref": "telemetry-1"}],
        transition_receipt_ids=["receipt-1"],
    )

    sample = await exporter.export(
        request_id="req-123",
        intent_id="intent-123",
        pdp_disposition="allow",
        reason_code="allowed",
        replay_ref="replay://workflow/req-123",
        evidence_bundle_id="bundle-123",
        policy_snapshot_hash="sha256:policy",
        decision_graph_snapshot_hash="sha256:graph",
        verifier_outcome="verified",
        evidence_bundle=bundle,
        intent_payload=intent_payload,
        trust_gap_codes=["coordinate_warning"],
        obligations=[{"type": "operator_review", "scope": "shadow"}],
    )

    assert sample.verdict == "near_miss_allow"
    assert sample.trust_gap_codes == ["coordinate_warning"]
    assert sample.obligations == [{"type": "operator_review", "scope": "shadow"}]
    assert sample.features.telemetry_age_seconds == 12.5
    assert sample.features.has_valid_coordinates is True
    assert sample.evidence_summary.signer_profile == "production-profile"
    assert sample.evidence_summary.telemetry_count == 1

    # Read from JSONL to verify persistence
    stored_samples = sample_store.load_governance_dataset()
    assert len(stored_samples) == 1
    assert stored_samples[0].sample_id == sample.sample_id
    assert stored_samples[0].verdict == "near_miss_allow"
    assert stored_samples[0].trust_gap_codes == ["coordinate_warning"]
    assert stored_samples[0].obligations == [{"type": "operator_review", "scope": "shadow"}]


@pytest.mark.asyncio
async def test_exporter_fails_closed_when_links_are_missing() -> None:
    exporter = GovernanceLearningSampleExporter()

    # Missing replay_ref should raise ValueError
    with pytest.raises(ValueError, match="replay_ref is required"):
        await exporter.export(
            request_id="req-123",
            intent_id="intent-123",
            pdp_disposition="allow",
            reason_code="allowed",
            replay_ref="",  # empty
            evidence_bundle_id="bundle-123",
            policy_snapshot_hash="sha256:policy",
            decision_graph_snapshot_hash="sha256:graph",
            verifier_outcome="verified",
        )

    # Ensure nothing was written to the file
    assert not sample_store.GOVERNANCE_SAMPLES_FILE.exists()


def test_verification_mismatch_and_stale_context_never_positive_reward() -> None:
    scorer = GovernanceRewardScorer()

    # Verification mismatch
    mismatch_obs = GovernanceRewardObservation(
        request_id="req-mismatch",
        pdp_disposition="allow",
        reason_code="allowed",
        replay_ref="replay://req-mismatch",
        evidence_bundle_id="bundle-mismatch",
        policy_snapshot_hash="sha256:policy",
        decision_graph_snapshot_hash="sha256:graph",
        verifier_outcome="verification_mismatch",
    )
    mismatch_verdict = scorer.score(mismatch_obs)
    assert mismatch_verdict.verdict == "verification_mismatch"
    assert mismatch_verdict.admissible_for_positive_reward is False

    # Stale context
    stale_obs = GovernanceRewardObservation(
        request_id="req-stale",
        pdp_disposition="allow",
        reason_code="stale_context",
        replay_ref="replay://req-stale",
        evidence_bundle_id="bundle-stale",
        policy_snapshot_hash="sha256:policy",
        decision_graph_snapshot_hash="sha256:graph",
        verifier_outcome="verified",
    )
    stale_verdict = scorer.score(stale_obs)
    assert stale_verdict.verdict == "stale_context"
    assert stale_verdict.admissible_for_positive_reward is False


def test_allow_requires_verified_verifier_outcome_for_positive_reward() -> None:
    scorer = GovernanceRewardScorer()
    base_observation = {
        "request_id": "req-non-verified",
        "pdp_disposition": "allow",
        "reason_code": "allowed",
        "replay_ref": "replay://req-non-verified",
        "evidence_bundle_id": "bundle-non-verified",
        "policy_snapshot_hash": "sha256:policy",
        "decision_graph_snapshot_hash": "sha256:graph",
    }

    for verifier_outcome in (None, "", "pending"):
        verdict = scorer.score(
            GovernanceRewardObservation(
                **base_observation,
                verifier_outcome=verifier_outcome,
            )
        )

        assert verdict.verdict == "clean_allow"
        assert verdict.training_eligible is True
        assert verdict.admissible_for_positive_reward is False
        assert "missing_verified_verifier_outcome" in verdict.notes


def test_result_verifier_lockout_maps_to_mismatch_and_never_positive_reward() -> None:
    verdict = GovernanceRewardScorer().score(
        GovernanceRewardObservation(
            request_id="req-lockout",
            pdp_disposition="allow",
            reason_code="allowed",
            replay_ref="replay://req-lockout",
            evidence_bundle_id="bundle-lockout",
            policy_snapshot_hash="sha256:policy",
            decision_graph_snapshot_hash="sha256:graph",
            verifier_outcome="result_verifier_lockout",
        )
    )

    assert verdict.verdict == "verification_mismatch"
    assert verdict.training_eligible is True
    assert verdict.admissible_for_positive_reward is False
    assert "missing_verified_verifier_outcome" in verdict.notes


def test_scenario_generator_emits_probes_correctly() -> None:
    base_intent = build_self_regulation_intent()
    generator = GovernanceScenarioGenerator(base_intent)
    scenarios = generator.generate()

    assert len(scenarios) == 7
    assert all(scenario.shadow_only is True for scenario in scenarios)
    assert all(scenario.expected_no_execute is True for scenario in scenarios)

    # Validate coordinate_redirect
    coord_redirect = next(s for s in scenarios if s.name == "coordinate_redirect")
    assert coord_redirect.expected_disposition == "deny"
    assert coord_redirect.expected_reason_code == "coordinate_mismatch"
    assert coord_redirect.intent["telemetry"]["current_coordinate_ref"] == "gazebo://warehouse/unauthorized-coordinate"

    # Validate replay_injection
    replay = next(s for s in scenarios if s.name == "replay_injection")
    assert replay.expected_disposition == "deny"
    assert replay.expected_reason_code == "token_replay_detected"

    # Validate high_value_missing_cosignature
    missing_cosign = next(s for s in scenarios if s.name == "high_value_missing_cosignature")
    assert missing_cosign.expected_disposition == "quarantine"
    assert missing_cosign.expected_reason_code == "missing_required_cosignature"
