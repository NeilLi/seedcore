from __future__ import annotations

import json
import logging
import os
import queue
import urllib.error
import urllib.request
import zlib
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from threading import Lock, Thread
from typing import Any, Dict, Iterable, Mapping, Sequence

from seedcore.coordinator.dao import TransferApprovalEnvelopeDAO
from seedcore.coordinator.core.governance import (
    build_governance_context_from_policy_case,
    evaluate_intent,
    prepare_policy_case,
)
from seedcore.database import get_async_pg_session_factory
from seedcore.infra.kafka.policy_outcome import publish_pdp_hot_path_policy_outcome_best_effort
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
from seedcore.ops.evidence.rct_replay_verification import apply_rct_triple_hash_fields
from seedcore.ops.hot_path_parity_log import get_hot_path_parity_logger, parity_db_file_path, parity_log_file_path

try:
    # Keep the module namespace aligned with the current package import path.
    from .pkg.manager import get_global_pkg_manager as _get_global_pkg_manager
except ImportError:  # pragma: no cover - fallback for alternate import roots
    from seedcore.ops.pkg.manager import get_global_pkg_manager as _get_global_pkg_manager

# Backward-compatible symbol for tests/monkeypatch hooks.
get_global_pkg_manager = _get_global_pkg_manager

HOT_PATH_CONTRACT_VERSION = "pdp.hot_path.asset_transfer.v1"
HOT_PATH_MODE_ENV = "SEEDCORE_RCT_HOT_PATH_MODE"
HOT_PATH_CANARY_PERCENT_ENV = "SEEDCORE_RCT_HOT_PATH_CANARY_PERCENT"
HOT_PATH_PROMOTION_GATE_DISABLED_ENV = "SEEDCORE_HOT_PATH_PROMOTION_GATE_DISABLED"
HOT_PATH_PARITY_DRILL_STABLE_DENY_ENV = "SEEDCORE_HOT_PATH_PARITY_DRILL_STABLE_DENY"
GOVERNANCE_SHADOW_ENABLED_ENV = "SEEDCORE_ENABLE_GOVERNANCE_SHADOW_ADVISORY"
GOVERNANCE_SHADOW_URL_ENV = "SEEDCORE_GOVERNANCE_SHADOW_ADVISORY_URL"
GOVERNANCE_SHADOW_QUEUE_SIZE_ENV = "SEEDCORE_GOVERNANCE_SHADOW_QUEUE_SIZE"
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


def _resolve_pkg_manager():
    manager = get_global_pkg_manager()
    if manager is not None:
        return manager
    # Some runtimes import SeedCore under "src.seedcore.*" while others use
    # "seedcore.*"; probe both globals to avoid split-manager false negatives.
    try:  # pragma: no cover - depends on runtime package root
        from src.seedcore.ops.pkg.manager import get_global_pkg_manager as _get_src_manager
    except Exception:
        return manager
    try:
        return _get_src_manager()
    except Exception:
        return manager


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
_GOVERNANCE_SHADOW_QUEUE: queue.Queue[dict[str, Any]] | None = None
_GOVERNANCE_SHADOW_QUEUE_LOCK = Lock()
_GOVERNANCE_SHADOW_WORKER_STARTED = False


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


def _hot_path_runtime_ready(runtime_status: Mapping[str, Any]) -> bool:
    return bool(
        runtime_status.get("authz_graph_ready")
        and runtime_status.get("graph_freshness_ok")
        and runtime_status.get("restricted_transfer_ready")
    )


def _strict_promotion_eligible(
    *,
    status_snapshot: Mapping[str, Any],
    runtime_status: Mapping[str, Any],
    promotion: Mapping[str, Any],
) -> bool:
    latency = status_snapshot.get("latency_ms")
    latency_slo_met = _latency_slo_met(latency if isinstance(latency, Mapping) else {})
    return bool(
        _hot_path_runtime_ready(runtime_status)
        and latency_slo_met
        and (promotion.get("promotion_gate_disabled") or promotion.get("promotion_eligible"))
        and int(status_snapshot.get("false_positive_allow_count") or 0) == 0
    )


