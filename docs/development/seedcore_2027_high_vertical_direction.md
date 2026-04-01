# SeedCore 2027 Significant Direction

Date: 2026-04-01  
Status: Working direction for 2027 staging

## Purpose

Define the 2027 expansion path after 2026 closure, focused on high-trust
vertical deployments where physical execution and forensic accountability must
be provable under enterprise operating constraints.

This document assumes 2026 remains the single-workflow proving year:

- one workflow: `Restricted Custody Transfer`
- one proof surface: governed receipts + replay-verifiable chain
- one operator status surface
- one asset-centric forensic view

## 2027 North Star

The 2027 objective is:

**Move SeedCore from a credible wedge to a deployable trust substrate for
high-regulation and high-consequence vertical environments.**

Practical meaning:

- SeedCore remains the governed decision + forensic replay boundary
- IGX Thor or Jetson-class nodes become trusted physical execution boundaries
- authority is bound to exact hardware identity, not just role or node label
- closure requires cryptographic evidence convergence across cloud and edge

## Target Verticals

Primary 2027 vertical focus should remain narrow and enterprise-legible:

- industrial robotics and controlled warehouse transfer
- medical or lab-adjacent controlled movement environments
- regulated custody-sensitive enterprise logistics

## Three-Plane Architecture

### Plane A: Cognitive / Intent Plane

- cloud agent (for example Gemini-class or equivalent)
- commerce lookup and workflow request construction
- policy preflight calls into SeedCore

Rule:

- this plane does not directly command robot actuation or edge control.

### Plane B: Trust Plane (SeedCore)

- Agent Action Gateway
- approval envelope and scope resolution
- hot-path policy evaluation
- decision artifacts and execution-token minting
- forensic block assembly
- replay / verification surfaces

Rule:

- this plane decides whether an action is admissible and under what exact scope.

### Plane C: Physical Execution Plane (IGX Thor / Jetson)

- perception and control stack
- local telemetry processing
- evidence packaging and signing
- closure callback to SeedCore

Rule:

- execution occurs only with transaction-specific authority issued by SeedCore.

## Operational Role by Substrate (2027 Baseline)

| Substrate | Operational role |
| --- | --- |
| Confluent Kafka | Event backbone for intent, telemetry, and policy outcome streams |
| Ray + Kubernetes | Distributed execution for compiled authz graph and shard-aware hot-path routing |
| Redis | Token revocation and emergency cutoff propagation |
| Cloud KMS | Hardware-backed signing for policy and transition artifacts |
| Durable forensic store | Long-lived persistence for signed forensic blocks and replay evidence |

## Edge Trust Binding Model

2027 should require explicit hardware-bound principal registration.

Minimum enrollment fields:

- `node_id`
- `hardware_fingerprint_id`
- `public_key_fingerprint`
- `attestation_type`
- `key_ref`
- `device_profile`
- `allowed_capabilities`
- `facility_ref`
- `zone_scope`

At allow-time, authority must be scoped to:

- workflow instance
- asset/product identity
- from/to zone and coordinate scope
- exact node fingerprint
- strict validity window

Invariant:

- the action is approved for this specific hardware identity and scope, not
  approved in the abstract.

## Forensic Handshake v2 (Cloud + Edge)

2027 should operationalize a six-step handshake:

1. Intent creation and persisted approval/scope resolution
2. Decision and scoped authority minting
3. Edge execution guard validation
4. Signed edge evidence capture
5. Forensic block assembly in SeedCore
6. Closure/settlement release only on full evidence convergence

Canonical convergence set:

- economic hash
- physical presence hash
- reasoning hash
- actuator hash
- device identity hash
- authority scope hash

## SeedCore Edge Trust Adapter v0.1

The first 2027 bridge deliverable should be a thin edge adapter for IGX/Jetson:

- validates scoped execution token from SeedCore
- verifies freshness and node/scope match before actuation
- signs local telemetry/evidence using device identity
- emits canonical evidence bundle to SeedCore closure path

This adapter is the shortest path from architecture claim to deployable trust
behavior.

## 2027 Stage Plan

## Stage 1 (Q1): Hardware-Bound Identity and Enrollment

Outcomes:

- edge principal registration contract frozen
- IGX/Jetson node enrollment flow implemented
- attestation/profile verification integrated in trust plane

Exit criteria:

- SeedCore can reject any closure evidence from non-enrolled or mismatched
  node identities.

## Stage 2 (Q2): Scoped Authority and Edge Guard Enforcement

Outcomes:

- transaction-specific authority scope includes node fingerprint + coordinate
- edge trust adapter validates authority before actuation
- replay of token on unauthorized node is blocked

Exit criteria:

- replay and cross-node token misuse tests fail closed by design.

## Stage 3 (Q3): Forensic Handshake v2 in Live Loop

Outcomes:

- closure requires six-field convergence set
- forensic block schema includes device + scope hash classes
- verification surfaces expose convergence and signer provenance clearly

Exit criteria:

- operators can prove which node acted, under which scope, with matching
  evidence chain for allow and non-allow outcomes.

## Stage 4 (Q4): High-Vertical Pilot Packaging

Outcomes:

- one high-vertical deployment profile (industrial or medical-adjacent)
- runbooks for trust operations, quarantine, and incident replay
- partner-facing verification package for approved stakeholders

Exit criteria:

- repeatable end-to-end demo: external request -> SeedCore decision ->
  IGX/Jetson execution -> signed evidence -> verified replay.

## 2027 Decision Rule

When prioritizing work in 2027, choose tasks that make this statement stronger:

> SeedCore can govern high-consequence edge execution with hardware-bound
> authority, and prove outcome integrity later through a replayable forensic
> chain that survives adversarial review.

If a task does not reinforce that statement, it is likely sidecar.
