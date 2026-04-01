# SeedCore 2026 Execution Plan

Date: 2026-04-01
Status: Working execution plan

## Purpose

This document converts the current SeedCore strategy into a concrete 2026
execution plan.

It is meant to answer:

> If SeedCore is going to become genuinely useful this year, what exactly do we
> ship, in what order, and how do we know the work is actually moving the
> product forward?

This plan is grounded in the current repo state:

- the must-win workflow remains `Restricted Custody Transfer`
- the proof / verification surface is the first real product surface
- the hot path remains in `shadow`
- the runtime already has a credible governed execution baseline

This is not a speculative "future platform" plan. It is a wedge-first
execution plan.

## 2026 Objective

The 2026 objective should be:

**Make SeedCore the verifiable agentic ledger for one high-trust agent workflow
that can be piloted credibly before year end.**

In practice, that means:

- one canonical workflow
- one external agent boundary
- one physical custody boundary
- one runtime decision contract
- one evidence loop
- one verification surface
- one forensic replay story that survives adversarial review

Everything else is secondary.

## Product Definition For 2026

The product to ship this year is:

**Agent-Governed Restricted Custody Transfer with a Forensic Handshake**

User-level promise:

- an external agent requests a restricted transfer or purchase intent
- SeedCore validates delegated authority and policy
- SeedCore returns `allow`, `deny`, `quarantine`, or `escalate`
- if allowed, SeedCore mints transaction-specific execution authority
- the physical actor produces sensor-grounded evidence before closure
- SeedCore binds the economic and physical evidence into one replayable
  forensic chain
- operators and partners can verify the result afterward without trusting the
  initiating agent

This should be treated as the canonical 2026 package.

## Architectural Positioning In One Diagram

Use this framing consistently across roadmap and architecture discussions:

- top (`Brain/Intent`): humans and AI agents originate intent
- bottom (`Sandboxes/Reality`): economic and physical systems emit evidence
- center hub (`SeedCore`): PDP plus forensic evidence integrator

Boundary mapping:

- economic boundary: commerce transaction and order identifiers (for example,
  Shopify sandbox)
- physical boundary: simulation or edge telemetry and motion evidence (Gazebo
  in Q3, Jetson/robot edge in Q4)

SeedCore obligation:

- do not issue scoped authority for high-consequence execution unless policy,
  approval lineage, and boundary evidence requirements are satisfied
- persist one replayable forensic handshake chain tying decision, authority,
  and closure evidence together

For 2026, that package should be grounded in one concrete physical story:

- the governed good is physically handled during transfer
- the edge evidence source is a Jetson AGX Orin-class node
- the Q4 pilot package scopes a Unitree B2-class robot as the physical courier
  or custodian actor
- the digital transaction boundary is represented through a narrow commerce
  sandbox integration such as Shopify Sandbox
- the physical custody boundary is represented through Gazebo simulation in Q3
  and hardware-in-the-loop in Q4
- the digital twin mutation is tied to the exact transfer event, not only the
  policy decision

## Canonical 2026 Handshake

The must-win story for the year is this six-step sequence:

1. Human provides a rough request such as "get me a Tang Dynasty style tea set,
   roughly $50."
2. Agent-B queries the commerce sandbox, identifies the item, and signs an
   intent packet with its delegated hardware-bound identity.
3. Agent-S validates the authority chain, reserves the item, and returns the
   physical location or custody coordinates.
4. The physical actor executes the move or verification path, then captures
   shelf or handover evidence plus telemetry.
5. SeedCore packages the request, decision, quote, location evidence, and edge
   telemetry into a forensic block.
6. Settlement or transfer release occurs only when the digital and physical
   fingerprints agree.

This is still `Restricted Custody Transfer`. The difference is that the 2026
story now makes the proof boundary explicit.

## Execution Principles

Every 2026 deliverable should improve at least one of these:

- authority correctness
- runtime safety
- evidence integrity
- operator trust
- partner verifiability
- external agent integration
- physical and economic state convergence

If a task does not improve one of those directly for `Restricted Custody
Transfer`, it is sidecar.

## Workstreams

The year should be run as five connected workstreams.

## Cluster Deployment Posture (Trust Slice)

For pilot and production-facing deployments, SeedCore should run as a
high-availability trust service on the cloud cluster rather than as a
single-node demo dependency.

Operational role by substrate:

| Substrate | Operational role |
| :--- | :--- |
| Confluent Kafka | Event backbone for intent, telemetry, and policy outcome streams |
| Ray + Kubernetes | Distributed execution for compiled authz graph and shard-aware hot-path routing |
| Redis | Token revocation and emergency cutoff propagation |
| Cloud KMS | Hardware-backed signing for policy and transition artifacts |
| Durable forensic store | Long-lived persistence for signed forensic blocks and replay evidence |

Non-negotiable invariant:

- SeedCore is the final authority service for the trust slice. If evidence
  convergence fails, SeedCore must not attest the forensic handshake.

### Workstream 1: Hot-Path Operability

Goal:

- turn the current hot-path shadow work into production-grade operational
  evidence

Required outcomes:

- real runtime semantics for `shadow`, `canary`, and `enforce`
- durable parity evidence for the last `1,000` runs
- operator-visible mismatch and freshness alerts
- realistic concurrent benchmark coverage
- explicit rollback and auto-quarantine behavior
- graph and decision readiness signals that remain trustworthy under degraded
  edge conditions

Primary repo anchors:

- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [hot_path_enforcement_promotion_contract.md](/Users/ningli/project/seedcore/docs/development/hot_path_enforcement_promotion_contract.md)

### Workstream 2: Agent Action Gateway And Delegated Authority

Goal:

- make SeedCore callable by an external agent through a clean product boundary
  with narrow zero-trust authority

Required outcomes:

- one stable request schema for agent-originated actions
- identity and delegated-authority binding for agent principals
- hardware or device fingerprint capture on the request path
- transaction-specific token scoping to workflow, product or asset id, and
  physical scope
- deterministic error contracts
- multi-signature release hooks for human approval plus physical verification
- one reference adapter for a current agent platform
- one reference digital-transaction adapter for the canonical commerce story

This is the workstream that turns SeedCore from "deep system" into "integrable
product" without weakening the trust boundary.

### Workstream 3: Evidence Closure, Forensic Blocks, And Settlement

Goal:

- prove not only that the action was authorized, but that the governed outcome
  actually happened and can be replayed later

Required outcomes:

- evidence ingestion required for selected allowed actions
- sensor-grounded evidence schemas for cryptographically signed edge telemetry
- a canonical fingerprint component set for the pilot, covering:
  - economic transaction hash
  - physical presence hash
  - policy or reason trace hash
  - actuator or torque telemetry hash
- a first-class forensic block that binds:
  - request and decision hashes
  - approval and delegation linkage
  - product or asset identity
  - physical evidence references
  - telemetry and torque or weight signals
  - settlement and twin mutation references
- authoritative twin settlement on completion
- atomic linkage between twin-state mutation and localized physical evidence:
  - location
  - environmental readings
  - hardware health
- synchronized state capture for the canonical digital transaction boundary and
  the physical execution boundary
- audit-chain consistency across runtime, replay, and verification
- explicit failure handling for missing, stale, or contradictory evidence

Interpretation:

- "settlement" is not only a completed status flag
- settlement means SeedCore can prove which governed state transition occurred,
  which physical evidence was attached, and which twin state was finalized as a
  result

### Workstream 4: Verification Surface Productization

Goal:

- make the proof story usable for operators and third parties

Required outcomes:

- workflow-specific operator status and forensic views
- narrow partner/public proof surfaces
- stable explanation payloads
- signer provenance and authority-source visibility
- digital-twin state visibility at the exact handover moment
- a usable audit-trail view that can correlate:
  - natural-language or agent request
  - digital transaction trail
  - physical replay and telemetry timeline
- runbooks for lookup, exception handling, and investigation

Q2 product spec for this workstream:

- [q2_2026_audit_trail_ui_spec.md](/Users/ningli/project/seedcore/docs/development/q2_2026_audit_trail_ui_spec.md)

### Workstream 5: Pilot Packaging

Goal:

- package the above into something a design partner can evaluate

Required outcomes:

- one deployment path
- one operational runbook
- one scripted demo / simulation
- one verification package
- one clear integration guide
- one physical handover story that crosses the edge boundary
- one adversarial drill package proving the pilot is resilient, not only happy
  path

The Q4 pilot package should be explicit about the hardware story:

- the Unitree B2 is the scoped physical actor for custody movement or handover
- the Jetson edge node is the scoped telemetry and local execution boundary
- the pilot demonstrates allow / deny behavior using both digital credentials
  and real-time physical telemetry
- the operator surface shows both proof artifacts and the twin state captured at
  custody transfer time
- the pilot includes at least three red-team drills:
  - coordinate tampering
  - stolen authority replay
  - physical double-spend attempt

## Quarter Plan

## Q2 2026: Make The Wedge Operable And Freeze The Forensic Contract

This quarter should focus on hardening what already exists and freezing the
first replay-grade forensic schema.

### Primary objective

- convert the current RCT sign-off wedge into an operable, repeatable trust
  runtime slice with stable forensic inputs

### Must-ship items

- freeze and version the current runtime-up RCT sign-off bundle
- freeze the Q2 Audit-Trail UI contract for the four-screen verification surface
  (`Transfers`, transfer detail, asset forensics, replay/verification)
- implement runtime-selectable hot-path mode semantics
- persist parity events and build `1,000`-run exportable evidence
- instrument hot-path observability consistently across Kubernetes and host-mode
  environments
- add graph freshness and dependency-based auto-quarantine
- add dedicated hot-path benchmark harness coverage for concurrent load
- promote runtime matrix capture and replay verification into CI / host gates
- define the deployment topology used by CI / host gates and benchmark the Ray
  coordination path under that topology
- freeze the first forensic block field set for the canonical workflow
- choose the schema direction explicitly:
  - canonical replay/export shape: JSON-LD
  - optional internal transport mirror later: Protobuf
- define transaction-specific authority binding inputs:
  - asset or product id
  - facility or zone scope
  - policy snapshot or decision hash
  - device fingerprint handle
- include simulated edge-network conditions in hot-path testing:
  - intermittent connectivity
  - sensor jitter / noise
  - edge hardware latency

### Exit criteria

- sign-off evidence is repeatable, not one-off
- hot-path observability is operator-grade
- `shadow` mode becomes promotion-quality evidence
- the first forensic block contract is fixed enough to build adapters against
- the runtime is stable enough to expose as a real integration boundary
- concurrency results reflect real coordination behavior, not only local happy
  path benchmarks

### Non-goals

- no broad product rebrand
- no general multi-workflow expansion
- no full autonomous robotics stack work

## Q3 2026: Productize The Agent Boundary And State Convergence

This quarter should make SeedCore usable by external agent systems and prove
that digital and physical state can be reconciled deterministically.

### Primary objective

- define the cleanest possible external contract for governed action requests
  and the first multi-agent forensic handshake

### Must-ship items

- stable `AgentActionRequest` contract for the RCT family
- mapping from external agent identity to accountable principal and delegation
- device-bound identity or attestation metadata on the request path
- deterministic response contract with:
  - disposition
  - explanation
  - required approvals
  - trust gaps
  - minted artifacts
- reference adapter or SDK for one current agent platform
- one reference commerce-side adapter for the canonical transaction flow
- gateway support for intent reservation and closure acknowledgement
- edge-to-cloud synchronization contract for Dockerized edge nodes running the
  restricted-transfer boundary
