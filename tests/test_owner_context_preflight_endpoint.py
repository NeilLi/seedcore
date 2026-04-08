from __future__ import annotations

import os
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

import seedcore.api.routers.identity_router as identity_router
from seedcore.api.external_authority import (
    CreatorProfileRecord,
    DIDDocumentRecord,
    DIDVerificationMethod,
    TrustPreferencesRecord,
)


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(identity_router.router, prefix="/api/v1", tags=["Identity"])
    return TestClient(app)


def test_owner_context_preflight_predicts_trust_gaps(monkeypatch):
    client = _make_client()

    async def _fake_get_did(session, did):
        return DIDDocumentRecord(
            did=did,
            verification_method=DIDVerificationMethod(signing_scheme="ed25519", key_ref="key:owner"),
        )

    async def _fake_get_creator(session, owner_id):
        return CreatorProfileRecord(owner_id=owner_id, version="v1", updated_by="identity_router")

    async def _fake_get_trust(session, owner_id):
        return TrustPreferencesRecord(
            owner_id=owner_id,
            max_risk_score=0.5,
            merchant_allowlist=["amazon.com"],
            required_provenance_level="verified",
            required_evidence_modalities=["camera", "seal_sensor"],
            high_value_step_up_threshold_usd=300,
        )

    async def _fake_get_delegation(session, delegation_id):
        return None

    monkeypatch.setattr(identity_router, "get_did_document", _fake_get_did)
    monkeypatch.setattr(identity_router, "get_creator_profile", _fake_get_creator)
    monkeypatch.setattr(identity_router, "get_trust_preferences", _fake_get_trust)
    monkeypatch.setattr(identity_router, "get_delegation", _fake_get_delegation)

    payload = {
        "owner_id": "did:seedcore:owner:acme-001",
        "assistant_id": "did:seedcore:assistant:buyer-bot-01",
        "delegation_id": "delegation-123",
        "merchant_ref": "other-merchant.com",
        "declared_value_usd": 420,
        "required_modalities": ["camera", "seal_sensor"],
        "available_modalities": ["camera"],
        "observed_provenance_level": "basic",
        "risk_score": 0.62,
    }
    response = client.post("/api/v1/owner-context/preflight", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "owner_trust_risk_escalation" in body["predicted_policy_signals"]["trust_gap_codes"]
    assert "owner_trust_merchant_violation" in body["predicted_policy_signals"]["trust_gap_codes"]
    assert "owner_trust_provenance_violation" in body["predicted_policy_signals"]["trust_gap_codes"]
    assert "seal_sensor" in body["predicted_policy_signals"]["missing_modalities"]
