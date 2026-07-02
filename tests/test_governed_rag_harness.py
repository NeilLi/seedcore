from __future__ import annotations

import ast
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from seedcore.models.rag import RAGAuthorizationEnvelope
from seedcore.ops.rag import GovernedRAGHarness, RAGClaimValidationError

NOW = datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)


def test_governed_rag_harness_happy_path() -> None:
    envelope = RAGAuthorizationEnvelope(
        envelope_id="env-happy",
        principal_ref="principal:user-1",
        workflow_ref="workflow-1",
        purpose="testing",
        policy_snapshot_ref="snapshot-1",
        policy_version="v1",
        issued_at=NOW,
        classification_ceiling="restricted",
    )

    harness = GovernedRAGHarness()
    mock_llm = """<scratchpad>
    Checking public, confidential, and restricted documents.
    </scratchpad>
    <response>
    {
        "answer": "Here is the combined response from public, confidential, and restricted files."
    }
    </response>"""

    result = harness.run_governed_query(
        query="actions co-signature secret",
        envelope=envelope,
        now=NOW,
        mock_llm_response=mock_llm,
    )

    assert result.trace.final_status == "accepted"
    assert result.evidence_bundle is not None
    assert len(result.evidence_bundle.evidence_items) == 3
    assert result.draft_answer is not None
    assert len(result.verified_claims) == 1
    assert result.prompt_metadata is not None
    assert len(result.prompt_metadata.evidence_item_ids) == 3
    assert result.rendered_prompt is not None
    assert (
        "SeedCore zero-trust RCT execution boundary tokenizes actions."
        in result.rendered_prompt
    )


def test_governed_rag_harness_unauthorized_leakage_denied() -> None:
    envelope = RAGAuthorizationEnvelope(
        envelope_id="env-leakage",
        principal_ref="principal:user-1",
        workflow_ref="workflow-1",
        purpose="testing",
        policy_snapshot_ref="snapshot-1",
        policy_version="v1",
        issued_at=NOW,
        classification_ceiling="public",
    )

    harness = GovernedRAGHarness()
    mock_llm = """<scratchpad>
    Thinking...
    </scratchpad>
    <response>
    {
        "answer": "Answer based on public data."
    }
    </response>"""

    result = harness.run_governed_query(
        query="actions co-signature secret",
        envelope=envelope,
        now=NOW,
        mock_llm_response=mock_llm,
    )

    assert result.trace.denied_candidate_count == 2
    assert result.evidence_bundle is not None
    assert len(result.evidence_bundle.evidence_items) == 1
    assert result.evidence_bundle.evidence_items[0].document_id == "doc-public-1"

    # Rendered prompt metadata verification
    assert result.prompt_metadata is not None
    assert result.prompt_metadata.denied_candidate_count == 2
    assert result.rendered_prompt is not None
    assert (
        "SeedCore zero-trust RCT execution boundary tokenizes actions."
        in result.rendered_prompt
    )
    assert "Confidential facility operator" not in result.rendered_prompt
    assert "Restricted transaction audit" not in result.rendered_prompt

    # Assert denied text never enters any ordinary fields in the trace/result
    dump_str = result.model_dump_json()
    assert "doc-confidential-1" not in dump_str
    assert "doc-restricted-1" not in dump_str
    assert "Confidential facility operator" not in dump_str
    assert "Restricted transaction audit" not in dump_str


def test_governed_rag_harness_blocked_on_zero_evidence() -> None:
    # Ceiling is public, but we query for confidential-only words. No public document matches.
    envelope = RAGAuthorizationEnvelope(
        envelope_id="env-zero",
        principal_ref="principal:user-1",
        workflow_ref="workflow-1",
        purpose="testing",
        policy_snapshot_ref="snapshot-1",
        policy_version="v1",
        issued_at=NOW,
        classification_ceiling="public",
    )

    harness = GovernedRAGHarness()
    result = harness.run_governed_query(
        query="co-signature requirement",
        envelope=envelope,
        now=NOW,
        mock_llm_response="",
    )

    assert result.trace.final_status == "blocked"
    assert result.evidence_bundle is not None
    assert len(result.evidence_bundle.evidence_items) == 0
    assert result.draft_answer is None


