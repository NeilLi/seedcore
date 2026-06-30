# RAG Evidence Bundle and Trace Contract

Date: 2026-05-17
Status: Draft

## Purpose

This specification defines the minimum durable objects required for SeedCore-governed Enterprise RAG.

The goal is to make every RAG interaction:

- authorization-bound
- evidence-grounded
- claim-verifiable
- replayable
- auditable
- safe for use in SeedCore workflows

This document is a contract/specification, not an ADR. The durable architecture decisions are captured in [ADR 0008](../adr/adr-0008-enterprise-rag-governed-evidence-acquisition.md) and [ADR 0009](../adr/adr-0009-authorization-aware-retrieval-boundary.md).

## Core Contract

```text
Request
  -> RAGAuthorizationEnvelope
  -> Authorized Retrieval
  -> RAGEvidenceItem[]
  -> RAGEvidenceBundle
  -> RAGDraftAnswer
  -> VerifiedRAGClaim[]
  -> RAGTrace
```

## 1. RAGAuthorizationEnvelope

```json
{
  "authorization_envelope_id": "authenv_001",
  "principal_id": "user_or_agent_123",
  "tenant_id": "tenant_acme",
  "workflow_id": "workflow_001",
  "purpose": "operator_copilot_answer",
  "roles": ["operator"],
  "groups": ["ops_team"],
  "delegation_scope": {
    "asset_id": "asset_001",
    "expires_at": "2026-05-17T12:00:00Z"
  },
  "classification_ceiling": "confidential",
  "region": "US",
  "device_fingerprint": "sha256:...",
  "risk_score": 0.21,
  "created_at": "2026-05-17T10:00:00Z"
}
```

## 2. ACLSnapshot

```json
{
  "acl_snapshot_id": "acl_001",
  "source_system": "sharepoint",
  "tenant_id": "tenant_acme",
  "resource_ref": "sharepoint://...",
  "version": "v17",
  "principal_refs": ["group:ops_team", "user:user_123"],
  "policy_tags": ["pii", "restricted"],
  "captured_at": "2026-05-17T09:59:00Z",
  "source_hash": "sha256:..."
}
```

## 3. DocumentSource

```json
{
  "source_id": "src_001",
  "source_system": "sharepoint",
  "tenant_id": "tenant_acme",
  "connector_version": "connector_v1",
  "sync_cursor": "cursor_001",
  "last_synced_at": "2026-05-17T09:59:30Z",
  "status": "active"
}
```

## 4. RAGDocument

```json
{
  "doc_id": "doc_001",
  "source_id": "src_001",
  "source_system": "sharepoint",
  "source_uri": "sharepoint://...",
  "tenant_id": "tenant_acme",
  "owner": "operations",
  "classification": "confidential",
  "source_hash": "sha256:...",
  "acl_snapshot_id": "acl_001",
  "source_version": "v12",
  "effective_from": "2026-01-01T00:00:00Z",
  "effective_until": null,
  "created_at": "2026-05-17T10:00:00Z",
  "updated_at": "2026-05-17T10:00:00Z"
}
```

## 5. RAGChunk

```json
{
  "chunk_id": "chunk_001",
  "doc_id": "doc_001",
  "text_ref": "object://rag/chunks/chunk_001",
  "chunk_hash": "sha256:...",
  "embedding_ref": "vector://collection/chunk_001",
  "acl_snapshot_id": "acl_001",
  "tenant_id": "tenant_acme",
  "classification": "confidential",
  "region": "US",
  "source_version": "v12",
  "token_count": 420
}
```

## 6. RAGEvidenceItem

```json
{
  "evidence_id": "ev_001",
  "chunk_id": "chunk_001",
  "doc_id": "doc_001",
  "text_ref": "object://rag/chunks/chunk_001",
  "chunk_hash": "sha256:...",
  "source_hash": "sha256:...",
  "source_system": "sharepoint",
  "source_uri": "sharepoint://...",
  "retrieval_score": 0.84,
  "authorization_decision_id": "dec_001",
  "policy_version": "rag_policy_v1",
  "retriever_version": "retriever_v1",
  "retrieved_at": "2026-05-17T10:01:00Z"
}
```

## 7. RAGEvidenceBundle

```json
{
  "bundle_id": "evb_001",
  "request_id": "req_001",
  "authorization_envelope_id": "authenv_001",
  "query_hash": "sha256:...",
  "evidence_item_ids": ["ev_001", "ev_002"],
  "candidate_count": 20,
  "authorized_count": 5,
  "denied_candidate_count": 15,
  "retriever_version": "retriever_v1",
  "embedding_model": "embedding_model_v1",
  "index_snapshot": "index_snapshot_001",
  "bundle_hash": "sha256:...",
  "created_at": "2026-05-17T10:01:10Z"
}
```

## 8. RAGDraftAnswer

