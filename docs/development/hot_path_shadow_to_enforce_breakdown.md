# Hot-Path Shadow To Enforce Breakdown

Date: 2026-03-31

## Purpose

This note breaks down the requirement:

> Hot-Path Enforcement: move from `shadow` to `enforce` mode, define promotion
> criteria, close parity gaps, and prove benchmarked latency under load.

It is grounded in the current repository, not an abstract target state.

## Program Placement (2026)

This hot-path track is a dependency inside the broader 2026 productization
program, not an isolated optimization project.

Program alignment:

- Q2 priority in
  [seedcore_2026_execution_plan.md](/Users/ningli/project/seedcore/docs/development/seedcore_2026_execution_plan.md):
  make the current RCT wedge operationally promotable
- Q3 priority in
  [agent_action_gateway_contract.md](/Users/ningli/project/seedcore/docs/development/agent_action_gateway_contract.md):
  expose a stable external agent boundary over a trustworthy decision path
- product narrative in
  [seedcore_positioning_narrative.md](/Users/ningli/project/seedcore/docs/development/seedcore_positioning_narrative.md):
  SeedCore owns admissibility and proof, so the decision path must be
  operationally defensible

Practical implication:

- `shadow -> enforce` readiness is part of "useful this year"
- if this track stalls, the external agent gateway becomes a thin wrapper around
  non-promotable internals

## Current Repo State

What already exists:

- a formal promotion contract in
  [hot_path_enforcement_promotion_contract.md](/Users/ningli/project/seedcore/docs/development/hot_path_enforcement_promotion_contract.md)
- a typed hot-path endpoint and shadow-status endpoint in
  [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py)
- hot-path evaluation logic and parity accounting in
  [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py)
- a canonical shadow verifier in
  [verify_rct_hot_path_shadow.py](/Users/ningli/project/seedcore/scripts/host/verify_rct_hot_path_shadow.py)
- authz-graph runtime health and refresh endpoints in
  [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py)
  and
  [authz_graph/manager.py](/Users/ningli/project/seedcore/src/seedcore/ops/pkg/authz_graph/manager.py)

What is still true today:

- the hot-path endpoint is mostly a verification sidecar; the main coordinator
  execution path still builds a `policy_case` and calls `evaluate_intent(...)`
  directly in
  [coordinator_service.py](/Users/ningli/project/seedcore/src/seedcore/services/coordinator_service.py)
- `SEEDCORE_RCT_HOT_PATH_MODE` is read once at module import time in
  [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py),
  so the documented rollback requirement of toggling back to `shadow` without a
  restart is not implemented yet
- shadow stats are in-memory only, keep only `256` latency samples and `20`
  recent results, and cannot prove the contract's required last `1,000`
  production-equivalent runs
- the current live sign-off doc shows green parity for the four canonical cases,
  but the recorded latency profile (`p50=52ms`, `p95=130ms`, `p99=146ms`) is
  above the stricter promotion contract threshold
- the repo has adjacent benchmark scripts, but there is not yet a dedicated
  load-test harness for `/api/v1/pdp/hot-path/evaluate` under realistic
  concurrency

## Main Gap Categories

The requirement breaks into five separate problems:

1. Define what `shadow` and `enforce` actually mean on the serving path.
2. Turn parity from an in-memory debug statistic into promotion-grade evidence.
3. Add safety rails so `enforce` fails closed instead of becoming a risky fast path.
4. Prove the hot path meets latency SLOs under load, not only on a tiny manual run.
5. Create an operator workflow for promotion, rollback, and sign-off.

## Recommended Breakdown

### Phase 0: Make Mode Semantics Real

Goal:

- define authoritative runtime behavior for `shadow`, `canary`, and `enforce`

Concrete work:

- introduce a small mode resolver instead of module-import-time
  `HOT_PATH_MODE`
- decide where mode is enforced:
  - either inside the coordinator/governance serving path
  - or in a dedicated hot-path selector used by the coordinator
- keep `shadow` as dual-evaluate plus baseline-authoritative
- make `enforce` candidate-authoritative with fail-closed fallback to
  `quarantine`
- add a narrow intermediate `canary` lane before full `enforce`

Primary code areas:

- [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py)
- [coordinator_service.py](/Users/ningli/project/seedcore/src/seedcore/services/coordinator_service.py)
- [governance.py](/Users/ningli/project/seedcore/src/seedcore/coordinator/core/governance.py)

Exit criteria:

- one runtime path clearly owns RCT hot-path serving selection
- switching from `shadow` back to `shadow` after `enforce` does not require a
  process restart
- tests prove baseline-authoritative versus candidate-authoritative behavior

### Phase 1: Close Promotion-Grade Parity Gaps

Goal:

- move from "parity looked good on recent runs" to "parity is promotable"

Concrete work:

- persist hot-path parity events instead of keeping them only in process memory
- expand parity accounting to a durable rolling window of at least `1,000` runs
- record enough context to root-cause mismatches:
  - request id
  - asset ref
  - snapshot version
  - baseline view
  - candidate view
  - mismatch keys
- explicitly track parity across PKG snapshot rotations
- promote the canonical four-case verifier into a repeatable CI or host gate
- add wider fixture coverage beyond the current canonical matrix

Primary code areas:

- [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py)
- [verify_rct_hot_path_shadow.py](/Users/ningli/project/seedcore/scripts/host/verify_rct_hot_path_shadow.py)
- [authz_parity_service.py](/Users/ningli/project/seedcore/src/seedcore/ops/pkg/authz_parity_service.py)
- [test_pdp_hot_path_router.py](/Users/ningli/project/seedcore/tests/test_pdp_hot_path_router.py)

Exit criteria:

- `1,000`-run parity evidence is exportable
- all mismatches are queryable and root-causable
- parity stays green across at least `3` snapshot rotations

### Phase 2: Add Safety And Observability Gates

Goal:

- make hot-path enforcement safe to operate

Concrete work:

- use authz-graph `compiled_at` status to compute graph age on every decision
- quarantine automatically when the compiled graph is older than the allowed
  freshness window
- surface dependency readiness directly in hot-path status:
  - authz graph healthy
  - snapshot aligned
  - approval source reachable
  - current mode
- emit alertable signals for:
  - any parity mismatch
  - snapshot mismatch
  - stale compiled graph
  - dependency unavailability
  - false-positive allow in enforce mode
- verify audit-chain consistency for hot-path decisions, not only response
  payload shape

Primary code areas:

- [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py)
- [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py)
- [authz_graph/manager.py](/Users/ningli/project/seedcore/src/seedcore/ops/pkg/authz_graph/manager.py)
- replay and evidence projection paths under
  [src/seedcore/services](/Users/ningli/project/seedcore/src/seedcore/services)
  and
  [src/seedcore/ops/evidence](/Users/ningli/project/seedcore/src/seedcore/ops/evidence)

Exit criteria:

- stale authz graph causes deterministic `quarantine`
- parity mismatches become operator-visible events, not only buried recent rows
- rollback thresholds can be monitored from runtime telemetry

### Phase 3: Build A Real Hot-Path Load Benchmark

Goal:

- prove latency against the actual hot-path contract under concurrent load

Concrete work:

- add a dedicated benchmark runner for `/api/v1/pdp/hot-path/evaluate`
- run against realistic RCT payloads and the persisted approval flow
- support configurable concurrency, warmup, total requests, and snapshot pinning
- record:
  - p50, p95, p99
  - error rate
  - quarantine rate
  - mismatch rate
  - dependency health during the run
- separate single-request microbenchmarks from concurrent end-to-end load tests

Primary code areas:

- new script under
  [scripts/host](/Users/ningli/project/seedcore/scripts/host)
- existing fixture inputs under
  [rust/fixtures/transfers](/Users/ningli/project/seedcore/rust/fixtures/transfers)
- local runtime bring-up flow in
  [deploy/local/README.md](/Users/ningli/project/seedcore/deploy/local/README.md)

Exit criteria:

- benchmark runs are repeatable in host mode
- latency evidence is captured under concurrency, not only sequential case replay
- results are suitable for inclusion in sign-off

### Phase 4: Optimize Until The Contract Is Actually True

Goal:

- close the performance gap revealed by the new benchmark

Likely optimization targets:

- approval-envelope lookup cost before decision evaluation
- policy-case assembly overhead
- compiled authz graph access path
- unnecessary response-shaping or duplicate baseline evaluation work
- any signer or receipt work happening synchronously on the critical path

Important note:

- the repo should not assume the current hot path is already fast enough
- the latest recorded live numbers are still above the promotion target, so this
  phase should be expected, not treated as optional cleanup

Exit criteria:

- `p50 < 25ms`, `p95 < 50ms`, and `p99 < 100ms` are met under the agreed load profile
- no fail-open behavior appears while tuning

### Phase 5: Promotion And Rollback Runbook

Goal:

- make the move to `enforce` operationally reversible and reviewable

Concrete work:

- define promotion inputs:
  - parity export
  - latency report
  - signer verification
  - dependency health window
- add a canary sequence:
  - `shadow`
  - small percentage authoritative serving
  - wider ramp
  - full `enforce`
- define automated rollback triggers from the contract
- capture the final sign-off artifact bundle in a stable location

Primary docs:

- [hot_path_enforcement_promotion_contract.md](/Users/ningli/project/seedcore/docs/development/hot_path_enforcement_promotion_contract.md)
- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [restricted_custody_transfer_demo_signoff_report.md](/Users/ningli/project/seedcore/docs/development/restricted_custody_transfer_demo_signoff_report.md)

Exit criteria:

- operators have one documented promote and rollback path
- sign-off can be reproduced from repo scripts and captured evidence

## Suggested Execution Order

The cleanest sequencing is:

1. Phase 0 first, because `enforce` is not well-defined yet on the real serving path.
2. Phase 1 and Phase 2 next, because promotion without durable evidence and safety
   gates would be misleading.
3. Phase 3 before heavy optimization work, so tuning is driven by measured hot-path
   load rather than intuition.
4. Phase 4 after the benchmark exposes the real bottlenecks.
5. Phase 5 last, once the system is genuinely promotable.
6. Agent Action Gateway rollout after Phase 1/2 minimums are stable, so external
   callers do not bind to unstable decision semantics.

## Practical Definition Of Done

This requirement should be considered complete only when all of the following are
true at the same time:

- the coordinator can authoritatively serve RCT decisions from the hot path
- `shadow`, `canary`, and `enforce` behavior is explicit and tested
- parity evidence covers at least `1,000` production-equivalent runs and `3`
  snapshot rotations
- the compiled authz graph age is actively enforced as a safety gate
- load-test evidence shows the contract latency targets under concurrent host-mode
  traffic
- operators can promote and rollback without a restart and without ambiguous manual
  steps
