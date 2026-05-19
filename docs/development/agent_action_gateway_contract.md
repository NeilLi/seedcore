# Agent Action Gateway Contract (v1)

Date: 2026-04-21 (last updated)
Status: v1 implemented. The request, response, and closure shapes described
below are enforced in production code and by contract tests. Future changes
to any mandatory field or reason code must be versioned via
`seedcore.agent_action_gateway.vN`.

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

This v1 contract defines:

- request and response shapes for the Agent Action Gateway
- deterministic mapping to `ActionIntent` and hot-path evaluation inputs
- transaction-specific authority scope for the canonical workflow
- device or hardware fingerprint fields for agent accountability
- minimum forensic-block linkage needed for replay correlation
- idempotency and error handling expectations
- minimum observability and proof linkage fields
- feature-flagged authentication boundary for external callers

v1 does not require replacing existing internal endpoints immediately.

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

### Clarification: "Delegated Authority, Not Ambient Authority"

This is the single most important rule the gateway enforces. It is the
boundary that separates this contract from a generic "agent API" pattern, so
it is worth stating precisely what it means, how the schema encodes it, and
how v1 enforces it at runtime.

#### What "ambient" vs "delegated" means here

- **Ambient authority** would mean: *"I am an authenticated agent, therefore I
  may move this asset."* The caller's identity alone implies authorization,
  and the server has to retroactively decide whether that identity "usually"
  has the right. This is the default pattern in most SaaS APIs and is
  deliberately not allowed here.
- **Delegated authority** means: *"I am agent X, acting for owner O, under
  delegation D, bound to approval envelope E, on hardware H, for asset A in
  scope S, under policy snapshot P."* The caller carries, in a single
  request, every artifact the runtime needs to reconstruct the authority
  chain **without consulting ambient session state**.

Every mandatory field on `AgentActionEvaluateRequest` exists to make the
second statement verifiable; every rejected optional shortcut exists to
prevent collapsing back to the first.

#### The delegation chain on the wire

A v1 evaluate request must carry the full chain, and pydantic rejects any
payload that omits a link:

| Link | Schema location | What it proves |
|---|---|---|
| Agent identity | `principal.agent_id`, `principal.role_profile` | Who is acting right now |
| Identity proof | `principal.session_token` **or** `principal.actor_token` (at least one required by `AgentActionPrincipal._require_identity_proof`) | That the acting agent is who it claims to be, not a forged caller |
| Principal-to-owner binding | `principal.owner_id`, `principal.delegation_ref` | That the agent is authorized *by* a specific owner via a specific delegation record |
| Hardware accountability | `principal.hardware_fingerprint.{fingerprint_id, public_key_fingerprint, node_id?, endpoint_id?, attestation_type?}` | That the action is bound to an accountable physical node, not a free-floating software process |
| Approval envelope | `approval.approval_envelope_id` (and optional `expected_envelope_version`) | That an externally-persisted approval decision exists for *this* workflow |
| Transaction scope | `authority_scope.{scope_id, asset_ref, product_ref?, expected_from_zone?, expected_to_zone?, expected_coordinate_ref?, max_radius_meters?}` with `expected_to_zone` **or** `expected_coordinate_ref` required by `AgentActionAuthorityScope._require_physical_scope_binding` | That the approved authority is narrow: a specific asset moving to a specific zone/coordinate, not "this owner's stuff in general" |
| Policy frame | `security_contract.{hash, version}` and optional top-level `policy_snapshot_ref` | Which policy graph/snapshot the caller believes they are operating under |
| Forensic fingerprint | `forensic_context.fingerprint_components.{economic_hash, physical_presence_hash, reasoning_hash, actuator_hash}` for replayable cases | That the specific act — economic, physical, reasoning, actuator — is bound to the delegation, not just the identity |
| Replay anchor | top-level `request_id`, `idempotency_key`, `requested_at` | That a second call cannot "reuse" the same delegation claim to do a different action |

If any of these are missing or malformed the request fails at the schema
layer with `422`, **before** any business logic runs. That is the first line
of defense against ambient-authority drift.

#### Where v1 actually enforces each link

Defense is layered — schema validation is necessary but not sufficient. The
gateway also performs runtime verification against persisted truth:

1. **Caller authentication** (optional boundary, off by default for
   in-process callers, mandatory for external deployments).
   `require_gateway_caller` in
   `src/seedcore/api/routers/agent_actions_router.py` enforces a Bearer
   token via `SEEDCORE_AGENT_ACTION_GATEWAY_AUTH_MODE` /
   `..._AUTH_TOKEN`. A missing or wrong token fails with `401` before the
   request body is even parsed — so an unauthenticated caller cannot claim
   *any* delegation.

2. **Role / workflow allowlist.** `_enforce_gateway_role_scope` consults
   `SEEDCORE_AGENT_ACTION_GATEWAY_ALLOWED_ROLES`. An authenticated caller
   with a role outside that allowlist is rejected `403
   role_not_authorized_for_workflow`, preventing "authenticated ⇒
   authorized" ambient drift.

