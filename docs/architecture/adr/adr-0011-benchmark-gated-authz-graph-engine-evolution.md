# ADR 0011: Benchmark-Gated Authorization Graph Engine Evolution

- Status: Accepted
- Date: 2026-06-17
- Scope: Future evolution of SeedCore's compiled authorization graph engine. Does not change PDP authority, `ExecutionToken` minting, active PKG snapshot semantics, evidence closure, or RESULT_VERIFIER behavior.
- Related: [ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time](./adr-0001-pdp-hot-path.md), [ADR 0006: Split RESULT_VERIFIER Into a Dedicated Process on Measurable Triggers](./adr-0006-result-verifier-deployment-split-trigger.md), [Authorization PKG RFC](../../development/pkg_authz_graph_rfc.md), [Authz Graph Engine Evolution Plan](../../development/authz_graph_engine_evolution_plan.md), [PDP Authz Graph Staging Rollout](../../development/pdp_authz_graph_staging_rollout.md)

## Context

SeedCore already has an implemented authorization graph baseline:

- `src/seedcore/ops/pkg/authz_graph/ontology.py` defines typed nodes and edges.
- `src/seedcore/ops/pkg/authz_graph/projector.py` projects governed sources
  into an `AuthzGraphSnapshot`.
- `src/seedcore/ops/pkg/authz_graph/compiler.py` compiles that snapshot into a
  read-only in-memory index for PDP and transition checks.
- `src/seedcore/ops/pkg/authz_graph/manager.py` activates a compiled snapshot
  beside the active PKG snapshot.
- `scripts/host/verify_authz_graph_rfc_phases.sh` verifies the staged graph
  contract.

This baseline is ReBAC-shaped and already supports multi-hop authority paths,
permission constraints, deny and quarantine outcomes, active snapshot status,
and replay-visible decision metadata.

The next architectural question is not whether SeedCore should have a graph.
It does. The question is when, if ever, SeedCore should move beyond the current
Python dictionary, set, list, and `deque` compiled index into lower-level graph
systems techniques such as formal tuple import/export, precomputed closure
tables, CSR/CSC layouts, Ray-backed hot shards, or Rust/PyO3 kernels.

Those techniques may become valuable at larger relationship scale, but adopting
them prematurely would add complexity before SeedCore has measured that the
current compiled index is the limiting factor.

## Decision

SeedCore will evolve the compiled authorization graph engine through
benchmark-gated stages.

The current default remains:

- final PDP decision is synchronous, deterministic, stateless at decision time,
  and fail-closed over pinned inputs;
- the active compiled authorization graph is local or near-local to the PDP;
- PostgreSQL / PKG snapshots remain the governance source of truth;
- graph projection, compilation, cache warming, benchmarking, and enrichment
  remain outside the final authority decision;
- `ExecutionToken` issuance, evidence closure, RESULT_VERIFIER, and replay
  semantics are unchanged by graph-engine optimizations.

### Tuple Boundary

SeedCore may define an OpenFGA/Zanzibar-compatible tuple lifecycle for import,
export, diagnostics, fixtures, and future backend portability.

The tuple boundary is an interoperability and test boundary. It is not a
decision to replace SeedCore's PDP with OpenFGA, SpiceDB, Zanzibar, Ory Keto,
or any other external authorization service.

The initial tuple contract should map SeedCore's existing graph shape into:

```text
subject -> relation -> object
```

with SeedCore-specific metadata for:

- snapshot version and snapshot hash
- policy or provenance source
- operation
- effect
- constraints
- validity window
- replay and diagnostic references

### Benchmark Gate

SeedCore must add structural graph benchmarks before adopting lower-level graph
engine work.

The benchmark suite must measure at least:

- authority-path depth
- delegation fanout
- role and organization closure size
- number of assets and resources
- permission density per subject
- deny and break-glass path behavior
- transition-check latency
- compiled snapshot build time
- resident memory footprint where practical

The benchmark output must report P50, P95, and P99 latency for the decision
core and must keep served endpoint SLOs separate from in-process compiled-index
numbers.

### Promotion Rule

The following enhancements are not default roadmap mandates. They are
authorized only after benchmark or production-representative evidence shows
that the current compiled index is the bottleneck:

- precomputed transitive closure or path-flattened subject indexes;
- strongly connected component detection for malformed or cyclic delegation
  structures;
- Ray actor promotion from experimental cache surface to production hot-path
  dependency;
