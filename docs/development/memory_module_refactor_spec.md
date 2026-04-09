# Memory Module Refactor Spec

Date: 2026-04-08
Status: In progress — **Phase 0–1 (contract freeze + backend alignment) are effectively done** in code; Phases 2–4 remain partially complete (runtime ownership, caller migration, legacy export cleanup).

## Purpose

This document defines how `src/seedcore/memory/` should be refactored to fit
the current SeedCore architecture, product boundary, and runtime contracts.

The current memory package still reflects an older "cognitive-first platform"
shape. The rest of the repository has narrowed around a different center:

- SeedCore is now a zero-trust execution and proof runtime for
  high-consequence actions.
- The PDP remains stateless and synchronous at decision time.
- Stateful systems exist around that boundary, but they must be explicit,
  typed, bounded, and fail-closed where they matter.
- The must-win 2026 wedge is Restricted Custody Transfer, not generalized
  autonomous cognition.

Memory should therefore become a well-bounded supporting subsystem for:

- short-lived agent/cognitive context
- scoped semantic retrieval for non-authoritative reasoning
- incident/salience logging where still useful
- operational telemetry about memory health

Memory should not continue to behave like an implicit "general substrate" that
quietly mixes cache, cognition, analytics, legacy energy loops, and
trust-critical state assumptions.

Memory is also not a threat-intelligence or defensive decision plane. In the
current SeedCore architecture, memory supports context, salience, and operator
legibility around the trust runtime; it does not replace the PDP, and it does
not redefine SeedCore as a cybersecurity detection system.

## Current Implementation Status

This spec started as a target-state refactor document. As of 2026-04-08, a
meaningful portion has now been implemented in the repo.

### Milestone checklist

Quick read for **“Core alignment & contract freeze”** (Phase 0–1) vs **later phases**.

| Item | State | Notes |
|------|--------|--------|
| `WorkingMemory` / `SemanticMemory` / `IncidentMemory` protocols + DTOs | **Done** | `memory/contracts.py` |
| HolonFabric ↔ pgvector / Neo4j contract alignment | **Done** (mock/contract lane) | Live DB: opt-in `SEEDCORE_LIVE_MEMORY_BACKENDS` |
| `MemoryRuntime` + `SemanticMemoryService` / `MwWorkingMemoryAdapter` | **Done** | Single construction path inside `memory/` |
| Promotion uses `HolonType.EPISODE` (not `TASK_EVENT`) | **Done** | `cognitive/memory_bridge.py` |
| Scoped retrieval via `SemanticMemoryService.search` | **Done** | `HolonFabricRetrieval` in `cognitive_core.py` (rename optional) |
| Tools / query paths use semantic facade | **Largely done** | `ToolManager`, `FindKnowledgeTool`, Ltm tools |
| One runtime owner per **process** + organism telemetry for state service | **Partial** | Default: state polls organism `/memory/telemetry`; Ray actors may still open local runtimes |
| No `HolonFabric` / raw backend use outside `memory/` | **Largely done** | `PgVectorStore` / `Neo4jGraph` constructed under `MemoryRuntime` only |
| Legacy package surface & `HolonClient` | **Done** | `HolonClient` removed; legacy via `memory.legacy` + deprecated `__getattr__` |
| Phase 2–4 (ownership everywhere, doc/README alignment, incident product decision) | **In progress** | See lists below |

### Completed in code

- caller-facing service contracts now exist in
  [src/seedcore/memory/contracts.py](/Users/ningli/project/seedcore/src/seedcore/memory/contracts.py)
- a shared runtime boundary now exists in
  [src/seedcore/memory/runtime.py](/Users/ningli/project/seedcore/src/seedcore/memory/runtime.py)
- working-memory and semantic-memory adapters now exist in
  [src/seedcore/memory/working_memory.py](/Users/ningli/project/seedcore/src/seedcore/memory/working_memory.py)
  and
  [src/seedcore/memory/semantic_memory.py](/Users/ningli/project/seedcore/src/seedcore/memory/semantic_memory.py)
- semantic backend contract mismatches in `HolonFabric` were repaired so
  upsert, delete, search, get-by-id, relationships, and stats now align with
  current backends
- cognitive promotion now maps task outcomes onto `HolonType.EPISODE` rather
  than the stale `TASK_EVENT` label
- tool-layer query and relationship paths now use normalized semantic-memory
  calls instead of reaching into graph neighbors directly
- additional tool and query entry points now accept or derive
  `SemanticMemoryService` explicitly instead of assuming direct
  `HolonFabric` access
- `CognitiveCore` retrieval now routes through `SemanticMemoryService` in
  `HolonFabricRetrieval`, including correct enum-to-scope-value normalization
- legacy exports were narrowed and compatibility/deprecation handling was added
  under `seedcore.memory.legacy`
