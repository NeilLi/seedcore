from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.services.mutation_receipt_service import mutation_receipt_service


def test_build_and_verify_mutation_receipt() -> None:
    receipt = mutation_receipt_service.build_signed_receipt(
        receipt_kind="identity.upsert_owner_policy",
        intent_id="identity:upsert_owner_policy:did:seedcore:owner:test-1",
        token_id="tok-identity-test-1",
        actor_ref="did:seedcore:assistant:test-1",
        target_ref="did:seedcore:owner:test-1",
        mutation_payload={"owner_id": "did:seedcore:owner:test-1", "policy_version": "v1"},
        snapshot_id=7,
    )
    result = mutation_receipt_service.verify_signed_receipt(receipt)
    assert result.get("verified") is True


def test_mutation_receipt_verification_fails_on_payload_tamper() -> None:
    receipt = mutation_receipt_service.build_signed_receipt(
        receipt_kind="tracking.create_event",
        intent_id="tracking:create:event-1",
        token_id="tok-tracking-test-1",
        actor_ref="sensor-hub",
        target_ref="event-1",
        mutation_payload={"event_type": "environmental_reading_recorded", "value": 42},
    )
    tampered = dict(receipt)
    tampered["payload_hash"] = "sha256:forged"
    result = mutation_receipt_service.verify_signed_receipt(tampered)
    assert result.get("verified") is False
