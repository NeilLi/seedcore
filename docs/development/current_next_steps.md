# Current Next Steps

This document tracks the practical next-step priorities for SeedCore based on the current repository state, not an earlier architecture-only roadmap.

## Why This Lives Outside The Root README

The root README should explain what SeedCore is and how to run it. The exact next steps shift more quickly as verification coverage, PKG/runtime behavior, and trust-surface features improve, so the detailed plan lives here instead.

## What Is Already In Place

The following capabilities are already present in the repository and should not be described as future work anymore:

- short-lived execution tokens with TTL enforcement
- Redis-backed token revocation and HAL emergency cutoff controls
- HAL transition receipts with verification paths
- evidence bundles that bind policy and transition artifacts into replayable closure
- public replay, trust-page, and verification workflow surfaces
- DID, delegation, and signed-intent support on the external surface
- staged PKG authz-graph rollout through Phase 5, including:
  - decision-centric ontology
  - multihop authority paths
  - explanation payloads
  - decision/enrichment split
  - shard-aware Ray authz cache routing

## Current Priorities

### 1. Hardware-Backed Signing And Device Trust

The main trust gap is no longer “add signatures.” It is moving signer identity from local or environment-backed delivery into stronger production-grade controls.

Current focus:

- move attested HAL and evidence-signing keys behind TPM, HSM, or cloud KMS-backed signers
- make signer profile selection explicit across PDP, evidence, and transition-receipt paths
- keep local dev fallbacks, but separate them clearly from production attested signer modes
- bind physical endpoint identity and signer identity more tightly in runtime verification and inventory

### 2. External Audit Anchoring And Default Receipt Chains

Receipt chaining and custody lineage exist, but external anchoring is still the next real step for dispute resistance.

Current focus:

- anchor policy receipts, execution receipts, transition receipts, and custody events into an external transparency log or enterprise audit ledger
- promote chained receipt relationships from optional or service-specific behavior into the default audit path
- make receipt-chain verification a first-class operator and trust-surface workflow

### 3. Dual Authorization For High-Risk Actions

The runtime already supports deny-by-default, quarantine, and governed receipts. The next control upgrade is stronger multi-party authorization for selected actions.

Current focus:

- add explicit co-sign or dual-approval paths for releases, protected transfers, and other high-risk transitions
- bind those approvals into the same evidence and replay closure
- ensure dual-authorization state participates in authz-graph explanation and policy replay

### 4. Policy Rollout And Activation Hardening

Policy reload, refresh, compare, and local activation flows exist now. The next step is operational hardening, not inventing policy distribution from scratch.

Current focus:

- make snapshot promotion, compare, reload, and runtime activation confirmation part of one consistent rollout contract
- reduce ambiguous or partial activation states across API, Ray Serve, and host-mode workflows
- improve fleet-facing rollout ergonomics so active runtime state is always obvious and auditable
- keep hot-path authz graph activation deterministic across refresh and restart flows

### 5. Multi-Party Delegation And External Authority In Runtime Paths

The API surface already supports DID, delegation, and signed intents. The next step is deeper operational use of those surfaces.

Current focus:

- carry delegation and external authority signals further into governed execution paths
- expand signed-intent usage from API support into more end-to-end runtime demos and product flows
- make partner and cross-organization trust boundaries easier to inspect through replay and trust views

### 6. Productization Of Trust Surfaces

SeedCore now has credible trust primitives; the next step is packaging them as a clearer product surface.

Current focus:

- refine trust-page and public-verification UX around the strongest governed evidence flows
- make replay, receipt-chain status, and signer provenance easier to present to operators, auditors, and buyers
- keep the proof story anchored in what the runtime actually verifies today

## What Is No Longer A Good Root-README Claim

The following older formulations are now too inaccurate or too incomplete to keep as the main “next steps” message:

- “add revocation and emergency stop” as future work
- “add transition receipts” as future work
- “replace restart-based policy operation” as if no runtime activation path exists today
- “make break-glass deterministic” without acknowledging the current compiled-authz and explanation path
- “add signed intents or delegation” as though those APIs do not already exist

## Practical Guidance

When the root README needs to mention roadmap direction, keep it brief and point here. The detailed plan should continue to be updated alongside real runtime and verification progress.
