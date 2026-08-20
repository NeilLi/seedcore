# Sovereign City Foundations And Infrastructure

Date: 2026-08-20
Status: C1a fixture, C1b persistence, isolated PostgreSQL schema-restore/reseed round-trip, and read-only REST discovery verified; MCP and governed action pending
Owner posture: SeedCore constructs the first digital representation and operating substrate directly

## 1. Decision

The SeedCore digital city starts with the city itself, not with a marketplace.
Commerce, producer discovery, tourism, agents, and immersive experiences are
applications over a more fundamental digital fabric:

```text
spatial reference and addresses
  -> land, sites, parcels, and administrative areas
  -> buildings, structures, spaces, roads, and paths
  -> water, drainage, energy, telecom, waste, and transport networks
  -> public facilities, environment, hazards, and service areas
  -> construction, commissioning, maintenance, incidents, and retirement
  -> businesses, services, discovery, trade, and agent experiences
```

SeedCore should construct a deliberately tiny, sovereign implementation of this
fabric for one closed-world block-scale district. It should be operable by one
founder, use fictional or explicitly permitted data, and connect consequential
infrastructure actions to the existing SeedCore trust runtime.

The initial objective is not to reproduce a municipal GIS, cadastral authority,
building-permit office, utility control center, BIM suite, or full smart-city
platform. It is to establish the smallest correct city-domain kernel on which
those systems can later federate.

The first code slice is intentionally limited to a lightweight Pydantic/JSONB
feature envelope, three foundation tables, and deterministic fixture queries.
It does **not** include a GIS engine, CityGML service, OGC-conformant endpoint,
BIM/IFC parser, generic utility simulator, or full construction platform.

## 2. Product Boundary

### 2.1 What SeedCore constructs

The bootstrap owns:

- a stable city-feature identity and relationship model;
- versioned geometry, names, addresses, and administrative containment;
- land-unit, site, building, structure, space, network, facility, environment,
  project, work-package, observation, and incident records;
- explicit source, confidence, temporal-validity, visibility, and authority
  posture for every material field;
- deterministic current-state projections over append-only change history;
- a 2D layer/query surface and agent-readable REST/MCP read contracts;
- construction and maintenance workflows for a controlled reference district;
- deterministic utility, sensor, inspection, and contractor simulators;
- governed routing for named high-consequence attempts;
- replay, evidence, verifier, quarantine, correction, and retirement linkage;
- import/export seams for later OGC, BIM/IFC, utility, sensor, and municipal
  adapters.

### 2.2 What SeedCore does not claim

Running this infrastructure does not make SeedCore:

- a cadastral or land-title authority;
- a planning, zoning, permitting, building-code, or inspection authority;
- an architect or engineer of record;
- a utility, grid operator, water authority, transport authority, or emergency
  service;
- a legal address issuer;
- a source of certified survey accuracy;
- a safety case for construction or physical operation;
- a substitute for competent operators, licensed contractors, or statutory
  approvals;
- the controller of real infrastructure merely because it holds a digital
  representation.

Official or regulated facts remain external claims until supplied by a named
issuer and admitted under an explicit policy. A simulated valve, road closure,
inspection, permit, meter, or commissioning receipt is always rendered as
simulated.

## 3. Foundational Invariants

### 3.1 Representation is not authority

A feature may exist in the city twin without being legally authoritative,
physically verified, operationally current, or safe to act upon.

```text
record exists
  != geometry is survey-grade
  != ownership is established
  != asset is present
  != asset is operational
  != action is permitted
  != action succeeded
```

### 3.2 Keep five state axes separate

Every material asset or network feature needs independently legible state:

| Axis | Examples | Source |
| --- | --- | --- |
| Lifecycle | planned, under construction, operational, retired | project/asset events |
| Administrative | draft, submitted, externally approved, rejected, expired | named issuer or fixture |
| Physical | observed, not observed, damaged, isolated, demolished | inspection/telemetry/evidence |
| Operational | available, degraded, outage, maintenance, closed | responsible operator or simulator |
| Trust | declared, registered, externally attested, verified, disputed, quarantined | SeedCore projection/verifier |

No single `status` field may collapse these axes.

### 3.3 Separate official, declared, observed, inferred, and simulated facts

Use a field-level source posture:

- `OFFICIAL_EXTERNAL`: supplied by a named competent authority;
- `OWNER_DECLARED`: supplied by an accountable owner/operator;
- `PROFESSIONAL_ATTESTED`: signed by a named licensed or designated professional;
- `DEVICE_OBSERVED`: emitted by an enrolled device under a stated capture profile;
- `HUMAN_OBSERVED`: recorded by an accountable inspector/operator;
- `MODEL_INFERRED`: machine-generated candidate, never authority by itself;
- `SEEDCORE_DERIVED`: deterministic projection or calculation over pinned inputs;
- `FIXTURE`: closed-world deterministic data;
- `SIMULATED_PROVIDER`: deterministic external-system behavior;
- `PRESENTATION_ONLY`: styling, narrative, illustration, mesh, or generated media.

`SIMULATION_ONLY` is a result/verifier disposition rather than an input-source
posture. It means the chain closed correctly for the isolated bootstrap profile
and has no live institutional or physical effect.

Source posture belongs to claims and observations, not only to the containing
record. A building outline may be fixture data while its public name is
owner-declared and its current access state is device-observed.

### 3.4 Time is first-class

City data changes slowly and quickly at the same time. Every versioned fact
should distinguish:

- `valid_from` / `valid_to`: when the fact applies in the represented world;
- `observed_at`: when a person or device observed it;
- `recorded_at`: when SeedCore received it;
- `effective_at`: when a governed transition took effect;
- `superseded_at`: when a newer version replaced the current projection;
- freshness and expiry profile;
- causal parent and compensation refs.

