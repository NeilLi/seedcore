from __future__ import annotations

from typing import Iterable

from seedcore.models.rag import RAGDraftAnswer, RAGEvidenceBundle, VerifiedRAGClaim


class RAGClaimValidationError(ValueError):
    def __init__(self, reason_code: str, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {detail}")


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
        raise RAGClaimValidationError(
            "rag_draft_bundle_mismatch",
            f"draft_answer.evidence_bundle_id={draft_answer.evidence_bundle_id} "
            f"does not match bundle.bundle_id={bundle.bundle_id}",
        )

    authorized_item_ids = set(bundle.evidence_item_ids)
    draft_cited_ids = set(draft_answer.cited_evidence_item_ids)

    duplicate_draft_ids = _duplicates(draft_answer.cited_evidence_item_ids)
    if duplicate_draft_ids:
        raise RAGClaimValidationError(
            "rag_draft_duplicate_citation_ids",
            "draft answer cites duplicate evidence_item_id values",
        )

    for cite_id in draft_answer.cited_evidence_item_ids:
        if cite_id not in authorized_item_ids:
            raise RAGClaimValidationError(
                "rag_draft_unknown_citation_id",
                "draft answer cites evidence_item_id outside the authorized bundle",
            )

    claim_list = list(claims)
    duplicate_claim_ids = _duplicates(claim.claim_id for claim in claim_list)
    if duplicate_claim_ids:
        raise RAGClaimValidationError(
            "rag_duplicate_claim_ids",
            "verified claims contain duplicate claim_id values",
        )

    for claim in claim_list:
        if claim.draft_answer_id != draft_answer.draft_answer_id:
            raise RAGClaimValidationError(
                "rag_claim_draft_mismatch",
                f"claim.draft_answer_id={claim.draft_answer_id} "
                f"does not match draft_answer.draft_answer_id={draft_answer.draft_answer_id}",
            )
        duplicate_claim_cite_ids = _duplicates(claim.evidence_item_ids)
        if duplicate_claim_cite_ids:
            raise RAGClaimValidationError(
                "rag_claim_duplicate_citation_ids",
                "verified claim cites duplicate evidence_item_id values",
            )
        for claim_cite_id in claim.evidence_item_ids:
            if claim_cite_id not in authorized_item_ids:
                raise RAGClaimValidationError(
                    "rag_claim_unknown_citation_id",
                    "verified claim cites evidence_item_id outside the authorized bundle",
                )
            if claim_cite_id not in draft_cited_ids:
                raise RAGClaimValidationError(
                    "rag_claim_citation_not_in_draft",
                    "verified claim cites evidence_item_id not cited by the draft answer",
                )


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicate_values: set[str] = set()
    for value in values:
        if value in seen:
            duplicate_values.add(value)
        seen.add(value)
    return sorted(duplicate_values)
