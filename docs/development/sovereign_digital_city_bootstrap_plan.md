# Sovereign Digital City Bootstrap Plan

Date: 2026-08-20
Status: Reference fixture, C1b persistence with isolated PostgreSQL schema-restore/reseed verification, and read-only REST discovery implemented; MCP and governed action pending
Owner posture: SeedCore constructs and operates the initial digital-city infrastructure directly

## 1. Decision

The first version of the SeedCore digital city should not wait for a tourism
board, super-app, payment protocol, logistics provider, merchant platform, or
municipal data program.

SeedCore should build a **sovereign, closed-world city kernel** that can be
operated by one founder at the beginning:

```text
SeedCore owns the initial software, schemas, storage, APIs, agent surfaces,
fixtures, operator tools, and deployment.

External institutions continue to own the real-world authority of their
claims, payments, transport, certifications, and public responsibilities.
```

This is not a contradiction. Owning the platform implementation is different
from claiming authority over every fact or real-world service represented by
the platform.

The bootstrap objective is:

> Build one locally operable digital-city substrate that represents a real
> district shape—land, buildings, roads, utilities, facilities, environment,
> projects, and incidents—and then demonstrates producer onboarding, public
> discovery, agent access, ordinary service coordination, one governed
> infrastructure action, one governed commerce/custody action, and replayable
> proof without requiring a live external integration.

The collectible rare-shoe RCT path remains the implemented trust-runtime wedge.
The city kernel reuses that authority spine rather than replacing or forking it.

Implemented bootstrap checkpoint:

- strict `CityFeatureV0`, `GeometryEnvelopeV0`, five state-axis, relationship,
  source, and visibility models;
- the canonical packaged 5-3-2-1-1 JSON fixture;
- deterministic public/protected fixture loading and lookup;
- registered read-only discovery query, projection, and anchor endpoints;
- pure-Python Haversine radius filtering and distance ordering;
- fail-closed `bootstrap_sim` request gating and focused tests;
- a three-table `seedcore_city_foundation` migration, explicit PostgreSQL
  repository, transactional fixture seeding, strict hydration parity, and
  fixture-or-Postgres storage selection with no configured-path fallback; and
- isolated PostgreSQL 17 verification of clean migration, scoped read/write
  grants, seed/reload, schema-only dump/restore followed by reseed/reload
  parity, and unchanged discovery responses.

Not yet implemented or promoted: producer projection composition, proof-page
rendering, MCP wrappers, reservations, simulated infrastructure execution, or
C3 governed-transition proof. PostgreSQL selection also remains explicit and
review-gated rather than the bootstrap default.

## 2. What Sovereign Means

### 2.1 SeedCore owns initially

- the city subject and service registry;
- the foundation feature registry for regions, land, sites, buildings,
  structures, spaces, roads, paths, utilities, facilities, environment,
  projects, work packages, observations, and incidents;
- versioned geometry, topology, relationships, temporal state, and redacted
  twin projections for the reference district;
- producer/merchant onboarding and profile lifecycle;
- source-linked draft ingestion and confirmation UX;
- local fixtures and manually curated seed data;
- public-safe trust projections and proof pages;
- structured spatial indexing and discovery;
- a basic availability and reservation ledger for the closed-world pilot;
- action classification and proposal routing;
- SeedCore Agent Action Gateway integration for governed actions;
- evidence, replay, verifier, and quarantine linkage;
- REST, MCP, SDK, operator, and simple web/map surfaces;
- the host-mode deployment, backups, migrations, observability, and runbooks;
- simulated commerce, logistics, certification, and municipal adapters;
- deterministic sensor, utility, inspection, contractor, and construction
  workflow simulators;
- the conformance tests that future live adapters must pass.

### 2.2 SeedCore does not claim initially

- that a simulated payment is a real payment authorization;
- that a simulated ride is a licensed transport service;
- that a producer declaration is an external certification;
- that a public anchor proves legal ownership, land rights, organic status, or
  regulatory compliance;
