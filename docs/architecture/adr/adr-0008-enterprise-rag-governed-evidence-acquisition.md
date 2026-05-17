# ADR 0008: Enterprise RAG as Governed Evidence Acquisition

- Status: Proposed
- Date: 2026-05-17
- Scope: Enterprise document and knowledge retrieval as SeedCore-governed evidence
- Related: [ADR 0001](./adr-0001-pdp-hot-path.md), [ADR 0004](./adr-0004-result-verifier-runtime.md), [ADR 0005](./adr-0005-replayable-evidence-governed-state-transitions.md), [Agent Action Gateway Contract](../../development/agent_action_gateway_contract.md), [Q2 Audit Trail UI Spec](../../development/q2_2026_audit_trail_ui_spec.md), [RAG Evidence Bundle and Trace Contract](../contracts/rag_evidence_bundle_trace_contract.md)

## Context

SeedCore already implements the core trust-runtime spine needed for high-assurance agentic workflows:

- delegated authority through the Agent Action Gateway
- deterministic PDP and hot-path evaluation over pinned policy/context inputs
- signed evidence bundles, transition receipts, and replay surfaces
- RESULT_VERIFIER enforcement with fail-closed mutation for the RCT trust slice
- operator proof surfaces and read-only copilot constraints

Enterprise RAG expands SeedCore's evidence model from transaction, telemetry, and action evidence into governed enterprise document and knowledge evidence. SeedCore does not yet have a productized Enterprise Document RAG subsystem with governed ingestion, chunk-level ACL metadata, authorization-aware retrieval, RAG-specific evidence bundles, natural-language claim verification, or RAG replay.

The architectural risk is that Enterprise RAG could be implemented as a standalone chatbot or semantic search layer. That would bypass SeedCore's authority model and weaken the central premise: high-consequence decisions must be based on authorized, versioned, replayable, and verifiable evidence.

## Decision

Enterprise RAG shall be implemented as a governed evidence acquisition capability inside SeedCore's existing Evidence / PDP / Replay / Verifier architecture.

Enterprise RAG shall not be treated as an independent product center, chatbot authority, or action-authorizing subsystem.

The LLM remains an advisory generation layer. It may summarize, explain, compare, and draft responses over authorized evidence, but it shall not authorize actions or mutate governed state.

The authoritative object is the replayable evidence chain, not the generated answer.

Enterprise RAG output is accepted by SeedCore only when:

1. the query is bound to an authorization envelope;
2. retrieved evidence is authorized by SeedCore policy;
3. retrieved evidence is represented as typed RAG evidence items;
4. evidence items are bound into a RAG evidence bundle;
5. generated claims are verified against the authorized evidence bundle;
6. the full request, retrieval, generation, verification, and final status are recorded in a RAG trace.

## Scope

This ADR applies to:

- enterprise document retrieval
- internal knowledge retrieval
- policy/document-grounded operator copilot answers
- RAG-supported workflow evidence
- future document/knowledge adapters inside the SeedCore Evidence Fabric

This ADR does not decide:

- the final vector database vendor
- the final embedding model
- the final document connector framework
- the final LLM provider
- the complete schema of all RAG trace objects

Those choices belong in implementation memos or in the RAG Evidence Bundle and Trace Contract.

## Architecture

The intended flow is:

```text
User / Agent / Workflow Query
        |
        v
RAGAuthorizationEnvelope
        |
        v
SeedCore PDP
        |
        v
Authorization-Aware Retriever
        |
        v
RAGEvidenceItem[]
        |
        v
RAGEvidenceBundle
        |
        v
Guarded Generator
        |
        v
Claim-Level Verifier
        |
        v
RAGTrace / Forensic Ledger
```

The initial implementation should begin with one controlled source, such as local SeedCore markdown docs or a controlled object-store document set, rather than broad enterprise connector support.

## Rationale

SeedCore's existing architecture already differentiates between advisory reasoning and authoritative execution. Enterprise RAG should preserve that distinction. The LLM can make evidence legible, but SeedCore's PDP, evidence bundle, verifier, and replay surfaces must remain the authority-bearing components.

This decision also keeps SemanticMemory in its current architectural lane. General-purpose semantic memory can support cognition, recall, routing, and operator assistance, but it is not an authority source unless its output is promoted into typed, freshness-aware, policy-authorized evidence.

The first milestone is not better search quality. The first milestone is proof that the model only saw authorized evidence and that every final material claim is supported by that evidence.

## Consequences

Positive consequences:

- Enterprise RAG inherits SeedCore's existing trust-runtime architecture.
- LLM outputs are prevented from becoming implicit authority.
- RAG answers become replayable and auditable.
- Document evidence can support SeedCore workflows without bypassing PDP enforcement.
- SeedCore's positioning strengthens around authorized, verified, replayable evidence chains for agentic decisions.

Negative consequences:

- RAG implementation is more complex than a standard chatbot pipeline.
- Retrieval latency may increase due to per-candidate authorization.
- Ingestion must preserve source permissions, provenance, hashes, and versioning.
- Claim-level verification becomes mandatory for authoritative answers.
- Teams must distinguish between advisory semantic memory and typed governed evidence.

## Non-Goals

- Build a general-purpose enterprise chatbot.
- Replace SeedCore PDP with LLM reasoning.
- Treat semantic similarity as authorization.
- Treat citations as sufficient proof without verification.
- Allow model-generated claims to authorize actions.
- Choose Qdrant, pgvector, Weaviate, or any other vector backend as an architecture decision in this ADR.

## Alternatives Considered

- **Standalone RAG chatbot:** Rejected because it would create a parallel authority and audit path outside SeedCore's existing trust-runtime spine.
- **Use semantic memory directly as authority:** Rejected because SeedCore already treats general memory reads as advisory unless promoted into typed, freshness-aware context.
- **ADR the vector database now:** Rejected because vendor choice is less durable than the authorization, evidence, and replay boundary. Backend choice can be implementation-specific until scale, sovereignty, or tenancy requirements force a durable decision.
- **Allow citations without claim verification:** Rejected because citations alone do not prove claim support, freshness, authorization, or conflict handling.

## Acceptance Criteria

This ADR is satisfied when SeedCore can demonstrate:

1. a RAG query is bound to a principal, workflow, purpose, and policy context;
2. every evidence item sent to the model has an authorization decision ID;
3. unauthorized chunks never reach the prompt;
4. every final material claim cites authorized evidence;
5. unsupported claims are blocked or escalated;
6. a RAG trace can reconstruct the full path from query to final answer.
