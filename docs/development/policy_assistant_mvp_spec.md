# Policy Assistant MVP Spec (SeedCore API + Runtime)

Date: 2026-04-08  
Status: Implementation-ready MVP spec

## 1) Scope

This MVP turns the policy-assistant decision memo into an executable backend plan.

MVP objective:

- let a general user define policy in plain language (handled in `pkg-simulator`)
- persist typed policy contracts in SeedCore
- run deterministic preflight checks before policy save/promotion
- keep final execution authority in existing PDP/gateway paths

Out of scope for this MVP:

- direct assistant authorization/minting
- replacing `agent-actions/evaluate` hot-path logic
- claiming fully signed-bundle freeze by default

## 2) Existing Surfaces Reused

Already available and reused unchanged:

- `POST /api/v1/trust-preferences`
- `GET /api/v1/trust-preferences/{owner_id}`
- `POST /api/v1/delegations`
- `POST /api/v1/intents/submit-signed`
- `POST /api/v1/agent-actions/evaluate` with `no_execute=true` preflight mode

Reference files:

- `src/seedcore/api/routers/identity_router.py`
- `src/seedcore/api/external_authority.py`
- `src/seedcore/api/routers/agent_actions_router.py`
- `src/seedcore/models/agent_action_gateway.py`

## 3) New API Additions (Exact)

### 3.1 Owner Policy Contract Endpoints

Add two endpoints under the existing identity authority surface:

- `POST /api/v1/owner-policies`
- `GET /api/v1/owner-policies/{owner_id}`

Purpose:

- store and retrieve a typed owner policy contract beyond trust preferences
- provide stable, versioned contract references used by assistant UX and replay explanations

Request model (new `OwnerPolicyUpsertRequest`):

```json
{
  "owner_id": "did:seedcore:owner:acme-001",
  "policy_id": "owner-policy-acme-main",
  "policy_version": "v1",
  "status": "ACTIVE",
  "default_disposition": "DENY",
  "allowed_categories": ["electronics", "home"],
  "denied_categories": ["weapons"],
  "spend_controls": [
    {
      "scope": "global",
      "currency": "USD",
      "per_transaction_limit": 500,
      "daily_limit": 1000,
      "monthly_limit": 10000,
      "step_up_threshold": 300
    }
  ],
  "merchant_rules": [
    {
      "merchant": "amazon.com",
      "marketplace": "amazon",
      "disposition": "ALLOW",
      "required_provenance": "verified",
      "max_amount": 500
    }
  ],
  "publishing_rules": [
    {
      "channel": "shopify",
      "content_type": "product_listing",
      "disposition": "ALLOW",
      "requires_review": true,
      "required_approvals": 1
    }
  ],
  "approval_chains": [
    {
      "action_family": "PURCHASE",
      "threshold_type": "amount_usd",
      "threshold_value": 300,
      "required_approval_count": 1,
      "approver_roles": ["owner"],
      "step_up_on_risk_score": 0.7
    }
  ],
  "delegated_assistants": [
    {
      "assistant_id": "did:seedcore:assistant:buyer-bot-01",
      "authority_level": "contributor",
      "allowed_actions": ["PURCHASE", "LIST"]
    }
  ],
  "updated_by": "policy_assistant",
  "metadata": {
    "source": "pkg-simulator",
    "assistant_run_id": "run-2026-04-08-001"
  }
}
```

Response model (new `OwnerPolicyRecord`):

- mirrors request payload
- adds `updated_at`
- includes `source_namespace` and `source_predicate` for replay/debug references

### 3.2 Owner Context HTTP Preflight Endpoint

Expose deterministic owner-context preflight over HTTP:

- `POST /api/v1/owner-context/preflight`

This is an API-surface equivalent of the existing MCP helper logic in `src/seedcore/plugin/mcp_server.py`.

Request:

```json
{
  "owner_id": "did:seedcore:owner:acme-001",
  "assistant_id": "did:seedcore:assistant:buyer-bot-01",
  "delegation_id": "delegation-123",
  "merchant_ref": "amazon.com",
  "declared_value_usd": 420,
  "required_modalities": ["camera", "seal_sensor"],
  "available_modalities": ["camera"],
  "observed_provenance_level": "verified",
  "risk_score": 0.62
}
```

Response:

```json
{
  "ok": false,
  "owner_id": "did:seedcore:owner:acme-001",
  "assistant_id": "did:seedcore:assistant:buyer-bot-01",
  "owner_context_hash": "sha256:...",
  "owner_context_ref": {
    "owner_id": "did:seedcore:owner:acme-001",
    "creator_profile_ref": "identity:creator_profile:v1",
    "trust_preferences_ref": "identity:trust_preferences:v2"
  },
  "delegation_check": {
    "checked": true,
    "delegation_id": "delegation-123",
    "valid": true,
    "issues": []
  },
  "predicted_policy_signals": {
    "trust_gap_codes": ["owner_trust_modality_violation"],
    "reason_codes": ["owner_trust_modalities_missing"],
    "missing_modalities": ["seal_sensor"]
  },
  "inputs": {
    "merchant_ref": "amazon.com",
    "declared_value_usd": 420,
    "observed_provenance_level": "verified",
    "risk_score": 0.62,
    "required_modalities": ["camera", "seal_sensor"],
    "available_modalities": ["camera"]
  },
  "warnings": []
}
```

