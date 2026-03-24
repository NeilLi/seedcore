from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from fastapi.testclient import TestClient

from seedcore.coordinator.core.governance import build_governance_context
from seedcore.models.evidence_bundle import EvidenceBundle, PolicyReceipt
from seedcore.models.task_payload import TaskPayload
from seedcore.ops.evidence.builder import attach_evidence_bundle, build_policy_receipt_artifact

from test_replay_router import _build_audit_record, _make_client


def _build_governed_task(*, intent_id: str = "intent-evidence-contract") -> dict:
    issued_at = datetime(2026, 3, 24, 9, 0, tzinfo=timezone.utc)
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


def test_task_payload_is_not_replay_evidence() -> None:
    payload = TaskPayload.from_db(
        {
            "task_id": "task-payload-not-evidence",
            "type": "action",
            "params": {"interaction": {"assigned_agent_id": "agent-1"}},
        }
    )
    task_dict = payload.model_dump(mode="json")

    with pytest.raises(Exception):
        EvidenceBundle(**task_dict)

    with pytest.raises(Exception):
        PolicyReceipt(**task_dict)


def test_policy_receipt_is_pdp_generated_not_caller_injected() -> None:
    task_dict = _build_governed_task(intent_id="intent-policy-receipt-origin")
    task_dict["params"]["governance"]["policy_decision"] = {
        "allowed": True,
        "reason": "zone_match",
        "policy_snapshot": "runtime-baseline-v1.0.0",
    }
    task_dict["params"]["governance"]["execution_token"] = {"token_id": "token-policy-receipt-origin"}
    task_dict["params"]["governance"]["policy_receipt"] = {
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

    receipt = build_policy_receipt_artifact(
        task_dict=task_dict,
        timestamp="2026-03-24T09:00:00+00:00",
    )

    assert receipt is not None
    assert receipt.policy_receipt_id != "caller-injected"
    assert receipt.task_id == "task-intent-policy-receipt-origin"
    assert receipt.intent_id == "intent-policy-receipt-origin"
    assert receipt.signer_metadata.signing_scheme in {"hmac_sha256", "ed25519"}


def test_evidence_bundle_is_post_execution_while_policy_receipt_is_pdp_generated() -> None:
    task_dict = _build_governed_task(intent_id="intent-post-execution")
    governance = build_governance_context(task_dict)

    assert "policy_receipt" in governance
    assert "evidence_bundle" not in governance

    task_dict["params"]["governance"] = governance
    envelope = {
        "task_id": task_dict["task_id"],
        "success": True,
        "payload": {"result": {"status": "executed"}},
        "meta": {"exec": {"finished_at": "2026-03-24T09:10:10+00:00"}},
    }

    attached = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="organism",
        agent_id="agent-1",
    )
    bundle = attached["meta"]["evidence_bundle"]

    assert bundle["created_at"] == "2026-03-24T09:10:10+00:00"
    assert bundle["policy_receipt_id"] == governance["policy_receipt"]["policy_receipt_id"]
    assert bundle["evidence_inputs"]["policy_receipt"]["policy_receipt_id"] == governance["policy_receipt"]["policy_receipt_id"]


def test_jsonld_is_export_only() -> None:
    record = _build_audit_record(task_id="task-jsonld-export", intent_id="intent-jsonld-export", asset_id="asset-1")
    client: TestClient = _make_client(record)

    get_response = client.get("/replay/jsonld", params={"audit_id": record["id"]})
    assert get_response.status_code == 200
    assert "@context" in get_response.json()

    post_response = client.post("/replay/jsonld", json={"audit_id": record["id"]})
    assert post_response.status_code == 405
