# SeedCore Q2 2026 Product Spec

Date: 2026-04-02  
Status: Working product spec (Q2 core surfaces implemented; closure sequence active)

## Implementation Status Update (2026-04-02)

This spec now has a concrete implementation baseline in the repository for the
RCT slice.

Update (2026-04-02, closure pass):

- Screen 1: business-readable **status summary strip** (counts + filter chips), filter form **prefill** from query string, **envelope** / **request id** filters on queue API and console form, trust-alerts panel caption aligned to Q2 categories.
- Screen 2: **Request / scope / approvals** fields aligned to spec (workflow type, valid until, idempotency, full hardware fingerprint, authority scope block, approvals + co-signed heuristic).
- Screen 4: **Verification summary** (signature / traces / tamper), **Verification actions** (replay + projection + runbook lookup links).
- Shared shell: search supports **`envelope:`** / **`approval:`** and **`request:`** prefixes routing to queue filters.
- Runbooks: three new JSON entries (**stale telemetry**, **authority scope mismatch**, **snapshot not ready**) plus operator **preset lookup** links when `SEEDCORE_VERIFICATION_API_BASE` is set.

Implemented in code:

- `VerificationSurfaceProjection`, `TransferAuditTrail`, and
  `AssetForensicProjection` are implemented as first-class read contracts.
- business-readable status vocabulary includes:
  `verified`, `quarantined`, `rejected`, `review_required`, `pending_approval`.
- verification service namespace is migrated to `/api/v1/verification/*`.
- Screen 2 side-by-side, three-column audit trail is implemented and correlated
  by workflow/audit join key.
- Screen 3 asset forensic view is wired to contract-driven payloads.
- Screen 1 queue API and console view are implemented through
  `GET /api/v1/verification/transfers/queue` and `/queue`.
- queue rows now include `product_ref`, `updated_at`, `trust_alerts`, and a
  `trust_alert` filter that stays intact through drill-down navigation.
- Screen 4 replay/verification page is implemented in operator console via
  workflow-scoped detail payloads.
- workflow-scoped replay detail payload is implemented through
  `GET /api/v1/verification/workflows/{workflow_id}/verification-detail`
  (`seedcore.verification_detail.v1`).
- dedicated replay contract is implemented through
  `GET /api/v1/verification/workflows/{workflow_id}/replay`
  (`seedcore.verification_replay.v1`).
- runbook index and entry routes are implemented under
  `/api/v1/verification/runbook` and
  `/api/v1/verification/runbook/{slug}` and are surfaced on replay failure
  panels.
- runbook lookup is implemented under `/api/v1/verification/runbook/lookup`
  for status/reason-driven assistance links.
- runtime parity is implemented for
  `/api/v1/verification/assets/{asset_ref}/forensics` via subject-based runtime
  lookup.
- hot-path operator visibility now has a Prometheus text endpoint at
  `/api/v1/pdp/hot-path/metrics`.
- the edge telemetry schema is now exported at
  `docs/schemas/edge_telemetry_envelope_v0.schema.json`.
- links between status/review/forensics/proof surfaces are projection-derived.

Still open for full Q2 closure:

- CI/CD enforcement for full Q2 acceptance matrix across environments
- deployment-realistic observability and alert validation for the hot-path
  operator story
- adversarial and degraded-edge-condition acceptance coverage for the Q2
  verification slice (pytest drill matrix is in repo; broaden to live envs)
- ~~read-only Gemini-visible verification tools~~ **Initial bundle shipped:** MCP tools
  `seedcore.verification.*` and `seedcore.hotpath.metrics` (see
  `skills/using-seedcore/references/gemini-tools.md`)

## Scheduled Closure Sequence (2026-04-02)

The remaining Q2 UI/product work should now run in this order:

1. **2026-04-02 to 2026-04-12: acceptance gate closure**
   - make queue/detail/replay/runbook/forensics checks mandatory in CI
   - keep the TS operator verification slice and Python replay/parity checks in
     the same pass/fail envelope
2. **2026-04-08 to 2026-04-19: observability closure**
   - wire deployment role and alert export so the shell banners and failure
     surfaces reflect deployment-realistic hot-path state
