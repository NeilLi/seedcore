# Policy-Governed RAG Research Adoption Review

Date: 2026-06-22
Status: Architecture review and adoption guidance
Related:

- [ADR 0008: Enterprise RAG as Governed Evidence Acquisition](../architecture/adr/adr-0008-enterprise-rag-governed-evidence-acquisition.md)
- [ADR 0009: Authorization-Aware Retrieval Boundary](../architecture/adr/adr-0009-authorization-aware-retrieval-boundary.md)
- [RAG Evidence Bundle and Trace Contract](../architecture/contracts/rag_evidence_bundle_trace_contract.md)
- [Knowledge Graph RAG Research Reference](kg_rag_research_reference.md)
- [Current Next Steps](current_next_steps.md)

## Research Signal

The Policy-Governed RAG research note is directionally aligned with SeedCore.
Its useful contribution is not "better RAG" in the ordinary chatbot sense. It
sharpens the RAG pipeline into three auditable boundaries:

1. **Contracts and control:** apply policy before text reaches the model.
2. **Manifests and trails:** bind cited evidence to source, policy, hash, and
   replay context.
3. **Receipts and verification:** emit a portable proof object that lets an
   auditor reconstruct what was authorized, shown to the model, cited, and
   accepted or blocked.

SeedCore already has the first two boundaries in architectural form and a first
vendor-neutral implementation slice for allow-only evidence promotion:

- `RAGAuthorizationEnvelope`
- per-chunk `RAGAuthorizationDecision`
- `RAGEvidenceItem`
- `RAGEvidenceBundle`
- `RAGTrace`
- `promote_authorized_rag_candidates(...)`

The research should therefore be adopted as a hardening overlay, not as a new
architecture center and not as a reason to import a full RAG platform.

The June 2026 KG / GraphRAG research signal adds one refinement to this review:
GraphRAG is better treated as a baseline retrieval pattern than as the frontier
itself. The frontier has split into efficient graph-enhanced retrieval,
path-centric evidence retrieval, agentic graph query/control systems, and graph
foundation models for structural KG reasoning. SeedCore should use that split as
roadmap input, while keeping every graph-derived chunk, path, query result, or
inferred edge behind the same PDP, evidence, verifier, and replay boundaries.

The enterprise trusted-AI / LLMOps signal adds a narrower prompt-engineering
lesson: versioned prompt structure, testing, and strict output schemas are
useful only when they sit behind SeedCore's governed evidence boundary. XML
tags, scratchpad isolation, and response prefill can improve prompt assembly
and parser reliability, but they do not become policy, authority, or proof.

## Verified Current Implementation State

As of 2026-06-22, the implemented codebase should be described narrowly:

- The governed RAG data contracts and allow-only promotion guard are implemented
  in `src/seedcore/models/rag.py` and
  `src/seedcore/ops/rag/authorization_boundary.py`.
- `promote_authorized_rag_candidates(...)` promotes only explicit
  `allow` decisions into `RAGEvidenceItem` objects and collapses denied,
  quarantined, or missing-decision candidates into aggregate denial counts.
- Focused tests in `tests/test_governed_rag_contracts.py` cover the promotion
  boundary, missing-decision handling, supported-claim evidence requirement, and
  accepted-trace closure-reference requirement.

The following pieces are not yet implemented as an end-to-end governed RAG
service and should remain explicit next work rather than implied current
behavior:

- production retrieval adapters that emit `RAGCandidateChunk` objects from a
  controlled source;
- a synchronous PDP or policy-check callout that mints the
  `RAGAuthorizationDecision` inputs consumed by the promotion guard;
- guarded prompt assembly that can only read from the returned
  `RAGEvidenceBundle`;
- verifier checks that every cited `evidence_item_id` belongs to the authorized
  bundle;
- trace/replay validation that cross-checks bundle, draft, claim, and policy
  decision references against concrete artifacts;
- RAG receipt signing, minimal-evidence-set artifacts, degraded/lite receipt
  outcomes, and side-channel-safe telemetry tests.

Primary references checked:

- [Policy-Governed RAG - Research Design Study](https://arxiv.org/abs/2510.19877)
- [RFC 9052: CBOR Object Signing and Encryption (COSE)](https://datatracker.ietf.org/doc/rfc9052/)
- [RFC 9053: COSE Algorithms](https://www.rfc-editor.org/info/rfc9053/)
- [RFC 7515: JSON Web Signature (JWS)](https://datatracker.ietf.org/doc/html/rfc7515)
- [RFC 7516: JSON Web Encryption (JWE)](https://www.rfc-editor.org/info/rfc7516/)
- [IETF SCITT working group](https://datatracker.ietf.org/wg/scitt/)
- [Open Policy Agent policy language](https://www.openpolicyagent.org/docs/policy-language)
- [Cedar policy language reference](https://docs.cedarpolicy.com/)

## What To Adopt

### 0. KG / GraphRAG routing taxonomy

Use [Knowledge Graph RAG Research Reference](kg_rag_research_reference.md) as
the living map for graph-retrieval research. Its SeedCore mapping is:

- Efficient GraphRAG patterns can inform the controlled-source retriever, but
  retrieved context still needs authorization before model-visible use.
- PathRAG / K-Paths-style retrieval can inform a future path-evidence profile,
  but each material node, edge, source, and graph snapshot must be authorized
  and replay-bound.
- Plan-on-Graph, Text-to-Cypher, and MCP graph tools belong behind constrained,
  policy-visible tool schemas. Write-capable graph actions require gated
  action semantics, scoped execution authority, and receipt closure.
- KG foundation models such as ULTRA, MERRY, and GraphOracle are advisory
  or shadow reasoning inputs until their outputs are promoted through a
  governed evidence or graph-mutation path.

### 0A. Guarded prompt assembly conventions

Adopt structured prompt conventions as a route-level guarded prompt assembly
profile, not as new core evidence-schema fields.

Recommended posture:

- Use deterministic section delimiters, including XML-style tags such as
  `<evidence>`, `<policy_rules>`, and `<action_parameters>`, inside prompt
  templates that render from an already authorized `RAGEvidenceBundle`.
- Treat those tags as model-visible isolation boundaries only. They do not
  replace `RAGEvidenceItem`, `RAGEvidenceBundle`, PDP decision IDs,
  `VerifiedRAGClaim`, `RAGTrace`, or receipt validation.
- Keep scratchpad or chain-of-thought instructions isolated from the parsed
  final payload. Do not persist scratchpad text as authority-bearing evidence.
- Version the prompt template, model config, route schema, and parser profile
  so replay can reconstruct which assembly profile produced a draft answer.
- Add negative tests proving denied, quarantined, or missing-decision chunks
  cannot appear in any rendered prompt section, citation payload, ordinary log,
  or proof UI.

Decision on XML tag standardization: standardize tag names in guarded prompt
assembly templates and tests first. Do not put `<evidence>` or
`<policy_rules>` inside RAG evidence schema validation levels until an
implementation needs a serialized prompt-render artifact with verifier support.

Decision on prefill conventions: allow response-prefill profiles for strict
developer-facing routers, but keep them optional and route-configured. SDK
preflight checks should not automatically emit a prefill prefix by default,
because preflight is about authority and readiness, while prefill is a
formatting reliability control. A route may advertise a suggested prefix only
when it also declares the expected output schema and fail-closed parse behavior.

### 1. Receipt profile for RAG traces

SeedCore should add a `RAGReceipt` contract that signs the existing RAG trace
closure. The receipt should bind:

- `trace_id`
- `authorization_envelope_id`
- `evidence_bundle_id`
- `draft_answer_id` when a draft exists
- verified claim IDs and claim support outcomes
- policy decision IDs
- denied candidate aggregate counts
- retriever, embedding, prompt, model, and verifier versions
- `bundle_hash`, `answer_hash`, and `trace_hash`
- final status: `accepted`, `blocked`, `escalated`, or `abstained`
- degradation mode, if any

The receipt proves process integrity and replayability. It does not prove the
LLM answer is objectively true, nor does it mint execution authority. It should
be treated like SeedCore's other proof artifacts: audit evidence under PDP,
token, verifier, and replay semantics.

Adoption profile:

- MVP: SeedCore-native JSON receipt signed through existing evidence-signing
  profiles.
- External audit profile: JOSE/JWS for JSON-centric auditors.
- Compact or device/profile-specific profile: COSE/CBOR after a real consumer
  requires it.
- Transparency profile: evaluate SCITT-style registration after the local
  receipt payload and replay validator are stable.

### 2. Minimal evidence set as a verifier artifact

The research's "minimal evidence set" idea is useful, but SeedCore should not
let it become model-driven evidence selection. Define it as a verifier-side
artifact:

- Start from the authorized `RAGEvidenceBundle`.
- Verify each material claim against cited evidence.
- Remove redundant evidence only when the same claim remains supported by the
  remaining authorized items.
- Record the algorithm, verifier version, and resulting minimal item IDs.
- Keep the full authorized bundle available for replay and forensics.

This keeps the model from deciding what evidence is legally sufficient while
still giving auditors a smaller claim-support set.

### 3. Abstain and lite receipt outcomes

SeedCore should explicitly model degraded RAG outcomes:

- `blocked`: policy, authorization, or verifier failure.
- `escalated`: allowed evidence exists, but human or higher-assurance review is
  required.
- `abstained`: the system refuses to answer because evidence is insufficient,
  stale, conflicted, or not authorized.
- `lite_receipt`: a degraded receipt that proves the boundary stopped safely
  but does not claim full answer verification.

This maps naturally to SeedCore's existing quarantine and fail-closed doctrine.
The system may explain the refusal at the policy-controlled level, but denied
candidate content and sensitive existence signals must stay hidden.

### 4. Side-channel-safe retrieval telemetry

The research calls out timing and leakage concerns around denied resources.
SeedCore should adopt the principle but keep it policy-specific:

- expose denied resources only as aggregate counts and reason-count buckets;
- avoid per-document timing, title, snippet, or existence leakage;
- report latency as coarse histogram buckets for the whole retrieval boundary;
- keep raw candidate and denied-content details in restricted forensic storage,
  if retained at all;
- make denial disclosure itself policy-controlled.

The current `RAGDeniedCandidateSummary` is a good starting point. The next
contract step is to add a safe telemetry profile to `RAGTrace` or `RAGReceipt`
rather than leaking diagnostic detail through ordinary logs or UI.

## What Not To Adopt Yet

### Do not claim leak elimination

The paper is a research-design artifact with stated targets, not production
proof that all leaks are eliminated. SeedCore docs should say "prevents denied
chunks from entering model-visible context under the enforced contract" rather
than "completely eliminates data leaks."

### Do not make receipts authority-bearing

A receipt can prove which policy decisions, evidence items, hashes, and
verification outcomes were bound together. It cannot authorize a future action.
For high-consequence execution, authority still requires:

```text
PDP allow -> scoped ExecutionToken -> actuator attempt -> evidence closure
-> verifier outcome -> replayable receipt
```

### Do not add a vector database mandate

The research does not change the existing ADR decision to defer vector database
selection. Qdrant, Milvus, pgvector, Weaviate, and search engines are substrate
choices under the authorization boundary. The first production-like RAG slice
should still use one controlled source before broad enterprise connectors.

### Do not add COSE/JOSE before the payload contract is stable

COSE and JOSE are useful formats, but they should wrap a stable SeedCore
payload. Adding a signing container before the receipt schema and replay
validator exist would create cryptographic ceremony around an immature contract.

### Do not make KG inference authority-bearing

Graph foundation models, path-pruning algorithms, Text-to-Cypher validators, or
agentic graph planners may improve candidate discovery and explanation quality.
They must not authorize access, publish policy/authz graph mutations, clear
quarantine, or replace replayable evidence closure. If they propose a new edge,
relation, path, or policy candidate, SeedCore should record it as a
provenance-bound proposal until a governed promotion path admits it.

## Recommended Stack Posture

| Layer | Adopt now | Spike later | Defer |
| :--- | :--- | :--- | :--- |
| Policy enforcement | Existing SeedCore PDP/PKG boundary and allow-only promotion | OPA/Rego or Cedar policy-authoring adapters only if they compile into pinned SeedCore decisions | LLM-as-policy-judge |
| Retrieval source | One controlled SeedCore docs/object-store source | pgvector or existing search/index adapters behind `RAGCandidateChunk` | Enterprise connector sprawl |
| Evidence and receipt | SeedCore JSON receipt signed by existing signer profiles | JOSE/JWS external audit profile | COSE/CBOR until compact/device/auditor need is real |
| Transparency | Local trace/replay validator | SCITT-style registration for external audit packages | Public transparency log by default |
| Claim verification | Deterministic citation/span checks first | NLI or LLM-judge as advisory verifier input with fail-closed handling | Unbounded model self-verification |
| Minimal evidence | Verifier-side minimal support set | Greedy minimization with recorded algorithm version | Model-selected legal sufficiency |
| Metrics | Aggregate denied counts and coarse latency histograms | Side-channel review under adversarial fixtures | Per-denied-document diagnostics in ordinary logs |
| KG / graph retrieval | Controlled-source chunk retrieval first | Path-evidence profile and constrained read-only graph query tools | Broad graph connector sprawl or write-capable graph agents before gated action boundaries |

## Immediate SeedCore Work

1. Build a controlled-source retrieval adapter that emits `RAGCandidateChunk`
   objects without selecting a broad vector-database or enterprise connector
   stack.
2. Add the PDP/policy decision callout that turns candidate chunks into
   `RAGAuthorizationDecision` inputs for the existing promotion guard.
3. Add guarded prompt assembly that accepts only a `RAGEvidenceBundle` and test
   that denied or missing-decision content cannot enter prompt input, citations,
   ordinary logs, or proof UI payloads. This slice should include versioned
   prompt sections, optional route-level response prefill, strict schema parse
   failure handling, and replayable prompt-render metadata.
4. Extend verifier and trace validation so supported claims cite only authorized
   bundle members and accepted traces cross-check bundle, draft, claim, and
   policy decision references.
5. Extend the RAG contract with a `RAGReceipt` profile and degradation modes.
6. Add `minimal_evidence_item_ids` and verifier metadata to the RAG trace or a
   companion verifier artifact.
7. Add side-channel-safe telemetry fields for aggregate denial and latency
   reporting.
8. After the chunk-level lane is green, add a path-evidence contract extension
   that binds path hashes, node/edge/source hashes, graph snapshot refs,
   authorization decision IDs, and denied-path aggregate counts.
9. Keep vector DB, graph DB, connector, COSE, JOSE, SCITT, NLI, Cypher agent,
   and KG foundation model choices behind the contract until the
   controlled-source RAG lane is green.

## Bottom Line

SeedCore should adopt the research's governance shape, not its hype. The
architecture already points in the right direction: policy before context,
evidence before generation, verifier before acceptance, replay before trust.
The next upgrade is to make guarded prompt assembly, RAG receipts, minimal
evidence sets, degraded outcomes, and side-channel-safe telemetry explicit
enough that every later retriever, connector, verifier, prompt profile, or
signing format has to obey the same authority-preserving contract.
