# Current Next Steps

This document tracks the next-stage priorities for SeedCore based on the
repository as it exists today.

It is intentionally written to balance two things:

- the strong baseline SeedCore already has
- the practical, wedge-first roadmap needed to make that baseline
  enterprise-credible

The goal is not to describe a perfect future state all at once. The goal is to
define the next 12-18 months in a way that is ambitious, believable, and
product-relevant.

## Status Update (2026-04-02)

Latest repo-aligned critical-path status:

- `VerificationSurfaceProjection` freeze pass is implemented for the Q2
  verification API and UI surfaces, including explicit versioned projection
  models and deterministic business-state mapping with `pending_approval`.
- verification service contract namespace is now `/api/v1/verification/*`
  (legacy `/api/v1/transfers/*` and `/api/v1/assets/forensics` paths are
  retired in the TS verification service layer).
- `AgentActionGateway` request boundary is now strict and externally stable for
  `seedcore.agent_action_gateway.v1`, with required identity/scope/hardware
  fields, deterministic schema invariants, canonical request hashing, and 24h+
  idempotency retention.
- Screen 2 side-by-side audit trail is now contract-driven (`request/authority`
  + `decision/artifacts` + `physical/closure`) and correlated through one
  workflow join key.
- Screen 1 queue surface is now implemented with filterable trust buckets and
  readiness/blocker views (`/api/v1/verification/transfers/queue` + operator
  `/queue`).
- Screen 4 replay/verification detail is now implemented through
  `seedcore.verification_detail.v1` at
  `/api/v1/verification/workflows/{workflow_id}/verification-detail`.
- hot-path semantics have been hardened for production gating:
  strict parity threshold (`1000/1000`), dependency and latency gates, durable
  parity evidence persistence, and rollback triggers.
- hot-path status now emits additive observability signals for operators and
  scraping (`alert_level`, structured alerts, gauges, optional deployment role)
  to support Kubernetes/Ray operational wiring.
- first forensic-block JSON-LD contract freeze pass is implemented with schema
  artifacts, strict runtime validation, explicit `forensic_block_id`, and
  closure/materialization consistency checks.
- host benchmark harness now supports configurable request delay and jitter
  (`scripts/host/benchmark_rct_hot_path.py`) to simulate edge-ish timing noise
  during load evidence collection.

## Why This Lives Outside The Root README

The root README should explain what SeedCore is, how it runs, and why the
architecture matters.

The exact next-stage plan changes faster than the high-level architecture
summary. As verification improves and the runtime hardens, this document can be
updated without turning the root README into a moving target.

## Baseline That Already Exists

SeedCore is no longer a conceptual architecture. The repository already
contains a functioning governed execution baseline.

The following should be treated as present, not future work:

- short-lived execution tokens with TTL enforcement
- Redis-backed token revocation and HAL emergency cutoff controls
- HAL transition receipts with verification paths
- evidence bundles that bind policy, execution, and transition artifacts into
  replayable closure
- asset fingerprint capture, signed HAL capture envelopes, and replay-friendly
  evidence models
- public replay, trust-page, and verification workflow surfaces
- DID, delegation, and signed-intent support on the external surface
- TPM-backed and KMS-backed signer hardening paths already exercised in repo
- staged PKG authz-graph rollout through Phase 5, including:
  - decision-centric ontology
  - multihop authority paths
  - explanation payloads such as `matched_policy_refs` and
    `missing_prerequisites`
  - decision-graph vs enrichment-graph split
  - shard-aware Ray authz cache routing

This means the next stage is not about adding more concepts for their own sake.
It is about converting the existing governed execution baseline into a
product-grade trust runtime for high-trust, multi-party environments.

## Strategic Objective

The right objective for the next stage is:

**Make SeedCore the most credible runtime for irrefutable, multi-party governed
execution and forensic replay in high-trust supply-chain and
asset-sensitive environments.**

That is a better objective than "solve all trusted autonomy problems" because
it forces the roadmap to stay wedge-first, operational, and commercially
legible.

