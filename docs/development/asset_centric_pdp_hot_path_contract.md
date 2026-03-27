# Asset-Centric PDP Hot Path Contract (Draft v1)

## Purpose

Define a **real, deterministic, low-latency PDP hot path** for Restricted Custody Transfer so authorization is:

- fast (bounded p95 latency)
- predictable (fixed dispositions and reason codes)
- anomaly-aware (trust-gap handling without ambiguous failures)
- replay-ready (governed receipt and signer provenance always emitted)

This contract is intentionally narrow: one workflow, one evidence model, one decision vocabulary.

## Hot Path Requirements

1. No live graph rebuild on request path.
2. No best-effort authorization.
3. No free-form LLM policy reasoning.
4. If any hard dependency is unavailable, fail closed (`quarantine` or `deny` based on policy).

## Endpoint (Proposed)

`POST /api/v1/pdp/hot-path/evaluate`

Optional debug:

- `?debug=true` includes check-by-check execution diagnostics.

## Request Contract

```json
{
  "contract_version": "pdp.hot_path.asset_transfer.v1",
  "request_id": "pdp-req-2026-04-02-0001",
  "requested_at": "2026-04-02T08:00:15Z",
  "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-02",
  "action_intent": {
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
          "required_roles": ["FACILITY_MANAGER", "QUALITY_INSPECTOR"],
          "approved_by": ["principal:facility_mgr_001", "principal:quality_insp_017"]
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
  },
  "asset_context": {
    "asset_ref": "asset:lot-8841",
    "current_custodian_ref": "principal:facility_mgr_001",
    "current_zone": "vault_a",
    "source_registration_status": "APPROVED",
    "registration_decision_ref": "registration_decision:abc123"
  },
  "telemetry_context": {
    "observed_at": "2026-04-02T08:00:10Z",
    "freshness_seconds": 5,
    "max_allowed_age_seconds": 60,
    "evidence_refs": ["evidence:telemetry-001"]
  }
}
```

### Required Request Fields

- `policy_snapshot_ref`
- `action_intent` (existing SeedCore model shape)
- `asset_context.asset_ref`
- `telemetry_context.observed_at`

### Hard Validation Rules

1. `action_intent.valid_until > now` or `deny`.
2. `action_intent.resource.asset_id == asset_context.asset_ref` or `deny`.
3. `policy_snapshot_ref` must equal active compiled snapshot for the hot path or `quarantine`.
4. Missing required approval role -> `deny` or `escalate` (policy-driven).
5. Telemetry staleness breach -> `quarantine`.

## Response Contract

```json
{
  "contract_version": "pdp.hot_path.asset_transfer.v1",
  "request_id": "pdp-req-2026-04-02-0001",
  "decided_at": "2026-04-02T08:00:15Z",
  "latency_ms": 14,
  "decision": {
    "allowed": true,
    "disposition": "allow",
    "reason_code": "restricted_custody_transfer_allowed",
    "reason": "Dual approval valid and custody transfer constraints satisfied.",
    "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-02",
    "policy_snapshot_hash": "sha256:snapshot-hash-transfer-001"
  },
  "required_approvals": [],
  "trust_gaps": [],
  "obligations": [
    {
      "code": "publish_replay_artifact",
      "severity": "required"
    }
  ],
  "checks": [
    {"check_id": "intent_ttl_valid", "result": "pass"},
    {"check_id": "principal_present", "result": "pass"},
    {"check_id": "approval_binding_match", "result": "pass"},
    {"check_id": "asset_custody_match", "result": "pass"},
    {"check_id": "telemetry_freshness", "result": "pass"},
    {"check_id": "snapshot_consistency", "result": "pass"}
  ],
  "execution_token": {
    "token_id": "token-transfer-001",
    "intent_id": "intent-transfer-001",
    "issued_at": "2026-04-02T08:00:16Z",
    "valid_until": "2026-04-02T08:01:16Z",
    "contract_version": "rules@transfer-v1",
    "constraints": {
      "action_type": "TRANSFER_CUSTODY",
      "asset_id": "asset:lot-8841",
      "from_zone": "vault_a",
      "target_zone": "handoff_bay_3",
      "approval_envelope_id": "approval-transfer-001",
      "approval_binding_hash": "sha256:approval-binding-transfer-001"
    },
    "signature": {
      "signer_type": "service",
      "signer_id": "seedcore-verify",
      "key_ref": "kms:seedcore/pdp",
      "attestation_level": "baseline"
    }
  },
  "governed_receipt": {
    "decision_hash": "receipt-transfer-001",
    "disposition": "allow",
    "snapshot_ref": "snapshot:pkg-prod-2026-04-02",
    "asset_ref": "asset:lot-8841",
    "resource_ref": "seedcore://zones/vault_a/assets/asset:lot-8841",
    "reason": "restricted_custody_transfer_allowed",
    "generated_at": "2026-04-02T08:00:16Z",
    "trust_gap_codes": [],
    "provenance_sources": ["tracking_event:telemetry-001"]
  },
  "signer_provenance": [
    {
      "artifact_type": "execution_token",
      "signer_type": "service",
      "signer_id": "seedcore-verify",
      "key_ref": "kms:seedcore/pdp",
      "attestation_level": "baseline"
    }
  ]
}
```

## Disposition and Reason-Code Taxonomy (Frozen)

### `allow`

- `restricted_custody_transfer_allowed`

### `deny`

- `expired_ttl`
- `missing_principal`
- `missing_source_registration`
- `unapproved_source_registration`
- `mismatched_registration_decision`
- `approval_incomplete`
- `asset_custody_mismatch`

### `quarantine`

- `stale_telemetry`
- `snapshot_not_ready`
- `hot_path_dependency_unavailable`
- `trust_gap_quarantine`

### `escalate`

- `break_glass_required`
- `manual_review_required`
- `high_risk_context`

## Business-State Mapping (Verification Surface)

- `allow + verified=true` -> `verified`
- `deny + verified=true` -> `rejected`
- `quarantine + verified=true` -> `quarantined`
- `escalate + verified=true` -> `review_required`
- any verification failure -> `verification_failed`

## Latency Budget and Gating

- p50: <= 10 ms
- p95: <= 25 ms
- p99: <= 50 ms
- hard timeout: 75 ms -> disposition `quarantine` with reason `hot_path_dependency_unavailable`

## Runtime Wiring (SeedCore)

1. Keep active compiled graph healthy via:
   - `POST /api/v1/pkg/authz-graph/refresh`
   - `GET /api/v1/pkg/authz-graph/status`
2. Force PDP to consume active compiled graph:
   - `SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true`
3. Emit stable policy outputs:
   - `PolicyDecision` (`allowed`, `disposition`, `deny_code`, `required_approvals`, `authz_graph`, `governed_receipt`)
   - `ExecutionToken` for `allow` only
4. Persist audit/replay artifacts immediately for verification surfaces.

## Rollout Plan

1. **D0 Shadow**: dual-evaluate current path and hot path, no serving impact.
2. **D1 Canary**: serve 5% from hot path, enforce parity on disposition/reason_code.
3. **D2 Ramp**: 25% -> 50% -> 100% with p95/p99 SLO gates.
4. **D3 Lock**: hot path becomes default for Restricted Custody Transfer; legacy path fallback only for incident mode.

## Acceptance Criteria

- Decision parity >= 99.9% against baseline for frozen fixtures.
- Zero fail-open events.
- 100% decisions produce replay-verifiable artifacts.
- Verification surfaces render business-readable states without raw stack traces.
