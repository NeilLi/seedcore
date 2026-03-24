#!/usr/bin/env python3
"""Verify the end-to-end product flow from policy to public replay surfaces."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from test_replay_router import _apply_transition_metadata, _build_audit_record, _make_client


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def main() -> int:
    results: list[CheckResult] = []

    record = _apply_transition_metadata(
        _build_audit_record(
            task_id="task-runtime-e2e",
            intent_id="intent-runtime-e2e",
            asset_id="asset-runtime-e2e",
        )
    )
    client = _make_client(record)

    replay = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "internal"})
    replay_body = replay.json()
    results.append(
        CheckResult(
            "product.policy_execution_evidence_replay",
            replay.status_code == 200
            and replay_body["policy_receipt"]["intent_id"] == "intent-runtime-e2e"
            and replay_body["evidence_bundle"]["policy_receipt_id"] == replay_body["policy_receipt"]["policy_receipt_id"]
            and replay_body["governed_receipt"]["decision_hash"] == "receipt-intent-runtime-e2e",
            {
                "status_code": replay.status_code,
                "policy_receipt_id": replay_body.get("policy_receipt", {}).get("policy_receipt_id"),
                "evidence_bundle_id": replay_body.get("evidence_bundle", {}).get("evidence_bundle_id"),
                "governed_receipt_hash": replay_body.get("governed_receipt", {}).get("decision_hash"),
            },
        )
    )

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    publish_body = publish.json()
    public_id = publish_body["public_id"]
    trust = client.get(f"/trust/{public_id}")
    trust_body = trust.json()
    results.append(
        CheckResult(
            "product.trust_page_works",
            trust.status_code == 200
            and trust_body["trust_page_id"] == public_id
            and trust_body["public_jsonld_ref"].endswith(f"/trust/{public_id}/jsonld")
            and trust_body["public_certificate_ref"].endswith(f"/trust/{public_id}/certificate"),
            {
                "status_code": trust.status_code,
                "subject_title": trust_body.get("subject_title"),
                "trust_page_id": trust_body.get("trust_page_id"),
            },
        )
    )

    verify_token = client.get(f"/verify/{public_id}")
    verify_audit = client.post("/verify", json={"audit_id": record["id"]})
    results.append(
        CheckResult(
            "product.public_verification_works",
            verify_token.status_code == 200
            and verify_token.json()["verified"] is True
            and verify_audit.status_code == 200
            and verify_audit.json()["verified"] is True,
            {
                "token_status": verify_token.status_code,
                "audit_status": verify_audit.status_code,
                "token_verified": verify_token.json().get("verified"),
                "audit_verified": verify_audit.json().get("verified"),
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nEnd-to-end product verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nEnd-to-end product verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
