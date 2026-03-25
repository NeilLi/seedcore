# Next Killer Demo Contract Freeze

## Goal

Define the next contract freeze that operationalizes the roadmap’s killer
demonstration:

```text
high-value asset transfer -> dual authorization -> governed execution ->
replayable third-party verification
```

This memo is the next strict-spec step after the current closed-loop demo
contract in
[end_to_end_governance_demo_contract.md](/Users/ningli/project/seedcore/docs/development/end_to_end_governance_demo_contract.md).

It does not replace the current baseline demo. It defines the contract work
needed for the next demonstration tier.

The execution center for this memo now lives in
[killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md).

## Why This Exists

The roadmap now points toward four connected tracks:

- trust hardening
- multi-party execution governance
- operational trust visibility
- workflow-specific verification surfaces

Those tracks should not start from vague product language. They need shared
contracts that frontend, backend, and trust-hardening work can all build
against.

The immediate next technical step is therefore:

- freeze the multi-party approval contract
- freeze the authorization output contract for dual-authorization transfer
- freeze the verification-surface projection contract

## Important Boundary Correction

This next step should not be described as inventing one giant
"multi-party `ActionIntent`" or one monolithic "dual-signed governed receipt."

SeedCore already freezes stricter runtime boundaries:

- `ActionIntent` remains the authorization request
- `ExecutionToken` remains the authorization artifact
- `EvidenceBundle` remains downstream evidence
- replay and trust-page surfaces remain downstream projections

See
[contract_freeze_zero_trust_terms.md](/Users/ningli/project/seedcore/docs/development/contract_freeze_zero_trust_terms.md).

For the next killer demo, the right move is to define a contract chain, not a
single overloaded artifact.

## Scope

This memo freezes the intended contract surfaces for one next-stage workflow:

**Restricted Custody Transfer**

That means:

- transfer of custody for a high-value asset
- dual authorization
- deterministic policy evaluation
- proof-bearing runtime artifacts
- replay-verifiable downstream projection

Canonical example:

- facility manager requests transfer
- quality inspector co-approves the transfer
- PDP evaluates the transfer against the active authorization graph
- runtime issues governed authorization artifacts
- verification surface shows a business-readable trust result

## Non-Goals

This memo does not:

- replace the current single-approval `RELEASE` demo contract
- require hardware-backed signing in the schema itself
- force multi-party state into top-level `ActionIntent` fields
- collapse `ExecutionToken`, `PolicyReceipt`, `TransitionReceipt`, and `EvidenceBundle` into one object
- define the final UI layout for the verification surface

## Frozen Contract Path For The Next Demo

The intended path for the next killer demo is:

```text
TaskPayload
  -> ActionIntent
  -> TransferApprovalEnvelope
  -> PolicyDecision / ExecutionToken / governed_receipt
  -> PolicyReceipt
  -> TransitionReceipt / EvidenceBundle
  -> VerificationSurfaceProjection
```

Notes:

- `ActionIntent` stays the accountable execution request.
- `TransferApprovalEnvelope` carries the multi-party approval state.
- `PolicyDecision.required_approvals` remains the deny/escalate path for missing approvals.
- `ExecutionToken` remains the only artifact that may unlock controlled execution.
- `governed_receipt`, `PolicyReceipt`, and `TransitionReceipt` remain distinct artifacts with different roles.

## Contract 1: TransferApprovalEnvelope

This should be treated as a governed approval object, not merely a loose
envelope.

This is the missing contract for dual-authorization workflows.

It should be persisted and referenced by the governed action, not fused into the
top-level `ActionIntent` schema.

Suggested JSON shape:

```json
{
  "approval_envelope_id": "approval-transfer-001",
  "workflow_type": "custody_transfer",
  "status": "APPROVED",
  "asset_ref": "asset:lot-8841",
  "lot_id": "lot-8841",
  "from_custodian_ref": "principal:facility_mgr_001",
  "to_custodian_ref": "principal:outbound_mgr_002",
  "transfer_context": {
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "facility_ref": "facility:north_warehouse",
    "custody_point_ref": "custody_point:handoff_bay_3"
  },
  "required_approvals": [
    {
      "role": "FACILITY_MANAGER",
      "principal_ref": "principal:facility_mgr_001",
      "status": "APPROVED",
      "approved_at": "2026-04-02T08:00:05Z",
      "approval_ref": "approval:facility_mgr_001"
    },
    {
      "role": "QUALITY_INSPECTOR",
      "principal_ref": "principal:quality_insp_017",
      "status": "APPROVED",
      "approved_at": "2026-04-02T08:00:12Z",
      "approval_ref": "approval:quality_insp_017"
    }
  ],
  "approval_binding_hash": "sha256:approval-binding-transfer-001",
  "policy_snapshot": "snapshot:pkg-prod-2026-04-02",
  "expires_at": "2026-04-02T08:05:00Z",
  "created_at": "2026-04-02T08:00:00Z"
}
```

### Why This Should Be Separate

- it gives Phase B a first-class approval contract
- it lets UI and API work track approval state without touching PDP internals
- it avoids overloading `ActionIntent` with mutable workflow state
- it gives receipts something stable to bind to later

## Approval Envelope Lifecycle Semantics

Before implementation, the lifecycle itself should be treated as frozen.

Allowed statuses:

- `PENDING`
- `PARTIALLY_APPROVED`
- `APPROVED`
- `EXPIRED`
- `REVOKED`
- `SUPERSEDED`

Lifecycle rules:

- approvals are append-only entries on the envelope history
- duplicate approvals for the same role are not allowed on the same envelope version
- an envelope cannot be reopened once it is `EXPIRED`, `REVOKED`, or `SUPERSEDED`
- a changed approval set or transfer condition produces a new envelope version rather than mutating history in place
- `approval_binding_hash` changes whenever approval-bearing state changes
- `ActionIntent` must reference the currently active envelope version only

Operational expectations:

- partial approval must still fail authorization unless policy explicitly allows staged progress
- revocation after partial or full approval invalidates the envelope for future authorization
- supersession must preserve replay linkage to older versions without allowing them to authorize new transfers

## Contract 2: ActionIntent Extension Pattern

The next demo should preserve the current top-level `ActionIntent` structure in
[src/seedcore/models/action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py).

Because that model already forbids arbitrary new top-level fields, the approval
reference should live in `action.parameters` and, when helpful, the
resource-specific transfer context should live in `resource.category_envelope`.

Suggested pattern:

```json
{
  "intent_id": "intent-transfer-001",
  "timestamp": "2026-04-02T08:00:15Z",
  "valid_until": "2026-04-02T08:01:15Z",
  "principal": {
    "agent_id": "agent:custody_runtime_01",
    "role_profile": "TRANSFER_COORDINATOR",
    "session_token": "session-transfer-001"
  },
  "action": {
    "type": "TRANSFER_CUSTODY",
    "operation": "MOVE",
    "parameters": {
      "approval_context": {
        "approval_envelope_id": "approval-transfer-001",
        "approval_binding_hash": "sha256:approval-binding-transfer-001",
        "required_roles": [
          "FACILITY_MANAGER",
          "QUALITY_INSPECTOR"
        ],
        "approved_by": [
          "principal:facility_mgr_001",
          "principal:quality_insp_017"
        ]
      }
    },
    "security_contract": {
      "hash": "policy-hash-transfer-001",
      "version": "rules@transfer-v1"
    }
  },
  "resource": {
    "asset_id": "asset:lot-8841",
    "target_zone": "handoff_bay_3",
    "provenance_hash": "asset-proof-hash-8841",
    "lot_id": "lot-8841",
    "category_envelope": {
      "transfer_context": {
        "from_zone": "vault_a",
        "to_zone": "handoff_bay_3",
        "expected_current_custodian": "principal:facility_mgr_001",
        "next_custodian": "principal:outbound_mgr_002"
      }
    }
  },
  "environment": {
    "origin_network": "network:warehouse_core"
  }
}
```

### Freeze Decision

For the next killer demo:

