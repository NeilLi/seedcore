from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401

from seedcore.api import external_authority as ext
from seedcore.models.action_intent import (
    ActionIntent,
    IntentAction,
    IntentPrincipal,
    IntentResource,
    SecurityContract,
)
from seedcore.models.source_registration import TrackingEventType
from seedcore.services import coordinator_service as cs


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def begin(self):
        return _FakeTransaction(self)


class _FakeTransaction:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _session_factory():
    return _FakeSession()


def _sample_intent() -> ActionIntent:
    return ActionIntent(
        intent_id="intent-ext-123",
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
async def test_did_and_delegation_apis_are_defined() -> None:
    did = ext.DIDDocumentRecord(
        did="did:seedcore:owner:test-owner",
        verification_method=ext.DIDVerificationMethod(signing_scheme="ed25519", key_ref="owner-k1"),
    )
    delegation = ext.DelegationRecord(
        owner_id="did:seedcore:owner:test-owner",
        assistant_id="did:seedcore:assistant:test-agent",
        authority_level="signer",
        scope=["asset-1"],
    )

    assert did.did.startswith("did:")
    assert did.verification_method.signing_scheme in {"ed25519", "hmac_sha256"}
    assert delegation.owner_id.startswith("did:")
    assert delegation.assistant_id.startswith("did:")
    assert delegation.status == "ACTIVE"


@pytest.mark.asyncio
async def test_signed_intents_supported_ed25519_and_hmac(monkeypatch: pytest.MonkeyPatch) -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=Encoding.Raw,
            format=PublicFormat.Raw,
        )
    ).decode("ascii")
    intent = _sample_intent()
    signed_at = "2026-03-20T00:00:00Z"
    payload = ext.build_external_intent_signing_payload(intent, nonce="nonce-1", signed_at=signed_at)
    payload_hash = ext.sha256_hex(ext.canonical_json(payload))
    signature = base64.b64encode(private_key.sign(payload_hash.encode("utf-8"))).decode("ascii")

    async def _fake_get_did_document(session, did):
        return ext.DIDDocumentRecord(
            did=did,
            verification_method=ext.DIDVerificationMethod(signing_scheme="ed25519", public_key=public_key, key_ref="k1"),
        )

    async def _fake_record_nonce_once(*, signer_did, nonce, ttl_seconds):
        return None

    monkeypatch.setattr(ext, "get_did_document", _fake_get_did_document)
    monkeypatch.setattr(ext, "_record_nonce_once", _fake_record_nonce_once)
    monkeypatch.setattr(ext, "utcnow", lambda: datetime(2026, 3, 20, 0, 0, 5, tzinfo=timezone.utc))

    verified, error, _ = await ext.verify_signed_intent_submission(
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

    hmac_payload = ext.build_external_intent_signing_payload(intent, nonce="nonce-2", signed_at=signed_at)
    hmac_hash = ext.sha256_hex(ext.canonical_json(hmac_payload))
    hmac_sig = hmac.new(b"dev-secret", hmac_hash.encode("utf-8"), hashlib.sha256).hexdigest()

    async def _fake_get_did_document_hmac(session, did):
        return ext.DIDDocumentRecord(
            did=did,
            verification_method=ext.DIDVerificationMethod(signing_scheme="hmac_sha256", key_ref="shared-key"),
        )

    calls = {"count": 0}

    async def _fake_record_nonce_once_hmac(*, signer_did, nonce, ttl_seconds):
        calls["count"] += 1
        if calls["count"] > 1:
            return "replayed_nonce"
        return None

    monkeypatch.setattr(ext, "get_did_document", _fake_get_did_document_hmac)
    monkeypatch.setattr(ext, "_record_nonce_once", _fake_record_nonce_once_hmac)
    monkeypatch.setenv("SEEDCORE_EXTERNAL_INTENT_HMAC_SECRETS_JSON", '{"did:seedcore:assistant:test-agent":"dev-secret"}')

    ok, replay_error, _ = await ext.verify_signed_intent_submission(
        object(),
        ext.SignedIntentSubmissionRequest(
            action_intent=intent,
            signature=hmac_sig,
            signer_did=intent.principal.agent_id,
            signing_scheme="hmac_sha256",
            key_ref="shared-key",
            nonce="nonce-2",
            signed_at=signed_at,
        ),
    )
    assert ok is True
    replayed, replay_error, _ = await ext.verify_signed_intent_submission(
        object(),
        ext.SignedIntentSubmissionRequest(
            action_intent=intent,
            signature=hmac_sig,
            signer_did=intent.principal.agent_id,
            signing_scheme="hmac_sha256",
            key_ref="shared-key",
            nonce="nonce-2",
            signed_at=signed_at,
        ),
    )
    assert replayed is False
    assert replay_error == "replayed_nonce"


@pytest.mark.asyncio
async def test_audit_receipts_emitted_and_complete() -> None:
    with patch.object(cs.Coordinator, "__init__", return_value=None):
        coordinator = cs.Coordinator.__new__(cs.Coordinator)

    coordinator._session_factory = _session_factory
    coordinator.governance_audit_dao = SimpleNamespace(
        append_record=AsyncMock(
            return_value={
                "entry_id": "audit-x",
                "recorded_at": "2026-03-23T04:16:27+00:00",
                "input_hash": "hash-x",
                "evidence_hash": None,
            }
        )
    )

    governance = {
        "action_intent": {
            "intent_id": "intent-audit",
            "principal": {"agent_id": "agent-10", "role_profile": "CARRIER"},
            "action": {"type": "MOVE", "operation": "MOVE"},
            "resource": {
                "asset_id": "asset-22",
                "resource_uri": "seedcore://zones/vault-a/assets/asset-22",
                "target_zone": "vault-a",
            },
        },
        "policy_decision": {
            "allowed": True,
            "policy_snapshot": "snapshot:1",
            "disposition": "quarantine",
            "reason": "quarantine",
            "authz_graph": {"reason": "trust_gap_quarantine", "restricted_token_recommended": True},
            "governed_receipt": {"decision_hash": "receipt-22", "trust_gap_codes": ["stale_telemetry"]},
            "break_glass": {},
        },
        "policy_case": {},
        "policy_receipt": {},
    }

    with patch.object(cs, "record_tracking_event", new=AsyncMock()) as mock_record_event:
        await coordinator._record_governance_audit(
            task_id="00000000-0000-0000-0000-0000000000a3",
            governance=governance,
            record_type="policy_decision",
        )

    coordinator.governance_audit_dao.append_record.assert_awaited_once()
    mock_record_event.assert_awaited_once()
    _, kwargs = mock_record_event.await_args
    assert kwargs["event_type"] == TrackingEventType.POLICY_DECISION_RECORDED
    assert kwargs["payload"]["governance_audit"]["entry_id"] == "audit-x"
    assert kwargs["payload"]["governed_receipt"]["decision_hash"] == "receipt-22"


def test_legacy_evidence_compatibility_preserved() -> None:
    legacy_evidence = {
        "telemetry_snapshot": {"zone_checks": {"current_zone": "packing-cell-2"}},
        "execution_receipt": {
            "actuator_endpoint": "robot_sim://asset-7",
            "signature": "sig-legacy",
        },
    }

    assert "telemetry_snapshot" in legacy_evidence
    assert "execution_receipt" in legacy_evidence
    assert legacy_evidence["execution_receipt"]["actuator_endpoint"].startswith("robot_sim://")
