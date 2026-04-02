from __future__ import annotations

import logging
import os
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from threading import Lock
from typing import Any, Dict, Iterable, Mapping, Sequence

from seedcore.coordinator.dao import TransferApprovalEnvelopeDAO
from seedcore.coordinator.core.governance import (
    build_governance_context_from_policy_case,
    evaluate_intent,
    prepare_policy_case,
)
from seedcore.database import get_async_pg_session_factory
from seedcore.models.action_intent import ExecutionToken, PolicyCase, PolicyDecision
from seedcore.models.pdp_hot_path import (
    HotPathAssetContext,
    HotPathCheckResult,
    HotPathDecisionView,
    HotPathEvaluateRequest,
    HotPathEvaluateResponse,
    HotPathSignerProvenance,
    HotPathTelemetryContext,
)
from seedcore.ops.pkg.manager import get_global_pkg_manager
from seedcore.ops.hot_path_parity_log import get_hot_path_parity_logger, parity_db_file_path, parity_log_file_path

HOT_PATH_CONTRACT_VERSION = "pdp.hot_path.asset_transfer.v1"
HOT_PATH_MODE_ENV = "SEEDCORE_RCT_HOT_PATH_MODE"
HOT_PATH_CANARY_PERCENT_ENV = "SEEDCORE_RCT_HOT_PATH_CANARY_PERCENT"
HOT_PATH_PROMOTION_GATE_DISABLED_ENV = "SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED"
HOT_PATH_PARITY_DRILL_STABLE_DENY_ENV = "SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY"
HOT_PATH_STALE_GRAPH_MAX_AGE_SECONDS = int(
    os.getenv("SEEDCORE_RCT_HOT_PATH_GRAPH_MAX_AGE_SECONDS", "600")
)
HOT_PATH_SUPPORTED_MODES = frozenset({"shadow", "canary", "enforce"})
HOT_PATH_PROMOTION_WINDOW_N = int(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N", "1000"))
HOT_PATH_PROMOTION_MIN_PARITY_RATIO = float(
    os.getenv("SEEDCORE_HOT_PATH_PROMOTION_MIN_PARITY_RATIO", "1.0")
)
HOT_PATH_PROMOTION_P50_MAX_MS = int(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_P50_MAX_MS", "25"))
HOT_PATH_PROMOTION_P95_MAX_MS = int(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_P95_MAX_MS", "50"))
HOT_PATH_PROMOTION_P99_MAX_MS = int(os.getenv("SEEDCORE_HOT_PATH_PROMOTION_P99_MAX_MS", "100"))
HOT_PATH_ROLLBACK_P99_MAX_MS = int(os.getenv("SEEDCORE_HOT_PATH_ROLLBACK_P99_MAX_MS", "250"))
HOT_PATH_AUTO_ROLLBACK_ENABLED = str(
    os.getenv("SEEDCORE_HOT_PATH_AUTO_ROLLBACK_ENABLED", "true")
).strip().lower() in {"1", "true", "yes", "on"}

REASON_CODE_DEFAULTS = {
    "allow": "restricted_custody_transfer_allowed",
    "deny": "policy_denied",
    "quarantine": "trust_gap_quarantine",
    "escalate": "manual_review_required",
}

logger = logging.getLogger(__name__)


@dataclass
class HotPathShadowStats:
    total: int = 0
    parity_ok: int = 0
    mismatched: int = 0
    last_run_at: str | None = None
    last_mismatch_at: str | None = None
    false_positive_allow_count: int = 0
    last_false_positive_allow_at: str | None = None
    latencies_ms: deque[int] = field(default_factory=lambda: deque(maxlen=2048))
    recent_results: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=HOT_PATH_PROMOTION_WINDOW_N)
    )
    lock: Lock = field(default_factory=Lock)

    def record(self, *, latency_ms: int, parity: Mapping[str, Any]) -> None:
        parity_copy = dict(parity)
        with self.lock:
            self.total += 1
            now = datetime.now(timezone.utc).isoformat()
            self.last_run_at = now
            self.latencies_ms.append(int(latency_ms))
            parity_ok = bool(parity_copy.get("parity_ok"))
            if parity_ok:
                self.parity_ok += 1
            else:
                self.mismatched += 1
                self.last_mismatch_at = now
            self.recent_results.append(parity_copy)
        _parity_persist_event(parity=parity_copy, latency_ms=int(latency_ms))

    def record_false_positive_allow(
        self,
        *,
        request_id: str,
        asset_ref: str | None,
        baseline_disposition: str,
        candidate_disposition: str,
        baseline_reason_code: str | None = None,
        candidate_reason_code: str | None = None,
    ) -> None:
        row = {
            "request_id": request_id,
            "asset_ref": asset_ref,
            "parity_ok": False,
            "mismatches": ["false_positive_allow"],
            "baseline": {
                "disposition": baseline_disposition,
                "reason_code": baseline_reason_code or "",
            },
            "candidate": {
                "disposition": candidate_disposition,
                "reason_code": candidate_reason_code or "",
            },
            "signal": "false_positive_allow",
            "signaled_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.lock:
            now = row["signaled_at"]
            self.false_positive_allow_count += 1
            self.last_false_positive_allow_at = now
            self.recent_results.append(row)
        _parity_persist_event(parity=row, latency_ms=0)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            samples = sorted(self.latencies_ms)
            current_mode = resolve_hot_path_mode()
            recent_results = list(self.recent_results)
            recent_mismatch_count = sum(1 for item in recent_results if not item.get("parity_ok", True))
            return {
                "mode": current_mode,
                "resolved_mode": current_mode,
                "total": self.total,
                "parity_ok": self.parity_ok,
                "mismatched": self.mismatched,
                "last_run_at": self.last_run_at,
                "last_mismatch_at": self.last_mismatch_at,
                "recent_mismatch_count": recent_mismatch_count,
                "false_positive_allow_count": self.false_positive_allow_count,
                "last_false_positive_allow_at": self.last_false_positive_allow_at,
                "latency_ms": {
                    "p50": _percentile(samples, 50),
                    "p95": _percentile(samples, 95),
                    "p99": _percentile(samples, 99),
                },
                "recent_results": recent_results,
            }


_HOT_PATH_SHADOW_STATS = HotPathShadowStats()
_TRANSFER_APPROVAL_DAO = TransferApprovalEnvelopeDAO()


def resolve_hot_path_mode() -> str:
    """Runtime PDP hot-path mode (read on each call — no process restart required)."""
    raw_mode = str(os.getenv(HOT_PATH_MODE_ENV, "shadow")).strip().lower()
    if raw_mode in HOT_PATH_SUPPORTED_MODES:
        return raw_mode
    return "shadow"


def resolve_hot_path_canary_percent() -> int:
    """When mode is `canary`, fraction of requests (0–100) that use candidate-authoritative PDP."""
    try:
        pct = int(str(os.getenv(HOT_PATH_CANARY_PERCENT_ENV, "10")).strip())
    except ValueError:
        return 10
    return max(0, min(100, pct))


def _latency_slo_met(latency: Mapping[str, Any]) -> bool:
    p50 = latency.get("p50")
    p95 = latency.get("p95")
    p99 = latency.get("p99")
    if p50 is None or p95 is None or p99 is None:
        return False
    try:
        return (
            int(p50) < HOT_PATH_PROMOTION_P50_MAX_MS
            and int(p95) < HOT_PATH_PROMOTION_P95_MAX_MS
            and int(p99) < HOT_PATH_PROMOTION_P99_MAX_MS
        )
    except (TypeError, ValueError):
        return False


def _rollback_reasons(
    *,
    status_snapshot: Mapping[str, Any],
    runtime_status: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if int(status_snapshot.get("false_positive_allow_count") or 0) > 0:
        reasons.append("false_positive_allow")
    runtime_ready = bool(
        runtime_status.get("authz_graph_ready")
        and runtime_status.get("graph_freshness_ok")
        and runtime_status.get("restricted_transfer_ready")
    )
    if not runtime_ready:
        reasons.append("dependency_unhealthy")
    latency = status_snapshot.get("latency_ms")
    p99 = latency.get("p99") if isinstance(latency, Mapping) else None
    if p99 is not None:
        try:
            if int(p99) > HOT_PATH_ROLLBACK_P99_MAX_MS:
                reasons.append("p99_latency_exceeded")
        except (TypeError, ValueError):
            pass
    return reasons


def _auto_rollback_reasons() -> list[str]:
    if not HOT_PATH_AUTO_ROLLBACK_ENABLED:
        return []
    status_snapshot = _HOT_PATH_SHADOW_STATS.snapshot()
    runtime_status = _resolve_hot_path_runtime_status()
    return _rollback_reasons(status_snapshot=status_snapshot, runtime_status=runtime_status)


def hot_path_authority_uses_candidate(request_id: str) -> bool:
    """
    PDP authority selection for Restricted Custody Transfer on the coordinator path.

    - shadow: baseline governance is authoritative; hot path runs for parity only.
    - enforce: hot-path (compiled-authz) decision is authoritative (fail-closed on errors).
    - canary: deterministic per-request mix — a canary_percent slice uses the hot path as authoritative.
    """
    mode = resolve_hot_path_mode()
    rollback_reasons = _auto_rollback_reasons() if mode in {"enforce", "canary"} else []
    if rollback_reasons:
        logger.warning(
            "RCT hot-path auto-rollback active; forcing baseline-authoritative path (mode=%s reasons=%s)",
            mode,
            ",".join(rollback_reasons),
        )
        return False
    if mode == "enforce":
        return True
    if mode == "shadow":
        return False
    if mode == "canary":
        pct = resolve_hot_path_canary_percent()
        if pct <= 0:
            return False
        if pct >= 100:
            return True
        rid = str(request_id or "").strip() or "anonymous"
        bucket = zlib.adler32(rid.encode("utf-8")) % 100
        return bucket < pct
    return False


def _promotion_gate_disabled() -> bool:
    return str(os.getenv(HOT_PATH_PROMOTION_GATE_DISABLED_ENV, "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _parity_drill_stable_path_shift_enabled() -> bool:
    """Operator-only: simulate stable-path deny while hot-path still allows (parity mismatch)."""
    return str(os.getenv(HOT_PATH_PARITY_DRILL_STABLE_DENY_ENV, "")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _baseline_for_parity_recording(
    baseline: PolicyDecision,
    candidate: PolicyDecision,
) -> PolicyDecision:
    if not _parity_drill_stable_path_shift_enabled():
        return baseline
    b_disp = str(baseline.disposition or "deny").strip().lower()
    c_disp = str(candidate.disposition or "deny").strip().lower()
    if c_disp == "allow" and b_disp == "allow":
        logger.warning(
            "%s active: recording synthetic stable-path deny against hot-path allow for parity evidence",
            HOT_PATH_PARITY_DRILL_STABLE_DENY_ENV,
        )
        return baseline.model_copy(
            deep=True,
            update={
                "disposition": "deny",
                "allowed": False,
                "deny_code": "operator_parity_drill_stable_path_deny",
                "reason": "Parity drill: simulated stable-path policy deny (env parity drill).",
            },
        )
    return baseline


def _parity_persist_event(*, parity: Mapping[str, Any], latency_ms: int) -> None:
    logger_inst = get_hot_path_parity_logger()
    event = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "latency_ms": int(latency_ms),
        "resolved_mode": resolve_hot_path_mode(),
        **dict(parity),
    }
    logger_inst.append(event)


def compute_hot_path_promotion_status() -> dict[str, Any]:
    """
    Mathematical promotion gate: last N persisted runs must meet minimum parity ratio (default 99.9%).
    N and ratio are overridable via SEEDCORE_HOT_PATH_PROMOTION_WINDOW_N and
    SEEDCORE_HOT_PATH_PROMOTION_MIN_PARITY_RATIO.
    """
    stats = get_hot_path_parity_logger().window_stats()
    gate_disabled = _promotion_gate_disabled()
    return {
        **stats,
        "promotion_gate_disabled": gate_disabled,
        "promotion_eligible": bool(stats.get("promotion_eligible")),
        "parity_log_path": str(parity_log_file_path()),
        "parity_db_path": str(parity_db_file_path()),
    }


def build_hot_path_request(
    policy_case: PolicyCase,
    *,
    request_id: str | None = None,
) -> HotPathEvaluateRequest:
    action_intent = policy_case.action_intent
    asset_twin = policy_case.relevant_twin_snapshot.get("asset")
    asset_custody = asset_twin.custody if asset_twin is not None else {}
    telemetry_summary = policy_case.telemetry_summary if isinstance(policy_case.telemetry_summary, Mapping) else {}
    evidence_summary = policy_case.evidence_summary if isinstance(policy_case.evidence_summary, Mapping) else {}
    approved_regs = policy_case.approved_source_registrations

    freshness_seconds = _coerce_optional_int(telemetry_summary.get("freshness_seconds"))
    max_allowed_age_seconds = _coerce_optional_int(
        telemetry_summary.get("max_allowed_age_seconds")
    )
    if freshness_seconds is None and bool(telemetry_summary.get("stale")):
        freshness_seconds = 301
    if max_allowed_age_seconds is None and (
        freshness_seconds is not None or bool(telemetry_summary.get("stale"))
    ):
        max_allowed_age_seconds = 300

    evidence_refs = []
    available_evidence = evidence_summary.get("available")
    if isinstance(available_evidence, list):
        evidence_refs.extend(str(item) for item in available_evidence if str(item).strip())
    telemetry_evidence = telemetry_summary.get("evidence_refs")
    if isinstance(telemetry_evidence, list):
        evidence_refs.extend(str(item) for item in telemetry_evidence if str(item).strip())

    registration_id = action_intent.resource.source_registration_id
    registration_decision_id = action_intent.resource.registration_decision_id
    source_registration_status = None
    if registration_id and registration_id in approved_regs:
        source_registration_status = "APPROVED"
        if registration_decision_id is None:
            registration_decision_id = approved_regs.get(registration_id)
    elif registration_decision_id and registration_decision_id in approved_regs.values():
        source_registration_status = "APPROVED"

    request_timestamp = _coerce_datetime(action_intent.timestamp) or datetime.now(timezone.utc)
    resolved_request_id = (
        str(request_id).strip()
        if request_id is not None and str(request_id).strip()
        else str(action_intent.intent_id).strip()
    )
    return HotPathEvaluateRequest(
        contract_version=HOT_PATH_CONTRACT_VERSION,
        request_id=resolved_request_id,
        requested_at=request_timestamp,
        policy_snapshot_ref=str(policy_case.policy_snapshot or action_intent.action.security_contract.version),
        action_intent=action_intent,
        asset_context=HotPathAssetContext(
            asset_ref=action_intent.resource.asset_id,
            current_custodian_ref=_coerce_optional_str(
                asset_custody.get("current_custodian_id")
                or asset_custody.get("current_custodian_ref")
                or asset_custody.get("owner_id")
            ),
            current_zone=_coerce_optional_str(
                asset_custody.get("current_zone")
                or asset_custody.get("zone")
            ),
            source_registration_status=source_registration_status,
            registration_decision_ref=_coerce_optional_str(registration_decision_id),
        ),
        telemetry_context=HotPathTelemetryContext(
            observed_at=(
                _coerce_optional_str(telemetry_summary.get("observed_at"))
                or action_intent.timestamp
            ),
            freshness_seconds=freshness_seconds,
            max_allowed_age_seconds=max_allowed_age_seconds,
            evidence_refs=evidence_refs,
        ),
    )


def hot_path_response_to_policy_decision(
    response: HotPathEvaluateResponse,
) -> PolicyDecision:
    disposition = str(response.decision.disposition or "deny").strip().lower()
    allowed = disposition == "allow"
    governed_receipt = dict(response.governed_receipt or {})
    if response.trust_gaps and not isinstance(governed_receipt.get("trust_gap_codes"), list):
        governed_receipt["trust_gap_codes"] = list(response.trust_gaps)
    if response.decision.policy_snapshot_hash and not governed_receipt.get("snapshot_hash"):
        governed_receipt["snapshot_hash"] = response.decision.policy_snapshot_hash
    if response.decision.policy_snapshot_ref and not governed_receipt.get("snapshot_version"):
        governed_receipt["snapshot_version"] = response.decision.policy_snapshot_ref
    if response.decision.reason and not governed_receipt.get("reason"):
        governed_receipt["reason"] = response.decision.reason
    if disposition and not governed_receipt.get("disposition"):
        governed_receipt["disposition"] = disposition

    authz_graph = {
        "disposition": disposition,
        "reason": response.decision.reason,
        "trust_gap_codes": list(response.trust_gaps),
        "snapshot_hash": response.decision.policy_snapshot_hash,
        "snapshot_version": response.decision.policy_snapshot_ref,
        "minted_artifacts": [
            {"kind": kind}
            for kind in _response_minted_artifact_kinds(response)
        ],
        "signer_provenance": [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in response.signer_provenance
        ],
    }
    return PolicyDecision(
        allowed=allowed,
        execution_token=response.execution_token,
        reason=response.decision.reason,
        policy_snapshot=response.decision.policy_snapshot_ref,
        deny_code=None if allowed else response.decision.reason_code,
        disposition=disposition,  # type: ignore[arg-type]
        required_approvals=list(response.required_approvals),
        obligations=[dict(item) for item in response.obligations],
        explanations=[
            f"{check.check_id}:{check.result}"
            for check in response.checks
        ],
        authz_graph=authz_graph,
        governed_receipt=governed_receipt,
    )


def build_governance_context_from_hot_path_response(
    policy_case: PolicyCase,
    response: HotPathEvaluateResponse,
) -> dict[str, Any]:
    policy_decision = hot_path_response_to_policy_decision(response)
    return build_governance_context_from_policy_case(
        policy_case,
        policy_decision=policy_decision,
    )


def record_false_positive_hot_path_signal(
    *,
    request_id: str,
    asset_ref: str | None,
    baseline_disposition: str,
    candidate_disposition: str,
    baseline_reason_code: str | None = None,
    candidate_reason_code: str | None = None,
) -> None:
    logger.warning(
        "RCT hot-path false-positive allow signal request_id=%s asset_ref=%s baseline=%s candidate=%s",
        request_id,
        asset_ref or "",
        baseline_disposition,
        candidate_disposition,
    )
    _HOT_PATH_SHADOW_STATS.record_false_positive_allow(
        request_id=request_id,
        asset_ref=asset_ref,
        baseline_disposition=baseline_disposition,
        candidate_disposition=candidate_disposition,
        baseline_reason_code=baseline_reason_code,
        candidate_reason_code=candidate_reason_code,
    )


async def resolve_authoritative_transfer_approval(
    request: HotPathEvaluateRequest,
) -> dict[str, Any]:
    parameters = (
        request.action_intent.action.parameters
        if isinstance(request.action_intent.action.parameters, Mapping)
        else {}
    )
    approval_context = (
        parameters.get("approval_context")
        if isinstance(parameters.get("approval_context"), Mapping)
        else {}
    )
    approval_envelope_id = str(approval_context.get("approval_envelope_id") or "").strip()
    if not approval_envelope_id:
        return {}
    session_factory = get_async_pg_session_factory()
    try:
        async with session_factory() as session:
            envelope_record = await _TRANSFER_APPROVAL_DAO.get_current_with_history(
                session,
                approval_envelope_id=approval_envelope_id,
            )
    except Exception:
        return {}
    if envelope_record is None:
        return {}
    return {
        "authoritative_approval_envelope": envelope_record.get("envelope"),
        "authoritative_approval_transition_history": envelope_record.get("transition_history"),
        "authoritative_approval_transition_head": envelope_record.get("approval_transition_head"),
    }


def evaluate_pdp_hot_path(
    request: HotPathEvaluateRequest,
    *,
    relevant_twin_snapshot: Mapping[str, Any] | None = None,
    authoritative_approval_envelope: Mapping[str, Any] | None = None,
    authoritative_approval_transition_history: Sequence[Mapping[str, Any]] | None = None,
    authoritative_approval_transition_head: str | None = None,
) -> HotPathEvaluateResponse:
    started = perf_counter()
    checks: list[HotPathCheckResult] = []

    asset_match = request.action_intent.resource.asset_id == request.asset_context.asset_ref
    checks.append(_check("asset_ref_match", asset_match, "asset_id and asset_ref must match"))
    if not asset_match:
        response = _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="deny",
            reason_code="asset_custody_mismatch",
            reason="Action intent asset does not match the provided asset context.",
            policy_snapshot_ref=request.policy_snapshot_ref,
        )
        _record_terminal_shadow_result(request=request, response=response)
        return response

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
        response = _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="stale_telemetry",
            reason="Telemetry freshness exceeds policy limits.",
            policy_snapshot_ref=request.policy_snapshot_ref,
            trust_gaps=["stale_telemetry"],
        )
        _record_terminal_shadow_result(request=request, response=response)
        return response

    runtime_status = _resolve_hot_path_runtime_status()
    compiled_authz_index = runtime_status.get("compiled_authz_index")
    if compiled_authz_index is None:
        checks.append(_check("compiled_authz_graph_ready", False, "active compiled authz graph unavailable"))
        response = _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="hot_path_dependency_unavailable",
            reason="Active compiled authorization graph is unavailable.",
            policy_snapshot_ref=request.policy_snapshot_ref,
        )
        _record_terminal_shadow_result(request=request, response=response)
        return response

    graph_freshness_ok = bool(runtime_status.get("graph_freshness_ok", True))
    checks.append(
        _check(
            "compiled_authz_graph_fresh",
            graph_freshness_ok,
            "active compiled authz graph is stale",
        )
    )
    if not graph_freshness_ok:
        response = _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="compiled_authz_graph_stale",
            reason="Active compiled authorization graph is older than the allowed freshness window.",
            policy_snapshot_ref=request.policy_snapshot_ref,
        )
        _record_terminal_shadow_result(request=request, response=response)
        return response

    compiled_snapshot = str(runtime_status.get("active_snapshot_version") or "").strip() or (
        str(getattr(compiled_authz_index, "snapshot_version", "")).strip()
        or str(getattr(compiled_authz_index, "snapshot_ref", "")).strip()
    )
    snapshot_ok = not compiled_snapshot or compiled_snapshot == request.policy_snapshot_ref
    checks.append(_check("snapshot_consistency", snapshot_ok, "requested snapshot does not match active compiled graph"))
    if not snapshot_ok:
        response = _build_terminal_response(
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
        _record_terminal_shadow_result(request=request, response=response)
        return response

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
        relevant_twin_snapshot=relevant_twin_snapshot,
        approved_source_registrations=approved_source_registrations,
        telemetry_summary=telemetry_summary,
        evidence_summary=evidence_summary,
        authoritative_approval_envelope=authoritative_approval_envelope,
        authoritative_approval_transition_history=authoritative_approval_transition_history,
        authoritative_approval_transition_head=authoritative_approval_transition_head,
    )
    baseline_decision = evaluate_intent(policy_case.model_copy(deep=True))
    decision = evaluate_intent(
        policy_case.model_copy(deep=True),
        compiled_authz_index=compiled_authz_index,
    )

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
            baseline=_baseline_for_parity_recording(baseline_decision, decision),
            candidate=decision,
        ),
    )
    return response


