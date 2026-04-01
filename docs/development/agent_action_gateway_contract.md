# Agent Action Gateway Contract (v1 Draft)

Date: 2026-04-01
Status: Draft contract for Q3 2026 productization

## Purpose

This document defines the first external contract for agent-originated governed
actions in SeedCore.

It is intentionally narrow and workflow-specific:

- workflow: `Restricted Custody Transfer`
- runtime outcome: `allow`, `deny`, `quarantine`, `escalate`
- authority model: delegated principal + persisted approval envelope +
  transaction-specific scope
- proof model: replayable decision, receipt, and forensic-block linkage

This is a product boundary contract, not an internal coordinator schema.

## Scope

This v1 draft defines:

- request and response shapes for the Agent Action Gateway
- deterministic mapping to `ActionIntent` and hot-path evaluation inputs
- transaction-specific authority scope for the canonical workflow
- device or hardware fingerprint fields for agent accountability
- minimum forensic-block linkage needed for replay correlation
- idempotency and error handling expectations
- minimum observability and proof linkage fields

This v1 draft does not require replacing existing internal endpoints
immediately.

## Non-Goals

This contract does not aim to:

- support every workflow in SeedCore
- define a general no-code agent orchestration language
- replace `ActionIntent` as the runtime accountability contract
- collapse policy receipts, transition receipts, and evidence into one object
- define a universal robotics or commerce adapter protocol in one pass

## Design Rules

The gateway should preserve four rules from the 2026 roadmap:

- the caller proves delegated authority, not ambient authority
- execution authority is scoped to the intended product or asset and physical
  scope
- forensic replay must be correlatable from the first gateway request onward
- scope mismatches are governed outcomes, not ambiguous implementation details

## Contract Version

Gateway contract version:

- `seedcore.agent_action_gateway.v1`

Downstream hot-path contract reference:

- `pdp.hot_path.asset_transfer.v1`

## Proposed Endpoint Surface

Primary endpoint:

- `POST /api/v1/agent-actions/evaluate`

Optional idempotency retrieval endpoint (recommended):

- `GET /api/v1/agent-actions/requests/{request_id}`

Optional closure endpoints (v1 scaffold):

- `POST /api/v1/agent-actions/{request_id}/closures`
- `GET /api/v1/agent-actions/closures/{closure_id}`

The evaluate endpoint should be the only required call for v1 clients.

## Terminology Note

In this contract, schema field names still use `asset` for compatibility with
the current runtime and hot-path models.

Product meaning:

- `asset` should be read as a custody-controlled physical good, lot, batch,
  shipment, container, or other real-world item under governed transfer
- `product_ref` is the external commerce-facing identity when the workflow
  includes a commerce system such as Shopify Sandbox
- this contract does not imply a digital-asset-only scope

## Request Contract

### Top-Level Shape

```json
{
  "contract_version": "seedcore.agent_action_gateway.v1",
  "request_id": "req-transfer-2026-0001",
  "requested_at": "2026-04-01T10:00:00Z",
  "idempotency_key": "idem-transfer-2026-0001",
  "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-01",
  "principal": {
    "agent_id": "agent:buyer_runtime_01",
    "role_profile": "TRANSFER_COORDINATOR",
    "session_token": "session-abc",
    "actor_token": null,
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
  "workflow": {
    "type": "restricted_custody_transfer",
    "action_type": "TRANSFER_CUSTODY",
    "valid_until": "2026-04-01T10:01:00Z"
  },
  "asset": {
    "asset_id": "asset:lot-8841",
    "lot_id": "lot-8841",
    "product_ref": "shopify:gid://shopify/Product/1234567890",
    "quote_ref": "shopify:quote:tea-set-2026-04-01-0001",
    "from_custodian_ref": "principal:facility_mgr_001",
    "to_custodian_ref": "principal:outbound_mgr_002",
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "provenance_hash": "sha256:asset-provenance",
    "declared_value_usd": 1500
  },
  "approval": {
    "approval_envelope_id": "approval-transfer-001",
    "expected_envelope_version": "23"
  },
  "authority_scope": {
    "scope_id": "scope:rct-2026-0001",
    "asset_ref": "asset:lot-8841",
    "product_ref": "shopify:gid://shopify/Product/1234567890",
    "facility_ref": "facility:warehouse-north",
    "expected_from_zone": "vault_a",
    "expected_to_zone": "handoff_bay_3",
    "expected_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
    "max_radius_meters": 0.5
  },
  "telemetry": {
    "observed_at": "2026-04-01T09:59:58Z",
    "freshness_seconds": 2,
    "max_allowed_age_seconds": 300,
    "current_zone": "vault_a",
    "current_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
    "evidence_refs": [
      "ev:cam-1",
      "ev:seal-sensor-7"
    ]
  },
  "forensic_context": {
    "reason_trace_ref": "reason:llm-inference-001",
    "fingerprint_components": {
      "economic_hash": "sha256:shopify-quote",
      "physical_presence_hash": "sha256:gazebo-point-cloud",
      "reasoning_hash": "sha256:reason-trace",
      "actuator_hash": "sha256:unitree-b2-torque"
    }
  },
  "security_contract": {
    "hash": "sha256:contract-hash",
    "version": "rules@8.0.0"
  },
  "options": {
    "debug": false,
    "no_execute": false
  }
}
```

