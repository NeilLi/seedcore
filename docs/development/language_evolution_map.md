# SeedCore Language Evolution Map

## Purpose

This note places the SeedCore language evolution plan next to the active
roadmap and contract-freeze work.

The goal is to stay ambitious without falling into a rewrite trap.

The governing principle is:

> Keep discovery flexible, make authority strict, and make trust visible.

That implies a three-zone stack:

- Python is the intelligence and orchestration plane.
- Rust is the control and proof kernel.
- TypeScript is the trust and product surface.

This is not a repo-wide rewrite plan. It is a boundary-tightening plan that
follows SeedCore's existing execution spine.

## Architecture Rule

The language split should reinforce one runtime truth:

> AI can advise, but governance decides.

In practical terms:

- Python should continue to host fast-changing, AI-heavy, and exploratory
  logic.
- Rust should gradually absorb deterministic, authority-bearing semantics.
- TypeScript should render authoritative state legibly without becoming the
  authority itself.

## SeedCore Module Map By Language

### Keep In Python For Now

These areas are still evolving quickly and should remain in Python in the near
term.

#### Agent and orchestration layer

Current landing zones:

- `src/seedcore/agents/*`
- `src/seedcore/tools/*`
- `src/seedcore/control/*`
- `src/seedcore/coordinator/core/advisory.py`
- `src/seedcore/coordinator/core/cognitive_reasoning.py`
- `src/seedcore/coordinator/core/plan.py`
- `src/seedcore/coordinator/core/routing.py`

Why:

- the logic is still fluid
- AI and planning are central
- this is not the final trust boundary

#### Advisory intelligence and enrichment

Current landing zones:

- `src/seedcore/coordinator/core/enrichment.py`
- `src/seedcore/ops/pkg/authz_graph/projector.py`
- `src/seedcore/ops/pkg/authz_graph/ontology.py`
- `src/seedcore/ops/source_registration/*`
- `src/seedcore/graph/*`
- `src/seedcore/ml/*`

Why:

- enrichment is not the synchronous decision kernel
- ontology and scenario work still need iteration speed
- simulations and intelligence may advise without owning final authority

#### Internal analytics, replay prep, and forensic tooling

Current landing zones:

- `src/seedcore/services/replay_service.py`
- `src/seedcore/monitoring/*`
- `src/seedcore/ops/fact/*`
- internal evaluation, analysis, and backfill scripts

Why:

- flexibility matters more than compile-time rigidity here
- these workflows prepare evidence and insight, but should not define final
  policy truth

### Move Toward Rust First

The first Rust moves should follow authority order, not repo convenience.

Recommended workspace:

- `rust/crates/seedcore-kernel-types`
- `rust/crates/seedcore-proof-core`
- `rust/crates/seedcore-approval-core`
- `rust/crates/seedcore-policy-core`
- `rust/crates/seedcore-token-core`
- `rust/crates/seedcore-verify`
- `rust/crates/seedcore-kernel-testkit`
- `rust/fixtures/`

Recommended migration order:

1. `seedcore-proof-core`
2. `seedcore-approval-core`
3. `seedcore-policy-core`
4. `seedcore-token-core`
5. `seedcore-verify`

Rationale:

- proof and receipt integrity are the most bounded authority surface
- approval lifecycle is the next strict state machine
- policy evaluation should move only after the truth table and explanation
  payload are frozen
- token enforcement should converge with the same strict kernel semantics
- verifier tooling should be externally shareable and offline-friendly

The detailed service/CLI-first Rust workspace proposal now lives in
[rust_workspace_proposal.md](/Users/ningli/project/seedcore/docs/development/rust_workspace_proposal.md).

### Move Toward TypeScript

TypeScript should be introduced where trust must become visible and product
legible.

Current bootstrap implemented in-repo:

- `ts/packages/contracts`
- `ts/apps/verification-console`
- `ts/services/verification-api`
- `ts/apps/proof-surface`
- `seedcore-verify summarize-transfer --dir rust/fixtures/transfers/allow_case`

#### 1. Verification or proof surface

Recommended first app:

- `web/proof-surface`
  or
- `web/verification-console`

Responsibilities:

- render business-readable proof state
- show receipt lineage
- show approval state
- show transfer and custody state
- expose replay-ready trust artifacts

