from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Iterable, Sequence

from seedcore.models.rag import (
    RAGAuthorizationDecision,
    RAGAuthorizationEnvelope,
    RAGCandidateChunk,
    RAGDeniedCandidateSummary,
    RAGEvidenceBundle,
    RAGEvidenceItem,
    RAGEvidencePromotionResult,
)


def promote_authorized_rag_candidates(
    *,
    envelope: RAGAuthorizationEnvelope,
    candidates: Sequence[RAGCandidateChunk],
    decisions: Iterable[RAGAuthorizationDecision],
    bundle_id: str,
    created_at: datetime,
    evidence_item_id_prefix: str = "rag-evidence",
) -> RAGEvidencePromotionResult:
    """Promote only PDP-allowed retrieval candidates into model-visible evidence."""

    decisions_by_chunk_id: dict[str, RAGAuthorizationDecision] = {}
    for decision in decisions:
        if decision.chunk_id in decisions_by_chunk_id:
            raise ValueError(f"duplicate authorization decision for chunk_id={decision.chunk_id}")
        decisions_by_chunk_id[decision.chunk_id] = decision

    evidence_items: list[RAGEvidenceItem] = []
    denied_reason_counts: Counter[str] = Counter()
    missing_decision_count = 0

    for candidate in candidates:
        chunk_id = candidate.chunk.chunk_id
        decision = decisions_by_chunk_id.get(chunk_id)
        if decision is None:
            missing_decision_count += 1
            denied_reason_counts["missing_chunk_authorization_decision"] += 1
            continue
        if decision.disposition != "allow":
            denied_reason_counts[decision.reason_code] += 1
            continue

        evidence_items.append(
            RAGEvidenceItem(
                evidence_item_id=f"{evidence_item_id_prefix}:{decision.decision_id}",
                document_id=candidate.document.document_id,
                document_hash=candidate.document.document_hash,
                chunk_id=chunk_id,
                chunk_hash=candidate.chunk.chunk_hash,
                source_ref=candidate.document.source.source_ref,
                acl_snapshot_id=candidate.chunk.acl_snapshot.acl_snapshot_id,
                acl_snapshot_hash=candidate.chunk.acl_snapshot.acl_snapshot_hash,
                authorization_decision_id=decision.decision_id,
                policy_snapshot_ref=decision.policy_snapshot_ref,
                policy_version=decision.policy_version,
                principal_ref=envelope.principal_ref,
                workflow_ref=envelope.workflow_ref,
                purpose=envelope.purpose,
                retrieval_timestamp=candidate.retrieved_at,
                retriever_version=candidate.retriever_version,
                index_snapshot_ref=candidate.index_snapshot_ref,
                text_ref=candidate.chunk.text_ref,
            )
        )

    denied_summary = RAGDeniedCandidateSummary(
        candidate_count=len(candidates),
        denied_candidate_count=len(candidates) - len(evidence_items),
        missing_decision_count=missing_decision_count,
        reason_counts=dict(denied_reason_counts),
    )
    evidence_bundle = RAGEvidenceBundle(
        bundle_id=bundle_id,
        authorization_envelope_id=envelope.envelope_id,
        principal_ref=envelope.principal_ref,
        workflow_ref=envelope.workflow_ref,
        purpose=envelope.purpose,
        policy_snapshot_ref=envelope.policy_snapshot_ref,
        created_at=created_at,
        evidence_items=evidence_items,
        denied_summary=denied_summary,
        retriever_versions=sorted({candidate.retriever_version for candidate in candidates}),
        index_snapshot_refs=sorted({candidate.index_snapshot_ref for candidate in candidates}),
    )
    return RAGEvidencePromotionResult(
        evidence_items=evidence_items,
        denied_summary=denied_summary,
        evidence_bundle=evidence_bundle,
    )
