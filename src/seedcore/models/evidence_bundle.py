from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SignerMetadata(BaseModel):
    signer_id: Optional[str] = None
    signer_type: Optional[str] = None
    key_id: Optional[str] = None
    public_key: Optional[str] = None
    proof_type: Optional[str] = None


class ExecutionReceipt(BaseModel):
    receipt_id: str
    proof_type: str = "ed25519"
    signature: str
    payload_hash: str
    signed_payload: Dict[str, Any] = Field(default_factory=dict)
    actuator_endpoint: Optional[str] = None
    actuator_result_hash: Optional[str] = None
    transition_receipt: Optional[Dict[str, Any]] = None
    transition_receipt_hash: Optional[str] = None
    transition_seq: Optional[int] = None
    previous_receipt_hash: Optional[str] = None
    node_id: Optional[str] = None
    signer: Optional[SignerMetadata] = None


class PolicyReceipt(BaseModel):
    receipt_id: str
    issued_at: str
    policy_snapshot: Optional[str] = None
    policy_case_hash: Optional[str] = None
    policy_decision_hash: Optional[str] = None
    execution_token: Dict[str, Any] = Field(default_factory=dict)
    signer: Optional[SignerMetadata] = None


class AssetFingerprint(BaseModel):
    fingerprint_hash: str
    algorithm: str = "sha256"
    asset_id: Optional[str] = None
    source_modalities: List[str] = Field(default_factory=list)
    components: Dict[str, str] = Field(default_factory=dict)


class PreContactEvidence(BaseModel):
    environmental_telemetry: Dict[str, float] = Field(default_factory=dict)
    voc_profile: Dict[str, str] = Field(default_factory=dict)
    vision_baseline: Dict[str, str] = Field(default_factory=dict)


class ManipulationTelemetry(BaseModel):
    commanded_forces: str = "envelope-verified"
    observed_forces: str = "within-tolerance"
    trajectory_hash: Optional[str] = None


class PolicyVerification(BaseModel):
    policy_hash: str
    authorization_token: str


class CustodyTransition(BaseModel):
    from_zone: str = Field(alias="from")
    to_zone: str = Field(alias="to")
    timestamp: str

    model_config = {
        "populate_by_name": True
    }


class SeedCoreCustodyEvent(BaseModel):
    context: Dict[str, str] = Field(
        alias="@context",
        default={
            "@vocab": "https://schema.org/",
            "seedcore": "https://seedcore.ai/schema/"
        }
    )
    type: str = Field(alias="@type", default="seedcore:SeedCoreCustodyEvent")
    id: str = Field(alias="@id")
    device_identity: str
    platform_state: str
    pre_contact_evidence: PreContactEvidence
    manipulation_telemetry: ManipulationTelemetry
    policy_verification: PolicyVerification
    custody_transition: CustodyTransition
    signature: str

    model_config = {
        "populate_by_name": True
    }


class EvidenceBundle(BaseModel):
    intent_ref: str
    executed_at: str
    node_id: Optional[str] = None
    telemetry_snapshot: Dict[str, Any] = Field(default_factory=dict)
    execution_receipt: ExecutionReceipt
    policy_receipt: Optional[PolicyReceipt] = None
    asset_fingerprint: Optional[AssetFingerprint] = None
    custody_event: Optional[SeedCoreCustodyEvent] = None