Why first:

- this is the most product-defining surface in the current roadmap

#### 2. Operator workflow console

Recommended app:

- `web/operator-console`

Responsibilities:

- intake workflow views
- quarantine and review workflow views
- approval interaction
- transfer review state
- anomaly and trust-gap visibility

Why:

- it turns backend trust into operator action without forcing TS to own
  runtime truth

#### 3. Integration API facade or BFF

Recommended service:

- `ts/services/verification-api`
  or
- `ts/services/trust-api`

Responsibilities:

- serve typed APIs to the UI
- map runtime artifacts into product views
- provide stable front-door contracts
- avoid leaking internal runtime complexity directly into UI code

#### 4. Shared contract package

Recommended package:

- `ts/packages/contracts`
  or
- `ts/packages/trust-types`

Responsibilities:

- generated TS types
- schema exports
- client helpers
- validation wrappers

## Recommended Migration Order

Migration should proceed in authority order.

### Phase 0: Freeze Contracts First

Before moving logic across languages, freeze the artifacts that define the
trust boundary:

- `ActionIntent`
- `TransferApprovalEnvelope`
- `PolicyDecision`
- `ExecutionToken`
- `PolicyReceipt`
- `TransitionReceipt`
- `EvidenceBundle`
- minimum explanation payload
- runtime disposition truth table

This is the anti-drift step. Without it, a multi-language stack will amplify
contract ambiguity.

See:

- `docs/development/killer_demo_execution_spine.md`
- `docs/development/next_killer_demo_contract_freeze.md`

### Phase 1: Rust Proof Kernel

Build `seedcore-proof-core` first and integrate it initially through a narrow
service or sidecar boundary rather than forcing FFI from day one.

Expected deliverables:

- canonical receipt generation
- signature verification
- deterministic hash compatibility tests
- a basic verifier CLI

Status as of March 25, 2026:

- completed for baseline scope:
  - `seedcore-proof-core` canonicalization, hashing, signing, signature
    verification, and replay-chain verification
  - deterministic fixture and golden-path coverage in the Rust workspace
  - `seedcore-verify` CLI, including `verify-transfer` and
    `summarize-transfer`
- remaining hardening can continue in follow-on phases (for example, broader
  external verifier packaging and page/API projection maturity)

### Phase 2: TypeScript Proof Surface

Build the first workflow-specific proof surface once proof artifacts are stable.

Expected deliverables:

- one asset proof page
- one transfer proof page
- business-readable status mapping from the runtime truth table

Status as of March 25, 2026:

- completed for baseline scope:
  - `ts/packages/contracts` provides strict TS contract parsing for verifier
    outputs
  - `ts/services/verification-api` provides a typed proof facade over
    `seedcore-verify`
  - `ts/apps/proof-surface` provides:
    - one transfer proof page
    - one asset proof page
    - business-readable status mapping from runtime disposition
- remaining maturity work can continue in later phases (for example richer
  operator workflow depth and broader product UX hardening)

### Phase 3: Rust Approval Engine

Move dual-approval lifecycle semantics into Rust after the contract freeze is
real, not aspirational.

Expected deliverables:

- deterministic approval transitions
- append-only approval history logic
- invalid-transition test matrix

Status as of March 26, 2026:

- completed for baseline scope:
  - `seedcore-approval-core` envelope validation, deterministic binding hash,
    and lifecycle transition primitives
  - `seedcore-verify` approval commands:
    - `validate-approval`
    - `approval-binding-hash`
    - `approval-summary`
    - `apply-approval-transition`
    - `verify-approval-history`
  - Python governance Restricted Custody Transfer envelope derivation now
    consumes Rust approval-summary outputs for required roles, approved
    principals, and canonical binding hash
  - Python governance now applies approval transitions via Rust and persists
    append-only transition history metadata (`approval_transition_head` and
    transition count) into workflow-facing output state
  - replay publication surfaces now expose approval transition chain metadata:
    replay timeline events, replay artifact payloads, and JSON-LD proof output
- remaining to close phase scope:
  - promote approval transition history from Python replay publication payloads
    into first-class Rust replay artifact/bundle contracts across crates

### Phase 4: TypeScript Operator Workflow Surface

Build a narrow governed workflow surface after approval semantics stabilize.

Expected deliverables:

