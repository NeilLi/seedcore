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
from seedcore.api.external_authority import OwnerPolicyRecord


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(identity_router.router, prefix="/api/v1", tags=["Identity"])
    return TestClient(app)


def test_owner_policy_upsert_and_get(monkeypatch):
    client = _make_client()

    async def _fake_upsert(session, payload):
        return OwnerPolicyRecord(
            owner_id=payload.owner_id,
            policy_id=payload.policy_id,
            policy_version=payload.policy_version,
            status=payload.status,
            default_disposition=payload.default_disposition,
            allowed_categories=payload.allowed_categories,
            denied_categories=payload.denied_categories,
            spend_controls=payload.spend_controls,
            merchant_rules=payload.merchant_rules,
            publishing_rules=payload.publishing_rules,
            approval_chains=payload.approval_chains,
            delegated_assistants=payload.delegated_assistants,
            updated_by=payload.updated_by,
            metadata=payload.metadata,
        )

    async def _fake_get(session, owner_id):
        return OwnerPolicyRecord(
            owner_id=owner_id,
            policy_id="owner-policy-acme-main",
            policy_version="v2",
            status="SUPERSEDED",
            default_disposition="DENY",
            updated_by="policy_assistant",
        )

    monkeypatch.setattr(identity_router, "upsert_owner_policy", _fake_upsert)
    monkeypatch.setattr(identity_router, "get_owner_policy", _fake_get)

    payload = {
        "owner_id": "did:seedcore:owner:acme-001",
        "policy_id": "owner-policy-acme-main",
        "policy_version": "v1",
        "status": "ACTIVE",
        "default_disposition": "DENY",
        "allowed_categories": ["electronics"],
        "denied_categories": ["weapons"],
        "updated_by": "policy_assistant",
    }
    upsert = client.post("/api/v1/owner-policies", json=payload)
    assert upsert.status_code == 200
    assert upsert.json()["policy_id"] == "owner-policy-acme-main"
    assert upsert.json()["policy_version"] == "v1"

    fetched = client.get("/api/v1/owner-policies/did:seedcore:owner:acme-001")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "SUPERSEDED"
    assert fetched.json()["policy_version"] == "v2"
