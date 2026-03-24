#!/usr/bin/env python3
"""Verify external identity surface, audit emission, and legacy evidence compatibility."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
TESTS_ROOT = PROJECT_ROOT / "tests"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

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


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: dict


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
        intent_id="intent-final-ext",
        timestamp="2026-03-20T00:00:00Z",
        valid_until="2026-03-20T00:05:00Z",
        principal=IntentPrincipal(agent_id="did:seedcore:assistant:test-agent", role_profile="signer", session_token="session-1"),
        action=IntentAction(type="RELEASE", parameters={"asset_id": "asset-1"}, security_contract=SecurityContract(hash="abc123", version="rules@1")),
        resource=IntentResource(asset_id="asset-1", target_zone="zone-a", provenance_hash="prov-1"),
    )


async def _run() -> int:
    results: list[CheckResult] = []

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
    results.append(
        CheckResult(
            "external.did_and_delegation_apis_defined",
            did.did.startswith("did:") and delegation.status == "ACTIVE",
            {"did": did.did, "delegation_status": delegation.status, "authority_level": delegation.authority_level},
        )
    )

    private_key = Ed25519PrivateKey.generate()
    public_key = base64.b64encode(
        private_key.public_key().public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
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

    with patch.object(ext, "get_did_document", _fake_get_did_document), \
         patch.object(ext, "_record_nonce_once", _fake_record_nonce_once), \
         patch.object(ext, "utcnow", lambda: datetime(2026, 3, 20, 0, 0, 5, tzinfo=timezone.utc)):
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

    with patch.object(ext, "get_did_document", _fake_get_did_document_hmac), \
         patch.object(ext, "_record_nonce_once", _fake_record_nonce_once_hmac), \
         patch.object(ext, "utcnow", lambda: datetime(2026, 3, 20, 0, 0, 1, tzinfo=timezone.utc)), \
         patch.dict("os.environ", {"SEEDCORE_EXTERNAL_INTENT_HMAC_SECRETS_JSON": '{"did:seedcore:assistant:test-agent":"dev-secret"}'}, clear=False):
        hmac_ok, hmac_error, _ = await ext.verify_signed_intent_submission(
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
    results.append(
        CheckResult(
            "external.signed_intents_supported",
            verified is True and error is None and hmac_ok is True and replayed is False and replay_error == "replayed_nonce",
            {"ed25519_verified": verified, "hmac_verified": hmac_ok, "replay_error": replay_error},
        )
    )

    coordinator_cls = getattr(cs.Coordinator, "func_or_class", cs.Coordinator)
    with patch.object(coordinator_cls, "__init__", return_value=None):
        coordinator = coordinator_cls.__new__(coordinator_cls)
    coordinator._session_factory = _session_factory
    coordinator.governance_audit_dao = SimpleNamespace(
        append_record=AsyncMock(
            return_value={
                "entry_id": "audit-final",
                "recorded_at": "2026-03-23T04:16:27+00:00",
                "input_hash": "hash-final",
                "evidence_hash": None,
            }
        )
    )
    governance = {
        "action_intent": {
            "intent_id": "intent-final-audit",
            "principal": {"agent_id": "agent-10", "role_profile": "CARRIER"},
            "action": {"type": "MOVE", "operation": "MOVE"},
            "resource": {"asset_id": "asset-22", "resource_uri": "seedcore://zones/vault-a/assets/asset-22", "target_zone": "vault-a"},
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
    _, kwargs = mock_record_event.await_args
    results.append(
        CheckResult(
            "external.audit_receipts_emitted",
            kwargs["event_type"] == TrackingEventType.POLICY_DECISION_RECORDED
            and kwargs["payload"]["governance_audit"]["entry_id"] == "audit-final"
            and kwargs["payload"]["governed_receipt"]["decision_hash"] == "receipt-22",
            {
                "event_type": kwargs["event_type"],
                "entry_id": kwargs["payload"]["governance_audit"]["entry_id"],
                "decision_hash": kwargs["payload"]["governed_receipt"]["decision_hash"],
            },
        )
    )

    legacy = {
        "telemetry_snapshot": {"zone_checks": {"current_zone": "packing-cell-2"}},
        "execution_receipt": {"actuator_endpoint": "robot_sim://asset-7", "signature": "sig-legacy"},
    }
    results.append(
        CheckResult(
            "external.legacy_evidence_compatibility",
            "telemetry_snapshot" in legacy and "execution_receipt" in legacy and legacy["execution_receipt"]["actuator_endpoint"].startswith("robot_sim://"),
            {"keys": sorted(legacy.keys()), "endpoint": legacy["execution_receipt"]["actuator_endpoint"]},
        )
    )

    failing = [result for result in results if not result.ok]
    for result in results:
        marker = "PASS" if result.ok else "FAIL"
        print(f"[{marker}] {result.name}: {json.dumps(result.detail, sort_keys=True)}")

    if failing:
        print(f"\nExternal surface verification failed: {len(failing)} checks failed.", file=sys.stderr)
        return 1
    print("\nExternal surface verification passed.")
    return 0


if __name__ == "__main__":
    import asyncio

    raise SystemExit(asyncio.run(_run()))