3. **Owner / delegation resolution against persisted identity facts.**
   `_resolve_owner_twin_snapshot_for_payload` uses `get_delegation` and
   `build_owner_twin_snapshot` from `src/seedcore/api/external_authority.py`
   to load the owner twin and its active `DelegatedAuthority` entries for
   the declared `owner_id` / `delegation_ref`. The resulting snapshot is
   then injected into the hot-path evaluation and stapled into the
   `governed_receipt.owner_context` on the response. The delegation claim
   is therefore always checked against durable identity facts, not
   against the caller's header state.

   Rollout is intentionally staged. `SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_MODE`
   defaults to `shadow`, where validation failures emit structured warning
   logs but do not block legacy/internal callers. Set the mode to `enforce`
   to fail closed with `403` for missing, mismatched, inactive, or wrong-agent
   delegations, and `503 delegation_store_unavailable` when the identity store
   cannot be reached. The check is read-only and runs after the canonical
   evaluate payload hash is computed, so it does not mutate the
   `delegation_ref`, `ActionIntent`, signature surface, or replay identity.
   A short in-process TTL cache
   (`SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_CACHE_TTL_SECONDS`, default
   30 seconds) bounds the added identity-fact lookup cost on the request path.
   Historical replay/read paths use the stored governed request and receipt;
   they do not re-authorize an old action against the delegation's current
   active/revoked state.

4. **Approval envelope resolution.** `resolve_authoritative_transfer_approval`
   in `src/seedcore/ops/pdp_hot_path.py` reads the persisted
   `transfer_approval` record keyed by `approval.approval_envelope_id` and
   passes the authoritative envelope (+ transition history + head hash)
   into `evaluate_pdp_hot_path`. The hot path then validates that the
   envelope is present, active, and consistent with the asset and scope in
   the request. Without a matching persisted envelope, the decision
   degrades to `deny` / `quarantine` with an explicit reason code — there
   is no code path where a request is allowed purely on the strength of
   the principal's identity.

5. **Asset / scope binding at the pydantic layer.**
   `AgentActionEvaluateRequest._validate_scope_consistency` already rejects
   any request where `authority_scope.asset_ref` disagrees with
   `asset.asset_id`, or where `authority_scope.product_ref` disagrees with
   `asset.product_ref`. That means a caller cannot reuse a valid
   delegation against a *different* asset — the common ambient-authority
   failure mode.

6. **Physical-scope contradiction and proof.**
   `_build_authority_scope_verdict` then computes a mismatch set against
   telemetry (coordinate, zone, product). `_apply_forensic_scope_guards`
   converts those mismatches into the precedence-ordered reason codes
   documented in §MITM Redirect Semantics:
   - coordinate / product / generic scope contradictions → `deny`
   - missing physical-presence hash → `quarantine
     physical_presence_proof_missing`
   - missing coordinate telemetry when a hash exists → `quarantine
     coordinate_scope_unverified`
   - stale telemetry → `quarantine
     telemetry_too_stale_for_scope_validation`

   In other words: *even a perfectly-authenticated, perfectly-delegated
   caller cannot execute if their physical scope claim cannot be
   verified.* Delegation grants the right to **ask**; the physical-proof
   layer grants the right to **succeed**.

7. **Hardware binding into the runtime intent.** In `_map_to_hot_path_request`
   the gateway copies `principal.hardware_fingerprint.*` into
   `ActionIntent.action.parameters.gateway.*` and into the execution
   endpoint. Downstream planners (`PLANNER_TYPE_DELEGATED_AUTHORITY`,
   `PLANNER_TYPE_CONDITIONAL_ESCROW`) and the Kafka delegated-intent
   envelope (`build_delegated_intent_envelope`) re-emit the same
   `owner_id`, `delegation_ref`, `agent_id`, and fingerprint, so the
   hardware identity travels with the request through execution and
   settlement rather than being asserted once and then dropped.

8. **Canonical request hash covers the whole chain.**
   `_canonical_gateway_payload_hash` includes the principal (agent,
   role, owner, delegation, organization, session/actor tokens, full
   hardware fingerprint), approval, authority scope, security contract,
   and options. Idempotency replay therefore requires the same *delegation
   claim*, not just the same idempotency key. A request that keeps the
   key but mutates the delegation chain falls into the `409
   idempotency_conflict` branch rather than ambient replay.

#### Ways this rules out ambient authority

Because of the above, the following "ambient" patterns cannot succeed in v1:

- "I'm logged in, so I can transfer any asset my owner controls." — blocked
  by `authority_scope.asset_ref == asset.asset_id` pydantic check and by
  persisted-envelope lookup.
- "I'm in the right role, so I can move this asset anywhere." — blocked by
  `expected_to_zone` / `expected_coordinate_ref` being mandatory, plus the
  coordinate / zone / product precedence in `_apply_forensic_scope_guards`.
- "I already proved who I am once this session." — blocked by
  `session_token` / `actor_token` being required on every request and by
  the canonical hash covering them.
- "My hardware doesn't matter, only my credentials do." — blocked by
  `principal.hardware_fingerprint` being mandatory and carried into the
  execution token and the delegated intent envelope.