`options.no_execute=true` enables preflight evaluation mode: policy and trust-gap
evaluation still run, but `ExecutionToken` is withheld.

### Required Request Rules

Required fields:

- `contract_version`
- `request_id`
- `requested_at`
- `idempotency_key`
- `principal.agent_id`
- `principal.role_profile`
- one of `principal.session_token` or `principal.actor_token`
- `principal.hardware_fingerprint.fingerprint_id`
- `principal.hardware_fingerprint.public_key_fingerprint`
- `workflow.type`
- `workflow.action_type`
- `workflow.valid_until`
- `asset.asset_id`
- `asset.provenance_hash`
- `approval.approval_envelope_id`
- `authority_scope.scope_id`
- `authority_scope.asset_ref`
- at least one of:
  - `authority_scope.expected_to_zone`
  - `authority_scope.expected_coordinate_ref`
- `telemetry.observed_at`
- `security_contract.hash`
- `security_contract.version`

Normalization rules:

- timestamps must be ISO-8601 UTC
- empty strings are invalid for required string fields
- `workflow.type` must be `restricted_custody_transfer` in v1
- `authority_scope.asset_ref` must equal `asset.asset_id`
- if both are present, `asset.product_ref` must equal `authority_scope.product_ref`
- unknown top-level fields should be rejected (`422`)

### Scope Validation Rules

The gateway must treat physical scope as part of authority, not only telemetry.

Minimum rules:

- the requested scope must resolve to one persisted or reconstructable authority
  scope
- the requested asset and product identity must not contradict that scope
- the request telemetry must not contradict the expected zone or coordinate when
  both are present
- missing scope evidence is a trust-gap problem
- contradictory scope evidence is a mismatch problem

This distinction matters:

- mismatch -> `deny` when the contradiction is deterministic
- incomplete or stale proof -> `quarantine` when the chain is insufficient but
  not contradictory

## Deterministic Mapping To Runtime Contracts

The gateway should map request payloads to internal runtime models as follows.

### `ActionIntent` Mapping

`ActionIntent.intent_id`:

- `request_id`

`ActionIntent.timestamp`:

- `requested_at`

`ActionIntent.valid_until`:

- `workflow.valid_until`

`ActionIntent.principal.agent_id`:

- `principal.agent_id`

`ActionIntent.principal.role_profile`:

- `principal.role_profile`

`ActionIntent.principal.session_token`:

- `principal.session_token` (or empty if `actor_token` provided)

`ActionIntent.principal.actor_token`:

- `principal.actor_token`

`ActionIntent.principal.public_key_fingerprint`:

- `principal.hardware_fingerprint.public_key_fingerprint`

`ActionIntent.action.type`:

- `workflow.action_type`

`ActionIntent.action.security_contract.hash`:

- `security_contract.hash`

`ActionIntent.action.security_contract.version`:

- `security_contract.version`

`ActionIntent.action.parameters` (minimum):

