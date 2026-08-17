# Design: External SDK, Plugin, and Skills Surface for the Owner / Creator Layer

This document turns the Owner / Creator Layer from the zero-trust runtime
diagram into an explicit external integration surface for SeedCore.

Revision note (2026-08-16): the surface now also covers vendor-neutral,
read-only verified-projection discovery and a media-first producer registration
draft flow. Discovery remains non-authoritative, and draft extraction requires
explicit producer or admitted-operator confirmation before governed first
writes.

The broader ecosystem placement is defined in
[`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md).
That architecture keeps this API/MCP/SDK surface canonical while placing maps,
commerce, logistics, agent registries, and spatial experiences in replaceable
surrounding planes.

The first implementation is owner-operated rather than partner-dependent. See
[`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md)
for the modular city kernel, closed-world fixtures, deterministic provider
simulators, and staged replacement with live adapters. Owning the bootstrap
stack does not permit plugin or SDK clients to bypass runtime authority.

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
- `seedcore.discovery.search`
- `seedcore.discovery.get_projection`
- `seedcore.discovery.explain_claim_state`
- `seedcore.producer.draft_registration_from_media`

The strict discovery MVP stops at those three read tools. Dedicated claim,
comparison, proof-summary, and anchor-resolution tools are deferred until
measured client usage requires them.

### Plugin behavior rules

- never cache delegation truth as authoritative state
- never locally override trust preferences
- never return "allow" as final authority without a runtime response
- treat preflight as advisory and evaluate as authoritative
- surface `source_url`, replay references, and trust gaps back to the assistant
- treat media-to-registration output as an expiring draft that requires an
  admitted producer or operator confirmation

### Skills pattern

Skills should compose these tools into higher-level workflows such as:

- owner onboarding
- creator profile setup
- delegation grant/revoke workflows
- trust-preference tuning
- action preflight before execution
- autonomous read-only exploration of verified public projections
- comparison and explanation of claim states without proposing authority
- conversational producer onboarding that drafts, explains, and corrects a
  registration before explicit confirmation

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

## 4. Read-Only Verified Projection Discovery Surface

SeedCore should expose a vendor-neutral read plane for Codex, Gemini, and other
AI agents to autonomously explore public-safe verified projections.

