# Next Killer Demo Implementation Plan

## Status

This document is the implementation plan for the next Restricted Custody Transfer demo.

It supersedes the older "contract freeze only" framing. The frozen contract shapes still matter, but the purpose here is now to drive delivery.

Live status and execution ordering remain in:
- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [seedcore_2026_execution_plan.md](/Users/ningli/project/seedcore/docs/development/seedcore_2026_execution_plan.md)

## Objective

Deliver the next killer demo as a real, runnable trust slice:

```text
high-value asset transfer -> dual authorization -> governed execution -> replayable third-party verification
```

The implementation should preserve SeedCore's core boundary rules:
- `ActionIntent` stays the accountable execution request
- approval state stays separate from intent
- authorization artifacts stay replayable and auditable
- verification surfaces remain downstream projections, not sources of truth

## What Is Already Frozen

These contracts are already stable enough to implement against:
- `TransferApprovalEnvelope`
- dual-authorization policy output
- `VerificationSurfaceProjection`
- minimal explanation payload
- deny/quarantine examples for incomplete approvals and custody mismatch

The code should treat those shapes as targets, not as open design space.

## Implementation Slices

### Slice 1 - Approval Envelope Persistence

Goal: make approval state first-class and durable.

Work:
- add or finalize the approval-envelope model and storage path
- bind the envelope to a transfer workflow version
- make lifecycle transitions append-only
- preserve replay-addressable old envelope versions

Implementation touchpoints:
- approval workflow domain model
- persistence layer for approval envelopes and approval history
- API boundary that attaches the active envelope reference to `ActionIntent`

Exit criteria:
- an active approval envelope can be created, approved, revoked, expired, and superseded
- duplicate approvals for the same role are rejected
- older envelope versions remain replay-addressable

### Slice 2 - Authorization Output Chain

Goal: make the allow/deny/quarantine output chain explicit and testable.

Work:
- populate `PolicyDecision.required_approvals` when the envelope is missing or incomplete
- preserve strict disposition values
- ensure `ExecutionToken` constraints bind to the approval envelope and transfer context
- keep `governed_receipt` and `PolicyReceipt` distinct but cross-linked

Implementation touchpoints:
- PDP decision logic
- execution-token minting path
- governed receipt construction
- policy-receipt signing and replay binding

Exit criteria:
- one allow-path demo passes with complete approval state
- one deny-path demo fails closed when approvals are incomplete
- one quarantine-path demo is emitted for stale or mismatched transfer conditions

### Slice 3 - Verification Surface

Goal: render business-readable trust status without leaking the runtime as a UI contract.

Work:
- implement or finalize `VerificationSurfaceProjection`
- derive public status from authoritative artifacts only
- keep drill-down links attached to replay and trust references
- maintain the frozen public vocabulary:
  - `verified`
  - `quarantined`
  - `rejected`
  - `review_required`
  - `pending_approval`

Implementation touchpoints:
- verification API
- operator/proof surfaces
- replay and forensic detail views
- UI filters and status summaries

Exit criteria:
- the same workflow can be viewed through business-readable status and replay-verifiable detail
- no raw internal graph or signer internals become the primary public status language

### Slice 4 - Evidence and Replay

Goal: preserve the proof chain from decision to verification.

Work:
- ensure the governed receipt carries the proof basis needed for replay
- keep evidence references and custody context attached
- validate that replay surfaces can reconstruct the same decision basis

Implementation touchpoints:
- evidence bundle materialization
- replay service
- forensic block generation
- trust-page or operator proof rendering

Exit criteria:
- a transfer decision can be replayed from the stored artifacts
- evidence and replay views agree on the same authorization lineage

### Slice 5 - Hardening and Gate Enforcement

Goal: make the demo stable under real operational pressure.

Work:
- add CI and host gates for the new transfer path
- expand degraded-edge drills
- validate benchmark behavior under deployment-realistic topology
- keep the verification API contract stable while deployment wiring evolves

Implementation touchpoints:
- `scripts/host/verify_q2_verification_contracts.sh`
- `scripts/host/verify_q2_degraded_edge_drill_matrix.sh`
- `scripts/host/verify_productized_surface.sh`
- deployment verification scripts and kube/Ray lanes

Exit criteria:
- the demo passes host verification and a degraded drill
- the same flow is stable enough to run in a deployment-realistic environment

## Recommended Order

1. Finish approval-envelope persistence and lifecycle.
2. Wire the authorization output chain around the envelope.
3. Implement the verification projection and operator surface.
4. Lock replay/evidence linkage.
5. Add the host and deployment gates last, after the functional path is stable.

## Deliverables

The implementation should produce:

1. `TransferApprovalEnvelope` schema, lifecycle, and persistence path
2. allow/deny/quarantine policy-output examples for the transfer workflow
3. workflow-specific verification projection and read surface
4. replayable evidence linkage for the governed transfer path
5. host/deployment verification coverage for the new flow

## Definition Of Done

The next killer demo is done when:
- a transfer request can be dual-approved
- the PDP produces a governed authorization output
- the runtime issues replayable proof artifacts
- the verification surface shows a clear business-readable result
- the full path is covered by repeatable host checks

## References

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [design_partner_demo_schedule.md](/Users/ningli/project/seedcore/docs/development/design_partner_demo_schedule.md)
- [seedcore_2026_execution_plan.md](/Users/ningli/project/seedcore/docs/development/seedcore_2026_execution_plan.md)
- [contract_freeze_zero_trust_terms.md](/Users/ningli/project/seedcore/docs/development/contract_freeze_zero_trust_terms.md)
- [end_to_end_governance_demo_contract.md](/Users/ningli/project/seedcore/docs/development/end_to_end_governance_demo_contract.md)
- [pkg_authz_graph_rfc.md](/Users/ningli/project/seedcore/docs/development/pkg_authz_graph_rfc.md)
