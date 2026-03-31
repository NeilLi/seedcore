from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from seedcore.api import external_authority as ext
from seedcore.models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)


def _sample_intent() -> ActionIntent:
    return ActionIntent(
        intent_id="intent-123",
        timestamp="2026-03-20T00:00:00Z",
        valid_until="2026-03-20T00:05:00Z",
        principal=IntentPrincipal(
            agent_id="did:seedcore:assistant:test-agent",
            role_profile="signer",
            session_token="session-1",
        ),
        action=IntentAction(
            type="RELEASE",
            parameters={"asset_id": "asset-1"},
            security_contract=SecurityContract(hash="abc123", version="rules@1"),
        ),
        resource=IntentResource(
            asset_id="asset-1",
            target_zone="zone-a",
            provenance_hash="prov-1",
        ),
    )


@pytest.mark.asyncio
async def test_verify_signed_intent_submission_ed25519(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )
    ).decode("ascii")
    intent = _sample_intent()
    signed_at = "2026-03-20T00:00:00Z"
    payload = ext.build_external_intent_signing_payload(
        intent,
        nonce="nonce-1",
        signed_at=signed_at,
    )
    payload_hash = ext.sha256_hex(ext.canonical_json(payload))
    signature = base64.b64encode(
        private_key.sign(payload_hash.encode("utf-8"))
    ).decode("ascii")

    async def _fake_get_did_document(session, did):
        return ext.DIDDocumentRecord(
            did=did,
            verification_method=ext.DIDVerificationMethod(
                signing_scheme="ed25519",
                public_key=public_key,
                key_ref="k1",
            ),
        )

    async def _fake_record_nonce_once(*, signer_did, nonce, ttl_seconds):
        return None

    monkeypatch.setattr(ext, "get_did_document", _fake_get_did_document)
    monkeypatch.setattr(ext, "_record_nonce_once", _fake_record_nonce_once)
    monkeypatch.setattr(ext, "utcnow", lambda: datetime(2026, 3, 20, 0, 0, 5, tzinfo=timezone.utc))

    verified, error, document = await ext.verify_signed_intent_submission(
        session=object(),
        submission=ext.SignedIntentSubmissionRequest(
            action_intent=intent,
            signature=signature,
            signer_did=intent.principal.agent_id,
            signing_scheme="ed25519",
            key_ref="k1",
            nonce="nonce-1",
            signed_at=signed_at,
        ),
    )

    assert verified is True
    assert error is None
    assert document is not None
    assert document.did == intent.principal.agent_id


@pytest.mark.asyncio
async def test_verify_signed_intent_submission_hmac_and_replay(monkeypatch):
    intent = _sample_intent()
    signed_at = "2026-03-20T00:00:00Z"
    payload = ext.build_external_intent_signing_payload(
        intent,
        nonce="nonce-2",
        signed_at=signed_at,
    )
    payload_hash = ext.sha256_hex(ext.canonical_json(payload))
    secret = "dev-secret"
    signature = hmac.new(
        secret.encode("utf-8"),
        payload_hash.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    async def _fake_get_did_document(session, did):
        return ext.DIDDocumentRecord(
            did=did,
            verification_method=ext.DIDVerificationMethod(
                signing_scheme="hmac_sha256",
                key_ref="shared-key",
            ),
        )

    calls = {"count": 0}

    async def _fake_record_nonce_once(*, signer_did, nonce, ttl_seconds):
        calls["count"] += 1
        if calls["count"] > 1:
            return "replayed_nonce"
        return None

    monkeypatch.setattr(ext, "get_did_document", _fake_get_did_document)
    monkeypatch.setattr(ext, "_record_nonce_once", _fake_record_nonce_once)
    monkeypatch.setattr(ext, "utcnow", lambda: datetime(2026, 3, 20, 0, 0, 1, tzinfo=timezone.utc))
    monkeypatch.setenv(
        "SEEDCORE_EXTERNAL_INTENT_HMAC_SECRETS_JSON",
        '{"did:seedcore:assistant:test-agent":"dev-secret"}',
    )

    submission = ext.SignedIntentSubmissionRequest(
        action_intent=intent,
        signature=signature,
        signer_did=intent.principal.agent_id,
        signing_scheme="hmac_sha256",
        key_ref="shared-key",
        nonce="nonce-2",
        signed_at=signed_at,
    )

    verified, error, _ = await ext.verify_signed_intent_submission(object(), submission)
    assert verified is True
    assert error is None

    replayed, replay_error, _ = await ext.verify_signed_intent_submission(object(), submission)
    assert replayed is False
    assert replay_error == "replayed_nonce"


@pytest.mark.asyncio
async def test_build_owner_twin_snapshot_includes_provenance_source_and_signer_metadata(monkeypatch):
    async def _fake_get_did_document(session, did):
        return ext.DIDDocumentRecord(
            did=did,
            verification_method=ext.DIDVerificationMethod(
                signing_scheme="ed25519",
                key_ref="owner-k1",
            ),
        )

    async def _fake_list_owner_delegations(session, owner_id):
        return []

    async def _fake_get_creator_profile(session, owner_id):
        return ext.CreatorProfileRecord(
            owner_id=owner_id,
            version="v2",
            updated_by="identity_router",
        )

    async def _fake_get_trust_preferences(session, owner_id):
        return ext.TrustPreferencesRecord(
            owner_id=owner_id,
            trust_version="v3",
            updated_by="identity_router",
        )

    monkeypatch.setattr(ext, "get_did_document", _fake_get_did_document)
    monkeypatch.setattr(ext, "_list_owner_delegations", _fake_list_owner_delegations)
    monkeypatch.setattr(ext, "get_creator_profile", _fake_get_creator_profile)
    monkeypatch.setattr(ext, "get_trust_preferences", _fake_get_trust_preferences)

    snapshot = await ext.build_owner_twin_snapshot(object(), "did:seedcore:owner:test-owner")
    creator_ref = snapshot.provenance["creator_profile_ref"]
    trust_ref = snapshot.provenance["trust_preferences_ref"]

    assert creator_ref["source_namespace"] == "identity"
    assert creator_ref["source_predicate"] == "creator_profile"
    assert creator_ref["updated_by"] == "identity_router"
    assert creator_ref["signer_did"] == "did:seedcore:owner:test-owner"
    assert creator_ref["signer_key_ref"] == "owner-k1"
    assert trust_ref["source_namespace"] == "identity"
    assert trust_ref["source_predicate"] == "trust_preferences"
    assert trust_ref["updated_by"] == "identity_router"
    assert trust_ref["signer_did"] == "did:seedcore:owner:test-owner"
    assert trust_ref["signer_key_ref"] == "owner-k1"
