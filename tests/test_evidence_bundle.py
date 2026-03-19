# Import mock dependencies BEFORE any other imports
import hashlib
import hmac
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

from seedcore.hal.custody.transition_receipts import build_transition_receipt
from seedcore.ops.evidence.builder import (
    _canonical_json,
    _extract_actuator_endpoint,
    attach_evidence_bundle,
)


def test_attach_evidence_bundle_includes_required_fields():
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
                    "resource": {"target_zone": "vault_alpha"},
                },
                "execution_token": {"token_id": "token-e-1"},
            },
        },
    }
    envelope = {
        "task_id": "task-e-1",
        "success": True,
        "error": None,
        "error_type": None,
        "retry": True,
        "decision_kind": None,
        "path": "organism_core",
        "payload": {
            "result": {
                "enqueued": [
                    {
                        "ok": True,
                        "command_id": "cmd-1",
                        "resp": {
                            "device_id": "tuya-abc",
                            "status": "ok",
                        },
                    }
                ]
            }
        },
        "meta": {
            "exec": {"finished_at": "2026-03-10T10:10:10+00:00"},
        },
    }

    out = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="physical_actuation_organ",
        agent_id="actuator_agent_1",
    )

    bundle = out["meta"]["evidence_bundle"]
    assert bundle["intent_ref"] == "governance://action-intent/intent-e-1"
    assert bundle["executed_at"] == "2026-03-10T10:10:10+00:00"
    assert "telemetry_snapshot" in bundle
    assert "execution_receipt" in bundle
    assert "node_id" in bundle
    assert "policy_receipt" in bundle
    assert "asset_fingerprint" in bundle
    assert bundle["execution_receipt"]["proof_type"] == "hmac_sha256"
    assert isinstance(bundle["execution_receipt"]["signature"], str)
    assert len(bundle["execution_receipt"]["signature"]) > 10
    assert isinstance(bundle["execution_receipt"]["signed_payload"], dict)
    assert isinstance(bundle["execution_receipt"]["signer"], dict)