- repo-root memory test execution was fixed via pytest bootstrap hygiene
- local runtime wiring for Neo4j was updated so host-local semantic memory is
  usable in `deploy/local`
- legacy flashbulb modules and routes are now documented in code as non-core
  compatibility surfaces

### Completed but still partial

- `MemoryRuntime` exists and is now used in several major callers
  (`OrganismCore`, `ToolManagerShard`, `BaseAgent`, `Organ`)
- lifecycle cleanup now closes runtime-owned resources in more places
- `MemoryAggregator` now reads semantic stats through the service/runtime
  boundary instead of constructing vector/graph backends directly
- `MemoryAggregator` now also supports injected runtime / semantic / working
  dependencies so ownership can remain with outer wiring instead of the
  aggregator itself
- `MemoryAggregator` incident polling now supports injected/runtime-provided
  `IncidentMemoryService` and emits contract-shaped status payloads
- `CognitiveCore` now has explicit shared semantic attachment
  (`attach_shared_semantic_memory`) and `CognitiveOrchestrator` can inject one
  shared `semantic_memory` facade into all core workers
- cross-layer tool integration tests now cover:
  - semantic holon query and relationship routes
  - query-tool registration for `knowledge.find`
  - `CollaborativeTaskTool` promotion via `semantic_memory.upsert_holon`

### Still required to complete the refactor

- finish removing direct `HolonFabric` use from callers that should instead
  depend on `SemanticMemory` or `WorkingMemory`
- reduce remaining duplicate memory-runtime construction paths so one clear
  bootstrap owner exists per process boundary
- add live-backend (non-mocked) integration coverage for semantic runtime paths
  where feasible in CI/host lanes
- clarify whether incident / flashbulb memory will be actively migrated or kept
  explicitly legacy-only
- finish migrating remaining compatibility references from `HolonFabric`
  terminology toward `SemanticMemory` terminology in logs/docstrings where that
  improves clarity

## Repo Findings

### 1. The exported memory surface is broader than the current architecture needs

Historically, `seedcore.memory.__init__` re-exported tiered-memory helpers,
`FlashbulbClient`, shard types, and similar at top level.

Status update:

- **mostly addressed in current code**
- **Primary `__all__`** now centers contracts, `MemoryRuntime`,
  `SemanticMemoryService`, `MwWorkingMemoryAdapter`, `HolonFabric` (still a
  construction primitive inside `memory/`), and incident types
- **`SharedMemorySystem` / `MemoryTier` / adaptive helpers**: `__getattr__` →
  `seedcore.memory.legacy` with `DeprecationWarning`
- **`SharedCacheShard` / `MwStoreShard` / `FlashbulbClient`**: no longer in
  `__all__`; accessible only via deprecated `__getattr__` → defining submodule
- remaining task: downstream callers should import from submodules explicitly;
  then tighten or remove lazy re-exports entirely

Relevant files:

- [src/seedcore/memory/__init__.py](/Users/ningli/project/seedcore/src/seedcore/memory/__init__.py)
- [src/seedcore/memory/system.py](/Users/ningli/project/seedcore/src/seedcore/memory/system.py)
- [README.md](/Users/ningli/project/seedcore/README.md)
- [docs/architecture/adr/adr-0001-pdp-hot-path.md](/Users/ningli/project/seedcore/docs/architecture/adr/adr-0001-pdp-hot-path.md)

### 2. The semantic-memory contract is stale at the API level

There are direct interface mismatches between the caller-facing fabric and the
actual backends:

- `HolonFabric.insert_holon()` calls `PgVectorStore.upsert(uuid=..., embedding=..., meta=...)`, but `PgVectorStore.upsert()` currently accepts a single `Holon` object.
- `HolonFabric.query_context()` calls `self.vec.search(query_vec=...)`, but `PgVectorStore.search()` expects `emb`.
- `HolonFabric.insert_holon()` passes extra properties into `Neo4jGraph.upsert_node()` and `upsert_edge()` that those methods do not accept.
- `HolonFabric.delete_holon()` assumes backend delete methods that do not exist today.
- `HolonFabric._hydrate_neighbors_scoped()` expects structured neighbor objects, while `Neo4jGraph.get_neighbors()` returns only UUID strings.

Relevant files:

- [src/seedcore/memory/holon_fabric.py](/Users/ningli/project/seedcore/src/seedcore/memory/holon_fabric.py)
- [src/seedcore/memory/backends/pgvector_backend.py](/Users/ningli/project/seedcore/src/seedcore/memory/backends/pgvector_backend.py)
- [src/seedcore/memory/backends/neo4j_graph.py](/Users/ningli/project/seedcore/src/seedcore/memory/backends/neo4j_graph.py)

Status update:

