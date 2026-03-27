from seedcore.ops.evidence.materializer import materialize_seedcore_custody_event_payload


def test_materialize_seedcore_custody_event_payload_from_audit_record():
    audit_record = {
        "id": "6f68f1dd-3f84-4f63-95c7-ab154a8c87f1",
        "intent_id": "intent-mat-1",
        "recorded_at": "2026-03-19T12:00:00+00:00",
        "policy_decision": {"allowed": True, "disposition": "allow"},
        "policy_receipt": {
            "policy_receipt_id": "policy-r-1",
            "policy_decision_id": "policy-decision-hash-1",
            "decision_graph_snapshot_hash": "snapshot-hash-1",
            "decision_graph_snapshot_version": "snapshot:1",
        },
        "evidence_bundle": {
            "evidence_bundle_id": "bundle-1",
            "execution_token_id": "token-mat-1",
            "node_id": "robot_sim://reachy/grasp#sim-1",
            "decision_graph_snapshot_hash": "snapshot-hash-1",
            "decision_graph_snapshot_version": "snapshot:1",
            "created_at": "2026-03-19T11:59:55+00:00",
            "signer_metadata": {"signer_id": "seedcore-evidence-service", "signing_scheme": "hmac_sha256"},
            "signature": "sig-1",
            "telemetry_refs": [
                {
                    "inline": {
                        "zone_checks": {"target_zone": "vault-a", "current_zone": "staging-a"},
                        "vision": [{"label": "box", "confidence": 0.99}],
                        "multimodal": {"environmental_telemetry": {"temp_c": 24.2}},
                    }
                }
            ],
            "asset_fingerprint": {
                "modality_map": {"provenance": "prov-hash-1", "visual_hash": "vision-hash-1"}
            },
            "evidence_inputs": {
                "execution_summary": {
                    "actuator_result_hash": "traj-hash-1",
                    "node_id": "robot_sim://reachy/grasp#sim-1",
                },
                "transition_receipts": [{"to_zone": "vault-a", "from_zone": "staging-a"}],
            },
        },
    }

    payload = materialize_seedcore_custody_event_payload(audit_record=audit_record)

    assert payload["@type"] == "seedcore:SeedCoreCustodyEvent"
    assert payload["@id"] == "seedcore:custody-event:6f68f1dd-3f84-4f63-95c7-ab154a8c87f1"
    assert payload["device_identity"] == "robot_sim://reachy/grasp#sim-1"
    assert payload["platform_state"] == "allow"
    assert payload["policy_verification"]["policy_hash"] == "policy-decision-hash-1"
    assert payload["policy_verification"]["decision_graph_snapshot_hash"] == "snapshot-hash-1"
    assert payload["custody_transition"]["to"] == "vault-a"
    assert payload["custody_transition"]["from"] == "staging-a"