def _rollback_reasons(
    *,
    status_snapshot: Mapping[str, Any],
    runtime_status: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if int(status_snapshot.get("false_positive_allow_count") or 0) > 0:
        reasons.append("false_positive_allow")
    if not _hot_path_runtime_ready(runtime_status):
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


def _build_hot_path_observability(status: Mapping[str, Any]) -> dict[str, Any]:
    """Cluster/Ray scrape-friendly signals and operator alerting hints (additive contract)."""
    alerts: list[dict[str, Any]] = []

    def add(severity: str, code: str, message: str) -> None:
        alerts.append({"severity": severity, "code": code, "message": message})

    if bool(status.get("rollback_triggered")):
        add(
            "critical",
            "rollback_active",
            "Hot-path auto-rollback is active; do not treat candidate PDP as promotion-eligible.",
        )
    if int(status.get("false_positive_allow_count") or 0) > 0:
        add(
            "critical",
            "false_positive_allow",
            "False-positive allow signals were recorded on the shadow hot path.",
        )
    if not bool(status.get("graph_freshness_ok", True)):
        add("warning", "graph_stale", "Authz graph failed freshness checks.")
    if not bool(status.get("authz_graph_ready", True)):
        add("warning", "authz_not_ready", "Compiled authz index is not ready.")
    if not bool(status.get("latency_slo_met", True)):
        add("warning", "latency_slo", "Hot-path latency percentiles exceed promotion SLOs.")

    recent_mm = int(status.get("recent_mismatch_count") or 0)
    total_runs = int(status.get("total") or 0)
    if recent_mm > 0 and total_runs >= 50:
        add(
            "warning",
            "parity_mismatch_window",
            f"Sliding promotion window includes {recent_mm} parity mismatches.",
        )

    critical = any(a["severity"] == "critical" for a in alerts)
    warning = any(a["severity"] == "warning" for a in alerts)
    if critical:
        level = "critical"
    elif warning:
        level = "warning"
    else:
        level = "ok"

    lat = status.get("latency_ms")
    p99 = lat.get("p99") if isinstance(lat, Mapping) else None
    prom = status.get("promotion") if isinstance(status.get("promotion"), Mapping) else {}

    return {
        "contract_version": "seedcore.observability.hot_path.v1",
        "deployment_role": (str(os.getenv("SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE", "")).strip() or None),
        "alert_level": level,
        "alerts": alerts,
        "gauges": {
            "total_runs": total_runs,
            "recent_mismatch_count": recent_mm,
            "parity_ok": int(status.get("parity_ok") or 0),
            "mismatched_total": int(status.get("mismatched") or 0),
            "p99_ms": p99,
            "graph_age_seconds": status.get("graph_age_seconds"),
            "graph_freshness_ok": bool(status.get("graph_freshness_ok")),
            "authz_graph_ready": bool(status.get("authz_graph_ready")),
            "latency_slo_met": bool(status.get("latency_slo_met")),
            "strict_promotion_eligible": bool(status.get("strict_promotion_eligible")),
            "rollback_triggered": bool(status.get("rollback_triggered")),
            "promotion_window_healthy": bool(prom.get("promotion_eligible")) if prom else None,
        },
    }


def _auto_rollback_reasons() -> list[str]:
    if not HOT_PATH_AUTO_ROLLBACK_ENABLED:
        return []
    status_snapshot = _HOT_PATH_SHADOW_STATS.snapshot()
    runtime_status = _resolve_hot_path_runtime_status()
    return _rollback_reasons(status_snapshot=status_snapshot, runtime_status=runtime_status)


def _is_promotion_eligible() -> bool:
    status = _HOT_PATH_SHADOW_STATS.snapshot()
    runtime_status = _resolve_hot_path_runtime_status()
    promotion = compute_hot_path_promotion_status()
    return _strict_promotion_eligible(
        status_snapshot=status,
        runtime_status=runtime_status,
        promotion=promotion,
    )


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

    if mode in {"enforce", "canary"}:
        if not _is_promotion_eligible():
            logger.warning(
                "RCT hot-path promotion eligibility not met; forcing baseline-authoritative path (mode=%s)",
                mode,
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
    normalized = baseline
    baseline_ref = str(baseline.policy_snapshot or "").strip()
    candidate_ref = str(candidate.policy_snapshot or "").strip()
    baseline_hash = _snapshot_hash(baseline)
    candidate_hash = _snapshot_hash(candidate)
    if baseline_ref and baseline_ref == candidate_ref and not baseline_hash and candidate_hash:
        authz_graph = (
            dict(baseline.authz_graph)
            if isinstance(baseline.authz_graph, Mapping)
            else {}
        )
        governed_receipt = (
            dict(baseline.governed_receipt)
            if isinstance(baseline.governed_receipt, Mapping)
            else {}
        )
        authz_graph.setdefault("snapshot_hash", candidate_hash)
        governed_receipt.setdefault("snapshot_hash", candidate_hash)
        normalized = baseline.model_copy(
            deep=True,
            update={
                "authz_graph": authz_graph,
                "governed_receipt": governed_receipt,
            },
        )
    if not _parity_drill_stable_path_shift_enabled():
        return normalized
    b_disp = str(normalized.disposition or "deny").strip().lower()
    c_disp = str(candidate.disposition or "deny").strip().lower()
    if c_disp == "allow" and b_disp == "allow":
        logger.warning(
            "%s active: recording synthetic stable-path deny against hot-path allow for parity evidence",
            HOT_PATH_PARITY_DRILL_STABLE_DENY_ENV,
        )
        return normalized.model_copy(
            deep=True,
            update={
                "disposition": "deny",
                "allowed": False,
                "deny_code": "operator_parity_drill_stable_path_deny",
                "reason": "Parity drill: simulated stable-path policy deny (env parity drill).",
            },
        )
    return normalized


def _parity_persist_event(*, parity: Mapping[str, Any], latency_ms: int) -> None:
    logger_inst = get_hot_path_parity_logger()
    event = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "latency_ms": int(latency_ms),
        "resolved_mode": resolve_hot_path_mode(),
        **dict(parity),
    }
    logger_inst.append(event)


def _parse_hot_path_datetime(value: Any) -> datetime | None:
    try:
        return _coerce_datetime(value)
    except (TypeError, ValueError):
        return None


def _non_empty(value: Any) -> bool:
    return bool(str(value or "").strip())


def _validate_context_freshness_bound(
    request: HotPathEvaluateRequest,
    *,
    checks: list[HotPathCheckResult],
    started: float,
) -> HotPathEvaluateResponse | None:
    freshness = request.context_freshness
    if freshness is None:
        return None

    if not _non_empty(freshness.local_view_ref):
        checks.append(
            _check(
                "context_freshness_bound",
                False,
                "context_freshness.local_view_ref is required when context_freshness is provided",
            )
        )
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="context_freshness_unavailable",
            reason="Context freshness was provided without a required local view reference.",
            policy_snapshot_ref=request.policy_snapshot_ref,
            trust_gaps=["context_freshness_unavailable"],
        )

    minimum_observed_at = str(freshness.minimum_observed_at or "").strip()
    if not minimum_observed_at:
        checks.append(_check("context_freshness_bound", True))
        return None

    minimum_dt = _parse_hot_path_datetime(minimum_observed_at)
    observed_dt = _parse_hot_path_datetime(request.telemetry_context.observed_at)
    if minimum_dt is None or observed_dt is None:
        checks.append(
            _check(
                "context_freshness_bound",
                False,
                "context freshness or telemetry observed_at timestamp is invalid",
            )
        )
        return _build_terminal_response(
            request=request,
            started=started,
            checks=checks,
            disposition="quarantine",
            reason_code="context_freshness_invalid_timestamp",
            reason="Context freshness timestamps could not be parsed safely.",
            policy_snapshot_ref=request.policy_snapshot_ref,
            trust_gaps=["stale_context"],
        )

    freshness_ok = observed_dt >= minimum_dt
    checks.append(
        _check(
            "context_freshness_bound",
            freshness_ok,
            "telemetry observed_at is older than context_freshness.minimum_observed_at",
        )
    )
    if freshness_ok:
        return None
    return _build_terminal_response(
        request=request,
        started=started,
        checks=checks,
        disposition="quarantine",
        reason_code="context_freshness_below_required_bound",
        reason="Telemetry context is older than the required local-view freshness bound.",
        policy_snapshot_ref=request.policy_snapshot_ref,
        trust_gaps=["stale_context"],
    )


