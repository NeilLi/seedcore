from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from seedcore.ml.reward.governance_reward import GovernanceRewardObservation, GovernanceRewardScorer
from seedcore.models.evidence_bundle import EvidenceBundle
from seedcore.models.governance_learning import (
    GovernanceEvidenceSummary,
    GovernanceFeatureVector,
    GovernanceLearningSampleV1,
)
from seedcore.ml.distillation.sample_store import append_governance_sample


class GovernanceLearningSampleExporter:
    """
    Builds and exports GovernanceLearningSampleV1 records to the JSONL store.
    """

    def __init__(self, scorer: Optional[GovernanceRewardScorer] = None) -> None:
        self._scorer = scorer or GovernanceRewardScorer()

    async def export(
        self,
        request_id: str,
        intent_id: str,
        pdp_disposition: str,
        reason_code: str,
        replay_ref: str,
        evidence_bundle_id: str,
        policy_snapshot_hash: str,
        decision_graph_snapshot_hash: str,
        verifier_outcome: str,
        evidence_bundle: Optional[EvidenceBundle] = None,
        intent_payload: Optional[Dict[str, Any]] = None,
        trust_gap_codes: Optional[List[str]] = None,
        obligations: Optional[List[Dict[str, Any]]] = None,
        state_binding_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GovernanceLearningSampleV1:
        # Check required fields and raise if absent
        if not replay_ref or not replay_ref.strip():
            raise ValueError("replay_ref is required for governance learning samples")
        if not evidence_bundle_id or not evidence_bundle_id.strip():
            raise ValueError("evidence_bundle_id is required for governance learning samples")
        if not policy_snapshot_hash or not policy_snapshot_hash.strip():
            raise ValueError("policy_snapshot_hash is required for governance learning samples")
        if not decision_graph_snapshot_hash or not decision_graph_snapshot_hash.strip():
            raise ValueError("decision_graph_snapshot_hash is required for governance learning samples")
        if not verifier_outcome or not verifier_outcome.strip():
            raise ValueError("verifier_outcome is required for governance learning samples")

        final_trust_gaps = trust_gap_codes or []
        final_obligations = obligations or []

        # Determine the verdict using scorer
        observation = GovernanceRewardObservation(
            request_id=request_id,
            pdp_disposition=pdp_disposition,
            reason_code=reason_code,
            replay_ref=replay_ref,
            evidence_bundle_id=evidence_bundle_id,
            policy_snapshot_hash=policy_snapshot_hash,
            decision_graph_snapshot_hash=decision_graph_snapshot_hash,
            verifier_outcome=verifier_outcome,
            trust_gap_codes=final_trust_gaps,
        )
        verdict_res = self._scorer.score(observation)

        # Compute deterministic features
        features = self._compute_features(intent_payload, final_trust_gaps)

        # Compute evidence summary
        evidence_summary = self._compute_evidence_summary(evidence_bundle)

        sample = GovernanceLearningSampleV1(
            sample_id=str(uuid.uuid4()),
            request_id=request_id,
            intent_id=intent_id,
            replay_ref=replay_ref,
            evidence_bundle_id=evidence_bundle_id,
            policy_snapshot_hash=policy_snapshot_hash,
            decision_graph_snapshot_hash=decision_graph_snapshot_hash,
            pdp_disposition=pdp_disposition,
            reason_code=reason_code,
            trust_gap_codes=final_trust_gaps,
            obligations=final_obligations,
            verifier_outcome=verifier_outcome,
            verdict=verdict_res.verdict,
            features=features,
            evidence_summary=evidence_summary,
            created_at=datetime.now(timezone.utc).isoformat(),
            state_binding_hash=state_binding_hash,
            metadata=metadata or {},
        )

        # Write to JSONL
        await append_governance_sample(sample)
        return sample

    def _compute_features(
        self, intent_payload: Optional[Dict[str, Any]], trust_gap_codes: List[str]
    ) -> GovernanceFeatureVector:
        if not intent_payload:
            return GovernanceFeatureVector(trust_gap_count=len(trust_gap_codes))

        # Check telemetry details
        telemetry = intent_payload.get("telemetry") or {}
        telemetry_age_seconds = float(telemetry.get("freshness_seconds", 0.0))

        # Coordinates validation
        current_zone = telemetry.get("current_zone")
        coord_ref = telemetry.get("current_coordinate_ref")
        has_valid_coordinates = bool(coord_ref and current_zone and current_zone != "loading_dock_unapproved")

        # Signature validation
        principal = intent_payload.get("principal") or {}
        has_valid_signature = bool(principal.get("session_token") or principal.get("actor_token"))

        # Enrollment, zone status
        device_enrolled = bool(principal.get("hardware_fingerprint"))
        is_approved_zone = bool(current_zone and current_zone != "loading_dock_unapproved")

        # Asset details
        asset = intent_payload.get("asset") or {}
        has_matching_assets = bool(asset.get("asset_id"))
        declared_value_usd = float(asset.get("declared_value_usd") or 0.0)

        # Co-signatures
        approval = intent_payload.get("approval") or {}
        approval_envelope_present = bool(approval.get("envelope_id") or intent_payload.get("approval_envelope_id"))
        requires_co_signature = bool(intent_payload.get("co_sign_required", False))

        distance_to_boundary = 0.0
        max_age = float(telemetry.get("max_allowed_age_seconds", 0.0))
        if max_age > 0:
            distance_to_boundary = max(0.0, max_age - telemetry_age_seconds)

        return GovernanceFeatureVector(
            telemetry_age_seconds=telemetry_age_seconds,
            has_valid_coordinates=has_valid_coordinates,
            has_valid_signature=has_valid_signature,
            has_matching_assets=has_matching_assets,
            device_enrolled=device_enrolled,
            is_approved_zone=is_approved_zone,
            approval_envelope_present=approval_envelope_present,
            declared_value_usd=declared_value_usd,
            requires_co_signature=requires_co_signature,
            trust_gap_count=len(trust_gap_codes),
            distance_to_boundary=distance_to_boundary,
        )

    def _compute_evidence_summary(self, evidence_bundle: Optional[EvidenceBundle]) -> GovernanceEvidenceSummary:
        if not evidence_bundle:
            return GovernanceEvidenceSummary()

        has_transition_receipts = len(evidence_bundle.transition_receipt_ids) > 0
        has_policy_receipt = bool(evidence_bundle.policy_receipt_id)
        has_asset_fingerprint = bool(evidence_bundle.asset_fingerprint)

        signer_profile = "none"
        if evidence_bundle.signer_metadata:
            signer_profile = evidence_bundle.signer_metadata.config_profile or "baseline"

        return GovernanceEvidenceSummary(
            has_transition_receipts=has_transition_receipts,
            has_policy_receipt=has_policy_receipt,
            has_asset_fingerprint=has_asset_fingerprint,
            signer_profile=signer_profile,
            telemetry_count=len(evidence_bundle.telemetry_refs),
            media_count=len(evidence_bundle.media_refs),
        )