3. **2026-04-15 to 2026-04-30: adversarial Q2 sign-off**
   - add replay-injection, stale-graph, and coordinate-tamper scenarios to the
     operator-facing acceptance matrix
4. **2026-05-01 onward: Q3 bridge**
   - keep the four-screen surface stable while external-agent adapters and edge
     telemetry closure work land behind the same contracts

## Audit-Trail UI for Restricted Custody Transfer

## 1. Product goal

Build the first operator-facing verification surface for SeedCore's canonical
workflow so an operator, partner, or evaluator can inspect one governed
transfer and answer:

- what was requested
- who had authority
- what SeedCore decided
- what evidence was attached
- whether settlement or closure is trustworthy
- how to replay or verify the result.

This Q2 UI is not the full Q4 pilot surface. It is the thin visible layer on
top of frozen status vocabulary, receipt-chain projection, operator status APIs,
and the first forensic block contract.

## 2. Scope and non-goals

### In scope for Q2

- workflow-specific status view for Restricted Custody Transfer
- business-readable trust states
- operator status tracking for prerequisite, approval, readiness, and governed
  outcome
- asset-centric forensic detail view
- side-by-side audit trail for:
  - request
  - transaction or authorization trail
  - physical replay or evidence timeline
- replay and trust links for approved users

### Explicitly out of scope for Q2

- multi-workflow UI
- generic trust portal
- broad robotics operations console
- full public verification package
- polished partner-facing marketing UX before contracts are frozen

## 3. Primary users

### A. Trust operator

Needs to understand status, missing prerequisites, trust gaps, and next action.

### B. Internal product or engineering reviewer

Needs artifact lineage, receipt IDs, replay references, policy snapshot, and
signer provenance.

### C. Design-partner evaluator

Needs an externally legible proof story for one completed transfer, without
reading source code.

## 4. Product principles

1. Business-readable first, proof-preserving second  
   Public-facing states should be `verified`, `quarantined`, `rejected`,
   `review_required`, and `pending_approval`, while internal failure classes
   stay in drill-down detail.
2. One transfer, one evidence model, one replay view  
   Avoid dashboard sprawl.
3. Receipts are the product artifact  
   UI is a visibility layer over governed receipts and replay-verifiable chains.
4. Every screen must map to a frozen contract  
   Freeze the verification projection before broad UI wiring.

## 5. Information architecture

Q2 should ship 4 screens and 1 shared shell.

### Shared shell

- top nav: `Transfers`, `Verification`, `Runbooks`
- search by:
  - `audit_id`
  - `workflow_id`
  - `asset_ref`
  - `request_id`
  - `approval_envelope_id`
- global status badge using business-readable vocabulary
- environment banner: `shadow`, later `canary`, `enforce`
- freshness banner for graph and telemetry readiness

### Screen 1: Transfer Queue / Workflow Status

### Screen 2: Transfer Detail / Audit-Trail View

### Screen 3: Asset-Centric Forensic View

### Screen 4: Replay / Verification View

## 6. Screen-by-screen spec

## Screen 1 - Transfer Queue / Workflow Status

### Purpose

Provide the operator-facing status API surface for the canonical transfer chain:

- prerequisite state
- approval state
- transfer readiness
- governed timeline

### Primary modules

1. Transfer list table
   - workflow ID
   - asset ref
   - product ref
   - current status
   - approval state
   - disposition
   - transfer readiness
   - updated at
2. Status summary strip
   - pending approval
   - verified
   - quarantined
   - rejected
   - review required
3. Trust alerts panel
   - stale telemetry
   - scope unverified
   - freshness violation
   - replay not ready
   - missing audit ID
4. Filter bar
   - status
   - disposition
   - facility
   - zone
   - approval completeness
   - replay readiness

### Required backend fields