This objective is anchored to the
[North Star: Autonomous Trade Environment](north_star_autonomous_trade_environment.md),
which defines the runtime as a "Trust Slice" where human oversight is shifted
from monitoring execution to defining policy.

The guiding discipline for this stage is:

- one wedge: high-trust, multi-party supply chain and asset transfer
- one proof surface: governed receipts and replayable verification
- one scaling logic: a compiled hot-path decision graph with cryptographic trust
  anchors
- one design lens: SeedCore as a verifiable agentic ledger, not only a
  controller

## Updated Design Lens: Verifiable Agentic Ledger

The strongest way to describe the next-stage architecture is:

**SeedCore should behave like a black-box flight recorder for autonomous
commerce.**

That means the runtime is responsible not only for saying "allow" or "deny,"
but for preserving a verifiable chain answering all of these after the fact:

- who had authority
- which hardware exercised that authority
- which physical location or custody boundary was in scope
- which economic transaction was allowed
- which evidence proved the physical act actually happened
- which reasoning and policy chain led to the release of funds or transfer

Operationally, that lens sharpens four design commitments:

- every high-consequence action should produce a durable digital fingerprint
- authority should be delegated and narrowly scoped, never broad and ambient
- physical and economic state must converge into one replayable evidence chain
- failures should be explainable through deterministic forensic replay rather
  than post-hoc log digging

Diagram positioning and deployment posture should stay explicit:

- top (`Brain/Intent`): humans and AI agents initiate high-consequence requests
- bottom (`Sandboxes/Reality`): economic and physical systems emit evidence
- center (`SeedCore`): PDP plus forensic evidence integrator and replay anchor
- cluster role: SeedCore runs as a high-availability trust slice service, not a
  best-effort sidecar

## Canonical Digital Fingerprint Chain

For the canonical 2026 workflow, the minimum provenance story should bind four
evidence classes into one chain:

- economic transfer proof:
  - `Order_ID`
  - transaction or quote hash
- physical presence proof:
  - shelf, zone, or coordinate binding
  - point-cloud, image, or lidar-derived hash
- runtime reasoning proof:
  - policy decision hash
  - reason trace or inference-log hash
- actuator proof:
  - trajectory hash
  - motor torque, weight, or other physical-effort telemetry hash

Integration baseline for this stage:

| Component | SeedCore interaction |
| :--- | :--- |
| Confluent Kafka | intent + telemetry ingress, policy outcome / scoped authority egress |
| Ray / Kubernetes | shard-aware compiled decision graph execution for hot path |
| Redis | revocation and emergency cutoff signaling |
| Cloud KMS | signer hardening for policy and transition artifacts |
| Durable forensic store | persistence of signed forensic blocks for replay and audit |

The point is not to force every integration to emit the exact same modalities on
day one. The point is to ensure that every high-value transfer can answer, in a
single replay chain:

- what was bought or transferred
- where the actor actually was
- why SeedCore allowed it
- what physical deed was actually performed

## Next Stage: Productizing Irrefutable Governed Execution

The next stage should focus on four priorities.

Operationally, those priorities should be executed as one productionization
program rather than as separate security, observability, and UX initiatives.

The dependency order should stay clear:

- first harden the trust boundary
- then make the trust runtime operable and visible
- then expose that trust boundary through a narrow product surface
- then expand multi-party governance on top of a runtime that is already
  defensible and operable

## Program Lock: One Must-Win Workflow

In the next phase, all workstreams must prove value against one canonical
workflow:

**Restricted Custody Transfer**

This means:

- every Phase A, B, C, and D deliverable must improve the same dual-approved,
  replay-verifiable transfer flow
- anything that does not improve that flow is second-tier for this phase
- registration intake remains important, but as an upstream prerequisite chain
  to the transfer proof surface rather than as the product center of gravity

For 2026, the most useful concrete expression of that workflow is a
**Forensic Handshake**:

- Agent-B (buyer-side) requests a restricted transfer or purchase intent
- Agent-S (seller-side or inventory-side) validates delegated authority and
  reserves the item
- SeedCore binds the request to a product identity, physical scope, and bounded
  execution token
