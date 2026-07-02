from __future__ import annotations

from datetime import datetime
from typing import Sequence

from seedcore.models.rag import (
    RAGAuthorizationDecision,
    RAGAuthorizationEnvelope,
    RAGCandidateChunk,
)

CLASSIFICATION_LEVELS = {
    "public": 0,
    "confidential": 1,
    "restricted": 2,
}


def authorize_retrieved_chunks(
    *,
    envelope: RAGAuthorizationEnvelope,
    candidates: Sequence[RAGCandidateChunk],
    decided_at: datetime,
) -> list[RAGAuthorizationDecision]:
    """
    Deterministic local PDP callout simulating RAG policy gating.
    Returns an authorization decision for each candidate chunk.
    """
    decisions: list[RAGAuthorizationDecision] = []
    ceiling = envelope.classification_ceiling.lower().strip()
    ceiling_level = CLASSIFICATION_LEVELS.get(ceiling, 0)

    for idx, candidate in enumerate(candidates):
        chunk_id = candidate.chunk.chunk_id
        doc_classification = candidate.document.classification.lower().strip()
        doc_level = CLASSIFICATION_LEVELS.get(doc_classification, 2)

        if doc_level > ceiling_level:
            disposition = "deny"
            reason_code = "classification_ceiling"
        else:
            disposition = "allow"
            reason_code = "rag_chunk_allowed"

        decisions.append(
            RAGAuthorizationDecision(
                decision_id=f"dec-{envelope.envelope_id}-{idx}",
                chunk_id=chunk_id,
                disposition=disposition,
                reason_code=reason_code,
                policy_snapshot_ref=envelope.policy_snapshot_ref,
                policy_version=envelope.policy_version,
                decided_at=decided_at,
            )
        )

    return decisions