### 3.3 Scenario Pack Batch Preflight Endpoint

Add a deterministic batch preflight endpoint to reduce UI orchestration complexity:

- `POST /api/v1/policy-assistant/scenario-pack/evaluate`

Behavior:

- accepts a list of `AgentActionEvaluateRequest` items
- forces `no_execute=true`
- calls existing `agent-actions/evaluate` flow per scenario
- returns per-scenario outcomes plus aggregate summary

Request:

```json
{
  "owner_id": "did:seedcore:owner:acme-001",
  "policy_version": "v1",
  "scenarios": [
    {
      "scenario_id": "safe_purchase_001",
      "label": "Safe low-value trusted merchant purchase",
      "request": {
        "contract_version": "seedcore.agent_action_gateway.v1",
        "request_id": "req-safe-001",
        "requested_at": "2026-04-08T09:00:00Z",
        "idempotency_key": "idem-safe-001",
        "principal": { "...": "..." },
        "workflow": { "...": "..." },
        "asset": { "...": "..." },
        "approval": { "...": "..." },
        "authority_scope": { "...": "..." },
        "telemetry": { "...": "..." },
        "security_contract": { "...": "..." },
        "options": { "no_execute": true }
      }
    }
  ]
}
```

Response:

```json
{
  "owner_id": "did:seedcore:owner:acme-001",
  "policy_version": "v1",
  "summary": {
    "total": 6,
    "allowed": 2,
    "denied": 2,
    "escalated": 2
  },
  "results": [
    {
      "scenario_id": "safe_purchase_001",
      "label": "Safe low-value trusted merchant purchase",
      "decision": "ALLOW",
      "reason_code": "allow",
      "trust_gaps": [],
      "required_approvals": [],
      "obligations": [],
      "governed_receipt_ref": "audit:..."
    }
  ]
}
```

## 4) Persistence Model (MVP)

Use existing facts storage pattern for consistency and speed:

- namespace: `identity`
- predicate for owner policy: `owner_policy_contract`
- subject: `owner_id`
- object_data: typed owner policy payload

Required versioning fields:

- `policy_id`
- `policy_version`
- `status` (`ACTIVE`, `SUPERSEDED`, `REVOKED`)
- `updated_at`
- `updated_by`

## 5) File-Level Backend Change Plan

### 5.1 Models and storage

- `src/seedcore/api/external_authority.py`
  - add `OwnerPolicyRecord`, `OwnerPolicyUpsertRequest`, nested typed models
  - add `upsert_owner_policy(...)` and `get_owner_policy(...)`
  - persist as identity fact (`owner_policy_contract`)

### 5.2 Routers

- `src/seedcore/api/routers/identity_router.py`
  - add `POST /owner-policies`
  - add `GET /owner-policies/{owner_id}`
  - add `POST /owner-context/preflight`

- `src/seedcore/api/routers/policy_assistant_router.py` (new)
  - add `POST /policy-assistant/scenario-pack/evaluate`

- `src/seedcore/api/routers/__init__.py`
  - register `policy_assistant_router` in `ACTIVE_ROUTER_SPECS`

### 5.3 Docs and contracts

- `docs/references/api/seedcore-api-reference.md`
  - add new endpoints and payload summaries

- `docs/development/gemini_phase1_quickstart.md`
  - add HTTP path examples equivalent to MCP preflight tools

## 6) Determinism and Guardrails

Hard rules for these new endpoints:

- no endpoint in this MVP mints execution tokens directly
- scenario-pack endpoint always sets `no_execute=true`
- owner-context preflight and scenario-pack responses must expose trust gaps and reason codes explicitly
- assistant-readable summaries must keep `facts` and `inferences` separate where generated

## 7) Test Plan (SeedCore)

Add tests:

- `tests/test_owner_policy_endpoints.py`
  - upsert/get owner policy contract
  - supersede behavior by version/status

- `tests/test_owner_context_preflight_endpoint.py`
  - trust-gap predictions for risk/merchant/provenance/modalities

- `tests/test_policy_assistant_scenario_pack_endpoint.py`
  - batch execution with forced no-execute
  - summary counters
  - deterministic response shape

Regression checks:

- existing `agent-actions/evaluate` behavior unchanged when called directly
- trust-preferences endpoints remain backward-compatible

## 8) Acceptance Criteria

MVP backend is complete when:

- typed owner policy can be written and read via API
- owner-context preflight is available via HTTP with stable contract fields
- scenario-pack batch preflight returns per-scenario decisions and aggregate summary
- all new endpoints are documented in API reference
- CI tests cover success and fail-closed scenarios

## 9) Rollout

Phase order:

1. Merge model/storage additions behind API endpoints.
2. Ship owner-context preflight HTTP endpoint.
3. Ship scenario-pack batch preflight endpoint.
4. Wire `pkg-simulator` UI against new endpoints.
5. Add release note that this MVP is advisory/preflight-only and not direct authorization.

Reference companion UI spec:

- `../pkg-simulator/docs/POLICY_ASSISTANT_MVP_SPEC.md`