- "My delegation covers this workflow generally, so the specific approval
  envelope is optional." — blocked by `approval.approval_envelope_id` being
  required and resolved from a persisted envelope on every evaluate.
- "I don't need to prove physical presence, my delegation is enough." —
  blocked by the `physical_presence_proof_missing` /
  `coordinate_scope_unverified` quarantine path when coordinate-bound
  scope is requested.

The net effect is that the gateway never infers authority from the caller's
ambient context. Every evaluate decision is the product of explicit,
replayable, forensically-linked delegation artifacts, and the absence of any
one of them is a governed outcome — not a silent allow.

#### Performance Characteristics vs. a Traditional "Agent API"

Carrying the full delegation chain on every request looks strictly heavier
than an ambient "is this caller logged in?" check. In practice v1 stays
within the same latency envelope as a traditional agent API because the
extra work is almost entirely CPU-local validation of content the caller
already sent, not additional network hops.

**What the evaluate path actually does per request**

1. Pydantic validation of ~8 nested models (principal, hardware fingerprint,
   asset, approval, authority scope, telemetry, security contract, forensic
   context).
2. Canonical payload hashing (`_canonical_gateway_payload_hash`) — one
   SHA-256 over a deterministic JSON projection.
3. Redis idempotency lookup (with in-memory fallback).
4. Owner / delegation lookup via `get_delegation` /
   `build_owner_twin_snapshot` from `src/seedcore/api/external_authority.py`.
5. Approval envelope lookup via `resolve_authoritative_transfer_approval` in
   `src/seedcore/ops/pdp_hot_path.py`.
6. Hot-path policy evaluation (`evaluate_pdp_hot_path`).
7. Scope-verdict overlay (`_build_authority_scope_verdict` +
   `_apply_forensic_scope_guards`).
8. Optional execution-token mint through the Rust kernel.
9. One structured log line.

In steady state only items 3–5 cross a network/disk boundary, and each is
bounded by design:

| Cost source | Mitigation in code |
|---|---|
| Policy graph evaluation | Not a DB query. `get_global_pkg_manager().get_active_compiled_authz_index()` (see `_resolve_hot_path_runtime_status` in `src/seedcore/ops/pdp_hot_path.py`) returns a compiled, in-process authorization index rebuilt only when the active snapshot version advances. Per-request cost is pointer lookup + O(1) dispatch, not a graph traversal of persisted facts. |
| Approval envelope resolution | Single indexed async PG read keyed on `approval_envelope_id` via `_TRANSFER_APPROVAL_DAO.get_current_with_history`. The envelope is immutable per version, so it caches trivially in front of PG. |
| Delegation / owner twin resolution | Single keyed read of an identity fact row plus a pre-joined owner-twin materialization — not a graph walk. |
| Idempotency lookup | Redis `GET` on `seedcore:agent_actions:idem:{key}` in normal deployments; TTL-honoring in-memory map when Redis is disabled. |
| Execution-token minting | Delegated to the compiled Rust kernel via `mint_execution_token_with_rust` in `src/seedcore/integrations/rust_kernel.py`, keeping the crypto off the Python GIL on the hot request. |
| Canonical payload hash / pydantic validation | Pure CPU, measured in microseconds even with the full delegation chain; dwarfed by any network hop. |
| Structured log emission | `logger.info` with `extra={…}`, wrapped in a try/except so observability can never block the request path. |
| Replay read (`GET /requests/{id}`) | Served entirely out of the idempotency cache — no PG read, no hot-path re-evaluation. |

Net: after the compiled graph is warm (which happens at process start or on
snapshot promotion, not per request), the evaluate path touches at most two
indexed PG reads and one Redis GET. Everything else is in-process
validation of fields the caller already sent.

**Horizontal scaling**

Delegated authority is harder to cache naively than ambient auth, but it is
also easier to shard:

- The gateway handler has no process-local mutable state beyond the
  in-memory idempotency fallback. Every record (delegation, approval,
  idempotency, request, closure) is keyed by a hash or ID, so adding gateway
  replicas is an O(1) operation.
- The compiled authz graph is a content-addressed, cache-friendly artifact:
  each replica lazy-loads the current snapshot and serves reads for the
  lifetime of that snapshot. Snapshot promotions are rare events.
- Idempotency is Redis-backed with a pure-local fallback
  (`SEEDCORE_AGENT_ACTION_DISABLE_REDIS_STORE`); at scale, flip Redis on and
  every replica shares the hash store.
- Forensic closure is off the evaluate critical path — callers that do not
  need it do not pay for it (execute and closure endpoints are opt-in).

**How we prove it empirically**

The performance claim is not hand-waved — it is instrumented:

- `scripts/host/benchmark_rct_hot_path.py` drives canonical cases through
  the live hot path and reports p50 / p95 / p99 per case and per
  disposition.
- `scripts/host/verify_hot_path_benchmark_lane.sh` wires that into the
  verification matrix so regressions are caught before merge.
- `tests/test_benchmark_rct_hot_path.py` gives the same instrumentation a
  deterministic unit-test harness.