- addressed in current implementation
- `HolonFabric`, `PgVectorStore`, and `Neo4jGraph` now agree on the active
  caller contract closely enough for mocked semantic contract tests to pass
- relationship payloads are normalized, delete paths exist, stats exist, and
  caller-facing lookups no longer need raw graph neighbor shapes

### 3. Cognitive promotion types drift from the current holon model

Earlier cognitive promotion paths emitted `TASK_EVENT`, but `HolonType`
currently defines only:

- `FACT`
- `EPISODE`
- `CONCEPT`
- `POLICY`

That means the current bridge/promotion path is conceptually newer than the
data model it writes into.

Relevant files:

- [src/seedcore/cognitive/memory_bridge.py](/Users/ningli/project/seedcore/src/seedcore/cognitive/memory_bridge.py)
- [src/seedcore/models/holon.py](/Users/ningli/project/seedcore/src/seedcore/models/holon.py)

Status update:

- addressed
- promotion now maps task outcomes onto `HolonType.EPISODE`, which matches the
  current ontology better than `TASK_EVENT`

### 4. Multiple upstream callers construct memory infrastructure directly

Memory resources are created ad hoc in several places:

- agents
- organs
- tool-manager shards
- memory/state aggregation

Those callers repeat DSN/env/config logic and couple themselves directly to
`PgVectorStore`, `Neo4jGraph`, and `MwManager` construction. That makes memory
hard to evolve consistently and prevents a single configuration / ownership
boundary.

Relevant files:

- [src/seedcore/agents/base.py](/Users/ningli/project/seedcore/src/seedcore/agents/base.py)
- [src/seedcore/organs/organ.py](/Users/ningli/project/seedcore/src/seedcore/organs/organ.py)
- [src/seedcore/tools/manager_actor.py](/Users/ningli/project/seedcore/src/seedcore/tools/manager_actor.py)
- [src/seedcore/ops/state/memory_aggregator.py](/Users/ningli/project/seedcore/src/seedcore/ops/state/memory_aggregator.py)

Status update:

- partially addressed
- a shared `MemoryRuntime` now exists and several major callers use it
- remaining issue: there are still multiple lazy-init branches creating
  runtimes locally rather than receiving one already-built dependency from a
  single bootstrap owner

### 5. Some fallback paths are now explicitly stubs

Legacy `ContextBroker` construction in `CognitiveCore` used to call named Mw
search helpers; those **named stub methods have been removed**. The default
broker still uses **no-op** `text_fn` / `vec_fn` lambdas; real memory work is
expected via `CognitiveMemoryBridge` and scoped retrieval.

Relevant file:

- [src/seedcore/cognitive/cognitive_core.py](/Users/ningli/project/seedcore/src/seedcore/cognitive/cognitive_core.py)

Status update:

- **substantially addressed**
- scoped retrieval class `HolonFabricRetrieval` delegates to
  `SemanticMemoryService.search` (string scope labels normalized there)
- `CognitiveCore.attach_shared_semantic_memory(...)` and orchestrator-level
  `semantic_memory=` injection exist for shared facade wiring
- remaining task: rename or document `HolonFabricRetrieval` (name still says
  “fabric”) and trim remaining “broker” wording in comments where misleading

### 6. Memory telemetry is partly simulated instead of contract-shaped

Earlier versions reached through ad hoc internals or invented fields.

Relevant files:

- [src/seedcore/ops/state/memory_aggregator.py](/Users/ningli/project/seedcore/src/seedcore/ops/state/memory_aggregator.py)
- [src/seedcore/memory/telemetry.py](/Users/ningli/project/seedcore/src/seedcore/memory/telemetry.py)

Status update:

- **substantially improved**
- **Shared** `telemetry` helpers build **contract-shaped** `mw` / `mlt` / `mfb`
  dicts for both aggregator and organism
- **State service** (default): prefers **organism** `GET /memory/telemetry` /
  `rpc_memory_telemetry` via `OrganismServiceClient`; **local**
  `connect_default_memory_runtime` in the aggregator is **fallback** when remote
  fetch fails or `MEMORY_AGGREGATOR_ORGANISM_TELEMETRY=0`
- incident-memory polling supports injected/runtime `IncidentMemoryService`
- remaining task: product policy for incident telemetry when disabled; optional
  CI lane for live backends (`SEEDCORE_LIVE_MEMORY_BACKENDS`)

### 7. Flashbulb memory remains a legacy sidecar

Flashbulb storage still lives as a MySQL-centric incident subsystem behind
legacy routers. It is not integrated with the current verification /
forensic / trust-slice architecture.

Relevant files:

- [src/seedcore/memory/flashbulb_memory.py](/Users/ningli/project/seedcore/src/seedcore/memory/flashbulb_memory.py)
- [src/seedcore/api/routers/legacy/mfb_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/legacy/mfb_router.py)