- that a city fixture is official municipal data;
- that a fixture parcel establishes title, a design is as-built truth, an
  imported BIM model proves physical state, or a simulated permit/inspection
  has legal effect;
- that SeedCore is a planning authority, utility operator, engineer of record,
  emergency service, or certified survey source;
- that a local reservation ledger makes SeedCore the merchant of record;
- that the platform may expose private locations, people, or media without
  consent;
- that operating all software modules permits one module to bypass the PDP,
  token, evidence, replay, or verifier boundaries.

### 2.3 Bootstrap labels

Every record and surface must expose its environment and source posture:

| Label | Meaning |
| --- | --- |
| `FIXTURE` | deterministic test data; no real-world claim |
| `SIMULATED_PROVIDER` | locally operated payment, logistics, certification, booking, route, utility, sensor, inspection, or contractor behavior |
| `PRODUCER_DECLARED` | confirmed by the producer but not independently verified |
| `SEEDCORE_REGISTERED` | admitted into a SeedCore registration record under a named profile |
| `EXTERNALLY_ATTESTED` | supplied by a named external issuer and checked under an explicit policy profile |
| `VERIFIED_FOR_CURRENT_PROFILE` | current evidence satisfies the named SeedCore verifier/policy profile |
| `PRESENTATION_ONLY` | narrative, translation, map styling, image, video, 3D, or XR content |
| `SIMULATION_ONLY` | a verifier/result disposition valid only for the isolated bootstrap simulation profile; never a live closure |

The bootstrap UI must never render a fixture or simulated-provider result as a
live institutional fact.

## 3. Solo-First Engineering Doctrine

The first infrastructure should optimize for legibility, deterministic tests,
and one-person operability.

### 3.1 Build a modular monolith first

Use one deployable API/application boundary with strong internal modules rather
than creating a fleet of new microservices.

```text
SeedCore host runtime
  ├── lightweight CityFeatureV0 / geometry / relationship model
  ├── five-parcel deterministic JSON reference fixture
  ├── deterministic foundation and producer projections
  ├── read-only discovery REST/MCP surface
  ├── producer/service profile and ordinary reservation modules
  ├── explicitly gated simulated provider adapters
  ├── existing Agent Action Gateway / PDP / token path
  ├── existing evidence / replay / RESULT_VERIFIER path
  └── public proof and operator surfaces
```

Internal boundaries should still be explicit enough to split later. The first
goal is not service topology. It is a correct end-to-end contract.

### 3.2 Reuse the current host stack

Bootstrap with infrastructure already understood by the repository:

| Component | Initial role |
| --- | --- |
| Existing FastAPI/API runtime | city REST routes, producer workflows, action routing |
| PostgreSQL | durable subjects, profiles, projections, reservations, provider events, read traces |
| Redis | existing token revocation, cutoff, and bounded hot-path support; not city truth |
| Local artifact/object-store adapter | raw intake media, manifests, public-safe derivatives, fixture artifacts |
| Existing Ray/coordinator paths | reuse only where current SeedCore behavior already depends on them |
| Existing Rust proof kernel | strict replay/proof verification where the current contracts support it |
| Existing TypeScript surfaces | operator and proof UI extension after API contracts stabilize |

Do not make Kafka, Kubernetes, Neo4j, a vector database, a search cluster, a
tile server, PostGIS, H3, an OGC service, a BIM/IFC parser, a GPU render farm,
or a new cloud account prerequisites for the first city slice. Add them only
after a measured correctness, scale, isolation, durability, or product
requirement appears.

### 3.3 One process does not mean one authority domain

Even when modules share a process and database:

- discovery tables do not write policy outcomes;
- availability rows do not mint tokens;
- simulated payment rows do not authorize custody;
- city-admin credentials do not automatically clear quarantine;
- presentation artifacts do not enter evidence tables;
- the PDP evaluates an explicit request package rather than reading ambient
  city application state;
