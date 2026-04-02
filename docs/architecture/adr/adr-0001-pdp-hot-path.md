# ADR 0001: Keep the PDP Stateless and Synchronous at Decision Time

- Status: Accepted
- Date: 2026-04-02
- Scope: SeedCore policy decision path for Restricted Custody Transfer and related governed actions
- Related: [Architecture Overview](../overview/architecture.md), [Asset-Centric PDP Hot Path Contract](../../development/asset_centric_pdp_hot_path_contract.md), [SeedCore 2026 Execution Plan](../../development/seedcore_2026_execution_plan.md)

## Context

SeedCore's current architecture already treats authorization as a narrow, deterministic hot path: requests are evaluated against a versioned policy snapshot, the result is turned into an execution-scoped authority envelope, and the outcome is recorded as replayable evidence.

Recent authorization systems show a consistent pattern:

- the request-time decision remains synchronous
- the policy evaluator is usually stateless at request time
- state is pushed into versioned snapshots, external graph stores, request context, consistency tokens, and audit logs
- compiled policy execution and fail-closed behavior matter more than adding asynchronous hops to the final allow/deny decision

For SeedCore, the competitive question is not whether the PDP is stateless. It is whether SeedCore can make that stateless decision path more trustworthy, faster, and more replayable than alternatives.

## Decision

SeedCore will keep the PDP decision function:

- stateless at request time
- synchronous for the final decision
- deterministic over a pinned policy snapshot and bounded request context
- fail-closed when dependencies, freshness, or contract checks are not satisfied

SeedCore will not use asynchronous policy evaluation for the final authorization decision in the hot path.

SeedCore will continue to rely on stateful supporting systems around that decision function:

- versioned policy snapshots and compiled authz artifacts
- authority, approval, custody, and telemetry context assembled before evaluation
- execution-token issuance after policy success
- governed receipts and replay evidence after decision and execution
- shadow/canary/enforce rollout with parity checks and rollback triggers

## Decision Boundaries

This ADR establishes the shape of the final authorization boundary. It does not require:

- a specific policy engine implementation
- a specific storage backend for policy snapshots or graph projections
- a prohibition on asynchronous enrichment, indexing, compilation, or audit processing

This ADR does require that the final governed decision remains a single synchronous, deterministic, fail-closed step over pinned inputs.

## Why

This design is the best balance of feasibility and advantage for the next several years because it matches how modern authorization systems are actually built while staying aligned with SeedCore's custody and replay requirements.

Benefits of this decision:

- predictable latency on the critical path
- simpler failure semantics than an async decision pipeline
- easier replay and forensic analysis
- smaller surface area for policy bypass
- better fit for short-lived execution tokens and high-consequence actions

Why this remains competitive:

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

## Implementation Notes

SeedCore should continue to preserve these properties in code and docs:

- one request-time policy decision
- one versioned policy snapshot per evaluation
- one deterministic decision vocabulary
- one governed receipt chain
- one hot-path observability contract
- one promotion gate for shadow to canary to enforce

## Follow-On Work

The items below are important strengthening work implied by this ADR, but they
are not changes to the core decision itself.

To keep this decision competitive over the next execution windows, prioritize the
following:

- Add a stronger cross-system freshness and causality contract.
- Include per-request consistency controls, strict model/version pinning, and
  explicit protection against stale authorization decisions.
- Add stricter schema/type validation for policy inputs and request context.
- Keep asynchronous work for enrichment, indexing, and compilation, not for the
  final `allow` / `deny` / `quarantine` / `escalate` decision.
- Keep the authoritative PDP local or near-local to execution boundaries where
  latency and consistency guarantees are controllable.
- Treat managed remote authorization services as better suited to admin-plane
  or moderate-risk SaaS use cases than SeedCore's final hot path.
- Introduce a Zanzibar-style external ReBAC store only if delegation/sharing
  graph complexity becomes a dominant driver; for the current wedge, the
  compiled asset-centric hot path remains the practical default.

Reference direction (informing these priorities): Zanzibar/SpiceDB/OpenFGA
consistency patterns and Cedar-style schema validation discipline.

## Alternatives Considered

### Fully Async PDP

Rejected for the hot path. It adds latency and ambiguity to the exact point where SeedCore must be crisp, bounded, and fail-closed.

### Stateful In-Process Authorization Engine

Rejected as the primary model. Mutable runtime state makes replay, rollout, and forensic explanation harder, and increases the chance of policy drift.

### Zanzibar-Style External Graph as the Primary PDP

Rejected as the default hot-path architecture for the current wedge. It is useful for large-scale relationship authorization, but SeedCore currently needs custody, evidence, and execution-token semantics first. A graph-backed ReBAC system can be added later if delegation complexity grows enough to justify it.
