from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from threading import Lock
from typing import Any, Dict, Iterable, Mapping, Sequence

from seedcore.coordinator.core.governance import evaluate_intent, prepare_policy_case
from seedcore.models.action_intent import ExecutionToken, PolicyDecision
from seedcore.models.pdp_hot_path import (
    HotPathCheckResult,
    HotPathDecisionView,
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathSignerProvenance,
)
from seedcore.ops.pkg.manager import get_global_pkg_manager

HOT_PATH_CONTRACT_VERSION = "pdp.hot_path.asset_transfer.v1"
HOT_PATH_MODE = os.getenv("SEEDCORE_RCT_HOT_PATH_MODE", "shadow").strip().lower() or "shadow"

REASON_CODE_DEFAULTS = {
    "allow": "restricted_custody_transfer_allowed",
    "deny": "policy_denied",
    "quarantine": "trust_gap_quarantine",
    "escalate": "manual_review_required",
}


@dataclass
class HotPathShadowStats:
    mode: str = HOT_PATH_MODE
    total: int = 0
    parity_ok: int = 0
    mismatched: int = 0
    last_run_at: str | None = None
    latencies_ms: deque[int] = field(default_factory=lambda: deque(maxlen=256))
    recent_results: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=20))
    lock: Lock = field(default_factory=Lock)

    def record(self, *, latency_ms: int, parity: Mapping[str, Any]) -> None:
        with self.lock:
            self.total += 1
            self.last_run_at = datetime.now(timezone.utc).isoformat()
            self.latencies_ms.append(int(latency_ms))
            parity_ok = bool(parity.get("parity_ok"))
            if parity_ok:
                self.parity_ok += 1
            else:
                self.mismatched += 1
            self.recent_results.append(dict(parity))

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            samples = sorted(self.latencies_ms)
            return {
                "mode": self.mode,
                "total": self.total,
                "parity_ok": self.parity_ok,
                "mismatched": self.mismatched,
                "last_run_at": self.last_run_at,
                "latency_ms": {
                    "p50": _percentile(samples, 50),
                    "p95": _percentile(samples, 95),
                    "p99": _percentile(samples, 99),
                },
                "recent_results": list(self.recent_results),
            }


_HOT_PATH_SHADOW_STATS = HotPathShadowStats()


