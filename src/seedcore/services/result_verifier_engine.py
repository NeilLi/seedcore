"""Reusable RESULT_VERIFIER computation (replay-chain + Rust verify-chain)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from seedcore.models.replay import ReplayVerificationStatus
from seedcore.models.result_verifier_outcome import ResultVerifierOutcome
from seedcore.services.replay_service import ReplayService


def _extract_asset_id_from_audit_record(record: Mapping[str, Any]) -> Optional[str]:
    policy_receipt = record.get("policy_receipt") if isinstance(record.get("policy_receipt"), dict) else {}
    action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
    resource = action_intent.get("resource") if isinstance(action_intent.get("resource"), dict) else {}
    for candidate in (policy_receipt.get("asset_ref"), resource.get("asset_id")):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _collect_evidence_refs(
    *,
    evidence_bundle: Mapping[str, Any],
    record: Mapping[str, Any],
) -> List[str]:
    refs: List[str] = []
    policy_receipt = record.get("policy_receipt") if isinstance(record.get("policy_receipt"), dict) else {}
    if isinstance(policy_receipt.get("policy_receipt_id"), str):
        refs.append(policy_receipt["policy_receipt_id"])
    if isinstance(evidence_bundle.get("evidence_bundle_id"), str):
        refs.append(evidence_bundle["evidence_bundle_id"])
    evidence_inputs = (
        evidence_bundle.get("evidence_inputs") if isinstance(evidence_bundle.get("evidence_inputs"), dict) else {}
    )
    tr = evidence_inputs.get("transition_receipts") if isinstance(evidence_inputs.get("transition_receipts"), list) else []
    for item in tr:
        if isinstance(item, dict) and isinstance(item.get("transition_receipt_id"), str):
            refs.append(item["transition_receipt_id"])
    return sorted(set(refs))


def is_restricted_custody_transfer_record(record: Mapping[str, Any]) -> bool:
    """v1 automation scope: RCT workflow only."""
    action_intent = record.get("action_intent") if isinstance(record.get("action_intent"), dict) else {}
    action = action_intent.get("action") if isinstance(action_intent.get("action"), dict) else {}
    params = action.get("parameters") if isinstance(action.get("parameters"), dict) else {}
    gateway = params.get("gateway") if isinstance(params.get("gateway"), dict) else {}
    wt = gateway.get("workflow_type")
    if isinstance(wt, str) and wt.strip() == "restricted_custody_transfer":
        return True
    policy_case = record.get("policy_case") if isinstance(record.get("policy_case"), dict) else {}
    hints = policy_case.get("workflow_hints") if isinstance(policy_case.get("workflow_hints"), dict) else {}
    w2 = hints.get("workflow_type")
    return isinstance(w2, str) and w2.strip() == "restricted_custody_transfer"


def map_replay_verification_to_outcome(
    status: ReplayVerificationStatus,
    *,
    record: Mapping[str, Any],
    evidence_bundle: Mapping[str, Any],
    transition_receipts: List[Mapping[str, Any]],
) -> ResultVerifierOutcome:
    issues = list(status.issues or [])
    asset_id = _extract_asset_id_from_audit_record(record)
    evidence_refs = _collect_evidence_refs(evidence_bundle=evidence_bundle, record=record)
    artifact_results = dict(status.artifact_results or {})

    if status.verified:
        return ResultVerifierOutcome(
            verified=True,
            failure_class="none",
            twin_event_type="verification_passed",
            asset_id=asset_id,
            evidence_refs=evidence_refs,
            artifact_results=artifact_results,
            issues=issues,
        )

    blob = " ".join(issues).lower()
    tamper = str(status.tamper_status or "")
    integrity = tamper in {"signature_invalid", "payload_mismatch"} or any(
        marker in blob
        for marker in (
            "signature",
            "payload_hash",
            "hash_mismatch",
            "rust_replay_chain",
            "forged",
            "invalid_signature",
            "tamper",
            "anchor_verification_failed",
        )
    )
    failure_code = issues[0] if issues else "verification_failed"
    if integrity:
        return ResultVerifierOutcome(
            verified=False,
            failure_code=failure_code,
            failure_class="integrity",
            twin_event_type="verification_failed",
            asset_id=asset_id,
            evidence_refs=evidence_refs,
            artifact_results=artifact_results,
            issues=issues,
        )
    return ResultVerifierOutcome(
        verified=False,
        failure_code=failure_code,
        failure_class="trust",
        twin_event_type="verification_quarantined",
        asset_id=asset_id,
        evidence_refs=evidence_refs,
        artifact_results=artifact_results,
        issues=issues,
    )


def verify_governed_audit_record(record: Mapping[str, Any]) -> ResultVerifierOutcome:
    """Run Python + Rust replay-chain verification over a governed audit row."""
    evidence_bundle = record.get("evidence_bundle") if isinstance(record.get("evidence_bundle"), dict) else {}
    if not evidence_bundle:
        return ResultVerifierOutcome(
            verified=False,
            failure_code="missing_evidence_bundle",
            failure_class="trust",
            twin_event_type="verification_quarantined",
            asset_id=_extract_asset_id_from_audit_record(record),
            issues=["missing_evidence_bundle"],
        )
    replay = ReplayService()
    status, evidence_bundle, _policy_receipt, transition_receipts = replay.verify_audit_record_for_result_verifier(record)
    return map_replay_verification_to_outcome(
        status,
        record=record,
        evidence_bundle=evidence_bundle,
        transition_receipts=transition_receipts,
    )
