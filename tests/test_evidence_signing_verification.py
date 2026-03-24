from __future__ import annotations

import base64
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.hal.custody.transition_receipts import (
    build_transition_receipt,
    verify_transition_receipt_result,
)
from seedcore.ops.evidence.builder import attach_evidence_bundle
from seedcore.ops.evidence.verification import (
    build_signed_artifact,
    verify_evidence_bundle_result,
    verify_policy_receipt_result,
)
from seedcore.services.replay_service import ReplayService

from test_replay_router import _build_audit_record


def _build_task_dict() -> dict:
    return {
        "task_id": "task-signing-1",
        "type": "action",
        "params": {
            "multimodal": {
                "detections": [{"label": "sealed_box", "confidence": 0.93}],
                "gps": {"lat": 13.123, "lon": 100.987},
            },
            "governance": {
                "action_intent": {
                    "intent_id": "intent-signing-1",
                    "resource": {
                        "asset_id": "asset-signing-1",
                        "provenance_hash": "prov-signing-1",
                        "target_zone": "vault_alpha",
                    },
                },
                "execution_token": {
                    "token_id": "token-signing-1",
                    "constraints": {"endpoint_id": "robot_sim://pybullet_r2d2_01"},
                },
                "policy_decision": {"allowed": True, "reason": "zone_match"},
            },
        },
    }


def test_evidence_completeness_includes_required_artifacts() -> None:
    transition_receipt = build_transition_receipt(
        intent_id="intent-signing-1",
        token_id="token-signing-1",
        actuator_endpoint="robot_sim://pybullet_r2d2_01",
        hardware_uuid="robot-1",
        actuator_result_hash="hash-signing-1",
        target_zone="vault_alpha",
        to_zone="vault_alpha",
    )
    envelope = {
        "payload": {
            "results": [
                {
                    "tool": "reachy.motion",
                    "output": {
                        "actuator_endpoint": "robot_sim://pybullet_r2d2_01",
                        "transition_receipt": transition_receipt,
                    },
                }
            ]
        },
        "meta": {"exec": {"finished_at": "2026-03-24T10:10:10+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=_build_task_dict(),
        envelope=envelope,
        organ_id="physical_actuation_organ",
        agent_id="actuator_agent_1",
    )["meta"]["evidence_bundle"]

    assert bundle["policy_receipt_id"]
    assert bundle["execution_token_id"] == "token-signing-1"
    assert bundle["transition_receipt_ids"] == [transition_receipt["transition_receipt_id"]]
    assert bundle["evidence_inputs"]["execution_summary"]["actuator_endpoint"] == "robot_sim://pybullet_r2d2_01"
    assert bundle["evidence_inputs"]["policy_receipt"]["policy_receipt_id"] == bundle["policy_receipt_id"]
    assert bundle["evidence_inputs"]["transition_receipts"][0]["transition_receipt_id"] == transition_receipt["transition_receipt_id"]
    assert bundle["telemetry_refs"]
    assert bundle["asset_fingerprint"]["fingerprint_hash"]


def test_signer_abstraction_supports_hmac_and_ed25519(monkeypatch) -> None:
    payload = {"artifact_id": "signing-demo", "status": "ok"}

    _, hmac_metadata, hmac_signature = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
    )
    assert hmac_signature
    assert hmac_metadata.signing_scheme == "hmac_sha256"

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    monkeypatch.setenv("SEEDCORE_EVIDENCE_BUNDLE_SIGNER_MODE", "ed25519")
    monkeypatch.setenv(
        "SEEDCORE_EVIDENCE_ED25519_PRIVATE_KEY_B64",
        base64.b64encode(private_bytes).decode("ascii"),
    )
    monkeypatch.setenv(
        "SEEDCORE_EVIDENCE_PUBLIC_KEYS_JSON",
        json.dumps({"evidence-ed25519-k1": {"public_key": base64.b64encode(public_bytes).decode("ascii")}}),
    )
    monkeypatch.setenv("SEEDCORE_EVIDENCE_ED25519_KEY_ID", "evidence-ed25519-k1")

    _, ed_metadata, ed_signature = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
        endpoint_id="robot_sim://pybullet_r2d2_01",
        trust_level="attested",
        node_id="robot_sim://pybullet_r2d2_01",
    )
    assert ed_signature
    assert ed_metadata.signing_scheme == "ed25519"
    assert ed_metadata.key_ref == "evidence-ed25519-k1"


def test_receipt_chains_validate_and_detect_tamper() -> None:
    record = _build_audit_record(
        task_id="task-signing-chain",
        intent_id="intent-signing-chain",
        asset_id="asset-signing-chain",
    )
    service = ReplayService()

    transition_results = record["evidence_bundle"]["evidence_inputs"]["transition_receipts"]
    signer_chain = service._build_signer_chain(  # noqa: SLF001 - verification target
        policy_receipt=record["policy_receipt"],
        evidence_bundle=record["evidence_bundle"],
        transition_receipts=transition_results,
    )
    verification = service._build_verification_status(  # noqa: SLF001 - verification target
        policy_receipt=record["policy_receipt"],
        evidence_bundle=record["evidence_bundle"],
        transition_receipts=transition_results,
    )

    assert [item["artifact_type"] for item in signer_chain] == [
        "policy_receipt",
        "evidence_bundle",
        "transition_receipt",
    ]
    assert verification.verified is True

    tampered = dict(transition_results[0])
    tampered["payload_hash"] = "broken-hash"
    tampered_result = verify_transition_receipt_result(tampered)
    assert tampered_result["verified"] is False
    assert tampered_result["error"] == "payload_hash_mismatch"


def test_fingerprint_preserves_metadata_through_bundle_and_replay_summary() -> None:
    envelope = {
        "payload": {"results": []},
        "meta": {"exec": {"finished_at": "2026-03-24T10:20:20+00:00"}},
    }
    task_dict = _build_task_dict()
    task_dict["params"]["governance"]["node_id"] = "robot_sim://pybullet_r2d2_01"

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="actuation_organ",
        agent_id="agent-1",
    )["meta"]["evidence_bundle"]

    fingerprint = bundle["asset_fingerprint"]
    assert fingerprint["capture_context"]["asset_id"] == "asset-signing-1"
    assert fingerprint["capture_context"]["target_zone"] == "vault_alpha"
    assert fingerprint["hardware_witness"]["node_id"] == "robot_sim://pybullet_r2d2_01"
    assert set(fingerprint["modality_map"].keys()) >= {"provenance", "visual_hash", "gps_hash"}

    record = _build_audit_record(
        task_id="task-signing-fingerprint",
        intent_id="intent-signing-fingerprint",
        asset_id="asset-signing-fingerprint",
    )
    record["evidence_bundle"]["asset_fingerprint"] = fingerprint
    summary = ReplayService()._build_fingerprint_summary(  # noqa: SLF001
        type("Replay", (), {"evidence_bundle": record["evidence_bundle"]})()
    )
    assert summary["fingerprint_hash"] == fingerprint["fingerprint_hash"]
    assert set(summary["modalities"]) >= {"provenance", "visual_hash", "gps_hash"}


def test_signed_artifacts_verify_cleanly() -> None:
    record = _build_audit_record(
        task_id="task-signing-verify",
        intent_id="intent-signing-verify",
        asset_id="asset-signing-verify",
    )
    assert verify_policy_receipt_result(record["policy_receipt"])["verified"] is True
    assert verify_evidence_bundle_result(record["evidence_bundle"])["verified"] is True
