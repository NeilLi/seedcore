# North Star: The Genuine Environment for Autonomous Trade

## Status: Architectural Reference with Execution Update

- **Version:** 1.2.0
- **Last updated:** 2026-06-20
- **Context:** This document represents the "North Star" of the SeedCore architecture: a zero-trust autonomous environment where physical actions are converted into replay-verifiable digital truth.

---

## Overview

The SeedCore runtime is designed to facilitate a "Genuine Environment" for
autonomous trade. In this vision, human oversight shifts from "watching the
work" to "setting the policy." Once policy is frozen in the
**Authorization PKG**, AI agents and robots can transact on behalf of humans
with bounded authority, backed by a runtime that ensures physical-to-digital
settlement is irrefutable and replay-verifiable.

This environment is still built on four technical pillars, but it should now be
read in two layers:

- `North star`: the durable target shape SeedCore is trying to become
- `Execution update`: what is already implemented in the current Restricted
Custody Transfer (RCT) trust slice, plus the next credible extension path

Architecturally, this should be shown as a three-layer placement:

- top (`Brain/Intent`): humans and AI agents propose actions
- bottom (`Sandboxes/Reality`): economic and physical systems emit evidence
- center (`SeedCore`): PDP + forensic evidence integrator + replay authority

The key design rule remains:

- brains may propose
- reality must attest
- SeedCore decides whether the transition becomes admissible digital truth

---

## 1. The Persistent Twin & Settlement Track

The **Persistent Twin Service** (see `src/seedcore/ops/digital_twin/`) acts as
the "ledger of record" for the environment, moving beyond simple database state
into a verifiable history.

- **Authoritative State:** Twins maintain append-only history
  (`digital_twin_history`) and strict `state_version`. Digital twin mutation
  history should gradually become state-root-capable to verify transaction
  sequences mathematically.
- **Replayable Evidence Bundles:** Simple "signed receipts" give way to
  replayable evidence bundles. Where a workflow opts into stricter
  governed-transition semantics, the replay contract carries lightweight
  `prior_state_binding`, `result_state_binding`, and `causal_parent_refs` so
  historical state and direct causal influence remain inspectable without
  claiming a full authenticated state-root store.
- **Causality and Freshness Tokens:** Zanzibar-style causality tokens or SpiceDB
  ZedTokens ("zookies") shape the context-supply target. When a policy profile
  requires freshness proof, the request package must show that the local context
  view is at least as fresh as the relevant token before the PDP can mint
  execution authority.
- **Settlement Loop:** Physical delivery does not trigger an immediate final
  state update. Instead, the twin enters a `PENDING` or otherwise provisional
  authority state until evidence converges.
- **Promotion to Authoritative:** State is promoted to `AUTHORITATIVE` only
  after the runtime ingests a valid `EvidenceBundle` and verifies that the
  executing `node_id` held the necessary authority at the time of execution.

Implemented now:

- persisted authoritative twin state, twin history, and versioning are part of
  the active runtime shape
- twin-event journaling is available as a deterministic verification trigger in
  the current RCT slice
- downstream fail-closed behavior is now wired to authoritative verifier-driven
  twin state, not just a read-side projection
- the evidence bundle builder, RCT replay verifier, and `ReplayService` now carry
  and surface `prior_state_binding`, `result_state_binding`, and
  `causal_parent_refs` for upgraded records; strict enforcement remains bounded
  by the `SEEDCORE_RCT_REPLAY_STRICT_STATE_TRANSITION_FIELDS` canary and the
  workflow opt-in hint

Next extension:

- introduce explicit settlement classes beyond the current RCT path so that
  delivery, custody change, rollback, and remediation each have first-class
  replay semantics
- promote twin closure from "single workflow completion" toward
  "lifecycle-grade settlement," where commerce, custody, and evidence state can
  reconcile across multiple handoffs without reopening historical truth

---

## 2. Physical-to-Digital Delivery (The Evidence Loop)

The transition from a physical task to a digital truth is governed by a
"Certified Frame" of the event. This loop ensures that every movement in the
real world has a corresponding, cryptographically anchored digital proof.

- **ActionIntent:** Every agent or robot plan is validated as a governed intent
  before any movement or transaction occurs.
- **ExecutionToken:** Signed by the PDP, this authorization token remains the
  bounded software authority artifact. For high-consequence physical execution,
  the target actuator-unlock path also binds software authority to
  **hardware-anchored signed telemetry** such as hardware signer, asset anchor,
  and approved zone evidence.
- **Two-Profile Edge Strategy (ADR 0003):** Edge hardware is divided into two
  distinct profiles. Jetson-class nodes serve as the prototype and validation
  lane, whereas **NVIDIA IGX Thor / T5000** is the target trusted-edge profile
  for production industrial and robotics boundary nodes once
  hardware-attestation, software-lane identity, and fail-closed operations are
  provisioned and replay-visible.
- **Logistics Optimization Boundary:** Optimization backends (such as NVIDIA
  cuOpt) are strictly **optional sidecars** used for route planning, schedule
  generation, and dispatch. They provide purely advisory candidate plans and
  must never act as a source of authority, truth, or evidence closure.