Late data must not silently rewrite history. Corrections append compensating
events and rebuild the current projection.

### 3.5 Geometry is versioned evidence-bearing data

Geometry requires:

- stable feature ref independent of geometry version;
- geometry kind and coordinate reference system;
- accuracy/precision class and capture method;
- source and responsible principal;
- valid and recorded times;
- public/protected/authority-tier visibility;
- parent geometry and derivation refs;
- digest for imported or generated artifacts;
- correction/supersession history.

An H3 cell, bounding box, address string, indoor room label, BIM mesh, or 3D
tile is a representation or index. None proves exact presence or legal boundary.

## 4. City Foundation Domain

### Canonical Phase 1 fixture: 5-3-2-1-1

The canonical Phase 1 verification profile is frozen in
`src/seedcore/fixtures/city_reference_district_v0.json`. Local refs remain
human-readable; runtime `feature_ref` values add the
`fixture:district-01:` namespace.

| Element | Frozen local refs | Verification role |
| --- | --- | --- |
| Five parcels | `parcel:01:workshop`, `parcel:02:visitor`, `parcel:03:farm`, `parcel:04:depot`, `parcel:05:private` | workshop land, public visit point, agricultural origin, controlled depot zone, and adjacent wrong-zone negative fixture |
| Three buildings | `building:01:north_workshop`, `building:02:visitor_center`, `building:03:storage_depot` | custody intake/return, public QR anchor, and protected controlled-entry target |
| Two roads/paths | `road:01:main_st`, `road:02:depot_access` | available workshop-to-visitor route and closed/under-maintenance incident route |
| One water line | `water_segment:01:main_feed` | protected simulated utility segment with `sim:utility:water:valve:01` isolation point |
| One workshop | `subject:artisan:som_wood` | declared local-producer/service anchor for discovery and the later governed custody proof |

The implemented fixture contains exactly 12 feature records and typed
relationships. Parcel 5, the storage depot, and the water line are excluded
from public discovery by visibility policy. The fixture is immutable source
data under `bootstrap_sim`; it is not land, utility, or municipal truth.

### 4.1 Common `CityFeatureV0`

All foundation objects share a small identity envelope:

```json
{
  "contract_version": "seedcore.city_feature.v0",
  "feature_ref": "fixture:district-01:building:01:north_workshop",
  "local_ref": "building:01:north_workshop",
  "feature_kind": "building",
  "name": "Som Artisan Workshop",
  "lifecycle_state": "OPERATIONAL",
  "administrative_state": "FIXTURE_ONLY",
  "physical_state": "OBSERVED_PRESENT",
  "operational_state": "AVAILABLE",
  "trust_state": "FIXTURE",
  "source_posture": "FIXTURE",
  "visibility": "PUBLIC_COARSE",
  "geometry": {
    "geometry_type": "Point",
    "coordinates": [0.0, 0.0001],
    "crs": "EPSG:4326",
    "precision_class": "public_coarse",
    "source_posture": "FIXTURE",
    "visibility": "PUBLIC_COARSE"
  },
  "public_anchor_ref": "fixture:district-01:anchor:workshop",
  "properties": {
    "facility_role": "workshop",
    "accepts_governed_custody": true
  }
}
```

The common envelope enables uniform discovery, relationships, history, and
redaction. Domain-specific profiles hold substantive attributes.

### 4.2 Spatial reference, regions, names, and addresses

Represent:

- country/region/locality/district/neighborhood hierarchy;
- named places and culturally appropriate aliases;
- street, path, waterway, landmark, entrance, delivery point, and access point;
- structured address components where locally applicable;
- non-street addressing and landmark directions;
- public/coarse versus protected/exact location;
- coordinate reference and vertical datum metadata;
- local-language names, transliteration, and pronunciation where consented.

Do not assume every place has a Western street address. An address is a
locating convention linked to features and access points, not the feature's
identity.

### 4.3 Land, sites, parcels, and rights references

Represent:

- land units and parcel-like boundaries;
- sites composed of one or more land units;
- zoning/planning-area references;
- easement, right-of-way, access, tenure, and restriction references;
- surface, subsurface, and air-space relationships where required;
- disputed, approximate, proposed, and official-boundary postures.

The bootstrap may create fixture land units. Live title, ownership, zoning, or
easement claims require authoritative external refs and must never be inferred
from occupancy, GPS, imagery, or operator entry.

### 4.4 Built environment

Represent:

- sites, buildings, bridges, walls, towers, shelters, and civil structures;
- building parts, levels, rooms/spaces, entrances, and circulation paths;
- functional use and occupancy class as sourced claims;
- structural/system components only to the detail needed by a named use case;
- accessibility features and temporary restrictions;
- connections to parcels, addresses, utilities, facilities, and projects;
- design/BIM artifact refs separately from observed as-built state.

A BIM/IFC model is a rich design or asset artifact. It does not automatically
become the operational twin. SeedCore binds its digest, author, version,
declared purpose, source posture, and mapping to stable city feature refs.

### 4.5 Mobility and public-realm networks

Represent node/edge topology for:

- streets and roads;
- pedestrian paths, stairs, ramps, and crossings;
- bicycle routes;
- public-transit stops and route references;
- freight/loading and delivery access;
- parking and pickup/drop-off areas;
- bridges, tunnels, barriers, and gates;
- closures, directionality, restrictions, surface state, and accessibility.

Routing is a derived service over versioned topology and restrictions. A route
proposal is not permission to enter, close, cross, or control a feature.

### 4.6 Utility and service networks

Use an explicit network model:

```text
network
  -> subnetwork / pressure zone / circuit / service area
  -> node (junction, source, sink, transformer, valve, meter, cabinet)
  -> edge (pipe, cable, duct, channel, conductor)
  -> accessory / support / containment feature
  -> connection to served site, building, facility, or asset
```

