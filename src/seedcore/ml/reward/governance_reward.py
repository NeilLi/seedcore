from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Sequence


GovernanceVerdict = Literal[
    "clean_allow",
    "clean_deny",
    "near_miss_policy_gap",
    "quarantine",
    "escalate",
    "verification_mismatch",
    "stale_context",
]


@dataclass(frozen=True)
class GovernanceRewardObservation:
    """Shadow-only observation consumed after PDP/replay/verifier outcomes exist."""

    request_id: str
    pdp_disposition: str
    reason_code: str
    replay_ref: Optional[str] = None
    evidence_bundle_id: Optional[str] = None
    policy_snapshot_hash: Optional[str] = None
    decision_graph_snapshot_hash: Optional[str] = None
    verifier_outcome: Optional[str] = None
    trust_gap_codes: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class GovernanceRewardVerdict:
    """Typed governance verdict for training/evaluation, never authorization."""

    request_id: str
    verdict: GovernanceVerdict
    reason_code: str
    replay_ref: Optional[str]
    evidence_bundle_id: Optional[str]
    policy_snapshot_hash: Optional[str]
    decision_graph_snapshot_hash: Optional[str]
    verifier_outcome: Optional[str]
    admissible_for_positive_reward: bool
    training_eligible: bool
    notes: Sequence[str] = field(default_factory=tuple)


class GovernanceRewardScorer:
    """Project governed outcomes into a typed, shadow-only learning verdict."""

    _STALE_CODES = {
        "stale_context",
        "stale_telemetry",
        "telemetry_too_stale_for_scope_validation",
        "compiled_authz_graph_stale",
    }
    _VERIFIER_FAILURES = {
        "verification_failed",
        "verification_mismatch",
        "result_verifier_failed",
        "failed",
        "mismatch",
    }

    def score(self, observation: GovernanceRewardObservation) -> GovernanceRewardVerdict:
        disposition = observation.pdp_disposition.strip().lower()
        reason_code = observation.reason_code.strip().lower()
        verifier_outcome = (observation.verifier_outcome or "").strip().lower()
        trust_gap_codes = {code.strip().lower() for code in observation.trust_gap_codes}
        all_codes = trust_gap_codes | {reason_code}

        if verifier_outcome in self._VERIFIER_FAILURES:
            verdict: GovernanceVerdict = "verification_mismatch"
        elif all_codes & self._STALE_CODES:
            verdict = "stale_context"
        elif disposition == "allow":
            verdict = "clean_allow"
        elif disposition == "deny":
            verdict = "near_miss_policy_gap" if reason_code.startswith("near_miss") else "clean_deny"
        elif disposition == "quarantine":
            verdict = "quarantine"
        elif disposition == "escalate":
            verdict = "escalate"
        else:
            verdict = "clean_deny"

        training_eligible, missing_links = self._training_eligibility(observation)
        return GovernanceRewardVerdict(
            request_id=observation.request_id,
            verdict=verdict,
            reason_code=observation.reason_code,
            replay_ref=observation.replay_ref,
            evidence_bundle_id=observation.evidence_bundle_id,
            policy_snapshot_hash=observation.policy_snapshot_hash,
            decision_graph_snapshot_hash=observation.decision_graph_snapshot_hash,
            verifier_outcome=observation.verifier_outcome,
            admissible_for_positive_reward=verdict == "clean_allow" and training_eligible,
            training_eligible=training_eligible,
            notes=tuple(f"missing_{name}" for name in missing_links),
        )

    @staticmethod
    def _training_eligibility(observation: GovernanceRewardObservation) -> tuple[bool, Sequence[str]]:
        required_links: Dict[str, Optional[str]] = {
            "replay_ref": observation.replay_ref,
            "evidence_bundle_id": observation.evidence_bundle_id,
            "policy_snapshot_hash": observation.policy_snapshot_hash,
            "decision_graph_snapshot_hash": observation.decision_graph_snapshot_hash,
        }
        missing = tuple(name for name, value in required_links.items() if not value)
        return not missing, missing
