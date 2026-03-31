from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone

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
from seedcore.ops.pkg.authz_graph import (
    AuthzDecisionDisposition,
    AuthzGraphCompiler,
    AuthzGraphProjector,
    CompiledPermissionMatch,
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


def _transfer_payload() -> dict:
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"] = {
        "intent_id": "intent-transfer-1",
        "timestamp": "2099-03-20T12:00:00+00:00",
        "valid_until": "2099-03-20T12:10:00+00:00",
        "principal": {
            "agent_id": "agent-1",
            "role_profile": "TRANSFER_COORDINATOR",
            "session_token": "sess-transfer-1",
        },
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "approval_context": {
                    "approval_envelope_id": "approval-transfer-001",
                    "approval_envelope_version": 1,
                    "observed_version": 1,
                    "required_roles": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
                    "approved_by": [
                        "principal:facility_mgr_001",
                        "principal:quality_insp_017",
                    ],
                }
            },
            "security_contract": {"hash": "h-transfer-1", "version": "snapshot:1"},
        },
        "resource": {
            "asset_id": "asset-1",
            "resource_uri": "seedcore://zones/handoff-bay-3/assets/asset-1",
            "target_zone": "handoff-bay-3",
            "provenance_hash": "prov-transfer-1",
            "lot_id": "lot-8841",
            "category_envelope": {
                "transfer_context": {
                    "from_zone": "vault-a",
                    "to_zone": "handoff-bay-3",
                    "facility_ref": "facility:north-warehouse",
                    "custody_point_ref": "custody_point:handoff-bay-3",
                    "expected_current_custodian": "principal:facility_mgr_001",
                    "next_custodian": "principal:outbound_mgr_002",
                }
            },
        },
        "environment": {"origin_network": "network:warehouse-core"},
    }
    return payload


def _transfer_approval_envelope(
    *,
    status: str = "APPROVED",
    quality_inspector_status: str = "APPROVED",
    version: int = 1,
) -> dict:
    return {
        "approval_envelope_id": "approval-transfer-001",
        "workflow_type": "custody_transfer",
        "status": status,
        "asset_ref": "asset-1",
        "lot_id": "lot-8841",
        "from_custodian_ref": "principal:facility_mgr_001",
        "to_custodian_ref": "principal:outbound_mgr_002",
        "transfer_context": {
            "from_zone": "vault-a",
            "to_zone": "handoff-bay-3",
            "facility_ref": "facility:north-warehouse",
            "custody_point_ref": "custody_point:handoff-bay-3",
        },
        "required_approvals": [
            {
                "role": "FACILITY_MANAGER",
                "principal_ref": "principal:facility_mgr_001",
                "status": "APPROVED",
                "approved_at": "2099-03-20T11:59:00+00:00",
                "approval_ref": "approval:facility_mgr_001",
            },
            {
                "role": "QUALITY_INSPECTOR",
                "principal_ref": "principal:quality_insp_017",
                "status": quality_inspector_status,
                "approved_at": (
                    "2099-03-20T11:59:30+00:00"
                    if quality_inspector_status == "APPROVED"
                    else None
                ),
                "approval_ref": "approval:quality_insp_017",
            },
        ],
        "policy_snapshot_ref": "snapshot:1",
        "expires_at": "2099-03-20T12:10:00+00:00",
        "created_at": "2099-03-20T11:58:00+00:00",
        "version": version,
    }


