#!/usr/bin/env python3
"""Verify the restricted custody transfer execution spine against the local SeedCore baseline."""

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

from seedcore.coordinator.core.governance import (  # noqa: E402
    ActionIntent,
    build_governance_context,
)
from seedcore.hal.custody.transition_receipts import build_transition_receipt  # noqa: E402
from seedcore.integrations.rust_kernel import verify_execution_token_with_rust  # noqa: E402
from seedcore.models.evidence_bundle import EvidenceBundle, PolicyReceipt, TransitionReceipt  # noqa: E402
from seedcore.models.task_payload import TaskPayload  # noqa: E402
from seedcore.ops.evidence.builder import build_evidence_bundle  # noqa: E402
from test_action_intent import _compiled_transfer_graph, _transfer_approval_envelope, _transfer_payload  # noqa: E402
from test_replay_router import _make_client  # noqa: E402
from test_replay_service import _build_audit_record  # noqa: E402


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict[str, Any]


def _api_url(path: str) -> str:
    base = os.getenv("SEEDCORE_API_URL", "http://127.0.0.1:8002").rstrip("/")
    return f"{base}{path}"


def _hal_url(path: str) -> str:
    base = os.getenv("SEEDCORE_HAL_URL", "http://127.0.0.1:8003").rstrip("/")
    return f"{base}{path}"


def _verify_execution_token_signature(token: dict[str, Any]) -> bool:
    verification = verify_execution_token_with_rust(token)
    return bool(verification.get("verified"))


def _build_runtime_transfer_payload(*, active_version: str) -> dict[str, Any]:
    payload = _transfer_payload()
    payload["task_id"] = "task-runtime-execution-spine"
    intent = payload["params"]["governance"]["action_intent"]
    intent["intent_id"] = "intent-runtime-execution-spine"
    intent["action"]["security_contract"]["version"] = "snapshot:1"
    intent["action"]["parameters"]["endpoint_id"] = "robot_sim://unit-1"
    intent["action"]["parameters"]["runtime_active_snapshot"] = active_version
    return payload


