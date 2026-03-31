# SeedCore API Reference

This document is a practical reference for the currently mounted `seedcore-api` surface defined by [main.py](/Users/ningli/project/seedcore/src/seedcore/main.py) and the active router registry in [__init__.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/__init__.py).

It is intentionally runtime-oriented: it describes what the application actually exposes today, how those endpoints are grouped, and a few important behavior notes from startup and readiness handling.

## 1. Application Surface

SeedCore runs a FastAPI application with:

- title: `SeedCore API`
- version: `1.0.0`
- primary API prefix: `/api/v1`
- interactive docs: `/docs`
- OpenAPI schema: `/openapi.json`

All active routers are mounted under `/api/v1` in this order:

1. Tasks
2. Replay
3. Source Registrations
4. Tracking Events
5. Identity
6. Control
7. Advisory
8. PKG
9. Capabilities

Legacy routers still exist in the codebase under `src/seedcore/api/routers/legacy`, but they are not part of the active mounted surface returned by `get_active_routers()`.

## 2. Runtime And Startup Notes

Important behavior from [main.py](/Users/ningli/project/seedcore/src/seedcore/main.py):

- CORS origins come from `CORS_ALLOW_ORIGINS`, defaulting to `*`.
- `RUN_DDL_ON_STARTUP=true` causes task and fact tables to be created on boot.
- Startup verifies database support for `ensure_task_node(uuid)`.
- Startup checks snapshot support through `pkg_active_snapshot_id(pkg_env)`.
- PKG manager initialization is attempted at startup, but failure is non-fatal.
- Task processing is expected to happen through dispatcher Ray actors, not inside this API process.

## 3. Unprefixed Operational Endpoints

These endpoints are mounted directly on the app, not under `/api/v1`.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/` | Basic welcome payload with links to docs and health. |
| `GET` | `/health` | Liveness check for the API process. |
| `GET` | `/readyz` | Readiness check with dependency status, currently focused on DB connectivity. |
| `GET` | `/_env` | Optional debug env dump, only mounted when `ENABLE_DEBUG_ENV=true`. |

## 4. Tasks API

Implemented in [tasks_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/tasks_router.py).

### 4.1 Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/tasks` | Create a task row and queue it for downstream processing. |
| `GET` | `/api/v1/tasks` | List tasks, optionally filtered by `snapshot_id`. |
| `GET` | `/api/v1/tasks/{task_id}` | Fetch a task by UUID or UUID prefix. |
| `GET` | `/api/v1/tasks/{task_id}/governance` | Return governed execution audit entries associated with a task. |
| `GET` | `/api/v1/governance/materialized-custody-event` | Backward-compatible JSON-LD materialization view, now backed by the replay service. |
| `POST` | `/api/v1/tasks/{task_id}/cancel` | Cancel a non-terminal task. |
| `GET` | `/api/v1/tasks/{task_id}/logs` | Stream task logs and metadata over Server-Sent Events. |

### 4.2 Notes

- `POST /tasks` creates the task and ensures a graph node mapping through `ensure_task_node(...)`.
- `GET /tasks/{task_id}/logs` returns `text/event-stream`.
- The governance materialization endpoint accepts one replay lookup key: `task_id`, `intent_id`, or `audit_id`.

## 5. Replay, Trust, And Verification API

Implemented in [replay_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/replay_router.py).

This router exposes the replay/trust MVP layer over governed audit records, evidence bundles, custody state, and digital twin history.

### 5.1 Replay Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/v1/replay` | Assemble a normalized replay record and return a projection view. |
| `GET` | `/api/v1/replay/timeline` | Return replay timeline events and verification status. |
| `GET` | `/api/v1/replay/artifacts` | Return replay artifacts, either full internal artifacts or public-safe summaries based on projection. |
| `GET` | `/api/v1/replay/jsonld` | Return JSON-LD generated from the replay record. |

