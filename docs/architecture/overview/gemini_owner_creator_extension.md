# Gemini Extension: Owner / Creator Layer Implementation

This document translates the `Owner / Creator Layer` in the zero-trust runtime diagram into an implementation-ready Gemini extension plan.

It is intentionally additive to existing SeedCore contracts:

- identity and delegation APIs
- owner twin delegation envelope
- policy-time and execution-time governance checks

## Objective

Provide Gemini-hosted assistants a governed way to:

- operate under explicit owner identity
- read and update creator profiles
- manage assistant delegations
- apply owner trust preferences at decision time

without bypassing SeedCore PDP, execution token gating, or replay evidence.

## Existing Building Blocks (Already In Repo)

- Identity and delegation endpoints are available under `/api/v1/identities/*` and `/api/v1/delegations/*`.
- Owner twin snapshots already project active delegation records from identity facts.
- Governance already enforces delegation scope, authority level, zone constraints, required modality evidence, and step-up behavior.
- Gemini host integration already exists through the plugin-facing MCP server and stdio entrypoint.

The extension should build on these surfaces before introducing new runtime primitives.

## Owner / Creator Layer Mapping

### 1. Owner Identity

Runtime anchor:

- DID document record (`did`, controller, verification method, metadata).

Gemini extension responsibilities:

- register/update owner DID
- fetch owner DID and state for preflight
- bind signed submissions to the same DID used in `ActionIntent.principal.agent_id`

### 2. Creator Profiles

Runtime anchor:

- identity DID metadata (short-term)
- dedicated creator profile fact namespace (recommended next step)

Gemini extension responsibilities:

- manage public creator profile fields used by publish/listing flows
- return profile provenance (`updated_at`, signer/key_ref, source namespace)
- expose profile as read-mostly to assistants unless owner-delegated

Current runtime refs include additive provenance metadata for creator/trust records:

- `updated_by`
- `source_namespace` and `source_predicate`
- `signer_did` and `signer_key_ref` (when owner DID verification metadata is available)

Recommended minimal profile schema:

- `creator_id` (DID)
- `display_name`
- `brand_handles` (platform -> handle map)
- `commerce_prefs` (merchant allowlist, blocked categories)
- `publish_prefs` (allowed channels, content policy profile)
- `risk_profile` (default risk tier for assistant actions)

### 3. Assistant Delegations

Runtime anchor:

- delegation grant/revoke APIs and owner twin delegation projection.

Gemini extension responsibilities:

- grant delegation from owner DID to assistant DID
- revoke delegation and confirm propagation to owner twin
- provide preflight simulation for delegation impact

Minimum delegation envelope in extension UX:

- `authority_level` (`observer`, `contributor`, `signer`)
- `scope` (asset IDs, lot IDs, or `*` if explicitly allowed)
- `constraints.allowed_zones`
- `constraints.required_modality`
- `requires_step_up`

### 4. Trust Preferences

Runtime anchor:

- delegation constraints + policy snapshot + governance evaluation.

Gemini extension responsibilities:

- map owner trust preferences to concrete policy-evaluable fields
- avoid free-form preferences that are not PDP-readable
- persist preference version and expose reference in action metadata

Recommended trust-preference shape:

- `trust_version`
- `max_risk_score`
- `merchant_allowlist`
- `required_provenance_level`
- `required_evidence_modalities`
- `high_value_step_up_threshold_usd`

## Gemini Extension Surface (Current MCP Tools)

Owner/creator tools now available:

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

Notes:

- write tools call existing runtime APIs first; only add new APIs where missing (creator profile, trust preferences).
- `preflight` should return disposition prediction + trust gaps without minting execution tokens.

## End-To-End Flow (Gemini)

1. Gemini extension resolves owner DID (`owner.get`).
2. Gemini extension resolves creator profile + trust preferences.
3. Gemini extension validates active delegation for assistant DID.
4. Gemini extension submits `agent-actions/evaluate` request with delegation refs and trust-preference refs in gateway metadata.
5. SeedCore PDP evaluates delegation, constraints, evidence, and risk.
6. If allowed, execution token is minted; otherwise deny/escalate is returned with trust gaps.
7. Evidence and replay references are surfaced back to Gemini for operator-visible rationale.

## Data Contract Additions (Minimal)

To avoid broad schema churn, add two additive records:

- `creator_profile` fact record
- `trust_preferences` fact record

Both should include:

- `record_id`
- `owner_id` (DID)
- `version`
- `status` (`ACTIVE`, `SUPERSEDED`, `REVOKED`)
- `payload` (typed object)
- `updated_at`
- `updated_by`
- `signature` metadata (optional in v1, recommended for v2)

## Rollout Plan

### Phase 1: Extension Wiring (No New Governance Logic)

- add Gemini MCP tool wrappers for existing identity/delegation endpoints
- add `agent_action.preflight` wrapper using existing gateway evaluate path with debug/no-execute option
- document owner onboarding and delegation lifecycle in integration guide

Exit:

- owner identity + delegation can be managed fully from Gemini extension

### Phase 2: Creator Profile + Trust Preference Persistence

- add API/router + storage records for creator profile and trust preferences
- read these records into relevant twin snapshot assembly
- expose references in decision explanations and replay metadata

Exit:

- runtime decisions can cite concrete owner trust preference versions

### Phase 3: Policy Binding and Proof

- bind trust preference fields to explicit policy checks (deny/escalate thresholds)
- add trust-preference mismatch reason codes
- include profile/preference refs in proof artifacts and trust pages

Exit:

- third-party verifier can explain decisions using owner preference version + delegation evidence

## Risks and Guardrails

- Do not allow Gemini-side local overrides of delegation or trust policy. Runtime is source of truth.
- Do not treat creator profile as authority by itself. Authority remains DID + delegation + policy.
- Keep all high-consequence actions on token-gated execution path.
- Preserve replayability: every mutation must produce timestamped, queryable records.

## Definition Of Done (Owner / Creator Layer For Gemini)

- owner DID lifecycle is extension-accessible
- creator profile lifecycle is extension-accessible
- delegation lifecycle is extension-accessible with runtime-enforced effects
- trust preferences are persisted, versioned, policy-evaluable, and visible in replay/proof
- gateway responses remain deterministic (`allow`/`deny`/`quarantine`/`escalate`) with trust-gap details

## Implementation Reference

For concrete Phase 1 usage examples, see:

- [Gemini Owner/Creator Phase 1 Quickstart](../../development/gemini_phase1_quickstart.md)