- **EvidenceBundle:** Post-delivery, the system captures a forensic package
  containing:
  - telemetry: GPS, vision, and sensor data
  - transition receipt: a cryptographically sealed proof of execution
  - trust anchors: TPM 2.0 or KMS-backed anchors to prevent spoofing or
    repudiation

Forensic handshake rule:

- economic identifiers, such as order or transaction IDs, and physical
telemetry fingerprints, such as point-cloud, trajectory, or motor-effort
digests, must converge under one replayable runtime chain before closure is
considered admissible

Implemented now:

- the governed closure flow persists evidence artifacts on the RCT path
- signed edge telemetry references are now part of the closure/evidence
contract, with strict asset binding and ordered hash contribution to
`physical_presence_hash`
- forensic materialization now preserves those telemetry references in a
replayable operator-facing shape

Next extension:

- move from "telemetry present" to "telemetry admissibility grades" so the
runtime can distinguish minimal closure proof from high-confidence physical
presence proof
- standardize evidence-bundle export and re-import for rollback, quarantine,
and third-party attestation workflows
- widen the physical fingerprint model from single snapshots toward richer
trajectory, force, and device-attestation digests without widening the frozen
replay contract

---

## 3. Autonomous Verification (Machine-to-Machine Trust)

In a high-velocity autonomous environment, verification cannot be a human-only
task. It must be a first-class, machine-native capability.

- **Verifier role:** Specialized `RESULT_VERIFIER` workers or agents monitor the admissibility chain.
- **Kernel-Level Verification:** They use the Rust `seedcore-verify` kernel to validate replay, signature provenance, policy snapshot alignment, and proof integrity.
- **Fail-Closed Twin Mutation:** If a verifier detects any mismatch (such as a broken seal, signature drift, or trust-anchor failure), it immediately triggers an authoritative digital twin mutation to `verification_failed` or `verification_quarantined` and applies a runtime lockout. Downstream transitions and evaluations are halted automatically without automatic unquarantine loops; clearance requires manual or policy-admitted operator remediation.
- **Measurable Split Triggers (ADR 0004):** The verifier currently runs embedded in the Coordinator service via journal polling. Any move to a dedicated `seedcore-result-verifier` service should be governed by recorded coordinator saturation, verifier watermark lag, blast-radius isolation needs, or regulatory network-isolation requirements rather than speculative platform refactoring.

Implemented now:

- `RESULT_VERIFIER` P0 is live for the current RCT trust slice
- intake currently polls `digital_twin_event_journal`, persists idempotent
verifier jobs and outcomes, and reuses the same replay-chain verification
path as the runtime replay surface
- verifier mismatches now write authoritative `verification_failed` or
`verification_quarantined` mutations and apply fail-closed lockout markers
that downstream evaluation and settlement handoff actively deny against

Current constraints:

- scope is intentionally narrow: RCT only
- trigger ownership is currently database-journal polling, not Kafka or event
bus native
- unquarantine remains operator-controlled; there is no automatic clearance
loop

Next extension:

- split verifier intake and worker ownership more cleanly so the subsystem can
move out of the coordinator when scale or isolation requires it
- add event-bus triggers only when the journal-trigger path becomes a real
bottleneck, not as speculative platform work
- formalize verifier remediation contracts so quarantine clearance, replay
export, and runbook lookup become one coherent trust workflow

---

## 4. Delegated Authority for Transactions

To enable machines to transact on behalf of humans, SeedCore implements a
root-of-trust based on delegated authority.

- **Graph Split (Decision vs. Enrichment):** The Authorization Policy Knowledge Graph (PKG) is split into two layers. Hot-path authorization evaluations target a benchmark-gated, in-memory **Decision Graph** shape so decisions stay synchronous and fast. In contrast, deep provenance metadata, analytics, and LLM-assisted explanations are deferred to an offline, asynchronous **Enrichment Graph**.
- **Path-Centric Traversal:** Authority evaluation moves beyond basic permission-to-role mappings to enforce explicit, physical delegation paths. Traversal resolves structural chains (e.g., `Principal -> Attested Device -> Organization -> Approved Facility -> Controlled Zone -> Target Asset`) to ensure the agent has explicit clearance for the specific boundary.
- **First-Mile Identity Ingress:** **Google Identity-Aware Proxy (IAP)** functions as the first-mile identity gate for operator, developer, and administrative console surfaces, keeping them strictly isolated from public-facing, zero-trust verification endpoints. Programmatic API and downstream automation calls must authenticate using workload-level identities (SPIFFE/SPIRE) or proof-of-possession tokens (like DPoP) instead of ambient human credentials.
- **Owner Twin Delegation:** Digital twins include a delegation envelope (`owner_id`, `delegations`) that defines which agents possess the authority to move a custody-controlled good or sign for a delivery.
- **Multi-Party Governance:** For high-value trades, the environment should enforce dual authorization. Two separate agents, such as a trade agent and a compliance agent, must co-sign a `TransferApprovalEnvelope` before the physical-to-digital loop can initialize.