- the physical actor produces shelf or handover evidence before closure
- payment or transfer finalization happens only when the physical and economic
  evidence chains agree

The execution spine for that rule now lives in
[killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md).

## Immediate Execution Order

The next implementation order remains locked to Restricted Custody Transfer
Slice 1, but the repository is no longer at the planning-only stage.

### Slice 1 Implementation Status

Completed in repo:

- `TransferApprovalEnvelope` is now a first-class runtime object with versioned
  persistence and append-only transition history
- Restricted Custody Transfer no longer trusts embedded approval payloads in
  `approval_context` as authoritative truth
- `/api/v1/pdp/hot-path/evaluate` resolves persisted approval state before
  policy evaluation
- hot-path shadow status and parity plumbing remain in `shadow` mode and are
  covered by the targeted RCT pytest slice
- replay and proof projections now recover approval metadata from persisted
  policy-case authority data
- host verification scripts no longer rely on synthesized approval state for
  the main RCT sign-off flow
- productized surface verification now fails closed when no runtime `audit_id`
  is available

### Slice 1 Live Sign-Off Closure (Completed 2026-03-30)

Closed in runtime-up evidence:

- hot-path parity accounting now includes canonical `quarantine` at run level
  (`run_parity: 4/4 ok, 0 mismatched`)
- captured full runtime matrix with explicit `audit_id` links:
  - `allow`: `ba05655c-9351-4783-97f1-fc6774c4f38b`
  - `deny`: `a65bbee7-023a-44fa-9e9d-75e0164102e4`
  - `quarantine`: `21dcb295-644a-465b-a505-064e6908c99c`
  - `escalate`: `28ac9873-3e8f-430f-9681-224fdad44286`
- allow-path artifact chain now carries non-null `approval_envelope_id`,
  `approval_envelope_version`, `approval_binding_hash`, `policy_receipt_id`,
  and `transition_receipt_ids`
- replay + verification surfaces are cross-surface consistent for captured
  identifiers (with status/proof intentionally keeping narrow business-state
  shape)
- productized surface protocol is green against captured runtime evidence
- offline Rust replay-chain verification is green for all four captured runtime
  audit chains
- hardened signer provenance captured on allow path for both `PolicyReceipt`
  and `TransitionReceipt` with KMS key ref `kms:rct-live-signoff-p256`

Capture bundle:

- `.local-runtime/rct_live_signoff/20260330T061828Z`

### Post-Closure Queue

What should be done next:

1. ~~Freeze and version the captured runtime sign-off bundle as a release
   artifact.~~ **Done (2026-04-01).** Canonical tree: `tests/fixtures/demo/rct_signoff_v1/`
   with `manifest.json` checksums; machine verification:
   `python scripts/tools/verify_rct_signoff_bundle.py`; release record and tarball:
   `release/rct_slice1_live_signoff_v1/README.md`.
2. ~~Promote capture verification into a repeatable CI/host gate (shadow parity +
   runtime matrix + replay-chain verify).~~ **Partially done (2026-04-02).**
   Host verification path updated and aligned to `/api/v1/verification/*`;
   full CI policy gate adoption remains open.
3. ~~Define explicit criteria for any future `shadow` -> `enforce` hot-path
   promotion.~~ **Done (2026-04-02).** Promotion semantics now include strict
   parity, latency SLO, dependency health, and rollback triggers.
4. ~~Freeze the first forensic-handshake contract additions:~~ **Done
   (2026-04-02).**
   - ~~transaction-scoped authority binding~~
   - ~~device fingerprint binding~~
   - ~~forensic block field set~~
   - ~~replay export shape~~
5. Keep broader signer expansion and non-RCT hardening in later phases
   (outside Slice 1 closure scope).

Interpretation note:

- Item 2 (CI/host gate) should be prioritized before broadening deployment
  blast radius.
- `runtime_ready` wiring work is an environment/integration follow-up and should
  proceed in parallel, but is not a blocker to preserving the frozen sign-off
  artifact in item 1.

### Explicit Sidecar