```json
{
  "workflow_id": "transfer-demo-001",
  "workflow_type": "custody_transfer",
  "asset_ref": "asset:lot-8841",
  "product_ref": "shopify:gid://shopify/Product/1234567890",
  "status": "pending_approval",
  "summary": {
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "current_state": "awaiting_approval",
    "approval_state": "partially_approved",
    "quarantined": false
  },
  "authorization": {
    "disposition": "escalate"
  },
  "approvals": {
    "required": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
    "completed_by": ["principal:facility_mgr_001"],
    "approval_envelope_id": "approval-transfer-001"
  },
  "verification": {
    "signature_valid": true,
    "policy_trace_available": true,
    "evidence_trace_available": false,
    "tamper_status": "clear"
  },
  "links": {
    "replay_ref": "replay:audit-transfer-001"
  },
  "updated_at": "2026-04-01T10:00:01Z"
}
```

### API recommendation

`GET /api/v1/verification/transfers/queue?status=&disposition=&facility=&zone=&approval_state=&replay_readiness=`

### Q2 acceptance criteria

- operator can identify all transfers by business-readable state
- operator can distinguish `pending_approval` vs `quarantined` vs `rejected`
- queue fails closed when no `audit_id` or replay join key is available

## Screen 2 - Transfer Detail / Audit-Trail View

### Purpose

This is the centerpiece screen. It must correlate:

- natural-language or agent request
- digital transaction trail
- physical replay or evidence timeline

### Layout

Three-column structure:

#### Left column: Request and authority

- request summary
- principal identity
- delegation or approval chain
- authority scope
- hardware fingerprint

#### Center column: Decision and artifacts

- SeedCore disposition
- explanation
- policy snapshot
- minted artifacts
- receipt lineage

#### Right column: Physical evidence and closure

- current zone or coordinate
- evidence refs
- forensic block summary
- settlement status
- replay readiness

### Modules

#### 2.1 Request card

Show:

- request ID
- requested at
- natural-language request summary
- workflow type
- action type
- valid until
- idempotency key

Fields source:

- gateway request shape
- workflow projection

#### 2.2 Principal and authority card

Show:

- agent ID
- role profile
- owner ID
- delegation ref
- organization ref
- session token present? yes or no
- hardware fingerprint ID
- node ID
- public key fingerprint
- attestation type

These are explicit parts of the Agent Action Gateway contract.

#### 2.3 Scope card

Show:

- scope ID
- asset ref
- product ref
- facility ref
- expected from or to zone
- expected coordinate ref
- max radius meters
- authority scope verdict

#### 2.4 Decision card

Show:

- allowed: true or false
- disposition: allow / deny / quarantine / escalate
- reason code
- reason
- policy snapshot ref
- latency ms

These are required response fields.

#### 2.5 Approvals card

Show:

- required approvers
- completed approvers
- approval envelope ID
- expected envelope version
- co-signed? yes or no

Aligned with approval projection and transfer envelope contract-freeze
direction.

#### 2.6 Minted artifacts card

Show:

- execution token ID
- policy receipt ID
- transition receipt IDs
- governed receipt hash
- audit ID
- forensic block ID

#### 2.7 Evidence or closure card

Show:

- evidence bundle ID
- node ID
- current zone
- current coordinate ref
- physical presence hash
- actuator hash
- reason trace ref
- replay ready? yes or no
- settlement status

These map to closure scaffold and forensic linkage.

### Required backend fields

