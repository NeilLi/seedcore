from seedcore.ops.evidence.state_binding import compute_authority_state_binding_hash


def test_compute_authority_state_binding_hash_is_deterministic() -> None:
    action_intent_a = {
        "intent_id": "intent-1",
        "resource": {"asset_id": "asset-1", "target_zone": "vault-a"},
        "action": {
            "operation": "MOVE",
            "parameters": {
                "transfer_context": {
                    "from_zone": "staging-a",
                    "to_zone": "vault-a",
                    "expected_current_custodian": "principal:a",
                    "next_custodian": "principal:b",
                }
            },
        },
    }
    action_intent_b = {
        "action": {
            "parameters": {
                "transfer_context": {
                    "next_custodian": "principal:b",
                    "to_zone": "vault-a",
                    "from_zone": "staging-a",
                    "expected_current_custodian": "principal:a",
                }
            },
            "operation": "MOVE",
        },
        "resource": {"target_zone": "vault-a", "asset_id": "asset-1"},
        "intent_id": "intent-1",
    }
    kwargs = {
        "approval_context": {
            "approval_envelope_id": "approval-1",
            "approval_envelope_version": 3,
            "approval_binding_hash": "sha256:approval-binding",
            "approval_transition_head": "sha256:approval-head",
        },
        "governed_receipt": {
            "principal_ref": "principal:a",
            "snapshot_hash": "sha256:snapshot",
            "evidence_refs": ["telemetry:1", "telemetry:2"],
        },
        "authz_graph": {"current_custodian": "principal:a"},
        "telemetry_summary": {"observed_at": "2026-04-03T00:00:00Z", "freshness_seconds": 5},
        "relevant_twin_snapshot": {"asset": {"id": "asset-twin-1", "revision_stage": "published"}},
    }

    hash_a = compute_authority_state_binding_hash(action_intent=action_intent_a, **kwargs)
    hash_b = compute_authority_state_binding_hash(action_intent=action_intent_b, **kwargs)

    assert isinstance(hash_a, str)
    assert hash_a.startswith("sha256:")
    assert hash_a == hash_b


def test_compute_authority_state_binding_hash_returns_none_without_material() -> None:
    assert compute_authority_state_binding_hash() is None
