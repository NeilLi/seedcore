from __future__ import annotations

from hashlib import sha256
from html import escape
from typing import Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from seedcore.models.rag import RAGEvidenceBundle


DEFAULT_GUARDED_RAG_TEMPLATE = """<policy_rules>
{policy_rules}
</policy_rules>

<action_parameters>
{action_parameters}
</action_parameters>

<evidence bundle_id="{bundle_id}">
{evidence_items}
</evidence>{response_prefill}"""


class RAGPromptMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version: str
    template_hash: str
    bundle_id: str
    evidence_item_ids: list[str] = Field(default_factory=list)
    rendered_character_count: int = Field(ge=0)
    evidence_character_count: int = Field(ge=0)
    policy_rule_character_count: int = Field(ge=0)
    action_parameter_character_count: int = Field(ge=0)
    denied_candidate_count: int = Field(ge=0)
    response_prefill_hash: Optional[str] = None


class RAGRenderedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    metadata: RAGPromptMetadata


def assemble_guarded_rag_prompt(
    *,
    bundle: RAGEvidenceBundle,
    template_version: str,
    policy_rules: Sequence[str] = (),
    action_parameters: Mapping[str, str] | None = None,
    evidence_text_by_id: Mapping[str, str] | None = None,
    response_prefill: str | None = None,
    template: str = DEFAULT_GUARDED_RAG_TEMPLATE,
) -> RAGRenderedPrompt:
    """Render model-visible RAG context only from an authorized evidence bundle."""

    if not isinstance(bundle, RAGEvidenceBundle):
        raise TypeError("guarded RAG prompt assembly requires a RAGEvidenceBundle")
    if not template_version:
        raise ValueError("template_version is required")

    action_parameters = action_parameters or {}
    evidence_text_by_id = evidence_text_by_id or {}
    _reject_unknown_evidence_text_refs(bundle=bundle, evidence_text_by_id=evidence_text_by_id)

    policy_rules_text = _render_policy_rules(policy_rules)
    action_parameters_text = _render_action_parameters(action_parameters)
    evidence_items_text = _render_evidence_items(
        bundle=bundle,
        evidence_text_by_id=evidence_text_by_id,
    )
    prefill_text = response_prefill or ""

    prompt = template.format(
        policy_rules=policy_rules_text,
        action_parameters=action_parameters_text,
        bundle_id=escape(bundle.bundle_id),
        evidence_items=evidence_items_text,
        response_prefill=f"\n{prefill_text}" if prefill_text else "",
    )

    metadata = RAGPromptMetadata(
        template_version=template_version,
        template_hash=_sha256_text(template),
        bundle_id=bundle.bundle_id,
        evidence_item_ids=bundle.evidence_item_ids,
        rendered_character_count=len(prompt),
        evidence_character_count=len(evidence_items_text),
        policy_rule_character_count=len(policy_rules_text),
        action_parameter_character_count=len(action_parameters_text),
        denied_candidate_count=bundle.denied_summary.denied_candidate_count,
        response_prefill_hash=_sha256_text(prefill_text) if prefill_text else None,
    )
    return RAGRenderedPrompt(prompt=prompt, metadata=metadata)


def _reject_unknown_evidence_text_refs(
    *,
    bundle: RAGEvidenceBundle,
    evidence_text_by_id: Mapping[str, str],
) -> None:
    allowed_ids = set(bundle.evidence_item_ids)
    unknown_ids = sorted(set(evidence_text_by_id) - allowed_ids)
    if unknown_ids:
        raise ValueError(
            "evidence_text_by_id contains ids that are not in the authorized bundle: "
            + ", ".join(unknown_ids)
        )


def _render_policy_rules(policy_rules: Sequence[str]) -> str:
    if not policy_rules:
        return "- Use only authorized evidence from the evidence section."
    return "\n".join(f"- {escape(str(rule))}" for rule in policy_rules)


def _render_action_parameters(action_parameters: Mapping[str, str]) -> str:
    if not action_parameters:
        return "- none"
    return "\n".join(
        f"- {escape(str(key))}: {escape(str(value))}"
        for key, value in sorted(action_parameters.items())
    )


def _render_evidence_items(
    *,
    bundle: RAGEvidenceBundle,
    evidence_text_by_id: Mapping[str, str],
) -> str:
    rendered_items: list[str] = []

    for item in bundle.evidence_items:
        if item.authorization_disposition != "allow":
            raise ValueError("guarded RAG prompt assembly can only render allow evidence items")
        rendered_item = [
            f'<evidence_item id="{escape(item.evidence_item_id)}">',
            f"document_id: {escape(item.document_id)}",
            f"document_hash: {escape(item.document_hash)}",
            f"chunk_id: {escape(item.chunk_id)}",
            f"chunk_hash: {escape(item.chunk_hash)}",
            f"source_ref: {escape(item.source_ref)}",
            f"text_ref: {escape(item.text_ref)}",
            f"authorization_decision_id: {escape(item.authorization_decision_id)}",
            f"policy_snapshot_ref: {escape(item.policy_snapshot_ref)}",
            f"policy_version: {escape(item.policy_version)}",
            f"retriever_version: {escape(item.retriever_version)}",
            f"index_snapshot_ref: {escape(item.index_snapshot_ref)}",
        ]
        evidence_text = evidence_text_by_id.get(item.evidence_item_id)
        if evidence_text is not None:
            rendered_item.extend(
                [
                    "<text>",
                    escape(evidence_text),
                    "</text>",
                ]
            )
        rendered_item.append("</evidence_item>")
        rendered_items.append("\n".join(rendered_item))

    return "\n".join(rendered_items)


def _sha256_text(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()
