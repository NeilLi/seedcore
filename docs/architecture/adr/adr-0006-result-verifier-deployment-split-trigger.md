# ADR 0006: Split RESULT_VERIFIER Into a Dedicated Process on Measurable Triggers

- Status: Proposed
- Date: 2026-04-20
- Scope: Deployment shape of the RESULT_VERIFIER runtime. Does not change its verification logic, DAO schema, twin mutation semantics, or its failure taxonomy.
- Related: [ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](./adr-0004-result-verifier-runtime.md) (this ADR tightens ADR 0004's "If coordinator CPU or isolation becomes an issue" clause into a measurable contract), [ADR 0003: Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments](./adr-0003-igx-thor-trusted-edge-profile.md), [SeedCore Proof Kernel PyO3 Bridge Decision Memo](../../development/seedcore_proof_pyo3_bridge_decision_memo.md)

## Context

ADR 0004 decided that RESULT_VERIFIER runs as a background runtime **inside**
the Coordinator service (Ray Serve deployment), started with the coordinator
lifecycle when `SEEDCORE_RESULT_VERIFIER_ENABLED` is set. That decision was
correct for v1. ADR 0004 also said, in its Consequences section:

> If coordinator CPU or isolation becomes an issue, the same DAO/runtime can
> be lifted into a separate process later without changing the schema or
> twin event vocabulary.

That sentence has shaped how the verifier runtime was actually built:
`result_verifier_jobs`, `result_verifier_outcomes`, and
`result_verifier_runtime_state` are all Postgres-backed; work claiming uses
`FOR UPDATE SKIP LOCKED`; watermark advancement is durable; the coordinator
code path calls into the runtime via a public service boundary. The split is
already **schema-ready**. What is missing is the criterion for when to
actually perform it.

Without a pre-agreed trigger, the decision drifts. The embedded deployment
silently becomes permanent, or it gets split under time pressure for a
reason that is not the original one. This ADR removes that drift by making
the trigger explicit, measurable, and pre-authorized.

This ADR does not override ADR 0004's verification logic, enforcement path,
or failure classification. It overrides only the deployment shape.

## Decision

1. **Keep RESULT_VERIFIER embedded in the Coordinator by default.** This is
   unchanged from ADR 0004. Do not pre-emptively split for speculative
   performance or isolation benefit.

2. **Split when any of the following triggers fire, individually, on
   production telemetry for the observation window specified.** A single
   trigger is sufficient; multiple triggers firing together do not raise the
   bar. The split is pre-authorized: when a trigger fires, the operator-of-
   record does not need to open a new decision, only the implementation
   change.

    - **CPU pressure trigger.** Coordinator replica P95 CPU utilization is
      above 70% for a rolling 7-day window **and** more than 30% of that
      utilization is attributable to verifier code paths (as measured by
      `result_verifier_job_seconds_total` / total replica CPU seconds).

    - **Latency trigger.** The P99 end-to-end verifier job latency
      (`digital_twin_event_journal` row appearance → `result_verifier_outcomes`
      row persisted) exceeds 30 seconds for any 24-hour window, **and**
      profiling attributes more than 40% of that latency to in-coordinator
      contention (GIL, serve actor queueing, intake polling gaps), not to
      database wait or Rust CPU.

    - **Blast-radius trigger.** A verifier-induced fault (panic, OOM,
      deadlock) takes down a coordinator replica or degrades hot-path PDP
      availability below its SLO in production or a production-representative
      load test. A single occurrence is sufficient; the SLO violation does
      not need to recur.

    - **Regulatory-isolation trigger.** A customer deployment under a
      regulated profile (per ADR 0003's Trusted Edge posture) requires
      verifier workloads to run in an isolated process, container, or node
      pool as a condition of acceptance. A signed customer requirement is
      sufficient evidence.

    - **Scaling-shape trigger.** The number of RCT verification jobs per
      day exceeds what a single coordinator replica can drain within its
      work-queue freshness target (default: intake watermark lag < 60s
      sustained). When horizontal coordinator replication is not an
      acceptable mitigation, this trigger fires.

3. **Split target is a dedicated `seedcore-result-verifier` service.** This
   is a minimal, pre-authorized shape:

    - **Process identity.** A separate Ray Serve deployment (initial
      target) or a standalone Kubernetes deployment (hardened target),
      named `seedcore-result-verifier`. Not a sidecar to the coordinator.

    - **Shared substrate.** Same Postgres cluster, same DAO classes, same
      `result_verifier_jobs` / `result_verifier_outcomes` /
      `result_verifier_runtime_state` tables, same Redis CRL, same
      digital twin service boundary. The only change is where the runtime
      loop calls into these from.

    - **Configuration gate.** `SEEDCORE_RESULT_VERIFIER_EMBEDDED=false` on
      the coordinator disables the embedded runtime. The new service sets
      `SEEDCORE_RESULT_VERIFIER_EMBEDDED=true` for itself.
      `SEEDCORE_RESULT_VERIFIER_ENABLED` keeps its current meaning (runtime
      on/off per process). The combined gate is:

      | Coordinator `_EMBEDDED` | Verifier svc `_ENABLED` | Effective shape            |
      | ----------------------- | ----------------------- | -------------------------- |
      | true (legacy default)   | n/a                     | embedded (today)           |
      | false                   | true                    | split (post-trigger)       |
      | false                   | false                   | verifier disabled (broken) |

      The broken combination must be rejected at startup by the coordinator.

    - **Ownership of the twin mutation boundary.** The split does **not**
      move the digital twin mutation boundary. Verifier outcomes still
      flow through `DigitalTwinService.apply_result_verifier_outcome`,
      which the dedicated service calls through the existing Python
      service boundary. This preserves ADR 0004's enforcement semantics
      byte-for-byte.

    - **CRL write path.** The dedicated service writes the Redis CRL
      directly using the same helper the coordinator uses today. The HAL
      admin revoke endpoint remains available as a human-operator path
      and is not on the verifier hot path.

4. **The split is reversible.** Reverting to embedded is a configuration
   rollback (`SEEDCORE_RESULT_VERIFIER_EMBEDDED=true` on coordinator,
   verifier service scaled to zero). No schema migration is required in
   either direction. This is a hard requirement on the split
   implementation: if implementing the split would require a
   non-reversible schema or DAO change, the split is not accepted.

5. **Coordinator replica coordination is unchanged.** Multiple coordinator
   replicas continue to be safe together; multiple verifier replicas are
   safe together for the same reason (DB-locked claim via SKIP LOCKED).
   This ADR does not require or preclude horizontal scaling of the
   verifier service.

## Rationale

- ADR 0004's embedded decision was correct for v1 because it let the
  verification loop ship without a second deployable, and the coordinator
  already held the DAOs, sessions, and service boundaries the runtime needs.
- Every technical debt associated with that embedding (coordinator CPU
  sharing, GIL contention, blast-radius coupling) is real but operationally
  invisible until production load exists. Splitting before that load exists
  is speculative.
- At the same time, drift is the actual risk. "We should split when
  coordinator CPU becomes an issue" is not a trigger; it is an excuse to
  not decide. The triggers in this ADR are numeric, measurable on current
  telemetry, and scoped to single conditions so they cannot be argued away.
- Keeping the split reversible costs nothing today because the DAO is
  already DB-backed, and it costs nothing at split time because the split
  only relocates the runtime loop. Locking in irreversibility would be a
  self-inflicted wound.
- This ADR intentionally does not interact with the PyO3 decision memo.
  If the bridge ever gets built, it lands in the same runtime loop
  regardless of whether that loop runs in the coordinator or in a
  dedicated service. The two decisions are orthogonal and should stay so.

## Consequences

- **Observability becomes a hard prerequisite.** The CPU-pressure,
  latency, and scaling-shape triggers are meaningless without
  `result_verifier_job_seconds_total`, per-code-path coordinator CPU
  attribution, and intake watermark lag metrics in production. Adding
  these metrics is on the critical path for this ADR being actionable;
  shipping them is not on the critical path for this ADR being
  **accepted**.
- **ADR 0004's Consequences section is tightened.** The informal
  "If coordinator CPU or isolation becomes an issue" clause is
  superseded by the measurable triggers in this ADR. ADR 0004 retains
  authority over verification logic, enforcement, and failure taxonomy;
  this ADR takes authority over deployment shape only.
- **Operator playbooks grow by one line.** The trigger fire is a
  pre-authorized implementation change, not a new decision. The
  operator-of-record records which trigger fired, which 24-hour or
  7-day window's data justified it, and which profile attribution
  (where relevant) was used.
- **Customer-requirement triggers bypass the metric gates.** A
  regulated-deployment requirement is, by itself, sufficient authority
  to split for that deployment, even with zero CPU or latency pressure.
  This is deliberate: ADR 0003's Trusted Edge profile is an independent
  trust boundary and should not be held hostage to generic load
  telemetry.
- **The split adds a deployable** (`seedcore-result-verifier`) to the
  platform surface. Image build, CI, rollout playbooks, and on-call
  rotations gain that one row. Nothing else in the platform surface
  changes.

## Alternatives Considered

- **Split now, regardless of load.** Rejected because none of the
  triggers have fired, because ADR 0004's embedded decision is still
  operationally correct, and because splitting adds deployable surface
  that does not buy anything until one of the triggers actually fires.
- **Leave ADR 0004 as-is, no tightening.** Rejected because the
  informal clause drifts under absence of criteria. Either this ADR
  exists or the decision migrates into chat.
- **Make any single trigger require a new ADR to act on.** Rejected
  because the whole point of enumerating triggers is to pre-authorize
  the response. Requiring a new ADR at trigger time is re-introducing
  the drift this ADR eliminates.
- **Make the split non-reversible (drop embedded path).** Rejected
  because the embedded path is cheap to keep, and the ability to
  roll back configuration without a schema migration is a meaningful
  reliability property.
- **Split only under the regulatory trigger.** Rejected because CPU,
  latency, blast-radius, and scaling pressures are equally valid
  reasons to split, and omitting them would force a future amendment
  anyway.
- **Split along a different boundary (e.g., move only the Rust
  verification call out).** Rejected because the boundary that matters
  for isolation and throughput is the runtime loop, not the Rust call
  inside it. See the PyO3 decision memo for the separate question of
  how the loop calls Rust.

## Trigger Prerequisites

The trigger prerequisites below are implemented and should be treated as the
current operational contract before a split is approved:

- Runtime emits `result_verifier_job_millis_total` with derived
  `result_verifier_job_seconds_total` for CPU-pressure evaluation.
- Runtime emits intake watermark lag gauge
  `result_verifier_watermark_lag_seconds` for scaling-shape evaluation.
- Dashboard row exists for verifier CPU pressure ratio
  (`coordinator:result_verifier_cpu_pressure_ratio`) and lag panel for
  `result_verifier_watermark_lag_seconds`.
- Operator runbook documents reversibility and the
  `SEEDCORE_RESULT_VERIFIER_EMBEDDED` gate.

## Notes

This ADR is deployment-shape work. It does not change any artifact hash,
replay bundle, signature envelope, outcome row, twin event vocabulary, or
CRL semantic. A deployment split under this ADR should be invisible to any
caller of the digital twin service, to any Python consumer of the Rust
kernel, and to any operator of an RCT workflow. If a proposed
implementation of the split breaks any of those boundaries, the
implementation is out of scope for this ADR.
