#!/usr/bin/env python3
"""Verify core evidence and replay boundary contracts against the local SeedCore setup."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

from seedcore.coordinator.core.governance import build_governance_context
from seedcore.models.evidence_bundle import EvidenceBundle, PolicyReceipt
from seedcore.models.task_payload import TaskPayload
from seedcore.ops.evidence.builder import attach_evidence_bundle, build_policy_receipt_artifact
from test_replay_router import _build_audit_record, _make_client


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _build_governed_task(*, intent_id: str) -> dict[str, Any]:
    issued_at = datetime.now(timezone.utc)
    valid_until = issued_at + timedelta(seconds=120)
    return {
        "task_id": f"task-{intent_id}",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": intent_id,
                    "timestamp": issued_at.isoformat(),
                    "valid_until": valid_until.isoformat(),
                    "principal": {
                        "agent_id": "agent-1",
                        "role_profile": "ROBOT_OPERATOR",
                        "session_token": "sess-1",
                    },
                    "action": {
                        "type": "MOVE",
                        "parameters": {},
                        "security_contract": {
                            "hash": "h-evidence-contract",
                            "version": "runtime-baseline-v1.0.0",
                        },
                    },
                    "resource": {
                        "asset_id": "asset-1",
                        "resource_uri": "seedcore://zones/vault-a/assets/asset-1",
                        "target_zone": "vault-a",
                        "provenance_hash": "prov-evidence-contract",
                    },
                }
            },
        },
    }


def main() -> int:
    results: list[CheckResult] = []

    payload = TaskPayload.from_db(
        {
            "task_id": "task-runtime-payload-shape",
            "type": "action",
            "params": {"interaction": {"assigned_agent_id": "agent-1"}},
        }
    ).model_dump(mode="json")
    task_payload_is_evidence = True
    payload_error = None
    try:
        EvidenceBundle(**payload)
    except Exception as exc:
        task_payload_is_evidence = False
        payload_error = type(exc).__name__
    results.append(
        CheckResult(
            "contract.task_payload_not_evidence_bundle",
            not task_payload_is_evidence,
            {"validation_error": payload_error},
        )
    )

    task_payload_is_receipt = True
    receipt_error = None
    try:
        PolicyReceipt(**payload)
    except Exception as exc:
        task_payload_is_receipt = False
        receipt_error = type(exc).__name__
    results.append(
        CheckResult(
            "contract.task_payload_not_policy_receipt",
            not task_payload_is_receipt,
            {"validation_error": receipt_error},
        )
    )

    governed_task = _build_governed_task(intent_id="intent-runtime-evidence")
    governance_ctx = build_governance_context(governed_task)
    results.append(
        CheckResult(
            "contract.policy_receipt_pdp_generated",
            isinstance(governance_ctx.get("policy_receipt"), dict)
            and bool(governance_ctx["policy_receipt"].get("policy_receipt_id"))
            and "evidence_bundle" not in governance_ctx,
            {
                "policy_receipt_id": governance_ctx.get("policy_receipt", {}).get("policy_receipt_id"),
                "has_evidence_bundle": "evidence_bundle" in governance_ctx,
            },
        )
    )

    injected_task = _build_governed_task(intent_id="intent-runtime-injected-receipt")
    injected_task["params"]["governance"]["policy_decision"] = {
        "allowed": True,
        "reason": "zone_match",
        "policy_snapshot": "runtime-baseline-v1.0.0",
    }
    injected_task["params"]["governance"]["execution_token"] = {"token_id": "token-runtime-injected-receipt"}
    injected_task["params"]["governance"]["policy_receipt"] = {
        "policy_receipt_id": "caller-injected",
        "policy_decision_id": "caller-injected",
        "task_id": "caller-task",
        "intent_id": "caller-intent",
        "timestamp": "2026-01-01T00:00:00Z",
        "signer_metadata": {
            "signer_type": "caller",
            "signer_id": "caller",
            "signing_scheme": "none",
        },
        "signature": "caller-signature",
    }
    derived_receipt = build_policy_receipt_artifact(
        task_dict=injected_task,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    results.append(
        CheckResult(
            "contract.policy_receipt_ignores_injected_input",
            derived_receipt is not None and derived_receipt.policy_receipt_id != "caller-injected",
            {
                "policy_receipt_id": derived_receipt.policy_receipt_id if derived_receipt else None,
                "signing_scheme": derived_receipt.signer_metadata.signing_scheme if derived_receipt else None,
            },
        )
    )

    governed_task["params"]["governance"] = governance_ctx
    attached = attach_evidence_bundle(
        task_dict=governed_task,
        envelope={
            "task_id": governed_task["task_id"],
            "success": True,
            "payload": {"result": {"status": "executed"}},
            "meta": {"exec": {"finished_at": "2026-03-24T09:10:10+00:00"}},
        },
        organ_id="organism",
        agent_id="agent-1",
    )
    evidence_bundle = attached.get("meta", {}).get("evidence_bundle", {})
    results.append(
        CheckResult(
            "contract.evidence_bundle_post_execution",
            evidence_bundle.get("created_at") == "2026-03-24T09:10:10+00:00"
            and evidence_bundle.get("policy_receipt_id") == governance_ctx["policy_receipt"]["policy_receipt_id"],
            {
                "created_at": evidence_bundle.get("created_at"),
                "policy_receipt_id": evidence_bundle.get("policy_receipt_id"),
            },
        )
    )

    record = _build_audit_record(
        task_id="task-runtime-jsonld",
        intent_id="intent-runtime-jsonld",
        asset_id="asset-1",
    )
    client = _make_client(record)
    get_response = client.get("/replay/jsonld", params={"audit_id": record["id"]})
    post_response = client.post("/replay/jsonld", json={"audit_id": record["id"]})
    results.append(
        CheckResult(
            "contract.jsonld_export_only",
            get_response.status_code == 200 and post_response.status_code == 405,
            {
                "get_status": get_response.status_code,
                "post_status": post_response.status_code,
                "jsonld_keys": sorted(get_response.json().keys()) if get_response.status_code == 200 else [],
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nEvidence contract verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nEvidence contract verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
