from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


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
    telemetry_snapshot: Dict[str, Any] = Field(default_factory=dict)
    execution_receipt: ExecutionReceipt
    custody_event: Optional[SeedCoreCustodyEvent] = None