def _signed_context_envelope_failure_detail(request: HotPathEvaluateRequest) -> str | None:
    for envelope in request.signed_context_envelopes:
        for field_name in ("envelope_id", "issuer", "issued_at", "claims_hash", "signature_ref"):
            if not _non_empty(getattr(envelope, field_name, None)):
                return f"signed_context_envelopes.{field_name} must not be empty"
        claims_hash = str(envelope.claims_hash).strip()
        if not claims_hash.startswith("sha256:") or not claims_hash.removeprefix("sha256:").strip():
            return "signed_context_envelopes.claims_hash must be a sha256: reference"
        if _parse_hot_path_datetime(envelope.issued_at) is None:
            return "signed_context_envelopes.issued_at must be a valid timestamp"
        for caveat in envelope.caveats:
            caveat_text = str(caveat or "").strip()
            if not caveat_text:
                return "signed_context_envelopes.caveats must not contain empty entries"
            if "=" not in caveat_text:
                continue
            key, value = (part.strip() for part in caveat_text.split("=", 1))
            if key == "asset_id" and value != request.asset_context.asset_ref:
                return "signed_context_envelopes asset_id caveat does not match asset_context.asset_ref"
            if key == "target_zone" and value != str(request.action_intent.resource.target_zone or "").strip():
                return "signed_context_envelopes target_zone caveat does not match action_intent.resource.target_zone"
    return None


