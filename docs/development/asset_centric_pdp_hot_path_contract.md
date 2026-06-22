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
5. No request-time remote database fan-out for trust-critical context.
6. Context must arrive as pinned local view state, a causality/freshness token,
   or a signed context envelope.
7. Causality-sensitive requests must prove the local view is at least as fresh
   as the user's last relevant mutation or fail closed.
8. Mutation-derived causality must be anchored in a signed mutation receipt or
   equivalent trusted sequencer output. A client-supplied token is only a
   freshness demand; it is not proof unless the receipt signature, scope,
   sequence, session binding, and epoch are valid.
9. Zanzibar-style external graph checks are not part of the default RCT hot
   path; graph inputs must be compiled into bounded local decision artifacts
   before evaluation.
10. Context sufficiency must be decided before policy allow: required fields,
    context-envelope signatures, causality freshness, and freshness SLAs must all
    pass or the request returns `deny`, `quarantine`, or `escalate` with an
    explicit trust gap.
11. If the local context watermark is behind the receipt-required sequence, the
    engine may block only inside a bounded convergence budget. If it cannot
    prove catch-up in time, it must return `quarantine` with
    `replay_mismatch_fail_closed` and mint no `ExecutionToken`.

## Context Infrastructure Pattern

The hot path follows ADR 0001's ecosystem posture:

- Signed Context Envelopes use Biscuit/Macaroon-style caveats for verifiable,
  request-bound context.
- Freshness tokens use SpiceDB `ZedToken`/Zanzibar zookie-style semantics to
  prevent stale authorization after a causally relevant update.
- Approval, custody, delegation, resource, and telemetry state are projected
  into subscribed local views through CDC or equivalent event streams.
- External graph PDP services remain future scale options, not the current
  execution gate for Restricted Custody Transfer.

## Signed Mutation Receipt And Watermark Gate

The next contract extension sharpens the existing `context_freshness` field into
a deterministic replay gate. A causality token should point to a signed mutation
receipt produced by the system that accepted the upstream mutation, such as an
approval update, delegation revoke, custody transition, asset lock, or source
registration change.

Minimum receipt semantics:

- `receipt_id`: stable opaque receipt reference.
- `mutation_type`: bounded operation class such as `approval.updated` or
  `delegation.revoked`.
- `sequence_number` or `log_offset`: monotonic boundary for the relevant
  tenant, cluster, or context stream.
- `snapshot_ref`: policy or context snapshot family the mutation belongs to,
  when known.
- `issued_at` and `expires_at`: short epoch for replay control.
- `subject_ref`, `resource_ref`, and optional `workflow_id`: scope binding.
- `session_binding_hash`: hash of the active caller/session/public-key binding
  when the profile requires proof-of-possession.
- `issuer`, `key_ref`, and `signature_ref`: verification material for the
  sequencer or mutation authority.

Runtime gate:

1. Verify the receipt signature, scope, epoch, and session binding.
2. Resolve the request's `required_watermark` from the receipt sequence or log
   offset.
3. Compare the local context projection's `local_view_watermark` with the
   required watermark.
4. If `local_view_watermark >= required_watermark`, evaluate normally.
5. If the local view is behind, block only inside the declared
   `barrier_timeout_ms` to let the local view converge or to use an explicitly
   admitted direct-source read for that profile.
6. If the boundary still cannot be proven, return `quarantine` with
   `replay_mismatch_fail_closed`, emit the receipt and watermark evidence, and
   withhold the `ExecutionToken`.

