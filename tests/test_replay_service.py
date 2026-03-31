from __future__ import annotations

import os
import sys
import hashlib
from typing import Any, Dict, List
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

import pytest

import seedcore.services.replay_service as replay_service_module
from seedcore.hal.custody.transition_receipts import build_transition_receipt
from seedcore.services.replay_service import ReplayProjectionKind, ReplayService
from seedcore.ops.evidence.verification import build_signed_artifact


class _DummySession:
    async def execute(self, *args, **kwargs):
        raise AssertionError("execute() should not be called in these tests")


class _FakeRedis:
    def __init__(self) -> None:
        self._values: Dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self._values[key] = {"value": value, "ex": ex}
        return True


def _build_policy_receipt(*, task_id: str, intent_id: str, asset_id: str | None = None) -> Dict[str, Any]:
    payload = {
        "policy_receipt_id": f"policy-{intent_id}",
        "policy_decision_id": f"decision-{intent_id}",
        "task_id": task_id,
        "intent_id": intent_id,
        "policy_version": "pkg@2026-03-20",
        "decision": {"allowed": True, "disposition": "allow"},
        "evaluated_rules": ["zone_match"],
        "subject_ref": "agent:test",
        "asset_ref": asset_id,
        "authz_disposition": None,
        "governed_receipt_hash": None,
        "decision_graph_snapshot_hash": None,
        "decision_graph_snapshot_version": None,
        "trust_gap_codes": [],
        "timestamp": "2026-03-20T10:00:00+00:00",
    }
    _, signer_metadata, signature, _ = build_signed_artifact(
        artifact_type="policy_receipt",
        payload=payload,
    )
    return {
        **payload,
        "signer_metadata": signer_metadata.model_dump(mode="json"),
        "signature": signature,
    }


def _build_evidence_bundle(
    *,
    task_id: str,
    intent_id: str,
    token_id: str,
    transition_receipts: List[Dict[str, Any]],
    asset_id: str | None = None,
) -> Dict[str, Any]:
    payload = {
        "evidence_bundle_id": f"bundle-{intent_id}",
        "task_id": task_id,
        "intent_id": intent_id,
        "intent_ref": None,
        "execution_token_id": token_id,
        "policy_receipt_id": f"policy-{intent_id}",
        "decision_graph_snapshot_hash": None,
        "decision_graph_snapshot_version": None,
        "transition_receipt_ids": [item["transition_receipt_id"] for item in transition_receipts],
        "asset_fingerprint": {
            "fingerprint_id": f"fingerprint-{intent_id}",
            "fingerprint_hash": f"hash-{intent_id}",
            "modality_map": {"visual_hash": f"visual-{intent_id}"},
            "derivation_logic": {"algorithm": "sha256"},
            "capture_context": {"asset_id": asset_id} if asset_id else {},
            "hardware_witness": {"node_id": "robot_sim://unit-1"},
            "captured_at": "2026-03-20T10:03:00+00:00",
        },
        "evidence_inputs": {
            "execution_summary": {
                "intent_id": intent_id,
                "task_id": task_id,
                "execution_token_id": token_id,
                "executed_at": "2026-03-20T10:02:00+00:00",
                "actuator_endpoint": "robot_sim://unit-1",
                "actuator_result_hash": "actuator-hash",
                "transition_receipt_ids": [item["transition_receipt_id"] for item in transition_receipts],
                "node_id": "robot_sim://unit-1",
            },
            "transition_receipts": transition_receipts,
        },
        "telemetry_refs": [
            {
                "kind": "telemetry_snapshot",
                "inline": {
                    "zone_checks": {"target_zone": "vault-a", "current_zone": "staging-a"},
                    "vision": [{"label": "sealed_box"}],
                },
            }
        ],
        "media_refs": [{"kind": "image", "uri": "s3://bucket/proof.jpg", "sha256": "media-sha"}],
        "node_id": "robot_sim://unit-1",
        "created_at": "2026-03-20T10:03:00+00:00",
    }
    _, signer_metadata, signature, _ = build_signed_artifact(
        artifact_type="evidence_bundle",
        payload=payload,
        endpoint_id="robot_sim://unit-1",
        trust_level="attested",
        node_id="robot_sim://unit-1",
    )
    return {
        **payload,
        "signer_metadata": signer_metadata.model_dump(mode="json"),
        "signature": signature,
    }


