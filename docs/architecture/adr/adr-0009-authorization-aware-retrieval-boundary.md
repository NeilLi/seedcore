# ADR 0009: Authorization-Aware Retrieval Boundary

- Status: Proposed
- Date: 2026-05-17
- Scope: Authorization and leakage boundary for SeedCore-governed Enterprise RAG
- Related: [ADR 0001](./adr-0001-pdp-hot-path.md), [ADR 0008](./adr-0008-enterprise-rag-governed-evidence-acquisition.md), [RAG Evidence Bundle and Trace Contract](../contracts/rag_evidence_bundle_trace_contract.md)

## Context

Enterprise RAG introduces a new class of evidence into SeedCore: governed text, document, and knowledge evidence. Unlike ordinary transaction or telemetry evidence, document evidence may contain mixed permissions, stale content, tenant-specific restrictions, sensitive fields, or policy-controlled classifications.

A standard RAG pipeline retrieves semantically similar chunks and then sends them to a model. That is insufficient for SeedCore because semantic relevance is not authorization.

The most important boundary is the point at which retrieved text becomes visible to downstream components such as rerankers, prompt assemblers, LLMs, verifiers, UI surfaces, or logs.

If unauthorized chunks are retrieved and processed before filtering, the system may leak sensitive information even if the final user-visible answer does not quote the restricted text.

## Decision

SeedCore shall enforce authorization before any retrieved chunk is exposed to reranking, prompt assembly, LLM generation, answer verification, operator display, or durable answer logs.

The retrieval pipeline shall use a two-stage authorization model:

1. coarse pre-filtering during candidate retrieval;
2. fine-grained SeedCore PDP authorization for each candidate before downstream use.

Only authorized chunks shall become `RAGEvidenceItem` objects.

Only `RAGEvidenceItem` objects may be included in a `RAGEvidenceBundle`.

Only a `RAGEvidenceBundle` may be used for guarded generation.

## Required Retrieval Flow

```text
Query
  |
  v
Authorization Envelope
  |
  v
Coarse Retrieval Filter
tenant, region, classification ceiling, source status
  |
  v
Candidate Chunks
  |
  v
Per-Candidate PDP Check
principal, workflow, purpose, ACL snapshot, policy version
  |
  v
Authorized Candidates Only
  |
  v
Reranking
  |
  v
RAGEvidenceItem[]
  |
  v
RAGEvidenceBundle
  |
  v
Prompt Assembly
```

## Hard Requirements

Each returned RAG evidence item shall include:

- evidence ID
- document ID
- chunk ID
- source hash
- chunk hash
- source system
- source URI or reference
- ACL snapshot ID
- authorization decision ID
- policy version
- principal/workflow/purpose binding
- retrieval timestamp
- retriever version
- index snapshot or equivalent index-version reference

The system shall record:

- number of retrieved candidates
- number of denied candidates
- policy versions used
- authorization decision IDs
- retriever version
- embedding model/version
- index snapshot or equivalent reference

## Prohibited Behavior

The system shall not:

- send unauthorized chunks to the LLM
- rerank unauthorized chunks
- summarize unauthorized chunks
- display unauthorized chunk titles or snippets
- use unauthorized chunks in citations
- allow model instructions inside retrieved documents to override SeedCore policy
- treat semantic memory as a governed authority source unless explicitly promoted into typed evidence
- answer from uncited or unverifiable retrieved context

## Handling Denied Candidates

Denied candidates may be counted and logged in aggregate for audit purposes.

Denied candidate content shall not be exposed to:

- the user
- the LLM
- the verifier
- ordinary application logs
- operator proof UI
- downstream generation steps

Whether the existence of denied resources may be disclosed is policy-controlled.

## Rationale

SeedCore must never rely on the LLM, reranker, or prompt assembly layer as the access-control boundary. Those components may transform, score, or explain already-authorized evidence, but they must not process text that the principal is not allowed to see.

The coarse retrieval filter is a performance optimization and a defense-in-depth layer. It is not the final authorization decision. The per-candidate PDP decision is the boundary that promotes a retrieved chunk into governed RAG evidence.

## Consequences

Positive consequences:

- The LLM never becomes the access-control boundary.
- Reranking and prompt assembly cannot leak restricted information.
- The system can prove which chunks were authorized.
- RAG traces become suitable for forensic replay.
- SeedCore maintains a fail-closed evidence posture.

Negative consequences:

- Retrieval is more complex.
- Per-candidate authorization may add latency.
- ACL synchronization must be reliable.
- Index invalidation becomes important when permissions change.
- Retrieval evaluation must measure both relevance and authorization correctness.

## Failure Modes Addressed

This ADR mitigates:

- unauthorized semantic leakage
- cross-tenant retrieval contamination
- stale permission metadata
- citation laundering
- prompt injection through retrieved documents
- over-disclosure through denial messages
- advisory memory being mistaken for authority

## Alternatives Considered

- **Retrieve broadly, rerank, then filter:** Rejected because rerankers or intermediate processors would already see unauthorized text.
- **Rely only on vector-store metadata filters:** Rejected because metadata filters are necessary but insufficient for fine-grained policy, purpose, workflow, delegation, and freshness checks.
- **Let the LLM self-police access rules:** Rejected because policy enforcement must be deterministic, replayable, and external to the model.
- **Expose denied snippets to operators by default:** Rejected because denial disclosure itself can be sensitive and must be policy-controlled.

## Acceptance Criteria

This ADR is satisfied when tests prove:

1. a user cannot retrieve chunks outside their tenant;
2. a user cannot retrieve chunks above their clearance;
3. a revoked permission prevents future retrieval;
4. denied chunks do not enter reranker inputs;
5. denied chunks do not enter prompts;
6. denied chunks do not appear in citations;
7. every authorized chunk has a policy decision ID;
8. every RAG answer can be traced back to a RAG evidence bundle.