Status update:

- still open architecturally
- the new incident-memory contract exists, and legacy flashbulb modules/routes
  are now marked in code as non-core compatibility surfaces
- remaining task: either migrate them onto `IncidentMemory` or leave them
  clearly quarantined as legacy-only

### 8. Tests cover the cache facade better than the semantic-memory contract

The current tests validate `MwManager` behavior well enough, but they do not
exercise the real `HolonFabric` <-> backend contract that is currently stale.
Also, the memory tests still assume a `src.*` import layout and did not run
from the repo root without explicitly setting `PYTHONPATH=.`

Command used:

```bash
PYTHONPATH=. pytest -q tests/test_memory_contracts.py tests/test_mw_manager.py
```

Observed result:

- 35 passed

This is useful, but it also means current green tests do not prove the semantic
memory stack is aligned.

Status update:

- improved
- semantic contract tests, bridge tests, and Neo4j relationship sanitization
  tests now exist
- repo-root pytest import hygiene has been fixed in test bootstrap
- dedicated runtime lifecycle and aggregator tests now exist
- regression coverage now includes semantic scope normalization in
  `HolonFabricRetrieval`
- caller integration tests now include query-tool registration and
  collaborative-task promotion paths
- remaining task: continue expanding live-backend integration depth without
  slowing default CI lanes

## Alignment Requirements

The refactor should align to these repo-level rules.

### A. Align with the root README

Memory is a supporting system around the trust runtime, not the product center.
The main product story is governed admissibility and replayable proof.

### B. Align with ADR 0001

Trust-critical decision-time context must not be sourced from ad hoc,
best-effort memory lookups. If memory influences governed flows, it must do so
through typed, freshness-aware, replay-visible context assembly owned by the
right source system.

### C. Align with current development docs

The active roadmap is about:

- verification
- hot-path operability
- replay and enforcement
- narrow external agent boundaries

Memory refactoring should reduce ambiguity and operational drift in support of
those goals, not reopen a broad "general autonomous cognition platform" track.

## Target Architecture

## 1. Define three caller-facing memory services

Refactor the package around three explicit service contracts.

### Working Memory

Purpose:

- short-lived cache
- recent episodic/chat fragments
- negative-cache / single-flight helpers
- telemetry snapshot for cache health

Public responsibilities:

- `get`
- `put`
- `delete`
- `append_episode`
- `get_recent_episode`
- `set_negative_cache`
- `check_negative_cache`
- `try_set_inflight`
- `clear_inflight`
- `stats_snapshot`

This is the evolution path for `MwManager`.

### Semantic Memory

Purpose:

- scoped semantic retrieval
- holon persistence
- relationship inspection
- long-term storage stats

Public responsibilities:

- `upsert_holon`
- `get_holon`
- `search`
- `list_relationships`
- `delete_holon`
- `stats_snapshot`

This should become the only caller-facing surface for Holon-backed long-term
memory. Callers should stop reaching through `fabric.graph` and `fabric.vec`.

### Incident Memory

Purpose:

- record high-salience incidents
- query incidents for analytics or operator review
- report stats

Public responsibilities:

- `record_incident`
- `get_incident`
- `list_incidents`
- `stats_snapshot`

This is the evolution path for flashbulb memory. It may remain optional, but it
should no longer sit in the package as a loosely related legacy branch.

## 2. Add one runtime/factory boundary

Introduce a shared memory runtime object, for example:

- `MemoryRuntime`
- or `MemoryProvider`

Responsibilities:

- own configured backend instances
- construct `WorkingMemory`, `SemanticMemory`, and `IncidentMemory`
- expose a single config boundary for PG/Neo4j/Redis/Ray/etc.
- handle lifecycle (`start`, `close`, `health`, `stats`)

This runtime should be created once in bootstrapping / organism wiring and
passed into callers. Agents, organs, shards, and aggregators should stop
rebuilding memory resources independently.

Implementation status:

- `MemoryRuntime` now exists and is in use
- not fully complete yet as a single ownership boundary, because some callers
  still instantiate runtimes lazily rather than receiving one from outer wiring

## 3. Narrow the semantic-memory data contract

The semantic layer should use one authoritative DTO family for:

- `HolonRecord`
- `HolonRelation`
- `SemanticSearchQuery`
- `SemanticSearchResult`
- `SemanticMemoryStats`

Rules:

- one normalized `HolonType` vocabulary
- one normalized relationship payload shape
- one normalized metadata envelope across vector and graph stores
- no raw backend records leaking into callers

### Type decision

`TASK_EVENT` should not remain an unmodeled ad hoc type.

Choose one of:

1. map task outcomes onto `HolonType.EPISODE`
2. formally extend `HolonType` with a stable event/task variant

Recommendation:

- use `EPISODE` as the canonical long-term event type unless there is a strong
  need to separate task outcomes from other episodic records at the ontology
  level

Implementation status:

- completed with `EPISODE`

## 4. Make trust boundaries explicit

The refactored memory module must document and enforce that:

- memory reads are advisory for cognition/tools unless explicitly promoted into
  a typed context envelope elsewhere
- governed PDP decisions do not call general-purpose memory services directly
- any hot-path-relevant context must arrive via owned, freshness-aware,
  replay-visible services outside this package

This is a doc and interface constraint, not only an implementation detail.

## 5. Move legacy energy-tier abstractions out of the default package surface

The following should no longer be part of the default `seedcore.memory`
surface:

- `SharedMemorySystem`
- `MemoryTier`
- `tiers.py`
- `adaptive_loop.py`
- `cost_vq.py` as a primary exported contract

Recommended treatment:

- move them under `seedcore.memory.legacy`
- or keep them in place temporarily but stop exporting them from
  `seedcore.memory.__init__`
- add deprecation notes where still imported

These may still be useful for experiments, archived telemetry, or research
notes, but they are not the current runtime contract.

Implementation status:

- largely completed
- legacy items now route through a compatibility/deprecation path under
  `seedcore.memory.legacy`
- remaining task: keep shrinking real caller dependence on those exports

## Proposed Package Shape

One possible target layout:

```text
src/seedcore/memory/
  __init__.py
  contracts.py
  runtime.py
  working_memory.py
  semantic_memory.py
  incident_memory.py
  types.py
  telemetry.py
  legacy/
    adaptive_loop.py
    cost_vq.py
    system.py
    tiers.py
  backends/
    pgvector_store.py
    neo4j_graph.py
    ray_cache.py
    incident_store.py
```

The exact filenames can differ. The important rule is:

- callers import contracts/services
- not raw backend adapters

## Caller Migration Plan

## 1. Cognitive layer

`CognitiveMemoryBridge` should depend on:

- `WorkingMemory`
- `SemanticMemory`

It should not require direct knowledge of `HolonFabric`, `PgVectorStore`, or
`Neo4jGraph`.

`CognitiveCore` should:

- receive a configured memory runtime from the outside
- stop creating Mw instances per agent by itself where possible
- delete deprecated `_mw_text_search` / `_mw_vector_search` fallback paths after
  migration

Implementation status:

- `CognitiveMemoryBridge` already uses `WorkingMemory` and `SemanticMemory`
- `HolonFabricRetrieval` in `CognitiveCore` now uses `SemanticMemoryService`
  instead of raw fabric search and correctly normalizes scope enum values
- remaining task: complete outer-wiring cleanup so cognitive paths do not rely
  on compatibility-era fallback composition longer than needed

## 2. Tool layer

`ToolManager`, `memory_tools.py`, and query tools should use the new contracts:

- semantic query by ID should call `SemanticMemory.get_holon()`
- relationship lookup should call `SemanticMemory.list_relationships()`
- search should call `SemanticMemory.search()`

Tools should stop reaching into `holon_fabric.graph.get_neighbors(...)`
directly, because that bypasses the caller contract and backend normalization.

Implementation status:

- substantially completed
- `ToolManager`, `memory_tools.py`, `FindKnowledgeTool`,
  `CollaborativeTaskTool`, and query-tool registration now prefer
  `SemanticMemoryService`
- remaining task: continue reducing compatibility-first constructor shapes
  where callers no longer need `HolonFabric` fallback support

## 3. Agent and organ wiring

`BaseAgent`, `Organ`, `OrganismCore`, and `ToolManagerShard` should receive
memory runtime dependencies from one place rather than locally rebuilding
backends.

That gives us:

- one config source
- one lifecycle owner
- fewer duplicated lazy-init branches
- less drift between local and shard execution paths

## 4. State service / memory aggregation

`MemoryAggregator` should use `stats_snapshot()` methods from the new service
contracts.

It should not:

- inspect backend internals directly
- guess memory shape from partial telemetry
- silently substitute simulated values except in an explicitly disabled or
  unavailable mode

Recommended status shape:

- `enabled`
- `degraded`
- `unavailable`

with a reason field, instead of blending real and simulated stats into one
opaque payload.

Implementation status:

- improved beyond the original slice
- `MemoryAggregator` now supports injected `semantic_memory`,
  `memory_runtime`, and `mw_manager` dependencies and avoids closing injected
  owners
- tests now cover injected semantic polling and lazy-runtime close semantics

## 5. Incident / flashbulb callers

Legacy incident routes and tuning-service hooks should migrate onto
`IncidentMemory`.

If the incident subsystem is not part of the current wedge, it should be kept
behind a compatibility namespace and marked clearly as non-core.

## Compatibility Rules

