# RFC: SeedCore Authorization PKG as a Live Decision Graph

## Status

Proposed

## Summary

The key shift in this RFC is simple:

> A useful PKG is not a knowledge graph about the domain in general.
> It is a decision graph for authorization under live context.

For SeedCore, especially in provenance-heavy supply-chain workflows, the graph should answer questions like:

- Is this actor allowed to perform this action on this asset now?
- Does the actor have a valid authority path to the asset or twin?
- Are the current custody, zone, workflow, device, telemetry, and evidence conditions sufficient?
- If denied or quarantined, what prerequisite is missing?
- If allowed, what governed receipt or obligation must be minted?

This RFC formalizes two things:

1. The baseline that already exists in SeedCore today.
2. The enhanced direction that should guide the next iterations of the authorization graph.

The baseline is a snapshot-scoped authorization graph projection compiled into an in-memory PDP index. The enhanced direction is a path-centric, explanation-first, asset-centric decision graph with a clean separation between hot authorization logic and broader knowledge enrichment.

## Problem Statement

SeedCore already has strong ingredients for deterministic policy control:

- versioned policy snapshots in PostgreSQL
- deterministic evaluation through OPA WASM or native rules
- hot-swap activation through Redis
- a synchronous `ActionIntent` Policy Decision Point (PDP)
- an authorization graph package under `src/seedcore/ops/pkg/authz_graph/`

What has been missing is a sharper design target for the graph itself.

The authorization graph should not become a giant enterprise ontology. It should become the smallest, hottest, most explainable graph that can answer high-value authorization questions in bounded time.

## Decision Target

The graph should be designed from authorization questions, not ontology completeness.

SeedCore should begin from the highest-value PDP decisions it must answer in under tens of milliseconds, for example:

- Can this inspection agent seal this lot now?
- Can this warehouse operator transfer custody of this batch?
- Can this robot arm manipulate this item in this zone?
- Can this partner read or append provenance for this shipment?
- Can this edge device sign evidence for this frame?

These questions imply a graph centered on:

- principals
- resources and assets
- actions
- live context
- policy constraints
- evidence

That is the backbone of a useful PKG for SeedCore.

## Baseline: What SeedCore Already Has

SeedCore already implements the core shape of an authorization graph runtime:

- snapshot-scoped projection orchestration in `src/seedcore/ops/pkg/authz_graph/service.py`
- deterministic graph projection in `src/seedcore/ops/pkg/authz_graph/projector.py`
- an explicit graph ontology in `src/seedcore/ops/pkg/authz_graph/ontology.py`
- a compiled in-memory authorization index in `src/seedcore/ops/pkg/authz_graph/compiler.py`
- active snapshot lifecycle management in `src/seedcore/ops/pkg/authz_graph/manager.py`
- runtime API endpoints documented in `docs/references/api/seedcore-api-reference.md`

### Baseline Properties

The current baseline is already directionally correct:

- PostgreSQL snapshots remain the governance source of truth.
- The authorization graph is rebuildable and projection-based.
- The synchronous PDP can consume a compiled read-only index.
- Decisions can produce `allow`, `deny`, or `quarantine`.
- Governed decision receipts and trust-gap semantics already exist.
- The runtime can refresh the active compiled authorization graph independently of a full PKG reload.

### Baseline Limits

The current baseline is still more permission-edge-centric than decision-path-centric.

It models:

- principals, roles, assets, resources, zones, custody points, inspections, attestations, tracking events, twins, and receipts
- edges such as `has_role`, `delegated_to`, `can`, `held_by`, `located_in`, and `governed_by`
- permission constraints largely attached to `can` edges

That is a strong starting point, but the next iterations should make authority paths, runtime context, explanation, and first-class constraints more explicit.

## Design Principles

### 1. Start from decisions, not encyclopedic modeling

Do not model all of supply chain first. Model the highest-value authorization questions first.

### 2. Model authority as paths

SeedCore authorization should move from:

- "principal has role"

to:

- principal is delegated by organization
- organization is approved for facility
- facility controls zone
- asset is in zone
- action requires certification, workflow state, or trust state
- device is bound to principal and currently attested
- policy allows the transition only if live conditions hold