Initial network kinds:

- potable and non-potable water;
- wastewater and stormwater/drainage;
- electricity;
- telecom/data;
- solid-waste collection/service areas;
- optional thermal/gas networks only when a safe named fixture requires them.

Store topology, commodity/service kind, directionality, capacity class,
operational posture, responsible-operator ref, criticality, protected geometry,
and dependency refs. Sensitive utility geometry should default to protected.

The OGC MUDDI conceptual model is an interoperability reference for subsurface
features; the bootstrap does not claim MUDDI conformance until a tested mapping
and conformance profile exist.

### 4.7 Public facilities and services

Represent facilities independently from organizations and services:

- clinic, school, market, workshop, shelter, community center, depot, park,
  water point, sanitation point, emergency assembly point;
- entrances and accessibility;
- responsible operator and service-area refs;
- declared hours, capacity, availability, and outage state;
- emergency role and critical dependencies;
- public contact separately from protected operational contacts.

One facility may host many services; one service may operate across many
facilities. Merchant discovery uses these refs but does not own them.

### 4.8 Environment, hazards, and observations

Represent:

- terrain, water bodies, vegetation/green areas, and drainage catchments;
- flood, fire, heat, air-quality, landslide, contamination, and other named
  hazard zones;
- sensors, datastreams, observed properties, features of interest, and
  observations;
- forecast, scenario, model output, and observed measurement as different
  source classes;
- measurement units, procedure, calibration, uncertainty, and freshness;
- privacy/security tier for environmental and infrastructure telemetry.

SensorThings is a later adapter target for heterogeneous observations. Raw
measurements and archives remain digest-bound; public views expose only the
necessary, redacted projection.

### 4.9 Construction, maintenance, and capital projects

Represent a project as coordination state, not as blanket authority:

- project identity, sponsor, accountable owner, and delivery parties;
- affected land, assets, networks, facilities, and service areas;
- stated objective, scope, phases, milestones, and dependencies;
- drawings, BIM/IFC, specifications, method statements, schedules, and change
  packages as versioned artifact refs;
- permit, review, approval, inspection, and professional-attestation refs;
- work packages and consequential action classifications;
- health/safety and environmental controls as external or reviewed artifacts;
- expected versus observed progress;
- commissioning, handover, defects, warranty, maintenance, and retirement;
- disputes, suspensions, incidents, compensation, and quarantine.

Project scheduling and document acceptance do not authorize a physical act.
Named actions cross the trust boundary described in Section 7.

### 4.10 Incidents, outages, restrictions, and work orders

Represent operational exceptions explicitly:

- incident/outage ref and severity;
- affected features and dependencies;
- detected/declared/confirmed source posture;
- start, expected restoration, observed restoration, and closure times;
- public-safe impact projection;
- operator work orders and assignment;
- temporary closure/isolation/bypass refs;
- evidence, inspection, remediation, and compensation refs;
- unresolved, disputed, and quarantined state.

An incident classifier may propose severity or affected assets. It cannot
declare an emergency, isolate a live utility, clear an outage, or close an
incident without the applicable human/policy and evidence path.

## 5. Relationship Graph And Topology

Use typed relationships rather than embedding an unbounded object graph:

| Relationship | Example |
| --- | --- |
| `LOCATED_IN` | building in site; site in district |
| `HAS_ADDRESS` | entrance has delivery address |
| `PART_OF` | building part in building; circuit in grid |
| `CONNECTS_TO` | pipe edge to valve node |
| `SERVES` | feeder serves facility |
| `DEPENDS_ON` | clinic depends on feeder and water zone |
| `CROSSES` | utility segment crosses road corridor |
| `ACCESS_VIA` | building reached through path/entrance |
| `AFFECTED_BY` | facility affected by outage/project/hazard |
| `CONSTRUCTED_BY` | asset version produced by project/work package |
| `OBSERVED_BY` | feature observed by sensor/inspection |
| `SUPERSEDES` | geometry/state/artifact version replaces prior version |
| `COMPENSATES` | correction or remediation addresses prior event |

Every relationship has its own source posture, validity interval, visibility,
and version. PostgreSQL tables are sufficient initially; a graph database is
not required. Road and utility algorithms use explicit node/edge tables and
well-tested traversal code.

## 6. Lifecycle And Twin Settlement

### 6.1 Asset lifecycle

Use a controlled lifecycle vocabulary:

```text
CONCEPT
  -> PROPOSED
  -> REVIEWED
  -> APPROVED_EXTERNAL | REJECTED_EXTERNAL | EXPIRED
  -> UNDER_CONSTRUCTION
  -> READY_FOR_COMMISSIONING
  -> COMMISSIONED
  -> OPERATIONAL
  -> DEGRADED | RESTRICTED | OUTAGE | UNDER_MAINTENANCE
  -> OPERATIONAL
  -> DECOMMISSIONING
  -> DECOMMISSIONED | DEMOLISHED
  -> ARCHIVED
```

Not every feature traverses every state. Administrative approval, physical
state, operational state, and SeedCore trust state remain separate even when a
project view shows a combined journey.

### 6.2 Design, as-built, observed, and authoritative projections

Maintain distinct projections:

- `DESIGN`: what a pinned design package proposes;
- `SCHEDULED`: what a current project/work plan says should happen;
- `AS_DECLARED_BUILT`: what a contractor/operator reports was built;
- `AS_OBSERVED`: what accepted inspections or enrolled devices observed;
- `OPERATIONAL_CURRENT`: the operator's current service state;
- `VERIFIED_CURRENT_PROFILE`: what the named SeedCore verifier profile accepts;
- `PUBLIC_SAFE`: a redacted view derived from the above.

Differences are first-class. A design/as-observed geometry delta, missing
inspection, unexpected utility crossing, or stale operational state must be
visible and may trigger review or quarantine.