```json
{
  "request": {
    "request_id": "req-transfer-2026-0001",
    "requested_at": "2026-04-01T10:00:00Z",
    "workflow_type": "restricted_custody_transfer",
    "action_type": "TRANSFER_CUSTODY",
    "valid_until": "2026-04-01T10:01:00Z",
    "idempotency_key": "idem-transfer-2026-0001",
    "request_summary": "Buyer-side agent requested custody transfer for tea set lot 8841"
  },
  "principal": {
    "agent_id": "agent:buyer_runtime_01",
    "role_profile": "TRANSFER_COORDINATOR",
    "owner_id": "did:seedcore:owner:acme-001",
    "delegation_ref": "delegation:owner-8841-transfer",
    "organization_ref": "org:warehouse-north",
    "hardware_fingerprint": {
      "fingerprint_id": "fp:jetson-orin-01",
      "node_id": "node:jetson-orin-01",
      "public_key_fingerprint": "sha256:device-key-fingerprint",
      "attestation_type": "tpm",
      "key_ref": "tpm2:jetson-orin-01-ak"
    }
  },
  "scope": {
    "scope_id": "scope:rct-2026-0001",
    "asset_ref": "asset:lot-8841",
    "product_ref": "shopify:gid://shopify/Product/1234567890",
    "facility_ref": "facility:warehouse-north",
    "expected_from_zone": "vault_a",
    "expected_to_zone": "handoff_bay_3",
    "expected_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
    "max_radius_meters": 0.5,
    "authority_scope_verdict": {
      "status": "matched",
      "mismatch_keys": []
    }
  },
  "decision": {
    "allowed": true,
    "disposition": "allow",
    "reason_code": "restricted_custody_transfer_allowed",
    "reason": "all mandatory checks passed",
    "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-01",
    "latency_ms": 42
  },
  "approvals": {
    "required": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
    "completed_by": [
      "principal:facility_mgr_001",
      "principal:quality_insp_017"
    ],
    "approval_envelope_id": "approval-transfer-001",
    "expected_envelope_version": "23"
  },
  "artifacts": {
    "execution_token_id": "token-123",
    "policy_receipt_id": "receipt-policy-1",
    "transition_receipt_ids": ["receipt-transition-1"],
    "audit_id": "audit-abc",
    "forensic_block_id": "fb-2026-0001"
  },
  "closure": {
    "evidence_bundle_id": "evb-123",
    "node_id": "node:jetson-orin-01",
    "current_zone": "handoff_bay_3",
    "current_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
    "replay_status": "pending",
    "settlement_status": "pending"
  }
}
```

### API recommendation

`GET /api/v1/verification/transfers/{workflow_id}`

## Screen 3 - Asset-Centric Forensic View

### Purpose

Deliver the single forensic view that binds:

- decision hash
- policy snapshot
- principal identity
- custody transition
- telemetry refs
- signature provenance
- economic settlement status

### Modules

#### 3.1 Asset identity card

- asset ref
- lot ID
- product ref
- quote or order ref
- provenance hash
- declared value

#### 3.2 Custody chain card

- from custodian
- to custodian
- from zone
- to zone
- custody proof refs
- transition events

#### 3.3 Forensic fingerprint card

Show the canonical four evidence classes:

- economic hash
- physical presence hash
- reasoning hash
- actuator hash

#### 3.4 Signer provenance card

- policy receipt signer
- transition receipt signer
- key refs
- KMS or TPM provenance
- signature validity
- tamper status

#### 3.5 Settlement and twin card

- settlement status
- twin mutation ref
- location at closure
- environmental readings
- hardware health
- finalized at

These are required directionally by Workstream 3 and 4, even if some fields are
placeholders in Q2.

### Required backend fields

```json
{
  "asset": {
    "asset_ref": "asset:lot-8841",
    "lot_id": "lot-8841",
    "product_ref": "shopify:gid://shopify/Product/1234567890",
    "quote_ref": "shopify:quote:tea-set-2026-04-01-0001",
    "provenance_hash": "sha256:asset-provenance",
    "declared_value_usd": 1500
  },
  "custody": {
    "from_custodian_ref": "principal:facility_mgr_001",
    "to_custodian_ref": "principal:outbound_mgr_002",
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "custody_proof": [
      "custody:state:vault_a",
      "approval:facility_mgr_001",
      "approval:quality_insp_017"
    ]
  },
  "forensic_fingerprint": {
    "economic_hash": "sha256:shopify-order",
    "physical_presence_hash": "sha256:gazebo-point-cloud",
    "reasoning_hash": "sha256:reason-trace",
    "actuator_hash": "sha256:unitree-b2-torque"
  },
  "signer_provenance": {
    "policy_receipt_id": "policy-receipt-transfer-001",
    "transition_receipt_ids": ["receipt-transition-1"],
    "signature_valid": true,
    "tamper_status": "clear",
    "key_ref": "kms:rct-live-signoff-p256"
  },
  "settlement": {
    "status": "pending",
    "twin_mutation_ref": null,
    "physical_location_ref": "gazebo://warehouse-north/shelf/A3",
    "environmental_readings": null,
    "hardware_health": null
  }
}
```

