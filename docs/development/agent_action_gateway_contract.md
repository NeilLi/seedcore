# Agent Action Gateway Contract (v1 Draft)

Date: 2026-03-31
Status: Draft contract for Q3 2026 productization

## Purpose

This document defines the first external contract for agent-originated governed
actions in SeedCore.

It is intentionally narrow and workflow-specific:

- workflow: `Restricted Custody Transfer`
- runtime outcome: `allow`, `deny`, `quarantine`, `escalate`
- authority model: delegated principal + persisted approval envelope
- proof model: replayable decision and receipt linkage

This is a product boundary contract, not an internal coordinator schema.

## Scope

This v1 draft defines:

- request and response shapes for the Agent Action Gateway
- deterministic mapping to `ActionIntent` and hot-path evaluation inputs
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
- this contract does not imply a digital-asset-only scope

## Request Contract

### Top-Level Shape

```json
{
  "contract_version": "seedcore.agent_action_gateway.v1",
  "request_id": "req-transfer-2026-0001",
  "requested_at": "2026-03-31T10:00:00Z",
  "idempotency_key": "idem-transfer-2026-0001",
  "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31",
  "principal": {
    "agent_id": "agent:custody_runtime_01",
    "role_profile": "TRANSFER_COORDINATOR",
    "session_token": "session-abc",
    "actor_token": null,
    "delegation_ref": "delegation:owner-8841-transfer",
    "organization_ref": "org:warehouse-north"
  },
  "workflow": {
    "type": "restricted_custody_transfer",
    "action_type": "TRANSFER_CUSTODY",
    "valid_until": "2026-03-31T10:01:00Z"
  },
  "asset": {
    "asset_id": "asset:lot-8841",
    "lot_id": "lot-8841",
    "from_custodian_ref": "principal:facility_mgr_001",
    "to_custodian_ref": "principal:outbound_mgr_002",
    "from_zone": "vault_a",
    "to_zone": "handoff_bay_3",
    "provenance_hash": "sha256:asset-provenance"
  },
  "approval": {
    "approval_envelope_id": "approval-transfer-001",
    "expected_envelope_version": "23"
  },
  "telemetry": {
    "observed_at": "2026-03-31T09:59:58Z",
    "freshness_seconds": 2,
    "max_allowed_age_seconds": 300,
    "evidence_refs": [
      "ev:cam-1",
      "ev:seal-sensor-7"
    ]
  },
  "security_contract": {
    "hash": "sha256:contract-hash",
    "version": "rules@8.0.0"
  },
  "options": {
    "debug": false
  }
}
```

### Required Request Rules

Required fields:

- `contract_version`
- `request_id`
- `requested_at`
- `idempotency_key`
- `principal.agent_id`
- `principal.role_profile`
- one of `principal.session_token` or `principal.actor_token`
- `workflow.type`
- `workflow.action_type`
- `workflow.valid_until`
- `asset.asset_id`
- `asset.provenance_hash`
- `approval.approval_envelope_id`
- `telemetry.observed_at`
- `security_contract.hash`
- `security_contract.version`

Normalization rules:

- timestamps must be ISO-8601 UTC
- empty strings are invalid for required string fields
- `workflow.type` must be `restricted_custody_transfer` in v1
- unknown top-level fields should be rejected (`422`)

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
- `gateway.delegation_ref`
- `gateway.organization_ref`

`ActionIntent.resource.asset_id`:

- `asset.asset_id`

`ActionIntent.resource.target_zone`:

- `asset.to_zone`

`ActionIntent.resource.provenance_hash`:

- `asset.provenance_hash`

`ActionIntent.resource.lot_id`:

- `asset.lot_id`

`ActionIntent.resource.category_envelope` (minimum):

- `from_custodian_ref`
- `to_custodian_ref`
- `from_zone`
- `to_zone`

### Hot-Path Input Mapping

The mapped `ActionIntent` plus request context should be transformed into:

- `HotPathEvaluateRequest.contract_version = "pdp.hot_path.asset_transfer.v1"`
- `HotPathEvaluateRequest.request_id = request_id`
- `HotPathEvaluateRequest.requested_at = requested_at`
- `HotPathEvaluateRequest.policy_snapshot_ref = policy_snapshot_ref or security_contract.version`
- `HotPathEvaluateRequest.asset_context.asset_ref = asset.asset_id`
- `HotPathEvaluateRequest.telemetry_context` from `telemetry`

