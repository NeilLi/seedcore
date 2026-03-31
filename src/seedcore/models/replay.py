from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ReplayProjectionKind(str, Enum):
    INTERNAL = "internal"
    AUDITOR = "auditor"
    BUYER = "buyer"
    PUBLIC = "public"


class ReplayTimelineEvent(BaseModel):
    event_id: str
    event_type: str
    timestamp: str
    summary: str
    artifact_ref: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class ReplayVerificationStatus(BaseModel):
    verified: bool = False
    signature_valid: bool = False
    policy_trace_available: bool = False
    evidence_trace_available: bool = False
    tamper_status: str = "unknown"
    issues: List[str] = Field(default_factory=list)
    verified_at: Optional[str] = None
    artifact_results: Dict[str, Any] = Field(default_factory=dict)
    signer_policy: Dict[str, Any] = Field(default_factory=dict)


class ReplayRecord(BaseModel):
    replay_id: str
    subject_type: str
    subject_id: str
    task_id: str
    intent_id: str
    audit_record_id: str
    authz_graph: Dict[str, Any] = Field(default_factory=dict)
    governed_receipt: Dict[str, Any] = Field(default_factory=dict)
    policy_receipt: Dict[str, Any] = Field(default_factory=dict)
    evidence_bundle: Dict[str, Any] = Field(default_factory=dict)
    transition_receipts: List[Dict[str, Any]] = Field(default_factory=list)
    digital_twin_history_refs: List[Dict[str, Any]] = Field(default_factory=list)
    signer_chain: List[Dict[str, Any]] = Field(default_factory=list)
    verification_status: ReplayVerificationStatus = Field(default_factory=ReplayVerificationStatus)
    replay_timeline: List[ReplayTimelineEvent] = Field(default_factory=list)
    public_projection: Dict[str, Any] = Field(default_factory=dict)
    buyer_projection: Dict[str, Any] = Field(default_factory=dict)
    auditor_projection: Dict[str, Any] = Field(default_factory=dict)
    internal_projection: Dict[str, Any] = Field(default_factory=dict)
    audit_record: Dict[str, Any] = Field(default_factory=dict)
    asset_custody_state: Optional[Dict[str, Any]] = None
    custody_transition_refs: List[Dict[str, Any]] = Field(default_factory=list)
    dispute_refs: List[Dict[str, Any]] = Field(default_factory=list)
    jsonld_export: Dict[str, Any] = Field(default_factory=dict)


class TrustPageProjection(BaseModel):
    trust_page_id: Optional[str] = None
    workflow_type: Optional[str] = None
    status: Optional[str] = None
    subject_title: str
    subject_summary: str
    verification_status: Dict[str, Any] = Field(default_factory=dict)
    approvals: Dict[str, Any] = Field(default_factory=dict)
    authorization: Dict[str, Any] = Field(default_factory=dict)
    custody_summary: Dict[str, Any] = Field(default_factory=dict)
    fingerprint_summary: Dict[str, Any] = Field(default_factory=dict)
    policy_summary: Dict[str, Any] = Field(default_factory=dict)
    dispute_summary: Dict[str, Any] = Field(default_factory=dict)
    timeline_summary: List[Dict[str, Any]] = Field(default_factory=list)
    verifiable_claims: List[Dict[str, Any]] = Field(default_factory=list)
    public_media_refs: List[Dict[str, Any]] = Field(default_factory=list)
    public_jsonld_ref: Optional[str] = None
    public_certificate_ref: Optional[str] = None


class VerificationResult(BaseModel):
    verification_id: str
    reference_type: str
    reference_id: str
    subject_id: Optional[str] = None
    subject_type: Optional[str] = None
    verified: bool
    signature_valid: bool
    policy_trace_available: bool
    evidence_trace_available: bool
    tamper_status: str
    verification_time: str
    public_claims: List[Dict[str, Any]] = Field(default_factory=list)
    reason: Optional[str] = None
    trust_url: Optional[str] = None
    public_jsonld_ref: Optional[str] = None


class TrustCertificate(BaseModel):
    certificate_id: str
    public_id: str
    subject_type: str
    subject_id: str
    verification_status: Dict[str, Any] = Field(default_factory=dict)
    trust_assertions: List[Dict[str, Any]] = Field(default_factory=list)
    public_claims: List[Dict[str, Any]] = Field(default_factory=list)
    trust_gap_codes: List[str] = Field(default_factory=list)
    trust_gap_details: List[Dict[str, Any]] = Field(default_factory=list)
    owner_context: Dict[str, Any] = Field(default_factory=dict)
    issued_at: str
    expires_at: Optional[str] = None
    signer_metadata: Dict[str, Any] = Field(default_factory=dict)
    signature: str


class PublicTrustReference(BaseModel):
    v: int = 1
    jti: str
    lookup_key: str
    lookup_value: str
    audit_id: str
    subject_type: str
    subject_id: str
    issued_at: str
    expires_at: str
    projection_version: str = "v1"