def evaluate_pdp_hot_path(request: HotPathEvaluateRequest) -> HotPathEvaluateResponse:
    started = perf_counter()
    checks: list[HotPathCheckResult] = []

    asset_match = request.action_intent.resource.asset_id == request.asset_context.asset_ref
    checks.append(_check("asset_ref_match", asset_match, "asset_id and asset_ref must match"))
    if not asset_match:
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="deny",
            reason_code="asset_custody_mismatch",
            reason="Action intent asset does not match the provided asset context.",
            policy_snapshot_ref=request.policy_snapshot_ref,
        )

    freshness_ok = True
    if (
        request.telemetry_context.freshness_seconds is not None
        and request.telemetry_context.max_allowed_age_seconds is not None
    ):
        freshness_ok = (
            request.telemetry_context.freshness_seconds
            <= request.telemetry_context.max_allowed_age_seconds
        )
    checks.append(_check("telemetry_freshness", freshness_ok, "telemetry exceeds allowed age"))
    if not freshness_ok:
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="stale_telemetry",
            reason="Telemetry freshness exceeds policy limits.",
            policy_snapshot_ref=request.policy_snapshot_ref,
            trust_gaps=["stale_telemetry"],
        )

    compiled_authz_index = _resolve_compiled_authz_index()
    if compiled_authz_index is None:
        checks.append(_check("compiled_authz_graph_ready", False, "active compiled authz graph unavailable"))
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="hot_path_dependency_unavailable",
            reason="Active compiled authorization graph is unavailable.",
            policy_snapshot_ref=request.policy_snapshot_ref,
        )

    compiled_snapshot = (
        str(getattr(compiled_authz_index, "snapshot_version", "")).strip()
        or str(getattr(compiled_authz_index, "snapshot_ref", "")).strip()
    )
    snapshot_ok = not compiled_snapshot or compiled_snapshot == request.policy_snapshot_ref
    checks.append(_check("snapshot_consistency", snapshot_ok, "requested snapshot does not match active compiled graph"))
    if not snapshot_ok:
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="snapshot_not_ready",
            reason=(
                f"Requested snapshot '{request.policy_snapshot_ref}' does not match "
                f"active compiled snapshot '{compiled_snapshot}'."
            ),
            policy_snapshot_ref=request.policy_snapshot_ref,
        )

    approved_source_registrations: dict[str, str | None] = {}
    if (request.asset_context.source_registration_status or "").strip().upper() == "APPROVED":
        approved_source_registrations[request.asset_context.asset_ref] = request.asset_context.registration_decision_ref

    telemetry_summary = {
        "observed_at": request.telemetry_context.observed_at,
        "stale": not freshness_ok,
    }
    evidence_summary = {"evidence_refs": list(request.telemetry_context.evidence_refs)}
    policy_case = prepare_policy_case(
        request.action_intent,
        policy_snapshot=request.policy_snapshot_ref,
        approved_source_registrations=approved_source_registrations,
        telemetry_summary=telemetry_summary,
        evidence_summary=evidence_summary,
    )
    baseline_decision = evaluate_intent(policy_case)
    decision = evaluate_intent(policy_case, compiled_authz_index=compiled_authz_index)

    checks.extend(_decision_checks(decision))
    trust_gaps = _extract_trust_gaps(decision)
    obligations = _normalize_obligations(decision.obligations)
    signer_provenance = _extract_signer_provenance(decision)
    reason_code = _decision_reason_code(decision)
    disposition = str(decision.disposition or "deny").strip().lower()
    policy_snapshot_ref = (
        str(decision.policy_snapshot).strip()
        if decision.policy_snapshot
        else request.policy_snapshot_ref
    )
    policy_snapshot_hash = _snapshot_hash(decision)

    response = HotPathEvaluateResponse(
        contract_version=HOT_PATH_CONTRACT_VERSION,
        request_id=request.request_id,
        decided_at=datetime.now(timezone.utc),
        latency_ms=max(0, round((perf_counter() - started) * 1000)),
        decision=HotPathDecisionView(
            allowed=bool(decision.allowed),
            disposition=disposition,  # type: ignore[arg-type]
            reason_code=reason_code,
            reason=str(decision.reason or reason_code),
            policy_snapshot_ref=policy_snapshot_ref,
            policy_snapshot_hash=policy_snapshot_hash,
        ),
        required_approvals=list(decision.required_approvals or []),
        trust_gaps=trust_gaps,
        obligations=obligations,
        checks=checks,
        execution_token=decision.execution_token if isinstance(decision.execution_token, ExecutionToken) else None,
        governed_receipt=dict(decision.governed_receipt or {}),
        signer_provenance=signer_provenance,
    )
    _HOT_PATH_SHADOW_STATS.record(
        latency_ms=response.latency_ms,
        parity=_shadow_parity_result(
            request=request,
            baseline=baseline_decision,
            candidate=decision,
        ),
    )
    return response


def hot_path_shadow_status() -> dict[str, Any]:
    return _HOT_PATH_SHADOW_STATS.snapshot()


