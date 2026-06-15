from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from seedcore.models.rag import (
    ACLSnapshot,
    DocumentSource,
    RAGAuthorizationDecision,
    RAGAuthorizationEnvelope,
    RAGCandidateChunk,
    RAGChunk,
    RAGDocument,
    RAGTrace,
    VerifiedRAGClaim,
)
from seedcore.ops.rag import promote_authorized_rag_candidates


NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


def test_promote_authorized_rag_candidates_excludes_denied_content() -> None:
    envelope = _envelope()
    allowed = _candidate("doc-1", "chunk-1", "txt://allowed")
    denied = _candidate("doc-2", "chunk-2", "txt://denied")
    missing = _candidate("doc-3", "chunk-3", "txt://missing-decision")

    result = promote_authorized_rag_candidates(
        envelope=envelope,
        candidates=[allowed, denied, missing],
        decisions=[
            _decision("decision-allow", "chunk-1", "allow", "rag_chunk_allowed"),
            _decision("decision-deny", "chunk-2", "deny", "acl_mismatch"),
        ],
        bundle_id="bundle-1",
        created_at=NOW,
    )

    assert [item.chunk_id for item in result.evidence_items] == ["chunk-1"]
    assert result.evidence_items[0].authorization_decision_id == "decision-allow"
    assert result.evidence_bundle.evidence_item_ids == ["rag-evidence:decision-allow"]
    assert result.denied_summary.denied_candidate_count == 2
    assert result.denied_summary.missing_decision_count == 1
    assert result.denied_summary.reason_counts == {
        "acl_mismatch": 1,
        "missing_chunk_authorization_decision": 1,
    }
    assert "chunk-2" not in result.denied_summary.model_dump_json()
    assert "txt://denied" not in result.denied_summary.model_dump_json()


def test_rag_chunk_document_mismatch_is_rejected() -> None:
    document = _document("doc-1")
    chunk = _chunk("doc-2", "chunk-1", "txt://chunk")

    with pytest.raises(ValidationError):
        RAGCandidateChunk(
            document=document,
            chunk=chunk,
            retrieval_score=0.8,
            retriever_version="fixture-retriever.v1",
            index_snapshot_ref="index-snapshot-1",
            retrieved_at=NOW,
        )


def test_supported_rag_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        VerifiedRAGClaim(
            claim_id="claim-1",
            draft_answer_id="draft-1",
            claim_text_ref="txt://claim",
            support_status="supported",
            evidence_item_ids=[],
            verifier_ref="rag-claim-verifier.v1",
            verified_at=NOW,
        )


def test_accepted_rag_trace_requires_policy_decisions() -> None:
    with pytest.raises(ValidationError):
        RAGTrace(
            trace_id="trace-1",
            authorization_envelope_id="rag-envelope-1",
            created_at=NOW,
            final_status="accepted",
            evidence_bundle_id="bundle-1",
            draft_answer_id="draft-1",
            verified_claim_ids=["claim-1"],
            policy_decision_ids=[],
        )


def _envelope() -> RAGAuthorizationEnvelope:
    return RAGAuthorizationEnvelope(
        envelope_id="rag-envelope-1",
        principal_ref="principal:operator",
        workflow_ref="workflow:rct-1",
        purpose="answer_operator_question",
        policy_snapshot_ref="policy-snapshot-1",
        policy_version="policy.v1",
        issued_at=NOW,
    )


def _acl(document_id: str) -> ACLSnapshot:
    return ACLSnapshot(
        acl_snapshot_id=f"acl-{document_id}",
        acl_snapshot_hash=f"acl-hash-{document_id}",
        source_system="fixture-rag",
        captured_at=NOW,
    )


def _document(document_id: str) -> RAGDocument:
    return RAGDocument(
        document_id=document_id,
        document_hash=f"doc-hash-{document_id}",
        source=DocumentSource(
            source_id="source-1",
            source_type="document_store",
            source_ref=f"docstore://{document_id}",
        ),
        acl_snapshot=_acl(document_id),
    )


def _chunk(document_id: str, chunk_id: str, text_ref: str) -> RAGChunk:
    return RAGChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_hash=f"chunk-hash-{chunk_id}",
        ordinal=0,
        text_ref=text_ref,
        acl_snapshot=_acl(document_id),
    )


def _candidate(document_id: str, chunk_id: str, text_ref: str) -> RAGCandidateChunk:
    return RAGCandidateChunk(
        document=_document(document_id),
        chunk=_chunk(document_id, chunk_id, text_ref),
        retrieval_score=0.8,
        retriever_version="fixture-retriever.v1",
        index_snapshot_ref="index-snapshot-1",
        retrieved_at=NOW,
    )


def _decision(
    decision_id: str,
    chunk_id: str,
    disposition: str,
    reason_code: str,
) -> RAGAuthorizationDecision:
    return RAGAuthorizationDecision(
        decision_id=decision_id,
        chunk_id=chunk_id,
        disposition=disposition,
        reason_code=reason_code,
        policy_snapshot_ref="policy-snapshot-1",
        policy_version="policy.v1",
        decided_at=NOW,
    )