- verifier closure is derived from evidence, not an application "completed"
  flag.

Database roles, repository interfaces, route scopes, and tests should enforce
those distinctions before service separation is considered.

## 4. Initial City Kernel

The city kernel has two compositional layers:

1. a **city foundation layer** for spatial identity, land, built assets,
   networks, facilities, environment, observations, construction, operations,
   and twin settlement;
2. a **city service layer** for producers, service profiles, public proof,
   discovery, availability, reservations, and agent proposals.

The full foundation-domain model, state axes, construction lifecycle, storage
shape, governed infrastructure-action flow, and slices are defined in
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md).
The ten modules below are the service layer and must sit on stable foundation
feature refs rather than inventing separate place, building, road, or facility
identities.

### 4.1 City subject registry

Represents the stable things that may appear in the city:

- producer or merchant;
- workshop or public visit point;
- agricultural batch;
- one-of-one artifact;
- service offering;
- event or experience;
- public anchor;
- governed asset/workflow ref.

Minimum fields:

- `subject_ref`, `subject_kind`, and lifecycle state;
- owner/creator context ref;
- tenancy/namespace;
- display-name source and locale;
- public-region ref;
- created/updated timestamps from explicit providers;
- source/fixture posture;
- visibility and consent state;
- correction, suspension, and withdrawal refs.

The registry is identity and lifecycle metadata. It does not make the subject's
claims true.

### 4.2 Merchant service profile

Implements the candidate `MerchantServiceProfileV0` from the platform
architecture:

- owner-confirmed public profile;
- service categories and ordinary/governed action classes;
- declared hours and freshness;
- public/coarse and protected/exact locations;
- availability source;
- registration/projection refs;
- cancellation, accessibility, support, and escalation data;
- enabled agent identity and attenuated delegation where applicable;
- `profile_is_authority: false`.

Start with `DRAFT`, `CONFIRMED`, `ACTIVE_READ`, `ACTIVE_SERVICE`, `SUSPENDED`,
and `REVOKED` lifecycle states. No LLM or extractor changes the state directly.

### 4.3 Source-linked producer intake

Reuse the strict `SourceRegistrationDraftV0` direction:

```text
one image + one audio clip
  -> transcript/extraction candidates
  -> source refs, confidence, missing fields, conflicts
  -> plain-language review and correction
  -> explicit producer/operator confirmation
  -> governed TrackingEvent first writes
  -> separate registration evaluation
```

For the first closed-world build, the founder may act as an assisted operator,
but the record must still distinguish producer declaration from operator entry
and model inference.

### 4.4 Projection engine

Materializes `VerifiedLocalProvenanceProjectionV0`-compatible public-safe read
records from registered state.

Required outputs:

- projection id/version and `as_of`;
- subject ref/kind;
- claim-by-claim status and named profile;
- verifier disposition;
- public-safe evidence refs;
- separate availability/commercial freshness;
- public/coarse location;
- presentation-only artifacts;
- canonical proof URL;
- expiry, revocation, correction, and withdrawal state.

Projection generation is deterministic. An LLM may explain a projection in a
separate presentation response but cannot change the projection.

### 4.5 Spatial catalog

Start with a deliberately small spatial contract:

- WGS84 latitude/longitude for controlled fixture and consented subjects;
- public precision class;
- coarse region and optional H3 cell candidate;
- bounded-distance filtering;
- exact/private geometry stored separately from public projection;
- deterministic test fixtures near cell/boundary edges.

Initial query implementation uses bounded application/PostgreSQL JSONB
filtering over the five-parcel fixture. Adopt PostGIS only after a measured
correctness or query requirement needs polygon containment,
network/geometry intersection, or nontrivial spatial joins. Adopt H3 only when
coarse indexing or privacy aggregation is contract-tested and actually needed.

Neither H3 nor PostGIS output becomes physical-presence proof by itself.

### 4.6 Discovery service

Implement the existing strict read surface:

