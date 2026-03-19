from seedcore.ops.evidence.materializer import materialize_seedcore_custody_event_payload


def test_materialize_seedcore_custody_event_payload_from_audit_record():
    audit_record = {
        "id": "6f68f1dd-3f84-4f63-95c7-ab154a8c87f1",
        "intent_id": "intent-mat-1",
        "token_id": "token-mat-1",
        "record_type": "execution_receipt",
        "recorded_at": "2026-03-19T12:00:00+00:00",
        "input_hash": "input-hash-1",
        "policy_decision": {"allowed": True, "disposition": "allow"},
        "policy_receipt": {
            "policy_decision_hash": "policy-decision-hash-1",
            "execution_token": {"token_id": "token-mat-1"},
        },
        "evidence_bundle": {
            "intent_ref": "governance://action-intent/intent-mat-1",
            "executed_at": "2026-03-19T11:59:55+00:00",
            "node_id": "robot_sim://reachy/grasp#sim-1",
            "telemetry_snapshot": {
                "zone_checks": {"target_zone": "vault-a", "current_zone": "staging-a"},
                "vision": [{"label": "box", "confidence": 0.99}],
                "multimodal": {"environmental_telemetry": {"temp_c": 24.2}},
            },
            "asset_fingerprint": {
                "components": {"provenance_hash": "prov-hash-1", "vision_hash": "vision-hash-1"}
            },
            "execution_receipt": {
                "signature": "sig-1",
                "payload_hash": "payload-hash-1",
                "actuator_result_hash": "traj-hash-1",
                "node_id": "robot_sim://reachy/grasp#sim-1",
            },
        },
    }

    payload = materialize_seedcore_custody_event_payload(audit_record=audit_record)

    assert payload["@type"] == "seedcore:SeedCoreCustodyEvent"
    assert payload["@id"] == "seedcore:custody-event:6f68f1dd-3f84-4f63-95c7-ab154a8c87f1"
    assert payload["device_identity"] == "robot_sim://reachy/grasp#sim-1"
    assert payload["platform_state"] == "allow"
    assert payload["policy_verification"]["policy_hash"] == "policy-decision-hash-1"
    assert payload["policy_verification"]["authorization_token"] == "token-mat-1"
    assert payload["custody_transition"]["to"] == "vault-a"
    assert payload["custody_transition"]["from"] == "staging-a"
    assert payload["signature"] == "sig-1"