- CSR/CSC or other contiguous-memory graph layouts;
- Rust/PyO3 authorization-graph kernels;
- memory-mapped compiled graph artifacts;
- replacement or shadow comparison with an external ReBAC engine.

The first response to a measured slowdown should be the smallest reversible
optimization that preserves replayability and PDP semantics. A native graph
kernel is a later-stage option, not the first fix.

### External ReBAC Boundary

Zanzibar, SpiceDB, OpenFGA, and related systems are valid reference designs for
tuple vocabulary, causality, freshness, and relationship-scale testing.

They must not become the default SeedCore hot-path PDP unless a separate
architecture decision shows all of the following:

- relationship scale, delegation complexity, or tenant requirements exceed the
  current compiled local index;
- the external service can preserve SeedCore's fail-closed semantics,
  freshness requirements, replay evidence, and `ExecutionToken` boundary;
- outage, latency, and consistency behavior are acceptable under RCT and other
  high-consequence workflows;
- rollback and parity behavior are proven against SeedCore fixtures.

Until then, external ReBAC systems remain reference and diagnostic surfaces, not
authority dependencies.

## Rationale

- ADR 0001 already defines the final PDP decision as synchronous, stateless at
  decision time, deterministic, and fail-closed over pinned inputs. Graph-engine
  optimization must strengthen that boundary, not move it elsewhere.
- SeedCore's current compiled graph is correct in shape for the current wedge:
  restricted custody transfer, active PKG snapshots, execution tokens,
  evidence closure, and replayable verification.
- Low-level graph engines solve real problems, but they also introduce
  irreversible design pressure: new binary formats, native build systems,
  memory-safety boundaries, cache invalidation, and operator playbooks.
- A formal tuple boundary is valuable before an engine rewrite because it makes
  graph fixtures, interoperability, diagnostics, and future backend comparison
  explicit.
- Benchmarks give SeedCore permission to stay simple when Python is fast enough
  and permission to go lower-level when evidence justifies it.

## Consequences

- Phase 1 work should focus on tuple schema, fixture import/export, and
  structural graph benchmarks. Runtime semantics should remain unchanged.
- Current authz graph staging and hardening remain the near-term priority. This
  ADR does not replace `pdp_authz_graph_staging_rollout.md`.
- Ray cache, path-flattening, CSR/CSC, Rust/PyO3, and memory-mapped graph
  layouts become measured escalation options rather than speculative rewrites.
- Documentation and code should avoid claiming that SeedCore already has a CSR,
  Tarjan, Rust graph, or external ReBAC implementation unless such work has
  landed and passed verification.
- Any future native graph kernel must preserve deterministic replay:
  decisions must still bind to snapshot version, snapshot hash, request context,
  matched authority paths, reason codes, and evidence outputs.

## Alternatives Considered

- **Adopt OpenFGA or SpiceDB as the default hot-path PDP now.** Rejected because
  SeedCore's current wedge needs local compiled decisions, `ExecutionToken`
  semantics, evidence closure, and replay more than planet-scale sharing
  infrastructure.
- **Rewrite the compiled graph engine in Rust immediately.** Rejected because
  there is not yet benchmark evidence that the Python compiled index is the
  bottleneck.
- **Adopt CSR/CSC layouts immediately.** Rejected because compact matrix
  layouts are useful for scale but would complicate the graph compiler before
  tuple contracts and structural benchmarks exist.
- **Do nothing beyond the current compiler.** Rejected because formal tuple
  fixtures and depth/fanout benchmarks are low-risk and make future decisions
  evidence-based.
- **Move Ray authz cache into production by default.** Rejected because the
  current verified posture treats Ray cache as an experimental or staging
  surface until production hot-path routing and parity gates are proven.

## Adoption Triggers

SeedCore may advance beyond Phase 1 when at least one of these conditions is
observed in benchmark or production-representative load:

- P95 or P99 compiled-index decision latency exceeds the current promotion SLO
  under realistic authority-path depth and fanout.
- Compiled snapshot build time blocks active snapshot promotion or rollback
  readiness.
- Memory footprint of the compiled index prevents realistic tenant, facility,
  or asset scale in the target deployment profile.
- Ray cache parity is green, but local per-process compiled indexes become the
  dominant operational bottleneck.
- A regulated or enterprise deployment requires tuple import/export parity with
  OpenFGA, SpiceDB, Zanzibar-style, or equivalent ReBAC fixtures.

Trigger evidence should be recorded in the development plan before changing the
runtime architecture.

