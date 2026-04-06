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

### Context Supply Chain Clarification

For SeedCore, a stateless PDP does **not** mean "pull whatever context is available at request time."

It means the final decision stays stateless while the **context supply chain**
becomes a first-class, fail-closed subsystem with four required properties:

- event-driven context propagation instead of best-effort polling
- per-request causality and freshness controls
- cryptographically verifiable context envelopes for edge-critical attributes
- attribute-level ownership and freshness SLAs

For high-consequence actions, stale context should be treated as a policy
failure, not as a soft operational inconvenience. In practice, stale custody,
approval, or device state is often equivalent to an authorization bypass.

## Decision Boundaries

This ADR establishes the shape of the final authorization boundary. It does not require:

- a specific policy engine implementation
- a specific storage backend for policy snapshots or graph projections
- a prohibition on asynchronous enrichment, indexing, compilation, or audit processing

This ADR does require that the final governed decision remains a single synchronous, deterministic, fail-closed step over pinned inputs.

This ADR also requires that the systems feeding that step be designed so the PDP
does not need to perform live, multi-hop consistency discovery at request time.

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
- the moat is the combination of compiled policy, pinned snapshots, strict context typing, freshness and causality guarantees, evidence binding, and operator-visible parity/rollback control
- SeedCore can make the final decision faster and more auditable than systems that rely on live graph rebuilding or loosely coupled policy calls

### Why the Context Supply Chain Must Be Stronger

Mature authorization systems do not solve freshness by making the final check
asynchronous. They solve it by making the surrounding state pipeline more
causally disciplined.

Patterns that inform SeedCore here:

- log-based CDC pipelines move source-of-truth mutations into streaming systems
  quickly enough for near-local materialized views and caches to stay current
- Zanzibar's zookie model, and SpiceDB's equivalent `ZedToken`, show how a
  caller can require a check to be "at least as fresh" as a causally relevant
  update
- cryptographic attenuation/envelope mechanisms such as macaroons and biscuit
  tokens show how context can be carried with the request itself rather than
  rediscovered through a late network round-trip

For SeedCore, these patterns are especially relevant because the hot path can
govern simulator execution, custody release, or physical robot actions. In that
environment, context lag is not merely stale UI data; it can create a real
world policy gap.

## Consequences

Positive:

- the final decision remains fast enough for user-facing and agent-facing workflows
- policy decisions are easier to reproduce from the same snapshot and request context
- execution and evidence layers can evolve independently of the decision contract

Negative:

- the snapshot and context supply chain becomes critical infrastructure
- stale telemetry or stale snapshots must be handled explicitly and conservatively
- local context caches, stream processors, and causality-token handling now sit
  on the trust-critical path even if they are outside the final PDP function
- any future extension that needs rich sharing or delegation graphs may require a separate graph-backed store, but not as the default hot-path architecture

## Implementation Notes

SeedCore should continue to preserve these properties in code and docs:

- one request-time policy decision
- one versioned policy snapshot per evaluation
- one deterministic decision vocabulary
- one governed receipt chain
- one hot-path observability contract
- one promotion gate for shadow to canary to enforce

SeedCore should also strengthen the context supply chain with the following
implementation rules.

### 1. Prefer Event-Driven Context Pipelines Over Request-Time Pulls

Wherever possible, context used by the hot path should be pushed from systems of
record into local materialized views or caches by event streams, not assembled
by synchronous fan-out during the final authorization call.

Preferred shape:

- source-of-truth mutation occurs
- CDC or equivalent change stream emits the mutation
- Kafka or another durable event backbone distributes the change
- near-local policy context views and caches subscribe and update
- the final PDP evaluates against those pinned local views

This is a better fit for SeedCore than repeatedly querying live backing systems
for approval, custody, or edge state at decision time.

### 2. Add Causality Tokens to Mutations and Requests

Critical mutations should return an opaque causality token representing a
minimum freshness boundary for later checks.

Examples:

- approval envelope updated
- custody or twin state changed
- delegation or role revoked
- asset lock or release status changed

The request assembler or PEP should be able to attach a causality token to a
subsequent hot-path check and require the local context view to be at least that
fresh before evaluation proceeds.

If the local context store cannot prove that freshness bound in time, the
request should block briefly for convergence or fail closed. SeedCore should not
silently downgrade to "best effort" freshness for high-consequence actions.

