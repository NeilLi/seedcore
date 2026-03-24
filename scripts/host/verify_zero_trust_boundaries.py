#!/usr/bin/env python3
"""Verify zero-trust execution, replay, and HAL boundary contracts."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from seedcore.hal.custody.forensic_sealer import ForensicSealer
from test_replay_router import _build_audit_record, _make_client


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _api_url(base_env: str, default: str, path: str) -> str:
    base = os.getenv(base_env, default).rstrip("/")
    return f"{base}{path}"


def _sign_token_payload(payload: dict[str, object]) -> str:
    token_base = {
        "token_id": payload["token_id"],
        "intent_id": payload["intent_id"],
        "issued_at": payload["issued_at"],
        "valid_until": payload["valid_until"],
        "contract_version": payload["contract_version"],
        "constraints": payload["constraints"],
    }
    from seedcore.hal.service import main as hal_main

    return hal_main._expected_execution_token_signature(token_base)  # noqa: SLF001 - intentional verifier


def _build_token(
    *,
    token_id: str,
    endpoint_id: str | None = None,
    target_zone: str | None = None,
    ttl_seconds: int = 5,
) -> dict[str, object]:
    issued_at = datetime.now(timezone.utc)
    constraints: dict[str, str] = {}
    if endpoint_id is not None:
        constraints["endpoint_id"] = endpoint_id
    if target_zone is not None:
        constraints["target_zone"] = target_zone
    payload: dict[str, object] = {
        "token_id": token_id,
        "intent_id": "intent-zero-trust-runtime",
        "issued_at": issued_at.isoformat(),
        "valid_until": (issued_at + timedelta(seconds=ttl_seconds)).isoformat(),
        "contract_version": "snapshot:test",
        "constraints": constraints,
    }
    payload["signature"] = _sign_token_payload(payload)
    return payload


def main() -> int:
    results: list[CheckResult] = []

    missing_token = requests.post(
        _api_url("SEEDCORE_HAL_URL", "http://127.0.0.1:8003", "/actuate"),
        json={"behavior_name": "move_forward", "behavior_params": {"distance": 1}},
        timeout=5,
    )
    results.append(
        CheckResult(
            "boundary.no_execution_without_authorization",
            missing_token.status_code == 403 and "invalid ExecutionToken" in json.dumps(missing_token.json()),
            {"status_code": missing_token.status_code, "body": missing_token.json()},
        )
    )

    forged = _build_token(token_id="tok-zero-trust-forged")
    forged["signature"] = "forged-signature"
    forged_response = requests.post(
        _api_url("SEEDCORE_HAL_URL", "http://127.0.0.1:8003", "/actuate"),
        json={
            "behavior_name": "move_forward",
            "behavior_params": {"distance": 1},
            "execution_token": forged,
        },
        timeout=5,
    )
    results.append(
        CheckResult(
            "boundary.no_policy_bypass_forged_token",
            forged_response.status_code == 403 and "forged ExecutionToken" in json.dumps(forged_response.json()),
            {"status_code": forged_response.status_code, "body": forged_response.json()},
        )
    )

    mismatch = _build_token(
        token_id="tok-zero-trust-mismatch",
        endpoint_id="robot_sim://wrong-endpoint",
    )
    mismatch_response = requests.post(
        _api_url("SEEDCORE_HAL_URL", "http://127.0.0.1:8003", "/actuate"),
        json={
            "behavior_name": "move_forward",
            "behavior_params": {"distance": 1},
            "execution_token": mismatch,
        },
        timeout=5,
    )
    results.append(
        CheckResult(
            "boundary.no_policy_bypass_endpoint_mismatch",
            mismatch_response.status_code == 403 and "endpoint mismatch" in json.dumps(mismatch_response.json()),
            {"status_code": mismatch_response.status_code, "body": mismatch_response.json()},
        )
    )

    record = _build_audit_record(
        task_id="task-zero-trust-runtime-public",
        intent_id="intent-zero-trust-runtime-public",
        asset_id="asset-1",
    )
    client = _make_client(record)
    public_response = client.get(
        "/replay/artifacts",
        params={"audit_id": record["id"], "projection": "public"},
    )
    public_body = public_response.json()
    results.append(
        CheckResult(
            "boundary.no_evidence_leakage_public_projection",
            public_response.status_code == 200
            and "public_artifacts" in public_body
            and "evidence_bundle" not in public_body
            and "policy_receipt" not in public_body
            and "transition_receipts" not in public_body,
            {
                "status_code": public_response.status_code,
                "keys": sorted(public_body.keys()),
            },
        )
    )

    sealer_error = None
    try:
        os.environ.pop("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64", None)
        os.environ.pop("SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_PEM", None)
        ForensicSealer(device_identity="robot_sim://unit-zero-trust").seal_custody_event_pilot(
            event_id="urn:seedcore:event:runtime-zero-trust",
            platform_state="allow",
            policy_hash="policy-receipt-runtime-zero-trust",
            auth_token="token-runtime-zero-trust",
            from_zone="zone-a",
            to_zone="zone-b",
            transition_receipt={"transition_receipt_id": "tr-runtime-zero-trust", "actuator_result_hash": "trajectory-hash"},
            actuator_telemetry={},
            media_hash_references=[],
            trajectory_hash=None,
            environmental_data={"temperatureC": 22.0},
        )
    except Exception as exc:  # noqa: BLE001 - explicit contract probe
        sealer_error = str(exc)
    results.append(
        CheckResult(
            "boundary.hal_sealer_restrictions_hold",
            isinstance(sealer_error, str) and "hal_capture requires Ed25519 signing" in sealer_error,
            {"error": sealer_error},
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nZero-trust boundary verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nZero-trust boundary verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
