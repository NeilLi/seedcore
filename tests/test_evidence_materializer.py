from seedcore.ops.evidence.materializer import materialize_seedcore_custody_event_payload


def test_materialize_seedcore_custody_event_payload_from_audit_record():
    audit_record = {
        "id": "6f68f1dd-3f84-4f63-95c7-ab154a8c87f1",
        "intent_id": "intent-mat-1",
        "recorded_at": "2026-03-19T12:00:00+00:00",
        "policy_decision": {
            "allowed": True,
            "disposition": "allow",
            "authz_graph": {
                "trust_gaps": [
                    {
                        "code": "stale_telemetry",
                        "message": "Gap detected: stale_telemetry",
                        "details": {},
                    }
                ]
            },
        },
        "policy_receipt": {
            "policy_receipt_id": "policy-r-1",
            "policy_decision_id": "policy-decision-hash-1",
            "decision_graph_snapshot_hash": "snapshot-hash-1",
            "decision_graph_snapshot_version": "snapshot:1",
            "state_binding_hash": "sha256:state-binding-hash-1",
        },
        "evidence_bundle": {
            "evidence_bundle_id": "bundle-1",
            "execution_token_id": "token-mat-1",
            "node_id": "robot_sim://reachy/grasp#sim-1",
            "decision_graph_snapshot_hash": "snapshot-hash-1",
            "decision_graph_snapshot_version": "snapshot:1",
            "state_binding_hash": "sha256:state-binding-hash-1",
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
                "nfc_verification": {
                    "disposition": "allow",
                    "reason_code": "rct_nfc_scan_verified",
                    "evidence_refs": ["evidence:nfc-scan-001"],
                    "freshness_seconds": 2,
                    "max_allowed_age_seconds": 60,
                    "observed_at": "2026-06-10T12:00:00Z",
                    "nfc_uid_hash": "sha256:nfc-public-hash",
                    "anchor_profile_ref": "profile:nxp-ntag424-dna-fixture-v1",
                    "scan_counter": 42,
                    "anchor_counter_key": "sha256:nfc-public-hash|profile:nxp-ntag424-dna-fixture-v1",
                    "challenge_nonce": "must-not-project",
                    "challenge_response_hash": "must-not-project",
                    "cmac_ref": "must-not-project",
                    "shadow_nfc_verification": {
                        "verified": True,
                        "disposition": "allow",
                        "reason_code": "rct_nfc_scan_verified",
                        "issues": [],
                        "challenge_nonce": "must-not-project",
                        "challenge_response_hash": "must-not-project",
                        "cmac_ref": "must-not-project",
                        "production_key_material": "must-not-project",
                    },
                },
                "taxonomy_bundle": {
                    "trust_gap_codes": [
                        {
                            "code": "stale_telemetry",
                            "operator_message": "Telemetry freshness exceeded policy threshold.",
                            "machine_category": "telemetry",
                            "severity": "critical",
                        }
                    ]
                },
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
    assert payload["policy_verification"]["state_binding_hash"] == "sha256:state-binding-hash-1"
    assert payload["policy_verification"]["trust_gap_details"][0]["message"] == "Telemetry freshness exceeded policy threshold."
    nfc = payload["policy_verification"]["nfc_verification"]
    assert nfc["disposition"] == "allow"
    assert nfc["reason_code"] == "rct_nfc_scan_verified"
    assert nfc["evidence_refs"] == ["evidence:nfc-scan-001"]
    assert nfc["nfc_uid_hash"] == "sha256:nfc-public-hash"
    assert "challenge_nonce" not in nfc
    assert "challenge_response_hash" not in nfc
    assert "cmac_ref" not in nfc
    assert nfc["shadow_nfc_verification"] == {
        "verified": True,
        "disposition": "allow",
        "reason_code": "rct_nfc_scan_verified",
        "issues": [],
    }
    assert "challenge_nonce" not in nfc["shadow_nfc_verification"]
    assert "challenge_response_hash" not in nfc["shadow_nfc_verification"]
    assert "cmac_ref" not in nfc["shadow_nfc_verification"]
    assert "production_key_material" not in nfc["shadow_nfc_verification"]
    assert payload["custody_transition"]["to"] == "vault-a"
    assert payload["custody_transition"]["from"] == "staging-a"