Any change that adds real latency on the evaluate path — a new PG read, a
synchronous crypto call, an un-cached snapshot fetch — surfaces on the
benchmark lane before it ships.

**Current status (2026-04-22, local host runtime)**

Done now:

- owner delegation lookup narrowed at query time in
  `src/seedcore/api/external_authority.py` (`_list_owner_delegations`) by
  filtering `Fact.predicate` with the `delegation:` prefix in SQL, reducing
  owner-twin resolution scan cost under hot-path load.
- gateway request-record/idempotency Redis writes in
  `src/seedcore/api/routers/agent_actions_router.py`
  (`_write_request_record`) switched from two sequential `SETEX` calls to one
  Redis pipeline execution, reducing write round-trips on the evaluate path.
- verification lanes remain green after the change:
  `tests/test_external_authority.py`,
  `tests/test_agent_action_gateway_productization.py`,
  `tests/test_benchmark_rct_hot_path.py`,
  `tests/test_capture_hot_path_deployment_baseline.py`.

Still remaining:

- close the concurrent-load latency gap to promotion SLOs
  (`p50 < 25ms`, `p95 < 50ms`, `p99 < 100ms`) in
  `docs/development/hot_path_enforcement_promotion_contract.md`;
  local benchmark still shows tail latency above this envelope.
- reduce non-policy overhead (boundary I/O, contention, and queueing) that
  dominates end-to-end gateway wall time relative to reported hot-path policy
  evaluation time.
- re-run the same benchmark and parity evidence on dedicated gateway-process
  split and real cluster topology as the source-of-truth performance sign-off.

**The apples-to-apples comparison**

The fair comparison is not "delegated authority vs. nothing." It is
"delegated authority evaluated once, on a compiled graph, at the boundary"
vs. "ambient authority plus whatever governance you eventually bolt on
after the fact, evaluated piecemeal across multiple services."

A traditional agent API that tries to match the guarantees in
§MITM Redirect Semantics still has to fetch the same delegation record,
fetch the same approval envelope, re-derive the same scope verdict, verify
the same hardware fingerprint, and produce the same forensic fingerprint —
but typically across multiple RPCs with their own serialization and TLS
costs, with lazy caches that miss under load, and without a single
canonical payload hash to short-circuit replays.

v1 spends the cost once, at the gateway, against a pre-compiled graph,
and then uses the canonical hash to make every retry and every replay
free. That is why the delegated-authority path does not have to be slower
than the ambient one in practice: it pays in CPU what the ambient path
pays in distributed-systems complexity.

## Contract Version

Gateway contract version:

- `seedcore.agent_action_gateway.v1`

Downstream hot-path contract reference:

- `pdp.hot_path.asset_transfer.v1`

## Endpoint Surface

Primary endpoint:

- `POST /api/v1/agent-actions/evaluate`

Execution endpoint (v1, replay-safe via the same idempotency key):

- `POST /api/v1/agent-actions/execute`

Idempotency retrieval endpoint:

- `GET /api/v1/agent-actions/requests/{request_id}`

Closure endpoints (v1 scaffold):

- `POST /api/v1/agent-actions/{request_id}/closures`
- `GET /api/v1/agent-actions/closures/{closure_id}`

The evaluate endpoint is the only required call for v1 clients; execute and
closure endpoints are opt-in for clients that also need runtime execution and
forensic-block linkage through the gateway.

### Deployment Topology

The gateway surface can be served either from the main SeedCore API
(`seedcore.main:app`) or from a dedicated process
(`seedcore.gateway_service.main:app`). Both serve exactly the same routes
at the same paths; the choice is purely operational.

- Monolithic deploy: the default. `seedcore.main` mounts the gateway
  router alongside Tasks, Replay, Transfer Approvals, etc.
- Split deploy (recommended for external-facing environments): run the
  dedicated `seedcore.gateway_service` process (entrypoint
  `deploy/local/run-gateway.sh`) and set
  `SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY=false` on the monolith so
  only one process advertises `/api/v1/agent-actions/*`. The split allows
  the hot path to scale and fail independently of the management API, and
  limits the blast radius of a gateway compromise.

Clients never need to know which topology is in use — the contract, paths,
authentication, idempotency, and response shapes are identical either way.

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

- `asset.to_zone` if provided, otherwise `authority_scope.expected_to_zone`
  (the gateway applies this fallback deterministically so scope-only requests
  still produce a usable runtime resource)

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

The mapped `ActionIntent` plus request context is transformed into:

- `HotPathEvaluateRequest.contract_version = "pdp.hot_path.asset_transfer.v1"`
- `HotPathEvaluateRequest.request_id = request_id`
- `HotPathEvaluateRequest.requested_at = requested_at`
- `HotPathEvaluateRequest.policy_snapshot_ref = policy_snapshot_ref or security_contract.version`
- `HotPathEvaluateRequest.asset_context.asset_ref = asset.asset_id`
- `HotPathEvaluateRequest.telemetry_context` from `telemetry`, including:
  - `observed_at`
  - `freshness_seconds` / `max_allowed_age_seconds`
  - `current_zone`
  - `current_coordinate_ref`
  - `evidence_refs`