def _compiled_transfer_graph(*, now: datetime, telemetry_at: datetime, inspection_at: datetime, current_custodian: str):
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@transfer",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-delegated-by",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "delegatedBy",
                "object_data": {"org": "acme-logistics"},
            },
            {
                "id": "fact-facility",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "org:acme-logistics",
                "predicate": "approvedForFacility",
                "object_data": {"facility_id": "north-warehouse"},
            },
            {
                "id": "fact-zone-control",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "facility:north-warehouse",
                "predicate": "controlsZone",
                "object_data": {"zone": "handoff-bay-3"},
            },
            {
                "id": "fact-lot-location",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "seedcore://zones/handoff-bay-3/assets/asset-1",
                "predicate": "locatedInZone",
                "object_data": {"zone": "handoff-bay-3"},
            },
            {
                "id": "fact-transfer-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "zone:handoff-bay-3",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "TRANSFER_CUSTODY",
                    "resource": "seedcore://zones/handoff-bay-3/assets/asset-1",
                    "zones": ["handoff-bay-3"],
                    "required_transferable_state": True,
                    "max_telemetry_age_seconds": 300,
                    "max_inspection_age_seconds": 3600,
                    "allow_quarantine": True,
                },
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {
                    "custodian": current_custodian,
                    "transferable": True,
                    "custody_point": "handoff-bay-3",
                    "zone": "handoff-bay-3",
                    "lot_id": "lot-8841",
                },
            },
            {
                "id": "fact-telemetry",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "observedIn",
                "object_data": {
                    "observation_id": "obs-transfer-1",
                    "measurement_type": "temperature",
                    "observed_at": telemetry_at.isoformat(),
                    "custody_point": "handoff-bay-3",
                },
            },
            {
                "id": "fact-attestation",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "attestedBy",
                "object_data": {
                    "attestation_id": "inspection-transfer-1",
                    "attestor": "lab-1",
                    "valid_from": inspection_at.isoformat(),
                    "valid_to": inspection_at.isoformat(),
                },
            },
        ],
    )
    return AuthzGraphCompiler().compile(graph)


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
    extra_claims: dict | None = None,
) -> str:
    claims = {
        "sub": subject,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
        "require_reason": require_reason,
    }
    if isinstance(extra_claims, dict):
        claims.update(extra_claims)
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


