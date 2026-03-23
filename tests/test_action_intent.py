from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import mock_ray_dependencies  # noqa: F401
import mock_eventizer_dependencies  # noqa: F401

import seedcore.coordinator.core.governance as governance_mod
from seedcore.coordinator.core.governance import (
    build_action_intent,
    build_governance_context,
    build_twin_snapshot,
    evaluate_intent,
    merge_authoritative_twins,
)


def _base_payload() -> dict:
    return {
        "task_id": "task-1",
        "type": "action",
        "params": {
            "interaction": {"assigned_agent_id": "agent-1"},
            "resource": {"asset_id": "asset-1"},
            "intent": "transport",
            "governance": {
                "action_intent": {
                    "intent_id": "intent-1",
                    "timestamp": "2099-03-20T12:00:00+00:00",
                    "valid_until": "2099-03-20T12:10:00+00:00",
                    "principal": {
                        "agent_id": "agent-1",
                        "role_profile": "ROBOT_OPERATOR",
                        "session_token": "sess-1",
                    },
                    "action": {
                        "type": "MOVE",
                        "parameters": {},
                        "security_contract": {"hash": "h-1", "version": "snapshot:1"},
                    },
                    "resource": {
                        "asset_id": "asset-1",
                        "target_zone": "vault-a",
                        "provenance_hash": "prov-1",
                    },
                }
            },
        },
    }


def _build_actor_token(
    *,
    secret: str,
    subject: str,
    issued_at: datetime,
    expires_at: datetime,
    session_token: str,
    origin_network: str | None = None,
) -> str:
    claims = {
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "session_token": session_token,
    }
    if origin_network is not None:
        claims["origin_network"] = origin_network
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signing_input = f"seedcore_hmac_v1.{payload}".encode("utf-8")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"seedcore_hmac_v1.{payload}.{signature}"


def test_build_twin_snapshot_uses_typed_lifecycle_schema():
    payload = _base_payload()
    payload["params"]["resource"]["parent_twin_id"] = "batch:lot-10"

    snapshots = build_twin_snapshot(payload)

    assert snapshots["owner"].twin_kind == "owner"
    assert snapshots["owner"].revision_stage == "PROPOSED"
    assert snapshots["asset"].twin_kind == "asset"
    assert snapshots["asset"].lifecycle_state == "REGISTERED"
    assert snapshots["asset"].lineage_refs == ["batch:lot-10"]


def test_build_twin_snapshot_emits_batch_and_product_twins_when_ids_are_stable():
    payload = _base_payload()
    payload["params"]["resource"].update(
        {
            "lot_id": "lot-10",
            "batch_twin_id": "batch:lot-10",
            "category_envelope": {"product_id": "product-77"},
        }
    )

    snapshots = build_twin_snapshot(payload)

    assert snapshots["asset"].custody["batch_twin_id"] == "batch:lot-10"
    assert snapshots["asset"].custody["product_id"] == "product-77"
    assert snapshots["batch"].twin_id == "batch:lot-10"
    assert snapshots["batch"].lineage_refs == ["product:product-77"]
    assert snapshots["product"].twin_id == "product:product-77"


def test_evaluate_intent_denies_stale_twin_state():
    payload = _base_payload()
    payload["params"]["governance"]["digital_twins"] = {
        "asset": {
            "twin_kind": "asset",
            "twin_id": "asset:asset-1",
            "freshness": {"status": "stale"},
        }
    }

    decision = evaluate_intent(payload)
    assert decision.allowed is False
    assert decision.deny_code == "stale_twin_state"


def test_build_governance_context_emits_signed_policy_receipt():
    payload = _base_payload()

    governance = build_governance_context(payload)

    assert governance["policy_receipt"]["policy_receipt_id"]
    assert governance["policy_receipt"]["policy_decision_id"]
    assert governance["policy_receipt"]["signer_metadata"]["signing_scheme"] == "hmac_sha256"
    assert governance["policy_receipt"]["signature"]
    assert governance["execution_token"]["token_id"]
    assert governance["execution_token"]["contract_version"]


def test_merge_authoritative_twins_overrides_untrusted_data():
    payload = _base_payload()
    payload["params"]["governance"]["digital_twins"] = {
        "assistant": {
            "twin_kind": "assistant",
            "twin_id": "assistant:agent-1",
            "delegation": {"revoked": False, "role_profile": "admin"},
        },
        "asset": {
            "twin_kind": "asset",
            "twin_id": "asset:asset-1",
            "custody": {"quarantined": False, "target_zone": "vault-a"},
        },
    }

    baseline = build_twin_snapshot(payload)
    merged = merge_authoritative_twins(
        baseline,
        {
            "agents": {"agent-1": {"is_revoked": True, "role_profile": "guest", "risk_score": 0.91}},
            "assets": {"asset-1": {"is_quarantined": True, "current_zone": "quarantine-lab"}},
        },
    )

    assert merged["assistant"].delegation["revoked"] is True
    assert merged["assistant"].delegation["role_profile"] == "guest"
    assert merged["assistant"].risk["score"] == pytest.approx(0.91)
    assert merged["asset"].custody["quarantined"] is True
    assert merged["asset"].custody["target_zone"] == "quarantine-lab"


def test_build_action_intent_uses_embedded_payload_as_canonical():
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"]["resource"]["resource_uri"] = (
        "seedcore://node-cluster-alpha/memory-bank/4"
    )
    payload["params"]["governance"]["action_intent"]["environment"] = {
        "origin_network": "mesh://lab-a"
    }

    action_intent = build_action_intent(payload)

    assert action_intent.intent_id == "intent-1"
    assert action_intent.principal.agent_id == "agent-1"
    assert action_intent.resource.resource_uri == "seedcore://node-cluster-alpha/memory-bank/4"
    assert action_intent.environment.origin_network == "mesh://lab-a"


def test_evaluate_intent_denies_stale_timestamp_when_window_enabled(monkeypatch):
    payload = _base_payload()
    monkeypatch.setenv("SEEDCORE_PDP_MAX_INTENT_AGE_MS", "500")
    monkeypatch.setattr(
        governance_mod,
        "_utcnow",
        lambda: datetime(2099, 3, 20, 12, 0, 1, tzinfo=timezone.utc),
    )

    decision = evaluate_intent(payload)

    assert decision.allowed is False
    assert decision.deny_code == "stale_intent"


def test_evaluate_intent_allows_valid_actor_token(monkeypatch):
    payload = _base_payload()
    issued_at = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    actor_secret = "actor-secret"
    payload["params"]["governance"]["action_intent"]["environment"] = {
        "origin_network": "mesh://lab-a"
    }
    payload["params"]["governance"]["action_intent"]["principal"]["actor_token"] = _build_actor_token(
        secret=actor_secret,
        subject="agent-1",
        issued_at=issued_at,
        expires_at=datetime(2099, 3, 20, 12, 0, 5, tzinfo=timezone.utc),
        session_token="sess-1",
        origin_network="mesh://lab-a",
    )

    monkeypatch.setenv("SEEDCORE_PDP_ACTOR_TOKEN_SECRET", actor_secret)
    monkeypatch.setattr(governance_mod, "_utcnow", lambda: issued_at)

    decision = evaluate_intent(payload)

    assert decision.allowed is True
    assert decision.execution_token is not None
