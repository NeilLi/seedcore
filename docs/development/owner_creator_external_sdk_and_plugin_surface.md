# Design: External SDK, Plugin, and Skills Surface for the Owner / Creator Layer

This document turns the Owner / Creator Layer from the zero-trust runtime
diagram into an explicit external integration surface for SeedCore.

The goal is to let external assistants, plugins, skills, and traditional SDK
clients manage:

- owner identity
- creator profiles
- assistant delegations
- trust preferences

without moving policy truth outside the SeedCore runtime.

## Design Goal

Expose the Owner / Creator Layer as a first-class external authority surface
that can be consumed in three ways:

- direct REST API
- MCP/plugin tools for model-facing assistants
- traditional SDKs for app and workflow developers

Kafka remains an optional ingress transport for delegated intent, not a second
authority system.

## Core Principle

External integrations may help users read, update, and submit owner-context
state, but they must not become the source of truth for:

- delegation validity
- policy allow/deny outcomes
- execution-token issuance
- replay/evidence integrity

SeedCore remains the authoritative runtime for policy evaluation and governed
execution.

## Architectural Position

From the diagram in
[zero_trust_custody_digital_twin_runtime.md](/Users/ningli/project/seedcore/docs/architecture/overview/zero_trust_custody_digital_twin_runtime.md),
the Owner / Creator Layer sits between external AI ecosystems and the SeedCore
runtime.

That means external integrations should be treated as clients of the Owner /
Creator Layer, not owners of its logic.

Recommended architecture:

- **Authority API**: canonical CRUD and preflight surface for owner identity,
  creator profiles, delegation records, trust preferences, and signed intent
  submission.
- **MCP/plugin surface**: thin model-facing wrappers over the same Authority
  API.
- **Traditional SDK**: typed client over the same Authority API for server apps,
  web apps, CLIs, and workflow engines.
- **Kafka ingress**: asynchronous delegated-intent transport into the same
  authoritative evaluation path.

## Source Of Truth Boundaries

### External plugin / skill / SDK owns

- user-facing onboarding flows
- owner-context forms and editors
- convenience wrappers around identity/profile/delegation APIs
- local UX state
- request signing or event publishing on behalf of the caller

### SeedCore runtime owns

- owner identity record persistence
- creator profile persistence
- delegation lifecycle enforcement
- trust preference persistence and versioning
- owner-context preflight
- governed action evaluation
- execution-token minting
- proof, replay, and audit references

## External Surfaces

## 1. Authority API

The Authority API is the canonical integration surface and should back every
other client form.

Current runtime endpoints already provide most of the required contract:

- `POST /api/v1/identities/dids`
- `PATCH /api/v1/identities/dids/{did}`
- `GET /api/v1/identities/dids/{did}`
- `POST /api/v1/delegations`
- `GET /api/v1/delegations/{delegation_id}`
- `POST /api/v1/delegations/{delegation_id}/revoke`
- `POST /api/v1/creator-profiles`
- `GET /api/v1/creator-profiles/{owner_id}`
- `POST /api/v1/trust-preferences`
- `GET /api/v1/trust-preferences/{owner_id}`
- `POST /api/v1/owner-policies`
- `GET /api/v1/owner-policies/{owner_id}`
- `POST /api/v1/owner-context/preflight`
- `POST /api/v1/intents/submit-signed`