def test_governed_rag_harness_abstained_on_parse_error() -> None:
    envelope = RAGAuthorizationEnvelope(
        envelope_id="env-parse-fail",
        principal_ref="principal:user-1",
        workflow_ref="workflow-1",
        purpose="testing",
        policy_snapshot_ref="snapshot-1",
        policy_version="v1",
        issued_at=NOW,
        classification_ceiling="restricted",
    )

    harness = GovernedRAGHarness()
    # Missing unclosed response tag
    malformed_llm = "<scratchpad>Thinking...</scratchpad><response>Unclosed"

    result = harness.run_governed_query(
        query="actions",
        envelope=envelope,
        now=NOW,
        mock_llm_response=malformed_llm,
    )

    assert result.trace.final_status == "abstained"
    assert result.trace.rejection_reason_codes == ["rag_response_malformed"]
    assert "Unclosed" not in result.trace.model_dump_json()


def test_governed_rag_harness_rejected_on_claim_validation_error() -> None:
    envelope = RAGAuthorizationEnvelope(
        envelope_id="env-val-fail",
        principal_ref="principal:user-1",
        workflow_ref="workflow-1",
        purpose="testing",
        policy_snapshot_ref="snapshot-1",
        policy_version="v1",
        issued_at=NOW,
        classification_ceiling="restricted",
    )

    harness = GovernedRAGHarness()
    mock_llm = """<scratchpad>Thinking...</scratchpad><response>Body</response>"""

    with patch(
        "seedcore.ops.rag.harness.validate_rag_claims_and_citations",
        side_effect=RAGClaimValidationError(
            "rag_claim_unknown_citation_id",
            "sensitive fixture text doc-restricted-1",
        ),
    ):
        result = harness.run_governed_query(
            query="actions",
            envelope=envelope,
            now=NOW,
            mock_llm_response=mock_llm,
        )

    assert result.trace.final_status == "rejected"
    assert result.trace.rejection_reason_codes == ["rag_claim_unknown_citation_id"]
    assert "doc-restricted-1" not in result.trace.model_dump_json()


def test_rag_envelope_rejects_unknown_classification_ceiling() -> None:
    with pytest.raises(ValidationError):
        RAGAuthorizationEnvelope(
            envelope_id="env-invalid-classification",
            principal_ref="principal:user-1",
            workflow_ref="workflow-1",
            purpose="testing",
            policy_snapshot_ref="snapshot-1",
            policy_version="v1",
            issued_at=NOW,
            classification_ceiling="internal",
        )


def test_rag_harness_contains_no_llm_imports() -> None:
    """Ensure that the RAG harness and PDP callout do not import any AI/LLM SDKs."""
    target_files = [
        "src/seedcore/ops/rag/pdp_callout.py",
        "src/seedcore/ops/rag/harness.py",
        "src/seedcore/ops/rag/controlled_retriever.py",
    ]

    forbidden_substrings = [
        "openai",
        "google.generativeai",
        "langchain",
        "anthropic",
        "cohere",
        "transformers",
        "cognitive_service",
        "xgboost",
        "xgboost_ray",
        "pandas",
        "sklearn",
        "torch",
        "dspy",
    ]

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    for relative_path in target_files:
        filepath = os.path.join(project_root, relative_path)
        assert os.path.exists(filepath), f"File not found: {filepath}"

        with open(filepath, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=filepath)

        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported_modules.append(node.module)

        for module in imported_modules:
            for forbidden in forbidden_substrings:
                assert forbidden not in module.lower(), (
                    f"Safety Boundary Violation: RAG operation file '{relative_path}' "
                    f"imports forbidden library: '{module}'"
                )
