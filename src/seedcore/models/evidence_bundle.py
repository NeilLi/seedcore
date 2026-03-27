from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class KeyBindingProof(BaseModel):
    binding_type: str = "none"
    key_handle: Optional[str] = None
    key_label: Optional[str] = None
    certificate_chain: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AttestationProof(BaseModel):
    attestation_type: str = "none"
    ak_key_ref: Optional[str] = None
    quote: Optional[str] = None
    endorsement_chain: List[str] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)
    issued_at: Optional[str] = None


class ReplayProof(BaseModel):
    receipt_nonce: Optional[str] = None
    receipt_counter: Optional[int] = None
    previous_receipt_hash: Optional[str] = None


class TransparencyProof(BaseModel):
    status: str = "not_configured"
    log_url: Optional[str] = None
    entry_id: Optional[str] = None
    integrated_time: Optional[str] = None
    proof_hash: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class TrustProof(BaseModel):
    signer_profile: str
    trust_anchor_type: str
    key_algorithm: str
    key_ref: str
    public_key_fingerprint: str
    key_binding: Optional[KeyBindingProof] = None
    attestation: Optional[AttestationProof] = None
    replay: Optional[ReplayProof] = None
    revocation_id: Optional[str] = None
    transparency: Optional[TransparencyProof] = None


class TrustBundleKey(BaseModel):
    key_ref: str
    key_algorithm: str
    public_key: str
    trust_anchor_type: str
    signer_profile: Optional[str] = None
    endpoint_id: Optional[str] = None
    node_id: Optional[str] = None
    revocation_id: Optional[str] = None
    attestation_root: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TrustBundleTransparencyConfig(BaseModel):
    enabled: bool = False
    log_url: Optional[str] = None
    public_key: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TrustBundle(BaseModel):
    version: str = "phase_a_v1"
    trusted_keys: Dict[str, TrustBundleKey] = Field(default_factory=dict)
    endpoint_bindings: Dict[str, str] = Field(default_factory=dict)
    node_bindings: Dict[str, str] = Field(default_factory=dict)
    accepted_trust_anchor_types: List[str] = Field(default_factory=list)
    attestation_roots: Dict[str, str] = Field(default_factory=dict)
    revoked_keys: List[str] = Field(default_factory=list)
    revoked_nodes: List[str] = Field(default_factory=list)
    revocation_cutoffs: Dict[str, str] = Field(default_factory=dict)
    transparency: Optional[TrustBundleTransparencyConfig] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


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
    workflow_type: Optional[str] = None
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
    trust_proof: Optional[TrustProof] = None


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
    decision_graph_snapshot_hash: Optional[str] = None
    decision_graph_snapshot_version: Optional[str] = None
    trust_gap_codes: List[str] = Field(default_factory=list)
    timestamp: str
    signer_metadata: SignerMetadata
    signature: str
    trust_proof: Optional[TrustProof] = None


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
    trust_proof: Optional[TrustProof] = None


class EvidenceBundle(BaseModel):
    evidence_bundle_id: str
    task_id: str
    intent_id: str
    intent_ref: Optional[str] = None
    execution_token_id: Optional[str] = None
    policy_receipt_id: Optional[str] = None
    decision_graph_snapshot_hash: Optional[str] = None
    decision_graph_snapshot_version: Optional[str] = None
    transition_receipt_ids: List[str] = Field(default_factory=list)
    asset_fingerprint: Optional[AssetFingerprint] = None
    evidence_inputs: Dict[str, Any] = Field(default_factory=dict)
    telemetry_refs: List[Dict[str, Any]] = Field(default_factory=list)
    media_refs: List[Dict[str, Any]] = Field(default_factory=list)
    node_id: Optional[str] = None
    signer_metadata: SignerMetadata
    signature: str
    created_at: str
    trust_proof: Optional[TrustProof] = None