def test_build_governance_context_carries_governed_receipt_hash_into_policy_receipt(monkeypatch):
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
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": "seedcore://zones/vault-a/assets/asset-1",
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                    "max_telemetry_age_seconds": 300,
                    "allow_quarantine": True,
                },
            },
            {
                "id": "fact-held",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "asset-1",
                "predicate": "heldBy",
                "object_data": {"custodian": "agent-1", "transferable": True},
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
                    "observed_at": "2099-03-20T11:30:00+00:00",
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    governance = build_governance_context(payload, compiled_authz_index=compiled)

    assert governance["policy_decision"]["disposition"] == "quarantine"
    assert governance["policy_receipt"]["authz_disposition"] == "quarantine"
    assert governance["policy_receipt"]["governed_receipt_hash"] == governance["policy_decision"]["governed_receipt"]["decision_hash"]
    assert governance["policy_receipt"]["trust_gap_codes"] == ["stale_telemetry"]


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


def test_evaluate_intent_can_use_ray_backed_authz_cache(monkeypatch):
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
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:ROBOT_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MOVE",
                    "resource": "resource:asset-1",
                    "zones": ["zone:vault-a", "vault-a"],
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_USE_RAY_AUTHZ_CACHE", "true")
    monkeypatch.setattr(
        governance_mod,
        "_evaluate_compiled_authz_graph_with_ray",
        lambda **kwargs: {
            "source": "ray_actor",
            "shard_key": "zone:vault-a",
            "match": CompiledPermissionMatch(
                allowed=True,
                matched_subjects=("principal:agent-1", "role:ROBOT_OPERATOR"),
                reason="matched_allow_permission",
            ),
            "transition_evaluation": None,
        },
    )

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert decision.execution_token is not None
    assert decision.authz_graph["evaluator"] == "ray_actor"


def test_compiled_authz_shard_key_prefers_facility_then_zone() -> None:
    action_intent = build_action_intent(_base_payload())
    action_intent.action.parameters = {"facility_id": "vault-hub"}

    assert governance_mod._compiled_authz_shard_key(action_intent) == "facility:vault-hub"

    action_intent.action.parameters = {}
    assert governance_mod._compiled_authz_shard_key(action_intent) == "zone:vault-a"


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


def test_evaluate_intent_denies_high_risk_break_glass_without_deterministic_procedure(monkeypatch):
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
                "relationship": "can_bypass",
                "operation": "MUTATE",
                "conditions": {"requires_break_glass": True, "bypass_deny": True, "zones": ["vault-a"]},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", break_glass_secret)

    policy_case = governance_mod.prepare_policy_case(
        payload,
        cognitive_assessment={
            "recommended_disposition": "allow",
            "risk_score": 0.97,
            "risk_factors": ["high_risk_release"],
            "missing_evidence": [],
            "policy_conflicts": [],
            "required_approvals": [],
        },
    )
    decision = evaluate_intent(policy_case, compiled_authz_index=compiled)

    assert decision.allowed is False
    assert decision.deny_code == "break_glass_procedure_required"
    assert decision.break_glass.outcome == "deterministic_procedure_required"


def test_evaluate_intent_allows_high_risk_break_glass_with_deterministic_procedure(monkeypatch):
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
            extra_claims={
                "procedure_id": "bgp-2026-001",
                "incident_id": "incident-42",
                "reason_code": "safety_incident",
            },
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
                "relationship": "can_bypass",
                "operation": "MUTATE",
                "conditions": {"requires_break_glass": True, "bypass_deny": True, "zones": ["vault-a"]},
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", break_glass_secret)

    policy_case = governance_mod.prepare_policy_case(
        payload,
        cognitive_assessment={
            "recommended_disposition": "allow",
            "risk_score": 0.97,
            "risk_factors": ["high_risk_release"],
            "missing_evidence": [],
            "policy_conflicts": [],
            "required_approvals": [],
        },
    )
    decision = evaluate_intent(policy_case, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert decision.break_glass.validated is True
    assert decision.break_glass.procedure_id == "bgp-2026-001"
    assert decision.break_glass.incident_id == "incident-42"
    assert decision.break_glass.reason_code == "safety_incident"


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
    assert decision.governed_receipt["snapshot_hash"] == compiled.snapshot_hash
    assert decision.authz_graph["mode"] == "transition_evaluation"
    assert decision.authz_graph["snapshot_hash"] == compiled.snapshot_hash
    assert ("principal:agent-1", "role:ROBOT_OPERATOR") in [tuple(path) for path in decision.authz_graph["authority_paths"]]
    assert "fact-allow" in decision.authz_graph["matched_policy_refs"]
    assert any(item["code"] == "stale_telemetry" for item in decision.authz_graph["trust_gaps"])
    assert any(item["code"] == "telemetry_freshness" and item["outcome"] == "failed" for item in decision.authz_graph["checked_constraints"])
    assert any(item["code"] == "telemetry_freshness" and item["outcome"] == "failed" for item in decision.authz_graph["missing_prerequisites"])


def test_evaluate_intent_phase1_release_requires_approved_registration_and_stage(monkeypatch):
    payload = _base_payload()
    payload["params"]["governance"]["requires_approved_source_registration"] = True
    payload["params"]["governance"]["action_intent"]["action"]["type"] = "RELEASE"
    payload["params"]["governance"]["action_intent"]["action"]["parameters"] = {
        "workflow_stage": "release_review"
    }
    payload["params"]["governance"]["action_intent"]["resource"].update(
        {
            "resource_uri": "resource:asset-1",
            "lot_id": "lot-1",
            "source_registration_id": "reg-1",
            "registration_decision_id": "decision-1",
            "product_id": "sku-1",
        }
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
                "object_data": {"role": "RELEASE_OPERATOR"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "role:RELEASE_OPERATOR",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "RELEASE",
                    "resource": "asset-1",
                    "required_current_custodian": True,
                    "required_transferable_state": True,
                    "require_approved_source_registration": True,
                    "workflow_stages": ["release_review"],
                },
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
                    "lot_id": "lot-1",
                },
            },
        ],
        registrations=[
            {
                "id": "reg-1",
                "snapshot_id": 1,
                "lot_id": "lot-1",
                "producer_id": "producer-1",
                "status": "approved",
            }
        ],
        registration_decisions=[
            {
                "id": "decision-1",
                "registration_id": "reg-1",
                "decision": "approved",
                "policy_snapshot_id": 1,
                "decided_at": "2099-03-20T11:59:00+00:00",
            }
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        approved_source_registrations={"reg-1": "decision-1"},
    )

    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert any(tuple(path) == ("principal:agent-1", "role:RELEASE_OPERATOR") for path in decision.authz_graph["authority_paths"])
    assert "fact-allow" in decision.authz_graph["matched_policy_refs"]
    assert any(item["code"] == "source_registration" and item["outcome"] == "passed" for item in decision.authz_graph["checked_constraints"])
    assert "registration:reg-1" in decision.governed_receipt["evidence_refs"]
    assert "registration_decision:decision-1" in decision.governed_receipt["evidence_refs"]


