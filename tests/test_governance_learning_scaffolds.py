from __future__ import annotations

from seedcore.drills.agent_self_regulation import build_self_regulation_intent
from seedcore.ml.curriculum import GovernanceScenarioGenerator
from seedcore.ml.reward import GovernanceRewardObservation, GovernanceRewardScorer


def _linked_observation(**overrides):
    data = {
        "request_id": "req-governance-learning-001",
        "pdp_disposition": "allow",
        "reason_code": "allowed",
        "replay_ref": "replay://workflow/req-governance-learning-001",
        "evidence_bundle_id": "fb:governance-learning-001",
        "policy_snapshot_hash": "sha256:policy",
        "decision_graph_snapshot_hash": "sha256:graph",
        "verifier_outcome": "verified",
        "trust_gap_codes": (),
    }
    data.update(overrides)
    return GovernanceRewardObservation(**data)


def test_governance_scenario_generator_emits_shadow_only_rct_probes() -> None:
    base_intent = build_self_regulation_intent()
    scenarios = GovernanceScenarioGenerator(base_intent).generate()

    assert [scenario.name for scenario in scenarios] == [
        "stale_telemetry_preflight",
        "out_of_bounds_preflight",
        "missing_required_evidence",
        "coordinate_redirect",
        "replay_injection",
        "tampered_telemetry_signature",
        "high_value_missing_cosignature",
    ]
    assert all(scenario.shadow_only for scenario in scenarios)
    assert all(scenario.expected_no_execute for scenario in scenarios)
    assert all(scenario.intent["options"]["scenario_lane"] == "shadow" for scenario in scenarios)
    assert base_intent["telemetry"]["freshness_seconds"] == 2

    stale = scenarios[0]
    assert stale.expected_disposition == "quarantine"
    assert stale.expected_reason_code == "stale_context"
    assert stale.intent["telemetry"]["freshness_seconds"] == 900

    out_of_bounds = scenarios[1]
    assert out_of_bounds.expected_disposition == "deny"
    assert out_of_bounds.expected_reason_code == "out_of_bounds_scope"
    assert out_of_bounds.intent["telemetry"]["current_zone"] == "loading_dock_unapproved"

    missing_evidence = scenarios[2]
    assert missing_evidence.expected_reason_code == "missing_required_evidence"
    assert missing_evidence.intent["telemetry"]["evidence_refs"] == ["origin_scan", "delivery_scan"]


def test_governance_reward_scorer_projects_clean_allow_without_authority() -> None:
    verdict = GovernanceRewardScorer().score(_linked_observation())

    assert verdict.verdict == "clean_allow"
    assert verdict.admissible_for_positive_reward is True
    assert verdict.training_eligible is True
    assert verdict.replay_ref == "replay://workflow/req-governance-learning-001"
    assert verdict.evidence_bundle_id == "fb:governance-learning-001"


def test_governance_reward_scorer_never_marks_verification_mismatch_positive() -> None:
    verdict = GovernanceRewardScorer().score(
        _linked_observation(
            pdp_disposition="allow",
            reason_code="allowed",
            verifier_outcome="verification_mismatch",
        )
    )

    assert verdict.verdict == "verification_mismatch"
    assert verdict.admissible_for_positive_reward is False
    assert verdict.training_eligible is True


def test_governance_reward_scorer_requires_replay_linked_training_material() -> None:
    verdict = GovernanceRewardScorer().score(
        _linked_observation(
            replay_ref=None,
            evidence_bundle_id=None,
            pdp_disposition="quarantine",
            reason_code="stale_telemetry",
            trust_gap_codes=("stale_telemetry",),
        )
    )

    assert verdict.verdict == "stale_context"
    assert verdict.training_eligible is False
    assert verdict.admissible_for_positive_reward is False
    assert verdict.notes == ("missing_replay_ref", "missing_evidence_bundle_id")
