from __future__ import annotations

from typing import Any, Mapping

from jsonschema import Draft202012Validator


FORENSIC_BLOCK_CONTRACT_ID = "seedcore.forensic_block.v1"
FORENSIC_BLOCK_CONTEXT = "https://seedcore.ai/contexts/forensic-v1.jsonld"

FORENSIC_BLOCK_JSON_SCHEMA: dict[str, Any] = {
    "$id": FORENSIC_BLOCK_CONTRACT_ID,
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": FORENSIC_BLOCK_CONTRACT_ID,
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "@context": {"type": "string", "const": FORENSIC_BLOCK_CONTEXT},
        "@type": {"type": "string", "const": "ForensicBlock"},
        "forensic_block_id": {"type": "string", "minLength": 1},
        "block_header": {
            "type": "object",
            "additionalProperties": True,
            "required": ["forensic_block_id", "audit_id", "timestamp", "version"],
            "properties": {
                "forensic_block_id": {"type": "string", "minLength": 1},
                "audit_id": {"type": "string", "minLength": 1},
                "timestamp": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
            },
        },
        "decision_linkage": {
            "type": "object",
            "additionalProperties": True,
            "required": ["request_id", "disposition", "decision_hash"],
            "properties": {
                "request_id": {"type": "string", "minLength": 1},
                "disposition": {"type": "string", "minLength": 1},
                "decision_hash": {"type": "string", "minLength": 1},
                "policy_receipt_id": {"type": ["string", "null"]},
                "policy_snapshot_ref": {"type": ["string", "null"]},
            },
        },
        "asset_identity": {
            "type": "object",
            "additionalProperties": True,
            "required": ["asset_id"],
            "properties": {
                "asset_id": {"type": "string", "minLength": 1},
                "lot_id": {"type": ["string", "null"]},
                "product_ref": {"type": ["string", "null"]},
                "quote_ref": {"type": ["string", "null"]},
            },
        },
        "authority_context": {
            "type": "object",
            "additionalProperties": True,
            "required": ["principal_id", "hardware_fingerprint", "delegation_chain_hash"],
            "properties": {
                "principal_id": {"type": "string", "minLength": 1},
                "owner_id": {"type": ["string", "null"]},
                "hardware_fingerprint": {"type": "string", "minLength": 1},
                "kms_key_ref": {"type": ["string", "null"]},
                "delegation_chain_hash": {"type": "string", "minLength": 1},
                "execution_token_id": {"type": ["string", "null"]},
                "organization_ref": {"type": ["string", "null"]},
            },
        },
        "fingerprint_components": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "economic_hash",
                "physical_presence_hash",
                "reasoning_hash",
                "actuator_hash",
            ],
            "properties": {
                "economic_hash": {"type": "string", "minLength": 1},
                "physical_presence_hash": {"type": "string", "minLength": 1},
                "reasoning_hash": {"type": "string", "minLength": 1},
                "actuator_hash": {"type": "string", "minLength": 1},
            },
        },
        "economic_evidence": {
            "type": "object",
            "additionalProperties": True,
            "required": ["transaction_hash", "asset_identity"],
            "properties": {
                "transaction_hash": {"type": "string", "minLength": 1},
                "asset_identity": {"type": "string", "minLength": 1},
            },
        },
        "spatial_evidence": {
            "type": "object",
            "additionalProperties": True,
            "required": ["presence_proof_hash", "coordinate_binding"],
            "properties": {
                "presence_proof_hash": {"type": "string", "minLength": 1},
                "coordinate_binding": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["coordinate_ref"],
                    "properties": {
                        "coordinate_ref": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
        "cognitive_evidence": {
            "type": "object",
            "additionalProperties": True,
            "required": ["decision", "reasoning_trace_hash"],
            "properties": {
                "decision": {"type": "string", "minLength": 1},
                "reasoning_trace_hash": {"type": "string", "minLength": 1},
            },
        },
        "physical_evidence": {
            "type": "object",
            "additionalProperties": True,
            "required": ["actuator_telemetry"],
            "properties": {
                "actuator_telemetry": {
                    "type": "object",
                    "additionalProperties": True,
                    "required": ["motor_torque_hash"],
                    "properties": {
                        "motor_torque_hash": {"type": "string", "minLength": 1},
                    },
                }
            },
        },
        "settlement_status": {
            "type": "object",
            "additionalProperties": True,
        },
    },
    "required": [
        "@context",
        "@type",
        "forensic_block_id",
        "block_header",
        "decision_linkage",
        "asset_identity",
        "authority_context",
        "fingerprint_components",
        "economic_evidence",
        "spatial_evidence",
        "cognitive_evidence",
        "physical_evidence",
    ],
}

_FORENSIC_BLOCK_VALIDATOR = Draft202012Validator(FORENSIC_BLOCK_JSON_SCHEMA)


def validate_forensic_block_payload(payload: Mapping[str, Any]) -> None:
    errors = sorted(_FORENSIC_BLOCK_VALIDATOR.iter_errors(dict(payload)), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    first = errors[0]
    path = ".".join(str(item) for item in first.absolute_path)
    location = path or "$"
    raise ValueError(f"forensic_block schema violation at '{location}': {first.message}")