def _build_transfer_replay_record(*, governance_ctx: dict[str, Any], evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    intent = governance_ctx["action_intent"]
    decision = governance_ctx["policy_decision"]
    token = governance_ctx["execution_token"]
    record = _build_audit_record(
        task_id="task-runtime-execution-spine",
        intent_id=intent["intent_id"],
        asset_id=intent["resource"]["asset_id"],
    )
    record["policy_snapshot"] = decision["policy_snapshot"]
    record["token_id"] = token["token_id"]
    record["action_intent"] = intent
    record["policy_case"] = governance_ctx["policy_case"]
    record["policy_decision"] = decision
    record["policy_receipt"] = governance_ctx["policy_receipt"]
    record["evidence_bundle"] = evidence_bundle
    return record


def _build_evidence_bundle_for_spine(*, task_payload: dict[str, Any], governance_ctx: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    transition_receipt = build_transition_receipt(
        intent_id=governance_ctx["action_intent"]["intent_id"],
        token_id=governance_ctx["execution_token"]["token_id"],
        actuator_endpoint="robot_sim://unit-1",
        hardware_uuid="robot-1",
        actuator_result_hash="actuator-hash-execution-spine",
        from_zone="vault-a",
        to_zone="handoff-bay-3",
        target_zone="handoff-bay-3",
        executed_at="2026-03-20T10:01:00+00:00",
        receipt_nonce="nonce-execution-spine",
    )
    envelope = {
        "task_id": task_payload["task_id"],
        "success": True,
        "payload": {
            "result": {"status": "executed"},
            "results": [
                {
                    "output": {
                        "transition_receipt": transition_receipt,
                        "actuator_endpoint": "robot_sim://unit-1",
                        "result_hash": "actuator-hash-execution-spine",
                    }
                }
            ],
        },
        "meta": {"exec": {"finished_at": "2026-03-20T10:03:00+00:00"}},
    }
    task_dict = {
        "task_id": task_payload["task_id"],
        "params": {
            "governance": governance_ctx,
            "routing": {"target_organ_hint": "organism"},
        },
    }
    evidence_bundle = build_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="organism",
        agent_id=governance_ctx["action_intent"]["principal"]["agent_id"],
    ).model_dump(mode="json")
    return transition_receipt, evidence_bundle


def main() -> int:
    os.environ.setdefault("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    results: list[CheckResult] = []

    api_health = requests.get(_api_url("/health"), timeout=5)
    api_body = api_health.json()
    results.append(
        CheckResult(
            "runtime.api_healthy",
            api_health.status_code == 200 and api_body.get("status") == "healthy",
            {"status_code": api_health.status_code, "body": api_body},
        )
    )

    pkg_status = requests.get(_api_url("/api/v1/pkg/status"), timeout=5)
    pkg_body = pkg_status.json()
    active_version = str(pkg_body.get("active_version") or "").strip()
    results.append(
        CheckResult(
            "runtime.pkg_ready",
            pkg_status.status_code == 200
            and bool(pkg_body.get("available"))
            and bool(pkg_body.get("authz_graph_ready"))
            and bool(active_version),
            {
                "status_code": pkg_status.status_code,
                "active_snapshot_id": pkg_body.get("active_snapshot_id"),
                "active_version": active_version,
                "engine_type": pkg_body.get("engine_type"),
                "authz_graph_ready": pkg_body.get("authz_graph_ready"),
            },
        )
    )

    hal_status = requests.get(_hal_url("/status"), timeout=5)
    hal_body = hal_status.json()
    results.append(
        CheckResult(
            "runtime.hal_connected",
            hal_status.status_code == 200 and str(hal_body.get("state") or "").strip().lower() == "connected",
            {"status_code": hal_status.status_code, "body": hal_body},
        )
    )

    now = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    task_payload_dict = _build_runtime_transfer_payload(active_version=active_version)
    task_payload = TaskPayload.from_db(task_payload_dict)
    results.append(
        CheckResult(
            "spine.task_payload_ingress",
            task_payload.task_id == "task-runtime-execution-spine"
            and task_payload.type == "action"
            and "governance" in task_payload.params,
            {
                "task_id": task_payload.task_id,
                "task_type": task_payload.type,
                "has_governance": "governance" in task_payload.params,
            },
        )
    )

    compiled = _compiled_transfer_graph(
        now=now,
        telemetry_at=now - timedelta(minutes=1),
        inspection_at=now - timedelta(minutes=2),
        current_custodian="facility_mgr_001",
    )
    authoritative_approval_envelope = _transfer_approval_envelope()
    governance_ctx = build_governance_context(
        task_payload_dict,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=authoritative_approval_envelope,
    )
    action_intent = ActionIntent(**governance_ctx["action_intent"])
    results.append(
        CheckResult(
            "spine.action_intent_derived",
            action_intent.action.operation.value == "TRANSFER_CUSTODY"
            and action_intent.environment.origin_network == "network:warehouse-core",
            {
                "intent_id": action_intent.intent_id,
                "operation": action_intent.action.operation.value,
                "resource_uri": action_intent.resource.resource_uri,
                "origin_network": action_intent.environment.origin_network,
            },
        )
    )

    transfer_envelope = dict(authoritative_approval_envelope)
    transfer_envelope["policy_snapshot_ref"] = governance_ctx["policy_decision"]["policy_snapshot"]
    results.append(
        CheckResult(
            "spine.transfer_approval_envelope_current_equivalent",
            transfer_envelope["workflow_type"] == "custody_transfer"
            and transfer_envelope["status"] == "APPROVED"
            and len(transfer_envelope["required_approvals"]) == 2,
            {
                "implemented_as": "authoritative_transfer_approval_fixture",
                "approval_envelope_id": transfer_envelope["approval_envelope_id"],
                "status": transfer_envelope["status"],
                "required_roles": [item["role"] for item in transfer_envelope["required_approvals"]],
            },
        )
    )

    policy_decision = governance_ctx["policy_decision"]
    execution_token = governance_ctx["execution_token"]
    governed_receipt_hash = (
        policy_decision.get("governed_receipt", {}).get("decision_hash")
        if isinstance(policy_decision.get("governed_receipt"), dict)
        else None
    )
    results.append(
        CheckResult(
            "spine.policy_decision_execution_token_governed_receipt",
            policy_decision["allowed"] is True
            and policy_decision["disposition"] == "allow"
            and bool(governed_receipt_hash)
            and _verify_execution_token_signature(execution_token),
            {
                "disposition": policy_decision["disposition"],
                "reason": policy_decision.get("reason"),
                "token_id": execution_token.get("token_id"),
                "governed_receipt_hash": governed_receipt_hash,
                "workflow_type": policy_decision.get("authz_graph", {}).get("workflow_type"),
                "required_approvals": policy_decision.get("required_approvals"),
            },
        )
    )

    policy_receipt = PolicyReceipt(**governance_ctx["policy_receipt"])
    results.append(
        CheckResult(
            "spine.policy_receipt_minted",
            policy_receipt.intent_id == action_intent.intent_id
            and policy_receipt.governed_receipt_hash == governed_receipt_hash,
            {
                "policy_receipt_id": policy_receipt.policy_receipt_id,
                "policy_version": policy_receipt.policy_version,
                "governed_receipt_hash": policy_receipt.governed_receipt_hash,
            },
        )
    )

    transition_receipt_raw, evidence_bundle_raw = _build_evidence_bundle_for_spine(
        task_payload=task_payload_dict,
        governance_ctx=governance_ctx,
    )
    transition_receipt = TransitionReceipt(**transition_receipt_raw)
    evidence_bundle = EvidenceBundle(**evidence_bundle_raw)
    results.append(
        CheckResult(
            "spine.transition_receipt_and_evidence_bundle",
            transition_receipt.intent_id == action_intent.intent_id
            and evidence_bundle.policy_receipt_id == policy_receipt.policy_receipt_id
            and transition_receipt.transition_receipt_id in evidence_bundle.transition_receipt_ids,
            {
                "transition_receipt_id": transition_receipt.transition_receipt_id,
                "endpoint_id": transition_receipt.endpoint_id,
                "evidence_bundle_id": evidence_bundle.evidence_bundle_id,
                "node_id": evidence_bundle.node_id,
            },
        )
    )

    record = _build_transfer_replay_record(
        governance_ctx=governance_ctx,
        evidence_bundle=evidence_bundle_raw,
    )
    client = _make_client(record)
    replay_response = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "public"})
    trust_publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    public_id = trust_publish.json()["public_id"] if trust_publish.status_code == 200 else None
    trust_response = client.get(f"/trust/{public_id}") if public_id else None
    verify_response = client.get(f"/verify/{public_id}") if public_id else None
    public_artifacts = replay_response.json().get("public_artifacts", {}) if replay_response.status_code == 200 else {}
    trust_body = trust_response.json() if trust_response is not None else {}
    verify_body = verify_response.json() if verify_response is not None else {}
    results.append(
        CheckResult(
            "spine.verification_surface_projection_current_equivalent",
            replay_response.status_code == 200
            and trust_publish.status_code == 200
            and trust_response is not None
            and trust_response.status_code == 200
            and verify_response is not None
            and verify_response.status_code == 200
            and verify_body.get("verified") is True
            and bool(public_artifacts.get("policy_summary", {}).get("governed_receipt_hash"))
            and bool(public_artifacts.get("fingerprint_summary", {}).get("fingerprint_hash"))
            and trust_body.get("workflow_type") == "custody_transfer",
            {
                "implemented_as": "replay_artifacts + trust_page + verify",
                "replay_status": replay_response.status_code,
                "trust_status": trust_response.status_code if trust_response is not None else None,
                "verify_status": verify_response.status_code if verify_response is not None else None,
                "trust_page_status": trust_body.get("status"),
                "workflow_type": trust_body.get("workflow_type"),
                "verified": verify_body.get("verified"),
                "public_artifact_keys": sorted(public_artifacts.keys()),
            },
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nExecution spine verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1

    print("\nExecution spine verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
