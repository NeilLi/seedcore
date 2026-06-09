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


def test_replay_jsonld_exposes_agent_execution_replay_case_contract() -> None:
    record = _build_audit_record(task_id="task-contract-jsonld-1", intent_id="intent-contract-jsonld-1", asset_id="asset-contract-jsonld-1")
    client = _make_client(record)

    response = client.get("/replay/jsonld", params={"audit_id": record["id"]})
    assert response.status_code == 200
    proof = response.json().get("proof", {})
    execution_case = proof.get("execution_replay_case")

    assert execution_case["@type"] == "seedcore:ExecutionReplayCase"
    assert execution_case["contract_version"] == "seedcore.execution_replay_case.v1"
    assert execution_case["projection"] == "internal"
    assert execution_case["workflow_id"] == record["id"]
    assert execution_case["replay_verdict"] in {"consistent", "inconsistent", "incomplete"}
    assert {
        "intent_received",
        "authority_resolved",
        "policy_evaluated",
        "token_minted",
        "action_dispatched",
        "telemetry_attached",
        "receipt_sealed",
        "replay_verified",
        "result_verified",
        "state_published",
    } == {item["step_type"] for item in execution_case["steps"]}
    assert execution_case["policy_snapshots"][0]["policy_receipt_id"] == record["policy_receipt"]["policy_receipt_id"]
    assert execution_case["telemetry_checks"][0]["checks"]["asset_binding"] == "not_checked"
    assert execution_case["signer_chain_checks"][0]["validation_mode"] == "q2_signature_presence_and_metadata"
    assert execution_case["copilot_brief_scope"] == {
        "mode": "registered_runbook_ids_only",
        "dynamic_mitigation_text_allowed": False,
        "authority": "read_only_non_authority_bearing",
    }
    assert "seedcore-verify verify-chain" in execution_case["reproduction"]["offline_verifier_command"]

    public_response = client.get("/replay/jsonld", params={"audit_id": record["id"], "projection": "public"})
    assert public_response.status_code == 200
    assert "execution_replay_case" not in public_response.json().get("proof", {})


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
