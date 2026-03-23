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
from seedcore.ops.pkg.authz_graph import AuthzDecisionDisposition, AuthzGraphCompiler, AuthzGraphProjector


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


def _build_break_glass_token(
    *,
    secret: str,
    subject: str,
    issued_at: datetime,
    expires_at: datetime,
    require_reason: bool = True,
) -> str:
    claims = {
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "require_reason": require_reason,
    }
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signing_input = f"seedcore_break_glass_v1.{payload}".encode("utf-8")
    signature = base64.urlsafe_b64encode(
        hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    return f"seedcore_break_glass_v1.{payload}.{signature}"


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


def test_evaluate_intent_allows_when_compiled_authz_graph_matches():
    payload = _base_payload()
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    payload["params"]["governance"]["action_intent"]["resource"]["resource_uri"] = (
        canonical_resource_uri
    )
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
                {
                    "id": "fact-zone",
                    "snapshot_id": 1,
                    "namespace": "authz",
                    "subject": canonical_resource_uri,
                    "predicate": "locatedInZone",
                    "object_data": {"zone": "vault-a"},
                },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                    "subject": "role:ROBOT_OPERATOR",
                    "predicate": "allowedOperation",
                    "object_data": {
                        "operation": "MUTATE",
                        "resource": canonical_resource_uri,
                        "zones": ["vault-a"],
                    },
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert decision.execution_token is not None


def test_evaluate_intent_denies_when_compiled_authz_graph_has_no_permission():
    payload = _base_payload()
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "authz_graph_denied"


def test_evaluate_intent_denies_when_compiled_authz_snapshot_mismatches():
    payload = _base_payload()
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:other",
        facts=[],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "authz_graph_snapshot_mismatch"


def test_evaluate_intent_denies_when_break_glass_is_required_but_missing():
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"]["resource"]["resource_uri"] = (
        "seedcore://zones/vault-a/assets/asset-1"
    )
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        policy_edge_manifests=[
            {
                "source_selector": "principal:agent-1",
                "target_selector": "seedcore://zones/vault-a/assets/asset-1",
                "relationship": "can_bypass",
                "operation": "MUTATE",
                "conditions": {"requires_break_glass": True, "bypass_deny": True, "zones": ["vault-a"]},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "authz_graph_denied"
    assert any("compiled_authz_result=break_glass_required" in item for item in decision.explanations)
    assert decision.break_glass.present is False
    assert decision.break_glass.required is True
    assert decision.break_glass.outcome == "break_glass_required"


def test_evaluate_intent_allows_break_glass_override_with_valid_token(monkeypatch):
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"]["resource"]["resource_uri"] = (
        "seedcore://zones/vault-a/assets/asset-1"
    )
    issued_at = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    break_glass_secret = "break-glass-secret"
    payload["params"]["governance"]["action_intent"]["environment"] = {
        "break_glass_token": _build_break_glass_token(
            secret=break_glass_secret,
            subject="agent-1",
            issued_at=issued_at,
            expires_at=datetime(2099, 3, 20, 12, 0, 5, tzinfo=timezone.utc),
        ),
        "break_glass_reason": "operator approved emergency release",
    }
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        policy_edge_manifests=[
            {
                "source_selector": "principal:agent-1",
                "target_selector": "seedcore://zones/vault-a/assets/asset-1",
                "relationship": "can",
                "operation": "MUTATE",
                "effect": "deny",
                "conditions": {"zones": ["vault-a"]},
            },
            {
                "source_selector": "principal:agent-1",
                "target_selector": "seedcore://zones/vault-a/assets/asset-1",
                "relationship": "can_bypass",
                "operation": "MUTATE",
                "conditions": {"requires_break_glass": True, "bypass_deny": True, "zones": ["vault-a"]},
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", break_glass_secret)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert decision.execution_token is not None
    assert decision.break_glass.present is True
    assert decision.break_glass.validated is True
    assert decision.break_glass.used is True
    assert decision.break_glass.override_applied is True
    assert decision.break_glass.outcome == "break_glass_override"


def test_evaluate_intent_denies_invalid_break_glass_token(monkeypatch):
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"]["resource"]["resource_uri"] = (
        "seedcore://zones/vault-a/assets/asset-1"
    )
    payload["params"]["governance"]["action_intent"]["environment"] = {
        "break_glass_token": "seedcore_break_glass_v1.invalid.invalid",
        "break_glass_reason": "operator approved emergency release",
    }
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        policy_edge_manifests=[
            {
                "source_selector": "principal:agent-1",
                "target_selector": "seedcore://zones/vault-a/assets/asset-1",
                "relationship": "can_bypass",
                "operation": "MUTATE",
                "conditions": {"requires_break_glass": True, "bypass_deny": True, "zones": ["vault-a"]},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", "break-glass-secret")

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "invalid_break_glass_token"
    assert decision.break_glass.present is True
    assert decision.break_glass.validated is False
    assert decision.break_glass.outcome == "verification_failed"


def test_evaluate_intent_quarantines_when_transition_has_trust_gap(monkeypatch):
    payload = _base_payload()
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": canonical_resource_uri,
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                    "max_telemetry_age_seconds": 300,
                    "require_attestation": True,
                    "require_seal": True,
                    "allow_quarantine": True,
                },
                "valid_from": "2099-03-20T11:50:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {
                    "custodian": "agent-1",
                    "transferable": True,
                },
                "valid_from": "2099-03-20T11:55:00+00:00",
                "valid_to": "2099-03-20T12:20:00+00:00",
            },
            {
                "id": "fact-attest",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "attestedBy",
                "object_data": {
                    "attestation_id": "attest-1",
                    "attestor": "lab-1",
                    "valid_from": "2099-03-19T12:00:00+00:00",
                    "valid_to": "2099-03-21T12:00:00+00:00",
                },
            },
            {
                "id": "fact-seal",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "sealedWith",
                "object_data": {"seal_id": "seal-1"},
            },
            {
                "id": "fact-telemetry",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "observedIn",
                "object_data": {
                    "observation_id": "obs-1",
                    "measurement_type": "temperature",
                    "quality_score": 0.88,
                    "observed_at": "2099-03-20T11:30:00+00:00",
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert decision.disposition == "quarantine"
    assert decision.execution_token is not None
    assert decision.execution_token.constraints["authz_disposition"] == "quarantine"
    assert decision.execution_token.constraints["restricted_state"] is True
    assert decision.governed_receipt["disposition"] == "quarantine"
    assert decision.authz_graph["mode"] == "transition_evaluation"
    assert any(item["code"] == "stale_telemetry" for item in decision.authz_graph["trust_gaps"])


def test_evaluate_intent_denies_when_transition_custody_mismatch(monkeypatch):
    payload = _base_payload()
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@test",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-role",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "hasRole",
                "object_data": {"role": "ROBOT_OPERATOR"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": canonical_resource_uri,
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                },
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {
                    "custodian": "agent-2",
                    "transferable": True,
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "authz_graph_denied"
    assert decision.disposition == "deny"
    assert decision.governed_receipt["disposition"] == AuthzDecisionDisposition.DENY.value
    assert decision.authz_graph["mode"] == "transition_evaluation"
    assert decision.authz_graph["reason"] == "principal_not_current_custodian"
