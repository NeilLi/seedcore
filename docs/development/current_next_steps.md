# Current Next Steps

This document tracks the next-stage priorities for SeedCore based on the repository as it exists today.

It is intentionally written to balance two things:

- the strong baseline SeedCore already has
- the practical, wedge-first roadmap needed to make that baseline enterprise-credible

The goal is not to describe a perfect future state all at once. The goal is to define the next 12-18 months in a way that is ambitious, believable, and product-relevant.

## Why This Lives Outside The Root README

The root README should explain what SeedCore is, how it runs, and why the architecture matters.

The exact next-stage plan changes faster than the high-level architecture summary. As verification improves and the runtime hardens, this document can be updated without turning the root README into a moving target.

## Baseline That Already Exists

SeedCore is no longer a conceptual architecture. The repository already contains a functioning governed execution baseline.

The following should be treated as present, not future work:

- short-lived execution tokens with TTL enforcement
- Redis-backed token revocation and HAL emergency cutoff controls
- HAL transition receipts with verification paths
- evidence bundles that bind policy, execution, and transition artifacts into replayable closure
- public replay, trust-page, and verification workflow surfaces
- DID, delegation, and signed-intent support on the external surface
- staged PKG authz-graph rollout through Phase 5, including:
  - decision-centric ontology
  - multihop authority paths
  - explanation payloads such as `matched_policy_refs` and `missing_prerequisites`
  - decision-graph vs enrichment-graph split
  - shard-aware Ray authz cache routing

This means the next stage is not about adding more concepts for their own sake. It is about converting the existing governed execution baseline into a product-grade trust runtime for high-trust, multi-party environments.

## Strategic Objective

The right objective for the next stage is:

**Make SeedCore the most credible runtime for irrefutable, multi-party governed execution in high-trust supply-chain and asset-sensitive environments.**

That is a better objective than “solve all trusted autonomy problems” because it forces the roadmap to stay wedge-first, operational, and commercially legible.

The guiding discipline for this stage is:

- one wedge: high-trust, multi-party supply chain and asset transfer
- one proof surface: governed receipts and replayable verification
- one scaling logic: a compiled hot-path decision graph with cryptographic trust anchors

## Next Stage: Productizing Irrefutable Governed Execution

The next stage should focus on four priorities.

### 1. Irrefutable Trust Anchors

SeedCore already issues bounded execution authority. The next step is to make the trust boundary cryptographically defensible in environments where spoofing, repudiation, or internal tampering are real concerns.

What to build:

- move critical HAL and evidence-signing flows behind TPM, HSM, or cloud KMS-backed signers where practical
- make signer profile selection explicit across PDP, evidence, and transition-receipt paths
- support optional external anchoring for selected high-value receipts into a transparency log or enterprise audit ledger
- separate internal operational audit from externally shareable verification receipts

Why this is feasible:

- this can start with cloud KMS-backed server-side signing
- it can use TPM-backed or device-bound signing for selected edge nodes instead of requiring universal hardware redesign
- external anchoring can begin only for high-stakes transitions rather than every low-risk action

Strategic result:

SeedCore will move trust from application claims to cryptographically anchored execution evidence.

### 2. Multi-Party Execution Governance

The current runtime already supports deny-by-default, quarantine, and governed receipts. The next step is to govern actions that cross organizational and approval boundaries.

What to build:

- dual authorization for selected high-risk transitions
- delegated authority chains across organizations, facilities, zones, and devices
- explicit break-glass paths with elevated evidence obligations
- co-signed approvals for exceptional or blocked workflow overrides
- signed approval and delegation capture as part of the same governed receipt chain

Why this is feasible:

SeedCore does not need to model every legal or commercial workflow immediately. It should start with a small number of high-value patterns:

- release from quarantine
- transfer of custody for a restricted lot
- emergency override of a blocked workflow

Strategic result:

SeedCore becomes more than an internal policy gate. It becomes a runtime for replayable, governed multi-party action.