`HotPathTelemetryContext` exposes `current_zone` and `current_coordinate_ref`
as first-class fields (see `src/seedcore/models/pdp_hot_path.py`) so the hot
path can reason about physical scope directly instead of relying on the
gateway overlay.

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
- if the coordinate or zone proof is missing, stale, or unverifiable, return
  `quarantine`
- mismatch is a business decision outcome, not a transport-layer error

#### Deny Reason-Code Precedence

When multiple scope contradictions are detected simultaneously, the gateway
emits exactly one `decision.reason_code` using the following precedence:

1. `coordinate_scope_mismatch` — expected coordinate contradicts telemetry
2. `asset_product_scope_mismatch` — product identity contradicts persisted
   authority scope
3. `authority_scope_mismatch` — any other deterministic scope contradiction

`trust_gaps` always includes the generic `authority_scope_mismatch` plus the
specific mismatch code, so replay tooling can see both the class and the
specific cause.

#### Quarantine Reason-Code Precedence

When a scope claim cannot be verified (as opposed to contradicted):

1. `physical_presence_proof_missing` — coordinate-bound scope is requested but
   `forensic_context.fingerprint_components.physical_presence_hash` is absent
2. `coordinate_scope_unverified` — the physical-presence hash is present but
   `telemetry.current_coordinate_ref` was not supplied for this request
3. `telemetry_too_stale_for_scope_validation` — telemetry freshness exceeds
   the bound required for scope validation

The hot path's internal freshness code (`stale_telemetry`) is remapped to
`telemetry_too_stale_for_scope_validation` by the gateway so external callers
only see the contract-canonical codes.

## Closure Contract (Scaffold)

To align with the 2026 "closure and proof" layer, this v1 draft includes a
contract-first closure scaffold.

Current behavior (Phase B — hardened closure path):

- closure is accepted only for requests that were decided as `allow`
- closure acknowledgement is persisted with idempotency semantics
- settlement handoff is enabled by default
  (`SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF=true`)
- contradiction detection runs before any twin-service call, so a closure
  whose evidence disagrees with the authority scope is never credited as
  settled (see §"Contradiction Workflow" below)
- transient settlement failures (twin service raising, gate service missing
  during settlement) do not drop the closure — they produce
  `settlement_status=pending_reconcile` and enqueue the closure for the
  reconciler
- settlement status is one of:
  - `pending` — legacy flag-off short-circuit (only emitted when
    `SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF=false`)
  - `pending_reconcile` — queued for retry; the reconciler will either
    promote to `applied` or escalate to `rejected` after
    `SEEDCORE_AGENT_ACTION_SETTLEMENT_RECONCILE_MAX_ATTEMPTS` retries
  - `applied` — twin snapshot was updated and the governed audit record was
    written
  - `contradicted` — closure evidence contradicts the authority scope under
    which the action was authorized
  - `rejected` — settlement failed in a way that is not retryable (policy
    lockout, reconciler max-attempts exceeded, etc.)
- replay status is one of:
  - `pending` — waiting on settlement (legacy flag-off or not yet
    attempted)
  - `pending_reconcile` — explicit signal to downstream replay consumers
    that a reconciler pass is expected
  - `ready` — settlement is `applied` and the replay artifact can be
    assembled
  - `contradicted` — replay artifact must be assembled for investigation,
    not published as a normal transfer receipt

Primary response semantics:

- `status = accepted_pending_settlement`
- `settlement_status` reflects handoff outcome
- `replay_status` is derived deterministically from `settlement_status`:
  - `applied` → `ready`
  - `contradicted` → `contradicted`
  - `pending_reconcile` → `pending_reconcile`
  - otherwise → `pending`

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

Enforced closure requirements:

- `evidence_bundle_id` is required
- `forensic_block.forensic_block_id` must be supplied
- if closure evidence contradicts the authorized scope, settlement is
  `contradicted` (not `applied`) and the replay artifact remains available
  for investigation — a closure contradiction can never silently downgrade
  to success
- every `telemetry_refs[*].asset_ref` must equal the original request's
  `asset.asset_id` (422 otherwise)

### Contradiction Workflow

`_detect_closure_contradictions` runs before any twin-service interaction
and short-circuits the handoff with `settlement_status=contradicted` when
any of the following are true:

| Reason code                              | Trigger                                                                                 |
| ---------------------------------------- | --------------------------------------------------------------------------------------- |
| `outcome_contradicts_allow_decision`     | evaluate returned `allow` but the closure reports `outcome=quarantined` or `failed`     |
| `summary_to_zone_mismatch`               | `summary.observed_to_zone` differs from `authority_scope.expected_to_zone`              |
| `summary_coordinate_mismatch`            | `summary.observed_coordinate_ref` differs from `authority_scope.expected_coordinate_ref`|
| `summary_product_mismatch`               | `summary.observed_product_ref` differs from `authority_scope.product_ref` / `asset.product_ref` |

When any contradiction fires:

- `settlement_status = contradicted`
- `replay_status = contradicted`
- `settlement_result.error_code = closure_contradicts_authority_scope`
- `settlement_result.contradictions` carries the full list of reason codes
  and the specific expected/observed values
- `next_actions` contains `quarantine_asset`, `investigate_scope_mismatch`,
  and `assemble_replay_record` — the first two are the automated
  Contradiction Workflow steps downstream systems are expected to honor

### Settlement Reconciliation

When the twin service raises during `settle_from_evidence_bundle`, the
closure path enqueues the closure onto the Redis list
`seedcore:agent_actions:closure_reconcile` (with an in-memory fallback
when Redis is not reachable) and returns `settlement_status=pending_reconcile`.

Operators (or a scheduled job) drain that queue by calling
`seedcore.api.routers.agent_actions_router.reconcile_pending_closures()`:

- On success, the stored closure record is rewritten with
  `settlement_status=applied`, `replay_status=ready`, and
  `settlement_result.attempts` reflecting the retry count.
- On continued failure, the entry is re-queued with an incremented
  attempt count.
- After `SEEDCORE_AGENT_ACTION_SETTLEMENT_RECONCILE_MAX_ATTEMPTS` attempts
  (default 5), the reconciler escalates the record to
  `settlement_status=rejected` with
  `error_code=settlement_reconcile_max_attempts_exceeded` so no closure
  can linger as a "zombie" indefinitely.

## Error Contract

Deterministic error behavior (as implemented):

- `400` reserved for higher-level semantic contract failures that pydantic
  validation cannot express; not emitted in v1
- `401` missing/invalid caller authentication (feature-flagged; see §Security)
- `403` caller is authenticated but not authorized for requested workflow
  scope (feature-flagged role allowlist)
- `404` request or closure record not found for a lookup endpoint
- `409` idempotency conflict (same key, different canonical request hash) or
  `closure_not_allowed` (closure on a non-`allow` original decision)
- `422` schema/validation failure (covers unsupported `workflow.type`,
  unknown top-level fields, and every other request-shape rule)
- `503` dependency unavailable (for example the async PG session factory or
  the gateway auth secret when auth is enabled but unconfigured)

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
  (`idempotency_conflict`)
- a duplicate key claimed by an in-flight request returns `409`
  (`idempotency_in_progress`)
- canonical hash must include:
  - authority scope fields
  - hardware fingerprint fields
  - asset and product identity fields
  - security contract fields
  - `options.no_execute` and `options.debug`
- retention is at least 24 hours

Retention is enforced by `SETEX` when Redis is reachable (key prefix
`seedcore:agent_actions:idem`) and by an opportunistic in-memory GC pass
keyed on `REQUEST_RECORD_TTL_SECONDS` (default 86 400 s, configurable via
`SEEDCORE_AGENT_ACTION_REQUEST_RECORD_TTL_SECONDS`) when Redis is disabled.

This prevents duplicate transfer execution from retry storms and stops callers
from reusing the same idempotency key with altered scope.

## Security Requirements

Minimum boundary expectations:

- gateway caller must authenticate as an approved agent principal (see the
  authentication flag below)
- request principal must map to a delegated authority path for the target
  physical good (`asset` in the current schema)
- request must carry device or hardware fingerprint metadata sufficient to bind
  the action to an accountable node
- approval envelope must resolve from persisted records
- authority scope must resolve from persisted or deterministic runtime truth
- policy snapshot reference used in decision must be recorded in response

### Authentication Boundary (Feature-Flagged)

v1 ships a feature-flagged HTTP authentication dependency on every gateway
route. It is disabled by default to preserve in-process and internal-ingress
callers; enable it for any external-facing deployment:

| Environment variable | Default | Effect |
|---|---|---|
| `SEEDCORE_AGENT_ACTION_GATEWAY_AUTH_MODE` | `off` | `shared_key` or `bearer` activates enforcement |
| `SEEDCORE_AGENT_ACTION_GATEWAY_AUTH_TOKEN` | empty | Required bearer secret when auth is enabled; missing secret produces `503 gateway_auth_not_configured` |
| `SEEDCORE_AGENT_ACTION_GATEWAY_ALLOWED_ROLES` | empty | Optional comma-separated allowlist; unknown role produces `403 role_not_authorized_for_workflow` |
| `SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_MODE` | `shadow` | `shadow` logs owner/delegation/agent mismatches without blocking; `enforce` fails closed; `off` skips the guard |
| `SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_CACHE_TTL_SECONDS` | `30` | In-process TTL cache for delegation validation lookups |

When enforcement is on, callers must send `Authorization: Bearer <token>`.
Missing or malformed headers return `401 missing_credentials`; wrong tokens
return `401 invalid_credentials`.

Optional but recommended for hardened profiles:

- detached request signature for non-repudiation
- mTLS between caller and gateway in controlled enterprise deployments
- attestation verification against a trust bundle for hardened edge profiles

## Observability Requirements

Every evaluate decision emits one structured log record with the event name
`agent_action_gateway.evaluate.decision` and carries:

- `request_id`
- `idempotency_key`
- `agent_id` (from `principal.agent_id`)
- `hardware_fingerprint_id`
- `asset_id`
- `product_ref` when provided
- `approval_envelope_id`
- `scope_id`
- `expected_coordinate_ref`
- `disposition`
- `reason_code`
- `policy_snapshot_ref`
- `latency_ms`
- `authority_scope_status`
- `trust_gaps`

Every closure decision emits `agent_action_gateway.closure.decision` with:

- `request_id`
- `closure_id`
- `idempotency_key`
- `evidence_bundle_id`
- `forensic_block_id`
- `settlement_status`
- `replay_status`
- `linked_disposition`

Logging is fail-soft: any exception inside the log path is swallowed so
observability can never break the request path.

## Rollout Plan

### Phase A: Adapter Mode — delivered

- `POST /api/v1/agent-actions/evaluate` exposed at
  `src/seedcore/api/routers/agent_actions_router.py`
- `GET /api/v1/agent-actions/requests/{request_id}` backed by an in-memory +
  Redis-aware request-record store with 24h retention
- internal mapping to the existing hot-path evaluation path with all
  `gateway.*` parameters preserved on `ActionIntent.action.parameters`
- output contract is stable while internal scoring continues to evolve
- zone- and asset-scoped validation active in the `_build_authority_scope_verdict`
  overlay, with coordinate-precision quarantine paths already wired

### Phase B: First-Class Gateway — delivered

Delivered:

- persisted idempotency records with canonical request hash and replay-safe
  response cache (Redis-backed when reachable, TTL-honoring in-memory
  fallback otherwise)
- contract tests in `tests/test_agent_actions_router.py` and
  `tests/test_agent_action_gateway_productization.py`
- one reference client adapter in
  `scripts/host/verify_agent_action_gateway_productization_real_calls.py`
- first-class forensic-block linkage in the closure scaffold
- red-team coverage for coordinate redirect (deny) and coordinate-scope
  unverified (quarantine)
- dedicated gateway process split — the agent action gateway can now be
  served as its own FastAPI application (`seedcore.gateway_service.main`,
  `deploy/local/run-gateway.sh`) so the external-facing surface can scale
  and fail independently of the management API
- `SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY` lets the monolith stop
  advertising `/api/v1/agent-actions/*` once the dedicated process is the
  single source of truth
- closure path hardened into a production settlement layer:
  `SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF` now defaults to `true`;
  `_detect_closure_contradictions` blocks contradictory closures before they
  can touch the twin service; transient settlement faults return
  `settlement_status=pending_reconcile` and are retried by
  `reconcile_pending_closures(...)` with a bounded retry budget and an
  explicit escalation path
- delegation lookup optimization on owner-twin resolution path:
  `_list_owner_delegations` now filters `delegation:*` rows at SQL selection
  time instead of scanning all owner facts in Python
- idempotency/request-record Redis write optimization:
  `_write_request_record` now pipelines Redis writes to reduce evaluate-path
  round-trip cost

Still pending:

- red-team fixtures for full MITM authority-replay scenarios beyond the
  coordinate-mismatch drill (delegation replay, stale-telemetry reuse)
- mTLS + detached-signature hardening of the external boundary (Security
  track B)
- promotion-SLO closure under concurrent load for hot-path benchmark lanes
  (keep parity at zero mismatches while meeting p50/p95/p99 thresholds)

## Acceptance Criteria

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | One external agent client can execute end-to-end RCT evaluation | Met | `scripts/host/verify_agent_action_gateway_productization_real_calls.py`, `tests/test_agent_action_gateway_productization.py` |
| 2 | All four dispositions (`allow`/`deny`/`quarantine`/`escalate`) are returned deterministically | Met | `tests/test_agent_actions_router.py::test_agent_actions_evaluate_wraps_hot_path_result`, `::test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch`, `::test_agent_actions_evaluate_quarantines_when_coordinate_scope_unverified`, `::test_agent_actions_evaluate_passes_through_escalate_disposition` |
| 3 | Mapping to internal `ActionIntent` and hot-path request is fully tested | Met | `::test_agent_actions_evaluate_maps_gateway_payload_to_hot_path_request`, `::test_agent_actions_evaluate_maps_scope_and_fingerprint_fields`, `::test_agent_actions_evaluate_forwards_current_zone_and_coordinate_to_hot_path`, `::test_agent_actions_evaluate_target_zone_falls_back_to_authority_scope` |
| 4 | Idempotency behavior is tested for replay and conflict paths | Met | `::test_agent_actions_idempotency_replay_and_conflict`, `::test_agent_action_gateway_in_memory_idempotency_respects_ttl` |
| 5 | Response includes enough fields for operator and replay correlation | Met | `::test_gateway_request_to_replay_correlation_*`, `::test_agent_action_gateway_decision_log_is_emitted` |
| 6 | Coordinate or zone mismatch can be reproduced as deterministic `deny` or `quarantine` | Met | Mismatch: `::test_agent_actions_evaluate_denies_when_scope_coordinate_mismatch`; quarantine: `::test_agent_actions_evaluate_quarantines_when_coordinate_scope_unverified` and `::test_agent_actions_evaluate_quarantines_when_physical_presence_proof_missing`; stale remap: `::test_agent_actions_evaluate_remaps_stale_telemetry_reason_code` |
| 7 | Closure can link the resulting evidence bundle and forensic block back to the original request | Met | Closure tests and `::test_build_closure_evidence_bundle_includes_forensic_block` |
| 8 | A closure whose evidence contradicts the authority scope never downgrades to a successful settlement | Met | `::test_agent_actions_closure_detects_outcome_contradiction`, `::test_agent_actions_closure_detects_summary_zone_contradiction` |
| 9 | Transient settlement faults are retried rather than dropped, with an explicit max-attempt escalation | Met | `::test_agent_actions_closure_pending_reconcile_when_settlement_raises`, `::test_reconcile_pending_closures_applies_when_service_recovers`, `::test_reconcile_pending_closures_escalates_after_max_attempts` |
| 10 | The agent action gateway can be served from its own FastAPI process | Met | `tests/test_gateway_service_app.py`, `deploy/local/run-gateway.sh`, `src/seedcore/gateway_service/main.py` |