- `POST /api/v1/discovery/query`;
- `GET /api/v1/discovery/projections/{projection_id}`;
- `GET /api/v1/discovery/anchors/{public_anchor_ref}`.

The first router supports allowlisted filters, stable ordering, pagination,
redaction, and freshness. It does not contain an LLM, negotiation engine,
auction, marketplace ranking service, or autonomous action loop.

### 4.7 Availability and reservation ledger

For the closed-world pilot, SeedCore may operate a minimal conventional
service ledger so the city can demonstrate useful coordination without a live
merchant platform.

Candidate records:

- service/profile ref;
- inventory or capacity unit;
- declared availability window and source;
- hold/reservation id and idempotency key;
- status: `AVAILABLE`, `HELD`, `CONFIRMED`, `EXPIRED`, `CANCELLED`, `REJECTED`;
- expiry and release behavior;
- requester and consented contact ref;
- terms/cancellation version;
- fixture/simulated/live-provider posture.

This ledger is not a payment system or custody ledger. Ordinary reservation
state cannot create an `ExecutionToken` or a verified provenance claim.

### 4.8 Action proposal router

Classifies a requested next step before any action adapter is selected:

- `READ_PUBLIC`;
- `DRAFT_PRIVATE`;
- `ORDINARY_EXTERNAL` or bootstrap-local ordinary service;
- `GOVERNED_DIGITAL`;
- `GOVERNED_PHYSICAL`;
- `REMEDIATION`.

The router may produce a `CityActionProposalV0` containing subject/projection
refs, proposed class, adapter, user-visible summary, required identity, terms,
and expected next boundary.

`CityActionProposalV0` is non-authoritative. Governed classes must be converted
into the existing strict Agent Action Gateway payload under an accountable
principal and delegation.

### 4.9 Simulated provider adapters

Build deterministic provider simulators behind the same adapter interfaces
future integrations will implement:

- `SimulatedBookingAdapter`;
- `SimulatedCommerceAdapter` using non-monetary/test references only;
- `SimulatedLogisticsAdapter` with route/assignment/callback fixtures;
- `SimulatedCertificateIssuer` with clearly non-production keys/issuer;
- `SimulatedMapRouteAdapter` with deterministic route estimates.

Each simulator must:

- identify itself as simulated in every response and artifact;
- use deterministic clocks/ids where replay requires them;
- support success, timeout, stale, rejection, cancellation, duplicate,
  tamper, and mismatched-correlation fixtures;
- never mint SeedCore execution authority;
- never be enabled under a production/live profile accidentally.

All fixture/provider refs use `fixture:district-01:*` or typed `sim:*` prefixes.
Simulators are admitted only under
`SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim`, with matching database
namespace, adapter roster, issuer/key registry, and public banner. Startup,
the typed PDP context builder, and the verifier each enforce this independently.
A valid simulated closure is `SIMULATION_ONLY`; fixture or simulated audit rows
must never enter shared staging or production audit/reporting.

### 4.10 Public proof and operator surfaces

The first human surfaces are:

1. server-rendered `/verify/{public_anchor_ref}`;
2. a minimal discovery list/detail page;
3. producer/operator draft confirmation;
4. city bootstrap status and fixture provenance;
5. existing verification/replay console links for governed actions.

A map is a later view over the same projection contract. The proof page comes
first so the city remains usable without JavaScript, WebGL, an agent, or a
native client.

## 5. Candidate Repository Shape

The current code footprint reuses existing domain models and avoids a second
trust runtime:

```text
src/seedcore/models/city_foundation.py
src/seedcore/fixtures/city_reference_district_v0.json
src/seedcore/services/city_foundation_service.py
src/seedcore/api/routers/discovery_router.py
src/seedcore/plugin/mcp_server.py                 # add thin read wrappers later
src/seedcore/api/routers/agent_actions_router.py  # reuse; do not fork
```

Future domain-module decomposition remains documented in the foundation
contract. It is not a directory-creation checklist.

Do not duplicate:

- identity/delegation models;
- `ActionIntent`;
- PDP evaluation;
- `ExecutionToken` lifecycle;
- evidence bundles;
- replay materialization;
- `RESULT_VERIFIER`;
- quarantine state;
- proof-kernel behavior.

The exact package names require codebase review before implementation. The
ownership boundary is the contract; this tree is a starting proposal.

## 6. Data And Migration Contract

### 6.1 Candidate tables

Foundation storage uses the dedicated `seedcore_city_foundation` PostgreSQL
schema. Its first migration creates only `city_features`,
`city_feature_geometries`, and `city_feature_relationships`. The service tables
below are later extractions, created only when the matching service slice lands.

| Table | Purpose | Authority posture |
| --- | --- | --- |
| `city_subjects` | stable subject identity/lifecycle | identity metadata, not claim truth |
| `merchant_service_profiles` | confirmed services and agent exposure | owner-confirmed profile, not execution authority |
| `city_locations` | public/protected spatial records | observation/declaration state explicit |
| `city_projection_versions` | immutable projection versions | read model derived from canonical state |
| `city_availability_events` | append-only availability changes | service state, not provenance or custody |
| `city_reservations` | ordinary holds/confirmations | conventional application state |
| `city_action_proposals` | proposed next actions and classification | non-authoritative |
| `city_provider_events` | simulated/live adapter callbacks | partner/simulator evidence or state only |
| `city_read_traces` | query/tool/projection observability | not authority or custody evidence |
| `city_presentation_artifacts` | derived story/media manifests | presentation only |

The minimal foundation tables and deferred extractions are specified in
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md).
Service-layer subjects reference those stable feature ids; they do not copy
geometry or network truth into merchant profiles.

Existing `tasks` records use `domain="city_foundation"`; existing
`source_registrations`/`tracking_events` remain provenance truth; and existing
`governed_execution_audit` remains policy/token/attempt/evidence truth. The city
schema does not duplicate any of them and is not scanned into the PDP/PKG hot
path or decision cache.

Prefer append-only events plus current projections where lifecycle history
matters. Every mutable current row should retain version, update reason,
principal/source, and causal/event refs.

### 6.2 Separate sensitive fields

- exact coordinates, personal contact, raw media, private documents, device
  data, and authority-tier telemetry do not enter public projection tables;
- public narrative text remains separate from structured claim fields;
- test/simulated issuer keys never share a trust registry with production
  issuers;
- payment credentials are never stored;
- fixture and live data cannot share an unlabeled namespace.

### 6.3 Migrations and reset

The bootstrap must support:

- forward database migrations;
- deterministic fixture seeding;
- fixture namespace teardown without broad database deletion;
- projection rebuild from source events;
- export of one subject/profile/proof chain for review;
- backup and restore of the local pilot;
- schema-version checks on startup.

Destructive fixture reset must target an explicit validated fixture namespace,
never the whole development or production database.

## 7. Agent-Native Interface

### 7.1 Strict MCP tools

Start with the three existing read tools:

- `seedcore.discovery.search`;
- `seedcore.discovery.get_projection`;
- `seedcore.discovery.explain_claim_state`.

Then add only after the underlying REST behavior exists:

- a private draft helper for producer intake;
- an ordinary reservation proposal/confirmation workflow;
- the existing explicit-authority action preflight/evaluate tools for governed
  actions.

Read, draft, ordinary service, and governed action tools need separate scopes
and visible host presentation. One local operator owning all credentials during
development does not justify one omnipotent credential contract.

### 7.2 First consumer-agent journey

```text
user asks for a local experience/product
  -> agent converts preference to structured filters
  -> read-only discovery query
  -> agent explains relevance, claim state, availability, and source separately
  -> user selects a result
  -> agent presents exact next action and class
  -> ordinary reservation uses the bootstrap ledger
     OR governed action enters the Agent Action Gateway
  -> result and proof/source links returned
```

### 7.3 First merchant-agent journey