### 3. Use Cryptographically Bound Context Envelopes for Edge-Critical State

For edge and robotics workflows, some context should arrive as a signed
envelope rather than as a late database lookup.

Examples include:

- hardware identity and attestation summary
- joint or actuator state
- thermal or safety-limit telemetry
- custody sensor evidence
- signed edge telemetry envelopes already modeled by SeedCore

The PDP remains stateless here too: it verifies the signature, checks freshness
and scope, and evaluates policy over the attached claims. This removes a whole
class of race conditions caused by request-time polling of remote edge state.

### 4. Enforce Attribute-Level Freshness SLAs

SeedCore should not treat all context as equally fresh or equally expensive.
Each context class should have:

- a data owner
- a source of truth
- a required freshness SLA
- a fail-closed disposition if the SLA is violated

Example direction:

- org/profile context may tolerate minute-level staleness for low-risk reads
- approval or delegation context may require tighter bounds for governed writes
- custody and robot/device telemetry for physical execution may require
  sub-second or otherwise explicitly bounded freshness

The important rule is that the SLA must be explicit and replay-visible, not left
to implicit cache defaults.

### 5. Bind Freshness Into Replay Evidence

Governed receipts and replay artifacts should continue evolving so they can
explain not only which policy snapshot was used, but also which context-freshness
and causality boundary was satisfied at decision time.

This direction is already compatible with SeedCore's `state_binding_hash`
trajectory and should grow toward:

- context version or token references
- freshness check outcomes
- edge-envelope signature provenance
- explicit mismatch or timeout reasons when quarantine occurs

## Follow-On Work

The items below are important strengthening work implied by this ADR, but they
are not changes to the core decision itself.

To keep this decision competitive over the next execution windows, prioritize the
following:

- Add a stronger cross-system freshness and causality contract.
- Define one explicit causality-token format for hot-path-relevant mutations and
  request assembly.
- Move trust-critical approval, custody, and delegation projections toward
  event-driven or CDC-backed local context views.
- Include per-request consistency controls, strict model/version pinning, and
  explicit protection against stale authorization decisions.
- Add request fields and replay evidence fields for context version/freshness
  proofs where the workflow is sensitive enough to require them.
- Add stricter schema/type validation for policy inputs and request context.
- Define attribute-level freshness SLAs and fail-closed behavior by context
  class, especially for custody, telemetry, and hardware state.
- Prefer signed edge-state envelopes over request-time remote polling for
  hardware-critical facts.
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

Concrete reference patterns informing this direction:

- Debezium-style log-based CDC and event streaming for context propagation
- Zanzibar zookies / SpiceDB `ZedToken`-style causality bounds
- Macaroon / Biscuit-style cryptographic attenuation and request-bound context
  envelopes

## Alternatives Considered

### Fully Async PDP

Rejected for the hot path. It adds latency and ambiguity to the exact point where SeedCore must be crisp, bounded, and fail-closed.

### Stateful In-Process Authorization Engine

Rejected as the primary model. Mutable runtime state makes replay, rollout, and forensic explanation harder, and increases the chance of policy drift.

### Zanzibar-Style External Graph as the Primary PDP

Rejected as the default hot-path architecture for the current wedge. It is useful for large-scale relationship authorization, but SeedCore currently needs custody, evidence, and execution-token semantics first. A graph-backed ReBAC system can be added later if delegation complexity grows enough to justify it.

### Best-Effort Request-Time Context Fetching

Rejected for the hot path. It creates hidden consistency races exactly where
SeedCore needs the most deterministic behavior. For high-consequence actions,
request-time pull chains should be minimized in favor of subscribed local views,
causality tokens, and signed context envelopes.

## References

- [Debezium Architecture](https://debezium.io/documentation/reference/architecture.html)
- [Debezium PostgreSQL Connector](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
- [Zanzibar: Google's Consistent, Global Authorization System](https://www.usenix.org/conference/atc19/presentation/pang)
- [SpiceDB Consistency and ZedTokens](https://authzed.com/docs/spicedb/concepts/consistency)
- [Macaroons: Cookies with Contextual Caveats for Decentralized Authorization in the Cloud](https://research.google/pubs/macaroons-cookies-with-contextual-caveats-for-decentralized-authorization-in-the-cloud/)
- [Biscuit FAQ](https://www.biscuitsec.org/docs/help/faq/)
