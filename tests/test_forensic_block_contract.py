from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if os.path.dirname(__file__) not in sys.path:
    sys.path.insert(0, os.path.dirname(__file__))
import mock_database_dependencies  # noqa: F401
import mock_ray_dependencies  # noqa: F401

from seedcore.models.agent_action_gateway import AgentActionClosureRequest
from seedcore.ops.evidence.materializer import materialize_seedcore_custody_event_payload


def _schema_payload() -> dict:
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "references"
        / "contracts"
        / "seedcore.forensic_block.v1.schema.json"
    )
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _build_audit_record() -> dict:
    return {
        "id": "2b4c76c8-20e2-4222-aa18-c4f1ee212f72",
        "intent_id": "req-transfer-2026-0001",
        "recorded_at": "2026-04-02T12:00:00Z",
        "policy_receipt": {
            "policy_receipt_id": "policy-receipt-2026-0001",
            "policy_decision_id": "sha256:policy-decision-0001",
            "decision_graph_snapshot_version": "snapshot:rct-2026-04-02",
        },
        "policy_decision": {
            "disposition": "allow",
            "authz_graph": {
                "disposition": "allow",
                "snapshot_version": "snapshot:rct-2026-04-02",
                "matched_policy_refs": ["rct.allow.v1"],
            },
            "governed_receipt": {
                "decision_hash": "sha256:decision-0001",
                "snapshot_version": "snapshot:rct-2026-04-02",
                "audit_id": "2b4c76c8-20e2-4222-aa18-c4f1ee212f72",
            },
        },
        "action_intent": {
            "intent_id": "req-transfer-2026-0001",
            "principal": {
                "agent_id": "did:seedcore:assistant:buyer-bot-77",
                "owner_id": "did:seedcore:owner:acme-001",
                "delegation_ref": "sha256:delegation-0001",
                "organization_ref": "org:acme",
            },
            "resource": {
                "asset_id": "asset:lot-8841",
                "lot_id": "lot-8841",
                "product_ref": "sku:cocoa-bar-72",
                "quote_ref": "quote-2026-0001",
            },
            "action": {
                "parameters": {
                    "gateway": {
                        "owner_id": "did:seedcore:owner:acme-001",
                        "delegation_ref": "sha256:delegation-0001",
                        "organization_ref": "org:acme",
                        "hardware_public_key_fingerprint": "sha256:hardware-fingerprint-0001",
                        "facility_ref": "facility:warehouse-a",
                        "expected_coordinate_ref": "coord:warehouse-a:slot-12",
                        "expected_to_zone": "vault-a",
                    }
                }
            },
        },
        "evidence_bundle": {
            "evidence_bundle_id": "bundle-2026-0001",
            "forensic_block_id": "fb-2026-0001",
            "execution_token_id": "token-transfer-2026-0001",
            "node_id": "edge:jetson-agx-orin-01",
            "created_at": "2026-04-02T12:00:00Z",
            "signer_metadata": {"key_ref": "kms://seedcore/verify/hsm-key-001"},
            "evidence_inputs": {
                "execution_summary": {"actuator_result_hash": "sha256:actuator-result-0001"},
            },
        },
    }


def test_forensic_block_schema_example_is_valid() -> None:
    example_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "references"
        / "contracts"
        / "seedcore.forensic_block.v1.example.json"
    )
    schema = _schema_payload()
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(payload)


def test_materialized_forensic_block_matches_contract_schema() -> None:
    audit_record = _build_audit_record()
    materialized = materialize_seedcore_custody_event_payload(audit_record=audit_record)
    forensic_block = materialized["seedcore:forensic_block"]
    schema = _schema_payload()
    Draft202012Validator(schema).validate(forensic_block)
    assert forensic_block["forensic_block_id"] == "fb-2026-0001"
    assert forensic_block["decision_linkage"]["request_id"] == "req-transfer-2026-0001"
    assert forensic_block["asset_identity"]["asset_id"] == "asset:lot-8841"


def test_materialized_forensic_block_rejects_invalid_existing_shape() -> None:
    audit_record = _build_audit_record()
    audit_record["evidence_bundle"]["forensic_block"] = {
        "@context": "https://seedcore.ai/contexts/forensic-v1.jsonld",
        "@type": "ForensicBlock",
        "forensic_block_id": "fb-2026-0001",
        "block_header": {
            "audit_id": "2b4c76c8-20e2-4222-aa18-c4f1ee212f72",
        },
        "authority_context": {
            "principal_id": "",
        },
        "fingerprint_components": {
            "economic_hash": "sha256:economic-0001",
            "physical_presence_hash": "sha256:physical-0001",
            "reasoning_hash": "sha256:reasoning-0001",
            "actuator_hash": "sha256:actuator-0001",
        },
    }

    with pytest.raises(ValueError, match="forensic_block schema violation"):
        materialize_seedcore_custody_event_payload(audit_record=audit_record)


def test_closure_request_requires_forensic_block_id() -> None:
    payload = {
        "request_id": "req-transfer-2026-0001",
        "closure_id": "closure-transfer-2026-0001",
        "idempotency_key": "idem-closure-2026-0001",
        "closed_at": "2026-04-02T12:00:00Z",
        "evidence_bundle_id": "bundle-2026-0001",
        "forensic_block": {
            "fingerprint_components": {
                "economic_hash": "sha256:economic-0001",
                "physical_presence_hash": "sha256:physical-0001",
                "reasoning_hash": "sha256:reasoning-0001",
                "actuator_hash": "sha256:actuator-0001",
            },
        },
    }
    with pytest.raises(ValidationError):
        AgentActionClosureRequest.model_validate(payload)
