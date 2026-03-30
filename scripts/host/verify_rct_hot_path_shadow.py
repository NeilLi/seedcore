#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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


def _build_request(case_dir: Path) -> dict[str, Any]:
    action_intent = _read_json(case_dir / "input.action_intent.json")
    asset_state = _read_json(case_dir / "input.asset_state.json")
    telemetry = _read_json(case_dir / "input.telemetry_summary.json")
    requested_at = datetime.now(timezone.utc).isoformat()
    freshness_seconds = telemetry.get("freshness_seconds")
    if freshness_seconds is None and telemetry.get("observed_at"):
        observed_at = datetime.fromisoformat(str(telemetry["observed_at"]).replace("Z", "+00:00"))
        freshness_seconds = max(0, int((datetime.now(timezone.utc) - observed_at).total_seconds()))
    return {
        "contract_version": "pdp.hot_path.asset_transfer.v1",
        "request_id": f"shadow:{case_dir.name}",
        "requested_at": requested_at,
        "policy_snapshot_ref": str(
            action_intent.get("action", {})
            .get("security_contract", {})
            .get("version", "snapshot:runtime")
        ),
        "action_intent": action_intent,
        "asset_context": {
            "asset_ref": asset_state.get("asset_ref") or action_intent.get("resource", {}).get("asset_id"),
            "current_custodian_ref": asset_state.get("current_custodian_ref"),
            "current_zone": asset_state.get("current_zone") or asset_state.get("current_zone_ref"),
            "source_registration_status": asset_state.get("source_registration_status") or "APPROVED",
            "registration_decision_ref": asset_state.get("registration_decision_ref"),
        },
        "telemetry_context": {
            "observed_at": telemetry.get("observed_at") or requested_at,
            "freshness_seconds": freshness_seconds,
            "max_allowed_age_seconds": telemetry.get("max_allowed_age_seconds", 300),
            "evidence_refs": telemetry.get("evidence_refs") or [],
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
        response = _post_json(evaluate_url, _build_request(case_dir))
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