- reconnection and reconciliation rules for restricted transfers under
  intermittent connectivity
- deterministic mapping from gateway request -> decision -> forensic block ->
  replay lookup
- simulated multi-agent handshake between:
  - buyer-side agent
  - seller-side or inventory-side adapter
  - SeedCore authority boundary
- first red-team validation in simulation:
  - coordinate tamper attempt should deny or quarantine
  - stolen session replay should be attributable in forensic logs

### Exit criteria

- one external agent platform can request an RCT action end to end
- SeedCore no longer requires callers to understand internal coordinator
  semantics
- denial, quarantine, and escalation behavior are externally legible
- the edge node can safely reconcile local custody outcomes after reconnect
- the digital transaction and physical verification states can be correlated by
  a single audit id or equivalent forensic join key

### Recommended discipline

- support one platform well
- avoid trying to support every agent framework at once
- support one commerce path well before generalizing to every marketplace

## Q4 2026: Close The Loop, Red-Team It, And Package The Pilot

This quarter should turn the runtime into a buyer- and operator-legible pilot.

### Primary objective

- prove end-to-end governed action with independent verification and adversarial
  resilience

### Must-ship items

- evidence-required closure for selected transfer actions
- authoritative twin settlement integrated into the runtime story
- sensor-grounded closure using Jetson-captured localized telemetry
- operator verification surface ready for live usage
- partner-facing proof flow for post-hoc verification
- one design-partner simulation or controlled pilot package
- Unitree B2 included as the physical custodian / courier actor in the pilot
- scripted zero-trust physical handover demonstrating policy `allow` / `deny`
  against real-time edge telemetry
- audit-trail view showing request, transaction trail, and physical replay side
  by side
- lightweight self-contained verification package that does not require the full
  SeedCore runtime stack
- full red-team package for the canonical workflow:
  - man-in-the-middle coordinate redirect
  - authority leak / replay injection
  - physical double-spend attempt
- operating metrics for:
  - allow / deny / quarantine / escalate rates
  - latency profile
  - parity stability
  - evidence closure rate
  - replay verification success
  - edge reconciliation time
  - time to proof
  - forensic block completeness rate
  - physical vs digital fingerprint match rate

### Exit criteria

- a third party can inspect a completed governed transfer
- a real or simulated external agent can initiate the flow
- the proof surface explains the final result without requiring source-code
  access
- the physical handover path is demonstrated with hardware in the loop, not
  only mocked software components
- the red-team drills produce deterministic quarantine, deny, or replay-visible
  findings instead of ambiguous failure

## Deliverable Map

The delivery order should stay strict.

### Layer 1: Runtime correctness

- hot-path semantics
- parity evidence
- rollback and quarantine behavior

### Layer 2: Product contract and delegated authority

- external request schema
- identity / delegation binding
- transaction-specific authority scope
- response contract

### Layer 3: Closure, forensic blocks, and proof

- evidence ingestion
- settlement
- replay and verification consistency
- edge-to-cloud reconciliation
- forensic block packaging

### Layer 4: Pilot packaging

- runbook
- deployment path
- operator flow
- partner proof flow
- red-team drill package
- physical handover packaging

Do not invert this order.

## Metrics That Actually Matter

The year should be measured with a small set of metrics.

### Runtime metrics

- hot-path p50 / p95 / p99 latency
- shadow parity rate
- mismatch root-cause closure time
- dependency freshness violations
- auto-quarantine rate
- evidence payload ingestion p50 / p95 latency
- evidence payload size distribution
- forensic block assembly latency

### Workflow metrics

- RCT allow / deny / quarantine / escalate distribution
- approval completeness rate
- evidence closure rate
- replay verification success rate
- edge node reconciliation time after reconnect
- twin-settlement completion time after governed action close
- physical vs digital fingerprint match rate
- red-team drill detection rate