```text
operator/producer creates and confirms service profile
  -> owner enables ACTIVE_READ
  -> discovery exposes current public projection
  -> owner explicitly enables one service action
  -> assistant handles read/request preparation within delegation
  -> reservation or governed action follows its separate boundary
  -> owner can suspend or revoke service/agent access
```

## 8. Closed-World Reference City

The first dataset should be intentionally small and reviewable.

Recommended envelope:

- one fictional district/block;
- five parcel-like land units grouped into three sites;
- three buildings: a workshop, small public facility, and control building;
- two road/path segments, one access point, and one water line with a simulated
  isolation point;
- one deterministic pressure/valve observation stream, one service incident,
  one workshop-maintenance project, and one isolation work package;
- 3-8 service/asset subjects, not dozens or thousands;
- three subject shapes represented by fixtures:
  - one agricultural micro-lot;
  - one one-of-one artisan object;
  - one workshop custody case;
- one visitor-facing discovery journey;
- one ordinary reservation flow;
- one governed physical/RCT flow;
- one simulated governed infrastructure flow, such as bounded valve isolation
  or controlled facility access;
- current, stale, partial, rejected, review, quarantined, and presentation-only
  projections;
- coarse and protected location examples;
- one simulated payment reference and one simulated logistics route, clearly
  labelled;
- one malicious-content fixture for prompt-injection isolation.

Use fictional or explicitly consented data until real producer enrollment,
privacy notices, correction, withdrawal, and support operations are ready.

## 9. Delivery Slices

Each slice must leave a demonstrable artifact and deterministic gate.

The foundation track `F0` through `F6` in
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)
precedes the map and governed-infrastructure demonstration. Foundation `F0-F2`
must at least be complete before service profiles are treated as located in a
real city model. The service slices below may reuse the same migrations and
fixture manifest, but they may not create parallel place or facility ids.

### Slice 0: Contract and namespace freeze

Deliver:

- bootstrap environment/source labels;
- city subject and service profile schemas;
- action-class taxonomy;
- fixture/live namespace separation;
- `bootstrap_sim` startup/context/verifier rejection rules;
- architecture tests proving no city module mints authority.

Done when:

- schema review passes;
- migrations apply and roll forward on a clean local database;
- fixture records cannot appear as live records;
- existing RCT verification gates remain green.

### Slice 1: Projection and proof kernel

Deliver:

- deterministic city fixture seeding;
- public-safe projection materializer;
- three read-only discovery endpoints;
- server-rendered proof page;
- stale/adverse-state fixtures.

Done when:

- API and proof page agree on projection version/state;
- public output contains no protected fields;
- projection rebuild is deterministic;
- discovery credentials cannot write.

### Slice 2: Producer intake and service lifecycle

Deliver:

- one-image-plus-one-audio draft;
- source-linked extraction fixture;
- correction and explicit confirmation;
- service profile lifecycle;
- suspend/revoke behavior.

Done when:

- extraction cannot auto-confirm or publish;
- inference and declaration remain distinct;
- withdrawal updates the projection without erasing history;
- operator can explain every public field's source.

### Slice 3: Agent read surface

Deliver:

- three MCP discovery wrappers;
- REST/MCP parity tests;
- prompt-injection fixtures;
- read trace and source URLs;
- one consumer-agent demonstration.

Done when:

- cached/stale results stay labelled;
- untrusted content cannot select tools or widen scope;
- the agent preserves claim and presentation state;
- no action tool is reachable from read credentials.

### Slice 4: Ordinary service coordination

Deliver:

- availability event ledger;
- one expiring reservation/hold flow;
- idempotency, cancellation, timeout, and duplicate handling;
- simulated route/booking provider callbacks;
- operator status view.

Done when:

- stale availability fails to current/unknown rather than false confirmation;
- ordinary reservation never creates policy allow or an `ExecutionToken`;
- provider callback mismatch is visible and replayable as application history;
- support/cancellation state is explicit.