def _build_audit_record(*, task_id: str, intent_id: str, asset_id: str | None = None) -> Dict[str, Any]:
    audit_suffix = hashlib.md5(intent_id.encode("utf-8")).hexdigest()[:12]
    transition_receipt = build_transition_receipt(
        intent_id=intent_id,
        token_id=f"token-{intent_id}",
        actuator_endpoint="robot_sim://unit-1",
        hardware_uuid="robot-1",
        actuator_result_hash="actuator-hash",
        from_zone="staging-a",
        to_zone="vault-a",
        target_zone="vault-a",
        executed_at="2026-03-20T10:01:00+00:00",
        receipt_nonce=f"nonce-{intent_id}",
    )
    return {
        "id": f"00000000-0000-0000-0000-{audit_suffix}",
        "task_id": task_id,
        "record_type": "execution_receipt",
        "intent_id": intent_id,
        "token_id": f"token-{intent_id}",
        "policy_snapshot": "pkg@2026-03-20",
        "policy_decision": {"allowed": True, "disposition": "allow"},
        "action_intent": {
            "intent_id": intent_id,
            "resource": {"asset_id": asset_id} if asset_id else {},
        },
        "policy_case": {},
        "policy_receipt": _build_policy_receipt(task_id=task_id, intent_id=intent_id, asset_id=asset_id),
        "evidence_bundle": _build_evidence_bundle(
            task_id=task_id,
            intent_id=intent_id,
            token_id=f"token-{intent_id}",
            transition_receipts=[transition_receipt],
            asset_id=asset_id,
        ),
        "actor_agent_id": "agent:test",
        "actor_organ_id": "organ:test",
        "input_hash": "input-hash",
        "evidence_hash": "evidence-hash",
        "recorded_at": "2026-03-20T10:04:00+00:00",
    }


def _apply_transition_metadata(
    record: Dict[str, Any],
    *,
    disposition: str = "quarantine",
    reason: str = "trust_gap_quarantine",
    trust_gap_codes: List[str] | None = None,
) -> Dict[str, Any]:
    codes = list(trust_gap_codes or ["stale_telemetry"])
    record["policy_decision"] = {
        **dict(record.get("policy_decision") or {}),
        "allowed": disposition != "deny",
        "disposition": disposition,
        "authz_graph": {
            "mode": "transition_evaluation",
            "disposition": disposition,
            "reason": reason,
            "snapshot_ref": "authz_graph@snapshot:1",
            "snapshot_id": "snapshot:1",
            "snapshot_version": "snapshot:1",
            "snapshot_hash": "snapshot-hash-1",
            "asset_ref": record.get("policy_receipt", {}).get("asset_ref"),
            "resource_ref": f"seedcore://zones/vault-a/assets/{record.get('policy_receipt', {}).get('asset_ref')}",
            "current_custodian": "principal:agent:test",
            "restricted_token_recommended": disposition == "quarantine",
            "trust_gaps": [
                {
                    "code": code,
                    "message": f"Gap detected: {code}",
                    "details": {},
                }
                for code in codes
            ],
        },
        "governed_receipt": {
            "decision_hash": f"receipt-{record['intent_id']}",
            "disposition": disposition,
            "snapshot_ref": "authz_graph@snapshot:1",
            "snapshot_id": "snapshot:1",
            "snapshot_version": "snapshot:1",
            "snapshot_hash": "snapshot-hash-1",
            "principal_ref": "principal:agent:test",
            "operation": "MOVE",
            "asset_ref": record.get("policy_receipt", {}).get("asset_ref"),
            "resource_ref": f"seedcore://zones/vault-a/assets/{record.get('policy_receipt', {}).get('asset_ref')}",
            "twin_ref": (
                f"asset:{record.get('policy_receipt', {}).get('asset_ref')}"
                if record.get("policy_receipt", {}).get("asset_ref")
                else None
            ),
            "reason": reason,
            "generated_at": "2026-03-20T10:00:00+00:00",
            "custody_proof": ["custody:handoff-1", "custody:handoff-2"],
            "evidence_refs": ["telemetry:temp-1"],
            "trust_gap_codes": codes,
            "provenance_sources": ["tracking_event:telemetry-1"],
            "advisory": {"evidence_quality_score": 0.73},
        },
    }
    return record


