# Autonomous Verifier Agents Decision Memo

Date: 2026-03-31

## Purpose

This memo evaluates whether SeedCore should implement the following requirement
now:

> Autonomous Verifier Agents (M2M Trust): Implement background agents that use
> the Rust `seedcore-verify` kernel to monitor the event stream and
> auto-quarantine twins on verification failure.

This decision is grounded in the current repository and active stage plan.
It is not a rejection of the long-term architecture direction.

## Decision

Decision: `DEFER`

Recommendation:

- do not implement autonomous verifier agents in the current milestone
- keep this requirement as a later-stage runtime capability
- revisit it only after the current hot-path, trust-hardening, and
  verification-surface priorities are materially complete

Short version:

- yes for the north-star architecture
- no for the current execution slice

## Why This Is Deferred

The requirement appears in the north-star architecture reference in
[north_star_autonomous_trade_environment.md](/Users/ningli/project/seedcore/docs/development/north_star_autonomous_trade_environment.md),
which explicitly describes a target environment where `RESULT_VERIFIER` agents
monitor the event stream and automatically quarantine twins on verification
failure.

That is directionally correct, but it is not the current delivery gate.

The active staged plan in
[current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
prioritizes:

- trust hardening
- multi-party governance
- the operational decision engine
- the verification product surface

The current signed-off Restricted Custody Transfer wedge in
[restricted_custody_transfer_demo_signoff_report.md](/Users/ningli/project/seedcore/docs/development/restricted_custody_transfer_demo_signoff_report.md)
already demonstrates:

- offline replay verification
- runtime proof projection
- business-readable verification states
- quarantine as a workflow outcome

But it does not claim that background verifier agents are implemented.

## What Already Exists

The repository already contains most of the underlying building blocks needed
for this future capability:

- Rust replay-chain verification through `seedcore-verify`
- Python integration helpers that call `verify-chain`
- replay/proof surfaces that expose `verified`, `quarantined`, `rejected`,
  `review_required`, and `verification_failed`
- persistent digital twin state, twin history, and append-only twin event
  journaling
- a `RESULT_VERIFIER` specialization in the agent taxonomy

This means the repo already supports verifier logic and verifier-facing product
surfaces.

## What Is Still Missing

The required runtime behavior itself is not implemented yet.

Missing pieces include:

- a background worker or agent loop that continuously consumes the twin event
  stream
- a deterministic trigger for when replay verification should run
- an authoritative write path that updates twins to `quarantined` or
  `verification_failed` because of verifier failure
- downstream transaction pause logic wired directly to those verifier-driven
  state transitions
- operational controls for idempotency, retries, alerting, and incident
  handling around autonomous quarantine

In other words, this is not a small extension to the current verifier.
It is a new runtime subsystem.

## Why It Should Not Preempt Current Work

Implementing this now would compete directly with work that is already more
urgent and more clearly on the critical path:

- moving the hot path from `shadow` to a safe and evidence-backed `enforce`
  mode
- closing parity, rollback, and observability gaps for hot-path promotion
- continuing trust hardening around signer provenance, TPM or KMS-backed
  verification, and replay integrity
- finishing the operator-facing verification and proof surfaces for the
  Restricted Custody Transfer wedge

Those items are already called out as live gaps in
[hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
and in the current staged roadmap.

## Revisit Triggers

This requirement should be promoted only when most of the following are true:

- the hot path has clear `shadow`, `canary`, and `enforce` semantics
- fail-closed quarantine behavior is already proven on the serving path
- replay verification outcomes are durable, queryable, and operator-visible
- signer and trust-anchor hardening are stable enough that automated quarantine
  will not create noisy false positives
- there is a clear event-stream ownership model for autonomous verification
- the Restricted Custody Transfer wedge needs autonomous runtime quarantine as a
  real operating capability, not just a future-state architecture claim

## Recommended Later Implementation Shape

When this requirement is revisited, the first implementation should be narrow:

- build a small verifier worker or daemon first, not a broad agent framework
- consume the twin event journal or replay-ready audit events
- invoke the Rust verifier as the source of truth
- write explicit verifier decisions back into authoritative twin state
- gate downstream execution off those persisted verifier outcomes

That approach keeps the trust logic narrow and testable while preserving the
option to package it later as a richer autonomous agent role.

## Final Call

Autonomous Verifier Agents are a valid part of SeedCore's north-star trust
model.

They are not required to complete the current milestone, and implementing them
now would likely dilute effort from higher-priority work that is already on the
critical path.

The right decision today is:

- `Later, not now`