### Slice 5: Governed city action

Deliver:

- one city proposal mapped into the existing Agent Action Gateway;
- accountable principal/delegation;
- policy allow/deny/escalate/quarantine paths;
- scoped token validation by the target execution adapter;
- evidence, receipt, replay, and verifier linkage;
- public-safe outcome projection.

Done when:

- missing/expired/replayed/wrong-scope token attempts fail closed;
- simulated payment/logistics success cannot bypass policy;
- evidence mismatch quarantines the workflow;
- operator can traverse proposal -> intent -> decision -> token/deny -> attempt
  -> evidence -> verifier.

### Slice 6: Simple 2D city surface

Deliver only after the read contract is stable:

- a minimal MapLibre or equivalent client;
- foundation layers for land, buildings, roads, public facilities, public-safe
  operational state, and permitted coarse infrastructure views;
- public/coarse markers from the projection API;
- list/map parity;
- accessible non-map alternative;
- no precise protected-location leakage.

Done when:

- map state never changes claim/verifier semantics;
- disabling JavaScript or the map still leaves proof usable;
- location precision and source are visible;
- adverse states cannot be hidden by styling.

### Slice 7: Replace simulators one at a time

Candidate order:

1. real map/route provider;
2. one real merchant availability/booking adapter;
3. one payment sandbox or ACP/AP2 bridge;
4. one logistics provider;
5. one external issuer/certifier;
6. one regional or municipal data feed.

Each adapter must pass the simulator's conformance and negative fixtures before
activation. Replace one boundary at a time so failures remain attributable.

## 10. Solo Operations

### 10.1 Development environments

| Environment | Data | External effects | Authority posture |
| --- | --- | --- | --- |
| `bootstrap_sim` | deterministic fictional records with prefix-scoped fixture/sim ids | none | `SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim`; `SIMULATION_ONLY` closure |
| `local-pilot` | consented pilot records | ordinary local service effects only if explicitly enabled | governed actions remain fail-closed |
| `partner-sandbox` | named provider test data | provider sandbox | no production custody or payment claims |
| `production` | reviewed live records | named live adapters | requires separate promotion and operations review |

No environment should be inferred from hostname alone. Startup configuration,
database namespace, credentials, issuer registry, adapter roster, and public
banners must agree. Simulation tests for staging run as an isolated
`bootstrap_sim` workload; simulated audit rows and trust roots do not enter the
shared staging environment.

### 10.2 Observability

Minimum signals:

- request/correlation id across REST, MCP, city modules, gateway, and verifier;
- projection version/freshness and rebuild failures;
- availability/reservation expiry and duplicate rate;
- action classification and handoff outcome;
- attempted boundary violations;
- read/write scope denials;
- simulated/live adapter label;
- evidence/verifier backlog and quarantine count;
- local backup age and migration version.

Observability helps operate the city. It does not become authority.

### 10.3 Runbooks

Before real pilot data:

- start/stop and health check;
- seed and inspect the fixture city;
- rebuild projections;
- correct/withdraw a producer record;
- suspend/revoke a service agent;
- expire/cancel a reservation;
- investigate adapter mismatch;
- inspect a governed replay;
- handle quarantine without automatic clearance;
- back up and restore;
- rotate local/sandbox credentials;
- remove consented public media/location while preserving required audit history.

## 11. Verification Program

### 11.1 Focused city checks

Candidate test groups:

- city schema and migration tests;
- `seedcore_city_foundation` schema/role/backup isolation tests;
- prefix and `bootstrap_sim` startup/context/verifier rejection tests;
- subject/service lifecycle tests;
- projection redaction and determinism tests;
- discovery filter/order/pagination tests;
- spatial boundary and precision tests;
- reservation idempotency/expiry tests;
- simulator conformance tests;
- REST/MCP parity tests;
- prompt-injection and unsafe-link tests;
- city proposal -> gateway contract tests;
- governed negative/replay fixtures;
- proof-page escaping, accessibility, and adverse-state tests.

