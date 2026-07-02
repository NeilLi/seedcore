# Knowledge Graph RAG Research Reference

Date: 2026-06-29
Status: Reference note for governed retrieval and graph-reasoning roadmap
Related:

- [Policy-Governed RAG Research Adoption Review](policy_governed_rag_research_adoption_review.md)
- [ADR 0008: Enterprise RAG as Governed Evidence Acquisition](../architecture/adr/adr-0008-enterprise-rag-governed-evidence-acquisition.md)
- [ADR 0009: Authorization-Aware Retrieval Boundary](../architecture/adr/adr-0009-authorization-aware-retrieval-boundary.md)
- [RAG Evidence Bundle and Trace Contract](../architecture/contracts/rag_evidence_bundle_trace_contract.md)
- [Policy Graph Builder Implementation Plan](policy_graph_builder_implementation_plan.md)
- [ADR 0011: Benchmark-Gated Authorization Graph Engine Evolution](../architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md)

## Purpose

This note translates the June 2026 KG / GraphRAG research signal into
SeedCore-native guidance.

The useful conclusion is not that one retrieval architecture replaces another.
The useful conclusion is that graph-backed retrieval has split into several
specialized lanes:

1. efficient graph-enhanced retrieval;
2. path-centric evidence retrieval;
3. agentic graph query and planning control;
4. graph foundation models for structural KG reasoning.

SeedCore should treat these as retrieval, planning, or reasoning substrates
behind existing PDP, evidence, verifier, and replay boundaries. None of them
becomes execution authority by itself.

## Field Map

| Research lane | Examples | Useful capability | SeedCore posture |
| :--- | :--- | :--- | :--- |
| Efficient GraphRAG | Microsoft GraphRAG, LazyGraphRAG, LightRAG | Build graph-enhanced retrieval without treating a flat vector index as the whole knowledge model. Lazy and incremental variants reduce eager indexing cost. | Candidate controlled-source retriever patterns only. Retrieved chunks still need coarse filtering, PDP authorization, evidence-item promotion, and replay refs. |
| Path-centric retrieval | PathRAG, K-Paths, path-constrained retrieval | Retrieve compact relational paths instead of broad redundant graph context, especially for multi-hop evidence tasks. | Strong fit for future `RAGEvidenceItem` extensions, but every path must be authorization-checked at node, edge, source, and snapshot levels before prompt use. |
| Agentic graph control | Plan-on-Graph, Text-to-Cypher agents, MCP graph tools | Let an agent decompose questions, inspect schema, run graph queries, self-correct, and use the graph as an interactive state space. | Treat as a governed control-plane candidate. Read/query tools may support advisory planning; writes, schema changes, policy graph mutation, or custody-state mutation require explicit gated actions, PDP allow, scoped token, and receipt closure. |
| KG foundation models | ULTRA, MERRY, GraphOracle | Generalize structural KG reasoning across unseen entities, relations, or graphs; support link prediction and inductive relation reasoning. | Shadow or advisory inference only until outputs are promoted into typed evidence or candidate graph-change proposals with provenance, policy checks, and verifier closure. |

## SeedCore Interpretation

### GraphRAG is baseline, not authority

GraphRAG is now best understood as a retrieval-workflow family: graph-based
indexing, graph-guided retrieval, and graph-enhanced generation. That is useful
for SeedCore, but it does not alter the authority model.

For SeedCore, a graph retriever may discover candidate context. It does not
decide whether the principal is allowed to see that context, whether the
context is fresh enough, whether a generated claim is verified, or whether a
later physical or digital action is admissible.

The enforced path remains:

```text
query / workflow need
  -> RAGAuthorizationEnvelope
  -> controlled retrieval candidates
  -> per-candidate PDP / policy decision
  -> RAGEvidenceItem / RAGEvidenceBundle
  -> guarded generation or advisory planning
  -> claim verification
  -> RAGTrace / RAGReceipt
```

### Path-centric retrieval needs path-level evidence

PathRAG and K-Paths sharpen an important point: the hard retrieval problem is
often not lack of context, but too much redundant or weakly related context.
For SeedCore this suggests a future path-evidence profile.

A governed path evidence item should bind at least:

- `path_id` and path hash;
- ordered node IDs and edge IDs;
- node, edge, and source hashes;
- graph snapshot or index snapshot;
- ACL or policy snapshot refs for every material node and edge;
- the query or sub-objective that selected the path;
- the retriever and pruning algorithm versions;
- authorization decision IDs for path admission;
- freshness and revocation posture;
- denied-path aggregate counts without exposing denied node or edge details.

This is an extension of the existing RAG evidence contract, not a replacement
for it. If any required node, edge, source, or snapshot cannot be authorized or
replayed, the path should produce `blocked`, `escalated`, `abstained`, or
`lite_receipt` closure rather than fallback to ungoverned context.

### Agentic graph systems belong behind gated tools

Plan-on-Graph-style systems and Text-to-Cypher agents make the graph feel like
an environment rather than a passive index. That is attractive for operator
copilots, policy graph authoring, and forensic replay exploration.

SeedCore should split graph tool access into three classes:

| Tool class | Example | Required boundary |
| :--- | :--- | :--- |
| Read-only advisory query | schema lookup, bounded Cypher read, path explanation | principal/workflow binding, purpose restriction, query log, safe output redaction |
| Evidence-producing retrieval | path retrieval, document-to-entity support, cited graph fact lookup | RAG authorization envelope, PDP decisions, evidence bundle, trace closure |
| State-changing graph action | policy graph publish, authz graph mutation, custody graph mutation | `@gated_action` / Agent Action Gateway, PDP allow, scoped `ExecutionToken`, co-signed mutation receipt where required, verifier/replay closure |

MCP-style graph tools can be useful integration surfaces, but generic read/write
Cypher access is too broad for SeedCore's production authority boundary. A
SeedCore-facing graph tool should expose constrained, named operations with
policy-visible input schemas and replayable outputs.

### KG foundation models stay non-authoritative

ULTRA, MERRY, GraphOracle, and related graph foundation model work are
promising for structural KG reasoning and zero-shot or low-shot transfer. Their
best near-term SeedCore role is not as a PDP replacement.

Good uses:

- suggest missing links or relation patterns for human or policy review;
- rank candidate paths before deterministic authorization;
- generate advisory explanations for why a graph path may matter;
- support benchmark-gated graph-engine research under ADR 0011;
- produce shadow evidence for policy graph builder UX.

Unsafe uses:

- authorizing access based on inferred link probability;
- mutating active policy or authz graphs from model output alone;
- clearing quarantine because a graph model predicts consistency;
- treating cross-graph generalization as proof of source truth;
- replacing replayable evidence closure with model confidence.

If a graph foundation model proposes a new relation, edge, or policy candidate,
SeedCore should represent that output as a proposal with model provenance,
input snapshot refs, confidence metadata, and review status. It can become
authority-relevant only after a governed promotion path admits it.

## Adoption Guidance

### Adopt now

- Keep GraphRAG, LightRAG, LazyGraphRAG, PathRAG, and K-Paths as research
  inputs for the controlled-source retrieval lane.
- With the chunk-level controlled-source fixture adapter and deterministic
  policy callout green, extend the future RAG contract vocabulary toward path
  evidence only after trace/replay and receipt boundaries are explicit.
- Treat graph-query agents as policy-visible tools, not free-form database
  shells.
- Use graph foundation models only in shadow/advisory lanes until a promotion
  receipt and verifier path exists.

### Spike later

- `RAGPathEvidenceItem` or equivalent path-evidence profile.
- A constrained Cypher/SPARQL read tool that returns redacted, policy-admitted
  evidence objects rather than raw graph dumps.
- Planner memory for graph exploration that records sub-objectives,
  self-corrections, query attempts, and rejected paths for replay.
- Benchmark fixtures comparing chunk retrieval, path retrieval, and compiled
  authz-graph traversal under ADR 0011.

### Defer

- Broad enterprise graph connector sprawl.
- Production write-capable MCP graph tools without gated actions.
- Treating Text-to-Cypher validation as a verifier substitute.
- Promoting inferred KG edges into active policy/authz graphs without co-signed
  receipts and graph-bound mutation gates.
- Replacing SeedCore PDP, `ExecutionToken`, evidence bundle, or
  `RESULT_VERIFIER` semantics with KG model confidence.

## Immediate Next Slice

Do not start by adding a graph database adapter or foundation model. The
controlled-source chunk path is now fixture-green; the next safe implementation
slice is to deepen verifier and replay closure:

1. cross-check bundle, draft, claim, parser output, and policy decision
   references against concrete artifacts;
2. add a RAG receipt / minimal-evidence-set profile with degraded outcomes;
3. add side-channel-safe denial and latency telemetry;
4. then add a path-evidence profile for graph paths.

The path-evidence work should begin as a contract extension and fixture set. It
should not require selecting Neo4j, Memgraph, RDF, vector search, GraphRAG,
LightRAG, PathRAG, or a KG foundation model as the production substrate.

## References Checked

- [GraphRAG: Unlocking LLM discovery on narrative private data](https://www.microsoft.com/en-us/research/blog/graphrag-unlocking-llm-discovery-on-narrative-private-data/)
- [LazyGraphRAG: Setting a new standard for quality and cost](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [LightRAG: Simple and Fast Retrieval-Augmented Generation](https://arxiv.org/abs/2410.05779)
- [HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models](https://arxiv.org/abs/2405.14831)
- [PathRAG: Pruning Graph-based Retrieval Augmented Generation with Relational Paths](https://arxiv.org/abs/2502.14902)
- [K-Paths: Reasoning over Graph Paths for Drug Repurposing and Drug Interaction Prediction](https://arxiv.org/abs/2502.13344)
- [Plan-on-Graph: Self-Correcting Adaptive Planning of Large Language Model on Knowledge Graphs](https://arxiv.org/abs/2410.23875)
- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro)
- [Neo4j MCP documentation](https://neo4j.com/docs/mcp/current/)
- [Towards Foundation Models for Knowledge Graph Reasoning](https://arxiv.org/abs/2310.04562)
- [Beyond Completion: A Foundation Model for General Knowledge Graph Reasoning](https://aclanthology.org/2025.findings-acl.1046/)
- [GraphOracle: A Foundation Model for Knowledge Graph Reasoning](https://arxiv.org/abs/2505.11125)
