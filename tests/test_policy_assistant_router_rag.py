from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from seedcore.api.routers.policy_assistant_router import router as policy_assistant_router

NOW = datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(policy_assistant_router, prefix="/api/v1")
    return TestClient(app)


def test_policy_assistant_rag_query_happy_path() -> None:
    client = _make_client()
    payload = {
        "query": "co-signatures dynamic NFC challenge",
        "envelope": {
            "envelope_id": "env-rct-happy",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "restricted",
        },
        "mock_llm_response": "<scratchpad>Analyzing protocols.</scratchpad><response>Handoff requires co-signatures.</response>",
        "policy_rules": ["Follow RCT standards."],
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace"]["final_status"] == "accepted"
    assert data["evidence_bundle"] is not None
    assert len(data["evidence_bundle"]["evidence_items"]) > 0
    assert data["draft_answer"] is not None
    assert len(data["verified_claims"]) == 1
    assert data["prompt_metadata"] is not None


def test_policy_assistant_rag_query_blocked_path() -> None:
    client = _make_client()
    payload = {
        "query": "cryptoprocessor challenge",  # Matches restricted-rct-3
        "envelope": {
            "envelope_id": "env-rct-blocked",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "public",
        },
        "mock_llm_response": "<scratchpad>Analyzing.</scratchpad><response>Body</response>",
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace"]["final_status"] == "blocked"
    assert len(data["evidence_bundle"]["evidence_items"]) == 0
    assert data["draft_answer"] is None


def test_policy_assistant_rag_query_filters_denied_chunks_without_leakage() -> None:
    client = _make_client()
    payload = {
        "query": "",
        "envelope": {
            "envelope_id": "env-rct-filtered",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "public",
        },
        "mock_llm_response": "<scratchpad>Using public evidence only.</scratchpad><response>Body</response>",
        "action_parameters": {"workflow_type": "restricted_custody_transfer"},
        "template_version": "guarded-rag.v1",
        "claim_support_status": "supported",
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace"]["final_status"] == "accepted"
    assert data["trace"]["denied_candidate_count"] == 4
    assert data["prompt_metadata"]["denied_candidate_count"] == 4
    assert len(data["evidence_bundle"]["evidence_items"]) == 2

    body = response.text
    assert "doc-confidential-1" not in body
    assert "doc-restricted-1" not in body
    assert "doc-confidential-rct-2" not in body
    assert "doc-restricted-rct-3" not in body
    assert "Confidential facility operator" not in body
    assert "Restricted transaction audit" not in body
    assert "Confidential Jordan PE authentication" not in body
    assert "Restricted challenge nonce" not in body


def test_policy_assistant_rag_query_abstained_on_parse_error() -> None:
    client = _make_client()
    payload = {
        "query": "co-signatures",
        "envelope": {
            "envelope_id": "env-rct-abstained",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "restricted",
        },
        "mock_llm_response": "unclosed tag response without tags",
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 200
    data = response.json()

    assert data["trace"]["final_status"] == "abstained"
    assert "rag_response_missing" in data["trace"]["rejection_reason_codes"]


def test_policy_assistant_rag_query_invalid_ceiling_fails_validation() -> None:
    client = _make_client()
    payload = {
        "query": "co-signatures",
        "envelope": {
            "envelope_id": "env-rct-invalid",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "internal",
        },
        "mock_llm_response": "<scratchpad>...</scratchpad><response>Body</response>",
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 422


def test_policy_assistant_rag_query_masks_unexpected_internal_errors(monkeypatch) -> None:
    from seedcore.ops.rag.harness import GovernedRAGHarness

    def _raise_internal_error(self, **kwargs):
        del self, kwargs
        raise RuntimeError("sensitive fixture text doc-restricted-rct-3")

    monkeypatch.setattr(GovernedRAGHarness, "run_governed_query", _raise_internal_error)

    client = _make_client()
    payload = {
        "query": "co-signatures",
        "envelope": {
            "envelope_id": "env-rct-internal-error",
            "principal_ref": "principal:operator",
            "workflow_ref": "workflow:rct-1",
            "purpose": "operator_advisory",
            "policy_snapshot_ref": "snapshot-1",
            "policy_version": "v1",
            "issued_at": NOW.isoformat(),
            "classification_ceiling": "restricted",
        },
        "mock_llm_response": "<scratchpad>...</scratchpad><response>Body</response>",
    }

    response = client.post("/api/v1/policy-assistant/governed-rag/query", json=payload)
    assert response.status_code == 500
    assert response.json()["detail"] == {
        "error_code": "governed_rag_query_failed",
        "message": "Governed RAG advisory query failed.",
    }
    assert "sensitive fixture text" not in response.text
    assert "doc-restricted-rct-3" not in response.text