```json
{
  "draft_answer_id": "draft_001",
  "bundle_id": "evb_001",
  "prompt_template_version": "rag_prompt_v1",
  "model_name": "model_name",
  "model_config_hash": "sha256:...",
  "answer_text_hash": "sha256:...",
  "claim_ids": ["claim_001", "claim_002"],
  "created_at": "2026-05-17T10:01:30Z"
}
```

## 9. Guarded Prompt Assembly Profile

Guarded prompt assembly is an implementation profile over an authorized
`RAGEvidenceBundle`; it is not a replacement for the bundle contract and does
not add authority to the LLM output. Prompt templates may use deterministic
section delimiters, including XML-style tags such as `<evidence>`,
`<policy_rules>`, and `<action_parameters>`, to keep authorized evidence,
policy reminders, and request parameters isolated in model-visible context.

These tags are prompt-assembly boundaries, not schema-validation fields inside
`RAGEvidenceItem` or `RAGEvidenceBundle`. The authoritative validation remains:

- only authorized `RAGEvidenceItem` objects may be rendered inside
  `<evidence>`;
- denied, quarantined, or missing-decision candidates must not be rendered in
  any model-visible section;
- policy text rendered inside `<policy_rules>` is explanatory context and must
  not replace the PDP decision IDs already bound into the trace;
- scratchpad or chain-of-thought instructions, if used, must be isolated from
  the parsed final payload and must not be persisted as authority-bearing
  evidence.

Guarded generators may also use response-prefill conventions, such as a JSON
object prefix for strict schema completion, when the downstream parser expects a
typed output. Prefill is a formatting reliability aid. It is not an
authorization control, cannot relax abstain/block semantics, and should be
configured on the guarded generator or route profile rather than emitted by SDK
preflight checks by default.

MVP acceptance for this profile requires tests proving that the rendered prompt
can be reconstructed from the bundle, contains no denied candidate content, and
that malformed or non-schema-valid model output produces blocked, escalated,
abstained, or lite-receipt closure rather than ungoverned fallback.

## 10. VerifiedRAGClaim

```json
{
  "claim_id": "claim_001",
  "draft_answer_id": "draft_001",
  "text": "The custody release requires supervisor approval.",
  "evidence_item_ids": ["ev_001"],
  "support_status": "supported",
  "verification_method": "span_check+nli",
  "verifier_version": "rag_verifier_v1",
  "confidence": 0.93,
  "created_at": "2026-05-17T10:01:40Z"
}
```

Allowed `support_status` values:

- `supported`
- `unsupported`
- `conflicted`
- `insufficient`

## 11. RAGTrace

```json
{
  "trace_id": "ragtrace_001",
  "request_id": "req_001",
  "workflow_id": "workflow_001",
  "principal_id": "user_or_agent_123",
  "authorization_envelope_id": "authenv_001",
  "evidence_bundle_id": "evb_001",
  "draft_answer_id": "draft_001",
  "verified_claim_ids": ["claim_001", "claim_002"],
  "policy_decision_ids": ["dec_001", "dec_002"],
  "final_status": "accepted",
  "answer_hash": "sha256:...",
  "trace_hash": "sha256:...",
  "created_at": "2026-05-17T10:02:00Z"
}
```

Allowed `final_status` values:

- `accepted`
- `blocked`
- `escalated`
- `abstained`

## 12. RAGReceipt

`RAGReceipt` is the portable proof object for a completed governed RAG
interaction. It signs the trace closure; it does not authorize future
execution, clear quarantine, or prove that the generated answer is objectively
true.

```json
{
  "receipt_id": "ragreceipt_001",
  "receipt_profile": "seedcore_rag_receipt_json_v1",
  "trace_id": "ragtrace_001",
  "authorization_envelope_id": "authenv_001",
  "evidence_bundle_id": "evb_001",
  "draft_answer_id": "draft_001",
  "verified_claim_ids": ["claim_001", "claim_002"],
  "policy_decision_ids": ["dec_001", "dec_002"],
  "minimal_evidence_item_ids": ["ev_001"],
  "denied_candidate_summary_hash": "sha256:...",
  "safe_telemetry_ref": "telemetry://rag/ragtrace_001",
  "bundle_hash": "sha256:...",
  "answer_hash": "sha256:...",
  "trace_hash": "sha256:...",
  "final_status": "accepted",
  "degradation_mode": null,
  "issued_at": "2026-05-17T10:02:05Z",
  "signer_metadata": {
    "signer_type": "service",
    "signer_id": "seedcore-rag-receipt-service",
    "signing_scheme": "hmac_sha256",
    "key_ref": "kms-or-dev-key-ref",
    "attestation_level": "baseline"
  },
  "signature": "base64-or-hex-signature"
}
```

Allowed `receipt_profile` values:

- `seedcore_rag_receipt_json_v1`: internal JSON payload signed by the existing
  SeedCore evidence signer profiles.
- `jws_rag_receipt_v1`: future JOSE/JWS external audit profile.
- `cose_rag_receipt_v1`: future COSE/CBOR compact or device-profile audit
  profile.