def test_evaluate_intent_surfaces_phase2_multihop_authority_path() -> None:
    payload = _base_payload()
    canonical_resource_uri = "seedcore://zones/vault-a/assets/asset-1"
    graph = AuthzGraphProjector().project_snapshot(
        snapshot_ref="pkg-authz@phase2",
        snapshot_version="snapshot:1",
        facts=[
            {
                "id": "fact-delegated-by",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "agent-1",
                "predicate": "delegatedBy",
                "object_data": {"org": "acme-logistics"},
            },
            {
                "id": "fact-facility",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "org:acme-logistics",
                "predicate": "approvedForFacility",
                "object_data": {"facility_id": "vault-hub"},
            },
            {
                "id": "fact-zone-control",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "facility:vault-hub",
                "predicate": "controlsZone",
                "object_data": {"zone": "vault-a"},
            },
            {
                "id": "fact-allow",
                "snapshot_id": 1,
                "namespace": "authz",
                "subject": "zone:vault-a",
                "predicate": "allowedOperation",
                "object_data": {
                    "operation": "MUTATE",
                    "resource": canonical_resource_uri,
                    "zones": ["vault-a"],
                },
            },
        ],
    )
    compiled = AuthzGraphCompiler().compile(graph)

    decision = evaluate_intent(payload, compiled_authz_index=compiled)

    assert decision.allowed is True
    assert any(
        tuple(path) == (
            "principal:agent-1",
            "org:acme-logistics",
            "facility:vault-hub",
            "zone:vault-a",
        )
        for path in decision.authz_graph["authority_paths"]
    )


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
    assert "fact-allow" in decision.authz_graph["matched_policy_refs"]
    assert any(item["code"] == "current_custodian" for item in decision.authz_graph["missing_prerequisites"])


def test_evaluate_intent_restricted_custody_transfer_escalates_when_approval_incomplete() -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context["approved_by"] = ["principal:facility_mgr_001"]
    approval_context.pop("approval_binding_hash", None)

    decision = evaluate_intent(
        payload,
        authoritative_approval_envelope=_transfer_approval_envelope(
            status="PARTIALLY_APPROVED",
            quality_inspector_status="PENDING",
        ),
    )

    assert decision.allowed is False
    assert decision.disposition == "deny"
    assert decision.execution_token is None
    assert decision.required_approvals == ["FACILITY_MANAGER", "QUALITY_INSPECTOR"]
    assert decision.authz_graph["workflow_type"] == "custody_transfer"
    assert decision.authz_graph["workflow_status"] == "rejected"
    assert any(item["code"] == "co_signatures" for item in decision.authz_graph["missing_prerequisites"])
    assert any(item["code"] == "approved_by" for item in decision.authz_graph["missing_prerequisites"])
    assert decision.authz_graph["minted_artifacts"] == []
    assert decision.obligations == [{"code": "update_verification_surface"}]