The VLA track in
[vla_2026_optimizations.md](/Users/ningli/project/seedcore/docs/development/vla_2026_optimizations.md)
remains sidecar for this phase.

It may continue in parallel as research or future-performance work, but it is
not on the critical path for the must-win demo or for Slice 1 runtime
hardening.

### 1. Irrefutable Trust Anchors

SeedCore already issues bounded execution authority. The next step is to make
the trust boundary cryptographically defensible in environments where spoofing,
repudiation, or internal tampering are real concerns.

What to build:

- move critical HAL and evidence-signing flows behind TPM, HSM, or cloud
  KMS-backed signers where practical
- bind every high-value action to a device or node fingerprint, including agent
  identity, hardware attestation handle, and current physical context when
  available
- evolve execution tokens into transaction-specific authority:
  - valid for one workflow instance
  - valid for one asset or product identity
  - valid for one physical zone, shelf, or coordinate scope
  - invalid outside the expected handoff context
- make signer profile selection explicit across PDP, evidence, and
  transition-receipt paths
- support optional external anchoring for selected high-value receipts into a
  transparency log or enterprise audit ledger
- separate internal operational audit from externally shareable verification
  receipts
- define security validation gates for trust-critical surfaces such as signer
  paths, receipt verification, replay verification, and revocation flows
- treat targeted external review and adversarial testing of the trust boundary
  as part of release readiness for high-stakes workflows

Why this is feasible:

- this can start with cloud KMS-backed server-side signing
- it can use TPM-backed or device-bound signing for selected edge nodes instead
  of requiring universal hardware redesign
- transaction-specific scoping can start with asset id + zone id + policy
  snapshot binding before full coordinate granularity is required everywhere
- external anchoring can begin only for high-stakes transitions rather than
  every low-risk action
- security validation can begin with scoped threat modeling and targeted
  penetration testing of the cryptographic and replay boundary instead of a
  broad platform-wide certification effort

Strategic result:

SeedCore will move trust from application claims to cryptographically anchored
execution evidence and measurably reduce spoofing, replay, and revocation risk
at the execution boundary.

### 2. Multi-Party Execution Governance

The current runtime already supports deny-by-default, quarantine, and governed
receipts. The next step is to govern actions that cross organizational,
approval, and physical verification boundaries.

What to build:

- delegated authority chains across organizations, facilities, zones, devices,
  and agents
- buyer-side and seller-side handshake validation for selected high-value
  transfers
- dual authorization for selected high-risk transitions
- multi-signature release rules where:
  - the human request or approval is signature one
  - the physical verification event is signature two
  - funds or final transfer release happens only after both land
- explicit break-glass paths with elevated evidence obligations
- co-signed approvals for exceptional or blocked workflow overrides
- signed approval and delegation capture as part of the same governed receipt
  chain

Why this is feasible:

SeedCore does not need to model every legal or commercial workflow immediately.
It should start with a small number of high-value patterns:

- release from quarantine
- transfer of custody for a restricted lot
- physical verification before economic settlement
- emergency override of a blocked workflow

Multi-party governance is the canonical demo workflow, but initial
productionization should still prioritize trust hardening for the artifacts
that support that workflow.

Strategic result:

SeedCore becomes more than an internal policy gate. It becomes a runtime for
replayable, governed multi-party action with explicit release authority.

### 3. The Asset-Centric Hot Path And Forensic Ledger

The strongest technical discipline for the next stage is keeping the real-time
decision path small, deterministic, and operationally useful while preserving
enough state to replay failures like a flight recorder.

What to build:

- a compiled Decision Graph for synchronous PDP evaluation
- strict inclusion of only latency-critical entities:
  - principals
  - devices
  - facilities
  - zones
  - lots, batches, and twins
  - active custody state
  - live policy context
- versioned graph snapshots for reproducible decisions
- cached or precompiled path evaluation for the most common action types
- first-class quarantine and trust-gap outcomes
- synchronized state capture between governed digital state and physical
  execution state for the canonical workflow:
  - agent request and reason trace hash
  - approval envelope state
  - economic transaction state
  - twin mutation state
  - physical telemetry state