The PDP should evaluate whether a valid path exists from principal to authority to resource to action under the current governed context.

### 3. Separate stable structure from hot runtime state

Identity and domain structure change slowly. Telemetry, attestation, custody, workflow stage, and network state change quickly. These should not be modeled as if they have the same lifecycle.

### 4. Keep the hot path deterministic

No live LLM calls, GraphRAG lookups, or probabilistic scoring should decide the final `allow` or `deny` outcome in the CONTROL path.

### 5. Optimize for explanation, not only decision

The graph is most valuable when it can explain:

- which rule matched
- which authority path was used
- which constraints were evaluated
- which prerequisite was missing
- which obligations or receipts were created

## Target Architecture

The PKG should evolve into four related planes.

### 1. Policy Plane

Authoritative policy remains in the current snapshot system:

- `pkg_snapshots`
- `pkg_policy_rules`
- `pkg_facts`
- OPA or native rule artifacts

This is the governance root.

### 2. Decision Graph Plane

This is the hot, authorization-focused graph used to answer live questions. It should contain only entities and relationships needed for deterministic decisions.

Examples:

- principals and organizations
- devices and certifications
- assets, lots, batches, shipments, twins
- facilities, zones, and workflow stages
- custody, attestation, telemetry, and inspection state
- policy rules, constraints, obligations, and evidence references

### 3. Compiled PDP Plane

The synchronous PDP should read an immutable compiled index derived from the active decision graph snapshot.

Examples:

- subject closure for role and delegation traversal
- permission and deny indexes
- resource-to-asset and asset-to-zone indexes
- current custodian and transferability summaries
- freshness windows for telemetry and inspections
- compiled transition requirements

### 4. Enrichment And Advisory Plane

This is the broader graph for analytics and learning, not the synchronous authorization hot path.

Examples:

- historical provenance expansion
- partner relationship analytics
- anomaly markers
- exception clustering
- document-to-policy mapping
- natural-language explanation helpers

## Decision Graph Versus Enrichment Graph

Architecturally, SeedCore should treat the PKG as two graphs, not one.

### Decision Graph

Small, hot, latency-sensitive, directly used by the PDP.

It should contain only what is required to answer:

> Given this principal, asset, device, place, workflow step, and current state, is this action allowed now?

### Enrichment Graph

Richer, broader, and slower-moving.

It should support:

- analytics
- onboarding new policies
- anomaly detection
- natural-language policy assistance
- partner and provenance exploration
- explanation views that are not part of the synchronous decision boundary

This separation matters because the PDP should not traverse a huge and noisy graph if deterministic latency is a product requirement.

## Layered Ontology

The ontology should be designed in four layers.

### A. Core Identity And Authority Layer

Changes slowly.

Examples:

- `Org`
- `HumanPrincipal`
- `AgentPrincipal`
- `ServicePrincipal`
- `DevicePrincipal`
- `Facility`
- `Zone`
- `ActionType`
- `Certification`
- `PolicyTemplate`

### B. Supply-Chain Domain Layer

Defines what the business governs.

Examples:

- `Product`
- `Batch`
- `Lot`
- `Shipment`
- `Container`
- `Twin`
- `InspectionEvent`
- `CustodyState`
- `ProvenanceRecord`
- `ComplianceProgram`
- `HandlingConstraint`

### C. Runtime Context Layer

Changes frequently and must remain compact and easy to update.

Examples:

- current location
- current custodian
- active device attestation
- temperature or humidity window
- network trust state
- current workflow stage
- shift window
- edge node health

### D. Evidence Layer

Binds decisions to proof.

Examples:

- `ExecutionToken`
- `PolicyDecision`
- `DecisionReceipt`
- `EvidenceBundle`
- `SignatureProof`
- `TelemetrySnapshot`
- `CustodyEvent`
- `ReplayReceipt`

## Baseline V1 Contract Versus Enhanced V2 Direction

The current implementation should be treated as Baseline V1. The next modeling direction should be treated as Enhanced V2.