- keep `ActionIntent` single-accountable
- reference multi-party approval state rather than embedding every signer at the top level
- treat the approval envelope as an upstream prerequisite to authorization

## Contract 3: Dual-Authorization Policy Output

The next demo needs a strict allow-path authorization output contract. This is
not just an `ExecutionToken`. It is the combined policy output:

- `PolicyDecision`
- `ExecutionToken`
- `governed_receipt`
- `PolicyReceipt`

### 3A. PolicyDecision

The current `PolicyDecision` model already supports:

- `required_approvals`
- `authz_graph`
- `governed_receipt`

For the next demo, the transfer workflow should freeze these additional
expectations:

- `required_approvals` is populated when the approval envelope is missing or incomplete
- `disposition` remains one of `allow`, `deny`, `quarantine`, or `escalate`
- `authz_graph` explains both graph-based decision basis and missing transfer prerequisites
- `obligations` should be explicit in the decision path even when implemented as structured fields inside receipts or policy artifacts

### 3B. ExecutionToken

Suggested required `constraints` fields for the transfer demo:

```json
{
  "token_id": "token-transfer-001",
  "intent_id": "intent-transfer-001",
  "issued_at": "2026-04-02T08:00:16Z",
  "valid_until": "2026-04-02T08:01:16Z",
  "contract_version": "rules@transfer-v1",
  "signature": "{token_signature}",
  "constraints": {
    "action_type": "TRANSFER_CUSTODY",
    "asset_id": "asset:lot-8841",
    "from_zone": "vault_a",
    "target_zone": "handoff_bay_3",
    "expected_current_custodian": "principal:facility_mgr_001",
    "next_custodian": "principal:outbound_mgr_002",
    "approval_envelope_id": "approval-transfer-001",
    "approval_binding_hash": "sha256:approval-binding-transfer-001",
    "co_signed": true,
    "approved_by": [
      "principal:facility_mgr_001",
      "principal:quality_insp_017"
    ],
    "governed_receipt_hash": "receipt-transfer-001"
  }
}
```

### 3C. governed_receipt

The current governed receipt already carries transition-facing proof metadata.

For the transfer demo, freeze these expected fields:

```json
{
  "decision_hash": "receipt-transfer-001",
  "disposition": "allow",
  "snapshot_ref": "snapshot:pkg-prod-2026-04-02",
  "snapshot_version": "rules@transfer-v1",
  "principal_ref": "principal:agent:custody_runtime_01",
  "operation": "TRANSFER_CUSTODY",
  "asset_ref": "asset:lot-8841",
  "resource_ref": "resource:custody_transfer",
  "reason": "dual_authorization_transfer_allowed",
  "generated_at": "2026-04-02T08:00:16Z",
  "custody_proof": [
    "custody:state:vault_a",
    "approval:facility_mgr_001",
    "approval:quality_insp_017"
  ],
  "evidence_refs": [
    "approval-envelope:approval-transfer-001"
  ],
  "trust_gap_codes": [],
  "provenance_sources": [
    "policy:transfer_v1",
    "approval_binding:sha256:approval-binding-transfer-001"
  ],
  "advisory": {
    "approval_envelope_id": "approval-transfer-001",
    "co_signed": true
  }
}
```

### 3D. PolicyReceipt

`PolicyReceipt` should remain the signed artifact that binds the policy output
for replay and verification.

For the transfer demo, the signed `decision` payload should include at least:

- the final disposition
- the approval envelope reference
- the approved signers
- the custody transition context
- the governed receipt hash

## Minimum Explanation Payload

Before broader UI work, the next killer demo should freeze one minimum
explanation payload shape that every product projection must derive from.

Required fields:

- `disposition`
- `matched_policy_refs`
- `authority_path_summary`
- `missing_prerequisites`
- `trust_gaps`
- `minted_artifacts`
- `obligations`

This explanation contract should remain runtime-first. The verification surface
may summarize it, but must not redefine it.

## Contract 4: VerificationSurfaceProjection

This is the product-facing contract for Phase D.

