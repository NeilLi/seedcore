# RFC: Authorization Graph for the Policy Knowledge Graph

## Status

Proposed

## Summary

SeedCore already has a strong policy control plane:

- versioned policy snapshots in PostgreSQL
- deterministic evaluation through OPA WASM or native rules
- hot-swap activation through Redis
- a synchronous `ActionIntent` Policy Decision Point (PDP)

What it does not yet have is a dedicated authorization graph that can answer path-based questions such as:

> Does this principal have a valid, snapshot-scoped path to perform this operation on this resource in this zone and network context?

This RFC introduces an **Authorization Graph** as a projection layer inside PKG. The graph does not replace the existing snapshot system. Instead, it complements it:

- PostgreSQL snapshots remain the source of truth for governed policy state.
- The authorization graph becomes a rebuildable operational projection.
- The synchronous PDP consumes a compiled in-memory authorization index derived from that graph.

For SeedCore's initial provenance and high-trust supply-chain wedge, this graph should be explicitly asset-centric. The system should treat high-value assets and their twins not as passive records, but as active participants in each authorization handshake. In practice, that means the PDP should evaluate identity, custody, lineage, telemetry, and state-transition validity together before issuing an execution token.

## Motivation

The current PKG in SeedCore is primarily a policy snapshot and rule-execution system, not yet a low-latency graph-native authorization engine. The repository already contains:

- PKG snapshot lifecycle and evaluation in `src/seedcore/ops/pkg/`
- a synchronous `ActionIntent` authorization boundary in `src/seedcore/coordinator/core/governance.py`
- graph foundations in Neo4j and DGL loaders
- governed facts, tracking events, source registrations, and twin-oriented state

That makes SeedCore a good fit for a graph-backed authorization projection, but not for replacing the current PKG control plane.

## Strategic Alignment: Asset-Centric Zero Trust

The near-term market wedge is provenance and high-trust supply chains where trust must be enforced at runtime rather than reconstructed after the fact. SeedCore should therefore evolve toward an asset-centric zero-trust model.

This changes the primary authorization question from:

> Is this actor allowed to perform this class of action?

to:

> Is this actor allowed to perform this specific state transition on this specific asset, with an intact custody and evidence chain, under the currently governed context?

This is not plain RBAC. It is closer to attribute-based and lineage-based access control, where the decision depends on:

- actor identity and role
- asset identity and twin state
- current and prior custodians
- route, zone, and facility context
- telemetry and inspection freshness
- authoritative attestations and registrations

For the supply-chain wedge, each high-value batch should behave like a sovereign root in the graph with a hardened, traversable history. The PDP should be able to prove that the requested action preserves the asset's governed trust chain before issuing any new execution token.

## Design Goals

1. Preserve the synchronous, stateless PDP contract.
2. Keep control decisions deterministic and snapshot-scoped.
3. Make authorization relationships explicit and traversable.
4. Keep AI and GraphRAG outside the CONTROL hot path.
5. Allow event-driven projection updates without making the PDP depend on live database traversals.
6. Treat asset state transitions, custody continuity, and lineage integrity as first-class authorization concerns.
7. Produce governed decision artifacts that can be reused as regulator-facing or consumer-facing proof.

## Non-Goals

- No live LLM, GraphRAG, or anomaly-model calls in the CONTROL PDP path.
- No direct authorization from unreviewed cognitive outputs.
- No replacement of the current Postgres snapshot catalog or OPA/native evaluator.
- No requirement that every PDP request hit Neo4j or Kafka.

## Current State

Today, SeedCore already provides:

- active policy snapshots and hot-swap management
- temporal PKG facts and governed fact persistence
- source registration and tracking-event projections
- a synchronous `ActionIntent -> PolicyDecision` function
- Ray as the distributed runtime substrate
- Neo4j-backed graph storage helpers

This means the missing piece is not orchestration. The missing piece is a coherent authorization graph contract that sits between governed domain state and the synchronous PDP.

## Proposed Architecture

The PKG should evolve into three related but distinct planes.

### 1. Policy Plane

Authoritative policy remains in the current snapshot system:

- `pkg_snapshots`
- `pkg_policy_rules`
- `pkg_facts`
- OPA/native rule artifacts

This plane defines what policy means and which snapshot is active.

### 2. Authorization Graph Plane

Introduce a rebuildable graph projection that stores authorization-relevant relationships:

- principals
- role profiles
- assets, twins, resources, and zones
- networks
- custody points and transfer paths
- source registrations and tracking evidence
- attestations, telemetry, and inspections
- twins and delegated authorities
- snapshot-scoped permission edges

This graph is deterministic and event-driven. It is not the source of truth. It is a projection of authoritative state.

### 3. Compiled PDP Plane

