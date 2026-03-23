from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SignerMetadata(BaseModel):
    signer_type: str
    signer_id: str
    signing_scheme: str
    key_ref: Optional[str] = None
    attestation_level: str = "baseline"
    node_id: Optional[str] = None
    config_profile: Optional[str] = None


class TransitionReceipt(BaseModel):
    transition_receipt_id: str
    intent_id: str
    execution_token_id: str
    endpoint_id: str
    hardware_uuid: str
    actuator_result_hash: str
    target_zone: Optional[str] = None
    from_zone: Optional[str] = None
    to_zone: Optional[str] = None
    executed_at: str
    receipt_nonce: str
    payload_hash: str
    signer_metadata: SignerMetadata
    signature: str


class PolicyReceipt(BaseModel):
    policy_receipt_id: str
    policy_decision_id: str
    task_id: str
    intent_id: str
    policy_version: Optional[str] = None
    decision: Dict[str, Any] = Field(default_factory=dict)
    evaluated_rules: List[str] = Field(default_factory=list)
    subject_ref: Optional[str] = None
    asset_ref: Optional[str] = None
    authz_disposition: Optional[str] = None
    governed_receipt_hash: Optional[str] = None
    trust_gap_codes: List[str] = Field(default_factory=list)
    timestamp: str
    signer_metadata: SignerMetadata
    signature: str


class AssetFingerprint(BaseModel):
    fingerprint_id: str
    fingerprint_hash: str
    modality_map: Dict[str, str] = Field(default_factory=dict)
    derivation_logic: Dict[str, Any] = Field(default_factory=dict)
    capture_context: Dict[str, Any] = Field(default_factory=dict)
    hardware_witness: Dict[str, Any] = Field(default_factory=dict)
    captured_at: str


class HALCaptureEnvelope(BaseModel):
    hal_capture_id: str
    event_id: str
    device_identity: str
    platform_state: str
    policy_receipt_id: Optional[str] = None
    transition_receipt_id: Optional[str] = None
    media_refs: List[Dict[str, Any]] = Field(default_factory=list)
    environmental_telemetry: Dict[str, float] = Field(default_factory=dict)
    trajectory_hash: Optional[str] = None
    node_id: Optional[str] = None
    captured_at: str
    signer_metadata: SignerMetadata
    signature: str


class EvidenceBundle(BaseModel):
    evidence_bundle_id: str
    task_id: str
    intent_id: str
    intent_ref: Optional[str] = None
    execution_token_id: Optional[str] = None
    policy_receipt_id: Optional[str] = None
    transition_receipt_ids: List[str] = Field(default_factory=list)
    asset_fingerprint: Optional[AssetFingerprint] = None
    evidence_inputs: Dict[str, Any] = Field(default_factory=dict)
    telemetry_refs: List[Dict[str, Any]] = Field(default_factory=list)
    media_refs: List[Dict[str, Any]] = Field(default_factory=list)
    node_id: Optional[str] = None
    signer_metadata: SignerMetadata
    signature: str
    created_at: str