- one constrained intake and transfer console
- approval state view
- explanation and review state view

### Phase 5: Rust PDP Decision Kernel

Move the deterministic decision kernel only after:

- workflow semantics are frozen
- the disposition truth table is stable
- the minimum explanation payload is agreed
- the minimum PKG decision projection is stable

This is the hardest migration and should happen after the surrounding contracts
stop moving.

### Phase 6: Selective Python Slimming

Once the Rust kernels exist:

- keep orchestration in Python
- keep advisory intelligence in Python
- move authority-critical checks out of Python

This is controlled boundary tightening, not a rewrite.

## Phase Scoreboard (As Of March 25, 2026)

1. Phase 0 (Contract Freeze First): In progress
Reason: contract-freeze documents exist, but full freeze enforcement is not yet
closed as a runtime gate.

2. Phase 1 (Rust Proof Kernel): Implemented for baseline scope
Reason: `seedcore-proof-core` and `seedcore-verify` are implemented with
deterministic verification paths and fixture-backed tests.

3. Phase 2 (TypeScript Proof Surface): Implemented for baseline scope
Reason: `ts/packages/contracts`, `ts/services/verification-api`, and
`ts/apps/proof-surface` are implemented, including transfer and asset proof
pages with business-readable state mapping.

4. Phase 3 (Rust Approval Engine): Partially complete
Reason: `seedcore-approval-core` is implemented, but full runtime cutover and
phase-close criteria are still pending.

5. Phase 4 (TypeScript Operator Workflow Surface): Not complete
Reason: the narrow operator workflow console remains to be built.

6. Phase 5 (Rust PDP Decision Kernel): Partially complete
Reason: `seedcore-policy-core` and `seedcore-token-core` are implemented, but
full operational cutover and freeze-aligned closure are still pending.

7. Phase 6 (Selective Python Slimming): Started, not complete
Reason: Python-to-Rust integration is active, but authority-critical logic is
not yet fully demoted from Python.

## Contract Strategy Across Python, Rust, and TypeScript

Language choice matters less than contract discipline.

Recommended split:

- Protobuf for internal service contracts such as PDP requests and responses,
  approval lifecycle events, token validation calls, and receipt metadata
  exchange
- JSON Schema for external proof artifacts such as receipts, evidence bundles,
  verification-surface payloads, and replay exports

Types should be generated into:

- Python
- Rust
- TypeScript

The important rule is one authority source, not three hand-maintained schema
families.

## Negative Ownership Rules

### Python Should Not Own Forever

- final allow or deny semantics
- receipt canonicalization
- irreversible approval transitions
- verifier source of truth

### TypeScript Should Not Own

- authoritative runtime decisions
- signer or verifier truth
- internal token semantics
- final artifact truth

### Rust Should Not Own

- prompting loops
- broad UI workflow composition
- enrichment experimentation
- early ontology exploration

## Repo Discipline Recommendation

To keep the stack healthy, define three explicit ownership zones.

### Zone A: Advisory Plane

Language:

- Python

Rule:

- may propose, enrich, simulate, and orchestrate
- may not make final authority decisions

### Zone B: Control Kernel

Language:

- Rust

Rule:

- owns deterministic artifacts, state transitions, and proof integrity
- may not absorb fuzzy or experimental logic just because it is performance
  sensitive

### Zone C: Trust Surface

Language:

- TypeScript

Rule:

- renders and exposes proof-bearing state
- may not invent authoritative runtime state

## Suggested First Milestone

The first multi-language milestone should stay narrow:

**Restricted Custody Transfer v1**

With:

- Python agent and orchestration layers initiating the flow
- Rust proof core generating signed receipts
- Rust approval core validating dual approval
- TypeScript proof surface showing approval state, disposition, receipt
  lineage, and replay verification state

This matches the current execution spine and is small enough to be credible.

## What To Avoid

- avoid a repo-wide rewrite
- avoid moving fast-changing AI orchestration into Rust too early
- avoid TypeScript backend sprawl that does not improve product clarity
- avoid leaving authority-bearing semantics in Python indefinitely

## Final Rule

The success condition is not "use three languages."

The success condition is:

> All authority-bearing semantics converge into a strict kernel, while AI and
> UI remain outside the final decision boundary.

That is the language evolution path that best fits SeedCore.