### 6.3 Settlement protocol

For consequential infrastructure transitions:

```text
project/work package proposes change
  -> accountable principal and delegation resolved
  -> external prerequisites referenced and freshness checked
  -> typed ActionIntent and target asset/network scope
  -> PDP allow / deny / escalate / quarantine
  -> short-lived ExecutionToken
  -> exact operator/actuator validates token and local interlocks
  -> physical attempt
  -> signed receipt, telemetry, inspection, and artifact evidence
  -> settlement proof vector
  -> RESULT_VERIFIER disposition
  -> append-only twin event and current projection update
```

The PDP admits a scoped attempt; it does not certify engineering correctness or
claim completion. The actuator may still refuse on local safety grounds. Only
evidence and verification close the represented transition.

### 6.4 Proof vector examples

| Transition | Required evidence candidates |
| --- | --- |
| Road closure starts | authority/prerequisite ref, token, exact segment and interval, operator/device receipt, public notice projection |
| Utility isolation | responsible operator, fresh topology/context, token, local interlock receipt, pre/post state telemetry |
| Excavation begins | work package, utility-conflict review ref, site/zone scope, operator receipt, capture manifest |
| Component installed | material/source ref, location/capture evidence, installer/inspection refs, design delta |
| Asset commissioned | approved test profile, results, professional/operator signoff, token where actuation is consequential, verifier closure |
| Facility reopens | resolved defects, access/safety checks, operator decision, current observation, public status update |
| Asset retired/demolished | target binding, approvals, isolation evidence, attempt receipt, waste/custody refs where applicable, final observation |

The exact proof vector is policy-profile specific. Missing proof leaves the
twin provisional, under review, or quarantined rather than falsely complete.

## 7. Action Classification For City Infrastructure

| Class | Examples | SeedCore posture |
| --- | --- | --- |
| `READ_PUBLIC` | view building, route, facility, public outage | redacted read only |
| `READ_PROTECTED` | inspect exact utility geometry or operator contacts | authenticated, purpose-bound read with audit |
| `DRAFT_PRIVATE` | draft design, work package, inspection note | no physical or official effect |
| `ORDINARY_WORKFLOW` | assign review, request information, schedule non-consequential visit | application state and accountable logs |
| `EXTERNAL_AUTHORITY_HANDOFF` | submit permit, request utility locate, request statutory inspection | external system remains authority |
| `GOVERNED_DIGITAL` | publish controlled operational state, promote as-built version, change protected topology | PDP/token/evidence as profile requires |
| `GOVERNED_PHYSICAL` | isolate utility, control gate, close road, energize, release controlled asset, operate actuator | full endpoint-enforced path and local safety interlocks |
| `REMEDIATION` | compensate incorrect twin state, revoke compromised device, clear quarantine | human-reviewed or independently policy-admitted |

The first live-capable implementation should allow only a tiny allowlist of
governed actions. Everything else stays read, draft, simulated, or external
handoff.

## 8. Bootstrap Storage And Module Shape

### 8.1 First code shape and future decomposition map

Do not create the full directory tree below in the first pull request. Start
with the smallest code-facing seam:

```text
src/seedcore/models/city_foundation.py
  # CityFeatureV0, GeometryEnvelopeV0, five state-axis enums

src/seedcore/fixtures/city_reference_district_v0.json
  # deterministic, prefix-scoped, minimal block fixture

src/seedcore/services/city_foundation_service.py
  # strict current/history reads and deterministic projection composition
```

Only split into the domain modules below after a concrete second feature makes
the shared file harder to understand or test.

Candidate modules under `src/seedcore/city/`:

```text
foundation/
  features.py              # common feature identity and lifecycle
  geometry.py              # versioned geometry and visibility
  places.py                # regions, names, addresses, access points
  land.py                  # land units, sites, rights references
  built_assets.py          # buildings, structures, spaces
  networks.py              # generic node/edge topology
  mobility.py              # roads, paths, restrictions, routing views
  utilities.py             # water/drainage/energy/telecom/waste profiles
  facilities.py            # public facilities and service areas
  environment.py           # hazards and environmental features
  observations.py          # sensor/inspection observations
  projects.py              # projects, work packages, artifacts, milestones
  operations.py            # incidents, outages, work orders
  relationships.py         # typed, temporal feature relationships
  twin_projection.py       # deterministic current/public-safe views
  repositories.py          # explicit storage boundaries
  adapters/                # OGC/BIM/sensor/provider seams
  fixtures/district_01.py  # deterministic reference district
```

This tree is a future decomposition map, not a bootstrap creation checklist.
The exact files require code review before implementation. These modules reuse
the existing identity, gateway, PDP, token, evidence, replay, settlement,
custody, and verifier primitives; they do not fork them.

### 8.2 Storage boundary and existing SeedCore seams

Use a dedicated PostgreSQL schema named `seedcore_city_foundation`. The first
migration creates the schema explicitly and grants separate read/write roles;
ORM metadata must not assume it already exists. Schema-qualified backup,
restore, migration ordering, and test-database reset must pass before the city
models are imported at application startup.

The foundation schema is isolated from the PDP/PKG hot path:

- `tasks` remains the shared work envelope. City tasks use
  `domain="city_foundation"` and carry stable city refs in typed JSON payloads;
  no city columns are added to `tasks`;
- `source_registrations`, `tracking_events`, their artifacts/measurements, and
  `registration_decisions` remain the provenance system of record. City
  projections link by stable refs; they do not copy or reinterpret registration
  decisions;
- `governed_execution_audit` remains the append-only audit for policy decisions,
  tokens, attempts, and evidence. City `feature_ref`, `work_package_ref`, and
  network/zone refs travel inside the existing typed action/evidence payloads;
  the city schema does not create a duplicate governed audit;