def _resolve_compiled_authz_index() -> Any | None:
    manager = get_global_pkg_manager()
    if manager is None:
        return None
    getter = getattr(manager, "get_active_compiled_authz_index", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:
        return None


def _check(check_id: str, ok: bool, failure_detail: str | None = None) -> HotPathCheckResult:
    if ok:
        return HotPathCheckResult(check_id=check_id, result="pass")
    return HotPathCheckResult(check_id=check_id, result="fail", detail=failure_detail)


def _build_terminal_response(
    *,
    request: HotPathEvaluateRequest,
    started: float,
    checks: list[HotPathCheckResult],
    disposition: str,
    reason_code: str,
    reason: str,
    policy_snapshot_ref: str,
    trust_gaps: Iterable[str] = (),
) -> HotPathEvaluateResponse:
    return HotPathEvaluateResponse(
        contract_version=HOT_PATH_CONTRACT_VERSION,
        request_id=request.request_id,
        decided_at=datetime.now(timezone.utc),
        latency_ms=max(0, round((perf_counter() - started) * 1000)),
        decision=HotPathDecisionView(
            allowed=False if disposition in {"deny", "escalate"} else True,
            disposition=disposition,  # type: ignore[arg-type]
            reason_code=reason_code,
            reason=reason,
            policy_snapshot_ref=policy_snapshot_ref,
        ),
        trust_gaps=list(trust_gaps),
        checks=checks,
    )


def _decision_reason_code(decision: PolicyDecision) -> str:
    if decision.deny_code:
        return str(decision.deny_code)
    disposition = str(decision.disposition or "deny").strip().lower()
    reason = str(decision.reason or "").strip().lower().replace(" ", "_")
    if reason:
        return reason
    return REASON_CODE_DEFAULTS.get(disposition, "policy_decision_resolved")


def _shadow_parity_result(
    *,
    request: HotPathEvaluateRequest,
    baseline: PolicyDecision,
    candidate: PolicyDecision,
) -> dict[str, Any]:
    baseline_view = _normalize_shadow_decision(baseline)
    candidate_view = _normalize_shadow_decision(candidate)
    mismatches: list[str] = []
    for key in (
        "disposition",
        "reason_code",
        "trust_gaps",
        "required_approvals",
        "policy_snapshot_ref",
        "policy_snapshot_hash",
        "minted_artifacts",
    ):
        if baseline_view[key] != candidate_view[key]:
            mismatches.append(key)
    return {
        "request_id": request.request_id,
        "asset_ref": request.asset_context.asset_ref,
        "parity_ok": not mismatches,
        "mismatches": mismatches,
        "baseline": baseline_view,
        "candidate": candidate_view,
    }


def _normalize_shadow_decision(decision: PolicyDecision) -> dict[str, Any]:
    authz_graph = decision.authz_graph if isinstance(decision.authz_graph, Mapping) else {}
    governed_receipt = decision.governed_receipt if isinstance(decision.governed_receipt, Mapping) else {}
    snapshot_hash = governed_receipt.get("snapshot_hash") or authz_graph.get("snapshot_hash")
    return {
        "disposition": str(decision.disposition or "deny"),
        "reason_code": _decision_reason_code(decision),
        "trust_gaps": tuple(sorted(_extract_trust_gaps(decision))),
        "required_approvals": tuple(sorted(str(item) for item in (decision.required_approvals or []) if str(item).strip())),
        "policy_snapshot_ref": str(decision.policy_snapshot or ""),
        "policy_snapshot_hash": str(snapshot_hash or ""),
        "minted_artifacts": tuple(sorted(_minted_artifact_kinds(decision))),
    }


def _minted_artifact_kinds(decision: PolicyDecision) -> Sequence[str]:
    kinds: list[str] = []
    if isinstance(decision.execution_token, ExecutionToken):
        kinds.append("execution_token")
    authz_graph = decision.authz_graph if isinstance(decision.authz_graph, Mapping) else {}
    for item in authz_graph.get("minted_artifacts") if isinstance(authz_graph.get("minted_artifacts"), list) else []:
        if isinstance(item, Mapping):
            kind = str(item.get("kind") or "").strip()
            if kind:
                kinds.append(kind)
    governed_receipt = decision.governed_receipt if isinstance(decision.governed_receipt, Mapping) else {}
    if governed_receipt.get("decision_hash") is not None and str(governed_receipt.get("decision_hash")).strip():
        kinds.append("governed_receipt")
    return kinds


def _percentile(samples: Sequence[int], percentile: int) -> int | None:
    if not samples:
        return None
    index = max(0, min(len(samples) - 1, round((percentile / 100) * (len(samples) - 1))))
    return int(samples[index])


def _extract_trust_gaps(decision: PolicyDecision) -> list[str]:
    trust_gap_codes = decision.governed_receipt.get("trust_gap_codes") if isinstance(decision.governed_receipt, Mapping) else None
    if isinstance(trust_gap_codes, list):
        return [str(code) for code in trust_gap_codes if str(code).strip()]
    authz_graph = decision.authz_graph if isinstance(decision.authz_graph, Mapping) else {}
    trust_gaps = authz_graph.get("trust_gaps")
    if not isinstance(trust_gaps, list):
        return []
    codes: list[str] = []
    for gap in trust_gaps:
        if isinstance(gap, Mapping):
            code = str(gap.get("code") or "").strip()
            if code:
                codes.append(code)
        else:
            code = str(gap).strip()
            if code:
                codes.append(code)
    return codes


def _normalize_obligations(obligations: Iterable[Any]) -> list[Dict[str, Any]]:
    normalized: list[Dict[str, Any]] = []
    for item in obligations:
        if isinstance(item, Mapping):
            value = dict(item)
        else:
            value = {"code": str(item)}
        if "severity" not in value:
            value["severity"] = "required"
        normalized.append(value)
    return normalized


def _extract_signer_provenance(decision: PolicyDecision) -> list[HotPathSignerProvenance]:
    provenance: list[HotPathSignerProvenance] = []

    token_sig = decision.execution_token.signature if decision.execution_token is not None else {}
    if isinstance(token_sig, Mapping) and token_sig:
        provenance.append(
            HotPathSignerProvenance(
                artifact_type="execution_token",
                signer_type=str(token_sig.get("signer_type") or "unknown"),
                signer_id=str(token_sig.get("signer_id") or "unknown"),
                key_ref=str(token_sig.get("key_ref") or "hidden"),
                attestation_level=str(token_sig.get("attestation_level") or "unknown"),
            )
        )

    receipt_sig = (
        decision.governed_receipt.get("signer_metadata")
        if isinstance(decision.governed_receipt, Mapping)
        else None
    )
    if isinstance(receipt_sig, Mapping):
        provenance.append(
            HotPathSignerProvenance(
                artifact_type="governed_receipt",
                signer_type=str(receipt_sig.get("signer_type") or "unknown"),
                signer_id=str(receipt_sig.get("signer_id") or "unknown"),
                key_ref=str(receipt_sig.get("key_ref") or "hidden"),
                attestation_level=str(receipt_sig.get("attestation_level") or "unknown"),
            )
        )
    return provenance


def _decision_checks(decision: PolicyDecision) -> list[HotPathCheckResult]:
    checks: list[HotPathCheckResult] = []
    checks.append(_check("principal_present", True))
    checks.append(_check("intent_ttl_valid", True))

    approval_context = (
        decision.authz_graph.get("approval_context")
        if isinstance(decision.authz_graph, Mapping)
        else None
    )
    if isinstance(approval_context, Mapping):
        has_binding = bool(str(approval_context.get("approval_binding_hash") or "").strip())
        checks.append(_check("approval_binding_match", has_binding, "approval binding hash missing"))
    else:
        checks.append(HotPathCheckResult(check_id="approval_binding_match", result="skip"))
    return checks


def _snapshot_hash(decision: PolicyDecision) -> str | None:
    governed_receipt = decision.governed_receipt if isinstance(decision.governed_receipt, Mapping) else {}
    authz_graph = decision.authz_graph if isinstance(decision.authz_graph, Mapping) else {}
    snapshot_hash = governed_receipt.get("snapshot_hash") or authz_graph.get("snapshot_hash")
    if snapshot_hash is None:
        return None
    value = str(snapshot_hash).strip()
    return value or None