The migration should preserve a bounded compatibility window.

### Keep temporarily

- `MwManager` import path
- `HolonFabric` import path
- current tool names such as `memory.mw.*` and `memory.holon.*`

### Add immediately

- deprecation warnings for legacy-only exports
- compatibility adapters so old callers route through the new services
- docstrings that clearly mark advisory vs authoritative usage

### Remove later

- direct backend access from tools and callers
- default exports for legacy tiered-memory utilities
- stub search helpers in `CognitiveCore`
- duplicate construction paths for memory resources

## Implementation Phases

## Phase 0: Contract freeze and test expansion

Deliverables:

- define `WorkingMemory`, `SemanticMemory`, and `IncidentMemory` protocols
- add DTOs for stats and semantic results
- add failing/targeted tests that capture the current backend mismatch cases
- fix test import hygiene so memory tests run from normal repo-root pytest flows

Acceptance:

- tests exist for semantic upsert/search/delete/relationship flows
- tests no longer depend on `src.*` import assumptions

Status:

- completed

## Phase 1: Repair semantic-memory backend contract

Deliverables:

- make `HolonFabric` and backend methods agree on signatures
- add missing delete/stats/relationship APIs
- normalize neighbor/relationship payloads
- resolve the `TASK_EVENT` vs `HolonType` mismatch

Acceptance:

- semantic integration tests pass against mocked backends
- caller-facing API no longer reaches through backend-specific method names

Status:

- completed for the current mocked/contract slice
- note: live backend integration coverage is still thinner than contract/mock
  coverage

## Phase 2: Introduce shared memory runtime

Deliverables:

- create `MemoryRuntime` / `MemoryProvider`
- wire it into organism/bootstrap/service initialization
- stop ad hoc PG/Neo4j/Mw construction in agents, organs, and tool shards

Acceptance:

- one config path for semantic/working/incident memory
- lifecycle close/health is explicit and testable

Status:

- partially completed
- runtime exists, is wired into key callers, and lifecycle close is improved
- organism / organ / agent local ToolManager and Ray tool shards now prefer
  ``semantic_memory=runtime.semantic`` when a ``MemoryRuntime`` is already held
- not yet complete as a single config/ownership path across every **Ray actor**
  boundary (organ / agent / shard may still open their own runtime when they
  need local semantic tools)
- state-service **default** path now polls organism memory telemetry; lazy local
  connect remains **fallback** only

## Phase 3: Migrate callers

Deliverables:

- migrate cognitive layer
- migrate tool layer
- migrate aggregator/state layer
- add compatibility wrappers for remaining old imports

Acceptance:

- no caller outside `memory/` reaches into `fabric.vec` / `fabric.graph`
- no caller outside `memory/` constructs raw memory backends directly

Status:

- partially completed
- tool query paths and aggregator paths are materially improved
- cognitive retrieval and query-tool registration are also more aligned with
  the semantic facade now
- remaining work includes finishing caller migration toward
  `SemanticMemory` / `WorkingMemory` service dependencies instead of
  `HolonFabric` compatibility use

## Phase 4: Retire legacy exports

Deliverables:

- slim `seedcore.memory.__init__`
- move old adaptive/tier utilities to `memory.legacy`
- mark flashbulb paths clearly as optional or legacy if still retained

Acceptance:

- package exports match the intended architecture
- docs stop presenting memory as a parallel architectural center

Status:

- partially completed
- package exports have been narrowed, but final caller/document cleanup is still
  needed

## Verification Plan

Required test layers:

1. Unit tests for `WorkingMemory` key semantics, TTL behavior, episodes, and telemetry.
2. Contract tests for `SemanticMemory` DTO normalization.
3. Integration tests for pgvector + Neo4j adapters behind the semantic-memory service.
4. Caller integration tests for:
   - `CognitiveMemoryBridge`
   - `ToolManager`
   - `FindKnowledgeTool`
   - `MemoryAggregator`
5. Lifecycle tests for shared runtime creation and shutdown.

Recommended commands after refactor:

```bash
pytest -q tests/test_memory_contracts.py
pytest -q tests/test_mw_manager.py
pytest -q tests/test_pgvector_backend.py
pytest -q tests/test_memory_aggregator.py
pytest -q tests/test_cognitive_memory_bridge.py
```

Current validated commands:

```bash
pytest -q tests/test_mw_manager.py tests/test_memory_contracts.py tests/test_cognitive_memory_bridge.py tests/test_semantic_memory_service.py tests/test_neo4j_graph_backend.py
```

Additional validated commands from the latest review slice:

```bash
pytest -q tests/test_memory_contracts.py tests/test_memory_aggregator.py tests/test_memory_runtime_lifecycle.py
pytest -q tests/test_tools.py tests/test_cognitive_memory_bridge.py tests/test_semantic_memory_service.py
pytest -q tests/test_memory_tool_integration.py
```