### 5.2 Trust Publishing And Public Retrieval

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/trust/publish` | Mint a signed public trust reference for a replayable record. |
| `POST` | `/api/v1/trust/refresh` | Mint a fresh signed public trust reference. |
| `POST` | `/api/v1/trust/revoke` | Revoke a public trust reference through Redis-backed revocation state. |
| `GET` | `/api/v1/trust/{public_id}` | Return the public trust page projection as JSON. |
| `GET` | `/api/v1/trust/{public_id}/jsonld` | Return the public JSON-LD trust artifact. |
| `GET` | `/api/v1/trust/{public_id}/certificate` | Return a signed trust certificate. |

### 5.3 Verification Endpoints

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/v1/verify/{reference_id}` | Verify a trust reference token directly. |
| `POST` | `/api/v1/verify` | Verify by exactly one of `reference_id`, `public_id`, `audit_id`, or `subject_id`. |

### 5.4 Notes

- Replay lookups require exactly one of `task_id`, `intent_id`, or `audit_id`.
- Projection modes currently include `internal`, `auditor`, `buyer`, and `public`.
- Public trust references are signed and time-bounded.
- Revocation depends on Redis. If Redis is unavailable, revoke returns `503`.
- Expired or revoked trust references return `410 Gone` semantics on public trust retrieval.
- Trust-facing projections now include normalized `trust_gap_details` derived from `trust_gap_codes`.
- When present in governed receipts, owner context references (`owner_id`, creator profile ref, trust preference ref) are surfaced in `authorization` and `policy_summary`.
- JSON-LD trust exports now include `proof.trust_gap_codes`, `proof.trust_gap_details`, and owner context references when available.
- Materialized custody-event `policy_verification` now includes `authority_consistency`, `authority_consistency_hash`, and `operator_actions` for forensic triage parity.
- Trust certificates now include `trust_gap_codes`, `trust_gap_details`, and owner context references when available.
- Verification now fails with `owner_identity_mismatch` or `delegation_ref_mismatch` when replay authority bindings conflict across principal, gateway, and governed owner context records.
- Verification of signed trust tokens now fails with `reference_subject_mismatch` when token subject bindings diverge from replay-resolved subject identity.
- Trust publish/refresh now return `409` with `authority_binding_mismatch` when replay authority bindings are inconsistent before token minting.
- Successful trust publish/refresh responses now include `authority_consistency`, `authority_consistency_hash`, and `operator_actions`.
- `409 authority_binding_mismatch` responses now also include `authority_consistency`, `authority_consistency_hash`, and `operator_actions` for immediate triage.
- Trust-page projections now include `authority_consistency` in `verification_status`, `authorization`, and `policy_summary` for operator triage.
- Trust-page projections now also expose top-level `authority_consistency_hash` for direct cross-artifact comparison.
- Trust-page projections now also expose top-level `authority_consistency` for direct API consumers.
- Trust-page projections now include `operator_actions` with remediation hints when authority consistency issues are present.
- Public replay-artifact payloads now include `authority_consistency_hash` and `operator_actions` for lightweight triage parity.
- Trust-page/certificate/verifier claim sets now include authority-binding claims (`authority_binding_consistent`, `authority_binding_mismatch_detected`).
- Trust certificates now include `operator_actions` so exported artifacts preserve operator remediation guidance.
- Trust-page `authority_consistency` and trust certificates now include `authority_consistency_hash` for quick cross-artifact consistency comparison.
- Trust certificates now include full `authority_consistency` (`ok`, `issues`, `hash`) for direct verifier inspection.
- JSON-LD proof exports now include `proof.authority_consistency_hash` for cross-artifact consistency comparison.
- JSON-LD proof exports now include `proof.operator_actions` for remediation guidance parity with trust page/certificate/verify surfaces.
- JSON-LD proof exports now include full `proof.authority_consistency` (`ok`, `issues`, `hash`) for direct verifier inspection.
- Verification responses now include `authority_consistency` and `authority_consistency_hash` when replay context is available.
- Verification responses now include `operator_actions` for direct remediation guidance on authority mismatch cases.

## 6. Source Registration API

Implemented in [source_registrations_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/source_registrations_router.py).