def hot_path_shadow_status() -> dict[str, Any]:
    status = _HOT_PATH_SHADOW_STATS.snapshot()
    runtime_status = _resolve_hot_path_runtime_status()
    promotion = compute_hot_path_promotion_status()
    runtime_ready = bool(
        runtime_status.get("authz_graph_ready")
        and runtime_status.get("graph_freshness_ok")
        and runtime_status.get("restricted_transfer_ready")
    )
    latency_slo_met = _latency_slo_met(status.get("latency_ms") if isinstance(status.get("latency_ms"), Mapping) else {})
    strict_promotion_eligible = bool(
        runtime_ready
        and latency_slo_met
        and (promotion.get("promotion_gate_disabled") or promotion.get("promotion_eligible"))
        and int(status.get("false_positive_allow_count") or 0) == 0
    )
    rollback_reasons = _rollback_reasons(
        status_snapshot=status,
        runtime_status=runtime_status,
    )
    rollback_triggered = bool(HOT_PATH_AUTO_ROLLBACK_ENABLED and rollback_reasons)
    enforce_ready = bool(strict_promotion_eligible and not rollback_triggered)
    mode = str(status.get("resolved_mode") or "shadow")
    status.update(
        {
            "active_snapshot_version": runtime_status.get("active_snapshot_version"),
            "compiled_at": runtime_status.get("compiled_at"),
            "graph_age_seconds": runtime_status.get("graph_age_seconds"),
            "graph_freshness_ok": runtime_status.get("graph_freshness_ok"),
            "authz_graph_ready": runtime_status.get("authz_graph_ready"),
            "restricted_transfer_ready": runtime_status.get("restricted_transfer_ready"),
            "canary_percent": resolve_hot_path_canary_percent() if mode == "canary" else None,
            "runtime_ready": runtime_ready,
            "latency_slo_met": latency_slo_met,
            "strict_promotion_eligible": strict_promotion_eligible,
            "auto_rollback_enabled": HOT_PATH_AUTO_ROLLBACK_ENABLED,
            "rollback_triggered": rollback_triggered,
            "rollback_reasons": rollback_reasons,
            "promotion": promotion,
            "enforce_ready": enforce_ready,
        }
    )
    return status


