#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = REPO_ROOT / "rust" / "fixtures" / "transfers"
DEFAULT_ARTIFACT_DIR = Path(".local-runtime/hot_path_shadow")
CANONICAL_CASES = (
    "allow_case",
    "deny_missing_approval",
    "quarantine_stale_telemetry",
    "escalate_break_glass",
)
EXPECTED_DISPOSITIONS = {
    "allow_case": "allow",
    "deny_missing_approval": "deny",
    "quarantine_stale_telemetry": "quarantine",
    "escalate_break_glass": "escalate",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=encoded,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_json(url: str) -> dict[str, Any]:
    with request.urlopen(url) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _resolve_active_snapshot(base_url: str) -> str | None:
    try:
        status = _get_json(f"{base_url.rstrip('/')}/pkg/status")
    except Exception:
        return None
    active_version = str(status.get("active_version") or "").strip()
    if active_version:
        return active_version
    version = str(status.get("version") or "").strip()
    return version or None


def _resolve_active_contract_bundles(base_url: str) -> dict[str, Any]:
    try:
        status = _get_json(f"{base_url.rstrip('/')}/pkg/status")
    except Exception:
        return {}
    bundles = status.get("active_contract_artifacts")
    return bundles if isinstance(bundles, dict) else {}


def _build_break_glass_token(
    *,
    secret: str,
    subject: str,
    issued_at: datetime,
    expires_at: datetime,
    require_reason: bool = True,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    claims: dict[str, Any] = {
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "require_reason": require_reason,
    }
    if isinstance(extra_claims, dict):
        claims.update(extra_claims)
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signing_input = f"seedcore_break_glass_v1.{payload}".encode("utf-8")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"seedcore_break_glass_v1.{payload}.{signature}"


def _normalize_binding_hash(value: Any) -> str | None:
    if isinstance(value, dict):
        algorithm = str(value.get("algorithm") or "").strip()
        digest = str(value.get("value") or "").strip()
        if algorithm and digest:
            return f"{algorithm}:{digest}"
        return None
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _required_roles(approval_envelope: dict[str, Any]) -> list[str]:
    roles: list[str] = []
    for item in approval_envelope.get("required_approvals") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _approved_by(approval_envelope: dict[str, Any]) -> list[str]:
    principals: list[str] = []
    for item in approval_envelope.get("required_approvals") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().upper() != "APPROVED":
            continue
        principal_ref = str(item.get("principal_ref") or "").strip()
        if principal_ref and principal_ref not in principals:
            principals.append(principal_ref)
    return principals


def _persist_authoritative_approval(base_url: str, case_dir: Path) -> dict[str, Any]:
    create_url = f"{base_url.rstrip('/')}/transfer-approvals"
    approval_envelope = _read_json(case_dir / "input.approval_envelope.json")
    return _post_json(create_url, {"envelope": approval_envelope})


def _build_request(
    case_dir: Path,
    *,
    persisted_approval: dict[str, Any],
    active_contract_bundles: dict[str, Any] | None = None,
    request_id_suffix: str | None = None,
) -> dict[str, Any]:
    action_intent_input = _read_json(case_dir / "input.action_intent.json")
    asset_state = _read_json(case_dir / "input.asset_state.json")
    telemetry = _read_json(case_dir / "input.telemetry_summary.json")
    approval_envelope = (
        dict(persisted_approval.get("envelope"))
        if isinstance(persisted_approval.get("envelope"), dict)
        else _read_json(case_dir / "input.approval_envelope.json")
    )
    request_id = f"shadow:{case_dir.name}"
    if request_id_suffix:
        request_id = f"{request_id}:{request_id_suffix.strip()}"
    issued_at = str(approval_envelope.get("created_at") or datetime.now(timezone.utc).isoformat())
    expires_at = str(approval_envelope.get("expires_at") or issued_at)
    requested_at = issued_at
    approval_binding_hash = (
        persisted_approval.get("approval_binding_hash")
        or _normalize_binding_hash(approval_envelope.get("approval_binding_hash"))
    )
    approval_envelope_id = (
        persisted_approval.get("approval_envelope_id")
        or approval_envelope.get("approval_envelope_id")
    )
    approval_version = (
        persisted_approval.get("version")
        or approval_envelope.get("version")
    )
    transfer_context = (
        dict(approval_envelope.get("transfer_context"))
        if isinstance(approval_envelope.get("transfer_context"), dict)
        else {}
    )
    telemetry_observed_at = str(telemetry.get("observed_at") or issued_at)
    freshness_seconds = telemetry.get("freshness_seconds")
    if freshness_seconds is None:
        freshness_seconds = 301 if bool(telemetry.get("stale")) else 5
    max_allowed_age_seconds = telemetry.get("max_allowed_age_seconds")
    if max_allowed_age_seconds is None:
        max_allowed_age_seconds = 300
    parameters: dict[str, Any] = {
        "endpoint_id": action_intent_input.get("endpoint_id"),
        "approval_context": {
            "approval_envelope_id": approval_envelope_id,
            "approval_envelope_version": approval_version,
            "observed_version": approval_version,
            "approval_binding_hash": approval_binding_hash,
            "required_roles": _required_roles(approval_envelope),
            "approved_by": _approved_by(approval_envelope),
        },
    }
    break_glass_path = case_dir / "input.break_glass.json"
    environment = {"origin_network": "network:warehouse-core"}
    if break_glass_path.exists():
        break_glass = _read_json(break_glass_path)
        break_glass_secret = os.getenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", "break-glass-secret")
        issued_dt = datetime.fromisoformat(issued_at.replace("Z", "+00:00"))
        expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        environment["break_glass_reason"] = str(break_glass.get("reason") or "urgent_release")
        environment["break_glass_token"] = _build_break_glass_token(
            secret=break_glass_secret,
            subject=str(action_intent_input.get("principal_agent_id") or "agent:custody_runtime_01"),
            issued_at=issued_dt,
            expires_at=expires_dt,
            extra_claims={"reason_code": str(break_glass.get("reason") or "urgent_release")},
        )
    return {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": request_id,
        "requested_at": requested_at,
        "policy_snapshot_ref": str(
            approval_envelope.get("policy_snapshot_ref")
            or approval_envelope.get("policy_snapshot")
            or "snapshot:runtime"
        ),
        "action_intent": {
            "intent_id": str(action_intent_input.get("action_intent_ref") or request_id),
            "timestamp": issued_at,
            "valid_until": expires_at,
            "principal": {
                "agent_id": str(action_intent_input.get("principal_agent_id") or "agent:custody_runtime_01"),
                "role_profile": "TRANSFER_COORDINATOR",
                "session_token": f"session:{request_id}",
            },
            "action": {
                "type": str(action_intent_input.get("action_type") or "TRANSFER_CUSTODY"),
                "parameters": parameters,
                "security_contract": {
                    "hash": f"fixture-contract:{case_dir.name}",
                    "version": str(
                        approval_envelope.get("policy_snapshot_ref")
                        or approval_envelope.get("policy_snapshot")
                        or "snapshot:runtime"
                    ),
                },
            },
            "resource": {
                "asset_id": str(approval_envelope.get("asset_ref") or asset_state.get("asset_ref")),
                "resource_uri": (
                    f"seedcore://zones/{str(transfer_context.get('to_zone') or 'handoff_bay_3')}/"
                    f"assets/{str(approval_envelope.get('asset_ref') or asset_state.get('asset_ref'))}"
                ),
                "target_zone": str(transfer_context.get("to_zone") or "handoff_bay_3"),
                "provenance_hash": f"fixture-provenance:{case_dir.name}",
                "source_registration_id": action_intent_input.get("source_registration_id"),
                "registration_decision_id": action_intent_input.get("registration_decision_id"),
                "lot_id": approval_envelope.get("lot_id"),
                "category_envelope": {
                    "transfer_context": {
                        "from_zone": transfer_context.get("from_zone"),
                        "to_zone": transfer_context.get("to_zone"),
                        "facility_ref": transfer_context.get("facility_ref"),
                        "custody_point_ref": transfer_context.get("custody_point_ref"),
                        "expected_current_custodian": approval_envelope.get("from_custodian_ref"),
                        "next_custodian": approval_envelope.get("to_custodian_ref"),
                    }
                },
            },
            "environment": environment,
        },
        "asset_context": {
            "asset_ref": asset_state.get("asset_ref") or approval_envelope.get("asset_ref"),
            "current_custodian_ref": asset_state.get("current_custodian_ref"),
            "current_zone": asset_state.get("current_zone") or asset_state.get("current_zone_ref"),
            "source_registration_status": (
                asset_state.get("source_registration_status")
                or ("APPROVED" if (asset_state.get("approved_registration_refs") or []) else "PENDING")
            ),
            "registration_decision_ref": (
                asset_state.get("registration_decision_ref")
                or action_intent_input.get("registration_decision_id")
            ),
        },
        "telemetry_context": {
            "observed_at": telemetry_observed_at,
            "freshness_seconds": freshness_seconds,
            "max_allowed_age_seconds": max_allowed_age_seconds,
            "evidence_refs": asset_state.get("evidence_refs") or telemetry.get("evidence_refs") or [],
        },
        "request_schema_bundle": (
            dict(active_contract_bundles.get("request_schema_bundle"))
            if isinstance(active_contract_bundles, dict)
            and isinstance(active_contract_bundles.get("request_schema_bundle"), dict)
            else None
        ),
        "taxonomy_bundle": (
            dict(active_contract_bundles.get("taxonomy_bundle"))
            if isinstance(active_contract_bundles, dict)
            and isinstance(active_contract_bundles.get("taxonomy_bundle"), dict)
            else None
        ),
    }


def run_verification(
    *,
    base_url: str,
    artifact_root: Path | None = DEFAULT_ARTIFACT_DIR,
    only_cases: tuple[str, ...] | None = None,
    request_id_suffix: str | None = None,
) -> dict[str, Any]:
    evaluate_url = f"{base_url.rstrip('/')}/pdp/hot-path/evaluate?debug=true"
    status_url = f"{base_url.rstrip('/')}/pdp/hot-path/status"
    active_snapshot = _resolve_active_snapshot(base_url)
    status_before = _get_json(status_url)
    active_contract_bundles = _resolve_active_contract_bundles(base_url)
    before_total = int(status_before.get("total") or 0)
    before_parity_ok = int(status_before.get("parity_ok") or 0)
    before_mismatched = int(status_before.get("mismatched") or 0)

    rows: list[dict[str, Any]] = []
    case_sequence = only_cases if only_cases else CANONICAL_CASES
    for case_name in case_sequence:
        case_dir = FIXTURE_ROOT / case_name
        persisted_approval = _persist_authoritative_approval(base_url, case_dir)
        payload = _build_request(
            case_dir,
            persisted_approval=persisted_approval,
            active_contract_bundles=active_contract_bundles,
            request_id_suffix=request_id_suffix,
        )
        if active_snapshot:
            payload["policy_snapshot_ref"] = active_snapshot
            payload["action_intent"]["action"]["security_contract"]["version"] = active_snapshot
        response = _post_json(evaluate_url, payload)
        rows.append(
            {
                "case": case_name,
                "expected_disposition": EXPECTED_DISPOSITIONS.get(case_name),
                "disposition": response.get("decision", {}).get("disposition"),
                "reason_code": response.get("decision", {}).get("reason_code"),
                "latency_ms": response.get("latency_ms"),
            }
        )

    status = _get_json(status_url)
    delta_total = max(0, int(status.get("total") or 0) - before_total)
    delta_parity_ok = max(0, int(status.get("parity_ok") or 0) - before_parity_ok)
    delta_mismatched = max(0, int(status.get("mismatched") or 0) - before_mismatched)
    disposition_mismatches = [
        row["case"]
        for row in rows
        if row.get("disposition") != EXPECTED_DISPOSITIONS.get(row.get("case"))
    ]
    recent = status.get("recent_results") or []
    recent_mismatches = [item for item in recent if not item.get("parity_ok")]
    passed = status.get("mode") == "shadow" and delta_mismatched == 0 and not disposition_mismatches

    artifact_path: Path | None = None
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "mode": status.get("mode"),
        "active_snapshot": active_snapshot or "unresolved",
        "pass": passed,
        "run_total": delta_total,
        "run_parity_ok": delta_parity_ok,
        "run_mismatched": delta_mismatched,
        "total": int(status.get("total") or 0),
        "parity_ok": int(status.get("parity_ok") or 0),
        "mismatched": int(status.get("mismatched") or 0),
        "latency_ms": status.get("latency_ms") or {},
        "cases": rows,
        "disposition_mismatches": disposition_mismatches,
        "recent_mismatches": recent_mismatches,
        "artifact_path": None,
    }

    if artifact_root is not None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_path = artifact_root / f"rct_hot_path_shadow_{timestamp}.json"
        artifact_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        summary["artifact_path"] = str(artifact_path)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Restricted Custody Transfer hot-path shadow parity.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8002/api/v1",
        help="Runtime API base URL.",
    )
    parser.add_argument(
        "--only",
        dest="only_cases",
        default="",
        help="Comma-separated subset of canonical cases (e.g. allow_case).",
    )
    parser.add_argument(
        "--request-id-suffix",
        default="",
        help="Append to shadow request_id for deduplication across repeated runs.",
    )
    args = parser.parse_args()

    only_tuple: tuple[str, ...] | None = None
    if str(args.only_cases or "").strip():
        only_tuple = tuple(c.strip() for c in str(args.only_cases).split(",") if c.strip())
    suffix = str(args.request_id_suffix or "").strip() or None

    summary = run_verification(
        base_url=args.base_url,
        artifact_root=DEFAULT_ARTIFACT_DIR,
        only_cases=only_tuple,
        request_id_suffix=suffix,
    )

    print("Restricted Custody Transfer Hot-Path Shadow")
    print(f"mode: {summary.get('mode')}")
    print(f"active_snapshot: {summary.get('active_snapshot')}")
    print(
        "run_parity: "
        f"{summary.get('run_parity_ok')}/{summary.get('run_total')} ok, "
        f"{summary.get('run_mismatched')} mismatched"
    )
    print(
        "parity: "
        f"{summary.get('parity_ok', 0)}/{summary.get('total', 0)} ok, "
        f"{summary.get('mismatched', 0)} mismatched"
    )
    latency = summary.get("latency_ms") or {}
    print(
        "latency_ms: "
        f"p50={latency.get('p50')} "
        f"p95={latency.get('p95')} "
        f"p99={latency.get('p99')}"
    )
    print("cases:")
    for row in summary.get("cases") or []:
        print(
            f"  - {row['case']}: disposition={row['disposition']} "
            f"reason={row['reason_code']} latency_ms={row['latency_ms']}"
        )
    print(f"artifact: {summary.get('artifact_path')}")

    disposition_mismatches = list(summary.get("disposition_mismatches") or [])
    if disposition_mismatches:
        print(f"disposition_mismatches: {','.join(disposition_mismatches)}")

    mismatches = summary.get("recent_mismatches") or []
    if mismatches:
        print("recent_mismatches:")
        for item in mismatches:
            print(
                f"  - {item.get('request_id')}: mismatches={','.join(item.get('mismatches') or [])}"
            )
    return 0 if summary.get("pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