It should translate technical policy and evidence state into business-readable
status without hiding the proof basis.

Rule:

`VerificationSurfaceProjection` is a downstream projection of `PolicyReceipt`,
`TransitionReceipt`, and `EvidenceBundle`. It must not invent authoritative
state that is not derivable from frozen runtime artifacts.

Suggested projection:

```json
{
  "workflow_id": "transfer-demo-001",
  "workflow_type": "custody_transfer",
  "status": "verified",
  "asset_ref": "asset:lot-8841",
  "summary": {
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "current_state": "verified_transfer_ready",
    "approval_state": "fully_approved",
    "quarantined": false
  },
  "approvals": {
    "required": [
      "FACILITY_MANAGER",
      "QUALITY_INSPECTOR"
    ],
    "completed_by": [
      "principal:facility_mgr_001",
      "principal:quality_insp_017"
    ],
    "approval_envelope_id": "approval-transfer-001"
  },
  "authorization": {
    "disposition": "allow",
    "governed_receipt_hash": "receipt-transfer-001",
    "policy_receipt_id": "policy-receipt-transfer-001",
    "execution_token_id": "token-transfer-001"
  },
  "verification": {
    "signature_valid": true,
    "policy_trace_available": true,
    "evidence_trace_available": true,
    "tamper_status": "clear"
  },
  "links": {
    "replay_ref": "replay:audit-transfer-001",
    "trust_ref": "trust:public-transfer-001"
  }
}
```

### Business-Readable Status Vocabulary

For the first workflow-specific verification surface, freeze these public-facing
states:

- `verified`
- `quarantined`
- `rejected`
- `review_required`
- `pending_approval`

Avoid exposing raw internal status language such as:

- graph edge mismatch
- signer verification branch
- receipt closure internals

Those should remain supporting detail under drill-down views.

## Deliverables

The next contract freeze should produce three concrete deliverables:

1. `TransferApprovalEnvelope` schema and lifecycle
2. dual-authorization transfer policy output examples
3. verification-surface projection schema for the first governed workflow

Optional but useful fourth deliverable:

4. deny and quarantine examples for incomplete approvals, stale telemetry, and custody mismatch

## Versioning Discipline

For the next killer demo, each artifact family should have explicit ownership
and replay-preservation rules.

- `TransferApprovalEnvelope`: owned by the governed workflow domain; new lifecycle semantics require a version bump and older versions must remain replay-addressable
- `PolicyDecision` and `ExecutionToken.constraints`: owned by the authorization runtime; new required fields must preserve backward-compatible replay reading for prior demos
- `governed_receipt` and `PolicyReceipt`: owned by the policy-and-proof boundary; deprecations must preserve signature verification for historical artifacts
- `VerificationSurfaceProjection`: owned by the proof surface; projection changes must remain derivable from the same authoritative artifacts

## What This Unlocks

This contract freeze allows work to proceed in parallel without collapsing
boundaries:

- backend can implement approval persistence and PDP evaluation rules
- trust-hardening work can define signer, receipt, and verification controls against real payloads
- frontend can build the workflow-specific verification surface against stable projection fields
- replay and trust-page work can bind to the same approval and receipt references

## Recommended Next Implementation Order

1. Freeze the `TransferApprovalEnvelope` examples and lifecycle states.
2. Freeze one allow-path and two deny/quarantine-path authorization outputs.
3. Freeze the verification projection for the workflow-specific trust surface.
4. Only then wire KMS-backed signing and the first workflow-specific UI.

## References

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md)
- [contract_freeze_zero_trust_terms.md](/Users/ningli/project/seedcore/docs/development/contract_freeze_zero_trust_terms.md)
- [end_to_end_governance_demo_contract.md](/Users/ningli/project/seedcore/docs/development/end_to_end_governance_demo_contract.md)
- [pkg_authz_graph_rfc.md](/Users/ningli/project/seedcore/docs/development/pkg_authz_graph_rfc.md)
- [action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py)
- [evidence_bundle.py](/Users/ningli/project/seedcore/src/seedcore/models/evidence_bundle.py)