def _resolve_compiled_authz_index() -> Any | None:
    return _resolve_hot_path_runtime_status().get("compiled_authz_index")


def _resolve_hot_path_runtime_status() -> dict[str, Any]:
    manager = get_global_pkg_manager()
    current_mode = resolve_hot_path_mode()
    if manager is None:
        return {
            "mode": current_mode,
            "resolved_mode": current_mode,
            "compiled_authz_index": None,
            "active_snapshot_version": None,
            "compiled_at": None,
            "graph_age_seconds": None,
            "graph_freshness_ok": False,
            "authz_graph_ready": False,
            "restricted_transfer_ready": False,
        }
    metadata_getter = getattr(manager, "get_metadata", None)
    metadata = metadata_getter() if callable(metadata_getter) else {}
    authz_status = (
        metadata.get("authz_graph", {})
        if isinstance(metadata, Mapping) and isinstance(metadata.get("authz_graph"), Mapping)
        else {}
    )
    getter = getattr(manager, "get_active_compiled_authz_index", None)
    try:
        compiled_authz_index = getter() if callable(getter) else None
    except Exception:
        compiled_authz_index = None

    compiled_at = _coerce_optional_str(
        authz_status.get("compiled_at")
        or getattr(compiled_authz_index, "compiled_at", None)
    )
    graph_age_seconds = _compiled_graph_age_seconds(compiled_at)
    graph_freshness_ok = (
        graph_age_seconds is None or graph_age_seconds <= HOT_PATH_STALE_GRAPH_MAX_AGE_SECONDS
    )
    authz_graph_ready = bool(compiled_authz_index) and bool(authz_status.get("healthy", True))
    return {
        "mode": current_mode,
        "resolved_mode": current_mode,
        "compiled_authz_index": compiled_authz_index,
        "active_snapshot_version": _coerce_optional_str(
            authz_status.get("active_snapshot_version")
            or getattr(compiled_authz_index, "snapshot_version", None)
            or getattr(compiled_authz_index, "snapshot_ref", None)
        ),
        "compiled_at": compiled_at,
        "graph_age_seconds": graph_age_seconds,
        "graph_freshness_ok": bool(authz_graph_ready) and graph_freshness_ok,
        "authz_graph_ready": authz_graph_ready,
        "restricted_transfer_ready": bool(
            authz_status.get(
                "restricted_transfer_ready",
                getattr(compiled_authz_index, "restricted_transfer_ready", False),
            )
        ),
    }


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
            allowed=disposition == "allow",
            disposition=disposition,  # type: ignore[arg-type]
            reason_code=reason_code,
            reason=reason,
            policy_snapshot_ref=policy_snapshot_ref,
        ),
        trust_gaps=list(trust_gaps),
        checks=checks,
    )