## Documentation Updates Required

After implementation, update:

- [README.md](/Users/ningli/project/seedcore/README.md)
- [docs/architecture/overview/architecture.md](/Users/ningli/project/seedcore/docs/architecture/overview/architecture.md)
- [src/seedcore/__init__.py](/Users/ningli/project/seedcore/src/seedcore/__init__.py)

The goal is to make the docs say the same thing the code now means:

- memory is a bounded supporting subsystem
- not a second product center
- not an implicit authority source for governed decisions

Current note:

- parts of this doc alignment are already underway in package/module docstrings
- README and architecture docs should still be reviewed after the remaining
  caller migration work lands

## Recommended First Slice

If we want the highest-value first move with the least churn, do this first:

1. Freeze new memory service contracts and DTOs.
2. Repair `HolonFabric` / backend signature mismatches.
3. Introduce a shared runtime factory.
4. Migrate `ToolManager` and `CognitiveMemoryBridge` to the new contracts.
5. Slim `seedcore.memory.__init__` and move legacy exports behind deprecation.

That sequence fixes the real breakpoints first while keeping the rollout
incremental.

## Remaining Recommended Next Slice

Focus on **closing real gaps** (not re-litigating completed contract work):

### 1. Keep reducing compatibility-first constructor shapes

**Direction:** new and internal code should take **`semantic_memory`** (or a
runtime-owned `MemoryRuntime`) first; **`holon_fabric`** remains a narrow escape
hatch for legacy callers and for deriving `SemanticMemoryService(fabric)` at the
boundary.

Concrete follow-ups:

- Prefer `ToolManager(..., semantic_memory=runtime.semantic)` everywhere the
  process already holds a `MemoryRuntime` (organism, organ actor, agent local
  manager, tool shards).
- query-tool constructors now require semantic-memory facades in new call paths;
  continue shrinking compatibility matrices in legacy entry points.
- `CognitiveCore` now accepts semantic at construction and via
  `attach_shared_semantic_memory`; continue removing remaining fallback wording
  and references that imply direct fabric access is preferred.

### 2. Outer-wiring and ownership (cognitive + runtime)

**Final ownership policy**

- **One `MemoryRuntime` owner per process boundary.**
- A `MemoryRuntime` object is never treated as cross-process shareable state.
- The process that opens PG/Neo4j pools owns `close()` for those pools.

**By process role**

- **Organism process:** owns the primary read/write `MemoryRuntime` for
  semantic storage in the organism runtime.
- **Agent / organ / tool-shard processes:** may own a local `MemoryRuntime`
  only when they execute semantic reads/writes in that process and cannot rely
  on a colocated outer owner. When already handed a runtime-owned
  `semantic_memory`, they must not reconnect storage themselves.
- **State service:** is **telemetry-only** and must not be a default storage
  owner. Its preferred source is a **remote memory-stats boundary** exposed by
  the organism service (or a dedicated stats proxy), not direct PG/Neo4j
  bootstrap.

**State service policy**

- `state_service` should poll **contract-shaped memory stats over RPC/HTTP**
  from the organism service.
- `MemoryAggregator(..., memory_runtime=...)` injection remains valid only for
  colocated/test deployments where the state layer runs in-process.
- local `connect_default_memory_runtime()` inside `MemoryAggregator` becomes an
  **explicit fallback/dev mode**, not the default production path.

**Recommended implementation shape**

1. add an organism-facing memory telemetry endpoint / RPC that returns the same
   `mw` / `mlt` / `mfb` payload families state service already consumes
2. teach `state_service` startup to prefer that remote source when an organism
   handle is available
3. keep lazy local runtime connect behind an explicit env flag for local/dev
   survival only
4. once remote stats polling is stable, treat duplicate state-service storage
   bootstrap as non-default and document it as fallback-only

**Target state:**

- **Organism / agents / shards:** one `MemoryRuntime` per process (or per shard)
  that owns `close()`; `ToolManager` and MW binding consume **`runtime.semantic`**
  and **`runtime.working`** rather than reconstructing parallel facades.
- **Cognitive service:** when the cognitive driver is **colocated** with
  semantic storage, inject the **same** `SemanticMemoryService` (or fabric via
  orchestrator) into `CognitiveCore` so per-agent bridges do not construct
  unnecessary extra wrappers. This is now supported by orchestrator-level
  shared semantic injection. When cognitive is **remote-only**,
  document that memory bridge / retrieval may be degraded unless an RPC or
  shared client supplies semantic access.
- **State service:** prefer organism-owned remote stats polling. Only use
  **`MemoryAggregator(..., memory_runtime=...)`** / local runtime wiring in
  colocated or test deployments, and keep lazy connect as explicit fallback.

