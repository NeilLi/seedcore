# Authz Graph Engine Evolution Plan

Date: 2026-06-17
Status: Future-performance plan, gated by [ADR 0011](../architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md)

## Purpose

This plan turns SeedCore's authorization graph hardening path into a measured
sequence.

SeedCore already has the correct authority shape for the current RCT wedge:
the PDP evaluates pinned inputs, the compiled authz graph supplies relationship
and constraint context, `ExecutionToken` permits only a bounded attempt, and
evidence / verifier closure decides whether execution settled.

This plan is about future engine maturity. It must not be used to bypass PDP
evaluation, skip `ExecutionToken` checks, move authority into Ray, or replace
replay-visible evidence with a faster graph lookup.

## Current Baseline

The current implementation is a logical compiled ReBAC engine over standard
Python data structures:

- typed graph ontology:
  [`src/seedcore/ops/pkg/authz_graph/ontology.py`](../../src/seedcore/ops/pkg/authz_graph/ontology.py)
- deterministic projection:
  [`src/seedcore/ops/pkg/authz_graph/projector.py`](../../src/seedcore/ops/pkg/authz_graph/projector.py)
- compiled authorization index and transition checks:
  [`src/seedcore/ops/pkg/authz_graph/compiler.py`](../../src/seedcore/ops/pkg/authz_graph/compiler.py)
- active compiled snapshot manager:
  [`src/seedcore/ops/pkg/authz_graph/manager.py`](../../src/seedcore/ops/pkg/authz_graph/manager.py)
- optional Ray cache surface:
  [`src/seedcore/ops/pkg/authz_graph/ray_cache.py`](../../src/seedcore/ops/pkg/authz_graph/ray_cache.py)
- staged verification:
  [`scripts/host/verify_authz_graph_rfc_phases.sh`](../../scripts/host/verify_authz_graph_rfc_phases.sh)

The baseline is good enough to keep hardening. It is not yet a CSR/CSC graph
engine, a Rust/PyO3 graph kernel, or an external OpenFGA / SpiceDB deployment.

## Non-Goals

This plan does not:

- replace the PDP with an external graph service;
- make Ray an authority source;
- make tuple import/export sufficient to mint execution authority;
- require Rust, CSR, CSC, `mmap`, or `petgraph` before benchmarks justify them;
- change the Agent Action Gateway contract;
- change `ExecutionToken` semantics;
- change RESULT_VERIFIER or evidence closure;
- weaken fail-closed behavior for stale, missing, or unverifiable context.

## Phase 1: Tuple Contract And Structural Benchmarks

Phase 1 is the next correct enhancement. It is low risk because it defines
interfaces and measurements before rewriting the engine.

### 1. Formal Tuple Lifecycle

Define a SeedCore authz tuple contract that can be exported from and imported
into the existing `AuthzGraphSnapshot` shape.

Minimum tuple fields:

- `tuple_id`
- `subject_ref`
- `relation`
- `object_ref`
- `operation`
- `effect`
- `constraints`
- `valid_from`
- `valid_to`
- `snapshot_version`
- `snapshot_hash`
- `provenance_ref`
- `policy_ref`

The tuple shape should be compatible with OpenFGA/Zanzibar-style diagnostics,
but must preserve SeedCore-specific authority metadata.

Candidate surfaces:

```text
GET  /api/v1/pkg/authz-graph/tuples
POST /api/v1/pkg/authz-graph/tuples/validate
POST /api/v1/pkg/authz-graph/tuples/compile-dry-run
```

The first implementation can stay internal or test-only if the API surface is
not yet needed. The important contract is the typed tuple schema and fixture
round trip.

### 2. Deep-Path Benchmark Harness

Add a structural graph benchmark that measures the current compiled index under
large but realistic relationship shapes.

Suggested command shape:

```bash
python scripts/host/benchmark_authz_graph_engine.py --profile rct_enterprise
```

