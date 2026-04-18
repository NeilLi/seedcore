"""Reusable RESULT_VERIFIER computation (replay-chain + Rust verify-chain)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from seedcore.models.replay import ReplayVerificationStatus
from seedcore.models.result_verifier_outcome import ResultVerifierOutcome
from seedcore.ops.evidence.rct_control_posture import (
    is_restricted_custody_transfer_record as _is_restricted_custody_transfer_record,
)
from seedcore.services.replay_service import ReplayService


class ResultVerifierRetryableError(RuntimeError):
    """Transient verifier infrastructure failure; safe to retry without mutating twins."""


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
    return _is_restricted_custody_transfer_record(record)


_DIRECT_REPLAY_MISMATCH_ISSUES = {
    "allow_missing_execution_token",
    "allow_invalid_execution_token",
    "snapshot_hash_mismatch",
    "policy_receipt_snapshot_hash_mismatch",
    "evidence_bundle_snapshot_hash_mismatch",
    "state_binding_hash_mismatch",
    "policy_receipt_state_binding_hash_mismatch",
    "evidence_bundle_state_binding_hash_mismatch",
    "payload_hash_mismatch",
    "artifact_hash_mismatch",
}

_RETRYABLE_RUST_REPLAY_ERROR_CODES = {
    "rust_verify_replay_chain_timeout",
    "rust_verify_replay_chain_unavailable",
    "rust_verify_replay_chain_failed",
    "rust_seal_replay_bundle_timeout",
    "rust_seal_replay_bundle_unavailable",
    "rust_seal_replay_bundle_failed",
}


def _issue_tail(issue: str) -> str:
    _, _, tail = issue.rpartition(":")
    return (tail or issue).strip().lower()


def _is_replay_mismatch_status(status: ReplayVerificationStatus) -> bool:
    if str(status.tamper_status or "").strip().lower() == "payload_mismatch":
        return True
    rust_chain = (
        status.artifact_results.get("rust_replay_chain")
        if isinstance(status.artifact_results, Mapping)
        else {}
    )
    rust_error_code = (
        str(rust_chain.get("error_code") or "").strip().lower()
        if isinstance(rust_chain, Mapping)
        else ""
    )
    if rust_error_code in {"allow_missing_execution_token", "allow_invalid_execution_token"}:
        return True
    for issue in list(status.issues or []):
        normalized = str(issue or "").strip().lower()
        if not normalized:
            continue
        tail = _issue_tail(normalized)
        if tail in _DIRECT_REPLAY_MISMATCH_ISSUES:
            return True
        if (
            normalized.startswith("rct_triple_hash_strict:")
            and "mismatch" in tail
        ):
            return True
        if (
            normalized.startswith("rct_state_transition_fields_opt_in:")
            and "mismatch" in tail
        ):
            return True
    return False


def _retryable_verifier_failure_code(status: ReplayVerificationStatus) -> str | None:
    rust_chain = (
        status.artifact_results.get("rust_replay_chain")
        if isinstance(status.artifact_results, Mapping)
        else {}
    )
    rust_error_code = (
        str(rust_chain.get("error_code") or "").strip().lower()
        if isinstance(rust_chain, Mapping)
        else ""
    )
    if rust_error_code in _RETRYABLE_RUST_REPLAY_ERROR_CODES:
        return rust_error_code

    for issue in list(status.issues or []):
        normalized = str(issue or "").strip().lower()
        if not normalized.startswith("rust_replay_chain:"):
            continue
        tail = _issue_tail(normalized)
        if tail in _RETRYABLE_RUST_REPLAY_ERROR_CODES:
            return tail
    return None


def _gate_reason_code_for_failure(*, verified: bool, failure_class: str | None, replay_mismatch: bool) -> str | None:
    if verified:
        return None
    if replay_mismatch:
        return "result_verifier_replay_mismatch"
    if failure_class == "integrity":
        return "result_verifier_verification_failed"
    if failure_class == "trust":
        return "result_verifier_quarantined"
    return "result_verifier_lockout"


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
    replay_mismatch = _is_replay_mismatch_status(status)
    integrity = tamper in {"signature_invalid", "payload_mismatch"} or any(
        marker in blob
        for marker in (
            "signature",
            "payload_hash",
            "hash_mismatch",
            "forged",
            "invalid_signature",
            "tamper",
            "anchor_verification_failed",
        )
    )
    failure_code = "replay_mismatch" if replay_mismatch else (issues[0] if issues else "verification_failed")
    if integrity:
        return ResultVerifierOutcome(
            verified=False,
            failure_code=failure_code,
            gate_reason_code=_gate_reason_code_for_failure(
                verified=False,
                failure_class="integrity",
                replay_mismatch=replay_mismatch,
            ),
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
        gate_reason_code=_gate_reason_code_for_failure(
            verified=False,
            failure_class="trust",
            replay_mismatch=replay_mismatch,
        ),
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
            gate_reason_code="result_verifier_quarantined",
            failure_class="trust",
            twin_event_type="verification_quarantined",
            asset_id=_extract_asset_id_from_audit_record(record),
            issues=["missing_evidence_bundle"],
        )
    replay = ReplayService()
    status, evidence_bundle, _policy_receipt, transition_receipts = replay.verify_audit_record_for_result_verifier(record)
    retryable_code = _retryable_verifier_failure_code(status)
    if retryable_code:
        raise ResultVerifierRetryableError(retryable_code)
    return map_replay_verification_to_outcome(
        status,
        record=record,
        evidence_bundle=evidence_bundle,
        transition_receipts=transition_receipts,
    )