def _apply_transfer_workflow_metadata(
    record: Dict[str, Any],
    *,
    disposition: str,
    required_approvals: List[str] | None = None,
    approved_by: List[str] | None = None,
    approval_transition_history: List[Dict[str, Any]] | None = None,
    approval_transition_head: str | None = None,
) -> Dict[str, Any]:
    transition_history = [dict(item) for item in (approval_transition_history or [])]
    transition_head = approval_transition_head or (
        str(transition_history[-1].get("event_hash"))
        if transition_history and transition_history[-1].get("event_hash") is not None
        else None
    )
    record = _apply_transition_metadata(
        record,
        disposition=disposition,
        reason="restricted_custody_transfer" if disposition == "allow" else "approval_incomplete",
        trust_gap_codes=["stale_telemetry"] if disposition == "quarantine" else [],
    )
    record["action_intent"] = {
        "intent_id": record["intent_id"],
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "approval_context": {
                    "approval_envelope_id": "approval-transfer-001",
                    "approved_by": list(approved_by or []),
                    "approval_transition_head": transition_head,
                    "approval_transition_history": transition_history,
                }
            },
        },
    }
    record["policy_decision"] = {
        **dict(record.get("policy_decision") or {}),
        "disposition": disposition,
        "required_approvals": list(required_approvals or []),
        "authz_graph": {
            **dict((record.get("policy_decision") or {}).get("authz_graph") or {}),
            "workflow_type": "custody_transfer",
            "workflow_status": (
                "pending_approval"
                if disposition == "escalate" and required_approvals
                else "quarantined"
                if disposition == "quarantine"
                else "verified"
                if disposition == "allow"
                else "rejected"
            ),
            "approved_by": list(approved_by or []),
            "approval_envelope_id": "approval-transfer-001",
            "approval_transition_head": transition_head,
            "approval_transition_count": len(transition_history),
            "authority_path_summary": [
                "principal:agent:test -> org:acme-logistics -> facility:north-warehouse -> zone:vault-a"
            ],
            "minted_artifacts": (
                [{"kind": "governed_receipt", "ref": f"receipt-{record['intent_id']}"}]
                if disposition != "escalate"
                else []
            ),
            "obligations": (
                [{"code": "update_verification_surface"}]
                if disposition == "escalate"
                else [{"code": "publish_replay_artifact"}]
            ),
        },
    }
    if disposition == "escalate":
        record["policy_decision"]["governed_receipt"] = {}
    return record


def _sample_approval_transition_history() -> List[Dict[str, Any]]:
    return [
        {
            "event_id": "approval-transition-event:sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72",
            "event_hash": "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72",
            "previous_event_hash": None,
            "occurred_at": "2026-04-02T08:00:30Z",
            "transition_type": "add_approval",
            "envelope_id": "approval-transfer-001",
            "previous_status": "PARTIALLY_APPROVED",
            "next_status": "APPROVED",
            "previous_binding_hash": None,
            "next_binding_hash": "sha256:fd6236849fc43a3d10c071da4a211964f652dcf83a91cf6a258cd6e3aabc4f9c",
            "envelope_version": 2,
        }
    ]