### API recommendation

`GET /api/v1/verification/assets/forensics?audit_id=...|intent_id=...|subject_id=...`

## Screen 4 - Replay / Verification View

### Purpose

Expose the replay-verifiable receipt chain and trust-page style verification for
approved stakeholders.

### Modules

#### 4.1 Verification summary

- workflow ID
- status
- asset ref
- approval state
- disposition
- signature valid
- evidence trace available
- tamper status

#### 4.2 Receipt chain timeline

- approval envelope
- governed receipt
- policy receipt
- transition receipt(s)
- forensic block
- replay ref
- trust ref

#### 4.3 Verification actions

- verify signatures
- open replay artifact
- export proof bundle
- inspect signer provenance
- inspect trust gaps

#### 4.4 Failure or contradiction panel

For deny or quarantine paths:

- trust gap codes
- mismatch keys
- stale telemetry flags
- recommended next actions:
  - investigate scope mismatch
  - quarantine asset
  - review forensic block

### Required backend fields

Use `VerificationSurfaceProjection` as the core contract.

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
    "required": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
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

This should be the frontend's primary read model.

### API recommendation

`GET /api/v1/verification/workflows/{workflow_id}/projection`
`GET /api/v1/verification/workflows/{workflow_id}/verification-detail`

## 7. Shared backend contract model

For Q2, keep to three read models:

### A. `VerificationSurfaceProjection`

Primary UI projection for status, summary, and verification links.

### B. `TransferAuditTrail`

Composable detail model for Screen 2.

### C. `AssetForensicProjection`

Asset-centric forensic model for Screen 3.

This prevents the UI from depending directly on raw internal receipts or
coordinator state.

## 8. Business-readable status vocabulary

Freeze this in Q2 and use it consistently:

- `verified`
- `quarantined`
- `rejected`
- `review_required`
- `pending_approval`

### Suggested mapping

- `allow` + valid signatures + evidence trace present + no tamper =>
  `verified`
- `quarantine` => `quarantined`
- `deny` => `rejected`
- `escalate` => `review_required`
- incomplete approvals => `pending_approval`

Do not expose raw internal states like graph mismatch branches on first load.
Those belong in drill-down detail.

## 9. Demo flow for Q2

The demo should use the captured RCT sign-off bundle and the four canonical
outcomes present in runtime evidence: `allow`, `deny`, `quarantine`,
`escalate`.

### Demo 1 - Happy path: verified transfer

1. Open Transfer Queue
2. Filter to `verified`
3. Open workflow `transfer-demo-001`
4. Show:
   - buyer-side agent request
   - dual approval complete
   - scope matched
   - device fingerprint matched
   - `allow` returned
   - execution token + policy receipt minted
5. Open asset forensic view
6. Highlight:
   - economic hash
   - physical presence hash
   - reasoning hash
   - actuator hash
7. Open replay view
8. Show signature validity and replay ref

Point to make: SeedCore proves not just authorization, but converged digital
and physical evidence.

### Demo 2 - Quarantine path: stale or incomplete proof

1. Return to queue
2. Filter to `quarantined`
3. Open quarantined workflow
4. Show:
   - approval maybe complete
   - scope not contradictory, but telemetry stale or unverifiable
   - business-readable status = `quarantined`
   - next action = investigation or await fresh evidence

Point to make: missing or stale proof becomes governed business state, not
silent failure.

### Demo 3 - Rejected path: scope contradiction

1. Filter to `rejected`
2. Show coordinate or asset/product mismatch
3. Highlight authority scope verdict = `mismatch`
4. Show deterministic reason code:
   - `authority_scope_mismatch`
   - `coordinate_scope_mismatch`
   - or `asset_product_scope_mismatch`

Point to make: contradiction leads to `deny`, not ambiguity.

### Demo 4 - Review required

1. Filter to `review_required`
2. Show missing human/governance release path
3. Highlight this as governed escalation, not generic error handling