- `approval_context.approval_envelope_id`
- `approval_context.expected_envelope_version`
- `gateway.idempotency_key`
- `gateway.owner_id` (when provided)
- `gateway.delegation_ref`
- `gateway.organization_ref`
- `gateway.scope_id`
- `gateway.expected_coordinate_ref`
- `gateway.expected_from_zone`
- `gateway.expected_to_zone`
- `gateway.hardware_fingerprint_id`
- `gateway.hardware_public_key_fingerprint`
- `gateway.reason_trace_ref`
- `value_usd` from `asset.declared_value_usd` when provided

`ActionIntent.resource.asset_id`:

- `asset.asset_id`

`ActionIntent.resource.target_zone`:

- `asset.to_zone` or `authority_scope.expected_to_zone`

`ActionIntent.resource.provenance_hash`:

- `asset.provenance_hash`

`ActionIntent.resource.lot_id`:

- `asset.lot_id`

`ActionIntent.resource.category_envelope` (minimum):

- `from_custodian_ref`
- `to_custodian_ref`
- `from_zone`
- `to_zone`
- `product_ref` when provided
- `expected_coordinate_ref` when provided

### Hot-Path Input Mapping

The mapped `ActionIntent` plus request context should be transformed into:

- `HotPathEvaluateRequest.contract_version = "pdp.hot_path.asset_transfer.v1"`
- `HotPathEvaluateRequest.request_id = request_id`
- `HotPathEvaluateRequest.requested_at = requested_at`
- `HotPathEvaluateRequest.policy_snapshot_ref = policy_snapshot_ref or security_contract.version`
- `HotPathEvaluateRequest.asset_context.asset_ref = asset.asset_id`
- `HotPathEvaluateRequest.telemetry_context` from `telemetry`
- `HotPathEvaluateRequest.telemetry_context.current_zone = telemetry.current_zone`
- `HotPathEvaluateRequest.telemetry_context.current_coordinate_ref = telemetry.current_coordinate_ref`

Authoritative approval resolution must still happen from persisted runtime
state, not from embedded request payloads.

Authoritative scope resolution should also happen from persisted runtime truth
or deterministic scope-derivation logic, not only from caller claims.

## Response Contract

### Top-Level Shape

```json
{
  "contract_version": "seedcore.agent_action_gateway.v1",
  "request_id": "req-transfer-2026-0001",
  "decided_at": "2026-04-01T10:00:01Z",
  "latency_ms": 42,
  "decision": {
    "allowed": true,
    "disposition": "allow",
    "reason_code": "restricted_custody_transfer_allowed",
    "reason": "all mandatory checks passed",
    "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-01"
  },
  "required_approvals": [],
  "trust_gaps": [],
  "obligations": [
    {
      "code": "capture_forensic_block"
    },
    {
      "code": "publish_replay_artifact"
    }
  ],
  "minted_artifacts": [
    "ExecutionToken",
    "PolicyReceipt"
  ],
  "authority_scope_verdict": {
    "status": "matched",
    "scope_id": "scope:rct-2026-0001",
    "mismatch_keys": []
  },
  "fingerprint_verdict": {
    "status": "matched",
    "missing_components": [],
    "mismatch_keys": []
  },
  "execution_token": {
    "token_id": "token-123",
    "expires_at": "2026-04-01T10:00:06Z",
    "scope_hash": "sha256:scope-hash"
  },
  "governed_receipt": {
    "audit_id": "audit-abc",
    "policy_receipt_id": "receipt-policy-1",
    "transition_receipt_ids": [
      "receipt-transition-1"
    ]
  },
  "forensic_linkage": {
    "forensic_block_id": null,
    "reason_trace_ref": "reason:llm-inference-001",
    "public_replay_ready": false
  }
}
```

### Response Rules

Required fields:

- `contract_version`
- `request_id`
- `decided_at`
- `latency_ms`
- `decision.allowed`
- `decision.disposition`
- `decision.reason_code`
- `decision.reason`
- `decision.policy_snapshot_ref`
- `authority_scope_verdict.status`
- `fingerprint_verdict.status`

Disposition semantics:

- `allow`: action is admissible; bounded artifacts may be minted
- `deny`: action is contradictory or forbidden
- `quarantine`: trust chain is incomplete, stale, or insufficiently verified
- `escalate`: human/governance review path is required

`execution_token` rules:

- present only when `decision.disposition == "allow"`
- omitted for `deny`, `quarantine`, and `escalate`

`authority_scope_verdict.status` semantics:

- `matched`: the asset, product, and physical scope claims are consistent
- `mismatch`: one or more scope facts contradict persisted or verified truth
- `unverified`: scope could not be verified with enough confidence

`fingerprint_verdict.status` semantics:

- `matched`: required fingerprint components are present and coherent
- `mismatch`: one or more components contradict the expected chain
- `incomplete`: one or more required fingerprint components are missing or stale

### MITM Redirect Semantics

The contract must make the first red-team drill explicit.

Canonical expectations:

- if the request claims an `expected_coordinate_ref` or zone that contradicts
  the reserved or authorized scope, return `deny`
- recommended reason codes for deterministic contradiction:
  - `authority_scope_mismatch`
  - `coordinate_scope_mismatch`
  - `asset_product_scope_mismatch`
- if the coordinate or zone proof is missing, stale, or unverifiable, return
  `quarantine`
- recommended reason codes for insufficient proof:
  - `coordinate_scope_unverified`
  - `physical_presence_proof_missing`
  - `telemetry_too_stale_for_scope_validation`

Mismatch is a business decision outcome, not a transport-layer error.

## Closure Contract (Scaffold)

To align with the 2026 "closure and proof" layer, this v1 draft includes a
contract-first closure scaffold.

Current behavior in this scaffold:

- closure is accepted only for requests that were decided as `allow`
- closure acknowledgement is persisted with idempotency semantics
- settlement handoff is feature-flagged
  (`SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF`)
- settlement status is one of:
  - `pending`
  - `applied`
  - `rejected`
- replay status is one of:
  - `pending`
  - `ready`
- no execution-path or twin-settlement behavior is changed in this slice

Primary response semantics:

- `status = accepted_pending_settlement`
- `settlement_status` reflects handoff outcome
- `replay_status` remains `pending` until settlement is applied or a finalized
  forensic contradiction is persisted

### Closure Request Shape (Scaffold)

```json
{
  "contract_version": "seedcore.agent_action_gateway.v1",
  "request_id": "req-transfer-2026-0001",
  "closure_id": "closure-2026-0001",
  "idempotency_key": "idem-closure-2026-0001",
  "closed_at": "2026-04-01T10:00:04Z",
  "outcome": "completed",
  "evidence_bundle_id": "evb-123",
  "transition_receipt_ids": [
    "receipt-transition-1"
  ],
  "node_id": "node:jetson-orin-01",
  "forensic_block": {
    "forensic_block_id": "fb-2026-0001",
    "fingerprint_components": {
      "economic_hash": "sha256:shopify-order",
      "physical_presence_hash": "sha256:gazebo-point-cloud",
      "reasoning_hash": "sha256:reason-trace",
      "actuator_hash": "sha256:unitree-b2-torque"
    },
    "current_coordinate_ref": "gazebo://warehouse-north/shelf/A3",
    "current_zone": "handoff_bay_3"
  },
  "summary": {
    "notes": "handover completed"
  }
}
```

### Closure Rules

Recommended closure requirements:

- `evidence_bundle_id` is required
- `forensic_block.forensic_block_id` should be supplied for the pilot profile
- if closure evidence contradicts the authorized scope, settlement should be
  rejected and the replay artifact should remain available for investigation
- a closure contradiction should not silently downgrade to success

Recommended contradiction outcomes:

- `settlement_status = rejected`
- `linked_disposition` remains the original request disposition
- `next_actions` should include one or more of:
  - `investigate_scope_mismatch`
  - `quarantine_asset`
  - `review_forensic_block`

## Error Contract

Recommended deterministic error behavior:

