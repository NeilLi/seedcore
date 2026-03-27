import base64
import hashlib
import hmac
import json
import os
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

from seedcore.hal.custody.transition_receipts import build_transition_receipt
from seedcore.ops.evidence.builder import attach_evidence_bundle
from seedcore.ops.evidence.verification import canonical_json


def test_attach_evidence_bundle_uses_new_canonical_fields():
    task_dict = {
        "task_id": "task-e-1",
        "type": "action",
        "params": {
            "multimodal": {
                "location_context": "vault_alpha",
                "detections": [{"label": "sealed_box", "confidence": 0.93}],
                "gps": {"lat": 13.123, "lon": 100.987},
            },
            "governance": {
                "action_intent": {
                    "intent_id": "intent-e-1",
                    "resource": {"asset_id": "asset-1", "provenance_hash": "prov-1", "target_zone": "vault_alpha"},
                },
                "execution_token": {"token_id": "token-e-1"},
                "policy_decision": {
                    "allowed": True,
                    "reason": "zone_match",
                    "authz_graph": {"snapshot_hash": "hash-e-1", "snapshot_version": "snapshot:1"},
                    "governed_receipt": {"snapshot_hash": "hash-e-1", "snapshot_version": "snapshot:1"},
                },
            },
        },
    }
    envelope = {
        "task_id": "task-e-1",
        "payload": {"result": {"enqueued": [{"resp": {"device_id": "tuya-abc", "status": "ok"}}]}},
        "meta": {"exec": {"finished_at": "2026-03-10T10:10:10+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="physical_actuation_organ",
        agent_id="actuator_agent_1",
    )["meta"]["evidence_bundle"]

    assert bundle["evidence_bundle_id"]
    assert bundle["task_id"] == "task-e-1"
    assert bundle["intent_id"] == "intent-e-1"
    assert bundle["execution_token_id"] == "token-e-1"
    assert isinstance(bundle["evidence_inputs"]["execution_summary"], dict)
    assert isinstance(bundle["telemetry_refs"], list)
    assert isinstance(bundle["asset_fingerprint"]["modality_map"], dict)
    assert bundle["decision_graph_snapshot_hash"] == "hash-e-1"
    assert bundle["signer_metadata"]["signing_scheme"] == "hmac_sha256"


def test_policy_receipt_and_bundle_signatures_are_deterministic(monkeypatch):
    monkeypatch.setenv("SEEDCORE_EVIDENCE_SIGNING_SECRET", "test-secret")
    task_dict = {
        "task_id": "task-e-2",
        "type": "action",
        "params": {
            "governance": {
                "action_intent": {
                    "intent_id": "intent-e-2",
                    "resource": {"asset_id": "asset-2", "provenance_hash": "prov-2"},
                },
                "execution_token": {"token_id": "token-e-2"},
                "policy_decision": {"allowed": True},
            }
        },
    }
    envelope = {"payload": {"results": []}, "meta": {"exec": {"finished_at": "2026-03-10T10:12:12+00:00"}}}

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=json.loads(json.dumps(envelope)),
        organ_id="organ-r",
        agent_id="agent-r",
    )["meta"]["evidence_bundle"]

    payload = dict(bundle)
    signature = payload.pop("signature")
    signer_metadata = payload.pop("signer_metadata")
    payload.pop("trust_proof", None)
    expected_signature = hmac.new(
        b"test-secret",
        hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert signature == expected_signature
    assert signer_metadata["signing_scheme"] == "hmac_sha256"


def test_evidence_bundle_binds_transition_receipt_ids():
    transition_receipt = build_transition_receipt(
        intent_id="intent-e-4",
        token_id="token-e-4",
        actuator_endpoint="robot_sim://pybullet_r2d2_01",
        hardware_uuid="robot-4",
        actuator_result_hash="hash-edge-4",
        target_zone="zone-r",
        to_zone="zone-r",
    )
    task_dict = {
        "task_id": "task-e-4",
        "type": "action",
        "params": {
            "governance": {
                "action_intent": {
                    "intent_id": "intent-e-4",
                    "resource": {"asset_id": "asset-4", "provenance_hash": "prov-4", "target_zone": "zone-r"},
                },
                "execution_token": {"token_id": "token-e-4"},
                "policy_decision": {"allowed": True},
            }
        },
    }
    envelope = {
        "payload": {"results": [{"tool": "reachy.motion", "output": {"transition_receipt": transition_receipt}}]},
        "meta": {"exec": {"finished_at": "2026-03-10T10:11:11+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="actuation_organ",
        agent_id="agent_77",
    )["meta"]["evidence_bundle"]

    assert bundle["transition_receipt_ids"] == [transition_receipt["transition_receipt_id"]]
    assert bundle["evidence_inputs"]["transition_receipts"][0]["transition_receipt_id"] == transition_receipt["transition_receipt_id"]


def test_evidence_bundle_can_select_ed25519_when_policy_allows(monkeypatch):
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

    task_dict = {
        "task_id": "task-e-5",
        "type": "action",
        "params": {
            "governance": {
                "action_intent": {
                    "intent_id": "intent-e-5",
                    "resource": {"asset_id": "asset-5", "provenance_hash": "prov-5"},
                },
                "execution_token": {"token_id": "token-e-5"},
                "policy_decision": {"allowed": True},
            }
        },
    }
    envelope = {"payload": {"results": []}, "meta": {"exec": {"finished_at": "2026-03-10T10:12:12+00:00"}}}

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="organ-r",
        agent_id="agent-r",
    )["meta"]["evidence_bundle"]

    assert bundle["signer_metadata"]["signing_scheme"] == "ed25519"
    assert bundle["signer_metadata"]["key_ref"] == "evidence-ed25519-k1"
