from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from seedcore.models.rag import (
    RAGAuthorizationEnvelope,
    RAGDeniedCandidateSummary,
    RAGDraftAnswer,
    RAGEvidenceBundle,
    RAGSupportStatus,
    RAGTrace,
    VerifiedRAGClaim,
)
from seedcore.ops.rag.authorization_boundary import promote_authorized_rag_candidates
from seedcore.ops.rag.claim_validation import (
    RAGClaimValidationError,
    validate_rag_claims_and_citations,
)
from seedcore.ops.rag.controlled_retriever import ControlledRetriever
from seedcore.ops.rag.output_parser import RAGParseError, parse_guarded_rag_response
from seedcore.ops.rag.pdp_callout import authorize_retrieved_chunks
from seedcore.ops.rag.prompt_assembly import RAGPromptMetadata, assemble_guarded_rag_prompt


class GovernedRAGResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace: RAGTrace
    evidence_bundle: Optional[RAGEvidenceBundle] = None
    draft_answer: Optional[RAGDraftAnswer] = None
    verified_claims: list[VerifiedRAGClaim] = Field(default_factory=list)
    rendered_prompt: Optional[str] = None
    prompt_metadata: Optional[RAGPromptMetadata] = None
    denied_summary: Optional[RAGDeniedCandidateSummary] = None


class GovernedRAGHarness:
    """Fixture-only governed RAG pipeline harness."""

    def __init__(self, retriever: ControlledRetriever | None = None) -> None:
        self.retriever = retriever or ControlledRetriever()

    def run_governed_query(
        self,
        *,
        query: str,
        envelope: RAGAuthorizationEnvelope,
        now: datetime,
        mock_llm_response: str,
        policy_rules: Sequence[str] = (),
        action_parameters: dict[str, str] | None = None,
        template_version: str = "guarded-rag.v1",
        claim_support_status: RAGSupportStatus = "supported",
    ) -> GovernedRAGResult:
        """
        Executes the full RAG pipeline:
        Retrieve -> Authorize -> Promote -> Assemble Prompt -> Parse -> Validate -> Trace
        """
        action_parameters = action_parameters or {}

        # 1. Retrieve candidates
        candidates = self.retriever.retrieve_candidates(query, retrieved_at=now)

        # 2. PDP Authorize
        decisions = authorize_retrieved_chunks(
            envelope=envelope,
            candidates=candidates,
            decided_at=now,
        )

        # 3. Promote to bundle
        bundle_id = f"bundle-{envelope.envelope_id}"
        promotion = promote_authorized_rag_candidates(
            envelope=envelope,
            candidates=candidates,
            decisions=decisions,
            bundle_id=bundle_id,
            created_at=now,
        )
        bundle = promotion.evidence_bundle

        # Build base trace
        trace_id = f"trace-{envelope.envelope_id}"
        policy_decision_ids = [dec.decision_id for dec in decisions]
        rejection_reasons = sorted(
            {dec.reason_code for dec in decisions if dec.disposition != "allow"}
        )

        # Handle cases where all candidates are denied
        if not bundle.evidence_items:
            trace = RAGTrace(
                trace_id=trace_id,
                authorization_envelope_id=envelope.envelope_id,
                created_at=now,
                final_status="blocked",
                denied_candidate_count=bundle.denied_summary.denied_candidate_count,
                rejection_reason_codes=rejection_reasons or ["no_evidence_available"],
            )
            return GovernedRAGResult(
                trace=trace,
                evidence_bundle=bundle,
                denied_summary=bundle.denied_summary,
            )

        # 4. Assemble prompt
        evidence_text_by_id = {}
        for item in bundle.evidence_items:
            evidence_text = self.retriever.text_for_ref(item.text_ref)
            if evidence_text is not None:
                evidence_text_by_id[item.evidence_item_id] = evidence_text

        try:
            rendered = assemble_guarded_rag_prompt(
                bundle=bundle,
                template_version=template_version,
                policy_rules=policy_rules,
                action_parameters=action_parameters,
                evidence_text_by_id=evidence_text_by_id,
            )
        except ValueError:
            trace = RAGTrace(
                trace_id=trace_id,
                authorization_envelope_id=envelope.envelope_id,
                created_at=now,
                final_status="abstained",
                rejection_reason_codes=["prompt_assembly_error"],
            )
            return GovernedRAGResult(
                trace=trace,
                evidence_bundle=bundle,
                denied_summary=bundle.denied_summary,
            )

        # 5. Parse response
        try:
            parsed = parse_guarded_rag_response(mock_llm_response)
        except RAGParseError as exc:
            trace = RAGTrace(
                trace_id=trace_id,
                authorization_envelope_id=envelope.envelope_id,
                created_at=now,
                final_status="abstained",
                rejection_reason_codes=[exc.reason_code],
            )
            return GovernedRAGResult(
                trace=trace,
                evidence_bundle=bundle,
                rendered_prompt=rendered.prompt,
                prompt_metadata=rendered.metadata,
                denied_summary=bundle.denied_summary,
            )

        # 6. Build draft answer
        draft_answer_id = f"draft-{envelope.envelope_id}"
        draft_answer = RAGDraftAnswer(
            draft_answer_id=draft_answer_id,
            evidence_bundle_id=bundle.bundle_id,
            answer_text_ref=f"ref://answers/{draft_answer_id}",
            cited_evidence_item_ids=bundle.evidence_item_ids,
            created_at=now,
        )

        # 7. Build and Validate claims
        claim_id = f"claim-{envelope.envelope_id}"
        claims = [
            VerifiedRAGClaim(
                claim_id=claim_id,
                draft_answer_id=draft_answer_id,
                claim_text_ref=f"ref://claims/{claim_id}",
                support_status=claim_support_status,
                evidence_item_ids=(
                    bundle.evidence_item_ids
                    if claim_support_status == "supported"
                    else []
                ),
                verifier_ref="fixture-verifier.v1",
                verified_at=now,
            )
        ]

        try:
            validate_rag_claims_and_citations(bundle=bundle, draft_answer=draft_answer, claims=claims)
        except RAGClaimValidationError as exc:
            trace = RAGTrace(
                trace_id=trace_id,
                authorization_envelope_id=envelope.envelope_id,
                created_at=now,
                final_status="rejected",
                rejection_reason_codes=[exc.reason_code],
            )
            return GovernedRAGResult(
                trace=trace,
                evidence_bundle=bundle,
                draft_answer=draft_answer,
                verified_claims=claims,
                rendered_prompt=rendered.prompt,
                prompt_metadata=rendered.metadata,
                denied_summary=bundle.denied_summary,
            )

        # 8. Create final RAGTrace (accepted)
        trace = RAGTrace(
            trace_id=trace_id,
            authorization_envelope_id=envelope.envelope_id,
            created_at=now,
            final_status="accepted",
            evidence_bundle_id=bundle.bundle_id,
            draft_answer_id=draft_answer.draft_answer_id,
            verified_claim_ids=[claim.claim_id for claim in claims],
            policy_decision_ids=policy_decision_ids,
            denied_candidate_count=bundle.denied_summary.denied_candidate_count,
            rejection_reason_codes=[],
        )

        return GovernedRAGResult(
            trace=trace,
            evidence_bundle=bundle,
            draft_answer=draft_answer,
            verified_claims=claims,
            rendered_prompt=rendered.prompt,
            prompt_metadata=rendered.metadata,
            denied_summary=bundle.denied_summary,
        )