For the synchronous hot path, the active authorization graph snapshot is compiled into an immutable in-memory index:

- adjacency sets
- role membership closure
- permission rules by principal or role
- lineage and custody continuity summaries
- zone and network constraints
- asset state and transferability flags
- attestation and inspection validity windows
- validity windows

The PDP reads this compiled index directly in-process.

## Why This Split

This split preserves the current SeedCore contract:

- the graph database is good at relationship storage and projection
- the compiled index is good at single-digit-millisecond reads
- PostgreSQL snapshots remain the governance root
- governed receipts can be minted from deterministic PDP state without requiring a second evaluation path

Without this split, the system risks creating two competing sources of policy truth or pushing graph latency into the synchronous PDP.

## Phase Plan

### Phase 1: Ontology, Projection, Compilation

Add a new package:

- `src/seedcore/ops/pkg/authz_graph/`

Phase 1 contains:

- a strict ontology for nodes, edges, and graph snapshots
- deterministic projectors for current SeedCore models
- a compiler that produces a read-only permission index
- initial decision receipt schemas for allowed and quarantined actions
- unit tests

This phase does not yet wire the compiler into the PDP.

### Phase 2: Snapshot-Scoped Projection Service

Add a projection service that builds graph snapshots from:

- governed facts
- source registrations
- tracking events
- twin snapshots
- authorization-relevant policy metadata

The output should be keyed by active snapshot version and be rebuildable.

### Phase 3: PDP Integration

Call the compiled authorization index from `evaluate_intent(...)` after cryptographic and freshness validation, but before `ExecutionToken` issuance.

### Phase 4: Event-Driven Updates

Projection updates should follow the existing event-stream-first direction in SeedCore:

- tasks and multimodal ingestion
- tracking events
- governed fact persistence
- snapshot hot-swap events

Kafka or outbox-style event transport may drive the projection workers, but the active PDP must only read a local compiled snapshot.

### Phase 5: Distributed Warm Caches

Use Ray actors to:

- build compiled snapshots
- shard hot subgraphs
- prewarm policy projections near execution regions

Ray should improve build and distribution, not become a hard dependency on every PDP request.

## Ontology

The initial ontology should support the following entity classes.

### Node Kinds

- `principal`
- `role_profile`
- `asset`
- `asset_batch`
- `resource`
- `zone`
- `network_segment`
- `custody_point`
- `registration`
- `attestation`
- `inspection`
- `sensor_observation`
- `handshake_intent`
- `digital_passport_fragment`
- `tracking_event`
- `fact`
- `policy_snapshot`
- `twin`
- `receipt`

### Edge Kinds

- `has_role`
- `delegated_to`
- `can`
- `held_by`
- `transferred_from`
- `attested_by`
- `observed_in`
- `sealed_with`
- `located_in`
- `requested`
- `backed_by`
- `recorded_by`
- `governed_by`

### Permission Semantics

Phase 1 treats `can` edges as deterministic permission edges with:

- `operation`
- `effect`
- `constraints`
- `valid_from`
- `valid_to`
- provenance metadata

For the supply-chain wedge, the compiler should also support asset-centric decision predicates that are derived deterministically from projected state, including:

- current custodian continuity
- asset transferability and restricted-state flags
- route or zone compliance
- inspection freshness
- telemetry coverage windows
- attestation validity

These predicates should remain deterministic compiled facts. Advisory systems may contribute evidence-quality signals, but they must not become a probabilistic allow primitive in the CONTROL path.

## Projection Inputs

The first deterministic projection inputs should be:

- `ActionIntent`
- `Fact`
- `SourceRegistration`
- `TrackingEvent`
- `Twin` or equivalent digital asset state
- inspection and attestation records when available

Supported fact predicates in Phase 1:

- `hasRole`
- `delegatedTo`
- `allowedOperation`
- `locatedInZone`
- `heldBy`
- `transferredFrom`
- `attestedBy`
- `observedIn`
- `sealedWith`

These predicates are sufficient to stand up a coherent first compiler and test path.

## Decision Semantics

The PDP should move toward asset-centric state-transition decisions rather than coarse subject-action checks. A principal should not be allowed to move an asset merely because they have a role label. They should be allowed only when the compiled graph proves that:

- they are an authorized current or delegated custodian
- the asset is in a transferable state
- the intended transfer preserves custody and policy invariants
- required telemetry, inspection, and attestation conditions are satisfied for the current snapshot

### Trust Gaps and Quarantine

Supply-chain operations often contain incomplete or stale evidence. The compiler should therefore model trust gaps explicitly instead of collapsing all missing context into a generic deny.

The PDP should support three deterministic outcomes:

- `allow`: the transition is permitted and an execution token may be issued
- `deny`: the transition violates governed policy and no execution token is issued
- `quarantine`: the transition is operationally tolerated but the asset is moved into a restricted governed state pending remediation