| Concern | Baseline V1 | Enhanced V2 Direction |
| :--- | :--- | :--- |
| Authority modeling | role, delegation, and `can` edges | explicit principal-to-authority-to-resource-to-action paths |
| Resource model | generic `asset` and `resource` nodes | richer supply-chain resource types such as lot, batch, shipment, container, twin |
| Runtime context | constraints mostly attached to permission edges | runtime state elevated into graph-visible context nodes and edges |
| Evidence | receipts and trust gaps exist | explicit evidence bundles, obligations, proof links, and decision artifacts |
| Explanation | reason codes and receipts | full path-of-authority, constraints checked, missing prerequisite, and minted obligations |
| Graph scope | one operational authz graph | split decision graph and enrichment graph |

Enhanced V2 should build on V1 rather than replace it. The current compiler and projector remain the foundation.

## V2 Minimum For The Next Killer Demo

The next killer demo does not need the full conceptual V2 target at once.

For the next implementation phase, the enforced V2 minimum should support one
canonical workflow only:

**Restricted Custody Transfer**

### Frozen V2 Minimum Entities

- `Org`
- `AgentPrincipal`
- `DevicePrincipal`
- `Facility`
- `Zone`
- `Lot`
- `CustodyState`
- `WorkflowStage`
- `PolicyRule`
- `Constraint`
- `ExecutionToken`
- `DecisionReceipt`

### Frozen V2 Minimum Path Types

- principal delegated by org
- org approved for facility
- facility controls zone
- lot located in zone
- transfer action governed by rule
- transition requires dual approval
- current custodian matches expected custodian
- telemetry freshness and inspection freshness where policy requires them

Everything else in V2 should be treated as secondary until this workflow is
proven end to end.

## Practical Schema Direction For SeedCore

The enhanced schema should organize around five families.

### Principal Side

Nodes:

- `(:Org)`
- `(:HumanPrincipal)`
- `(:AgentPrincipal)`
- `(:ServicePrincipal)`
- `(:DevicePrincipal)`

Edges:

- `[:MEMBER_OF]`
- `[:OPERATES]`
- `[:BOUND_TO_DEVICE]`
- `[:DELEGATED_BY]`
- `[:CERTIFIED_FOR]`

### Resource Side

Nodes:

- `(:Product)`
- `(:Lot)`
- `(:Batch)`
- `(:Shipment)`
- `(:Twin)`
- `(:EvidenceBundle)`
- `(:Facility)`
- `(:Zone)`

Edges:

- `[:PART_OF]`
- `[:LOCATED_IN]`
- `[:REPRESENTED_BY]`
- `[:HAS_EVIDENCE]`
- `[:UNDER_CUSTODY_OF]`

### Policy Side

Nodes:

- `(:ActionType)`
- `(:PolicyRule)`
- `(:Constraint)`
- `(:Obligation)`
- `(:ComplianceProgram)`

Edges:

- `[:CAN_ATTEMPT]`
- `[:GOVERNED_BY]`
- `[:REQUIRES]`
- `[:SATISFIED_BY]`
- `[:DENIES_IF]`
- `[:OBLIGATES]`

### Runtime Side

Nodes:

- `(:ExecutionContext)`
- `(:TelemetryState)`
- `(:NetworkState)`
- `(:AttestationState)`
- `(:WorkflowStage)`

Edges:

- `[:IN_CONTEXT]`
- `[:HAS_STATE]`
- `[:AT_STAGE]`
- `[:AT_TIME]`

### Evidence Side

Nodes:

- `(:DecisionReceipt)`
- `(:ExecutionToken)`
- `(:SignatureProof)`
- `(:CustodyEvent)`

Edges:

- `[:ISSUED_FOR]`
- `[:SIGNED_BY]`
- `[:RECORDED_AS]`
- `[:PROVES]`

These schema families are logical targets. They can be materialized as new labels and edge kinds, or as specializations layered over the current `NodeKind` and `EdgeKind` contract.

## Constraint Modeling Strategy

Constraint handling should be staged.

### Baseline V1

Keep decision-critical constraints on compiled permission structures so the current compiler stays simple and deterministic.

Examples:

- zone restrictions
- network restrictions
- custody point requirements
- telemetry freshness windows
- inspection freshness windows
- attestation and seal requirements
- transferability requirements