@pytest.mark.asyncio
async def test_assemble_replay_record_for_asset_includes_enrichment_and_verified_chain():
    record = _build_audit_record(task_id="task-asset-1", intent_id="intent-asset-1", asset_id="asset-1")
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type(
            "TwinDAO",
            (),
            {
                "list_history": AsyncMock(
                    side_effect=[
                        [{"id": "asset-hist-1", "twin_type": "asset", "state_version": 2, "authority_source": "pdp", "recorded_at": "2026-03-20T10:05:00+00:00"}],
                        [{"id": "tx-hist-1", "twin_type": "transaction", "state_version": 1, "authority_source": "settlement", "recorded_at": "2026-03-20T10:06:00+00:00"}],
                    ]
                )
            },
        )(),
        asset_custody_dao=type(
            "AssetDAO",
            (),
            {
                "get_snapshot": AsyncMock(
                    return_value={
                        "asset_id": "asset-1",
                        "current_zone": "vault-a",
                        "is_quarantined": False,
                        "authority_source": "governed_transition_receipt",
                        "last_transition_seq": 4,
                    }
                )
            },
        )(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.subject_type == "asset"
    assert replay.subject_id == "asset-1"
    assert replay.verification_status.verified is True
    assert replay.verification_status.artifact_results["decision_graph_snapshot"]["verified"] is True
    assert replay.verification_status.artifact_results["policy_receipt"]["verified"] is True
    assert replay.verification_status.artifact_results["evidence_bundle"]["verified"] is True
    assert replay.verification_status.artifact_results["rust_replay_chain"]["verified"] is True
    assert replay.verification_status.artifact_results["rust_replay_chain"]["artifact_count"] == 6
    assert [
        item.get("artifact_type")
        for item in replay.verification_status.artifact_results["rust_replay_chain"]["artifact_reports"]
    ] == [
        "action_intent",
        "policy_decision",
        "policy_receipt",
        "execution_token",
        "transition_receipt",
        "evidence_bundle",
    ]
    assert replay.verification_status.signer_policy["evidence_bundle"]["preferred_scheme"] in {"ed25519", "hmac_sha256"}
    assert replay.asset_custody_state["current_zone"] == "vault-a"
    assert [item.event_type for item in replay.replay_timeline] == [
        "policy_receipt_issued",
        "transition_executed",
        "evidence_materialized",
        "audit_recorded",
        "digital_twin_updated",
        "digital_twin_updated",
    ]
    assert "audit_record" not in replay.public_projection
    assert replay.internal_projection["audit_record"]["actor_agent_id"] == "agent:test"


@pytest.mark.asyncio
async def test_assemble_replay_record_for_transaction_defaults_to_transaction_subject():
    record = _build_audit_record(task_id="task-tx-1", intent_id="intent-tx-1", asset_id=None)
    record["action_intent"] = {"intent_id": "intent-tx-1", "resource": {}}
    record["policy_receipt"]["asset_ref"] = None
    record["evidence_bundle"]["asset_fingerprint"]["capture_context"] = {}

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type(
            "TwinDAO",
            (),
            {"list_history": AsyncMock(return_value=[{"id": "tx-hist-2", "twin_type": "transaction", "state_version": 3, "authority_source": "settlement", "recorded_at": "2026-03-20T10:07:00+00:00"}])},
        )(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.subject_type == "transaction"
    assert replay.subject_id == "transaction:intent-tx-1"
    assert replay.asset_custody_state is None
    assert replay.public_projection["subject_title"] == "Transaction transaction:intent-tx-1"


@pytest.mark.asyncio
async def test_public_projection_redacts_internal_details_and_internal_projection_keeps_them():
    record = _build_audit_record(task_id="task-redact-1", intent_id="intent-redact-1", asset_id="asset-redact-1")
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert "audit_record" in replay.internal_projection
    assert "evidence_bundle" in replay.internal_projection
    assert "audit_record" not in replay.public_projection
    assert "signer_chain" not in replay.public_projection
    assert replay.public_projection["fingerprint_summary"]["fingerprint_hash"] == "hash-intent-redact-1"


@pytest.mark.asyncio
async def test_replay_surfaces_authz_transition_metadata_for_quarantine() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-graph-1", intent_id="intent-graph-1", asset_id="asset-graph-1")
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-graph-1", "current_zone": "vault-a"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.authz_graph["reason"] == "trust_gap_quarantine"
    assert replay.governed_receipt["decision_hash"] == "receipt-intent-graph-1"
    assert replay.internal_projection["governed_receipt"]["custody_proof"] == ["custody:handoff-1", "custody:handoff-2"]
    assert replay.internal_projection["authz_graph"]["current_custodian"] == "principal:agent:test"
    assert replay.public_projection["policy_summary"]["governed_receipt_hash"] == "receipt-intent-graph-1"
    assert replay.public_projection["policy_summary"]["decision_graph_snapshot_hash"] == "snapshot-hash-1"
    assert replay.public_projection["policy_summary"]["trust_gap_codes"] == ["stale_telemetry"]
    assert replay.public_projection["custody_summary"]["quarantined"] is True
    assert replay.public_projection["custody_summary"]["custody_proof_count"] == 2
    assert any(item.event_type == "authz_transition_evaluated" for item in replay.replay_timeline)


@pytest.mark.asyncio
async def test_replay_surfaces_owner_trust_gap_details_and_owner_context_refs() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-owner-trust-1", intent_id="intent-owner-trust-1", asset_id="asset-owner-trust-1"),
        disposition="deny",
        reason="owner_trust_preference_violation",
        trust_gap_codes=["owner_trust_merchant_violation"],
    )
    governed_receipt = (
        record.get("policy_decision", {}).get("governed_receipt")
        if isinstance(record.get("policy_decision"), dict)
        and isinstance(record.get("policy_decision", {}).get("governed_receipt"), dict)
        else {}
    )
    governed_receipt["owner_context"] = {
        "owner_id": "did:seedcore:owner:acme-001",
        "creator_profile_ref": {
            "owner_id": "did:seedcore:owner:acme-001",
            "version": "v2",
            "updated_at": "2026-03-31T10:00:00Z",
        },
        "trust_preferences_ref": {
            "owner_id": "did:seedcore:owner:acme-001",
            "trust_version": "v3",
            "updated_at": "2026-03-31T10:00:01Z",
        },
    }
    record["policy_decision"]["governed_receipt"] = governed_receipt

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-owner-trust-1"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    authorization = replay.public_projection["authorization"]
    assert authorization["trust_gap_codes"] == ["owner_trust_merchant_violation"]
    assert authorization["trust_gap_details"][0]["category"] == "owner_trust"
    assert authorization["owner_context"]["owner_id"] == "did:seedcore:owner:acme-001"
    assert authorization["owner_context"]["trust_preferences_ref"]["trust_version"] == "v3"

    claims = replay.public_projection["verifiable_claims"]
    assert any(item.get("claim") == "owner_trust_preference_gap_detected" for item in claims)
    assert any(item.get("claim") == "owner_trust_preferences_version_bound" for item in claims)

    public_jsonld = service.build_jsonld_export(replay, projection=ReplayProjectionKind.PUBLIC)
    proof = public_jsonld["proof"]
    assert proof["trust_gap_codes"] == ["owner_trust_merchant_violation"]
    assert proof["trust_gap_details"][0]["category"] == "owner_trust"
    assert proof["owner_context"]["owner_id"] == "did:seedcore:owner:acme-001"
    assert proof["owner_context"]["creator_profile_ref"]["version"] == "v2"

    certificate = await service.build_trust_certificate(
        replay,
        public_id="public-owner-trust-1",
        expires_at="2026-04-30T10:00:00Z",
    )
    assert isinstance(certificate.authority_consistency_hash, str)
    assert certificate.authority_consistency_hash.startswith("sha256:")
    assert certificate.operator_actions == []
    assert certificate.trust_gap_codes == ["owner_trust_merchant_violation"]
    assert certificate.trust_gap_details[0]["category"] == "owner_trust"
    assert certificate.owner_context["owner_id"] == "did:seedcore:owner:acme-001"
    assert certificate.owner_context["trust_preferences_ref"]["trust_version"] == "v3"


@pytest.mark.asyncio
async def test_replay_includes_custody_transition_and_dispute_refs():
    record = _build_audit_record(task_id="task-graph-1", intent_id="intent-graph-1", asset_id="asset-graph-1")
    dispute_case = {
        "dispute_id": "dispute:test-1",
        "status": "OPEN",
        "asset_id": "asset-graph-1",
        "title": "Seal mismatch",
        "references": {"transition_event_id": "receipt-intent-graph-1"},
        "recorded_at": "2026-03-20T10:05:00+00:00",
        "updated_at": "2026-03-20T10:05:00+00:00",
    }
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-graph-1"})})(),
        custody_transition_dao=type(
            "TransitionDAO",
            (),
            {
                "list_for_asset": AsyncMock(
                    return_value=[
                        {
                            "transition_event_id": "receipt-intent-graph-1",
                            "asset_id": "asset-graph-1",
                            "transition_seq": 1,
                            "lineage_status": "authoritative",
                            "recorded_at": "2026-03-20T10:04:30+00:00",
                            "intent_id": "intent-graph-1",
                            "audit_record_id": record["id"],
                        }
                    ]
                )
            },
        )(),
        custody_dispute_dao=type(
            "DisputeDAO",
            (),
            {
                "list_cases": AsyncMock(
                    return_value=[dispute_case]
                ),
                "list_events": AsyncMock(return_value=[]),
                "get_case": AsyncMock(return_value=dispute_case),
            },
        )(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.custody_transition_refs[0]["transition_event_id"] == "receipt-intent-graph-1"
    assert replay.dispute_refs[0]["dispute_id"] == "dispute:test-1"
    assert any(item.event_type == "custody_lineage_recorded" for item in replay.replay_timeline)
    assert replay.public_projection["dispute_summary"]["count"] == 1


@pytest.mark.asyncio
async def test_public_reference_lifecycle_supports_decode_revoke_and_failed_verification():
    record = _build_audit_record(task_id="task-ref-1", intent_id="intent-ref-1", asset_id="asset-ref-1")
    dao = type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})()
    service = ReplayService(
        governance_audit_dao=dao,
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])
    reference, public_id = service.build_public_reference(
        lookup_key="audit_id",
        lookup_value=record["id"],
        replay=replay,
        ttl_hours=4,
    )
    decoded = service.decode_public_reference(public_id)
    redis_client = _FakeRedis()
    revoke_result = await service.revoke_reference(public_id=public_id, redis_client=redis_client)
    verification = await service.verify_reference(
        _DummySession(),
        public_id=public_id,
        redis_client=redis_client,
    )

    assert decoded.audit_id == record["id"]
    assert revoke_result["revoked"] is True
    assert await service.reference_is_revoked(reference=reference, redis_client=redis_client) is True
    assert verification.verified is False
    assert verification.reason == "revoked_reference"


