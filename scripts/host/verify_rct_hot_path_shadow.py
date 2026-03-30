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
CANONICAL_CASES = (
    "allow_case",
    "deny_missing_approval",
    "quarantine_stale_telemetry",
    "escalate_break_glass",
)


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
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Restricted Custody Transfer hot-path shadow parity.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8002/api/v1",
        help="Runtime API base URL.",
    )
    args = parser.parse_args()

    evaluate_url = f"{args.base_url.rstrip('/')}/pdp/hot-path/evaluate?debug=true"
    status_url = f"{args.base_url.rstrip('/')}/pdp/hot-path/status"

    rows: list[dict[str, Any]] = []
    for case_name in CANONICAL_CASES:
        case_dir = FIXTURE_ROOT / case_name
        persisted_approval = _persist_authoritative_approval(args.base_url, case_dir)
        response = _post_json(
            evaluate_url,
            _build_request(case_dir, persisted_approval=persisted_approval),
        )
        rows.append(
            {
                "case": case_name,
                "disposition": response.get("decision", {}).get("disposition"),
                "reason_code": response.get("decision", {}).get("reason_code"),
                "latency_ms": response.get("latency_ms"),
            }
        )

    status = _get_json(status_url)

    print("Restricted Custody Transfer Hot-Path Shadow")
    print(f"mode: {status.get('mode')}")
    print(
        "parity: "
        f"{status.get('parity_ok', 0)}/{status.get('total', 0)} ok, "
        f"{status.get('mismatched', 0)} mismatched"
    )
    latency = status.get("latency_ms") or {}
    print(
        "latency_ms: "
        f"p50={latency.get('p50')} "
        f"p95={latency.get('p95')} "
        f"p99={latency.get('p99')}"
    )
    print("cases:")
    for row in rows:
        print(
            f"  - {row['case']}: disposition={row['disposition']} "
            f"reason={row['reason_code']} latency_ms={row['latency_ms']}"
        )

    recent = status.get("recent_results") or []
    mismatches = [item for item in recent if not item.get("parity_ok")]
    if mismatches:
        print("recent_mismatches:")
        for item in mismatches:
            print(
                f"  - {item.get('request_id')}: mismatches={','.join(item.get('mismatches') or [])}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
