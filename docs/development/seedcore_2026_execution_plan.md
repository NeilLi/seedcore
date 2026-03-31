# SeedCore 2026 Execution Plan

Date: 2026-03-31
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

This is not a speculative "future platform" plan. It is a wedge-first execution
plan.

## 2026 Objective

The 2026 objective should be:

**Make SeedCore the governed action and proof layer for one high-trust agent
workflow that can be piloted credibly before year end.**

In practice, that means:

- one canonical workflow
- one external agent boundary
- one physical custody boundary
- one runtime decision contract
- one evidence loop
- one verification surface

Everything else is secondary.

## Product Definition For 2026

The product to ship this year is:

**Agent-Governed Restricted Custody Transfer**

User-level promise:

- an external agent requests a restricted transfer
- SeedCore validates authority and policy
- SeedCore returns `allow`, `deny`, `quarantine`, or `escalate`
- if allowed, SeedCore mints bounded execution authority
- the action closes with sensor-grounded, replayable evidence
- operators and partners can verify the result afterward

This should be treated as the canonical 2026 package.

For 2026, that package should be grounded in one concrete physical story:

- the governed good is physically handled during transfer
- the edge evidence source is a Jetson AGX Orin-class node
- the Q4 pilot package scopes a Unitree B2-class robot as the physical courier
  or custodian actor
- the digital twin mutation is tied to the exact transfer event, not only the
  policy decision

## Execution Principles

Every 2026 deliverable should improve at least one of these:

- authority correctness
- runtime safety
- evidence integrity
- operator trust
- partner verifiability
- external agent integration

If a task does not improve one of those directly for `Restricted Custody
Transfer`, it is sidecar.

## Workstreams

The year should be run as five connected workstreams.

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

Primary repo anchors:

- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [hot_path_enforcement_promotion_contract.md](/Users/ningli/project/seedcore/docs/development/hot_path_enforcement_promotion_contract.md)

### Workstream 2: Agent Action Gateway

Goal:

- make SeedCore callable by an external agent through a clean product boundary

Required outcomes:

- one stable request schema for agent-originated actions
- identity and delegated-authority binding for agent principals
- narrow, deterministic error contracts
- one reference adapter for a current agent platform

This is the workstream that turns SeedCore from "deep system" into "integrable
product".

### Workstream 3: Evidence Closure And Settlement

Goal:

- prove not only that the action was authorized, but that the governed outcome
  actually happened

Required outcomes:

- evidence ingestion required for selected allowed actions
- sensor-grounded evidence schemas for cryptographically signed edge telemetry
- authoritative twin settlement on completion
- atomic linkage between twin-state mutation and localized physical evidence:
  - location
  - environmental readings
  - hardware health
- audit-chain consistency across runtime, replay, and verification
- explicit failure handling for missing or invalid evidence

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
- runbooks for lookup, exception handling, and investigation

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

The Q4 pilot package should be explicit about the hardware story:

- the Unitree B2 is the scoped physical actor for custody movement or handover
- the Jetson edge node is the scoped telemetry and local execution boundary
- the pilot demonstrates allow / deny behavior using both digital credentials
  and real-time physical telemetry
- the operator surface shows both proof artifacts and the twin state captured at
  custody transfer time

## Quarter Plan

## Q2 2026: Make The Wedge Operable

This quarter should focus on hardening what already exists.

### Primary objective

- convert the current RCT sign-off wedge into an operable, repeatable trust
  runtime slice

### Must-ship items

- freeze and version the current runtime-up RCT sign-off bundle
- implement runtime-selectable hot-path mode semantics
- persist parity events and build `1,000`-run exportable evidence
- instrument hot-path observability consistently across Kubernetes and host-mode
  environments
- add graph freshness and dependency-based auto-quarantine
- add dedicated hot-path benchmark harness coverage for concurrent load
- promote runtime matrix capture and replay verification into CI / host gates
- define the deployment topology used by CI / host gates and benchmark the Ray
  coordination path under that topology
- include simulated edge-network conditions in hot-path testing:
  - intermittent connectivity
  - sensor jitter / noise
  - edge hardware latency

### Exit criteria

- sign-off evidence is repeatable, not one-off
- hot-path observability is operator-grade
- `shadow` mode becomes promotion-quality evidence
- the runtime is stable enough to expose as a real integration boundary
- concurrency results reflect real coordination behavior, not only local happy
  path benchmarks

### Non-goals

- no broad product rebrand
- no general multi-workflow expansion
- no full autonomous robotics stack work

## Q3 2026: Productize The Agent Boundary

This quarter should make SeedCore usable by external agent systems.

### Primary objective

- define the cleanest possible external contract for governed action requests

### Must-ship items

- stable `AgentActionRequest` contract for the RCT family
- mapping from external agent identity to accountable principal and delegation
- deterministic response contract with:
  - disposition
  - explanation
  - required approvals
  - trust gaps
  - minted artifacts
- reference adapter or SDK for one current agent platform
- developer integration guide and sample flow
- edge-to-cloud synchronization contract for Dockerized edge nodes running the
  restricted-transfer boundary
- reconnection and reconciliation rules for restricted transfers under
  intermittent connectivity

### Exit criteria

- one external agent platform can request an RCT action end to end
- SeedCore no longer requires callers to understand internal coordinator
  semantics
- denial, quarantine, and escalation behavior are externally legible
- the edge node can safely reconcile local custody outcomes after reconnect

### Recommended discipline

- support one platform well
- avoid trying to support every agent framework at once

## Q4 2026: Close The Loop And Package The Pilot

This quarter should turn the runtime into a buyer- and operator-legible pilot.

### Primary objective

- prove end-to-end governed action with independent verification

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
- lightweight self-contained verification package that does not require the full
  SeedCore runtime stack
- operating metrics for:
  - allow / deny / quarantine / escalate rates
  - latency profile
  - parity stability
  - evidence closure rate
  - replay verification success
  - edge reconciliation time
  - time to proof

### Exit criteria

- a third party can inspect a completed governed transfer
- a real or simulated external agent can initiate the flow
- the proof surface explains the final result without requiring source-code
  access
- the physical handover path is demonstrated with hardware in the loop, not
  only mocked software components

## Deliverable Map

The delivery order should stay strict.

### Layer 1: Runtime correctness

- hot-path semantics
- parity evidence
- rollback and quarantine behavior

### Layer 2: Product contract

- external request schema
- identity / delegation binding
- response contract

### Layer 3: Closure and proof

- evidence ingestion
- settlement
- replay and verification consistency
- edge-to-cloud reconciliation

### Layer 4: Pilot packaging

- runbook
- deployment path
- operator flow
- partner proof flow
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

### Workflow metrics

- RCT allow / deny / quarantine / escalate distribution
- approval completeness rate
- evidence closure rate
- replay verification success rate
- edge node reconciliation time after reconnect
- twin-settlement completion time after governed action close

### Product metrics

- time to integrate one external agent
- operator time to explain a decision
- time to investigate a failed transfer
- number of required manual trust-ops steps per transfer
- time for a third-party verifier to validate one exported transfer package

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

## 2026 Decision Rule

When choosing between two tasks, prefer the one that makes this sentence more
true:

> An external agent can request a restricted transfer through SeedCore, SeedCore
> can govern the action safely across the cloud and edge boundary, and a third
> party can verify what happened afterward.

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
- we occupy a necessary layer between frontier agents and real-world execution

That is enough to matter.
