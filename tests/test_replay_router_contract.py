from __future__ import annotations

from test_replay_router import _build_audit_record, _make_client
from test_replay_service import _apply_transition_metadata


def test_trust_surface_success_schema_contract() -> None:
    record = _build_audit_record(task_id="task-contract-1", intent_id="intent-contract-1", asset_id="asset-contract-1")
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 200
    publish_body = publish.json()
    public_id = publish_body["public_id"]

    assert {
        "public_id",
        "trust_url",
        "verify_url",
        "jsonld_url",
        "certificate_url",
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
        "proof_surface",
    }.issubset(publish_body.keys())
    assert {
        "artifact_refs",
        "key_hashes",
        "trust_gap_codes",
        "owner_context_ref",
        "operator_action_codes",
    }.issubset(publish_body["proof_surface"].keys())
    assert {
        "authority_consistency_hash",
        "owner_context_hash",
        "governed_receipt_hash",
        "fingerprint_hash",
    }.issubset(publish_body["proof_surface"]["key_hashes"].keys())

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 200
    trust_body = trust.json()
    assert {
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
        "policy_summary",
        "authorization",
    }.issubset(trust_body.keys())

    certificate = client.get(f"/trust/{public_id}/certificate")
    assert certificate.status_code == 200
    cert_body = certificate.json()
    assert {
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
        "trust_gap_codes",
        "trust_gap_details",
        "owner_context",
    }.issubset(cert_body.keys())

    public_jsonld = client.get(f"/trust/{public_id}/jsonld")
    assert public_jsonld.status_code == 200
    proof = public_jsonld.json().get("proof", {})
    assert {
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
        "trust_gap_codes",
        "trust_gap_details",
    }.issubset(proof.keys())

    verify = client.get(f"/verify/{public_id}")
    assert verify.status_code == 200
    verify_body = verify.json()
    assert {
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
    }.issubset(verify_body.keys())


def test_trust_publish_mismatch_schema_contract() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-contract-mismatch-1", intent_id="intent-contract-mismatch-1", asset_id="asset-contract-mismatch-1")
    )
    record["action_intent"] = {
        "intent_id": "intent-contract-mismatch-1",
        "principal": {
            "agent_id": "did:seedcore:assistant:warehouse-bot-01",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
        },
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "gateway": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "delegation_ref": "delegation:owner-8841-transfer",
                }
            },
        },
    }
    record["policy_decision"]["governed_receipt"]["owner_context"] = {
        "owner_id": "did:seedcore:owner:other-999",
        "creator_profile_ref": {"owner_id": "did:seedcore:owner:other-999", "version": "v2"},
        "trust_preferences_ref": {"owner_id": "did:seedcore:owner:other-999", "trust_version": "v1"},
    }
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 409
    body = publish.json()["detail"]
    assert {
        "code",
        "issues",
        "authority_consistency",
        "authority_consistency_hash",
        "owner_context_hash",
        "operator_actions",
        "proof_surface",
    }.issubset(body.keys())
    assert body["code"] == "authority_binding_mismatch"
    assert body["proof_surface"]["artifact_refs"]["trust_url"] is None
