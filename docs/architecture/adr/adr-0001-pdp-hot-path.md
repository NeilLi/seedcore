# ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time

- Status: Accepted
- Date: 2026-04-02
- Scope: SeedCore policy decision path for Restricted Custody Transfer and related governed actions

## Context

SeedCore's current architecture already treats authorization as a narrow, deterministic hot path: requests are evaluated against a versioned policy snapshot, the result is turned into an execution-scoped authority envelope, and the outcome is recorded as replayable evidence.

Recent authorization systems show a consistent pattern:

- the request-time decision remains synchronous
- the policy evaluator is usually stateless at request time
- state is pushed into versioned snapshots, external graph stores, request context, consistency tokens, and audit logs
- compiled policy execution and fail-closed behavior matter more than adding asynchronous hops to the final allow/deny decision

For SeedCore, the competitive question is not whether the PDP is stateless. It is whether SeedCore can make that stateless decision path more trustworthy, faster, and more replayable than alternatives.

## Decision

SeedCore will keep the PDP decision path:

- stateless at request time
- synchronous for the final decision
- deterministic over a pinned policy snapshot and bounded request context
- fail-closed when dependencies, freshness, or contract checks are not satisfied

SeedCore will not use asynchronous policy evaluation for the final authorization decision in the hot path.

Instead, SeedCore will surround the PDP with stateful supporting systems:

- versioned policy snapshots and compiled authz artifacts
- authority, approval, custody, and telemetry context assembled before evaluation
- execution-token issuance after policy success
- governed receipts and replay evidence after decision and execution
- shadow/canary/enforce rollout with parity checks and rollback triggers

## Rationale

This design is the best balance of feasibility and advantage for the next several years because it matches how modern authorization systems are actually built while staying aligned with SeedCore's custody and replay requirements.

Benefits:

- predictable latency on the critical path
- simpler failure semantics than an async decision pipeline
- easier replay and forensic analysis
- smaller surface area for policy bypass
- better fit for short-lived execution tokens and high-consequence actions

Why this is still competitive:

- the moat is not "stateless PDP" by itself
- the moat is the combination of compiled policy, pinned snapshots, strict context typing, evidence binding, and operator-visible parity/rollback control
- SeedCore can make the final decision faster and more auditable than systems that rely on live graph rebuilding or loosely coupled policy calls

## Consequences

Positive:

- the final decision remains fast enough for user-facing and agent-facing workflows
- policy decisions are easier to reproduce from the same snapshot and request context
- execution and evidence layers can evolve independently of the decision contract

Negative:

- the snapshot and context supply chain becomes critical infrastructure
- stale telemetry or stale snapshots must be handled explicitly and conservatively
- any future extension that needs rich sharing or delegation graphs may require a separate graph-backed store, but not as the default hot-path architecture

## Alternatives Considered

### Fully Async PDP

Rejected for the hot path. It adds latency and ambiguity to the exact point where SeedCore must be crisp, bounded, and fail-closed.

### Stateful In-Process Authorization Engine

Rejected as the primary model. Mutable runtime state makes replay, rollout, and forensic explanation harder, and increases the chance of policy drift.

### Zanzibar-Style External Graph as the Primary PDP

Useful for large-scale relationship authorization, but not the right primary architecture for SeedCore's current wedge. SeedCore needs custody, evidence, and execution-token semantics first; a graph store can be added later if delegation complexity grows enough to justify it.

## Implementation Notes

SeedCore should continue to preserve these properties in code and docs:

- one request-time policy decision
- one versioned policy snapshot per evaluation
- one deterministic decision vocabulary
- one governed receipt chain
- one hot-path observability contract
- one promotion gate for shadow to canary to enforce

This ADR is intentionally aligned with the current architecture overview, the asset-centric PDP hot-path contract, and the Q2 execution plan.

