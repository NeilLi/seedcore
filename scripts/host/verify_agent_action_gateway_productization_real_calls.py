#!/usr/bin/env python3
"""Run real local HTTP verification for Agent Action Gateway productization."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from seedcore.adapters.rct_agent_action_gateway_reference_adapter import (  # noqa: E402
    build_rct_agent_action_evaluate_request_v1,
    build_rct_gateway_correlation_from_evaluate_response,
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _build_payload(request_id: str, idempotency_key: str, policy_snapshot_ref: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    requested_at = now.isoformat().replace("+00:00", "Z")
    workflow_valid_until = (now + timedelta(seconds=90)).isoformat().replace("+00:00", "Z")
    observed_at = (now - timedelta(seconds=2)).isoformat().replace("+00:00", "Z")

    return build_rct_agent_action_evaluate_request_v1(
        request_id=request_id,
        idempotency_key=idempotency_key,
        requested_at=requested_at,
        policy_snapshot_ref=policy_snapshot_ref,
        principal={
            "agent_id": "agent:custody_runtime_01",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "session-local-abc",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
            "organization_ref": "org:warehouse-north",
            "hardware_fingerprint": {
                "fingerprint_id": "fp:jetson-orin-01",
                "node_id": "node:jetson-orin-01",
                "public_key_fingerprint": "sha256:fingerprint-key",
                "attestation_type": "tpm",
                "key_ref": "tpm2:jetson-orin-01-ak",
            },
        },
        workflow_valid_until=workflow_valid_until,
        asset_base={
            "asset_id": "asset:lot-8841",
            "lot_id": "lot-8841",
            "from_custodian_ref": "principal:facility_mgr_001",
            "to_custodian_ref": "principal:outbound_mgr_002",
            "from_zone": "vault_a",
            "to_zone": "handoff_bay_3",
            "provenance_hash": "sha256:asset-provenance",
        },
        approval_envelope_id="approval-transfer-001",
        approval_expected_envelope_version="23",
        authority_scope_base={
            "scope_id": "scope:rct-2026-local-0001",
            "asset_ref": "asset:lot-8841",
            "expected_from_zone": "vault_a",
            "expected_to_zone": "handoff_bay_3",
            "expected_coordinate_ref": "gazebo://warehouse/shelf/A3",
        },
        telemetry={
            "observed_at": observed_at,
            "freshness_seconds": 2,
            "max_allowed_age_seconds": 300,
            "current_zone": "vault_a",
            "current_coordinate_ref": "gazebo://warehouse/shelf/A3",
            "evidence_refs": ["ev:cam-1", "ev:seal-sensor-7"],
        },
        security_contract={"hash": "sha256:contract-hash", "version": "rules@8.0.0"},
        shopify_sandbox_transaction={
            "product_ref": "shopify:gid://shopify/Product/1234567890",
            "quote_ref": "shopify:quote:tea-set-2026-04-03-local",
            "declared_value_usd": 1500,
            "economic_hash": "sha256:shopify-order-local",
        },
        options={"debug": False},
    )


def _json_or_text(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"non_json": resp.text[:500]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Agent Action Gateway productization via real local calls.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8002", help="SeedCore API base URL")
    parser.add_argument(
        "--policy-snapshot-ref",
        default="runtime-baseline-v1.0.0-1774251324625-local-1774260434866",
        help="Policy snapshot ref to send in gateway payload",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--strict-replay-ready",
        action="store_true",
        help="Fail if replay record is not yet materialized (404 pending is treated as failure).",
    )
    args = parser.parse_args()

    request_id = f"req-local-{uuid.uuid4().hex[:12]}"
    idempotency_key = f"idem-local-{uuid.uuid4().hex[:12]}"
    payload = _build_payload(request_id, idempotency_key, args.policy_snapshot_ref)

    checks: list[CheckResult] = []
    summary: dict[str, Any] = {
        "request_id": request_id,
        "idempotency_key": idempotency_key,
        "base_url": args.base_url,
    }

    with httpx.Client(timeout=args.timeout) as client:
        health_resp = client.get(f"{args.base_url}/health")
        hal_resp = client.get("http://127.0.0.1:8003/status")
        checks.append(
            CheckResult(
                "runtime.health",
                health_resp.status_code == 200,
                {"status_code": health_resp.status_code, "body": _json_or_text(health_resp)},
            )
        )
        checks.append(
            CheckResult(
                "hal.status",
                hal_resp.status_code == 200,
                {"status_code": hal_resp.status_code, "body": _json_or_text(hal_resp)},
            )
        )

        evaluate_resp = client.post(
            f"{args.base_url}/api/v1/agent-actions/evaluate",
            params={"debug": "true", "no_execute": "true"},
            json=payload,
        )
        evaluate_body = _json_or_text(evaluate_resp)
        summary["evaluate"] = {"status_code": evaluate_resp.status_code, "body": evaluate_body}
        checks.append(
            CheckResult(
                "gateway.evaluate_status",
                evaluate_resp.status_code == 200 and isinstance(evaluate_body, dict),
                {"status_code": evaluate_resp.status_code},
            )
        )

        if not isinstance(evaluate_body, dict):
            print(json.dumps({"checks": [c.__dict__ for c in checks], "summary": summary}, indent=2))
            return 1

        idempotent_resp = client.post(
            f"{args.base_url}/api/v1/agent-actions/evaluate",
            params={"debug": "true", "no_execute": "true"},
            json=payload,
        )
        idempotent_body = _json_or_text(idempotent_resp)
        summary["evaluate_idempotent"] = {"status_code": idempotent_resp.status_code, "body": idempotent_body}
        checks.append(
            CheckResult(
                "gateway.idempotency",
                idempotent_resp.status_code == 200
                and isinstance(idempotent_body, dict)
                and idempotent_body.get("request_id") == request_id,
                {"status_code": idempotent_resp.status_code},
            )
        )

        correlation = build_rct_gateway_correlation_from_evaluate_response(
            request_id=request_id,
            gateway_evaluate_response=evaluate_body,
        )
        summary["correlation"] = correlation
        try:
            uuid.UUID(str(correlation.get("audit_id") or ""))
            audit_id_is_uuid = True
        except ValueError:
            audit_id_is_uuid = False
        checks.append(
            CheckResult(
                "correlation.audit_id_uuid_safe",
                audit_id_is_uuid,
                {
                    "audit_id": correlation.get("audit_id"),
                    "audit_id_source": correlation.get("audit_id_source"),
                },
            )
        )

        request_record_resp = client.get(f"{args.base_url}/api/v1/agent-actions/requests/{request_id}")
        summary["request_record"] = {
            "status_code": request_record_resp.status_code,
            "body": _json_or_text(request_record_resp),
        }
        checks.append(
            CheckResult(
                "gateway.request_record_fetch",
                request_record_resp.status_code == 200,
                {"status_code": request_record_resp.status_code},
            )
        )

        replay_intent_resp = client.get(
            f"{args.base_url}/api/v1/replay",
            params={"intent_id": correlation["intent_id"], "projection": "public"},
        )
        replay_audit_resp = client.get(
            f"{args.base_url}/api/v1/replay",
            params={"audit_id": correlation["audit_id"], "projection": "public"},
        )
        replay_intent_body = _json_or_text(replay_intent_resp)
        replay_audit_body = _json_or_text(replay_audit_resp)
        summary["replay"] = {
            "intent": {"status_code": replay_intent_resp.status_code, "body": replay_intent_body},
            "audit": {"status_code": replay_audit_resp.status_code, "body": replay_audit_body},
        }

        checks.append(
            CheckResult(
                "replay.audit_lookup_shape",
                replay_audit_resp.status_code != 422,
                {"status_code": replay_audit_resp.status_code, "detail": replay_audit_body},
            )
        )

        replay_ready = replay_intent_resp.status_code == 200 or replay_audit_resp.status_code == 200
        replay_pending = replay_intent_resp.status_code == 404 and replay_audit_resp.status_code == 404
        if args.strict_replay_ready:
            replay_ok = replay_ready
        else:
            replay_ok = replay_ready or replay_pending
        checks.append(
            CheckResult(
                "replay.materialization_state",
                replay_ok,
                {
                    "strict_replay_ready": args.strict_replay_ready,
                    "replay_ready": replay_ready,
                    "replay_pending": replay_pending,
                    "intent_status": replay_intent_resp.status_code,
                    "audit_status": replay_audit_resp.status_code,
                },
            )
        )

    result = {"checks": [c.__dict__ for c in checks], "summary": summary}
    print(json.dumps(result, indent=2))
    failed = [c for c in checks if not c.ok]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