- digital-twin journal, custody, replay, and verifier tables remain canonical
  for their current roles. Foundation projections reference their outcomes;
- the PDP context loader never scans foundation tables or accepts ambient city
  state. A typed context builder resolves an allowlisted, pinned projection and
  supplies only the fields required by the named policy profile;
- no foundation table participates in PKG snapshot construction or the PDP
  decision cache by default.

Cross-schema refs are application-validated stable ids in v0, not a web of
foreign keys into hot-path tables. Add a cross-schema foreign key only when its
delete, restore, replay, migration, and failure semantics are proven.

### 8.3 Phase-one tables and deferred tables

The first migration creates only:

| Schema-qualified table | Purpose |
| --- | --- |
| `seedcore_city_foundation.city_features` | stable feature identity, feature kind, five state axes, temporal/source envelope, JSONB domain profile |
| `seedcore_city_foundation.city_feature_geometries` | small versioned GeoJSON geometry envelope with CRS, precision, source, time, and visibility |
| `seedcore_city_foundation.city_feature_relationships` | typed, temporal, source-labelled relationships between stable feature refs |

Do not create a table per future concept before a query or invariant requires
it. The following are candidate extractions after the lightweight slice:

| Table | Purpose |
| --- | --- |
| `city_feature_names` | localized names and aliases with source posture |
| `city_addresses` | structured/non-street address and access-point links |
| `city_land_units` | parcel/site and land-reference profiles |
| `city_built_asset_profiles` | building/structure/space attributes |
| `city_networks` | network identity, kind, operator, service area |
| `city_network_nodes` | topology nodes and accessories |
| `city_network_edges` | topology edges, direction, capacity, state |
| `city_facility_profiles` | facility roles, accessibility, service refs |
| `city_environment_features` | terrain, water, green area, hazard profiles |
| `city_observations` | append-only measurements and inspection observations |
| `city_projects` | project scope, parties, phases, status axes |
| `city_project_artifacts` | versioned drawings/BIM/specification refs and digests |
| `city_work_packages` | bounded work scope, targets, prerequisites, action class |
| `city_asset_state_events` | append-only asset/operational transition history |
| `city_incidents` | incident/outage current envelope |
| `city_work_orders` | accountable operational assignments |
| `city_twin_projection_versions` | deterministic immutable read projections |

Use PostgreSQL JSONB and application-level validation first. Geometry v0 is a
bounded GeoJSON envelope with explicit WGS84/CRS metadata. Enable PostGIS only
after a measured query or correctness requirement needs polygon containment,
network/geometry intersection, or nontrivial spatial joins. H3 remains an
optional coarse query/aggregation/privacy index. Neither is part of the PDP or
proof truth. A graph database, time-series cluster, BIM server, OGC server,
tile server, and data lake are not bootstrap prerequisites.

### 8.4 Simulator and fixture isolation

Every fixture and simulated provider id is prefix-scoped:

```text
fixture:district-01:feature:*
fixture:district-01:geometry:*
fixture:district-01:project:*
sim:utility:*
sim:inspection:*
sim:payment:*
sim:logistics:*
```

Simulation is admitted only when
`SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim`. This profile must agree with the
database/schema namespace, adapter roster, issuer/key registry, and public UI
banner at startup. A generic development or staging label is insufficient.

Enforce the boundary three times when code lands:

1. startup fails if simulated adapters, fixture issuers, fixture keys, or
   prefixed ids are configured outside `bootstrap_sim`;
2. the typed PDP context builder rejects every `FIXTURE`,
   `SIMULATED_PROVIDER`, or `sim:*` input unless the runtime and named policy
   profile explicitly admit bootstrap simulation;
3. the verifier refuses a live/production closure if any required source,
   receipt, issuer, device, operator, or provider ref is simulated. A valid
   bootstrap result is labelled `SIMULATION_ONLY`, never production-verified.

Ephemeral simulation tests may run in an isolated `bootstrap_sim` workload, but
their audit namespace, keys, and results cannot enter shared staging or
production audit/reporting. Promotion copies code and schemas, never fixture
rows, simulated receipts, or test trust roots.

### 8.5 Data tiers

At minimum:

- `PUBLIC`: intentionally publishable, coarse where necessary;
- `OPERATOR`: operational data for accountable city operators;
- `PROTECTED_INFRASTRUCTURE`: exact utilities, critical dependencies, access
  control, safety/security detail;
- `AUTHORITY_EVIDENCE`: policy, token, signed telemetry, inspection, custody,
  and verifier artifacts;
- `RAW_RESTRICTED`: original media, survey, BIM, telemetry archive, personal or
  sensitive documentation.

Projection code only moves data toward a less sensitive tier through explicit,
tested redaction. Public clients never query raw foundation tables.

## 9. Minimum Viable Reference District

The first fixture is a fictional block small enough to review entirely in one
test file:

- one district and one named block;
- five parcel-like land units grouped into three sites;
- three buildings: one workshop, one small public facility, and one control
  building;
- two connected road/path segments and one access point;
- one water line represented by two nodes, one edge, and one simulated isolation
  point serving the workshop/public facility;
- one deterministic pressure/valve observation stream;
- one small workshop-maintenance project and one isolation work package;
- one simulated water-service incident and one compensating correction;
- the existing producer/service and rare-shoe RCT fixture journey linked to
  actual sites and access points.

Electricity, drainage, indoor navigation, multiple neighborhoods, bridges,
multi-utility dependency analysis, detailed construction artifacts, and a
larger facility catalog form an extension fixture only after the first governed
transition and read APIs pass. They are not required for Phase 1.

The dataset should contain deliberate adverse cases:

- approximate and disputed boundary;
- design/as-observed geometry mismatch;
- stale sensor reading;
- broken network edge and cascading facility impact;
- protected utility geometry requested with public scope;
- expired external approval fixture;
- wrong asset/zone token;
- repeated attempt;
- incomplete inspection;
- false completion callback;
- quarantined commissioning;
- superseded address and renamed facility.

## 10. Solo-First Delivery Slices

### Slice F0: Vocabulary, namespace, and safety freeze

Deliver:

- feature kinds and relationship vocabulary;
- five separate state axes;
- source/authority and visibility labels;
- fixture/live namespace separation;
- action-class allowlist;
- threat and privacy review for infrastructure data.

Exit gate: no foundation type can imply legal authority or bypass the trust
runtime merely by changing application state.

### Slice F1: Spatial identity and land skeleton

Deliver:

- common feature, names, geometry, relationship, region, address, land, and
  site schemas;
- the three-table `seedcore_city_foundation` migration and deterministic JSON
  fixture seed;
- GeoJSON import/export for the reference district;
- current and history query;
- public/protected redaction tests.

Exit gate: one can reconstruct the district hierarchy and geometry history
without confusing approximate, fixture, protected, or superseded data.

### Slice F2: Built assets and network topology

Deliver:

- building/structure/space profiles;
- two road/path segments and the single water-line node/edge fixture encoded in
  the lightweight feature/relationship model;
- facility and dependency relationships;
- topology validation, broken-edge fixtures, and impacted-facility query;
- no PostGIS, general GIS topology engine, or graph database requirement.

Exit gate: topology and geometry produce deterministic results, sensitive
utility coordinates do not escape, and no derived route or dependency becomes
authority.

### Slice F3: Twin history and observations

Deliver:

- append-only asset-state events;
- design, as-declared, as-observed, operational, verified, and public-safe
  projections;
- sensor and inspection observation envelope;
- deterministic sensor simulator;
- freshness, uncertainty, late-event, compensation, and rebuild tests.

Exit gate: current state rebuilds from history and late/corrected observations
cannot silently mutate sealed past state.

### Slice F4: Project and construction workflow

Deliver:

- project, artifact, milestone, work-package, prerequisite, inspection, and
  change-package contracts;
- the one workshop-maintenance project and water-isolation work package;
- expected/observed progress and design/as-observed delta;
- external-authority handoff refs clearly marked fixture/simulated.

Exit gate: project completion cannot be declared from schedule, document
upload, LLM extraction, or contractor callback alone.

### Slice F5: One governed infrastructure action

Use a simulator first, such as a bounded water-valve isolation or controlled
facility access transition. Deliver:

- work package to typed `ActionIntent` mapping;
- exact asset, network zone, time, operator, and prerequisite binding;
- PDP allow/deny/escalate/quarantine fixtures;
- endpoint token validation and local-interlock refusal;
- signed attempt/telemetry/inspection evidence;
- verifier settlement and twin projection update;
- stale, wrong-zone, replay, mismatch, partial, and compensation cases.

Exit gate: the full chain is traversable from project/work package through
verifier closure, and no simulator/provider/application success can close it.

### Slice F6: Foundation map and agent reads

Deliver:

- simple 2D layer client with accessible list/detail fallback;
- layer/time/source/visibility controls;
- strict native read collections plus a documented future OGC API Features
  mapping; no conformance or server claim;
- strict REST and read-only MCP tools for feature, relationship, incident, and
  public facility discovery;
- query and redaction audit traces.

Exit gate: REST, MCP, map, and proof surfaces agree on identifiers, versions,
source posture, freshness, and public-safe visibility.

### Slice F7: Standards adapters and live-source replacement

Replace one fixture boundary at a time:

1. reviewed public basemap/address/feature source;
2. one OGC API Features adapter;
3. one SensorThings observation adapter;
4. one IFC/BIM artifact mapping for a selected project;
5. one utility/MUDDI logical mapping;
6. one official planning/permit/inspection reference source;
7. one real device or actuator only after a separate safety and operations
   review.

Each replacement passes fixture conformance, provenance, freshness, redaction,
revocation, outage, and negative-path tests before activation.

## 11. Code-Facing Implementation Handoff

This sequence translates the architecture into three reviewable changes. It is
an implementation contract, not evidence that the code exists.

### Change C1a: In-memory foundation fixture — implemented

Implemented:

- `src/seedcore/models/city_foundation.py` containing `CityFeatureV0`,
  `GeometryEnvelopeV0`, field/source/visibility contracts, and lifecycle,
  administrative, physical, operational, and trust enums;
- `src/seedcore/fixtures/city_reference_district_v0.json` containing only the
  minimum viable district and adverse cases;
- `src/seedcore/services/city_foundation_service.py` for strict fixture loading,
  public visibility filtering, and reference lookup;
- deterministic schema, prefix, relationship, redaction, runtime-profile,
  distance, and API tests in `tests/test_city_foundation_discovery.py`.

`CityFeatureV0` should be a strict Pydantic boundary model. PostgreSQL stores
the envelope only after the persistence gate. No PostGIS, H3, OGC, IFC, BIM,
tile, graph, telemetry platform, or database dependency is introduced in C1a.

### Change C1b: Foundation persistence — implemented and locally verified

Implemented:

- `deploy/migrations/137_city_foundation.sql` creates exactly
  `city_features`, `city_feature_geometries`, and
  `city_feature_relationships` under `seedcore_city_foundation`, with fixture
  namespace/runtime checks, current-geometry uniqueness, relationship foreign
  keys, indexes, and separate read/write roles;
- `src/seedcore/services/city_foundation_repository.py` provides explicit,
  transactional replace/read behavior and strict `ReferenceDistrictV0`
  hydration;
- `SEEDCORE_CITY_FOUNDATION_STORAGE=fixture|postgres` selects the storage
  boundary. Unknown values fail closed, and an explicitly selected PostgreSQL
  path never falls back to the packaged fixture;