This surface supports governed provenance-heavy registration intake and decision submission.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/source-registrations` | Create a source registration and emit initial tracking events for declared evidence and measurements. |
| `GET` | `/api/v1/source-registrations/{registration_id}` | Fetch the projected source registration view. |
| `POST` | `/api/v1/source-registrations/{registration_id}/artifacts` | Add a new provenance or seal artifact to an existing registration. |
| `POST` | `/api/v1/source-registrations/{registration_id}/submit` | Submit the registration into the governed decision workflow and create a task. |
| `GET` | `/api/v1/source-registrations/{registration_id}/verdict` | Fetch the latest registration decision verdict. |

### 6.1 Notes

- Submission creates a task in the `provenance` domain.
- Source registration writes are coupled to `TrackingEvent` ingestion rather than relying only on direct table mutation.

## 7. Tracking Events API

Implemented in [tracking_events_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/tracking_events_router.py).

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/tracking-events` | Ingest a tracking event directly. |
| `GET` | `/api/v1/tracking-events` | List tracking events. |
| `GET` | `/api/v1/tracking-events/{event_id}` | Fetch a single tracking event. |
| `GET` | `/api/v1/source-registrations/{registration_id}/tracking-events` | List tracking events scoped to a source registration. |

Tracking events form the append-only provenance ingress stream used by source registration projection flows.

## 8. Identity And Delegation API

Implemented in [identity_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/identity_router.py).

This surface adds the missing external authority APIs needed for DID-style identity, delegation lifecycle management, and externally signed intent submission.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/identities/dids` | Register or replace a DID document used for external intent signing. |
| `PATCH` | `/api/v1/identities/dids/{did}` | Update a registered DID document. |
| `GET` | `/api/v1/identities/dids/{did}` | Fetch the current DID document. |
| `POST` | `/api/v1/delegations` | Grant delegated authority from an owner DID to an assistant DID. |
| `GET` | `/api/v1/delegations/{delegation_id}` | Fetch a delegation record. |
| `POST` | `/api/v1/delegations/{delegation_id}/revoke` | Revoke a delegation record. |
| `POST` | `/api/v1/creator-profiles` | Upsert creator profile metadata for an owner DID. |
| `GET` | `/api/v1/creator-profiles/{owner_id}` | Fetch the current creator profile for an owner DID. |
| `POST` | `/api/v1/trust-preferences` | Upsert owner trust-preference policy hints. |
| `GET` | `/api/v1/trust-preferences/{owner_id}` | Fetch current trust preferences for an owner DID. |
| `POST` | `/api/v1/intents/submit-signed` | Verify an externally signed `ActionIntent` and run it through the current PDP flow. |

### 8.1 Notes

- DID and delegation records are currently persisted using the existing facts table in the `identity` namespace.
- Creator profile and trust preference records are also persisted in the `identity` namespace as owner-scoped fact records.
- Externally signed intent submission currently supports `ed25519` and `hmac_sha256`.
- Signed submission requires nonce protection and rejects replayed nonces.
- Signed submission verifies ingress authenticity but still runs the normal PDP and delegation checks before issuing `ExecutionToken`.

## 9. Custody API

Implemented in [custody_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/custody_router.py).

This surface exposes the new custody graph, lineage, search, and dispute workflows over the append-only custody transition chain.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/v1/custody/assets/{asset_id}/lineage` | Return the ordered lineage chain for an asset plus linked artifacts and disputes. |
| `GET` | `/api/v1/custody/assets/{asset_id}/transitions` | Return custody transition events for an asset. |
| `GET` | `/api/v1/custody/assets/{asset_id}/graph` | Return a graph projection with `{nodes, edges, root_node_id}` for the asset investigation view. |
| `GET` | `/api/v1/custody/query` | Search custody transitions by asset, intent, task, token, zone, actor, endpoint, time range, and dispute status. |
| `GET` | `/api/v1/custody/disputes` | List dispute cases, optionally filtered by asset or status. |
| `GET` | `/api/v1/custody/disputes/{dispute_id}` | Fetch one dispute case with append-only dispute events. |
| `POST` | `/api/v1/custody/disputes` | Open a dispute linked to custody graph entities. |
| `POST` | `/api/v1/custody/disputes/{dispute_id}/events` | Append a dispute event or move a dispute into review. |
| `POST` | `/api/v1/custody/disputes/{dispute_id}/resolve` | Resolve or reject a dispute case. |

### 9.1 Notes

- Custody lineage is now persisted in `custody_transition_event` and treated as the canonical append-only transition chain.
- Graph projection is Postgres-first and does not rely on Neo4j for correctness.
- Replay records now surface linked custody transition refs and dispute refs without exposing the full internal graph by default.