- a forensic block or ledger entry that binds:
  - decision and approval hashes
  - product or asset identity
  - physical location evidence
  - edge telemetry references
  - transition and policy receipt ids
  - replay ordering metadata
- critical-path tracing and decision-path visibility for the governed execution
  path, especially registration submission, PDP evaluation, signer selection,
  replay publication, and verification
- focused dashboards, trust-anomaly detection, and alerting for authz-graph
  health, deny and quarantine spikes, snapshot mismatches, signer failures,
  replay verification failures, and stuck registration workflows

Why this matters:

SeedCore should not behave like an academic graph platform that turns every
issue into a generic deny. In real operations, the correct governed outcome is
often:

- isolate the asset
- preserve state
- require manual review
- escalate an evidence or telemetry gap

The point is not tracing every microsecond. The point is giving operators
visibility into why actions were allowed, denied, quarantined, or slowed and
whether the runtime is still preserving its deterministic contract.

Strategic result:

SeedCore keeps the hot path explainable, fast, and deterministic even as the
broader ontology grows and the replay burden increases.

### 4. Productize The Verification Surface

The runtime's trust value has to be visible, not just internally correct.

What to build:

- signed, governed receipts for every high-value allow, deny, or quarantine
  outcome
- verification pages or APIs that can replay the full receipt chain from
  approval through transfer verification
- operator-facing workflow status APIs for Restricted Custody Transfer that
  expose:
  - prerequisite state
  - approval state
  - transfer readiness
  - governed tracking timeline
- a workflow-specific proof surface for Restricted Custody Transfer, with
  registration intake treated as an upstream prerequisite rather than the
  product center
- business-readable trust states such as verified, quarantined, rejected, and
  review required rather than raw graph-routing, signer, or replay failure
  details
- asset-centric forensic views tying together:
  - decision hash
  - policy snapshot
  - principal identity
  - custody transition
  - telemetry references
  - signature provenance
  - economic settlement status
- an audit-trail UI that can eventually show, side by side:
  - the natural-language or agent request
  - the digital transaction trail
  - the physical replay or evidence timeline
- public or partner-visible verification surfaces restricted to approved
  stakeholders

Why this is feasible:

SeedCore does not need a universal trust portal on day one. It needs a narrow
but impressive proof surface for one wedge:

- one asset class
- one transfer chain
- one evidence model
- one replay view

It can also start with one governed intake workflow that already matches the
trust story:

- one registration-to-transfer chain
- one operator status view
- one monitored path from prerequisite approval to transfer to replay
  verification

It should not begin as a generic admin dashboard. It should begin as a governed
operational surface for one high-trust workflow.

Strategic result:

SeedCore stops looking like a backend-only control layer and becomes a visible
trust product.

Phase D should therefore be executed as one constrained product wedge rather
than as a broad UX program.

The execution rules for this phase are:

- one asset class
- one transfer chain
- one evidence model
- one replay view
- one operator status surface

The core deliverables should be framed as product artifacts, not just backend
capabilities:

- provable outcomes: governed receipts and replay-verifiable receipt chains
- business-readable state translation: verified, quarantined, rejected, review
  required
- operator workflow visibility: prerequisite-to-transfer lifecycle for
  Restricted Custody Transfer
- asset-centric forensic context: a single view that binds policy, identity,
  custody, telemetry, settlement, and signature provenance
- external verification surface: a partner-visible trust page or API for
  approved stakeholders only

Authoritative Q2 product specification for this phase:

- [q2_2026_audit_trail_ui_spec.md](/Users/ningli/project/seedcore/docs/development/q2_2026_audit_trail_ui_spec.md)

If Phase D expands beyond that narrow proof surface before the canonical
workflow is demonstrably credible, it will dilute the product story and slow
the trust proof.

## 12-18 Month Execution Program

The next stage is best presented as a staged execution program rather than a
giant future-state promise.

It should be described and managed as one program that makes governed execution
defendable, operable, and usable in production.

### Phase A: Trust Hardening

Focus:

- KMS, TPM, or HSM-backed signing for selected receipt paths
- clearer signer provenance and signer policy profiles
- transaction-scoped authority binding to asset identity and physical scope
- optional external anchoring for high-value events
- verifier tooling for signature and signer-chain inspection
- security validation gates for signer, replay, and revocation surfaces before
  claiming enterprise-grade trust properties

Success condition:

SeedCore can produce receipt chains that are difficult to spoof, difficult to
erase, and easy to verify.

Current closure checkpoint for strict TPM attestation path:

- generate strict TPM fixtures with real AK cert + endorsement root + signed
  TPM quote: `python scripts/tools/generate_strict_tpm_receipt_fixtures.py`
- verify strict receipt offline with trust bundle only: `cargo run -q -p seedcore-verify -- verify-receipt --artifact fixtures/receipts/restricted_transition_receipt_strict_tpm_artifact.json --trust-bundle fixtures/receipts/restricted_transition_trust_bundle_strict_tpm.json`
- keep `seedcore-verify` strict fixture regression green
  (`verify_restricted_transition_receipt_strict_attestation_with_real_fixture`)
  before declaring Phase A mathematically closed
- operationalize fleet rollout using the TPM checklist and drills in
  [tpm_fleet_rollout_runbook.md](/Users/ningli/project/seedcore/docs/development/tpm_fleet_rollout_runbook.md)

### Phase B: Multi-Party Governance

Focus:

- delegated authority chains
- dual authorization
- human-plus-physical-verification multi-signature release rules
- break-glass workflows with elevated evidence
- cross-organization approval paths

Success condition:

SeedCore can govern one or two high-risk transitions that require more than one
approving authority and can prove why release authority was granted.

### Phase C: Operational Decision Engine And Forensic State Store

Focus:

- compiled decision graph discipline
- quarantine and trust-gap state as first-class outcomes
- fast-path evaluation and shard-aware cache routing
- deterministic explanation output for hot-path decisions
- critical-path tracing, dashboards, and alerting for trust-runtime failures and
  degraded decision readiness
- synchronized forensic-state capture linking policy, telemetry, and settlement
  state to the same governed event

Success condition:

SeedCore can answer real authorization questions quickly and explainably
without pulling broad enrichment context into the synchronous path, while still
recording enough converged state to replay the action later.

### Phase D: Verification Product Surface

Focus:

- governed receipts as the visible product artifact
- replay and trust-page UX for operators, auditors, and partners
- asset-centric trust history
- API and UI proof layer for third-party verification
- operator-facing status tracking and proof monitoring for Restricted Custody
  Transfer, with registration intake treated as its prerequisite chain
- business-readable trust-state translation for workflow outcomes and failure
  classes
- an audit-trail view that can correlate request, digital transaction, and
  physical replay evidence

Default build order:

1. freeze the workflow-specific status vocabulary and receipt-chain projection
2. expose operator-facing status APIs for prerequisite, approval, and transfer
   readiness
3. publish the asset-centric forensic view for the canonical transfer chain
4. expose partner-visible replay or trust-page verification for approved
   stakeholders
5. implement the four Q2 UI screens in order: transfer queue, transfer detail,
   asset-centric forensics, replay/verification view

Success condition:

SeedCore can show an externally legible chain of decision, execution, economic
settlement, and physical evidence for one specific high-value asset workflow,
with a business-readable status surface and replay-verifiable receipts that
approved third parties can inspect.

## Phase Done Means

- Phase A is done when the canonical transfer flow emits signed artifacts with
  verifier output, tamper checks, signer provenance, and device-bound authority
  binding that can be demonstrated end to end.
- Phase B is done when Restricted Custody Transfer can require dual approval and
  deterministic physical verification before releasing the final transfer or
  settlement path.
- Phase C is done when the PDP returns a bounded-latency explanation payload and
  the runtime preserves a replayable forensic state chain for the canonical
  workflow.
- Phase D is done when the canonical transfer flow has an externally legible
  proof surface showing business-readable state, artifact lineage, settlement
  linkage, and replay verification.