The benchmark should generate synthetic but deterministic fixtures for:

- 5, 10, 20, and 50 authority-path depth;
- role and organization fanout;
- multi-agent delegation chains;
- facility -> zone -> asset resource paths;
- 1k, 10k, and 100k resource / asset references where practical;
- allow, deny, break-glass, and quarantine transition checks;
- snapshot compile time and decision time separately.

Required output:

- graph profile name;
- node and edge counts;
- subject count;
- permission count;
- max authority depth;
- compile time;
- decision P50, P95, P99;
- memory footprint where measurable;
- pass / warn / fail against configured SLOs.

Keep benchmark fixtures deterministic so they can be checked into CI or run
locally without live services.

### Phase 1 Acceptance

Phase 1 is complete when:

- tuple schema has focused tests;
- tuple export/import round trip preserves existing graph semantics;
- benchmark harness reports P50/P95/P99 for the current compiler;
- at least one fixture exercises deep authority paths and high asset count;
- benchmark results are documented before any engine rewrite is proposed.

## Phase 2: Measured Systems Hardening

Phase 2 starts only if Phase 1 shows measurable pressure.

Candidate work:

- precompute subject closure for common principals;
- add cycle detection and explicit malformed-delegation diagnostics;
- add path-flattened indexes for hot authority paths;
- promote Ray cache verification from experimental host check into a staging or
  CI gate;
- require parity between local compiled index and Ray actor decisions before
  any hot-path routing change.

Phase 2 must preserve:

- snapshot hash binding;
- authority path explanations;
- deny / quarantine reason codes;
- rollback to local compiled index;
- deterministic replay metadata.

### Phase 2 Triggers

Enter Phase 2 when at least one is true:

- P95 or P99 decision time misses the configured hot-path promotion target in a
  realistic benchmark profile;
- subject traversal depth or fanout dominates decision time;
- compiled snapshot activation becomes too slow for rollback or promotion;
- Ray cache parity is green and local index duplication becomes the measured
  bottleneck.

## Phase 3: Native Graph Kernel Candidate

Phase 3 is a later system-kernel track. It should not start until Phase 2
evidence shows Python object layout, pointer chasing, or memory footprint is the
dominant bottleneck.

Candidate work:

- CSR or CSC representation for authority adjacency;
- compact integer id mapping for subject, relation, object, operation, and
  resource refs;
- Rust/PyO3 extension for decision-core evaluation;
- memory-mapped compiled graph artifacts;
- comparison harness against the Python compiler;
- crash-safe fallback to the Python compiled index.

The native kernel must be treated like other trust-critical compiled surfaces:
typed input, strict schema, parity tests, replay binding, and fail-closed
fallbacks are required before enforce mode.

### Phase 3 Triggers

Enter Phase 3 only when at least one is true:

- realistic enterprise graph scale cannot fit the target memory profile with
  the Python compiled index;
- Python compiled-index P99 remains above target after Phase 2;
- snapshot compile or activation time prevents operational rollback readiness;
- a design partner requires million-scale relationship checks under measured
  latency targets that Python cannot meet.

## Verification Spine

Keep these existing gates in the loop:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_authz_engine_parity.sh
pytest tests/test_pkg_authz_graph.py tests/test_pkg_authz_graph_manager.py tests/test_authz_parity_service.py -q
```

When Phase 1 lands, add the tuple and benchmark tests to the smallest relevant
verification slice rather than making every local run execute the largest graph
profile.

## Documentation Rules

- Do not claim CSR/CSC, Tarjan/path flattening, Rust graph kernels, or external
  ReBAC engines are implemented until code and tests exist.
- Keep ADR 0011 as the durable rule: benchmark first, optimize second.
- Keep this plan as the schedule and acceptance surface.
- Keep `pdp_authz_graph_staging_rollout.md` as the operational rollout guide for
  the current active graph behavior.
- Keep ADR 0001 as the authority boundary.