def test_evidence_bundle_mandatory_field_completeness():
    task_dict = {
        "task_id": "task-e-2",
        "type": "action",
        "params": {
            "location_context": "zone-z",
            "governance": {
                "action_intent": {
                    "intent_id": "intent-e-2",
                    "resource": {"target_zone": "zone-z"},
                },
                "execution_token": {"token_id": "token-e-2"},
                "policy_decision": {"allowed": True, "reason": "zone_match"},
            },
            "multimodal": {
                "current_zone": "zone-z",
                "vision": [{"label": "sealed_bin", "confidence": 0.98}],
                "sensors": [{"source": "imu", "value": "stable"}],
                "gps": {"lat": 18.8, "lon": 98.9},
            },
        },
    }
    envelope = {
        "payload": {
            "result": {
                "enqueued": [
                    {
                        "resp": {
                            "actuator_endpoint": "robot_sim://actuator/move_forward",
                            "status": "accepted",
                            "device_id": "sim-001",
                            "result_hash": "abc123",
                            "actuator_ack": True,
                        }
                    }
                ]
            }
        },
        "meta": {"exec": {"finished_at": "2026-03-10T10:11:11+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="actuation_organ",
        agent_id="agent_77",
    )["meta"]["evidence_bundle"]

    assert bundle["intent_ref"]
    assert bundle["executed_at"]
    assert isinstance(bundle["telemetry_snapshot"], dict)
    assert isinstance(bundle["execution_receipt"], dict)
    assert isinstance(bundle["policy_receipt"], dict)
    assert isinstance(bundle["asset_fingerprint"], dict)

    telemetry = bundle["telemetry_snapshot"]
    assert telemetry["executed_by"]["organ_id"] == "actuation_organ"
    assert telemetry["executed_by"]["agent_id"] == "agent_77"
    assert telemetry["executed_by"]["node_id"] == bundle["node_id"]
    assert "target_zone" in telemetry["zone_checks"]
    assert "current_zone" in telemetry["zone_checks"]
    assert isinstance(telemetry["vision"], list)
    assert isinstance(telemetry["sensors"], list)
    assert isinstance(telemetry["endpoint_responses"], list)

    receipt = bundle["execution_receipt"]
    assert receipt["proof_type"] == "hmac_sha256"
    assert receipt["signature"]
    assert receipt["payload_hash"]
    assert isinstance(receipt["signed_payload"], dict)
    assert receipt["signed_payload"]["intent_id"] == "intent-e-2"
    assert receipt["signed_payload"]["policy_decision"]["allowed"] is True
    assert receipt["node_id"] == bundle["node_id"]
    assert isinstance(receipt["signer"], dict)

    policy_receipt = bundle["policy_receipt"]
    assert policy_receipt["execution_token"]["token_id"] == "token-e-2"
    assert isinstance(policy_receipt["signer"], dict)
    assert policy_receipt["policy_decision_hash"]

    asset_fingerprint = bundle["asset_fingerprint"]
    assert asset_fingerprint["fingerprint_hash"]
    assert asset_fingerprint["algorithm"] == "sha256"


def test_evidence_bundle_hashing_is_reproducible_and_explainable(monkeypatch):
    monkeypatch.setenv("SEEDCORE_EVIDENCE_SIGNING_SECRET", "test-secret")
    task_dict = {
        "task_id": "task-e-3",
        "type": "action",
        "params": {
            "governance": {
                "action_intent": {"intent_id": "intent-e-3"},
                "execution_token": {"token_id": "token-e-3"},
                "policy_decision": {"allowed": True},
            }
        },
    }
    envelope = {
        "payload": {
            "results": [
                {
                    "tool": "reachy.motion",
                    "output": {
                        "actuator_endpoint": "robot_sim://reachy/pose",
                        "result_hash": "hash-r3",
                    },
                }
            ]
        },
        "meta": {"exec": {"finished_at": "2026-03-10T10:12:12+00:00"}},
    }

    out_one = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=json.loads(json.dumps(envelope)),
        organ_id="organ-r",
        agent_id="agent-r",
    )["meta"]["evidence_bundle"]["execution_receipt"]

    out_two = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=json.loads(json.dumps(envelope)),
        organ_id="organ-r",
        agent_id="agent-r",
    )["meta"]["evidence_bundle"]["execution_receipt"]

    assert out_one["payload_hash"] == out_two["payload_hash"]
    assert out_one["signature"] == out_two["signature"]

    recomputed_hash = hashlib.sha256(_canonical_json(out_one["signed_payload"]).encode("utf-8")).hexdigest()
    assert out_one["payload_hash"] == recomputed_hash

    expected_signature = hmac.new(
        b"test-secret",
        out_one["payload_hash"].encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert out_one["signature"] == expected_signature


def test_evidence_bundle_binds_transition_receipt_hash():
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
                    "resource": {"target_zone": "zone-r"},
                },
                "execution_token": {"token_id": "token-e-4"},
            }
        },
    }
    envelope = {
        "payload": {
            "results": [
                {
                    "tool": "reachy.motion",
                    "output": {
                        "actuator_endpoint": "robot_sim://pybullet_r2d2_01",
                        "result_hash": "hash-edge-4",
                        "transition_receipt": transition_receipt,
                    },
                }
            ]
        },
        "meta": {"exec": {"finished_at": "2026-03-10T10:13:13+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="actuation_organ",
        agent_id="agent_edge",
    )["meta"]["evidence_bundle"]

    receipt = bundle["execution_receipt"]
    assert receipt["transition_receipt"]["payload_hash"] == transition_receipt["payload_hash"]
    assert receipt["transition_receipt_hash"] == hashlib.sha256(
        _canonical_json(transition_receipt).encode("utf-8")
    ).hexdigest()
    assert (
        receipt["signed_payload"]["transition_receipt_hash"]
        == receipt["transition_receipt_hash"]
    )
    assert receipt["signer"]["proof_type"] == transition_receipt["proof_type"]
    assert receipt["signer"]["key_id"] == transition_receipt.get("key_id")


def test_evidence_bundle_v11_prefers_explicit_node_and_asset_fingerprint():
    task_dict = {
        "task_id": "task-e-5",
        "type": "action",
        "params": {
            "governance": {
                "node_id": "node://line-a/arm-2",
                "asset_fingerprint": {
                    "fingerprint_hash": "fingerprint-custom-5",
                    "algorithm": "sha256",
                    "source_modalities": ["vision", "gps"],
                    "components": {"vision_hash": "vh-5", "gps_hash": "gh-5"},
                },
                "action_intent": {
                    "intent_id": "intent-e-5",
                    "resource": {
                        "asset_id": "asset-e-5",
                        "target_zone": "zone-e-5",
                    },
                },
                "execution_token": {
                    "token_id": "token-e-5",
                    "issued_at": "2026-03-10T10:14:14+00:00",
                    "signature": "sig-token-e-5",
                    "issuer": "seedcore-pdp-main",
                    "proof_type": "hmac_sha256",
                },
                "policy_decision": {"allowed": True, "reason": "approved"},
                "policy_case": {"policy_snapshot": "snapshot:5"},
            },
            "multimodal": {
                "detections": [{"label": "asset-e-5", "confidence": 0.99}],
                "gps": {"lat": 18.81, "lon": 98.92},
            },
        },
    }
    envelope = {
        "payload": {"results": []},
        "meta": {"exec": {"finished_at": "2026-03-10T10:14:20+00:00"}},
    }

    bundle = attach_evidence_bundle(
        task_dict=task_dict,
        envelope=envelope,
        organ_id="actuation_organ",
        agent_id="agent-e5",
    )["meta"]["evidence_bundle"]

    assert bundle["node_id"] == "node://line-a/arm-2"
    assert bundle["execution_receipt"]["node_id"] == "node://line-a/arm-2"
    assert bundle["telemetry_snapshot"]["executed_by"]["node_id"] == "node://line-a/arm-2"
    assert bundle["asset_fingerprint"]["fingerprint_hash"] == "fingerprint-custom-5"
    assert bundle["policy_receipt"]["policy_snapshot"] == "snapshot:5"
    assert bundle["policy_receipt"]["signer"]["signer_id"] == "seedcore-pdp-main"


@pytest.mark.parametrize(
    ("actuator_entries", "task_dict", "expected_endpoint"),
    [
        (
            [{"resp": {"actuator_endpoint": "robot_sim://direct/resp"}}],
            {"params": {}},
            "robot_sim://direct/resp",
        ),
        (
            [{"tool": "reachy.motion", "output": {"actuator_endpoint": "robot_sim://direct/output"}}],
            {"params": {}},
            "robot_sim://direct/output",
        ),
        (
            [{"tool": "reachy.motion", "output": {"endpoint_response": {"actuator_endpoint": "robot_sim://nested"}}}],
            {"params": {}},
            "robot_sim://nested",
        ),
        (
            [{"resp": {"device_id": "tuya-device-1", "status": "ok"}}],
            {"params": {}},
            "tuya://tuya-device-1",
        ),
        (
            [{"tool": "reachy.motion", "output": {"robot_state": {"head": {"yaw": 0.2}}}}],
            {"params": {}},
            "tool://reachy.motion",
        ),
        (
            [],
            {"params": {"routing": {"target_organ_hint": "physical_actuation_organ"}}},
            "organ://physical_actuation_organ",
        ),
    ],
)
def test_actuator_endpoint_extraction_precedence(actuator_entries, task_dict, expected_endpoint):
    assert _extract_actuator_endpoint(task_dict, actuator_entries) == expected_endpoint