### Enhanced V2

Promote the highest-value constraints into first-class graph structure where explanation and graph querying benefit from it.

Examples:

- allowed temperature band
- allowed geography
- inspection-before-transfer
- two-party approval
- certified-device-only sealing
- same-facility-only transfer unless export release exists
- deny while custody dispute is open

Decision-relevant constraints should be graph-visible. Richer raw payloads can still live in documents.

## Evaluation Semantics

The PDP should increasingly answer state-transition questions rather than coarse subject-action checks.

The authorization question becomes:

> Can this principal, possibly bound to a device and acting under delegated authority, perform this specific action on this specific asset or twin under the current governed context?

The evaluation flow should be:

1. Receive `ActionIntent` with principal, action, asset or resource, and live context.
2. Resolve the active compiled authorization graph snapshot.
3. Resolve principal closure across role, delegation, and authority path relationships.
4. Resolve the target asset, twin, batch, shipment, or resource neighborhood.
5. Evaluate deterministic permission or deny matches.
6. Evaluate live constraints such as zone, workflow stage, custody continuity, telemetry freshness, inspection freshness, attestation, device binding, and network state.
7. Return `allow`, `deny`, or `quarantine`.
8. Mint a governed receipt and any required obligations.
9. Return an explanation payload suitable for operator, auditor, or downstream replay use.

## Decision Outcomes

The decision engine should support three deterministic outcomes:

- `allow`
- `deny`
- `quarantine`

`quarantine` should remain a governed outcome, not an informal side effect. It is appropriate when the trust chain is incomplete but not contradictory, for example:

- stale telemetry
- expired inspection window
- missing expected custody checkpoint
- temporary evidence-source degradation

If the surrounding workflow supports it, a quarantine result may mint a restricted-scope token and mark the asset or twin as restricted until remediation completes.

## Explanation Contract

A useful authorization graph should explain every result.

At minimum, the PDP response should be able to return:

- disposition
- matched policy rule or deny condition
- authority path used
- evaluated constraints
- missing prerequisite when denied
- trust gaps when quarantined
- evidence obligations or governed receipt references created

For the next killer demo, the minimum frozen explanation payload should include:

- `disposition`
- `matched_policy_refs`
- `authority_path_summary`
- `missing_prerequisites`
- `trust_gaps`
- `minted_artifacts`
- `obligations`

Verification surfaces may summarize these fields, but they should not invent
authoritative policy meaning that is not derivable from this explanation layer.

Example explanation:

> Denied because `AgentPrincipal quality-twin-03` is bound to `Device edge-node-7`, but `Device edge-node-7` lacks valid calibration certification for `LotClass pharma-cold-chain`, required by `PolicyRule inspect_cold_chain_v4`.

## Governed Receipts And Digital Passport Fragments

SeedCore should continue treating decision artifacts as product surfaces, not just internal logs.

Every `allow` decision should mint a signed governed receipt that binds:

- decision hash
- policy snapshot version
- principal and asset identifiers
- approved operation or transition
- compiled decision basis
- custody and evidence references
- timestamps, validity, and signer metadata

For the next killer demo, obligations should also become explicit enough to
prove what must now exist because of the decision, for example:

- publish replay artifact
- generate transfer transition receipt
- attach telemetry proof
- close prior custodian state
- update the proof surface within the governed workflow

Successive receipt fragments can support a Mutable Digital Passport style view for downstream consumer, auditor, or regulator-facing trust surfaces without changing CONTROL-path semantics.

## Deterministic Plane Versus Advisory Plane

SeedCore should preserve a hard boundary:

### Deterministic Plane

- curated ontology
- signed or governed policy updates
- versioned graph mutations
- validated edge types
- explicit revocation logic
- compiled snapshot-scoped decision indexes

### Advisory Plane

- candidate policy extraction from documents
- anomaly markers
- natural-language regulation mapping
- topology analysis
- explanation summarization

AI may advise. Governance decides.

Advisory systems must not directly write trusted allow or deny semantics into the decision graph without a governed promotion workflow.

## Runtime And Storage Recommendations

### Near Term