@pytest.mark.asyncio
async def test_verify_reference_fails_on_subject_mismatch_for_signed_token() -> None:
    record = _build_audit_record(task_id="task-ref-mismatch-1", intent_id="intent-ref-mismatch-1", asset_id="asset-ref-mismatch-1")
    dao = type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})()
    service = ReplayService(
        governance_audit_dao=dao,
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])
    _, public_id = service.build_public_reference(
        lookup_key="audit_id",
        lookup_value=record["id"],
        replay=replay,
        ttl_hours=4,
    )
    decoded = service.decode_public_reference(public_id)
    mismatched_public_id = service.encode_public_reference(
        decoded.model_copy(update={"subject_id": "asset-ref-mismatch-other"})
    )
    verification = await service.verify_reference(
        _DummySession(),
        public_id=mismatched_public_id,
    )

    assert verification.verified is False
    assert verification.reason == "reference_subject_mismatch"
    assert verification.tamper_status == "authority_mismatch"


@pytest.mark.asyncio
async def test_verify_reference_fails_on_owner_identity_mismatch() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-owner-mismatch-1", intent_id="intent-owner-mismatch-1", asset_id="asset-owner-mismatch-1"),
        disposition="allow",
        reason="restricted_custody_transfer",
        trust_gap_codes=[],
    )
    record["action_intent"] = {
        "intent_id": "intent-owner-mismatch-1",
        "principal": {
            "agent_id": "did:seedcore:assistant:warehouse-bot-01",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
        },
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "gateway": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "delegation_ref": "delegation:owner-8841-transfer",
                }
            },
        },
    }
    record["policy_decision"]["governed_receipt"]["owner_context"] = {
        "owner_id": "did:seedcore:owner:other-999",
        "creator_profile_ref": {"owner_id": "did:seedcore:owner:other-999", "version": "v2"},
        "trust_preferences_ref": {"owner_id": "did:seedcore:owner:other-999", "trust_version": "v1"},
    }

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    verification = await service.verify_reference(_DummySession(), audit_id=record["id"])
    assert verification.verified is False
    assert verification.reason == "owner_identity_mismatch"
    assert verification.tamper_status == "authority_mismatch"

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])
    authority_policy = replay.public_projection["policy_summary"]["authority_consistency"]
    authority_authz = replay.public_projection["authorization"]["authority_consistency"]
    authority_verification = replay.public_projection["verification_status"]["authority_consistency"]
    assert authority_policy["ok"] is False
    assert "owner_identity_mismatch" in authority_policy["issues"]
    assert authority_policy["hash"].startswith("sha256:")
    assert authority_authz["ok"] is False
    assert "owner_identity_mismatch" in authority_authz["issues"]
    assert authority_authz["hash"] == authority_policy["hash"]
    assert authority_verification["ok"] is False
    assert "owner_identity_mismatch" in authority_verification["issues"]
    assert authority_verification["hash"] == authority_policy["hash"]
    assert "Authority binding mismatches require operator review." in replay.public_projection["subject_summary"]
    assert replay.public_projection["operator_actions"][0]["code"] == "reconcile_owner_identity"

    certificate = await service.build_trust_certificate(
        replay,
        public_id="public-owner-mismatch-1",
        expires_at="2026-04-30T10:00:00Z",
    )
    assert certificate.authority_consistency_hash == authority_policy["hash"]
    assert certificate.operator_actions[0]["code"] == "reconcile_owner_identity"