### Product metrics

- time to integrate one external agent
- operator time to explain a decision
- time to investigate a failed transfer
- number of required manual trust-ops steps per transfer
- time for a third-party verifier to validate one exported transfer package
- time to reconstruct one failed handshake from replay artifacts only

## Ownership Model

Even if the team is small, the work should be thought of as four explicit
ownership lanes:

### Runtime lane

- hot path
- policy evaluation
- approval truth
- decision contracts

### Trust lane

- signer provenance
- evidence integrity
- replay verification
- settlement correctness
- forensic block schema and chain integrity

### Product lane

- verification surface
- external API contract
- integration guides
- operator runbooks

### Pilot lane

- demo package
- design-partner workflow
- onboarding path
- operational metrics and sign-off
- hardware-in-the-loop validation
- adversarial drill validation

This helps prevent "everything is infra" drift.

## 2026 Risks

The main risks are strategic, not only technical.

### Risk 1: Becoming too broad

Symptom:

- too many workflows, too many surfaces, too much generic autonomy language

Counter:

- keep `Restricted Custody Transfer` as the must-win workflow for the full year

### Risk 2: Staying too internal

Symptom:

- excellent runtime internals, but no external contract that a real agent
  platform can use

Counter:

- ship the Agent Action Gateway in Q3 even if it is narrow

### Risk 3: Over-optimizing before productizing

Symptom:

- spending large amounts of time on generalized performance or architecture
  cleanup before the integration and proof story is product-ready

Counter:

- optimize only where it is required for hot-path promotion or pilot readiness

### Risk 4: Letting proof quality drift

Symptom:

- a good policy engine but weak replay, settlement, or evidence closure

Counter:

- treat verification and evidence as first-class release gates

### Risk 5: The edge-to-cloud reality gap

Symptom:

- the governed transfer works in centralized simulation but breaks under
  intermittent networking, sensor noise, or physical hardware latency

Counter:

- require Q2 hot-path testing to include degraded edge-network conditions
- require Q4 pilot evidence to come from actual hardware in the loop

### Risk 6: Verification package dependency bloat

Symptom:

- a third party needs too much internal SeedCore infrastructure just to verify
  one completed transfer

Counter:

- keep the Q4 verification package lightweight and self-contained
- rely only on standard cryptographic primitives and exported proof artifacts,
  not the full Kubernetes / Ray runtime

### Risk 7: Split-brain forensic schemas

Symptom:

- one internal transport schema and one external audit schema diverge before the
  first pilot is stable

Counter:

- freeze one canonical replay/export contract first
- add transport-specific encodings only after the external field set stabilizes

## 2026 Decision Rule

When choosing between two tasks, prefer the one that makes this sentence more
true:

> An external agent can request a restricted transfer through SeedCore,
> SeedCore can govern the action safely across the cloud and edge boundary, and
> a third party can verify both the digital transaction and the physical outcome
> afterward.

If a task does not strengthen that sentence, it is probably not on the critical
path.

## End State For This Year

SeedCore has had a successful 2026 if, by year end, it can honestly claim:

- we have one governed high-trust workflow that is externally integrable
- we have one operator-grade proof surface for it
- we can prove both authorization and post-action closure
- we can show denial, quarantine, and escalation as strengths, not edge cases
- we can demonstrate the workflow with physical hardware and edge telemetry in
  the loop
- we can replay the workflow as a coherent forensic chain after the fact
- we occupy a necessary layer between frontier agents and real-world execution

That is enough to matter.

## 2027 Continuation

After 2026 closure, the next-stage high-vertical deployment direction is
tracked in:

- [seedcore_2027_high_vertical_direction.md](/Users/ningli/project/seedcore/docs/development/seedcore_2027_high_vertical_direction.md)

This continuation keeps the same trust-boundary model while adding staged
hardware-bound execution identity for IGX/Jetson edge deployments.
