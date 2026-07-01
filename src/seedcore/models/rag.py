from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


RAGAuthorizationDisposition = Literal["allow", "deny", "quarantine"]
RAGFinalStatus = Literal[
    "draft",
    "accepted",
    "rejected",
    "quarantined",
    "blocked",
    "escalated",
    "abstained",
]
RAGSourceType = Literal[
    "database",
    "document_store",
    "object_store",
    "filesystem",
    "memory",
    "wiki",
    "other",
]
RAGSupportStatus = Literal["supported", "unsupported", "contradicted", "unverified"]


class RAGAuthorizationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope_id: str
    principal_ref: str
    workflow_ref: str
    purpose: str
    policy_snapshot_ref: str
    policy_version: str
    issued_at: datetime
    expires_at: Optional[datetime] = None
    signed_context_refs: List[str] = Field(default_factory=list)
    context_hash: Optional[str] = None


class ACLSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    acl_snapshot_id: str
    acl_snapshot_hash: str
    source_system: str
    captured_at: datetime
    version: Optional[str] = None


class DocumentSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    source_type: RAGSourceType
    source_ref: str
    tenant_ref: Optional[str] = None


class RAGDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    document_hash: str
    source: DocumentSource
    acl_snapshot: ACLSnapshot
    title_ref: Optional[str] = None
    metadata_hash: Optional[str] = None


class RAGChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    document_id: str
    chunk_hash: str
    ordinal: int = Field(ge=0)
    text_ref: str
    acl_snapshot: ACLSnapshot
    metadata_hash: Optional[str] = None


class RAGCandidateChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document: RAGDocument
    chunk: RAGChunk
    retrieval_score: float = Field(ge=0)
    retriever_version: str
    index_snapshot_ref: str
    retrieved_at: datetime

    @model_validator(mode="after")
    def _chunk_matches_document(self) -> "RAGCandidateChunk":
        if self.chunk.document_id != self.document.document_id:
            raise ValueError("chunk.document_id must match document.document_id")
        return self


class RAGAuthorizationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    chunk_id: str
    disposition: RAGAuthorizationDisposition
    reason_code: str
    policy_snapshot_ref: str
    policy_version: str
    decided_at: datetime


class RAGEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_item_id: str
    document_id: str
    document_hash: str
    chunk_id: str
    chunk_hash: str
    source_ref: str
    acl_snapshot_id: str
    acl_snapshot_hash: str
    authorization_decision_id: str
    authorization_disposition: Literal["allow"] = "allow"
    policy_snapshot_ref: str
    policy_version: str
    principal_ref: str
    workflow_ref: str
    purpose: str
    retrieval_timestamp: datetime
    retriever_version: str
    index_snapshot_ref: str
    text_ref: str


class RAGDeniedCandidateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_count: int = Field(ge=0)
    denied_candidate_count: int = Field(ge=0)
    missing_decision_count: int = Field(default=0, ge=0)
    reason_counts: Dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_are_consistent(self) -> "RAGDeniedCandidateSummary":
        if self.denied_candidate_count > self.candidate_count:
            raise ValueError("denied_candidate_count cannot exceed candidate_count")
        for reason, count in self.reason_counts.items():
            if not reason:
                raise ValueError("reason_counts keys must be non-empty")
            if count < 0:
                raise ValueError("reason_counts values must be non-negative")
        return self


class RAGEvidenceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    authorization_envelope_id: str
    principal_ref: str
    workflow_ref: str
    purpose: str
    policy_snapshot_ref: str
    created_at: datetime
    evidence_items: List[RAGEvidenceItem] = Field(default_factory=list)
    denied_summary: RAGDeniedCandidateSummary
    retriever_versions: List[str] = Field(default_factory=list)
    index_snapshot_refs: List[str] = Field(default_factory=list)
    bundle_hash: Optional[str] = None

    @model_validator(mode="after")
    def _bundle_counts_match_items(self) -> "RAGEvidenceBundle":
        authorized_count = len(self.evidence_items)
        total_count = self.denied_summary.candidate_count
        denied_count = self.denied_summary.denied_candidate_count
        if total_count < authorized_count + denied_count:
            raise ValueError("candidate_count must cover authorized and denied candidates")
        for item in self.evidence_items:
            if item.principal_ref != self.principal_ref:
                raise ValueError("evidence item principal_ref must match bundle")
            if item.workflow_ref != self.workflow_ref:
                raise ValueError("evidence item workflow_ref must match bundle")
            if item.purpose != self.purpose:
                raise ValueError("evidence item purpose must match bundle")
            if item.policy_snapshot_ref != self.policy_snapshot_ref:
                raise ValueError("evidence item policy_snapshot_ref must match bundle")
        return self

    @property
    def evidence_item_ids(self) -> List[str]:
        return [item.evidence_item_id for item in self.evidence_items]


class RAGEvidencePromotionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_items: List[RAGEvidenceItem] = Field(default_factory=list)
    denied_summary: RAGDeniedCandidateSummary
    evidence_bundle: RAGEvidenceBundle


class RAGDraftAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft_answer_id: str
    evidence_bundle_id: str
    answer_text_ref: str
    cited_evidence_item_ids: List[str] = Field(default_factory=list)
    created_at: datetime


class VerifiedRAGClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    draft_answer_id: str
    claim_text_ref: str
    support_status: RAGSupportStatus
    evidence_item_ids: List[str] = Field(default_factory=list)
    verifier_ref: str
    verified_at: datetime

    @model_validator(mode="after")
    def _supported_claims_cite_evidence(self) -> "VerifiedRAGClaim":
        if self.support_status == "supported" and not self.evidence_item_ids:
            raise ValueError("supported claims require at least one evidence_item_id")
        return self


class RAGTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    authorization_envelope_id: str
    created_at: datetime
    final_status: RAGFinalStatus
    evidence_bundle_id: Optional[str] = None
    draft_answer_id: Optional[str] = None
    verified_claim_ids: List[str] = Field(default_factory=list)
    policy_decision_ids: List[str] = Field(default_factory=list)
    denied_candidate_count: int = Field(default=0, ge=0)
    rejection_reason_codes: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _accepted_traces_have_closure_refs(self) -> "RAGTrace":
        if self.final_status == "accepted":
            if not self.evidence_bundle_id:
                raise ValueError("accepted RAG traces require evidence_bundle_id")
            if not self.draft_answer_id:
                raise ValueError("accepted RAG traces require draft_answer_id")
            if not self.verified_claim_ids:
                raise ValueError("accepted RAG traces require verified_claim_ids")
            if not self.policy_decision_ids:
                raise ValueError("accepted RAG traces require policy_decision_ids")
        degraded_statuses = {
            "rejected",
            "quarantined",
            "blocked",
            "escalated",
            "abstained",
        }
        if self.final_status in degraded_statuses and not self.rejection_reason_codes:
            raise ValueError(
                "rag_trace_degraded_status_requires_rejection_reason_codes"
            )
        return self
