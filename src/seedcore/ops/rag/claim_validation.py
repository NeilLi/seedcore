from __future__ import annotations

from typing import Iterable

from seedcore.models.rag import RAGDraftAnswer, RAGEvidenceBundle, VerifiedRAGClaim


def validate_rag_claims_and_citations(
    *,
    bundle: RAGEvidenceBundle,
    draft_answer: RAGDraftAnswer,
    claims: Iterable[VerifiedRAGClaim],
) -> None:
    """
    Validates that all cited evidence item IDs belong to the authorized evidence bundle,
    and that claims properly align with the draft answer.
    """
    if draft_answer.evidence_bundle_id != bundle.bundle_id:
        raise ValueError(
            f"Draft answer evidence_bundle_id={draft_answer.evidence_bundle_id} "
            f"does not match bundle_id={bundle.bundle_id}"
        )

    authorized_item_ids = set(bundle.evidence_item_ids)

    # 1. Validate Draft Answer Citations
    for cite_id in draft_answer.cited_evidence_item_ids:
        if cite_id not in authorized_item_ids:
            raise ValueError(
                f"Draft answer cites unauthorized or unknown evidence item ID: {cite_id}"
            )

    # 2. Validate Verified Claims Citations & References
    for claim in claims:
        if claim.draft_answer_id != draft_answer.draft_answer_id:
            raise ValueError(
                f"Verified claim draft_answer_id={claim.draft_answer_id} "
                f"does not match draft_answer_id={draft_answer.draft_answer_id}"
            )
        for claim_cite_id in claim.evidence_item_ids:
            if claim_cite_id not in authorized_item_ids:
                raise ValueError(
                    f"Verified claim cites unauthorized or unknown evidence item ID: {claim_cite_id}"
                )