@pytest.mark.asyncio
async def test_verify_reference_fails_on_delegation_ref_mismatch() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(task_id="task-delegation-mismatch-1", intent_id="intent-delegation-mismatch-1", asset_id="asset-delegation-mismatch-1"),
        disposition="allow",
        reason="restricted_custody_transfer",
        trust_gap_codes=[],
    )
    record["action_intent"] = {
        "intent_id": "intent-delegation-mismatch-1",
        "principal": {
            "agent_id": "did:seedcore:assistant:warehouse-bot-01",
            "owner_id": "did:seedcore:owner:acme-001",
            "delegation_ref": "delegation:owner-8841-transfer",
        },
        "action": {
            "type": "TRANSFER_CUSTODY",
            "parameters": {
                "gateway": {
                    "owner_id": "did:seedcore:owner:acme-001",
                    "delegation_ref": "delegation:owner-9999-transfer",
                }
            },
        },
    }
    record["policy_decision"]["governed_receipt"]["owner_context"] = {
        "owner_id": "did:seedcore:owner:acme-001",
        "creator_profile_ref": {"owner_id": "did:seedcore:owner:acme-001", "version": "v2"},
        "trust_preferences_ref": {"owner_id": "did:seedcore:owner:acme-001", "trust_version": "v1"},
    }

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value=None)})(),
    )

    verification = await service.verify_reference(_DummySession(), audit_id=record["id"])
    assert verification.verified is False
    assert verification.reason == "delegation_ref_mismatch"
    assert verification.tamper_status == "authority_mismatch"


