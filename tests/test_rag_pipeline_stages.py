from __future__ import annotations

from datetime import datetime, timezone

import pytest

from seedcore.models.rag import (
    ACLSnapshot,
    RAGDeniedCandidateSummary,
    RAGDraftAnswer,
    RAGEvidenceBundle,
    RAGEvidenceItem,
    RAGTrace,
    VerifiedRAGClaim,
)
from seedcore.ops.rag import (
    RAGClaimValidationError,
    RAGParseError,
    parse_guarded_rag_response,
    validate_rag_claims_and_citations,
)

NOW = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)


def test_output_parser_extracts_scratchpad_and_response() -> None:
    raw_output = """<scratchpad>
    Here is some step-by-step thinking.
    </scratchpad>
    <response>
    {
        "status": "success",
        "answer": "Here is the verified response."
    }
    </response>"""

    parsed = parse_guarded_rag_response(raw_output)
    assert parsed.scratchpad == "Here is some step-by-step thinking."
    assert "success" in parsed.response_body
    assert "verified response" in parsed.response_body


def test_output_parser_raises_on_missing_or_malformed_tags() -> None:
    with pytest.raises(RAGParseError, match="rag_response_missing"):
        parse_guarded_rag_response("<scratchpad>Thinking...</scratchpad> Body text.")

    with pytest.raises(RAGParseError, match="rag_response_malformed"):
        parse_guarded_rag_response("<response>Unclosed body tag")

    with pytest.raises(RAGParseError, match="rag_scratchpad_missing"):
        parse_guarded_rag_response("<response>Body</response>", require_scratchpad=True)


def test_output_parser_rejects_duplicate_or_empty_response() -> None:
    with pytest.raises(RAGParseError, match="rag_response_malformed"):
        parse_guarded_rag_response("<response>one</response><response>two</response>")

    with pytest.raises(RAGParseError, match="rag_response_empty"):
        parse_guarded_rag_response("<response>   </response>")


def test_claim_validation_happy_path() -> None:
    bundle = _bundle()
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=["ev-1"],
        created_at=NOW,
    )
    claim = VerifiedRAGClaim(
        claim_id="claim-1",
        draft_answer_id="draft-1",
        claim_text_ref="text-ref-1",
        support_status="supported",
        evidence_item_ids=["ev-1"],
        verifier_ref="verifier-1",
        verified_at=NOW,
    )
    # Should complete without error
    validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[claim])


def test_claim_validation_unauthorized_draft_citation() -> None:
    bundle = _bundle()
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=["ev-unknown"],  # Unauthorized!
        created_at=NOW,
    )
    with pytest.raises(RAGClaimValidationError, match="rag_draft_unknown_citation_id"):
        validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[])


def test_claim_validation_unauthorized_claim_citation() -> None:
    bundle = _bundle()
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=["ev-1"],
        created_at=NOW,
    )
    claim = VerifiedRAGClaim(
        claim_id="claim-1",
        draft_answer_id="draft-1",
        claim_text_ref="text-ref-1",
        support_status="supported",
        evidence_item_ids=["ev-unknown"],  # Unauthorized!
        verifier_ref="verifier-1",
        verified_at=NOW,
    )
    with pytest.raises(RAGClaimValidationError, match="rag_claim_unknown_citation_id"):
        validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[claim])


def test_claim_validation_rejects_duplicate_draft_citations() -> None:
    bundle = _bundle()
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=["ev-1", "ev-1"],
        created_at=NOW,
    )

    with pytest.raises(RAGClaimValidationError, match="rag_draft_duplicate_citation_ids"):
        validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[])


def test_claim_validation_rejects_claim_citation_not_in_draft() -> None:
    bundle = _bundle(include_second_item=True)
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=["ev-1"],
        created_at=NOW,
    )
    claim = VerifiedRAGClaim(
        claim_id="claim-1",
        draft_answer_id="draft-1",
        claim_text_ref="text-ref-1",
        support_status="supported",
        evidence_item_ids=["ev-2"],
        verifier_ref="verifier-1",
        verified_at=NOW,
    )

    with pytest.raises(RAGClaimValidationError, match="rag_claim_citation_not_in_draft"):
        validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[claim])


def test_claim_validation_rejects_claim_citation_when_draft_has_no_citations() -> None:
    bundle = _bundle()
    draft = RAGDraftAnswer(
        draft_answer_id="draft-1",
        evidence_bundle_id="bundle-1",
        answer_text_ref="ref-1",
        cited_evidence_item_ids=[],
        created_at=NOW,
    )
    claim = VerifiedRAGClaim(
        claim_id="claim-1",
        draft_answer_id="draft-1",
        claim_text_ref="text-ref-1",
        support_status="supported",
        evidence_item_ids=["ev-1"],
        verifier_ref="verifier-1",
        verified_at=NOW,
    )

    with pytest.raises(RAGClaimValidationError, match="rag_claim_citation_not_in_draft"):
        validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft, claims=[claim])


def test_reconciled_rag_trace_statuses_require_rejection_reasons() -> None:
    for final_status in ("blocked", "escalated", "abstained"):
        with pytest.raises(ValueError, match="rejection_reason_codes"):
            RAGTrace(
                trace_id=f"trace-{final_status}",
                authorization_envelope_id="env-1",
                created_at=NOW,
                final_status=final_status,
            )

        trace = RAGTrace(
            trace_id=f"trace-{final_status}-with-reason",
            authorization_envelope_id="env-1",
            created_at=NOW,
            final_status=final_status,
            rejection_reason_codes=[f"rag_{final_status}"],
        )
        assert trace.final_status == final_status


def _bundle(*, include_second_item: bool = False) -> RAGEvidenceBundle:
    acl = ACLSnapshot(
        acl_snapshot_id="acl-1",
        acl_snapshot_hash="hash-1",
        source_system="test",
        captured_at=NOW,
    )
    item = RAGEvidenceItem(
        evidence_item_id="ev-1",
        document_id="doc-1",
        document_hash="doc-hash-1",
        chunk_id="chunk-1",
        chunk_hash="chunk-hash-1",
        source_ref="ref-1",
        acl_snapshot_id="acl-1",
        acl_snapshot_hash="hash-1",
        authorization_decision_id="dec-1",
        policy_snapshot_ref="policy-ref",
        policy_version="v1",
        principal_ref="principal:user",
        workflow_ref="workflow:1",
        purpose="testing",
        retrieval_timestamp=NOW,
        retriever_version="v1",
        index_snapshot_ref="idx-1",
        text_ref="text-1",
    )
    items = [item]
    if include_second_item:
        items.append(
            item.model_copy(
                update={
                    "evidence_item_id": "ev-2",
                    "document_id": "doc-2",
                    "document_hash": "doc-hash-2",
                    "chunk_id": "chunk-2",
                    "chunk_hash": "chunk-hash-2",
                    "authorization_decision_id": "dec-2",
                    "text_ref": "text-2",
                }
            )
        )
    denied = RAGDeniedCandidateSummary(
        candidate_count=len(items),
        denied_candidate_count=0,
    )
    return RAGEvidenceBundle(
        bundle_id="bundle-1",
        authorization_envelope_id="env-1",
        principal_ref="principal:user",
        workflow_ref="workflow:1",
        purpose="testing",
        policy_snapshot_ref="policy-ref",
        created_at=NOW,
        evidence_items=items,
        denied_summary=denied,
    )