## Killer Demonstration

The roadmap should stay anchored to one demonstration that proves the category.

The best next-stage demonstration is:

**Restricted Custody Transfer with a Forensic Handshake: a high-value transfer
that requires deterministic policy evaluation, delegated authority, hardware
fingerprints, physical verification, and replayable third-party proof.**

If SeedCore can demonstrate that end to end, it will tell a much more credible
story than a broad list of trust claims.

The immediate next technical step for that demonstration is to freeze the
approval, authorization-output, forensic-block, and verification-surface
contracts for the next dual-authorization workflow before broad UI or signer
integration work begins. See
[killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
and
[next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md).

Phase 0 closure is now machine-checkable through
[phase0_contract_freeze_manifest.json](/Users/ningli/project/seedcore/docs/development/phase0_contract_freeze_manifest.json)
with the validation gate
`python scripts/tools/verify_phase0_contract_freeze.py`.

The current engineering sign-off state for that demo, including what is passed
offline and what still genuinely demands a live runtime proof, now lives in
[restricted_custody_transfer_demo_signoff_report.md](/Users/ningli/project/seedcore/docs/development/restricted_custody_transfer_demo_signoff_report.md).

The recommended multi-language boundary plan for that work now lives in
[language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md).

The concrete service/CLI-first Rust kernel proposal for that same track now
lives in
[rust_workspace_proposal.md](/Users/ningli/project/seedcore/docs/development/rust_workspace_proposal.md).

For post-2026 high-vertical staging (SeedCore trust boundary + IGX/Jetson
physical execution boundary), see:
[seedcore_2027_high_vertical_direction.md](/Users/ningli/project/seedcore/docs/development/seedcore_2027_high_vertical_direction.md).

## Red-Team Program

The forensic-ledger story only becomes credible if the failure modes are
deliberately exercised.

The first required adversarial drills should be:

- the man-in-the-middle physical redirect:
  - intercept coordinate or zone data
  - attempt to redirect the robot to the wrong shelf or handoff point
  - prove the mismatched fingerprint or scope binding blocks final settlement
- the authority leak:
  - simulate session-token theft or agent replay
  - prove SeedCore can identify the exact injection point and contain the blast
    radius
- the physical double-spend:
  - attempt to pick two items while paying or settling for one
  - prove telemetry or weight mismatch produces quarantine and replay-visible
    discrepancy

These should be release-gating drills for the canonical workflow, not optional
"security extras."

## Schema Recommendation

SeedCore should treat the first **Forensic Block** as a product-facing evidence
contract, not only an internal transport message.

Recommended choice:

- canonical external and replay-export shape: JSON-LD
- optional internal transport mirror for high-throughput node-to-node exchange:
  Protobuf

Rationale:

- JSON-LD fits the verification, trust-page, and third-party audit surface
  already present in the repo
- Protobuf can still be added later for Ray/Kubernetes transport after the
  external field set stabilizes
- choosing JSON-LD first avoids creating one internal truth schema and a second
  audit schema that drift immediately

## Messaging Guardrails

The next-stage narrative should stay ambitious without overclaiming.

Better positioning:

- "SeedCore is productizing irrefutable governed execution and forensic replay."
- "SeedCore is positioning to become a verifiable agentic ledger for
  high-trust, multi-party workflows."
- "SeedCore moves trust from application claims to cryptographically anchored
  execution evidence."

Claims to avoid:

- "only viable execution runtime for 2026"
- "legally binding digital contracts" as a near-term product claim
- "full autonomous commerce stack" before the narrow wedge is demonstrably
  credible

More grounded alternatives:

- "well aligned with emerging provenance, auditability, and product-passport
  requirements in regulated supply chains"
- "governed, co-signed execution receipts for high-trust multi-party workflows"
- "a runtime for cryptographically defensible, replayable governed execution"

## Practical Guidance

When the root README mentions roadmap direction, it should stay short and point
here.

This document should be updated when one of two things changes:

- the baseline has materially improved and a "future" item is now present
- the wedge strategy changes and the next-stage narrative needs to be tightened