- `persist_reference_district()` seeds only the reviewed fixture and requires
  full model parity after reload; and
- `scripts/host/verify_city_foundation_persistence.py` performs an explicit
  PostgreSQL seed/reload/public-projection verification under
  `SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim`; mutation requires the explicit
  `--seed` flag, while the default mode is read-only parity verification.

Focused migration-shape, serialization/hydration parity, explicit seeding,
timezone normalization, and storage-profile failure tests are implemented in
`tests/test_city_foundation_persistence.py`. On 2026-08-20, an isolated local
PostgreSQL 17 run verified clean migration, read/write grants, transactional
seed/reload, schema-only dump/restore followed by reseed/reload parity, and the
unchanged query/projection/anchor API with eight public rows. PostgreSQL remains
an explicit opt-in storage profile until this change receives human review;
there is no automatic migration, seeding, or fixture fallback.

### Change C2: Read-only discovery and MCP parity — REST implemented, MCP pending

Implemented `src/seedcore/api/routers/discovery_router.py` with:

```text
POST /api/v1/discovery/query
GET  /api/v1/discovery/projections/{projection_id}
GET  /api/v1/discovery/anchors/{public_anchor_ref}
```

The router is registered through the existing API router loader, rejects calls
outside `SEEDCORE_CITY_RUNTIME_PROFILE=bootstrap_sim`, excludes protected
features, and uses a pure-Python Haversine helper for radius filtering and
distance ordering. After REST review, add thin wrappers to
`src/seedcore/plugin/mcp_server.py`:

- `seedcore.discovery.search`;
- `seedcore.discovery.get_projection`;
- `seedcore.discovery.explain_claim_state`.

The MCP tools do not query raw foundation tables, accept free-form SQL/filter
expressions, or expose action tools under read credentials.

### Change C3: Two governed-transition proofs

Reuse `src/seedcore/api/routers/agent_actions_router.py` and the existing
governed audit/replay/verifier path for:

1. the simulated water-isolation work package targeting the exact fixture line,
   isolation point, zone, operator, time, and local interlock;
2. one artisan/rare-shoe-style RCT custody transition already compatible with
   the current product wedge.

Do not add `city.execute`, a city-specific PDP, a duplicate token service, a
foundation audit table, or a simulator-only verifier. Both demonstrations must
produce normal policy, token/non-allow, attempt, evidence, replay, verifier,
and quarantine artifacts, with the infrastructure result additionally marked
`SIMULATION_ONLY`.

[`current_next_steps.md`](current_next_steps.md) records the C1-C3 order. C1a,
C1b, and the REST portion of C2 are implemented and focused-test plus isolated
PostgreSQL verified. C1b promotion, MCP parity, and C3 still require review and
closure.

## 12. APIs And Agent Surfaces

The C2 API surface is only:

```text
POST /api/v1/discovery/query
GET  /api/v1/discovery/projections/{projection_id}
GET  /api/v1/discovery/anchors/{public_anchor_ref}
```

These endpoints return public-safe projections assembled through the
foundation service. The following are deferred candidates, not C1-C3 scope:

```text
GET  /api/v1/city/collections
GET  /api/v1/city/features/{feature_ref}
POST /api/v1/city/features/query
GET  /api/v1/city/features/{feature_ref}/history
GET  /api/v1/city/features/{feature_ref}/relationships
GET  /api/v1/city/networks/{network_ref}/topology
GET  /api/v1/city/facilities/{facility_ref}/public-status
GET  /api/v1/city/incidents/{incident_ref}/public-status
POST /api/v1/city/projects/{project_ref}/work-packages/draft
POST /api/v1/city/action-proposals
```

Deferred foundation-specific MCP candidates:

- `seedcore.city.search_features`;
- `seedcore.city.get_feature`;
- `seedcore.city.get_relationships`;
- `seedcore.city.get_public_facility_status`;
- `seedcore.city.get_public_incident_status`;
- `seedcore.city.explain_source_and_state`.

Write/draft tools use a different authenticated namespace. Governed actions use
the existing explicit-authority action gateway rather than a generic
`city.execute` tool.

## 13. Operational And Security Requirements

### 13.1 Threats that matter early

- exposure of exact critical-infrastructure geometry;
- false official/permit/title/inspection claims;
- stale operational state rendered as current;
- topology poisoning and false dependency propagation;
- model-generated geometry or progress treated as observed fact;
- project-document prompt injection crossing into tools;
- forged sensor, contractor, inspection, or completion events;
- token replay or wrong-asset/wrong-zone actuation;
- cross-namespace fixture/live confusion;
- deletion or hidden mutation of disputed history;
- public inference of households, vulnerable people, or sensitive facilities;
- single-founder credential concentration.

### 13.2 Controls

- field-level source posture and field allowlists;
- public-safe projection boundary;
- separate credentials and database roles for read, operator, adapter, and
  authority paths;
- protected geometry purpose/scope checks and access audit;
- content isolation before any model sees imported project artifacts;
- enrolled signer/device/operator registries and revocation;
- deterministic topology and state-transition validation;
- short-lived scoped tokens and endpoint/local-interlock validation;
- append-only history, compensation, replay, and quarantine;
- fixture/live startup assertions and visible environment banners;
- encrypted backups and tested restore;
- human review for production promotion, credential changes, quarantine
  clearance, and live actuation.

### 13.3 Founder-operability rule

The founder may fill several organizational roles during the fixture build,
but role changes remain explicit events. Before live high-consequence use,
separate at least proposer, approver/policy administrator, actuator/operator,
and verifier/quarantine-clearance responsibilities according to the applicable
policy and regulation.

## 14. Verification Program

Test groups:

- schema/version/backward-compatibility tests;
- schema-qualified migration, role/grant, backup/restore, and hot-path
  non-participation tests;
