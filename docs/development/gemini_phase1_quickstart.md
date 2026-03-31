# Gemini Owner/Creator Phase 1-2 Quickstart

This quickstart shows how to use the Gemini extension tools for:

- owner DID onboarding
- creator profile persistence
- assistant delegation lifecycle
- trust preferences persistence
- governed action preflight (`no_execute`)

## Prerequisites

- SeedCore API is running and reachable via `SEEDCORE_API`.
- Gemini host is running the SeedCore MCP server (`seedcore.plugin.gemini_stdio`).
- You have owner and assistant DID identifiers prepared.

## Tool Surface (Phase 1)

- `seedcore.identity.owner.upsert`
- `seedcore.identity.owner.get`
- `seedcore.creator_profile.upsert`
- `seedcore.creator_profile.get`
- `seedcore.delegation.grant`
- `seedcore.delegation.get`
- `seedcore.delegation.revoke`
- `seedcore.trust_preferences.upsert`
- `seedcore.trust_preferences.get`
- `seedcore.agent_action.preflight`

## 1) Register Owner Identity

Call:

```json
{
  "tool": "seedcore.identity.owner.upsert",
  "arguments": {
    "did": "did:seedcore:owner:acme-001",
    "controller": "did:seedcore:owner:acme-001",
    "display_name": "Acme Creator Ops",
    "signing_scheme": "ed25519",
    "public_key": "BASE64_PUBLIC_KEY",
    "key_ref": "key-2026-q2",
    "service_endpoints": {
      "web": "https://acme.example"
    },
    "metadata": {
      "tier": "pilot"
    },
    "status": "ACTIVE"
  }
}
```

Validate:

```json
{
  "tool": "seedcore.identity.owner.get",
  "arguments": {
    "did": "did:seedcore:owner:acme-001"
  }
}
```

## 2) Upsert Creator Profile

Call:

```json
{
  "tool": "seedcore.creator_profile.upsert",
  "arguments": {
    "owner_id": "did:seedcore:owner:acme-001",
    "version": "v1",
    "status": "ACTIVE",
    "display_name": "Acme Creator Ops",
    "brand_handles": {
      "instagram": "@acme",
      "youtube": "@acme"
    },
    "commerce_prefs": {
      "merchant_allowlist": [
        "merchant:trusted-1"
      ]
    },
    "publish_prefs": {
      "allowed_channels": [
        "youtube",
        "shop"
      ]
    },
    "risk_profile": {
      "tier": "standard"
    }
  }
}
```

Validate:

```json
{
  "tool": "seedcore.creator_profile.get",
  "arguments": {
    "owner_id": "did:seedcore:owner:acme-001"
  }
}
```

## 3) Grant Assistant Delegation

Call:

```json
{
  "tool": "seedcore.delegation.grant",
  "arguments": {
    "owner_id": "did:seedcore:owner:acme-001",
    "assistant_id": "did:seedcore:assistant:warehouse-bot-01",
    "authority_level": "signer",
    "scope": [
      "asset:lot-8841"
    ],
    "constraints": {
      "allowed_zones": [
        "handoff_bay_3"
      ],
      "required_modality": [
        "camera",
        "seal_sensor"
      ]
    },
    "requires_step_up": true
  }
}
```

Save `delegation_id` from the response, then check:

```json
{
  "tool": "seedcore.delegation.get",
  "arguments": {
    "delegation_id": "REPLACE_WITH_DELEGATION_ID"
  }
}
```

## 4) Upsert Trust Preferences

Call:

```json
{
  "tool": "seedcore.trust_preferences.upsert",
  "arguments": {
    "owner_id": "did:seedcore:owner:acme-001",
    "trust_version": "v1",
    "status": "ACTIVE",
    "max_risk_score": 0.7,
    "merchant_allowlist": [
      "merchant:trusted-1"
    ],
    "required_provenance_level": "verified",
    "required_evidence_modalities": [
      "camera",
      "seal_sensor"
    ],
    "high_value_step_up_threshold_usd": 1000
  }
}
```

Validate:

```json
{
  "tool": "seedcore.trust_preferences.get",
  "arguments": {
    "owner_id": "did:seedcore:owner:acme-001"
  }
}
```

## 5) Run Governed Preflight (No Execute)

Use `seedcore.agent_action.preflight` to evaluate policy/trust gaps without minting `ExecutionToken`.

```json
{
  "tool": "seedcore.agent_action.preflight",
  "arguments": {
    "debug": true,
    "no_execute": true,
    "request": {
      "contract_version": "seedcore.agent_action_gateway.v1",
      "request_id": "req-transfer-2026-0001",
      "requested_at": "2026-03-31T10:00:00Z",
      "idempotency_key": "idem-transfer-2026-0001-preflight",
      "policy_snapshot_ref": "snapshot:pkg-prod-2026-03-31",
      "principal": {
        "agent_id": "did:seedcore:assistant:warehouse-bot-01",
        "role_profile": "TRANSFER_COORDINATOR",
        "session_token": "session-abc",
        "owner_id": "did:seedcore:owner:acme-001",
        "delegation_ref": "REPLACE_WITH_DELEGATION_ID",
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
        "debug": true,
        "no_execute": true
      }
    }
  }
}
```

Expected checks:

- `decision.disposition` is one of `allow`, `deny`, `quarantine`, `escalate`
- `trust_gaps` and `required_approvals` are populated when applicable
- `execution_token` is `null`
- `minted_artifacts` does not include `ExecutionToken`

## 4) Revoke Delegation
## 6) Revoke Delegation

```json
{
  "tool": "seedcore.delegation.revoke",
  "arguments": {
    "delegation_id": "REPLACE_WITH_DELEGATION_ID",
    "reason": "pilot completed"
  }
}
```

Then verify state:

```json
{
  "tool": "seedcore.delegation.get",
  "arguments": {
    "delegation_id": "REPLACE_WITH_DELEGATION_ID"
  }
}
```

## Troubleshooting

- `404 owner DID not found` or `assistant DID not found`: register both DIDs first.
- `422 principal.session_token or principal.actor_token is required`: include one identity proof token.
- `deny/quarantine` with delegation reason: validate `scope`, `authority_level`, allowed zones, and required modality.
- idempotency conflicts: use a fresh `idempotency_key` for each distinct request payload.