Point to make: human review is an explicit runtime outcome.

## 10. MVP data requirements

To support the Q2 UI, backend must expose these fields reliably.

### Identity or authority

- `request_id`
- `workflow_id`
- `asset_ref`
- `product_ref`
- `principal.agent_id`
- `principal.role_profile`
- `delegation_ref`
- `approval_envelope_id`
- `approval_envelope_version`
- `hardware_fingerprint.fingerprint_id`
- `hardware_fingerprint.public_key_fingerprint`
- `authority_scope.scope_id`
- `expected_coordinate_ref`
- `expected_from_zone`
- `expected_to_zone`

### Decision or status

- `decision.disposition`
- `decision.reason_code`
- `decision.reason`
- `policy_snapshot_ref`
- `latency_ms`
- `status` (business-readable)
- `trust_gap_codes`
- `authority_scope_verdict.status`
- `fingerprint_verdict.status`

### Artifact lineage

- `audit_id`
- `governed_receipt_hash`
- `policy_receipt_id`
- `transition_receipt_ids`
- `execution_token_id`
- `forensic_block_id`
- `replay_ref`
- `trust_ref`

### Evidence or closure

- `evidence_bundle_id`
- `current_zone`
- `current_coordinate_ref`
- `economic_hash`
- `physical_presence_hash`
- `reasoning_hash`
- `actuator_hash`
- `settlement_status`
- `replay_status`
- `tamper_status`
- `signature_valid`

## 11. Suggested API surface

For Q2, keep it narrow and explicitly separate current implementation from
next additions.

### Implemented in current verification service

- `GET /api/v1/verification/transfers`
- `GET /api/v1/verification/transfers/catalog`
- `GET /api/v1/verification/transfers/queue`
- `GET /api/v1/verification/transfers/status`
- `GET /api/v1/verification/transfers/audit-trail`
- `GET /api/v1/verification/transfers/{workflow_id}`
- `GET /api/v1/verification/workflows/{workflow_id}/projection`
- `GET /api/v1/verification/workflows/{workflow_id}/verification-detail`
- `GET /api/v1/verification/assets/forensics`
- `GET /api/v1/verification/assets/{asset_ref}/forensics` (fixture-oriented resolver)
- `GET /api/v1/verification/transfers/summary`
- `GET /api/v1/verification/transfers/proof`
- `GET /api/v1/verification/assets/proof`

### Deferred or next-step additions

- `GET /api/v1/verification/replay/{audit_id}` (or equivalent projection route)
- `GET /api/v1/verification/runbooks/{status_or_reason_code}`

All endpoints should remain read-only projections over existing sources of
truth.

## 12. Q2 success criteria for the UI

The Audit-Trail UI is successful in Q2 if:

- an operator can explain any of the four canonical outcomes without opening
  logs
- a reviewer can trace one transfer from request to receipts to evidence to
  replay
- a non-engineer can distinguish `verified`, `quarantined`, `rejected`, and
  `review_required`
- the UI is backed by frozen projection fields, not ad hoc joins
- the UI remains narrow: one asset class, one transfer chain, one replay view

## 13. Recommended build order

1. ~~Freeze `VerificationSurfaceProjection`~~ **Done**
2. ~~Freeze one allow-path payload and two deny/quarantine examples~~ **Done**
3. ~~Implement operator status API~~ **Done (verification namespace)**
4. ~~Implement transfer detail page~~ **Done (Screen 2 side-by-side)**
5. ~~Implement asset forensic page~~ **Done (Screen 3 contract-driven)**
6. ~~Implement replay or verification page enhancements and namespace alignment~~ **Done (Screen 4 verification summary + actions; dedicated `/replay` links)**
7. ~~Add runbooks for lookup and investigation~~ **Done (expanded runbook corpus + preset lookups + `/runbook/lookup`)**

## 14. Strong recommendation

Build this UI as a governed case viewer, not a dashboard.

That framing is closer to the category:

**SeedCore is the verifiable agentic ledger for one high-trust workflow.**

The UI should feel like opening an aircraft incident recorder for one governed
transfer, not browsing admin analytics.