- keep PostgreSQL as the policy source of truth
- use the existing authorization graph projection contract as the operational decision graph
- continue using Neo4j as the first graph-backed iteration path because the repository already has Neo4j foundations
- compile active graph snapshots into immutable in-process PDP indexes

### Scale Layer

Use Ray above the graph, not instead of the graph.

Ray actors are a good fit for:

- compiled snapshot builds
- regional or tenant-local cache warming
- hot subgraph shard caches
- facility or trade-lane scoped decision neighborhoods

The PDP decision function (stateless at decision time) should ask a local or near-local compiled cache first and only fall back to graph refresh or rebuild workflows outside the synchronous request path.

### Longer Term

Benchmark alternative graph stores only after the decision path is stable and measurable. If streaming updates or traversal speed become dominant bottlenecks, evaluate whether Memgraph or a multimodel store adds real value behind the same projection contract.

## Out Of Scope For Decision Graph V2 Minimum

The first V2 decision graph should explicitly exclude:

- partner analytics
- historical provenance exploration beyond the immediate required chain
- natural-language policy ingestion
- anomaly inference
- general-purpose knowledge nodes
- non-decision UI metadata

These may live in enrichment, analytics, or advisory surfaces, but they should
not shape the synchronous decision graph for the next killer demo.

## What To Avoid

### Trap 1: Giant Universal Ontology

Do not try to model all of supply chain before proving the decision wedge.

### Trap 2: RBAC In Graph Clothing

If the graph is only users, roles, and permissions with prettier edges, SeedCore is not using graph structure to solve the right problem.

### Trap 3: Historical Analytics In The Hot Path

The decision graph must stay compact, deterministic, and bounded.

### Trap 4: AI Owning Final Authorization Semantics

LLMs and GraphRAG can propose, summarize, and detect. They should not own final allow or deny semantics in CONTROL.

## Phased Recommendation

### Phase 0: Baseline Hardening

Stabilize the current implementation:

- snapshot alignment
- projection rebuild determinism
- compiled index correctness
- staging rollout and refresh workflows
- governed receipt coverage

### Phase 1: Decision-Centric Ontology

Anchor the graph to concrete SeedCore authorization questions and identify the minimum domain entities required for the first wedge.

### Phase 2: Authority Path Expansion

Add explicit organization, facility, zone, device, certification, and delegated-authority path modeling.

### Phase 3: First-Class Constraints And Explanation

Promote the highest-value constraints into graph-visible structure and return explanation payloads that expose matched path, checked constraints, and missing prerequisites.

### Phase 4: Decision Graph Versus Enrichment Graph Split

Keep the hot decision graph compact while introducing a broader enrichment graph for analytics, policy discovery, and explanation support.

### Phase 5: Distributed Cache And Shard Layer

Use Ray actors to distribute hot compiled decision neighborhoods by region, tenant, facility, trade lane, or product family.

## Acceptance Criteria

This RFC is successful when the authorization graph can reliably answer five questions:

1. Authority: who is allowed to do what
2. Scope: on which exact asset, twin, or shipment
3. Condition: under what live context
4. Obligation: what evidence or follow-up is required
5. Explanation: why the answer was allow, deny, or quarantine

Phase success should also require:

1. snapshot-scoped deterministic behavior
2. no live database traversals in the synchronous PDP path
3. no live AI calls in the CONTROL path
4. a governed receipt or equivalent proof artifact for successful decisions
5. bounded latency suitable for the synchronous PDP

## Open Questions

- Which supply-chain entities should become first-class in the first product wedge: lot, batch, shipment, container, device, facility, or workflow stage?
- Which constraints should graduate from edge attributes into explicit graph nodes first?
- How should obligations be represented in the compiled index?
- What is the minimal explanation payload that is still operator- and regulator-useful?
- When should Ray-based shard caches be introduced versus keeping a single active compiled snapshot per environment?
- Which parts of the broader enrichment graph should remain completely outside the governed projection pipeline?

## Related Documents

- `docs/development/pdp_authz_graph_staging_rollout.md`
- `docs/development/policy_gate_matrix.md`
- `docs/references/api/seedcore-api-reference.md`