This is a bounded freshness barrier, not a general request-time database fan-out
permission. The final PDP decision remains synchronous and deterministic over
the proven context package.

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
  "context_freshness": {
    "causality_token": "ctx:approval-transfer-001:000042",
    "mutation_receipt_ref": "mutation_receipt:approval-transfer-001:000042",
    "required_watermark": "000042",
    "local_view_watermark": "000042",
    "barrier_timeout_ms": 25,
    "minimum_observed_at": "2026-04-02T08:00:12Z",
    "local_view_ref": "view:rct-edge-handoff-bay-3:000042",
    "local_view_version": "000042",
    "freshness_sla_profile": "rct.fixture.v1"
  },
  "context_sufficiency": {
    "schema_profile": "rct.hot_path.context.v1",
    "required_fields_present": true,
    "causality_satisfied": true,
    "mutation_receipt_verified": true,
    "watermark_gate_satisfied": true,
    "session_binding_satisfied": true,
    "token_epoch_satisfied": true,
    "freshness_sla_satisfied": true,
    "signed_envelopes_verified": true,
    "state_binding_hash": "sha256:state-binding-transfer-001"
  },
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
  "signed_context_envelopes": [
    {
      "envelope_id": "sce-edge-telemetry-001",
      "issuer": "device:edge-node-7",
      "issued_at": "2026-04-02T08:00:10Z",
      "claims_hash": "sha256:edge-context-claims-001",
      "caveats": [
        "asset_id=asset:lot-8841",
        "target_zone=handoff_bay_3",
        "max_age_seconds=60"
      ],
      "signature_ref": "sig:edge-context-001"
    }
  ],
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
- `context_freshness.local_view_ref`
- `context_freshness.local_view_version`
- `context_freshness.freshness_sla_profile`
- `context_freshness.mutation_receipt_ref` for causality-sensitive mutations
- `context_freshness.required_watermark` for receipt-backed freshness checks
- `context_freshness.local_view_watermark` when a local view is used as proof
- `context_sufficiency.schema_profile`
- `context_sufficiency.state_binding_hash`
- `action_intent` (existing SeedCore model shape)
- `asset_context.asset_ref`
- `telemetry_context.observed_at`

### Hard Validation Rules

1. `action_intent.valid_until > now` or `deny`.
2. `action_intent.resource.asset_id == asset_context.asset_ref` or `deny`.
3. `policy_snapshot_ref` must equal active compiled snapshot for the hot path or `quarantine`.
4. Missing required approval role -> `deny` or `escalate` (policy-driven).
5. Telemetry staleness breach -> `quarantine`.
6. Required local view freshness below `context_freshness.causality_token` -> `quarantine`.
7. Invalid signed context envelope signature, caveat, or scope -> `deny` or `quarantine` based on policy.
8. Missing context-sufficiency required fields -> `deny` or `quarantine`
   based on the failed context class.
9. Missing or unverifiable `state_binding_hash` input for a high-consequence
   RCT path -> `quarantine`.
10. Missing, unsigned, expired, scope-mismatched, or session-mismatched mutation
    receipt for a causality-sensitive request -> `quarantine`.
11. `local_view_watermark < required_watermark` after the bounded barrier
    budget -> `quarantine` with `replay_mismatch_fail_closed`.
12. A repeated token/receipt pair outside the admitted session or epoch ->
    `deny` or `quarantine` according to the policy profile.

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
    "context_freshness": {
      "causality_token": "ctx:approval-transfer-001:000042",
      "mutation_receipt_ref": "mutation_receipt:approval-transfer-001:000042",
      "local_view_ref": "view:rct-edge-handoff-bay-3:000042",
      "local_view_version": "000042",
      "required_watermark": "000042",
      "local_view_watermark": "000042",
      "freshness_sla_profile": "rct.fixture.v1"
    },
    "freshness_barrier": {
      "required_watermark": "000042",
      "local_view_watermark": "000042",
      "barrier_result": "already_satisfied",
      "barrier_wait_ms": 0
    },
    "state_binding_hash": "sha256:state-binding-transfer-001",
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
- `insufficient_context`
- `context_freshness_breach`
- `mutation_receipt_invalid`
- `context_watermark_behind`
- `replay_mismatch_fail_closed`
- `state_binding_hash_missing`
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
- All allow-path decisions include replay-visible context sufficiency,
  causality/freshness, signed-envelope, and `state_binding_hash` evidence.
- Causality-sensitive allow paths include a verified signed mutation receipt,
  required watermark, local-view watermark, barrier result, session binding
  status, and token epoch status.
- Missing, stale, invalid, or partial context fixtures resolve to deterministic
  `deny`, `quarantine`, or `escalate`; no insufficient-context fixture may mint
  an `ExecutionToken`.
- Receipt replay, session mismatch, expired epoch, local-watermark lag, and
  barrier-timeout fixtures resolve to deterministic `deny` or `quarantine` with
  no `ExecutionToken`.
- Verification surfaces render business-readable states without raw stack traces.