def _validate_signed_context_envelopes(
    request: HotPathEvaluateRequest,
    *,
    checks: list[HotPathCheckResult],
    started: float,
) -> HotPathEvaluateResponse | None:
    if not request.signed_context_envelopes:
        return None

    failure_detail = _signed_context_envelope_failure_detail(request)
    checks.append(
        _check(
            "signed_context_envelope_structural",
            failure_detail is None,
            failure_detail,
        )
    )
    if failure_detail is None:
        return None
    return _build_terminal_response(
        request=request,
        started=started,
        checks=checks,
        disposition="quarantine",
        reason_code="signed_context_envelope_invalid",
        reason="Signed context envelope failed deterministic structural or scope validation.",
        policy_snapshot_ref=request.policy_snapshot_ref,
        trust_gaps=["signed_context_envelope_invalid"],
    )


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
    request_schema_bundle, taxonomy_bundle = _resolve_active_hot_path_contract_bundles(policy_case)
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
        request_schema_bundle=request_schema_bundle,
        taxonomy_bundle=taxonomy_bundle,
    )


def hot_path_response_to_policy_decision(
    response: HotPathEvaluateResponse,
) -> PolicyDecision:
    disposition = str(response.decision.disposition or "deny").strip().lower()
    allowed = disposition == "allow"
    governed_receipt = dict(response.governed_receipt or {})
    if response.trust_gaps and not isinstance(governed_receipt.get("trust_gap_codes"), list):
        governed_receipt["trust_gap_codes"] = list(response.trust_gaps)
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
        "snapshot_hash": governed_receipt.get("snapshot_hash") or response.decision.policy_snapshot_hash,
        "snapshot_version": governed_receipt.get("snapshot_version") or response.decision.policy_snapshot_ref,
        "minted_artifacts": [
            {"kind": kind}
            for kind in _response_minted_artifact_kinds(response)
        ],
        "signer_provenance": [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in response.signer_provenance
        ],
    }
    if governed_receipt.get("policy_snapshot_hash"):
        authz_graph["policy_snapshot_hash"] = governed_receipt["policy_snapshot_hash"]
    if governed_receipt.get("decision_graph_snapshot_hash"):
        authz_graph["decision_graph_snapshot_hash"] = governed_receipt["decision_graph_snapshot_hash"]
    if isinstance(response.request_schema_bundle, Mapping) and response.request_schema_bundle:
        authz_graph["request_schema_bundle"] = dict(response.request_schema_bundle)
    if isinstance(response.taxonomy_bundle, Mapping) and response.taxonomy_bundle:
        authz_graph["taxonomy_bundle"] = dict(response.taxonomy_bundle)
        governed_receipt["taxonomy_bundle"] = dict(response.taxonomy_bundle)
    if isinstance(response.request_schema_bundle, Mapping) and response.request_schema_bundle:
        governed_receipt["request_schema_bundle"] = dict(response.request_schema_bundle)
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


def _resolve_active_hot_path_contract_bundles(
    policy_case: PolicyCase,
) -> tuple[Dict[str, Any] | None, Dict[str, Any] | None]:
    manager = _resolve_pkg_manager()
    if manager is None:
        return None, None

    metadata = {}
    metadata_getter = getattr(manager, "get_metadata", None)
    if callable(metadata_getter):
        metadata = metadata_getter() or {}
    active_version = None
    if isinstance(metadata, Mapping):
        active_version = (
            metadata.get("active_version")
            or (metadata.get("authz_graph") or {}).get("active_snapshot_version")
        )
    policy_snapshot = str(policy_case.policy_snapshot or "").strip()
    if policy_snapshot and active_version and policy_snapshot != str(active_version).strip():
        return None, None

    request_schema_getter = getattr(manager, "get_active_request_schema_bundle", None)
    taxonomy_getter = getattr(manager, "get_active_taxonomy_bundle", None)
    request_schema_bundle = request_schema_getter() if callable(request_schema_getter) else None
    taxonomy_bundle = taxonomy_getter() if callable(taxonomy_getter) else None

    resolved_request_schema_bundle = (
        dict(request_schema_bundle)
        if isinstance(request_schema_bundle, Mapping) and request_schema_bundle
        else None
    )
    resolved_taxonomy_bundle = (
        dict(taxonomy_bundle)
        if isinstance(taxonomy_bundle, Mapping) and taxonomy_bundle
        else None
    )
    return resolved_request_schema_bundle, resolved_taxonomy_bundle


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