def test_evaluate_intent_restricted_custody_transfer_allows_with_canonical_explanation(monkeypatch) -> None:
    payload = _transfer_payload()
    now = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    compiled = _compiled_transfer_graph(
        now=now,
        telemetry_at=now - timedelta(minutes=1),
        inspection_at=now - timedelta(minutes=2),
        current_custodian="facility_mgr_001",
    )

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert decision.authz_graph["workflow_type"] == "custody_transfer"
    assert decision.authz_graph["workflow_status"] == "verified"
    assert any(
        summary == "principal:agent-1 -> org:acme-logistics -> facility:north-warehouse -> zone:handoff-bay-3"
        for summary in decision.authz_graph["authority_path_summary"]
    )
    assert decision.authz_graph["matched_policy_refs"] == ["fact-transfer-allow"]
    assert {item["kind"] for item in decision.authz_graph["minted_artifacts"]} == {"execution_token", "governed_receipt"}
    assert {"code": "generate_transition_receipt"} in decision.obligations
    assert {"code": "publish_replay_artifact"} in decision.obligations
    assert {"code": "close_prior_custodian_state"} in decision.obligations
    assert {"code": "attach_telemetry_proof"} in decision.obligations
    assert decision.execution_token is not None
    assert decision.execution_token.constraints["approval_envelope_id"] == "approval-transfer-001"
    assert decision.execution_token.constraints["expected_current_custodian"] == "principal:facility_mgr_001"
    assert decision.governed_receipt["workflow_type"] == "custody_transfer"
    assert decision.governed_receipt["approval_envelope_id"] == "approval-transfer-001"
    assert decision.governed_receipt["co_signed"] is True
    assert decision.governed_receipt["snapshot_hash"] == compiled.snapshot_hash
    assert decision.authz_graph["snapshot_hash"] == compiled.snapshot_hash


def test_evaluate_intent_restricted_custody_transfer_marks_pending_cosign(monkeypatch) -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context["approved_by"] = ["principal:facility_mgr_001"]

    decision = evaluate_intent(
        payload,
        authoritative_approval_envelope=_transfer_approval_envelope(
            status="PARTIALLY_APPROVED",
            quality_inspector_status="PENDING",
        ),
    )

    assert decision.allowed is False
    assert decision.disposition == "deny"
    assert decision.authz_graph["reason"] == "pending_co_sign"
    assert decision.authz_graph["co_sign_status"] == "pending_co_sign"
    assert decision.authz_graph["co_sign_required"] is True
    assert len(decision.authz_graph["expected_co_signers"]) == 2


def test_evaluate_intent_restricted_custody_transfer_allows_zone_admin_emergency_override(monkeypatch) -> None:
    payload = _transfer_payload()
    payload["params"]["governance"]["action_intent"]["principal"]["agent_id"] = "zone-admin-1"
    payload["params"]["governance"]["action_intent"]["principal"]["role_profile"] = "ZONE_ADMINISTRATOR"
    payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]["approved_by"] = [
        "principal:facility_mgr_001"
    ]
    issued_at = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    break_glass_secret = "break-glass-secret"
    payload["params"]["governance"]["action_intent"]["environment"] = {
        "origin_network": "network:warehouse-core",
        "break_glass_token": _build_break_glass_token(
            secret=break_glass_secret,
            subject="zone-admin-1",
            issued_at=issued_at,
            expires_at=datetime(2099, 3, 20, 12, 0, 5, tzinfo=timezone.utc),
            extra_claims={
                "procedure_id": "bgp-2026-001",
                "incident_id": "incident-override-1",
                "reason_code": "safety_incident",
            },
        ),
        "break_glass_reason": "zone administrator emergency override",
    }
    compiled = _compiled_transfer_graph(
        now=issued_at,
        telemetry_at=issued_at - timedelta(minutes=1),
        inspection_at=issued_at - timedelta(minutes=2),
        current_custodian="facility_mgr_001",
    )

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")
    monkeypatch.setenv("SEEDCORE_PDP_BREAK_GLASS_SECRET", break_glass_secret)

    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert decision.break_glass.validated is True
    assert decision.authz_graph["transfer_outcome"] == "EMERGENCY_OVERRIDE"
    assert decision.authz_graph["co_sign_status"] == "emergency_override"
    assert decision.governed_receipt["transfer_outcome"] == "EMERGENCY_OVERRIDE"
    assert decision.governed_receipt["co_sign_status"] == "emergency_override"