### 11.2 Existing trust gates remain required

When city work touches authority, policy, token, evidence, custody, replay, or
verification:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

Run narrower city checks first, then the relevant trust-runtime gates. A green
city UI is not sufficient if the authority path regresses.

### 11.3 Circuit-breaker rule

When the same deterministic city or trust gate fails repeatedly, stop
autonomous iteration and surface the fixture, verifier, diff, and runbook
evidence. Do not relax the test, policy, redaction, token, or evidence boundary
to keep the demo moving.

## 12. Bootstrap Success Criteria

The sovereign bootstrap is complete when one operator can:

1. start the city locally from documented commands;
2. seed a deterministic closed-world dataset;
3. traverse district -> land/site -> building/facility -> entrance/space and
   road/utility topology at a pinned version;
4. distinguish design, declared, observed, operational, verified, and
   public-safe twin state;
5. operate one construction/maintenance work package and settle one simulated
   governed infrastructure action through the existing trust spine;
6. create, correct, confirm, publish, suspend, and withdraw a producer/service
   record;
7. search and inspect public-safe projections through REST, MCP, and a human
   proof page;
8. see relevance, location, availability, claim state, commercial state,
   authority state, and verifier state separately;
9. create and cancel one ordinary reservation without invoking the PDP;
10. propose one governed physical commerce/custody action that enters the
    existing strict SeedCore path;
11. demonstrate allow, deny, stale, replay, wrong scope, evidence mismatch, and
   quarantine outcomes;
12. rebuild projections and replay the governed chains deterministically;
13. prove that fixture, simulated-provider, presentation, and live/verified
    state cannot be confused;
14. back up, restore, and operate the system using written runbooks;
15. replace one simulator with a real adapter without changing the canonical
    city, authority, or replay contracts.

The exact first three code changes are C1 lightweight foundation contract, C2
read-only discovery/MCP parity, and C3 two governed-transition proofs, as
defined in
[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md).

## 13. Explicit Non-Goals For The Bootstrap

- no microservice program;
- no city-scale data volume;
- no legal cadastre, permit office, certified survey, engineering authority,
  utility control center, or emergency dispatch function;
- no global map or tile infrastructure;
- no custom payment rail, stored payment credential, or real escrow;
- no licensed transport operation;
- no official municipal-data claim;
- no automatic external certification;
- no generic marketplace commission engine;
- no recommendation marketplace or multi-agent bidding;
- no real-time autonomous price negotiation;
- no 3D/XR requirement for core use;
- no public exact-location exposure by default;
- no multiple cities or production verticals in parallel;
- no second PDP, token service, custody ledger, verifier, or proof truth;
- no model-driven production promotion, quarantine clearance, or secret access.

## 14. Relationship To The Platform Architecture

[`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md)
defines the long-range ecosystem planes, protocol posture, risks, and promotion
gates.

[`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)
defines what the sovereign city actually contains below commerce: spatial
identity, land, built assets, networks, facilities, environment, construction,
operations, and twin settlement.

This document changes the starting topology, not the final boundaries:

```text
Beginning:
  one SeedCore operator owns a closed-world modular city kernel
  + deterministic provider simulators
  + the existing trust runtime

Later:
  external systems replace simulators through versioned adapters
  while SeedCore remains the trust slice for governed physical action
```

The live execution order is tracked in
[`current_next_steps.md`](current_next_steps.md). Detailed producer/discovery
contracts remain in
[`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md).

## 15. Final Build Rule

```text
Own the first implementation end to end.
Model the city foundation before treating businesses as the city.
Keep every internal module replaceable.
Simulate dependencies before negotiating integrations.
Do not simulate away authority boundaries.

The founder may operate the whole bootstrap city.
The discovery service still cannot authorize.
The payment simulator still cannot release custody.
The agent still cannot approve itself.
The PDP still cannot claim execution happened.
Only evidence and verification can close the governed transition.
```