def _governance_shadow_enabled() -> bool:
    return str(os.getenv(GOVERNANCE_SHADOW_ENABLED_ENV, "false")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _governance_shadow_advisory_url() -> str:
    return (
        str(os.getenv(GOVERNANCE_SHADOW_URL_ENV, "")).strip()
        or "http://127.0.0.1:8000/xgboost/governance/advisory"
    )


def _governance_shadow_queue_size() -> int:
    try:
        return max(1, int(str(os.getenv(GOVERNANCE_SHADOW_QUEUE_SIZE_ENV, "256")).strip()))
    except ValueError:
        return 256


def _get_governance_shadow_queue() -> queue.Queue[dict[str, Any]]:
    global _GOVERNANCE_SHADOW_QUEUE
    with _GOVERNANCE_SHADOW_QUEUE_LOCK:
        if _GOVERNANCE_SHADOW_QUEUE is None:
            _GOVERNANCE_SHADOW_QUEUE = queue.Queue(maxsize=_governance_shadow_queue_size())
        return _GOVERNANCE_SHADOW_QUEUE


def _ensure_governance_shadow_worker() -> None:
    global _GOVERNANCE_SHADOW_WORKER_STARTED
    with _GOVERNANCE_SHADOW_QUEUE_LOCK:
        if _GOVERNANCE_SHADOW_WORKER_STARTED:
            return
        worker = Thread(
            target=_governance_shadow_worker_loop,
            name="seedcore-governance-shadow-advisory",
            daemon=True,
        )
        worker.start()
        _GOVERNANCE_SHADOW_WORKER_STARTED = True


def _governance_shadow_worker_loop() -> None:
    shadow_queue = _get_governance_shadow_queue()
    while True:
        item = shadow_queue.get()
        try:
            _run_governance_shadow_advisory_job(item)
        except Exception as exc:  # pragma: no cover - final safety net for daemon loop
            logger.warning("Governance shadow advisory worker failed: %s", exc)
        finally:
            shadow_queue.task_done()


def _reset_governance_shadow_queue_for_tests() -> None:
    global _GOVERNANCE_SHADOW_QUEUE, _GOVERNANCE_SHADOW_WORKER_STARTED
    with _GOVERNANCE_SHADOW_QUEUE_LOCK:
        _GOVERNANCE_SHADOW_QUEUE = None
        _GOVERNANCE_SHADOW_WORKER_STARTED = False


def _enqueue_governance_shadow_advisory(
    *,
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> None:
    if not _governance_shadow_enabled():
        return

    try:
        item = _build_governance_shadow_advisory_item(request=request, response=response)
    except Exception as exc:
        _record_governance_shadow_event(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "status": "failed",
                "event_type": "governance_shadow_advisory",
                "request_id": request.request_id,
                "asset_ref": request.asset_context.asset_ref,
                "failure_reason": "feature_encoding_failed",
                "error": str(exc),
                "false_safe_advisory": False,
                "student_final_authority_usage": 0,
            }
        )
        return

    shadow_queue = _get_governance_shadow_queue()
    try:
        shadow_queue.put_nowait(item)
        _ensure_governance_shadow_worker()
    except queue.Full:
        _record_governance_shadow_event(
            {
                **item,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "status": "queue_full",
                "failure_reason": "queue_full",
                "false_safe_advisory": False,
                "student_final_authority_usage": 0,
            }
        )


def _build_governance_shadow_advisory_item(
    *,
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> dict[str, Any]:
    return {
        "event_type": "governance_shadow_advisory",
        "request_id": request.request_id,
        "asset_ref": request.asset_context.asset_ref,
        "advisory_url": _governance_shadow_advisory_url(),
        "features": _encode_governance_shadow_features(request=request, response=response),
        "pdp": {
            "disposition": str(response.decision.disposition or ""),
            "reason_code": str(response.decision.reason_code or ""),
            "trust_gaps": list(response.trust_gaps),
        },
    }


def _encode_governance_shadow_features(
    *,
    request: HotPathEvaluateRequest,
    response: HotPathEvaluateResponse,
) -> list[float]:
    action_parameters = (
        request.action_intent.action.parameters
        if isinstance(request.action_intent.action.parameters, Mapping)
        else {}
    )
    approval_context = (
        action_parameters.get("approval_context")
        if isinstance(action_parameters.get("approval_context"), Mapping)
        else {}
    )
    resource = request.action_intent.resource
    telemetry = request.telemetry_context
    governed_receipt = response.governed_receipt if isinstance(response.governed_receipt, Mapping) else {}
    freshness_seconds = float(telemetry.freshness_seconds or 0)
    max_age = telemetry.max_allowed_age_seconds
    distance_to_boundary = (
        float(max_age - telemetry.freshness_seconds)
        if max_age is not None and telemetry.freshness_seconds is not None
        else 0.0
    )
    declared_value = _coerce_float(
        action_parameters.get("declared_value_usd")
        or getattr(resource, "declared_value_usd", None)
        or 0.0
    )
    required_roles = approval_context.get("required_roles")
    requires_co_signature = bool(required_roles) or any(
        str(item.get("type") or "").lower() in {"co_signature", "cosignature"}
        for item in response.obligations
        if isinstance(item, Mapping)
    )
    has_policy_receipt = bool(
        governed_receipt.get("policy_receipt")
        or governed_receipt.get("policy_receipt_id")
        or response.decision.policy_snapshot_hash
    )
    has_transition_receipts = bool(
        governed_receipt.get("transition_receipt")
        or governed_receipt.get("transition_receipt_id")
        or governed_receipt.get("transition_receipt_ids")
    )
    has_asset_fingerprint = bool(
        governed_receipt.get("asset_fingerprint")
        or governed_receipt.get("asset_fingerprint_hash")
        or request.asset_context.asset_ref
    )
    signer_profile_known = bool(response.signer_provenance)
    return [
        freshness_seconds,
        _bool_float(bool(telemetry.current_coordinate_ref)),
        _bool_float(bool(request.signed_context_envelopes)),
        _bool_float(request.action_intent.resource.asset_id == request.asset_context.asset_ref),
        _bool_float(
            bool(
                request.action_intent.principal.actor_token
                or request.action_intent.principal.session_token
                or request.action_intent.principal.spiffe_id
                or request.action_intent.principal.dpop_jkt
            )
        ),
        _bool_float(
            bool(request.asset_context.current_zone)
            and request.asset_context.current_zone == request.action_intent.resource.target_zone
        ),
        _bool_float(bool(approval_context)),
        declared_value,
        _bool_float(requires_co_signature),
        float(len(response.trust_gaps)),
        distance_to_boundary,
        _bool_float(has_transition_receipts),
        _bool_float(has_policy_receipt),
        _bool_float(has_asset_fingerprint),
        _bool_float(signer_profile_known),
        float(len(telemetry.evidence_refs)),
        0.0,
    ]


def _run_governance_shadow_advisory_job(item: Mapping[str, Any]) -> None:
    base_event = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event_type": "governance_shadow_advisory",
        "request_id": str(item.get("request_id") or ""),
        "asset_ref": str(item.get("asset_ref") or ""),
        "pdp": dict(item.get("pdp") or {}),
        "features": list(item.get("features") or []),
    }
    try:
        prediction_payload = _post_governance_shadow_advisory(
            url=str(item.get("advisory_url") or _governance_shadow_advisory_url()),
            features=base_event["features"],
        )
        from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1

        prediction = GovernanceAdvisoryOutputV1(**prediction_payload)
        pdp_disposition = str(base_event["pdp"].get("disposition") or "").lower()
        false_safe = pdp_disposition in {"deny", "quarantine", "escalate"} and not prediction.abstain
        _record_governance_shadow_event(
            {
                **base_event,
                "status": "completed",
                "prediction": prediction.model_dump(mode="json"),
                "false_safe_advisory": false_safe,
                "student_final_authority_usage": prediction.student_final_authority_usage,
            }
        )
    except Exception as exc:
        _record_governance_shadow_event(
            {
                **base_event,
                "status": "failed",
                "failure_reason": "advisory_prediction_failed",
                "error": str(exc),
                "false_safe_advisory": False,
                "student_final_authority_usage": 0,
            }
        )


def _post_governance_shadow_advisory(*, url: str, features: Sequence[float]) -> dict[str, Any]:
    payload = json.dumps({"features": list(features)}, separators=(",", ":")).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=0.75) as response:
            body = response.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"governance advisory service unavailable: {exc}") from exc
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("governance advisory response must be a JSON object")
    return parsed