## 10. Control API

Implemented in [control_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/control_router.py).

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `GET` | `/api/v1/facts` | List control-plane facts. |
| `GET` | `/api/v1/facts/{fact_id}` | Fetch one fact. |
| `POST` | `/api/v1/facts` | Create a fact. |
| `PATCH` | `/api/v1/facts/{fact_id}` | Update part of a fact. |
| `DELETE` | `/api/v1/facts/{fact_id}` | Delete a fact. |

This is the lightweight CRUD control-plane surface currently mounted in the active API.

## 11. Advisory API

Implemented in [advisory_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/advisory_router.py).

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/advisory` | Run advisory evaluation and return non-binding governance-style guidance. |

This route is advisory-only. It does not replace the governed authorization path for controlled execution.

## 12. PKG API

Implemented in [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py).

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/pkg/reload` | Reload the active PKG evaluator state. |
| `POST` | `/api/v1/pkg/snapshots/{snapshot_version}/activate` | Activate a snapshot and publish hot-update events fleet-wide. |
| `POST` | `/api/v1/pkg/authz-graph/refresh` | Refresh the active compiled authorization graph for the current PKG snapshot. |
| `GET` | `/api/v1/pkg/status` | Report PKG runtime status. |
| `GET` | `/api/v1/pkg/authz-graph/status` | Report active authorization graph runtime status. |
| `POST` | `/api/v1/pkg/ota/heartbeat` | Record edge runtime heartbeat and resolve desired policy snapshot for compliance. |
| `GET` | `/api/v1/pkg/ota/stream` | Open always-on OTA policy stream (SSE) for edge runtimes. |
| `POST` | `/api/v1/pkg/evaluate_async` | Run asynchronous policy evaluation. |
| `POST` | `/api/v1/pkg/snapshots/compare` | Compare two policy snapshots. |
| `POST` | `/api/v1/pkg/snapshots/{snapshot_id}/compile-rules` | Compile rules for a specific snapshot. |

These endpoints support policy runtime inspection and snapshot-oriented operations.

### 12.1 Notes

- `GET /api/v1/pkg/status` now includes `authz_graph_ready` plus an `authz_graph` summary when the PKG manager is initialized.
- `GET /api/v1/pkg/authz-graph/status` is the focused operational status view for the active compiled authorization graph.
- `POST /api/v1/pkg/authz-graph/refresh` rebuilds the active compiled authorization graph from snapshot-scoped sources without requiring a full PKG evaluator reload.
- `POST /api/v1/pkg/snapshots/{snapshot_version}/activate` is the primary hot-rollout control-plane path for live policy activation.
- `POST /api/v1/pkg/ota/heartbeat` + `GET /api/v1/pkg/ota/stream` provide edge compliance and always-on OTA distribution.
- The PDP only auto-consumes the active compiled authorization graph when `SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true`.
- Redis PKG control-plane messages now support both evaluator activation and authz-graph refresh semantics.

## 13. Capabilities API

Implemented in [capabilities_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/capabilities_router.py).

| Method | Path | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/capabilities/register` | Register or refresh runtime capability definitions. |

This endpoint is the active mounted capability-management surface at the moment.

## 14. Quick Practical Rules

- Treat `/health` as process liveness and `/readyz` as dependency readiness.
- Treat `/api/v1/replay*`, `/api/v1/trust*`, and `/api/v1/verify*` as the canonical replay/trust API family.
- Treat `/api/v1/identities/dids*`, `/api/v1/delegations*`, and `/api/v1/intents/submit-signed` as the external authority ingress family.
- Treat `/api/v1/custody*` as the canonical lineage, graph, and dispute workflow family.
- Prefer `/api/v1/replay/jsonld` over older one-off JSON-LD generation paths for new integrations.
- Use `/api/v1/tasks/{task_id}/logs` only for streaming clients that can consume SSE.
- Use `/api/v1/pkg/authz-graph/status` and `/api/v1/pkg/authz-graph/refresh` for authz-graph operations instead of inferring state from general PKG logs.
- Do not assume legacy routers are mounted just because they exist in the repository.