Authoritative approval resolution must still happen from persisted runtime
state, not from embedded request payloads.

## Response Contract

### Top-Level Shape

```json
{
  "contract_version": "seedcore.agent_action_gateway.v1",
  "request_id": "req-transfer-2026-0001",
  "decided_at": "2026-03-31T10:00:01Z",
  "latency_ms": 42,
  "decision": {
    "allowed": true,
    "disposition": "allow",
    "reason_code": "restricted_custody_transfer_allowed",
    "reason": "all mandatory checks passed",
    "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31"
  },
  "required_approvals": [],
  "trust_gaps": [],
  "obligations": [],
  "minted_artifacts": [
    "ExecutionToken",
    "PolicyReceipt"
  ],
  "execution_token": {
    "token_id": "token-123",
    "expires_at": "2026-03-31T10:00:06Z"
  },
  "governed_receipt": {
    "audit_id": "audit-abc",
    "policy_receipt_id": "receipt-policy-1",
    "transition_receipt_ids": [
      "receipt-transition-1"
    ]
  }
}
```

## Closure Contract (Scaffold)

To align with the 2026 "closure and proof" layer, this v1 draft includes a
contract-first closure scaffold.

Current behavior in this scaffold:

- closure is accepted only for requests that were decided as `allow`
- closure acknowledgement is persisted with idempotency semantics
- settlement handoff is feature-flagged (`SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF`)
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
- `replay_status` remains `pending` until settlement is applied

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

Disposition semantics:

- `allow`: action is admissible; bounded artifacts may be minted
- `deny`: action is contradictory or forbidden
- `quarantine`: trust chain is incomplete or stale
- `escalate`: human/governance review path is required

`execution_token` rules:

- present only when `decision.disposition == "allow"`
- omitted for `deny`, `quarantine`, and `escalate`

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

## Idempotency Contract

`idempotency_key` is required for v1.

Rules:

- same `idempotency_key` + same canonical request hash returns the original
  decision payload
- same `idempotency_key` + different request hash returns `409`
- retention should be at least 24 hours

This prevents duplicate transfer execution from retry storms.

## Security Requirements

Minimum boundary expectations:

- gateway caller must authenticate as an approved agent principal
- request principal must map to a delegated authority path for the target
  physical good (`asset` in the current schema)
- approval envelope must resolve from persisted records
- policy snapshot reference used in decision must be recorded in response

Optional but recommended:

- detached request signature for non-repudiation
- mTLS between caller and gateway in controlled enterprise deployments

## Observability Requirements

Each request should be traceable with:

- `request_id`
- `idempotency_key`
- `principal.agent_id`
- `asset.asset_id`
- `approval.approval_envelope_id`
- `decision.disposition`
- `decision.reason_code`
- `policy_snapshot_ref`
- `latency_ms`

## Rollout Plan

### Phase A: Adapter Mode

- expose `POST /api/v1/agent-actions/evaluate`
- expose `GET /api/v1/agent-actions/requests/{request_id}` with a minimal
  in-memory request-record store
- internally map to existing hot-path evaluation path
- keep output contract stable even while internals evolve

### Phase B: First-Class Gateway

- separate gateway service/handler from internal router details
- persist idempotency records and response cache
- add contract tests and one reference client adapter

## Acceptance Criteria

This v1 contract should be considered ready when all are true:

- one external agent client can execute end-to-end RCT evaluation
- all four dispositions are returned deterministically
- mapping to internal `ActionIntent` and hot-path request is fully tested
- idempotency behavior is tested for replay and conflict paths
- response includes enough fields for operator and replay correlation

## Related Documents

- [seedcore_2026_execution_plan.md](/Users/ningli/project/seedcore/docs/development/seedcore_2026_execution_plan.md)
- [seedcore_positioning_narrative.md](/Users/ningli/project/seedcore/docs/development/seedcore_positioning_narrative.md)
- [useful_this_year_execution_memo.md](/Users/ningli/project/seedcore/docs/development/useful_this_year_execution_memo.md)
- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [src/seedcore/models/action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py)
- [src/seedcore/models/pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/models/pdp_hot_path.py)
