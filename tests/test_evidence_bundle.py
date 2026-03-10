# Import mock dependencies BEFORE any other imports
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies

from seedcore.ops.evidence.builder import attach_evidence_bundle


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
    assert bundle["execution_receipt"]["proof_type"] == "hmac_sha256"
    assert isinstance(bundle["execution_receipt"]["signature"], str)
    assert len(bundle["execution_receipt"]["signature"]) > 10