def _record_governance_shadow_event(event: Mapping[str, Any]) -> None:
    try:
        from seedcore.ops.governance_learning.shadow_parity_log import (
            get_governance_shadow_advisory_logger,
        )

        get_governance_shadow_advisory_logger().append(dict(event))
    except Exception as exc:
        logger.warning("Governance shadow advisory log write failed: %s", exc)


def _bool_float(value: bool) -> float:
    return 1.0 if bool(value) else 0.0


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
        publish_pdp_hot_path_policy_outcome_best_effort(request, response)
        _enqueue_governance_shadow_advisory(request=request, response=response)
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
        publish_pdp_hot_path_policy_outcome_best_effort(request, response)
        _enqueue_governance_shadow_advisory(request=request, response=response)
        return response

    context_freshness_response = _validate_context_freshness_bound(
        request,
        checks=checks,
        started=started,
    )
    if context_freshness_response is not None:
        _record_terminal_shadow_result(request=request, response=context_freshness_response)
        publish_pdp_hot_path_policy_outcome_best_effort(request, context_freshness_response)
        _enqueue_governance_shadow_advisory(request=request, response=context_freshness_response)
        return context_freshness_response

    signed_context_response = _validate_signed_context_envelopes(
        request,
        checks=checks,
        started=started,
    )
    if signed_context_response is not None:
        _record_terminal_shadow_result(request=request, response=signed_context_response)
        publish_pdp_hot_path_policy_outcome_best_effort(request, signed_context_response)
        _enqueue_governance_shadow_advisory(request=request, response=signed_context_response)
        return signed_context_response

    stage = _pdp_authz_graph_rollout_stage()
    runtime_status = _resolve_hot_path_runtime_status() if stage > 0 else {}
    compiled_authz_index = runtime_status.get("compiled_authz_index") if stage > 0 else None

    if stage > 0:
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
            publish_pdp_hot_path_policy_outcome_best_effort(request, response)
            _enqueue_governance_shadow_advisory(request=request, response=response)
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
            publish_pdp_hot_path_policy_outcome_best_effort(request, response)
            _enqueue_governance_shadow_advisory(request=request, response=response)
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
            publish_pdp_hot_path_policy_outcome_best_effort(request, response)
            _enqueue_governance_shadow_advisory(request=request, response=response)
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
    _ag = dict(decision.authz_graph or {})
    _gr = dict(decision.governed_receipt or {})
    apply_rct_triple_hash_fields(_ag, _gr, compiled_authz_index=compiled_authz_index)
    decision.authz_graph = _ag
    decision.governed_receipt = _gr

    if compiled_authz_index is not None:
        mismatch = (baseline_decision.allowed != decision.allowed) or (baseline_decision.disposition != decision.disposition)
        if stage in (1, 2):
            comparison_decision = decision
            decision = baseline_decision.model_copy(deep=True)
            if mismatch and stage == 2:
                decision.trust_alert = json.dumps({
                    "alert_level": "warning",
                    "code": "authz_graph_divergence",
                    "message": f"Divergence detected: baseline is '{baseline_decision.disposition}', compiled graph is '{comparison_decision.disposition}'."
                })
        elif stage == 3:
            is_critical = (request.action_intent.action.type == "TRANSFER_CUSTODY")
            if is_critical:
                decision = baseline_decision.model_copy(deep=True)

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
            trust_alert=decision.trust_alert,
        ),
        required_approvals=list(decision.required_approvals or []),
        trust_gaps=trust_gaps,
        obligations=obligations,
        checks=checks,
        execution_token=decision.execution_token if isinstance(decision.execution_token, ExecutionToken) else None,
        execution_preconditions=(
            decision.execution_token.execution_preconditions
            if isinstance(decision.execution_token, ExecutionToken)
            else None
        ),
        governed_receipt=dict(decision.governed_receipt or {}),
        signer_provenance=signer_provenance,
        request_schema_bundle=(
            dict(request.request_schema_bundle)
            if isinstance(request.request_schema_bundle, Mapping) and request.request_schema_bundle
            else None
        ),
        taxonomy_bundle=(
            dict(request.taxonomy_bundle)
            if isinstance(request.taxonomy_bundle, Mapping) and request.taxonomy_bundle
            else None
        ),
    )
    _HOT_PATH_SHADOW_STATS.record(
        latency_ms=response.latency_ms,
        parity=_shadow_parity_result(
            request=request,
            baseline=_baseline_for_parity_recording(baseline_decision, decision),
            candidate=decision,
        ),
    )
    publish_pdp_hot_path_policy_outcome_best_effort(request, response)
    _enqueue_governance_shadow_advisory(request=request, response=response)
    return response