The first expanded scenario contract for this surface is
[`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md).

The canonical implementation should remain the SeedCore Projection Discovery
API. MCP tools, assistant plugins, AI skills, and SDK methods are thin clients
over that same API and projection schema.

Allowed autonomous behavior includes:

- semantic and structured search
- filtering and pagination
- fetching current projection and claim state
- comparing public-safe projections
- explaining the difference between claimed, registered, verified, review,
  rejected, quarantined, and presentation-only state
- composing route or itinerary candidates
- resolving a public QR/NFC anchor to its safe projection

The discovery plane must not:

- mutate a registration, policy, projection, inventory, reservation, or
  custody record
- infer a new verification verdict
- expose authority-tier telemetry or private location
- treat semantic rank or agent preference as trust
- automatically cross from exploration into booking, purchase, release,
  workshop approval, custody transfer, or quarantine clearance

Any consequential next step must be represented as a separate proposed action
and enter the existing owner/delegation, `ActionIntent`, PDP,
`ExecutionToken`, receipt, and replay path.

Recommended SDK module:

- `verifiedDiscovery`

Recommended minimum methods:

- `search(query)`
- `getProjection(projectionId)`
- `explainClaimState(projectionId, claim)`

Additional comparison and proof-summary methods remain future candidates, not
part of the strict client contract.

Discovery results should preserve projection version, `as_of` time, freshness
or expiry state, policy/profile refs, current verifier disposition,
presentation-only labels, and a canonical source URL. Cached results are never
locally authoritative.

Free-form producer descriptions, presentation narratives, captions, URLs, and
external documents must be treated as untrusted content. They cannot supply
tool instructions, delegation, policy, or permission to an autonomous agent.

Frontier-agent hosts reduce the need for SeedCore to build a separate itinerary
or chat UI for each ecosystem. They do not replace the minimum SeedCore-owned
surfaces:

- accessible producer draft review and confirmation
- canonical public `/verify/{public_anchor_ref}` proof page
- authorized operator exception and dispute workflows
- privacy, consent, retention, support, and correction documentation

The proof page is the fallback source link rendered by discovery clients. It
must explain exact claim state, profile, freshness, and verifier disposition in
plain language without collapsing them into a generic badge or score.

Optional creative presentation should use a separate
`GroundedCreativeArtifactV0`-style record. Agent clients may render or summarize
an `Artisan Story & Lore` artifact only when they preserve its
`PRESENTATION_ONLY` state, source projection/version, factual source refs,
synthetic-media disclosure, consent/visibility state, and canonical correction
URL. The artifact is untrusted content and must never provide tool instructions,
policy, delegation, or action scope.

The strict discovery API has only:

- `POST /api/v1/discovery/query`
- `GET /api/v1/discovery/projections/{projection_id}`
- `GET /api/v1/discovery/anchors/{public_anchor_ref}`

It is stateless and read-only over static fixtures or projections. Semantic
recommendation, real-time negotiation, agent bidding, and marketplace protocols
are explicitly deferred.

The canonical `/verify/{public_anchor_ref}` page is safely escaped,
server-rendered HTML with no required client JavaScript, native app, 3D canvas,
or map stack. `explain_claim_state` is deterministic and template-backed in the
MVP.

## 5. Kafka Ingress Surface

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

## Flow E: Autonomous read-only discovery

1. External agent receives a user exploration goal.
2. Agent calls read-only discovery tools and paginates or refines as needed.
3. SeedCore returns public-safe projections with versions, claim states,
   freshness, and verifier disposition.
4. Agent compares, explains, or drafts an itinerary without mutating state.
5. If the user requests a consequential action, the agent creates a separate
   proposed action and enters Flow C under explicit principal and delegation
   scope.

## Flow F: Media-first producer registration draft

1. Producer or assisted operator uploads exactly one image and one audio clip
   through an approved channel adapter.
2. SeedCore creates an expiring `SourceRegistrationDraftV0` with source-linked
   field candidates, missing fields, conflicts, and public-redaction preview.
3. Producer or admitted operator reviews and corrects a plain-language summary.
4. Explicit confirmation produces governed `TrackingEvent` first writes.
5. The registration workflow separately evaluates and emits a
   `RegistrationDecision`; the drafting agent never emits that decision.

## Guardrails

- Do not allow plugin-side local overrides of delegation or trust policy.
- Do not treat creator profile as authority by itself.
- Do not mint execution authority outside the SeedCore runtime.
- Do not treat Kafka acceptance as policy acceptance.
- Do not let SDK convenience methods collapse preflight and evaluate into one
  ambiguous call.
- Do not let discovery tools or skills silently cross into action tools.
- Do not treat free-form discovered content as instructions or permissions.
- Do not let a plugin maintain a separate verification truth from the current
  SeedCore projection.
- Do not let a media-ingestion agent auto-confirm a registration, invent a
  missing claim, or label inferred content as producer-declared.
- Do not infer verified origin from image scenery, audio narration, or device
  geolocation.
- Do not let payment or escrow webhooks mint, widen, extend, or override
  execution authority.

## Recommended Packaging

For production adoption, package the external Owner / Creator surface as:

- `SeedCore Authority API`
- `SeedCore MCP Server` or assistant-specific plugin wrapper
- `SeedCore SDK` in TypeScript/Python
- `SeedCore Verified Discovery API` and read-only projection tools
- accessible producer draft-confirmation and public proof-page adapters
- optional `SeedCore Kafka Producer Helper` for delegated intent workflows

All of them should target the same authority contracts.

## Rollout Plan

### Phase 1

- keep existing REST and MCP authority surfaces canonical
- freeze the verified-projection, query, freshness, and public-anchor contracts
- add `src/seedcore/api/routers/discovery_router.py` and register it through the
  existing router registry
- extend `src/seedcore/plugin/runtime_client.py` and
  `src/seedcore/plugin/mcp_server.py` with thin discovery calls
- implement exactly three stateless read-only discovery endpoints and three MCP
  wrappers after contract fixtures are reviewed
- use structured allowlisted filters and stable ordering; defer semantic
  recommendation, negotiation, and bidding
- do not widen `GEMINI_MINIMAL_READ_ONLY_BUNDLE` merely by adding tools to the
  full plugin surface; supported-host exposure is separately reviewed

### Phase 2

- add the canonical low-bandwidth public proof page
- add `SourceRegistrationDraftV0` beside existing source-registration models
  and implement the draft-only media adapter under `src/seedcore/adapters/`
- constrain the helper to exactly one image and one audio clip
- require explicit producer/operator confirmation before governed first writes
- publish official TypeScript and Python discovery clients
- keep the proof page safely escaped and server-rendered with no required
  client JavaScript, 3D renderer, or map stack
- reserve a disabled-by-default story/lore region that cannot obscure current
  disposition, freshness, or adverse claim state

### Phase 2A

- freeze a presentation-only creative artifact and sentence/source citation
  contract after the base proof page is stable
- pilot producer-approved story text with one existing consented still or audio
  excerpt and a deterministic proof-only fallback
- test claim-state preservation, prompt-injection isolation, consent,
  impersonation, cultural-safety, expiry, correction, and withdrawal behavior
- defer generated reels, synthetic/voice-cloned characters, live personas, AR,
  and 3D to separately reviewed presentation experiments

### Phase 3

- add signing helpers for `submit-signed`
- add owner-context assembly helpers for client ergonomics
- add proof/replay helper methods to SDK responses
- add broker-backed async examples for Kafka delegated intent

### Phase 4

- publish Codex, Gemini, and vendor-neutral discovery skill examples over the
  same read-only MCP tools
- add assistant-specific manifests as thin adapters over the canonical server
- validate endpoint trust, scopes, prompt-injection isolation, freshness, rate
  limits, and source-link rendering for each supported host

## Success Criteria

- external assistants can manage owner identity, creator profiles, delegations,
  and trust preferences without bypassing governance
- plugin and SDK clients use the same authoritative runtime contracts
- preflight remains advisory and evaluate remains authoritative
- Kafka and direct HTTP flows converge into the same runtime policy path
- replay and proof references remain available for all high-consequence actions
- Codex, Gemini, and other agents can autonomously search and explain current
  public-safe projections without gaining mutation or execution authority
- discovery clients preserve claim state, projection version, freshness, and
  presentation-only labels without collapsing them into a provenance score
- low-tech producers can create and correct a source-linked registration draft
  without handling schemas or credentials, while confirmation remains explicit
- consumers can open a canonical human-readable proof page without installing
  an agent, plugin, or specialist application
- creative presentation remains source-cited, consented, explicitly
  non-authoritative, and unable to hide stale, partial, rejected, or quarantined
  proof state
