from __future__ import annotations

from datetime import datetime, timezone

import pytest

from seedcore.models.rag import (
    ACLSnapshot,
    DocumentSource,
    RAGAuthorizationDecision,
    RAGAuthorizationEnvelope,
    RAGCandidateChunk,
    RAGChunk,
    RAGDocument,
)
from seedcore.ops.rag import (
    assemble_guarded_rag_prompt,
    promote_authorized_rag_candidates,
)


NOW = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


def test_guarded_prompt_renders_only_authorized_evidence() -> None:
    result = _promotion_result()

    rendered = assemble_guarded_rag_prompt(
        bundle=result.evidence_bundle,
        template_version="guarded-rag.v1",
        policy_rules=["Cite evidence_item_id values for every material claim."],
        action_parameters={"question_hash": "sha256:question"},
        evidence_text_by_id={
            "rag-evidence:decision-allow": "Allowed custody release instructions."
        },
    )

    assert "<evidence" in rendered.prompt
    assert '<evidence_item id="rag-evidence:decision-allow">' in rendered.prompt
    assert "Allowed custody release instructions." in rendered.prompt
    assert "doc-denied" not in rendered.prompt
    assert "chunk-denied" not in rendered.prompt
    assert "txt://denied" not in rendered.prompt
    assert "txt://missing-decision" not in rendered.prompt
    assert rendered.metadata.evidence_item_ids == ["rag-evidence:decision-allow"]
    assert rendered.metadata.denied_candidate_count == 2


def test_guarded_prompt_rejects_text_for_unknown_evidence_ids() -> None:
    result = _promotion_result()

    with pytest.raises(ValueError, match="not in the authorized bundle"):
        assemble_guarded_rag_prompt(
            bundle=result.evidence_bundle,
            template_version="guarded-rag.v1",
            evidence_text_by_id={
                "rag-evidence:decision-allow": "Allowed text.",
                "rag-evidence:decision-deny": "Denied text must not pass.",
            },
        )


def test_guarded_prompt_rejects_malformed_non_allow_evidence_item() -> None:
    result = _promotion_result()
    malformed_item = result.evidence_items[0].model_copy(
        update={"authorization_disposition": "deny"}
    )
    malformed_bundle = result.evidence_bundle.model_copy(
        update={"evidence_items": [malformed_item]}
    )

    with pytest.raises(ValueError, match="only render allow evidence items"):
        assemble_guarded_rag_prompt(
            bundle=malformed_bundle,
            template_version="guarded-rag.v1",
        )


def test_guarded_prompt_metadata_is_replay_friendly_without_prefill_authority() -> None:
    result = _promotion_result()

    rendered = assemble_guarded_rag_prompt(
        bundle=result.evidence_bundle,
        template_version="guarded-rag.v1",
        action_parameters={"route": "operator-copilot"},
        response_prefill='{"answer":',
    )

    assert rendered.metadata.template_version == "guarded-rag.v1"
    assert rendered.metadata.template_hash.startswith("sha256:")
    assert rendered.metadata.bundle_id == "bundle-1"
    assert rendered.metadata.rendered_character_count == len(rendered.prompt)
    assert rendered.metadata.evidence_character_count > 0
    assert rendered.metadata.action_parameter_character_count > 0
    assert rendered.metadata.response_prefill_hash
    assert '{"answer":' in rendered.prompt
    assert rendered.metadata.evidence_item_ids == ["rag-evidence:decision-allow"]


def test_guarded_prompt_requires_evidence_bundle() -> None:
    with pytest.raises(TypeError, match="requires a RAGEvidenceBundle"):
        assemble_guarded_rag_prompt(
            bundle=object(),  # type: ignore[arg-type]
            template_version="guarded-rag.v1",
        )


def _promotion_result():
    envelope = _envelope()
    allowed = _candidate("doc-allowed", "chunk-allowed", "txt://allowed")
    denied = _candidate("doc-denied", "chunk-denied", "txt://denied")
    missing = _candidate("doc-missing", "chunk-missing", "txt://missing-decision")

    return promote_authorized_rag_candidates(
        envelope=envelope,
        candidates=[allowed, denied, missing],
        decisions=[
            _decision(
                "decision-allow",
                "chunk-allowed",
                "allow",
                "rag_chunk_allowed",
            ),
            _decision(
                "decision-deny",
                "chunk-denied",
                "deny",
                "acl_mismatch",
            ),
        ],
        bundle_id="bundle-1",
        created_at=NOW,
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