- prefix and `bootstrap_sim` startup/context/verifier isolation tests;
- temporal geometry and relationship tests;
- hierarchy, containment, intersection, and topology tests;
- address/localization and protected-location redaction tests;
- source-posture and five-axis state tests;
- append-only history, late data, projection rebuild, and compensation tests;
- network break/cascade and incident-impact tests;
- simulator determinism and live/fixture separation tests;
- project artifact digest and prompt-injection isolation tests;
- work-package prerequisite and action-class tests;
- gateway/token/local-interlock/evidence/verifier negative tests;
- REST/MCP/map/proof parity tests;
- backup/restore and migration rehearsal.

When work touches SeedCore authority or verification, the existing core gates
remain mandatory:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

Repeated deterministic failure triggers the documented circuit breaker. Do not
relax geometry privacy, external prerequisites, policy, token, evidence, or
verifier rules to make a construction demo pass.

## 15. Definition Of Done For The C1-C3 Foundation MVP

One operator can:

1. start, migrate, seed, back up, restore, and inspect the reference district;
2. traverse region -> land/site -> building/facility -> entrance/space;
3. traverse the two road/path segments and single water-line relationship
   topology;
4. see critical facility dependencies and a simulated outage impact;
5. compare design, declared, observed, operational, verified, and public-safe
   twin projections at a pinned time;
6. explain every material field's source, validity, precision, and visibility;
7. append a correction without rewriting sealed history;
8. operate one project and maintenance work-package lifecycle;
9. execute one simulated governed infrastructure action through principal,
   PDP, token, endpoint, evidence, verifier, and twin settlement;
10. demonstrate deny, stale, wrong asset/zone, replay, interlock refusal,
    evidence mismatch, incomplete inspection, quarantine, and compensation;
11. query the same public-safe foundation through REST, MCP, map, and proof
    surfaces without semantic disagreement;
12. link the producer/service city layer to sites, facilities, access points,
    routes, and operational state without giving discovery authority;
13. prove PostGIS, H3, OGC services, BIM/IFC parsing, a graph database, and a
    tile platform are not required to run or verify the MVP.

Replacing one fixture input with a standards-based adapter is the next
promotion gate after C1-C3. It is not part of the foundation MVP definition of
done.

## 16. Explicit Non-Goals

- no complete real municipality or nationwide cadastre;
- no legal title, permit, zoning, inspection, or professional certification;
- no production utility control, traffic control, emergency dispatch, or
  building management system;
- no autonomous construction site or robot fleet;
- no full BIM authoring, common-data environment, GIS desktop, or asset
  management suite;
- no mandatory 3D city, photorealistic reconstruction, XR, or indoor navigation;
- no citywide real-time telemetry ingestion;
- no public exact critical-infrastructure map;
- no graph database, streaming platform, data lake, tile farm, or Kubernetes
  program without measured need;
- no universal ontology or premature conformance claim;
- no model-generated official facts, approvals, inspections, completion, or
  safety verdicts;
- no replacement of the rare-shoe RCT wedge while the foundation is built.

## 17. Standards Posture

Adopt concepts and adapters incrementally:

| Standard/reference | Bootstrap posture |
| --- | --- |
| GeoJSON / WGS84 | initial simple exchange for public and fixture geometry |
| PostGIS / OGC Simple Features concepts | expected implementation substrate for spatial joins and topology support |
| OGC API Features | read API shape and later conformance/adaptor target |
| CityGML 3.0 | conceptual reference for semantic urban features and later 3D exchange; not the internal authority model |
| IFC 4.3 | versioned BIM/design/as-built artifact and mapping target |
| OGC MUDDI | conceptual reference for underground utility integration |
| OGC SensorThings | adapter target for Things, sensors, datastreams, observed properties, and observations |
| IndoorGML | deferred reference for indoor navigation topology |
| OGC API Tiles / 3D Tiles | deferred delivery formats for scale and visualization |
| H3 | optional coarse lookup, aggregation, and privacy index |

SeedCore's canonical internal contract remains small and purpose-built. Claim
conformance only after profiles, mappings, validation, and tests exist.

Primary references:

- [OGC CityGML 3.0](https://www.ogc.org/standards/citygml/)
- [OGC API - Features](https://www.ogc.org/standards/ogcapi-features/)
- [OGC MUDDI](https://www.ogc.org/standards/muddi/)
- [OGC SensorThings API](https://ogcapi.ogc.org/sensorthings/overview.html)
- [buildingSMART IFC 4.3.2 documentation](https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/content/introduction.htm)
- [OGC IndoorGML 1.1](https://docs.ogc.org/is/19-011r4/19-011r4.pdf)
- [OGC API - Tiles](https://ogcapi.ogc.org/tiles/overview.html)

## 18. Relationship To Other SeedCore Documents

- [`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md)
  owns the combined solo-first implementation sequence and city service layer;
- [`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md)
  owns the long-range ecosystem planes and promotion gates;
- [`persistent_twin_settlement_real_world_ai_operations.md`](persistent_twin_settlement_real_world_ai_operations.md)
  owns the generic append-only twin settlement pattern;
- [`physical_telemetry_processing_contract.md`](physical_telemetry_processing_contract.md)
  owns replay-grade high-rate telemetry processing;
- [`policy_gate_matrix.md`](policy_gate_matrix.md) and
  [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md) own the
  policy and governed-action boundaries;
- [`current_next_steps.md`](current_next_steps.md) owns live execution order.

## 19. Final Build Rule

```text
Model the city before building the marketplace.
Build one district before claiming a platform.
Keep identity, geometry, topology, time, source, privacy, and authority explicit.

A design is not an as-built observation.
An observation is not an official approval.
An approval is not permission for an agent to act.
A token admits only the scoped attempt.
Only evidence and verification settle the governed city transition.
```