A quarantine outcome is appropriate when the trust chain is incomplete but not yet contradictory, for example:

- telemetry coverage is stale
- an inspection window has expired
- an expected custody checkpoint is missing
- an evidence source is temporarily degraded

Quarantine must remain a governed outcome, not an informal side effect. If supported by the surrounding workflow, it should mint a restricted-scope token and mark the twin or asset state as restricted until a remediation event resolves the gap.

## Governed Receipt and Mutable Digital Passport

For this wedge, the decision artifact is a product surface, not just an internal audit log. Every `allow` decision should mint a signed governed receipt payload. Internally, this can evolve toward a Mutable Digital Passport (MDP) assembled from successive governed receipt fragments over the asset lifecycle.

The governed receipt should bind:

- a stable decision hash
- the policy snapshot version
- the principal and asset or twin identifiers
- the approved operation or state transition
- the compiled decision basis
- provenance or custody proof references
- supporting evidence references
- timestamps, validity, and signer metadata

The receipt may also include advisory fields such as an evidence quality score, provided those fields are clearly marked as advisory and are not the sole determinant of an allow decision.

The MDP concept fits naturally with the projection model:

- each allowed transition appends a new governed passport fragment
- fragments remain traceable to authoritative facts, events, and attestations
- consumer or regulator views can be derived from the same governed receipt chain without changing CONTROL-path semantics

## PDP Guardrails

The synchronous PDP must remain bounded:

- no network calls
- no live database traversals
- no LLM calls
- no GraphRAG calls
- no probabilistic scoring as the final allow signal

GraphRAG and neuro-symbolic systems may write advisory facts or risk markers into governed storage, but those must still pass through deterministic policy compilation before they influence authorization.

## Storage Recommendation

Near-term recommendation:

- keep PostgreSQL as the policy source of truth
- use Neo4j as the first operational authorization graph because the repository already contains Neo4j integration
- compile the active graph snapshot into in-process indexes for the PDP

Longer-term option:

- if hot-path graph mirror latency becomes a bottleneck, add a dedicated low-latency mirror such as Memgraph behind the same projection contract

## Risks

- accidentally creating a second policy source of truth
- allowing graph projection drift across snapshot versions
- leaking advisory AI outputs into CONTROL authorization
- letting direct graph queries creep into the PDP hot path
- overfitting ontology and compiler behavior to one vertical before the core projection contract stabilizes
- conflating customer-facing passport rendering with the deterministic receipt contract that backs it

## Canonical Wedge Scenarios

The following scenarios help anchor the architecture in high-trust supply-chain workflows without changing the core control-plane principles.

### A. Harvest-to-Vault Handshake

Flow:

- a harvester scans and mints a new batch in the field
- the system binds the scan, the actor identity, the location, and the anti-counterfeit or seal identifier into a single handshake intent

PDP expectations:

- validate zone membership, permit status, and registration freshness
- validate that the batch or twin is not already active under a conflicting seal
- issue an authorization result that mints the governed asset state

### B. Anomalous Diversion Block

Flow:

- a logistics actor attempts to receive or transfer a shipment at an unexpected facility

PDP expectations:

- validate the compiled custody chain and route or zone constraints
- allow advisory systems to contribute governed risk markers through prior projection, but not through live calls
- return a hard deny when the transition breaks lineage or route policy

### C. Consumer Truth Reveal

Flow:

- a downstream consumer or inspector scans a product and requests a bounded authenticity view

PDP expectations:

- validate the single-use handshake intent and any presentation constraints
- verify custody continuity and the governed receipt chain
- return an allow result with a derived, presentation-safe receipt or passport view

## Acceptance Criteria

Phase 1 is successful when:

1. authorization-relevant objects can be projected into a strict graph ontology
2. a compiled permission index can answer deterministic allow/deny checks
3. asset-centric lineage and custody constraints can be represented without live graph traversal in the PDP
4. governed receipt payloads can be minted from compiled decision state
5. quarantine or trust-gap outcomes are modeled explicitly if the workflow enables them
6. the implementation is snapshot-scoped and test-covered
7. no changes are required to the current synchronous PDP contract

## Open Questions

- Which snapshot metadata should mint `can` edges versus fact-derived permissions?
- How should deny edges be represented and prioritized relative to allow edges?
- Which twin relationships should be elevated into the authorization graph first?
- When should region-local Ray caches be introduced versus keeping a single in-process compiled snapshot?
- Which asset and custody concepts should be first-class in Phase 1 versus represented as resource specializations?
- Should governed receipt fragments be stored directly in PKG tables, graph projections, or both?
- What is the minimal deterministic representation of lineage proof for a governed receipt: graph path, Merkle proof, or a hybrid?