- `400` malformed semantic contract (for example unsupported `workflow.type`)
- `401` missing/invalid caller authentication
- `403` caller is authenticated but not authorized for requested workflow scope
- `409` idempotency conflict (same key, different canonical request hash)
- `422` schema/validation failure
- `503` dependency unavailable (for example policy graph or approval store)

Error payload minimum:

```json
{
  "error_code": "idempotency_conflict",
  "message": "idempotency key already used with different request body",
  "request_id": "req-transfer-2026-0001"
}
```

Important distinction:

- malformed or unauthenticated request -> transport or validation error
- scope contradiction or trust-gap -> normal governed response with
  `deny` / `quarantine` / `escalate`

## Idempotency Contract

`idempotency_key` is required for v1.

Rules:

- same `idempotency_key` + same canonical request hash returns the original
  decision payload
- same `idempotency_key` + different request hash returns `409`
- canonical hash must include:
  - authority scope fields
  - hardware fingerprint fields
  - asset and product identity fields
  - security contract fields
- retention should be at least 24 hours

This prevents duplicate transfer execution from retry storms and stops callers
from reusing the same idempotency key with altered scope.

## Security Requirements

Minimum boundary expectations:

- gateway caller must authenticate as an approved agent principal
- request principal must map to a delegated authority path for the target
  physical good (`asset` in the current schema)
- request must carry device or hardware fingerprint metadata sufficient to bind
  the action to an accountable node
- approval envelope must resolve from persisted records
- authority scope must resolve from persisted or deterministic runtime truth
- policy snapshot reference used in decision must be recorded in response

Optional but recommended:

- detached request signature for non-repudiation
- mTLS between caller and gateway in controlled enterprise deployments
- attestation verification against a trust bundle for hardened edge profiles

## Observability Requirements

Each request should be traceable with:

- `request_id`
- `idempotency_key`
- `principal.agent_id`
- `principal.hardware_fingerprint.fingerprint_id`
- `asset.asset_id`
- `asset.product_ref` when provided
- `approval.approval_envelope_id`
- `authority_scope.scope_id`
- `authority_scope.expected_coordinate_ref`
- `decision.disposition`
- `decision.reason_code`
- `policy_snapshot_ref`
- `latency_ms`

Each closure should be traceable with:

- `closure_id`
- `evidence_bundle_id`
- `forensic_block.forensic_block_id`
- `settlement_status`
- `replay_status`

## Rollout Plan

### Phase A: Adapter Mode

- expose `POST /api/v1/agent-actions/evaluate`
- expose `GET /api/v1/agent-actions/requests/{request_id}` with a minimal
  in-memory request-record store
- internally map to existing hot-path evaluation path
- keep output contract stable even while internals evolve
- start with zone- and asset-scoped validation before full coordinate precision
  is required everywhere

### Phase B: First-Class Gateway

- separate gateway service/handler from internal router details
- persist idempotency records and response cache
- add contract tests and one reference client adapter
- add first-class forensic-block linkage for closure and replay
- add red-team fixtures for coordinate redirect and authority replay

## Acceptance Criteria

This v1 contract should be considered ready when all are true:

- one external agent client can execute end-to-end RCT evaluation
- all four dispositions are returned deterministically
- mapping to internal `ActionIntent` and hot-path request is fully tested
- idempotency behavior is tested for replay and conflict paths
- response includes enough fields for operator and replay correlation
- coordinate or zone mismatch can be reproduced as a deterministic
  `deny` or `quarantine` outcome
- closure can link the resulting evidence bundle and forensic block back to the
  original request

## Related Documents

- [seedcore_2026_execution_plan.md](/Users/ningli/project/seedcore/docs/development/seedcore_2026_execution_plan.md)
- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [seedcore_positioning_narrative.md](/Users/ningli/project/seedcore/docs/development/seedcore_positioning_narrative.md)
- [useful_this_year_execution_memo.md](/Users/ningli/project/seedcore/docs/development/useful_this_year_execution_memo.md)
- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [asset_centric_pdp_hot_path_contract.md](/Users/ningli/project/seedcore/docs/development/asset_centric_pdp_hot_path_contract.md)
- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [src/seedcore/models/action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py)
- [src/seedcore/models/pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/models/pdp_hot_path.py)
