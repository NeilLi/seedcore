from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from test_replay_router import _apply_transition_metadata, _build_audit_record, _make_client


def test_policy_execution_evidence_replay_chain_is_present() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(
            task_id="task-e2e-1",
            intent_id="intent-e2e-1",
            asset_id="asset-e2e-1",
        )
    )
    client = _make_client(record)

    response = client.get("/replay/artifacts", params={"audit_id": record["id"], "projection": "internal"})

    assert response.status_code == 200
    body = response.json()
    assert body["policy_receipt"]["intent_id"] == "intent-e2e-1"
    assert body["evidence_bundle"]["intent_id"] == "intent-e2e-1"
    assert body["evidence_bundle"]["policy_receipt_id"] == body["policy_receipt"]["policy_receipt_id"]
    assert body["transition_receipts"][0]["execution_token_id"] == body["evidence_bundle"]["execution_token_id"]
    assert body["governed_receipt"]["decision_hash"] == "receipt-intent-e2e-1"


def test_trust_page_works_end_to_end() -> None:
    record = _build_audit_record(task_id="task-e2e-2", intent_id="intent-e2e-2", asset_id="asset-e2e-2")
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    assert publish.status_code == 200
    public_id = publish.json()["public_id"]

    trust = client.get(f"/trust/{public_id}")
    assert trust.status_code == 200
    body = trust.json()
    assert body["trust_page_id"] == public_id
    assert body["subject_title"] == "Asset asset-e2e-2"
    assert body["public_jsonld_ref"].endswith(f"/trust/{public_id}/jsonld")
    assert body["public_certificate_ref"].endswith(f"/trust/{public_id}/certificate")
    assert isinstance(body["verifiable_claims"], list)


def test_public_verification_works_for_token_and_audit_lookup() -> None:
    record = _build_audit_record(task_id="task-e2e-3", intent_id="intent-e2e-3", asset_id="asset-e2e-3")
    client = _make_client(record)

    publish = client.post("/trust/publish", json={"audit_id": record["id"], "ttl_hours": 4})
    public_id = publish.json()["public_id"]

    by_token = client.get(f"/verify/{public_id}")
    assert by_token.status_code == 200
    assert by_token.json()["verified"] is True
    assert by_token.json()["trust_url"].endswith(f"/trust/{public_id}")

    by_audit = client.post("/verify", json={"audit_id": record["id"]})
    assert by_audit.status_code == 200
    assert by_audit.json()["verified"] is True
    assert by_audit.json()["subject_id"] == "asset-e2e-3"
    assert by_audit.json()["subject_type"] == "asset"