### 3. The Asset-Centric Hot Path

The strongest technical discipline for the next stage is keeping the real-time decision path small, deterministic, and operationally useful.

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

Why this matters:

SeedCore should not behave like an academic graph platform that turns every issue into a generic deny. In real operations, the correct governed outcome is often:

- isolate the asset
- preserve state
- require manual review
- escalate an evidence or telemetry gap

Strategic result:

SeedCore keeps the hot path explainable, fast, and deterministic even as the broader ontology grows.

### 4. Productize The Verification Surface

The runtime’s trust value has to be visible, not just internally correct.

What to build:

- signed governed receipts for every high-value allow, deny, or quarantine outcome
- verification pages or APIs that replay receipt chains
- asset-centric forensic views tying together:
  - decision hash
  - policy snapshot
  - principal identity
  - custody transition
  - telemetry references
  - signature provenance
- public or partner-visible verification surfaces for approved stakeholders

Why this is feasible:

SeedCore does not need a universal trust portal on day one. It needs a narrow but impressive proof surface for one wedge:

- one asset class
- one transfer chain
- one evidence model
- one replay view

Strategic result:

SeedCore stops looking like a backend-only control layer and becomes a visible trust product.

## 12-18 Month Execution Program

The next stage is best presented as a staged execution program rather than a giant future-state promise.

### Phase A: Trust Hardening

Focus:

- KMS, TPM, or HSM-backed signing for selected receipt paths
- clearer signer provenance and signer policy profiles
- optional external anchoring for high-value events
- verifier tooling for signature and signer-chain inspection

Success condition:

SeedCore can produce receipt chains that are difficult to spoof, difficult to erase, and easy to verify.

### Phase B: Multi-Party Governance

Focus:

- delegated authority chains
- dual authorization
- break-glass workflows with elevated evidence
- cross-organization approval paths

Success condition:

SeedCore can govern one or two high-risk transitions that require more than one approving authority.

### Phase C: Operational Decision Engine

Focus:

- compiled decision graph discipline
- quarantine and trust-gap state as first-class outcomes
- fast-path evaluation and shard-aware cache routing
- deterministic explanation output for hot-path decisions

Success condition:

SeedCore can answer real authorization questions quickly and explainably without pulling broad enrichment context into the synchronous path.

### Phase D: Verification Product Surface

Focus:

- governed receipts as the visible product artifact
- replay and trust-page UX for operators, auditors, and partners
- asset-centric trust history
- API and UI proof layer for third-party verification

Success condition:

SeedCore can show an externally legible chain of decision, execution, and evidence for a specific high-value asset workflow.

## Killer Demonstration

The roadmap should stay anchored to one demonstration that proves the category.

The best next-stage demonstration is:

**a high-value asset transfer that requires deterministic policy evaluation, dual authorization, hardware-backed evidence, and replayable third-party verification**

If SeedCore can demonstrate that end to end, it will tell a much more credible story than a broad list of trust claims.

## Messaging Guardrails

The next-stage narrative should stay ambitious without overclaiming.

Better positioning:

- “SeedCore is productizing irrefutable governed execution.”
- “SeedCore is positioning to become one of the first runtimes purpose-built for deterministic, multi-party governed execution.”
- “SeedCore moves trust from application claims to cryptographically anchored execution evidence.”

Claims to avoid:

- “only viable execution runtime for 2026”
- “legally binding digital contracts” as a near-term product claim
- “infrastructure for the entire EU Digital Product Passport” as though the wedge has already been won

More grounded alternatives:

- “well aligned with emerging provenance, auditability, and product-passport requirements in regulated supply chains”
- “governed, co-signed execution receipts for high-trust multi-party workflows”
- “a runtime for cryptographically defensible, replayable governed execution”

## Practical Guidance

When the root README mentions roadmap direction, it should stay short and point here.

This document should be updated when one of two things changes:

- the baseline has materially improved and a “future” item is now present
- the wedge strategy changes and the next-stage narrative needs to be tightened
