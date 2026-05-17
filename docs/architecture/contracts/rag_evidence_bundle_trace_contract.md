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

## 9. VerifiedRAGClaim

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

## 10. RAGTrace

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

## Open Implementation Notes

- Vector database choice is intentionally left open.
- Connector framework choice is intentionally left open.
- The first MVP should use one controlled document source before broad enterprise connector support.
- Claim verification may start with structured citations and lexical span checks before adding NLI or LLM-judge support.
