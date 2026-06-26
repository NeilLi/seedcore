from __future__ import annotations

from typing import Iterable, List

from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1
from seedcore.models.governance_learning import GovernanceLearningSampleV1


class GovernanceAdvisoryLabeler:
    """Derive shadow-only advisory labels from frozen governance samples."""

    _VERIFIED_OUTCOMES = {"verified"}
    _VERIFIER_FAILURES = {
        "verification_failed",
        "verification_mismatch",
        "verification_lockout",
        "result_verifier_failed",
        "result_verifier_lockout",
        "result_verifier_verification_failed",
        "failed",
        "lockout",
        "mismatch",
        "replay_mismatch",
    }

    def label(self, sample: GovernanceLearningSampleV1) -> GovernanceAdvisoryOutputV1:
        verifier_outcome = sample.verifier_outcome.strip().lower()
        verified_clean_allow = (
            sample.verdict == "clean_allow"
            and sample.pdp_disposition.strip().lower() == "allow"
            and verifier_outcome in self._VERIFIED_OUTCOMES
        )
        abstain = not verified_clean_allow
        return GovernanceAdvisoryOutputV1(
            reason_code=sample.reason_code,
            trust_gap_codes=list(sample.trust_gap_codes),
            missing_authority_context=self._missing_authority_context(sample),
            evidence_risk_flags=self._evidence_risk_flags(sample),
            required_obligations=list(sample.obligations),
            abstain=abstain,
            abstain_reasons=[] if not abstain else self._abstain_reasons(sample),
        )

    def _missing_authority_context(self, sample: GovernanceLearningSampleV1) -> List[str]:
        codes = self._all_codes(sample)
        missing: List[str] = []
        if self._contains(codes, "cosign", "co_signature", "co-sign"):
            missing.append("co_signature")
        if self._contains(codes, "approval", "envelope"):
            missing.append("approval_envelope")
        if self._contains(codes, "delegation", "did"):
            missing.append("delegation_chain")
        if self._contains(codes, "token", "replay", "scope"):
            missing.append("execution_token_scope")
        if self._contains(codes, "signature", "signer"):
            missing.append("valid_signature")
        if self._contains(codes, "stale", "freshness"):
            missing.append("fresh_context")
        if self._contains(codes, "coordinate", "zone", "bounds"):
            missing.append("authorized_location_scope")
        if self._contains(codes, "evidence", "receipt", "bundle"):
            missing.append("evidence_closure")
        if sample.verifier_outcome.strip().lower() not in self._VERIFIED_OUTCOMES:
            missing.append("verified_result_closure")
        if sample.features.requires_co_signature and not self._contains(missing, "co_signature"):
            missing.append("co_signature")
        if not sample.features.approval_envelope_present and sample.pdp_disposition.strip().lower() == "allow":
            missing.append("approval_envelope")
        return self._unique(missing)

    def _evidence_risk_flags(self, sample: GovernanceLearningSampleV1) -> List[str]:
        codes = self._all_codes(sample)
        flags: List[str] = []
        verifier_outcome = sample.verifier_outcome.strip().lower()
        if verifier_outcome in self._VERIFIER_FAILURES:
            flags.append("verification_mismatch")
        elif verifier_outcome not in self._VERIFIED_OUTCOMES:
            flags.append("verifier_not_verified")
        if self._contains(codes, "stale"):
            flags.append("stale_context")
        if self._contains(codes, "coordinate", "zone", "bounds"):
            flags.append("location_scope_risk")
        if self._contains(codes, "signature", "signer"):
            flags.append("signature_risk")
        if self._contains(codes, "replay"):
            flags.append("replay_risk")
        if self._contains(codes, "evidence", "receipt", "bundle"):
            flags.append("evidence_closure_risk")
        if not sample.evidence_summary.has_policy_receipt:
            flags.append("missing_policy_receipt")
        if not sample.evidence_summary.has_transition_receipts:
            flags.append("missing_transition_receipts")
        if not sample.evidence_summary.has_asset_fingerprint:
            flags.append("missing_asset_fingerprint")
        if not sample.features.has_valid_signature:
            flags.append("invalid_or_missing_signature")
        if not sample.features.has_valid_coordinates:
            flags.append("invalid_or_missing_coordinates")
        return self._unique(flags)

    def _abstain_reasons(self, sample: GovernanceLearningSampleV1) -> List[str]:
        reasons: List[str] = []
        if sample.verdict != "clean_allow":
            reasons.append(f"verdict_{sample.verdict}")
        if sample.pdp_disposition.strip().lower() != "allow":
            reasons.append(f"pdp_{sample.pdp_disposition.strip().lower()}")
        if sample.verifier_outcome.strip().lower() not in self._VERIFIED_OUTCOMES:
            reasons.append("verifier_not_verified")
        reasons.extend(f"trust_gap_{code}" for code in sample.trust_gap_codes)
        reasons.extend(self._evidence_risk_flags(sample))
        return self._unique(reasons)

    @staticmethod
    def _all_codes(sample: GovernanceLearningSampleV1) -> List[str]:
        return [sample.reason_code, sample.verdict, sample.verifier_outcome, *sample.trust_gap_codes]

    @staticmethod
    def _contains(values: Iterable[str], *needles: str) -> bool:
        lowered = [str(value).lower() for value in values]
        return any(needle in value for needle in needles for value in lowered)

    @staticmethod
    def _unique(values: Iterable[str]) -> List[str]:
        result: List[str] = []
        for value in values:
            text = str(value).strip()
            if text and text not in result:
                result.append(text)
        return result