## Implementation Notes

v1 of this contract lives in the following files:

- Request/response/closure pydantic models:
  `src/seedcore/models/agent_action_gateway.py`
- Router and overlay logic (scope verdict, reason-code precedence, auth
  dependency, structured logging, in-memory TTL, contradiction detection,
  settlement reconciliation):
  `src/seedcore/api/routers/agent_actions_router.py`
- Dedicated gateway FastAPI app (process split):
  `src/seedcore/gateway_service/main.py`
  (entrypoint: `deploy/local/run-gateway.sh`)
- Hot-path telemetry and decision view models:
  `src/seedcore/models/pdp_hot_path.py`
- Generated JSON schema artifact for external clients:
  `docs/references/contracts/seedcore.agent_action_gateway.v1.schema.json`
  (regenerate with `scripts/tools/generate_agent_action_gateway_schema.py`)
- Contract tests: `tests/test_agent_actions_router.py`,
  `tests/test_agent_action_gateway_productization.py`,
  `tests/test_agent_action_gateway_schema.py`,
  `tests/test_gateway_service_app.py`
- Reference client and live verification:
  `scripts/host/verify_agent_action_gateway_productization_real_calls.py`
- Red-team drill wrapper:
  `scripts/host/verify_q2_degraded_edge_drill_matrix.sh`

Feature flags:

- `SEEDCORE_AGENT_ACTION_ENABLE_SETTLEMENT_HANDOFF` — enable settlement
  handoff during closure (default `true`; when `false` the legacy
  `settlement_status=pending` short-circuit is used)
- `SEEDCORE_AGENT_ACTION_SETTLEMENT_RECONCILE_MAX_ATTEMPTS` — bounded retry
  budget for closures stuck in `pending_reconcile` (default `5`; the
  reconciler escalates to `rejected` once exceeded)
- `SEEDCORE_MAIN_API_MOUNT_AGENT_ACTION_GATEWAY` — when `false`, the
  monolithic `seedcore.main` API stops registering the gateway router so
  the dedicated `seedcore.gateway_service` process is the single source of
  truth for `/api/v1/agent-actions/*` (default `true` for back-compat)
- `SEEDCORE_AGENT_ACTION_GATEWAY_AUTH_MODE` / `..._AUTH_TOKEN` /
  `..._ALLOWED_ROLES` — activate the authentication boundary
- `SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_MODE` — choose `shadow`,
  `enforce`, or `off` for persisted delegation validation
- `SEEDCORE_AGENT_ACTION_DELEGATION_VALIDATION_CACHE_TTL_SECONDS` — tune the
  short in-process cache used by delegation validation
- `SEEDCORE_AGENT_ACTION_DISABLE_REDIS_STORE` — force the in-memory
  idempotency/record store for tests or local-only deployments
- `SEEDCORE_AGENT_ACTION_REQUEST_RECORD_TTL_SECONDS` — override the default
  24-hour retention floor

## Related Documents

- [seedcore_2026_execution_plan.md](seedcore_2026_execution_plan.md)
- [current_next_steps.md](current_next_steps.md)
- [hot_path_shadow_to_enforce_breakdown.md](/Users/ningli/project/seedcore/docs/development/hot_path_shadow_to_enforce_breakdown.md)
- [asset_centric_pdp_hot_path_contract.md](/Users/ningli/project/seedcore/docs/development/asset_centric_pdp_hot_path_contract.md)
- [next_killer_demo_contract_freeze.md](archive/historical/next_killer_demo_contract_freeze.md)
- [src/seedcore/models/action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py)
- [src/seedcore/models/pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/models/pdp_hot_path.py)
- [src/seedcore/models/agent_action_gateway.py](/Users/ningli/project/seedcore/src/seedcore/models/agent_action_gateway.py)
- [src/seedcore/api/routers/agent_actions_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/agent_actions_router.py)
- [docs/references/contracts/seedcore.agent_action_gateway.v1.schema.json](/Users/ningli/project/seedcore/docs/references/contracts/seedcore.agent_action_gateway.v1.schema.json)