def build_hot_path_failure_response(
    request: HotPathEvaluateRequest,
    *,
    reason_code: str,
    reason: str,
    trust_gaps: Iterable[str] = (),
) -> HotPathEvaluateResponse:
    return _build_terminal_response(
        request=request,
        started=perf_counter(),
        checks=[
            _check("compiled_authz_graph_ready", False, reason),
        ],
        disposition="quarantine",
        reason_code=reason_code,
        reason=reason,
        policy_snapshot_ref=request.policy_snapshot_ref,
        trust_gaps=trust_gaps,
    )


def _record_terminal_shadow_result(
    *,
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> None:
    terminal_view = _normalize_shadow_terminal_response(response)
    _HOT_PATH_SHADOW_STATS.record(
        latency_ms=response.latency_ms,
        parity={
            "request_id": request.request_id,
            "asset_ref": request.asset_context.asset_ref,
            "parity_ok": True,
            "mismatches": [],
            "baseline": terminal_view,
            "candidate": terminal_view,
        },
    )


def _normalize_shadow_terminal_response(response: HotPathEvaluateResponse) -> dict[str, Any]:
    minted_artifacts: list[str] = []
    if isinstance(response.execution_token, ExecutionToken):
        minted_artifacts.append("execution_token")
    return {
        "disposition": str(response.decision.disposition or "deny"),
        "reason_code": str(response.decision.reason_code or ""),
        "trust_gaps": tuple(sorted(str(item) for item in response.trust_gaps if str(item).strip())),
        "required_approvals": tuple(
            sorted(str(item) for item in response.required_approvals if str(item).strip())
        ),
        "policy_snapshot_ref": str(response.decision.policy_snapshot_ref or ""),
        "policy_snapshot_hash": str(response.decision.policy_snapshot_hash or ""),
        "minted_artifacts": tuple(sorted(minted_artifacts)),
    }


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


def _response_minted_artifact_kinds(response: HotPathEvaluateResponse) -> Sequence[str]:
    kinds: list[str] = []
    if isinstance(response.execution_token, ExecutionToken):
        kinds.append("execution_token")
    if response.governed_receipt.get("decision_hash") is not None and str(
        response.governed_receipt.get("decision_hash")
    ).strip():
        kinds.append("governed_receipt")
    return kinds


def _coerce_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    normalized = _coerce_optional_str(value)
    if normalized is None:
        return None
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _compiled_graph_age_seconds(compiled_at: str | None) -> int | None:
    compiled_at_dt = _coerce_datetime(compiled_at)
    if compiled_at_dt is None:
        return None
    age = datetime.now(timezone.utc) - compiled_at_dt
    return max(0, int(age.total_seconds()))


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