@pytest.mark.asyncio
async def test_replay_projection_maps_restricted_custody_transfer_to_quarantined_status():
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(task_id="task-transfer-q", intent_id="intent-transfer-q", asset_id="asset-transfer-q"),
        disposition="quarantine",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-q"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.public_projection["workflow_type"] == "custody_transfer"
    assert replay.public_projection["status"] == "quarantined"
    assert replay.public_projection["approvals"]["completed_by"] == [
        "principal:facility_mgr_001",
        "principal:quality_insp_017",
    ]
    assert replay.public_projection["policy_summary"]["obligations"] == [{"code": "publish_replay_artifact"}]


@pytest.mark.asyncio
async def test_replay_projection_maps_escalation_with_required_approvals_to_pending_approval():
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(task_id="task-transfer-p", intent_id="intent-transfer-p", asset_id="asset-transfer-p"),
        disposition="escalate",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001"],
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-p"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.public_projection["status"] == "pending_approval"
    assert replay.public_projection["approvals"]["required"] == [
        "FACILITY_MANAGER",
        "QUALITY_INSPECTOR",
    ]
    assert replay.public_projection["authorization"]["disposition"] == "escalate"


@pytest.mark.asyncio
async def test_replay_projection_and_jsonld_include_approval_transition_chain() -> None:
    transition_history = _sample_approval_transition_history()
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(
            task_id="task-transfer-chain-1",
            intent_id="intent-transfer-chain-1",
            asset_id="asset-transfer-chain-1",
        ),
        disposition="allow",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
        approval_transition_history=transition_history,
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-chain-1"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.public_projection["approvals"]["approval_transition_count"] == 1
    assert replay.public_projection["approvals"]["approval_transition_head"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"
    assert any(item.event_type == "approval_transition_applied" for item in replay.replay_timeline)
    assert any(
        item.get("claim") == "approval_transition_chain_available" and item.get("value") is True
        for item in replay.public_projection["verifiable_claims"]
    )
    assert replay.verification_status.artifact_results["approval_transition_history"]["valid"] is True
    assert replay.jsonld_export["proof"]["approval_transition_chain"]["count"] == 1
    assert replay.jsonld_export["proof"]["approval_transition_chain"]["head"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"


@pytest.mark.asyncio
async def test_public_jsonld_approval_transition_chain_exposes_hash_only_fields() -> None:
    transition_history = _sample_approval_transition_history()
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(
            task_id="task-transfer-chain-2",
            intent_id="intent-transfer-chain-2",
            asset_id="asset-transfer-chain-2",
        ),
        disposition="allow",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
        approval_transition_history=transition_history,
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-chain-2"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])
    public_jsonld = service.build_jsonld_export(replay, projection=ReplayProjectionKind.PUBLIC)

    chain = public_jsonld["proof"]["approval_transition_chain"]
    assert chain["count"] == 1
    assert chain["head"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"
    assert chain["events"][0]["event_hash"] == "sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72"
    assert "previous_status" not in chain["events"][0]


@pytest.mark.asyncio
async def test_replay_verification_flags_invalid_approval_transition_history_chain() -> None:
    transition_history = _sample_approval_transition_history()
    transition_history[0]["previous_event_hash"] = "sha256:unexpected-head"
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(
            task_id="task-transfer-chain-3",
            intent_id="intent-transfer-chain-3",
            asset_id="asset-transfer-chain-3",
        ),
        disposition="allow",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
        approval_transition_history=transition_history,
        approval_transition_head="sha256:5cbde77901f79006292aff1d9508f13ed64018f166f559aa0de39aef31dccb72",
    )
    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-chain-3"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.verification_status.verified is False
    assert replay.verification_status.artifact_results["approval_transition_history"]["valid"] is False
    assert replay.verification_status.artifact_results["rust_replay_chain"]["verified"] is True
    assert any(
        isinstance(item, str) and item.startswith("approval_transition_history:")
        for item in replay.verification_status.issues
    )


@pytest.mark.asyncio
async def test_allow_replay_requires_execution_token_in_rust_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    record = _apply_transfer_workflow_metadata(
        _build_audit_record(
            task_id="task-transfer-token-required-1",
            intent_id="intent-transfer-token-required-1",
            asset_id="asset-transfer-token-required-1",
        ),
        disposition="allow",
        required_approvals=["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
        approved_by=["principal:facility_mgr_001", "principal:quality_insp_017"],
    )

    monkeypatch.setattr(
        replay_service_module,
        "mint_execution_token_with_rust",
        lambda claims: {"error": "mint_failed", "claims": dict(claims)},
    )

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-token-required-1"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    rust_chain = replay.verification_status.artifact_results["rust_replay_chain"]
    assert rust_chain["execution_token_required"] is True
    assert rust_chain["execution_token_present"] is False
    assert rust_chain["execution_token_verified"] is False
    assert rust_chain["verified"] is False
    assert any(item == "rust_replay_chain:allow_missing_execution_token" for item in replay.verification_status.issues)


@pytest.mark.asyncio
async def test_replay_verification_fails_on_decision_graph_snapshot_hash_mismatch() -> None:
    record = _apply_transition_metadata(
        _build_audit_record(
            task_id="task-transfer-snapshot-mismatch-1",
            intent_id="intent-transfer-snapshot-mismatch-1",
            asset_id="asset-transfer-snapshot-mismatch-1",
        )
    )
    record["policy_decision"]["authz_graph"]["snapshot_hash"] = "snapshot-hash-authz"
    record["policy_decision"]["governed_receipt"]["snapshot_hash"] = "snapshot-hash-receipt"
    record["policy_receipt"]["decision_graph_snapshot_hash"] = "snapshot-hash-receipt"
    record["policy_receipt"]["decision_graph_snapshot_version"] = "snapshot:1"
    record["evidence_bundle"]["decision_graph_snapshot_hash"] = "snapshot-hash-receipt"
    record["evidence_bundle"]["decision_graph_snapshot_version"] = "snapshot:1"

    service = ReplayService(
        governance_audit_dao=type("DAO", (), {"get_by_entry_id": AsyncMock(return_value=record)})(),
        digital_twin_dao=type("TwinDAO", (), {"list_history": AsyncMock(return_value=[])})(),
        asset_custody_dao=type("AssetDAO", (), {"get_snapshot": AsyncMock(return_value={"asset_id": "asset-transfer-snapshot-mismatch-1"})})(),
    )

    _, _, replay = await service.assemble_replay_record(_DummySession(), audit_id=record["id"])

    assert replay.verification_status.verified is False
    assert replay.verification_status.artifact_results["decision_graph_snapshot"]["verified"] is False
    assert replay.verification_status.artifact_results["decision_graph_snapshot"]["error_code"] == "snapshot_hash_mismatch"
    assert "decision_graph_snapshot:snapshot_hash_mismatch" in replay.verification_status.issues