def hot_path_shadow_status() -> dict[str, Any]:
    status = _HOT_PATH_SHADOW_STATS.snapshot()
    runtime_status = _resolve_hot_path_runtime_status()
    promotion = compute_hot_path_promotion_status()
    runtime_ready = _hot_path_runtime_ready(runtime_status)
    latency_slo_met = _latency_slo_met(status.get("latency_ms") if isinstance(status.get("latency_ms"), Mapping) else {})
    strict_promotion_eligible = _strict_promotion_eligible(
        status_snapshot=status,
        runtime_status=runtime_status,
        promotion=promotion,
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
    status["observability"] = _build_hot_path_observability(status)
    return status


def _prometheus_escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def hot_path_prometheus_text() -> str:
    """
    Prometheus text exposition for scrape targets (json_exporter alternative).

    Emits gauges/counters aligned with observability.gauges and alert_level.
    """
    s = hot_path_shadow_status()
    obs = s.get("observability") if isinstance(s.get("observability"), Mapping) else {}
    gauges = obs.get("gauges") if isinstance(obs.get("gauges"), Mapping) else {}
    role_raw = obs.get("deployment_role") if obs.get("deployment_role") else os.getenv(
        "SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE", "unset"
    )
    role = _prometheus_escape_label(str(role_raw))

    def alert_level_num() -> int:
        al = str(obs.get("alert_level") or "ok").strip().lower()
        if al == "critical":
            return 2
        if al == "warning":
            return 1
        return 0

    lines: list[str] = []

    def emit_gauge(name: str, help_text: str, value: float | int) -> None:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        lines.append(f'{name}{{deployment_role="{role}"}} {value}')

    emit_gauge(
        "seedcore_hot_path_alert_level",
        "Observability alert level (0=ok, 1=warning, 2=critical).",
        alert_level_num(),
    )
    emit_gauge(
        "seedcore_hot_path_rollback_triggered",
        "Whether auto-rollback is active (1=yes).",
        1 if bool(s.get("rollback_triggered")) else 0,
    )
    emit_gauge(
        "seedcore_hot_path_graph_freshness_ok",
        "Authz graph freshness check (1=ok).",
        1 if bool(s.get("graph_freshness_ok")) else 0,
    )
    emit_gauge(
        "seedcore_hot_path_authz_graph_ready",
        "Compiled authz index readiness (1=ready).",
        1 if bool(s.get("authz_graph_ready")) else 0,
    )
    emit_gauge(
        "seedcore_hot_path_latency_slo_met",
        "Latency percentiles within promotion SLO (1=yes).",
        1 if bool(s.get("latency_slo_met")) else 0,
    )
    emit_gauge(
        "seedcore_hot_path_runtime_ready",
        "Combined dependency readiness for strict promotion (1=yes).",
        1 if bool(s.get("runtime_ready")) else 0,
    )
    emit_gauge(
        "seedcore_hot_path_total_runs",
        "In-process hot-path evaluation count (reset on restart).",
        int(s.get("total") or 0),
    )
    emit_gauge(
        "seedcore_hot_path_parity_ok_total",
        "Cumulative parity-ok evaluations in-process.",
        int(s.get("parity_ok") or 0),
    )
    emit_gauge(
        "seedcore_hot_path_mismatched_total",
        "Cumulative parity mismatches in-process.",
        int(s.get("mismatched") or 0),
    )
    emit_gauge(
        "seedcore_hot_path_recent_mismatch_count",
        "Mismatches in the sliding promotion window.",
        int(gauges.get("recent_mismatch_count") or 0),
    )
    p99 = gauges.get("p99_ms")
    if p99 is not None:
        try:
            emit_gauge(
                "seedcore_hot_path_latency_p99_ms",
                "Reported p99 latency of hot-path evaluations (ms).",
                float(p99),
            )
        except (TypeError, ValueError):
            pass
    ga = s.get("graph_age_seconds")
    if ga is not None:
        try:
            emit_gauge(
                "seedcore_hot_path_graph_age_seconds",
                "Age of compiled authz graph in seconds.",
                float(ga),
            )
        except (TypeError, ValueError):
            pass
    return "\n".join(lines) + "\n"


def _pdp_authz_graph_rollout_stage() -> int:
    raw = os.getenv("SEEDCORE_PDP_AUTHZ_GRAPH_ROLLOUT_STAGE")
    if raw is not None:
        try:
            return max(0, min(4, int(raw)))
        except ValueError:
            return 4
    use_active_raw = os.getenv("SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH")
    if use_active_raw is not None:
        return 4 if str(use_active_raw).strip().lower() in {"1", "true", "yes", "on"} else 0
    return 4


def _resolve_compiled_authz_index() -> Any | None:
    if _pdp_authz_graph_rollout_stage() == 0:
        return None
    return _resolve_hot_path_runtime_status().get("compiled_authz_index")


def _resolve_hot_path_runtime_status() -> dict[str, Any]:
    manager = _resolve_pkg_manager()
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