def test_evaluate_intent_restricted_custody_transfer_denies_when_only_embedded_envelope_is_provided() -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context.pop("approval_binding_hash", None)
    approval_context.pop("required_roles", None)
    approval_context.pop("approved_by", None)
    approval_context["approval_envelope"] = _transfer_approval_envelope()

    decision = evaluate_intent(payload)

    assert decision.allowed is False
    assert decision.disposition == "deny"
    assert decision.authz_graph["reason"] == "approval_envelope_missing"
    assert any(item["code"] == "approval_envelope" for item in decision.authz_graph["missing_prerequisites"])


def test_evaluate_intent_restricted_custody_transfer_uses_authoritative_envelope_when_context_missing(monkeypatch) -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context.pop("approval_binding_hash", None)
    approval_context.pop("required_roles", None)
    approval_context.pop("approved_by", None)

    monkeypatch.setattr(
        governance_mod,
        "summarize_transfer_approval_with_rust",
        lambda envelope: {
            "valid": True,
            "status": "APPROVED",
            "required_roles": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
            "approved_by": [
                "principal:facility_mgr_001",
                "principal:quality_insp_017",
            ],
            "co_signed": True,
            "binding_hash": "sha256:approval-binding-transfer-001",
            "error_code": None,
            "details": [],
        },
    )

    decision = evaluate_intent(
        payload,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert decision.required_approvals == ["FACILITY_MANAGER", "QUALITY_INSPECTOR"]
    assert decision.execution_token is not None
    assert decision.execution_token.constraints["approval_binding_hash"] == "sha256:approval-binding-transfer-001"


def test_evaluate_intent_restricted_custody_transfer_escalates_on_rust_binding_mismatch(monkeypatch) -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context["approval_binding_hash"] = "sha256:provided-binding-hash"

    monkeypatch.setattr(
        governance_mod,
        "summarize_transfer_approval_with_rust",
        lambda envelope: {
            "valid": True,
            "status": "APPROVED",
            "required_roles": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
            "approved_by": [
                "principal:facility_mgr_001",
                "principal:quality_insp_017",
            ],
            "co_signed": True,
            "binding_hash": "sha256:computed-binding-hash",
            "error_code": None,
            "details": [],
        },
    )

    decision = evaluate_intent(
        payload,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is False
    assert decision.disposition == "escalate"
    assert decision.authz_graph["reason"] == "approval_binding_mismatch"
    assert any(item["code"] == "approval_binding" for item in decision.authz_graph["missing_prerequisites"])


def test_evaluate_intent_restricted_custody_transfer_uses_authoritative_transition_history() -> None:
    payload = _transfer_payload()
    approval_context = payload["params"]["governance"]["action_intent"]["action"]["parameters"]["approval_context"]
    approval_context.pop("approval_binding_hash", None)
    transition_history = [
        {
            "event_id": "approval-transition-event:sha256:transition-event-001",
            "event_hash": "sha256:transition-event-001",
            "previous_event_hash": None,
            "occurred_at": "2099-03-20T12:00:03+00:00",
            "transition_event": {
                "event_id": "approval-transition-event:sha256:transition-event-001",
                "event_hash": "sha256:transition-event-001",
                "previous_event_hash": None,
                "occurred_at": "2099-03-20T12:00:03+00:00",
                "transition_type": "add_approval",
                "envelope_id": "approval-transfer-001",
                "previous_status": "PARTIALLY_APPROVED",
                "next_status": "APPROVED",
                "previous_binding_hash": None,
                "next_binding_hash": "sha256:approval-binding-transfer-001",
                "envelope_version": 2,
            },
        }
    ]

    decision = evaluate_intent(
        payload,
        authoritative_approval_envelope=_transfer_approval_envelope(version=2),
        authoritative_approval_transition_history=transition_history,
        authoritative_approval_transition_head="sha256:transition-event-001",
    )

    assert decision.allowed is True
    assert decision.disposition == "allow"
    assert decision.execution_token is not None
    assert decision.execution_token.constraints["approval_binding_hash"].startswith("sha256:")
    assert decision.execution_token.constraints["approval_transition_head"] == "sha256:transition-event-001"
    assert decision.execution_token.constraints["co_signed"] is True
    assert decision.authz_graph["approval_transition_count"] == 1
    assert decision.authz_graph["approval_transition_head"] == "sha256:transition-event-001"


def test_evaluate_intent_restricted_custody_transfer_quarantines_when_telemetry_is_stale(monkeypatch) -> None:
    payload = _transfer_payload()
    now = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    compiled = _compiled_transfer_graph(
        now=now,
        telemetry_at=now - timedelta(minutes=20),
        inspection_at=now - timedelta(minutes=2),
        current_custodian="facility_mgr_001",
    )

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is False
    assert decision.disposition == "quarantine"
    assert decision.execution_token is None
    assert decision.authz_graph["workflow_status"] == "quarantined"
    assert any(item["code"] == "stale_telemetry" for item in decision.authz_graph["trust_gaps"])
    assert {"code": "preserve_restricted_state"} in decision.obligations
    assert {"code": "manual_review"} in decision.obligations
    assert {"code": "attach_telemetry_proof"} in decision.obligations


def test_evaluate_intent_restricted_custody_transfer_denies_when_expected_custodian_mismatches(monkeypatch) -> None:
    payload = _transfer_payload()
    now = datetime(2099, 3, 20, 12, 0, 0, tzinfo=timezone.utc)
    compiled = _compiled_transfer_graph(
        now=now,
        telemetry_at=now - timedelta(minutes=1),
        inspection_at=now - timedelta(minutes=2),
        current_custodian="outbound_mgr_002",
    )

    monkeypatch.setenv("SEEDCORE_PDP_USE_AUTHZ_GRAPH_TRANSITIONS", "true")

    decision = evaluate_intent(
        payload,
        compiled_authz_index=compiled,
        authoritative_approval_envelope=_transfer_approval_envelope(),
    )

    assert decision.allowed is False
    assert decision.disposition == "deny"
    assert decision.authz_graph["workflow_status"] == "rejected"
    assert decision.authz_graph["reason"] == "expected_custodian_mismatch"
    assert any(item["code"] == "expected_custodian" for item in decision.authz_graph["missing_prerequisites"])
    assert decision.obligations == [{"code": "update_verification_surface"}]


def test_evaluate_intent_escalates_when_owner_trust_max_risk_exceeded() -> None:
    payload = _base_payload()
    owner_twin = build_twin_snapshot(payload)["owner"].model_dump(mode="json")
    owner_twin["telemetry"] = {
        "owner_context": {
            "trust_preferences": {
                "status": "ACTIVE",
                "trust_version": "v1",
                "max_risk_score": 0.2,
            }
        }
    }

    decision = evaluate_intent(
        payload,
        relevant_twin_snapshot={"owner": owner_twin},
        cognitive_assessment={
            "recommended_disposition": "allow",
            "risk_score": 0.9,
        },
    )

    assert decision.allowed is False
    assert decision.disposition == "escalate"
    assert decision.authz_graph.get("reason") == "owner_trust_risk_escalation"
    assert "owner_trust_risk_escalation" in list(decision.governed_receipt.get("trust_gap_codes") or [])


def test_evaluate_intent_denies_when_owner_trust_merchant_not_allowlisted() -> None:
    payload = _base_payload()
    payload["params"]["governance"]["action_intent"]["action"]["parameters"] = {
        "gateway": {
            "organization_ref": "org:merchant-untrusted",
        }
    }
    owner_twin = build_twin_snapshot(payload)["owner"].model_dump(mode="json")
    owner_twin["telemetry"] = {
        "owner_context": {
            "trust_preferences": {
                "status": "ACTIVE",
                "trust_version": "v1",
                "merchant_allowlist": ["org:merchant-trusted"],
            }
        }
    }

    decision = evaluate_intent(
        payload,
        relevant_twin_snapshot={"owner": owner_twin},
    )

    assert decision.allowed is False
    assert decision.disposition == "deny"
    assert decision.deny_code == "owner_trust_merchant_violation"