Allowed `degradation_mode` values:

- `lite_receipt`: the boundary stopped safely but did not complete full answer
  verification.
- `abstain_insufficient_evidence`: authorized evidence was absent or
  insufficient.
- `abstain_stale_evidence`: candidate evidence failed freshness requirements.
- `abstain_conflicted_evidence`: authorized evidence conflicted and no safe
  answer could be accepted.
- `abstain_verifier_unavailable`: verification could not complete inside the
  required policy window.
- `policy_blocked`: policy or PDP evaluation blocked the RAG interaction.
- `none`: full receipt with no degradation.

## 13. Minimal Evidence Set

The minimal evidence set is a verifier artifact, not a model-selected
authority source. It may be derived only from already authorized
`RAGEvidenceItem` objects.

Required fields for a minimal evidence artifact:

```json
{
  "minimal_evidence_set_id": "mses_001",
  "trace_id": "ragtrace_001",
  "evidence_bundle_id": "evb_001",
  "claim_ids": ["claim_001"],
  "minimal_evidence_item_ids": ["ev_001"],
  "candidate_evidence_item_ids": ["ev_001", "ev_002"],
  "selection_algorithm": "greedy_remove_reverify_v1",
  "verifier_version": "rag_verifier_v1",
  "created_at": "2026-05-17T10:01:45Z"
}
```

The full authorized evidence bundle must remain available for replay and
forensics even when a smaller minimal set is attached to a receipt.

## 14. Side-Channel-Safe Telemetry

RAG denial and timing telemetry must avoid leaking sensitive resource
existence. Ordinary traces, receipts, logs, and proof UI payloads may expose
only aggregate denied counts, reason-count buckets, and coarse latency
histograms.

```json
{
  "safe_telemetry_id": "ragtelemetry_001",
  "trace_id": "ragtrace_001",
  "candidate_count": 20,
  "authorized_count": 5,
  "denied_candidate_count": 15,
  "missing_decision_count": 0,
  "reason_counts": {
    "acl_mismatch": 10,
    "classification_ceiling": 5
  },
  "proof_latency_histogram": {
    "bucket_ms": [50, 100, 250, 500, 1000],
    "counts": [2, 7, 5, 1, 0]
  }
}
```

Denied document IDs, chunk IDs, titles, snippets, raw text refs, and
per-denied-resource timings must not appear in ordinary receipts, prompts,
citations, logs, or proof UI payloads.

## Required Invariants

1. No `RAGEvidenceItem` may exist without an authorization decision.
2. No `RAGEvidenceBundle` may include unauthorized chunks.
3. No `RAGDraftAnswer` may be generated without a bundle.
4. No material claim may be accepted without supporting evidence.
5. No RAG answer may be marked accepted without a `RAGTrace`.
6. Semantic memory is advisory unless promoted into typed evidence.
7. Revoked or stale chunks must not be retrieved for new decisions.
8. The system must support replay from `RAGTrace`.
9. Denied candidate content must not appear in reranker input, prompt input, citations, ordinary logs, or operator proof UI.
10. No accepted or full RAG receipt may exist without a trace, bundle hash,
    policy decision IDs, verified claim IDs, and a signer profile.
11. A minimal evidence set may reduce verifier-visible support only from
    already authorized evidence; it must never introduce new evidence or expose
    denied candidate content.
12. Degraded receipts must preserve fail-closed semantics and disclose only
    policy-safe refusal or abstention metadata.
13. Guarded prompt assembly must render only authorized evidence bundle
    members and must treat XML tags, policy reminders, scratchpads, and
    response prefill as non-authoritative formatting controls.

## MVP Acceptance Tests

- Tenant isolation test.
- Classification ceiling test.
- Revoked ACL test.
- Unauthorized chunk non-reranking test.
- Unauthorized chunk non-prompt test.
- Unsupported claim blocking test.
- Citation laundering test.
- Replay reconstruction test.
- Semantic-memory-not-authority test.
- RAG receipt closure test.
- Minimal evidence set verifier test.
- Lite receipt / abstain degradation test.
- Side-channel-safe denied telemetry test.
- Guarded prompt assembly reconstruction and denied-content exclusion test.
- Schema-prefill failure-to-abstain or failure-to-block test.

## Open Implementation Notes

- Vector database choice is intentionally left open.
- Connector framework choice is intentionally left open.
- The first MVP should use one controlled document source before broad enterprise connector support.
- Claim verification may start with structured citations and lexical span checks before adding NLI or LLM-judge support.
- COSE/JOSE should wrap a stable SeedCore RAG receipt payload, not replace the
  SeedCore trace or verifier contracts.
- Transparency registration, such as SCITT-style publication, is a later
  external audit profile after local receipt generation and replay validation
  are green.
- XML-style prompt sections and response prefill should be versioned with the
  prompt template profile and route schema, not with core evidence item
  validation.