### 3. Already narrowed or documented elsewhere

- **`HolonClient`**: **removed from the repo**; `SemanticMemoryService` /
  `CognitiveMemoryBridge` promotion paths are canonical for semantic writes.
- Flashbulb / legacy MFB routes: marked non-core; migrate to `IncidentMemory` only
  if product needs unified incident telemetry.

**Preferred host-local integration runner for this slice:**

```bash
bash scripts/host/verify_memory_refactor_integration.sh
```

Optional extensions:

```bash
# include live semantic backend integration when PgVector/Neo4j are available
bash scripts/host/verify_memory_refactor_integration.sh --live-backend

# include live runtime endpoint checks for organism/ops memory surfaces
bash scripts/host/verify_memory_refactor_integration.sh --runtime

# run both optional layers
bash scripts/host/verify_memory_refactor_integration.sh --all
```

The script currently bundles:

- contract and adapter tests
- memory aggregator and runtime lifecycle tests
- cognitive memory bridge / shared semantic wiring tests
- semantic-memory backend contract tests
- host-local runtime default regression checks
- cognitive package import safety checks for optional DSPy environments

**Raw pytest equivalent for the core slice:**

```bash
pytest -q tests/test_memory_tool_integration.py tests/test_memory_contracts.py \
  tests/test_memory_aggregator.py tests/test_memory_runtime_lifecycle.py \
  tests/test_cognitive_memory_bridge.py tests/test_cognitive_memory_wiring.py \
  tests/test_memory_telemetry.py tests/test_semantic_memory_service.py \
  tests/test_neo4j_graph_backend.py tests/test_mw_manager.py \
  tests/test_host_local_runtime_defaults.py tests/test_cognitive_package_imports.py
```

---

## Implementation truth, Ray hardening, and deferred research (2026-04-09)

This checklist tracks **truth-alignment** and **shortest-path hardening** versus **research-only** items. It complements the refactor milestones above; it does not replace them.

### Implement / in progress (this repo)

| Item | Status | Notes |
|------|--------|--------|
| ML service docstring matches exposed HTTP API | **Done** | `ml_service.py` no longer claims `/hgnn/*`; graph embeddings stay under `seedcore.graph` / GraphDispatcher actors. |
| Rename misleading `h_hgnn` system vector | **Done** | `SystemState.h_agent_centroid` + metrics key `h_agent_centroid`; payloads now use one canonical field name. |
| Escalation path label vs ML | **Done** | `DecisionKind.ESCALATED` now serializes as `"escalated"`; comments clarify it is not an ML HTTP surface. |
| `MemoryRuntime.health()` includes graph reachability | **Done** | Neo4j `ping()` + payload field `graph`. |
| pgvector search telemetry | **Done** | DEBUG log: `k`, filter use, row count, latency. |
| Live semantic integration | **Extended** | `tests/test_semantic_memory_live_integration.py`: health asserts `graph`; optional `test_live_semantic_search_executes_pgvector_path` when `SEEDCORE_LIVE_MEMORY_BACKENDS=1`. |
| Ray object spilling (K8s) | **Done** | `deploy/k8s/rayservice.yaml`: `RAY_object_spilling_config` + `emptyDir` at `/tmp/ray/spill` on head and workers; `docker/env.example` documents the same pattern. |
| Idempotent graph embedder actors | **Done** | `GraphEmbedder` / `NimRetrievalEmbedder`: `max_restarts=3`. |
| Single `MemoryRuntime` owner per process | **In progress** | See §2.2 / checklist above; finish removing duplicate construction paths. |

### Manuscript / narrative — defer or delete unless built

| Item | Action |
|------|--------|
| NVSA / stochastic in-memory factorization | **Defer** — not in codebase; frame as future work only. |
| Dynamic spectral hypergraph clustering for escalation | **Defer** — not implemented; coordinator uses surprise/drift/PKG, not spectral grouping. |
| Placement-group scaling from “surprise sentinel” | **Defer** — no such control loop; document Ray Serve autoscaling / KubeRay instead. |
| “Millions of micro-agents / general cognitive substrate” | **Defer / delete** — conflicts with current product wedge (e.g. RCT-focused boundary in this spec). |

### References (ops + retrieval)

- [RayService HA](https://docs.ray.io/en/latest/cluster/kubernetes/user-guides/rayservice-high-availability.html)
- [Ray Serve fault tolerance](https://docs.ray.io/en/latest/serve/production-guide/fault-tolerance.html)
- [Ray object spilling](https://docs.ray.io/en/latest/ray-core/objects/object-spilling.html)
- [Ray actor fault tolerance](https://docs.ray.io/en/latest/ray-core/fault_tolerance/actors.html)
- [Neo4j vector indexes](https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes)
- [pgvector](https://github.com/pgvector/pgvector)
