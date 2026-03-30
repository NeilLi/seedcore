# Killer Demo Execution Spine

## Status

Working execution spine for the next 90-day contract-and-proof phase.

Current repo state on 2026-03-30:

- the Restricted Custody Transfer Slice 1 authority boundary is implemented
- persisted approval records, not embedded request payloads, are the RCT source of truth
- hot-path rollout remains intentionally in `shadow`
- runtime-up verification is now exercised locally across `8002`, `7071`, `7072`, and `7073`
- full Slice 1 live-demo sign-off closure is captured with explicit runtime audit chains for `allow`/`deny`/`quarantine`/`escalate`, cross-surface consistency evidence, and allow-path hardened signer provenance

## Purpose

This document is the execution center of gravity above the roadmap, contract
freeze, and PKG RFC for the next SeedCore build phase.

It exists to answer four questions unambiguously:

- what exact workflow becomes product first
- which artifacts are authoritative
- which explanation payload is mandatory
- what remains out of scope until that workflow is proven

## Program Lock

For the next phase, all workstreams must prove value against one canonical
workflow:

**Restricted Custody Transfer**

Definition:

- a high-value asset changes custody
- the transfer requires dual approval
- the transfer is deterministically authorized by the PDP
- the decision mints governed artifacts
- the result is replay-verifiable and business-readable to a third party

Secondary workflows such as registration intake, release from quarantine, and
other approval flows remain useful, but they are not the primary execution
spine.

## Primary Rule

Every near-term Phase A, B, C, and D deliverable must improve Restricted
Custody Transfer directly.

If a task does not improve this workflow’s:

- trust boundary
- approval chain
- decision path
- proof surface
- replayability

it is second-tier for this phase.

## Authoritative Artifact Order

The authoritative contract order for the next killer demo is:

```text
TaskPayload
  -> ActionIntent
  -> TransferApprovalEnvelope
  -> PolicyDecision / ExecutionToken / governed_receipt
  -> PolicyReceipt
  -> TransitionReceipt / EvidenceBundle
  -> VerificationSurfaceProjection
```

Artifact rules:

- `TaskPayload` is proposal only.
- `ActionIntent` is the accountable authorization request.
- `TransferApprovalEnvelope` is governed approval state and must come from persisted runtime records for Restricted Custody Transfer.
- `ExecutionToken` is the only authorization artifact that may unlock execution.
- `governed_receipt`, `PolicyReceipt`, and `TransitionReceipt` are proof-bearing artifacts with different roles.
- `EvidenceBundle` records what happened after execution.
- `VerificationSurfaceProjection` is downstream product projection only.

## Runtime Truth Table

| Runtime disposition | Meaning | Token? | Receipt? | Surface state |
| :--- | :--- | :--- | :--- | :--- |
| `allow` | prerequisites satisfied | yes | yes | `verified` |
| `deny` | contradictory or forbidden | no | yes | `rejected` |
| `quarantine` | trust chain incomplete but not contradictory | maybe restricted | yes | `quarantined` |
| `escalate` | human or governance review required | no or pending | yes | `review_required` |

This table should be treated as the shared translation layer across runtime,
proof, and UI documents.

## Minimum Explanation Payload

The next killer demo must emit a minimum explanation payload that every
verification view can derive from.

Mandatory fields:

- `disposition`
- `matched_policy_refs`
- `authority_path_summary`
- `missing_prerequisites`
- `trust_gaps`
- `minted_artifacts`
- `obligations`

The goal is not maximal detail. The goal is minimum cross-document consistency.

## Canonical Demo Script

The best near-term demo is not generic robotics. It is one sealed, high-value
lot handoff that makes the physical-to-digital custody boundary undeniable.

Demo happy path:

- a packer cell seals a high-value lot into a smart container
- the runtime submits the `ActionIntent` for `Restricted Custody Transfer`
- dedicated transfer-approval endpoints persist the versioned `TransferApprovalEnvelope`
- an inspector agent co-approves that persisted approval record
- the PDP hot path evaluates against the canonical snapshot
- the runtime mints a `PolicyReceipt`, `TransitionReceipt`, and governed proof chain
- the courier verifies the handoff before accepting custody through the proof surface or `seedcore-verify`

Mandatory sibling failure modes:

- missing approval envelope or incomplete dual approval
- stale telemetry or broken-seal quarantine
- break-glass review path

Sign-off rule:

- the same runtime `audit_id` must tie together replay, verification API, proof surface, operator console, and offline verification for the live demo claim

Demo rule:

- keep packing as upstream context
- keep the handoff decision point as the center of gravity
- show the same asset story across operator status, forensic view, public proof, and offline verification

## Slice 1 Runtime Rule

For the current delivery slice, the demo must run against these runtime truths:

- `TransferApprovalEnvelope` is a first-class runtime object with versioned persistence
- `approval_context` is reference-and-observation only, not the source of truth
- Restricted Custody Transfer fails closed when no authoritative approval envelope is present
- proof surfaces render approval version, approval binding hash, policy receipt id, transition receipt ids, signer provenance, and runtime custody state from runtime artifacts
- hot-path rollout stays in `shadow` mode until parity evidence is green
- VLA optimization work remains explicitly sidecar to this demo

## Product-First Rule

SeedCore’s first product surface in this phase is:

- architecture term: **Proof Surface**
- user-facing term: **Verification Surface**

It is not:

- a generic admin console
- a general observability dashboard
- a broad workflow manager

It is a workflow-specific proof surface for Restricted Custody Transfer.

## Must-Win Success Criteria

The phase is successful when Restricted Custody Transfer is:

- dual-approved
- deterministically authorized
- receipt-bound
- proof-explainable
- replay-verifiable
- business-readable

## Out Of Scope Until This Is Proven

Do not let the phase drift into:

- generic partner UX across many workflows
- broad dashboard programs
- open-ended enrichment modeling
- natural-language policy authoring
- non-essential multi-workflow orchestration
- analytics-first PKG work

## Related Documents

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [restricted_custody_transfer_demo_signoff_report.md](/Users/ningli/project/seedcore/docs/development/restricted_custody_transfer_demo_signoff_report.md)
- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md)
- [rust_workspace_proposal.md](/Users/ningli/project/seedcore/docs/development/rust_workspace_proposal.md)
- [pkg_authz_graph_rfc.md](/Users/ningli/project/seedcore/docs/development/pkg_authz_graph_rfc.md)
- [contract_freeze_zero_trust_terms.md](/Users/ningli/project/seedcore/docs/development/contract_freeze_zero_trust_terms.md)
