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

## Motivation

The current PKG in SeedCore is primarily a policy snapshot and rule-execution system, not yet a low-latency graph-native authorization engine. The repository already contains:

- PKG snapshot lifecycle and evaluation in `src/seedcore/ops/pkg/`
- a synchronous `ActionIntent` authorization boundary in `src/seedcore/coordinator/core/governance.py`
- graph foundations in Neo4j and DGL loaders
- governed facts, tracking events, source registrations, and twin-oriented state

That makes SeedCore a good fit for a graph-backed authorization projection, but not for replacing the current PKG control plane.

## Design Goals

1. Preserve the synchronous, stateless PDP contract.
2. Keep control decisions deterministic and snapshot-scoped.
3. Make authorization relationships explicit and traversable.
4. Keep AI and GraphRAG outside the CONTROL hot path.
5. Allow event-driven projection updates without making the PDP depend on live database traversals.

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
- resources and zones
- networks
- source registrations and tracking evidence
- twins and delegated authorities
- snapshot-scoped permission edges

This graph is deterministic and event-driven. It is not the source of truth. It is a projection of authoritative state.

### 3. Compiled PDP Plane

For the synchronous hot path, the active authorization graph snapshot is compiled into an immutable in-memory index:

- adjacency sets
- role membership closure
- permission rules by principal or role
- zone and network constraints
- validity windows

The PDP reads this compiled index directly in-process.

## Why This Split

This split preserves the current SeedCore contract:

- the graph database is good at relationship storage and projection
- the compiled index is good at single-digit-millisecond reads
- PostgreSQL snapshots remain the governance root

Without this split, the system risks creating two competing sources of policy truth or pushing graph latency into the synchronous PDP.

## Phase Plan

### Phase 1: Ontology, Projection, Compilation

Add a new package:

- `src/seedcore/ops/pkg/authz_graph/`

Phase 1 contains:

- a strict ontology for nodes, edges, and graph snapshots
- deterministic projectors for current SeedCore models
- a compiler that produces a read-only permission index
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
- `resource`
- `zone`
- `network_segment`
- `registration`
- `tracking_event`
- `fact`
- `policy_snapshot`
- `twin`

### Edge Kinds

- `has_role`
- `delegated_to`
- `can`
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

## Projection Inputs

The first deterministic projection inputs should be:

- `ActionIntent`
- `Fact`
- `SourceRegistration`
- `TrackingEvent`

Supported fact predicates in Phase 1:

- `hasRole`
- `delegatedTo`
- `allowedOperation`
- `locatedInZone`

These predicates are sufficient to stand up a coherent first compiler and test path.

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

## Acceptance Criteria

Phase 1 is successful when:

1. authorization-relevant objects can be projected into a strict graph ontology
2. a compiled permission index can answer deterministic allow/deny checks
3. the implementation is snapshot-scoped and test-covered
4. no changes are required to the current synchronous PDP contract

## Open Questions

- Which snapshot metadata should mint `can` edges versus fact-derived permissions?
- How should deny edges be represented and prioritized relative to allow edges?
- Which twin relationships should be elevated into the authorization graph first?
- When should region-local Ray caches be introduced versus keeping a single in-process compiled snapshot?