These are documented in
[seedcore-api-reference.md](/Users/ningli/project/seedcore/docs/references/api/seedcore-api-reference.md#L183).

### Authority API responsibilities

- register and fetch owner DID records
- manage creator profile lifecycle
- grant, inspect, and revoke delegations
- persist trust-preference records
- assemble or validate owner-context inputs before action evaluation
- accept signed external intent for authoritative evaluation

## 2. MCP / Plugin / Skills Surface

The model-facing surface should stay deliberately thin. It should call the
Authority API and return normalized results, not implement local governance.

The current MCP server already expresses the right tool boundary in
[mcp_server.py](/Users/ningli/project/seedcore/src/seedcore/plugin/mcp_server.py#L40).

Recommended tool families:

- `seedcore.identity.owner.upsert`
- `seedcore.identity.owner.get`
- `seedcore.creator_profile.upsert`
- `seedcore.creator_profile.get`
- `seedcore.delegation.grant`
- `seedcore.delegation.get`
- `seedcore.delegation.revoke`
- `seedcore.trust_preferences.upsert`
- `seedcore.trust_preferences.get`
- `seedcore.owner_context.get`
- `seedcore.owner_context.preflight`
- `seedcore.agent_action.preflight`
- `seedcore.agent_action.evaluate`

### Plugin behavior rules

- never cache delegation truth as authoritative state
- never locally override trust preferences
- never return "allow" as final authority without a runtime response
- treat preflight as advisory and evaluate as authoritative
- surface `source_url`, replay references, and trust gaps back to the assistant

### Skills pattern

Skills should compose these tools into higher-level workflows such as:

- owner onboarding
- creator profile setup
- delegation grant/revoke workflows
- trust-preference tuning
- action preflight before execution

The skill should orchestrate tool calls, but all persistent writes still go
through SeedCore.

## 3. Traditional SDK Surface

The SDK should be a typed wrapper around the Authority API rather than a second
protocol.

Recommended modules:

- `ownerIdentity`
- `creatorProfile`
- `delegation`
- `trustPreferences`
- `ownerContext`
- `agentActions`
- `signedIntent`

### Example SDK shape

```ts
const client = new SeedcoreClient({
  baseUrl: process.env.SEEDCORE_API,
  apiKey: process.env.SEEDCORE_API_KEY,
})

await client.ownerIdentity.upsert({
  did: "did:seedcore:owner:123",
  displayName: "Acme Creator",
  signingScheme: "ed25519",
  publicKey: "base58-public-key",
})

await client.creatorProfile.upsert({
  ownerId: "did:seedcore:owner:123",
  displayName: "Acme Creator",
  publishPrefs: { defaultMarketplace: "seedcore-shop" },
})

await client.delegation.grant({
  ownerId: "did:seedcore:owner:123",
  assistantId: "did:assistant:openai:agent-01",
  authorityLevel: "operator",
  scope: ["publish", "list_inventory"],
})

const preflight = await client.ownerContext.preflight({
  owner_id: "did:seedcore:owner:123",
  assistant_id: "did:assistant:openai:agent-01",
  delegation_id: "deleg-123",
})

const decision = await client.agentActions.evaluate({
  contract_version: "seedcore.agent_action_gateway.v1",
  request_id: "req-123",
  principal: {
    agent_id: "did:assistant:openai:agent-01",
    owner_id: "did:seedcore:owner:123",
    delegation_ref: "delegation:deleg-123",
  },
  workflow: {
    type: "publish_listing",
    action_type: "PUBLISH",
  },
})
```

### SDK design requirements

- typed request and response models
- clear distinction between preflight and evaluate
- optional signing helpers for `submit-signed`
- idempotency support
- replay-safe request identifiers
- no local policy engine

## 4. Kafka Ingress Surface

Kafka is appropriate for external assistants or workflow engines that need
asynchronous delegated-intent submission.

The contract is already documented in
[kafka_delegated_intent_ingress.md](/Users/ningli/project/seedcore/docs/development/kafka_delegated_intent_ingress.md).

The required behavior is:

1. external producer emits delegated intent to `seedcore.intent.v1`
2. SeedCore ingress validates payload shape and owner-context inputs
3. ingress calls `POST /api/v1/owner-context/preflight`
4. ingress calls `POST /api/v1/agent-actions/evaluate`
5. downstream observability is emitted through `seedcore.policy_outcome.v1`

This preserves a single authority path even when transport is asynchronous.

## Owner / Creator Domain Contract

The external surface should expose four user-meaningful records.

### Owner identity

Primary purpose:

- identify the owner as a DID-bound authority subject
- support signed external requests
- attach metadata and service endpoints

Minimum fields:

- `did`
- `controller`
- `display_name`
- `signing_scheme`
- `public_key`
- `key_ref`
- `service_endpoints`
- `status`
- `metadata`

### Creator profile

Primary purpose:

- represent creator-facing profile and publishing context
- support listing and commerce workflows
- carry non-authority business preferences

Minimum fields:

- `owner_id`
- `version`
- `status`
- `display_name`
- `brand_handles`
- `commerce_prefs`
- `publish_prefs`
- `risk_profile`
- `updated_by`
- `metadata`

### Assistant delegation

Primary purpose:

- bind an assistant to scoped owner authority
- constrain the types of actions an assistant may request

Minimum fields:

- `owner_id`
- `assistant_id`
- `authority_level`
- `scope`
- `constraints`
- `requires_step_up`
- `status`

### Trust preferences

Primary purpose:

- persist owner-defined trust thresholds in a form the runtime can reference
- support deterministic preflight explanations and proof artifacts

Minimum fields:

- `owner_id`
- `trust_version`
- `status`
- `max_risk_score`
- `merchant_allowlist`
- `required_provenance_level`
- `required_evidence_modalities`
- `high_value_step_up_threshold_usd`
- `updated_by`
- `metadata`

## Canonical Flows

## Flow A: Owner onboarding through plugin or SDK

1. Register owner DID.
2. Upsert creator profile.
3. Upsert trust preferences.
4. Optionally upsert owner policy contract.
5. Return a summarized owner-context view to the external client.

## Flow B: Assistant delegation lifecycle

1. Grant delegation from owner DID to assistant DID.
2. Read delegation record for confirmation.
3. Use preflight to validate whether a proposed action fits current scope.
4. Revoke delegation when authority should end.

## Flow C: Governed action from external assistant

1. External assistant resolves owner context.
2. External assistant validates or fetches active delegation.
3. External assistant runs owner-context preflight.
4. External assistant submits `agent-actions/evaluate` or `intents/submit-signed`.
5. SeedCore returns disposition, trust gaps, and proof references.

## Flow D: Async delegated intent over Kafka

1. External workflow publishes delegated intent envelope.
2. SeedCore Kafka ingress performs preflight.
3. SeedCore Kafka ingress forwards the authoritative evaluate call.
4. Outcome is observed from runtime responses and Kafka outcome topics.

## Guardrails

- Do not allow plugin-side local overrides of delegation or trust policy.
- Do not treat creator profile as authority by itself.
- Do not mint execution authority outside the SeedCore runtime.
- Do not treat Kafka acceptance as policy acceptance.
- Do not let SDK convenience methods collapse preflight and evaluate into one
  ambiguous call.

## Recommended Packaging

For production adoption, package the external Owner / Creator surface as:

- `SeedCore Authority API`
- `SeedCore MCP Server` or assistant-specific plugin wrapper
- `SeedCore SDK` in TypeScript/Python
- optional `SeedCore Kafka Producer Helper` for delegated intent workflows

All of them should target the same authority contracts.

## Rollout Plan

### Phase 1

- keep existing REST and MCP surfaces as canonical
- document the Owner / Creator surface as a stable external integration plane

### Phase 2

- publish official TypeScript and Python SDK clients
- add signing helpers for `submit-signed`
- add owner-context assembly helpers for client ergonomics

### Phase 3

- add assistant-specific plugin manifests and examples
- add broker-backed async examples for Kafka delegated intent
- add proof/replay helper methods to SDK responses

## Success Criteria

- external assistants can manage owner identity, creator profiles, delegations,
  and trust preferences without bypassing governance
- plugin and SDK clients use the same authoritative runtime contracts
- preflight remains advisory and evaluate remains authoritative
- Kafka and direct HTTP flows converge into the same runtime policy path
- replay and proof references remain available for all high-consequence actions