Implemented now:

- the external action boundary is converging around a strict
`AgentActionGateway` request contract
- reference adapter work now exists for an agent-facing boundary and a narrow
commerce-side adapter for the canonical transaction flow
- the active wedge already proves that business prerequisites, authority
binding, and replay lookup can correlate through one governed workflow chain

Next extension:

- make the delegation envelope more explicit about time-bounded authority,
revocation cause, and approval lineage so machine-to-machine handoff is
inspectable without replaying every artifact manually
- productize dual-authorization as a reusable policy pattern rather than an
RCT-only special case
- add a stable transaction-to-asset reconciliation layer so economic truth and
custody truth can remain independently auditable while still settling
together

---

## 5. Supporting Planes Required for the North Star

The autonomous trade environment should stay narrow at its trust core, but it
still depends on surrounding support planes that now need to be named
explicitly.

### 5.1 Enterprise RAG as Governed Evidence

Memory and retrieval planes are reframed as **governed evidence acquisition** systems (ADR 0008 & ADR 0009). Enterprise RAG must never act as a permissive, direct-to-agent chatbot or bypass the PDP. It functions as an evidence-gathering sidecar that must satisfy a strict **Two-Stage Authorization Boundary**:
1. **Coarse Candidate Filtering:** Retrieve potential context elements based on query semantics.
2. **Fine-Grained PDP Chunk Checks:** Filter every retrieved chunk against active policy gates. Chunks that fail this check are blocked and must never be exposed to the LLM context, prompt builders, or operator surfaces.

*   Memory exists strictly to support time-bounded context, scoped retrieval, and operator legibility around the trust runtime.
*   Memory does not replace the PDP, define admissibility, or act as an ambient threat-intelligence layer.
*   The current runtime provides isolated caller-facing `WorkingMemory`, `SemanticMemory`, and `IncidentMemory` contracts; governed RAG adds the separate fine-grained retrieval authorization boundary before chunks can become evidence or model context.

North-star implication:

- autonomous trade needs bounded context, but only as a support plane around a
deterministic decision and evidence core
- for an implementation-oriented flow that turns retrieved memory into a
  bounded context envelope before the PDP, see
  [Trading Memory Admissibility Flow](./trading_memory_admissibility_flow.md)

### 5.2 Operator and External Read Surfaces

Autonomous trade will not be trusted if the proof can only be understood by the
runtime itself.

- operator verification surfaces, replay lookup, queue views, and runbook links
are therefore part of the environment, not optional UI garnish
- read-only external bundles, including the current minimal Gemini-visible
bundle, are the right pattern: narrow, contract-driven, and explicitly unable
to mutate authority or closure state

North-star implication:

- every machine-verifiable truth should also have a human-legible, read-only
proof path

---

## Conclusion: The Runtime as a "Trust Slice"

The SeedCore runtime functions as a trust slice for autonomous operations. By combining the optimized **Decision Graph** that defines what *can* happen with the **Evidence Loop** that proves what *did* happen, it creates an environment where autonomous trade is not just possible, but replay-verifiable and operationally governable.

Every physical handoff becomes a candidate digital truth. It is admitted only when policy, authority lineage, and evidence converge.

### Cluster Service Posture

In production, the runtime enforces a **synchronous and stateless PDP** (ADR 0001). At decision time, the PDP must not perform external network calls or slow polling; it should evaluate pinned request packages against near-local read models fed by event-driven context propagation.

To reduce hot-path latency without changing the authority model, the cluster service may adopt benchmarked internal acceleration layers:
*   **Dragonfly DB / Redis RESP3** client-side caching for in-memory ledger and token revocation lookups.
*   **Protocol Buffers / FlatBuffers** as internal transport mirrors once field stability, replay equivalence, and benchmark evidence justify them; JSON-LD remains the external replay and audit surface.

The trust slice integrates with the surrounding cluster components as follows:

| Component              | Trust-slice interaction                                             |
| ---------------------- | ------------------------------------------------------------------- |
| Confluent Kafka        | Transport for intent, telemetry, and policy outcome streams         |
| Ray / Kubernetes       | Distributed compute for compiled decision graph hot-path evaluation |
| Redis / Dragonfly      | Revocation, client-side caching, and emergency cutoff propagation   |
| Cloud KMS              | Hardware-backed signing for receipts and transition artifacts       |
| Durable forensic store | Long-term persistence for signed forensic blocks and replay trails  |


For a **local** phased schedule, including broker compose, topics, and producer
order, see [local_kafka_streams_schedule.md](local_kafka_streams_schedule.md).

Near-term production posture extension:

- keep the hot path synchronous and deterministic at decision time
- keep verification and replay outputs durable and queryable
- use event transport and distributed compute only where they reduce
operational risk or support clear scale or isolation goals
- avoid widening the runtime into a generic agent platform before the trust
slice is operationally credible

Final-authority invariant:

- if policy, authority lineage, or cryptographic evidence convergence fails,
SeedCore refuses to attest the forensic handshake
