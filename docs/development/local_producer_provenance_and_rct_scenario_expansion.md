# Local Producer Provenance And RCT Scenario Expansion

Date: 2026-08-16
Status: Revised draft; agent-native discovery and grounded creative-sidecar directions accepted, local vertical activation remains staged

## Purpose

This document expands SeedCore's Restricted Custody Transfer (RCT) and source-
registration patterns into three adjacent local-producer scenarios:

1. agricultural micro-lots and regional food batches
2. one-of-one artisan crafts
3. regional workshops that accept, transform, or return customer property

It also defines how a tourist or traveler may discover and inspect these
products through a separate presentation and discovery experience, including
source-grounded humor and rich media that remain explicitly non-evidentiary.

The goal is not to build a generic tourism marketplace, a universal provenance
score, or a 3D map of local businesses. The goal is to test whether SeedCore's
existing contracts can govern claims and consequential physical handoffs across
three distinct asset shapes:

```text
divisible batch     -> agriculture
singular artifact   -> artisan craft
custody-bound work  -> regional workshop
```

The collectible rare-shoe RCT application remains the must-win commercial
wedge. These scenarios are reuse references and staged pilot candidates. They
must not displace the rare-shoe contract, verification, hardware-anchor, and
replay work already in progress.

## Product Positioning

The reusable product narrative is:

```text
Discover local products through ordinary AI-assisted experiences.
Register origin and production claims through governed source registration.
Use SeedCore RCT only when a consequential batch release, artifact transfer,
or workshop custody event requires bounded authority and replayable proof.
```

This produces a narrower and more credible category than "verified local
commerce." SeedCore does not guarantee that every producer story is true. It
governs how evidence is registered, which actions are admissible, who may
execute them, and whether the resulting physical transition closes under
replay.

## Architectural Separation

### Four Distinct Planes

| Plane | Responsibility | Authority posture |
| --- | --- | --- |
| Presentation | 2D/3D product views, workshop tours, translated stories, safe previews | Presentation only; may be generated but must be labelled and source-linked |
| Discovery | Match tourist preferences, itinerary, location, accessibility, availability, and declared product attributes | Recommendation only; never a policy or custody decision |
| Source registration | Adjudicate producer, origin, batch, method, material, condition, and external-certificate evidence | Produces a `RegistrationDecision`; does not mint execution authority |
| Governed action and verification | Admit a batch release, unique-object handoff, workshop operation, or return transfer and verify the result | `ActionIntent` -> PDP -> scoped `ExecutionToken` -> receipt -> replay / verifier |

The planes may exchange explicit, versioned projections. They must not share an
implicit authority path.

```text
Producer claims + raw evidence
  -> TrackingEvent first write
  -> SourceRegistration projection
  -> RegistrationDecision
  -> public-safe verified projection
  -> discovery / showcase

Consequential physical action
  -> accountable principal or agent
  -> typed ActionIntent
  -> PDP admission under pinned policy and fresh context
  -> scoped ExecutionToken or deny
  -> operator / actuator attempt
  -> signed evidence and transition receipt
  -> RESULT_VERIFIER / replay closure
```

### Risk-Tiered Use

Not every local sale needs RCT.

| Tier | Example | SeedCore involvement |
| --- | --- | --- |
| Tier 0: showcase | public workshop tour or AI-translated producer story | no authority path; ordinary presentation service |
| Tier 1: registered provenance | ordinary honey jar linked to an approved production batch | `TrackingEvent` -> `SourceRegistration` -> `RegistrationDecision` |
| Tier 2: governed batch release | export-grade coffee micro-lot released to a logistics partner | approved registration plus a scoped release `ActionIntent` |
| Tier 3: restricted custody | one-of-one textile, customer-owned instrument, rare craft, or insured shipment | full RCT with approvals, token, signed handoffs, evidence, and replay |

Policy and product owners select the tier. A discovery UI, attractive story, or
high model-confidence score cannot silently escalate an ordinary product into a
SeedCore-governed claim, or relax a governed transfer into an ordinary click.

## Shared Trust Boundaries

### Identity And Site Claims

A producer identifier, DID, phone account, or workshop profile does not prove
ownership, maker status, land rights, or control of a location.

Producer and site registration may include:

- verified person or organization credential
- cooperative, guild, cultural association, or business-registry reference
- declared site and boundary
- lease, land, permit, or registry reference when the policy profile requires
  one
- admitted inspector, certifier, buyer, or cooperative attestation
- device and signer enrollment evidence
- challenge-bound capture and telemetry refs

The registration record must state which claims were declared, externally
attested, policy-admitted, rejected, or still pending. It must not flatten
those states into one generic producer badge.

### App And Device Integrity

Apple App Attest or Android Play Integrity may strengthen a claim that a
request came from an expected app instance or recognized device environment.
They do not prove:

- the camera observed the claimed field, workshop, or product
- the producer controls or owns the depicted location
- the GPS fix or wall-clock time is physically truthful
- the depicted process actually created the sold item
- a static QR or NFC identifier remains attached to the registered asset

Capture requests should bind a server nonce, producer or operator identity,
registration or workflow id, artifact manifest, physical-anchor ref when
required, and observation time. The server must reconstruct and verify the
canonical binding rather than trusting a client-supplied digest.

### Media Lineage And Truth

Hashes and C2PA Content Credentials may prove content binding, lineage,
declared transformations, and tamper evidence. They do not prove factual
origin, organic status, handmade production, material composition, or legal
ownership.

Raw evidence must remain available according to retention policy. Masks,
thumbnails, translations, captions, point clouds, meshes, 3D views, and edited
clips are derived artifacts.

### External Certification

Organic, fair-trade, geographic-indication, laboratory, guild, repair, or
cultural-origin claims remain external assertions until SeedCore verifies the
issuer, signature, scope, asset or batch binding, issue time, expiry,
revocation, and policy admissibility.

SeedCore preserves and governs use of the claim. It does not become the organic
certifier, land registry, guild, or cultural authority.

## Scenario A: Agricultural Micro-Lot

### Commercial Scene

Candidate products include single-origin coffee, specialty honey, tea, cacao,
regional spirits, dried fruit, spices, and other small-batch products for which
origin, production window, handling, and batch identity affect value.

The user-facing promise should be narrow:

```text
This package is linked to a registered lot whose declared origin, production
evidence, packing lineage, and custody events can be inspected and replayed.
```

It must not become an unqualified statement that the product is organic,
ethically produced, legally exported, or chemically authentic unless the
relevant admitted evidence and policy profile support that exact claim.

### Actors

| Actor | Responsibility |
| --- | --- |
| Farmer or producer collective | declares source, production window, quantity, and supporting evidence |
| Field or collection operator | captures observations and signs or submits telemetry under assigned scope |
| Cooperative or processor | receives, transforms, grades, aggregates, or packs the lot |
| Inspector, laboratory, or certifier | supplies external signed claims under an admitted issuer profile |
| Packing operator | creates sealed child units linked to the parent batch |
| Courier or export partner | executes a scoped release and custody handoff |
| Retailer or receiving buyer | receives the lot and provides closure evidence |
| SeedCore operator / verifier | monitors policy, evidence, replay, and quarantine outcomes |

### Governed Lifecycle

```text
Producer declares micro-lot and claimed origin
  -> capture, measurements, and external certificates become TrackingEvents
  -> SourceRegistration projects current batch state
  -> validators evaluate evidence under a pinned registration policy
  -> RegistrationDecision approves, rejects, reviews, or quarantines the lot
  -> packing creates sealed child units linked to the parent batch
  -> high-value or restricted release becomes an ActionIntent
  -> PDP checks registration, quantity, recipient, zone, TTL, and approvals
  -> scoped ExecutionToken authorizes one release attempt
  -> courier and receiver submit signed seal, weight, and condition evidence
  -> RESULT_VERIFIER checks lineage, quantity balance, custody, and receipts
```

Registration remains distinct from release. An approved origin registration
does not itself authorize packing, export, custody movement, or settlement.

### AgriculturalBatchRegistrationV0 Profile

This should begin as a profile over `TrackingEvent`, `SourceRegistration`,
artifacts, measurements, and `RegistrationDecision`, not as a separate event
store.

Candidate fields:

- `registration_id`
- `batch_id`
- `producer_ref`
- `producer_credential_refs`
- `product_kind`
- `declared_origin`
- `site_claim_refs`
- `production_window`
- `initial_quantity`
- `quantity_unit`
- `harvest_or_collection_method`
- `processing_method`
- `external_certificate_refs`
- `environmental_measurement_refs`
- `laboratory_result_refs`
- `visual_evidence_refs`
- `physical_anchor_profile`
- `policy_snapshot_ref`
- `registration_decision_ref`
- `risk_state`

### BatchTransformationV0

Agricultural goods are divisible and transformable. SeedCore needs an explicit
lineage record when a parent batch is split, merged, dried, roasted, fermented,
filtered, packed, or otherwise changed.

```json
{
  "contract_version": "seedcore.batch_transformation.v0",
  "transformation_id": "batch-transform:coffee-001:pack-001",
  "operation": "split_and_pack",
  "parent_batch_refs": ["batch:coffee-001"],
  "child_batch_refs": [
    "package:coffee-001:0001",
    "package:coffee-001:0002"
  ],
  "input_quantity": {"value": 20.0, "unit": "kg"},
  "output_quantity": {"value": 19.2, "unit": "kg"},
  "declared_process_loss": {"value": 0.8, "unit": "kg"},
  "process_profile_ref": "process:coffee-pack:v0",
  "operator_ref": "operator:coop-pack-001",
  "observed_at": "2026-08-14T04:00:00Z",
  "evidence_refs": ["evidence:scale-001", "evidence:seal-001"],
  "payload_sha256": "sha256:batch-transform"
}
```

The arithmetic is illustrative fixture data. Policy profiles define permitted
loss, conversion, aggregation, and measurement tolerances by product and
process.

### Evidence Classes

- producer and site claim refs
- harvest, collection, or production interval
- raw media and capture-binding manifests
- weight, moisture, temperature, humidity, altitude, or other relevant
  measurements
- chemical, pollen, spectroscopy, or laboratory summaries when applicable
- inspector and certification signatures
- processing or transformation receipts
- parent/child batch lineage
- packing weight, package count, seal, and dynamic NFC refs when justified
- transit-temperature and receiving-condition evidence for perishable goods

No single modality proves origin. Visual evidence cannot replace laboratory
evidence where composition matters, and a laboratory sample cannot prove that
the delivered package contains the sampled batch without custody lineage.

### Policy Gates

- producer and operator identities meet the selected policy profile
- the registration decision is approved and fresh
- required issuer signatures are trusted, scoped, and unexpired
- batch quantity and parent/child lineage reconcile within admitted tolerance
- split, merge, and processing operations are declared
- physical anchor, package, and workflow bindings agree
- release recipient, route or zone, quantity, TTL, and approvals are within
  scope
- quarantine, recall, contamination, or certificate-revocation state is clear
- receiving telemetry and receipts close the same release attempt

### Toxic Paths

| Failure | Required posture |
| --- | --- |
| production observed outside the registered window | deny registration or require review |
| certification issued by an unknown, expired, or revoked issuer | exclude the claim; deny if policy requires it |
| child packages exceed parent quantity plus admitted process tolerance | quarantine lineage and block release |
| two origins are mixed without a declared merge | quarantine the resulting batch |
| static QR copied onto another package | treat as identifier failure; require stronger binding where policy demands it |
| genuine seal or tag moved to a different package | quarantine on anchor or package-binding mismatch |
| valid origin evidence replayed for another producer, lot, or season | deny and preserve cross-batch replay evidence |
| transit temperature exceeds profile | review or quarantine according to product policy |
| laboratory result exists but sample-to-batch custody is broken | treat composition claim as insufficient |

The defining agricultural problem is **divisible batch lineage**. Quantity,
transformation, and custody conservation matter more than reconstructing an
attractive 3D representation of the farm.

## Scenario B: One-Of-One Artisan Craft

### Commercial Scene

Candidate products include hand-loomed textiles, carved objects, signed
ceramics, handmade instruments, limited jewelry, custom leather goods, and
other artifacts whose maker, method, material, uniqueness, and condition affect
value.

The user-facing promise should distinguish the maker claim, process evidence,
material evidence, object identity, and custody outcome rather than collapsing
them into "authentic handmade."

### Actors

| Actor | Responsibility |
| --- | --- |
| Maker or family workshop | declares authorship, method, materials, and the intended artifact |
| Material supplier | supplies batch or origin refs for relevant inputs |
| Cooperative, guild, or cultural association | supplies external identity or method attestations when applicable |
| Authenticator or curator | evaluates the completed artifact under a declared profile |
| Gallery or listing partner | supplies product, quote, and order context |
| Buyer or buyer agent | expresses commercial intent within delegated constraints |
| Courier or custodian | executes the admitted physical handoff |
| Verifier | checks object identity, evidence lineage, custody, and closure |

### Governed Lifecycle

```text
Maker registers identity, workshop claim, materials, and intended piece
  -> production milestones append raw and derived evidence
  -> completed artifact receives a physical and visual fingerprint
  -> RegistrationDecision records admitted maker, method, material, and state
  -> AI may prepare a sourced product story, translation, or listing proposal
  -> buyer or agent proposes acquisition
  -> high-value release becomes a scoped custody ActionIntent
  -> PDP checks registration, buyer approval, asset state, and evidence
  -> courier handoff executes under a short-lived ExecutionToken
  -> delivery capture, physical-anchor evidence, and receipt close via replay
```

### CraftObjectRegistrationV0 Profile

Candidate fields:

- `registration_id`
- `asset_id`
- `maker_ref`
- `maker_credential_refs`
- `workshop_claim_ref`
- `craft_class`
- `material_batch_refs`
- `declared_method_refs`
- `process_milestone_refs`
- `maker_mark_or_signature_hash`
- `visual_evidence_refs`
- `spatial_fingerprint_hash`
- `physical_anchor_profile`
- `condition_baseline_ref`
- `external_attestation_refs`
- `policy_snapshot_ref`
- `registration_decision_ref`
- `custody_state`
- `risk_state`

The profile may reuse the rare-shoe visual-evidence adapter for raw-preserving
capture, static reconstruction, fingerprint comparison, and outcome taxonomy.
The comparison remains evidence only.

### Evidence Classes

- maker identity and workshop association
- material-supplier or material-batch references
- dye, clay, wood, metal, thread, stone, or leather declarations
- process-stage raw images or video
- loom, kiln, tool, mold, or workstation evidence when relevant
- maker's mark, signature, seal, or dynamic physical anchor
- final macro, visual, or geometric fingerprint
- completed condition and packaging baseline
- admitted cultural or guild attestations with issuer provenance

### Policy Gates

- maker and workshop credentials meet the claim profile
- required process milestones link to the same registration and artifact
- external cultural, guild, or material claims come from admitted issuers
- completed artifact fingerprint and physical anchor bind to the registration
- modifications, restorations, or substitutions are declared
- listing, quote, order, value, buyer approval, and asset refs agree
- release and delivery occur under scoped, fresh authority
- final observation is sufficiently consistent or routes to review/quarantine

### Toxic Paths

| Failure | Required posture |
| --- | --- |
| reseller claims to be the maker | reject maker claim; preserve seller role separately |
| factory-produced substitute uses a copied workshop story | quarantine or reject when evidence contradicts the registration |
| material origin differs from the declared source | isolate the material claim; deny if policy requires it |
| AI narrative adds unsupported history or cultural claims | label/remove generated claim; never promote it into provenance |
| visually similar item replaces the registered piece | quarantine on fingerprint or anchor mismatch |
| genuine tag is moved to another artifact | deny or quarantine on physical-anchor binding failure |
| restoration occurs without being appended to lineage | flag condition/provenance discontinuity and require review |
| visual capture is insufficient | recapture or review; do not infer counterfeit status from missing evidence |

This is the closest RCT extension to the rare-shoe application because it uses
a singular physical object, visual fingerprint, condition baseline, bounded
release, delivery evidence, and replayable custody closure.

## Scenario C: Regional Workshop Custody

### Commercial Scene

Candidate services include instrument repair, jewelry restoration, custom
furniture, motorcycle-part refurbishment, textile alteration, camera repair,
and restoration of customer-owned artifacts.

This is a strong RCT scenario because the workshop receives physical property
it does not own, may perform irreversible operations, may substitute parts, and
must return the correct asset to an authorized recipient.

### Actors

| Actor | Responsibility |
| --- | --- |
| Customer or owner-side custodian | declares the item, constraints, delivery recipient, and approval limits |
| Intake operator | records condition, accessories, defects, and initial handoff evidence |
| Workshop owner | accepts organizational responsibility and assigns operators |
| Craftsperson or technician | performs only admitted work under assigned scope |
| AI diagnostic assistant | suggests diagnosis, parts, or plan; never supplies approval or authority |
| Parts or materials supplier | supplies part identity and provenance refs |
| Quality inspector | records completion tests and discrepancies |
| Return courier | executes a bounded return handoff |
| Verifier | replays intake, approvals, work, parts, release, and receipt |

### Governed Lifecycle

```text
Customer and workshop record an intake handoff
  -> condition, accessories, defects, and customer constraints are registered
  -> workshop receives bounded custody, not ownership
  -> AI may diagnose and propose a work plan
  -> accountable craftsperson submits exact work scope
  -> customer approves price, parts, and irreversible operations
  -> PDP admits only the approved action class, asset, operator, and window
  -> scope changes require a new approval and policy evaluation
  -> completion inspection records parts, condition, and test evidence
  -> return release requires recipient, zone, time, and custody checks
  -> customer receipt and verifier replay close the case
```

### WorkshopCustodyCaseV0 Profile

```json
{
  "contract_version": "seedcore.workshop_custody_case.v0",
  "case_id": "workshop-case:instrument-001",
  "asset_id": "asset:instrument-001",
  "customer_principal_ref": "principal:customer-001",
  "workshop_principal_ref": "principal:workshop-001",
  "intake_custody_receipt_ref": "receipt:intake-001",
  "condition_baseline_ref": "condition:instrument-001:intake",
  "included_item_refs": ["accessory:case-001", "accessory:bow-001"],
  "approved_work_scope": ["diagnose", "replace_string", "adjust_bridge"],
  "prohibited_operations": ["replace_original_label", "refinish_body"],
  "spending_limit": {"currency": "USD", "amount": "400.00"},
  "irreversible_operation_approval_ref": null,
  "assigned_operator_refs": ["operator:craftsperson-001"],
  "required_part_provenance": true,
  "return_recipient_ref": "principal:customer-001",
  "policy_snapshot_ref": "policy:workshop:v0",
  "workflow_join_key": "sha256:workshop-case"
}
```

The contract sketch is not a new authority source. Each consequential workshop
operation still needs a typed `ActionIntent` or an admitted, explicitly scoped
workflow node under the existing gateway and token lifecycle.

### Evidence Classes

- dual-party intake receipt
- asset identity and initial visual fingerprint
- condition, defects, and included-accessory inventory
- approved diagnosis and work order
- price and spending-limit approval
- separately approved irreversible operations
- assigned operator and workstation refs
- replacement-part identity and provenance
- before, during, and after raw media
- quality-control measurements and test results
- original-part return or disposal evidence when required
- final release, recipient, courier, and customer-receipt evidence

### Policy Gates

- intake asset and workshop custody receipt agree
- customer or delegated approver is active and correctly scoped
- requested operation is inside the approved work scope
- irreversible operation has explicit step-up approval
- price and replacement parts remain inside approved constraints
- operator is assigned and qualified for the operation profile
- prohibited operations are absent
- part provenance is present when required
- release recipient and return route are correct
- condition, included items, and final tests satisfy closure policy

### Toxic Paths

| Failure | Required posture |
| --- | --- |
| workshop performs irreversible work outside approved scope | deny the operation before execution or quarantine the case after evidence mismatch |
| AI diagnosis is treated as customer approval | deny; advisory output is not approval |
| part is replaced without disclosure or evidence | quarantine completion and require operator review |
| original parts are not returned when required | withhold closure or route to dispute review |
| cost increase exceeds delegated limit | require a new approval; do not widen the existing token |
| item is released to the wrong recipient | deny release and preserve attempted mismatch evidence |
| final inspection is missing | withhold closure where policy requires it |
| edited showcase imagery hides condition deterioration | inspect raw evidence; quarantine presentation/evidence contamination |

The principal object is a **custody-bound work order**: customer asset,
approved transformation scope, assigned operator, parts, constraints, and final
return remain bound throughout the case.

## Accessible Producer Ingestion

### Product Goal

Small producers and workshop operators should not need to understand JSON
schemas, DPoP, API keys, signing formats, policy graphs, or MCP configuration.
SeedCore should own a narrow, accessible ingestion experience that converts
photos, documents, measurements, and voice notes into a reviewable draft.

```text
photo / document / scale reading / voice note
  -> simple mobile upload, assisted cooperative UI, or opt-in messaging webhook
  -> conversational ingestion adapter
  -> SourceRegistrationDraftV0
  -> plain-language producer or authorized-operator confirmation
  -> governed TrackingEvent first writes
  -> SourceRegistration projection
  -> validators and RegistrationDecision
```

The AI-assisted intake step creates a draft, not a registration decision. It
must never silently convert extracted text, image interpretation, transcript,
translation, location metadata, or model confidence into registered fact.

### SourceRegistrationDraftV0

The draft should preserve:

- draft id and selected registration profile
- producer or workshop identity candidate
- source artifact refs and hashes
- extracted field candidates with per-field source refs
- declared versus model-inferred field labels
- transcript and translation refs
- missing required fields
- conflicts and low-confidence fields
- privacy-sensitive fields and proposed public redactions
- confirmation status, confirming principal, and confirmation time
- expiry time so an abandoned draft cannot become ambient state

The producer-facing confirmation should use local language and concrete
statements, for example:

```text
You declared this as coffee lot LOT-42, collected between 12 and 14 August.
The uploaded scale image was read as 24.8 kg.
Origin is still a claim and has not yet been verified.
Confirm, correct, or save as draft.
```

Confirmation means "submit these declared fields and artifacts into the
governed registration workflow." It does not mean SeedCore has verified the
claim, authorized release, or transferred custody.

### Draft Tool Boundary

Candidate tool:

- `seedcore.producer.draft_registration_from_media`

The tool may extract, normalize, translate, identify missing fields, and
prepare a draft. It must not:

- submit or confirm on behalf of the producer without an admitted principal
- invent missing measurements, certificates, dates, or locations
- overwrite raw media or transcript artifacts
- label inferred content as producer-declared
- produce a `RegistrationDecision`
- submit an `ActionIntent` or mint execution authority

Confirmation should be a distinct producer/operator action with identity,
consent, idempotency, and an explicit review summary. Assisted cooperative
operators may help, but their role and delegation must remain visible.

### Inclusion And Reliability

- support low-bandwidth uploads and resumable/offline capture queues
- provide an assisted cooperative or municipal desk workflow
- use local-language prompts and accessible controls
- avoid requiring a proprietary chat platform; messaging channels are optional
  adapters over the same draft contract
- let producers correct transcripts and extracted measurements
- state data retention, public visibility, fees, and dispute ownership before
  confirmation
- preserve raw media and confirmation evidence for authorized review
- never penalize a producer's product ranking merely because they need assisted
  intake or cannot afford optional hardware

## Tourist Discovery And On-Site Verification

### Experience Boundary

The tourist experience consumes public-safe, read-only projections from the
registration and RCT systems.

```text
Tourist preference or itinerary prompt
  -> ordinary semantic discovery service
  -> read-only verified local-producer projections
  -> product or workshop cards with explicit claim status
  -> ordinary route, reservation, or checkout service
  -> optional on-site scan and evidence inspection
```

Examples:

- "Find a smallholder coffee micro-lot along my route whose current batch has
  an approved source registration."
- "Show hand-loomed indigo textiles made by registered family workshops, and
  distinguish maker evidence from AI-generated story text."
- "Find an instrument workshop that records customer-property intake, approved
  work scope, replacement parts, and return custody."

The discovery model may use natural-language preferences and public product
knowledge. It must not query authority-tier telemetry directly or interpret an
AI similarity score as a verification verdict.

### Agent-Native Autonomous Discovery Surface

SeedCore should make the read-only discovery plane directly usable by Codex,
Gemini, and other current or future AI agents through vendor-neutral contracts.
The canonical service should be a SeedCore Projection Discovery API exposed
through thin MCP tools, assistant plugins, AI skills, and typed SDK clients.

```text
Codex skill / Gemini extension / third-party agent / application
  -> SeedCore MCP, plugin, skill, or SDK wrapper
  -> read-only Projection Discovery API
  -> public-safe VerifiedLocalProvenanceProjectionV0 records
  -> autonomous search, filter, compare, explain, and route planning
```

The assistant-specific packages are adapters, not independent discovery
databases. MCP, REST/OpenAPI, JSON Schema, pagination, and stable projection
contracts should remain canonical so a new agent host does not require a new
truth or policy implementation.

Frontier agents reduce the need for SeedCore to build a custom itinerary app,
chat assistant, or destination map for every platform. They do not eliminate
SeedCore-owned user experience entirely. SeedCore still needs:

- a low-tech producer intake and confirmation surface
- a canonical, accessible public proof page
- an authorized operator and exception surface
- documentation, consent, privacy, support, and dispute flows

The owned surfaces establish stable semantics and accessibility when an agent
host is unavailable, incompatible, unsafe, or unable to render the exact claim
state. Agent ecosystems are distribution channels over SeedCore contracts, not
the only way a producer or consumer can understand the record.

Strict v0 read-only MCP tools:

- `seedcore.discovery.search`
- `seedcore.discovery.get_projection`
- `seedcore.discovery.explain_claim_state`

Claim details, public proof summary, and anchor resolution should be returned by
the projection payload or deterministic explanation in v0. Separate
`get_claims`, `compare_projections`, `get_public_proof_summary`, and
`resolve_public_anchor` tools are deferred until real client usage proves that
the three-tool surface is insufficient.

Recommended AI skills or plugin workflows:

- `discover_verified_local_producers`
- `compare_local_product_claims`
- `build_verified_local_route`
- `explain_product_proof`
- `inspect_on_site_product_projection`

The skills may autonomously compose multiple read calls, refine queries,
paginate, compare products, explain evidence status, and draft an itinerary.
They must not create a new verification state, mutate a registration, reserve
inventory, purchase a product, release a batch, approve workshop work, transfer
custody, or clear quarantine.

Any transition from exploration to consequential action is an explicit handoff:

```text
autonomous read-only exploration
  -> proposed next action shown with exact subject and projection refs
  -> accountable principal / delegation resolved
  -> separate ActionIntent submitted to Agent Action Gateway
  -> PDP evaluates current policy, asset state, scope, freshness, and approvals
  -> scoped ExecutionToken or deny
  -> receipt and replay closure
```

A discovery skill must not automatically call an action tool merely because a
product ranks highly or has a current verified projection. If a host supports
both discovery and action tools, their namespaces, permissions, audit traces,
and user-facing status must remain visibly distinct.

#### Strict v0 Discovery Query Contract

The canonical v0 read surface has exactly three endpoints:

- `POST /api/v1/discovery/query` for read-only structured filtering over static
  projections
- `GET /api/v1/discovery/projections/{projection_id}`
- `GET /api/v1/discovery/anchors/{public_anchor_ref}`

Using `POST` for the query does not make the operation a write. The server
contract, authorization scope, and implementation must guarantee that these
calls do not mutate registration, policy, custody, inventory, reservation, or
verifier state.

The v0 router is stateless and fixture- or read-model-backed. It applies an
allowlisted filter grammar, stable ordering, pagination, redaction, and
freshness projection. It does not contain an LLM, recommendation engine,
real-time negotiation, agent bidding, marketplace matching, or dynamic
multi-agent protocol. The calling agent may interpret the structured results
for the user's itinerary, but the router itself does not rank trust or negotiate
commerce.

Each discovery result should carry:

- `projection_id` and `projection_version`
- `subject_ref` and `subject_kind`
- public producer or workshop display fields
- structured claim states and their named policy/profile refs
- current verifier disposition
- `as_of` time, freshness or expiry state, and optional `etag`
- public-safe evidence and presentation refs
- coarse public location and accessibility fields when permitted
- `source_url` or canonical projection link
- explicit `presentation_only` labels
- pagination cursor and result-limit metadata

Semantic relevance, itinerary fit, popularity, distance, and user preference
may influence ranking. They must be returned separately from verification and
claim state so an agent cannot interpret ranking as trust.

#### Read Permissions And Privacy

Suggested capabilities:

- `discovery:read_public`
- `projection:read_public`
- optional `projection:read_partner` for authenticated, contract-approved
  fields

The discovery token or API key must never carry custody execution, quarantine
release, policy mutation, or authority-tier evidence permissions. Public tools
must return coarse locations where exact farm, home, workshop, or storage
coordinates would create privacy or theft risk.

Caching is allowed only as a convenience layer. Clients must preserve
projection version and `as_of` time, honor expiry/revocation signals, and avoid
describing a cached result as current after its freshness bound. A discovery
client cannot locally convert stale or unavailable state into `verified`.

#### Untrusted Content And Prompt Injection

Producer descriptions, AI narratives, URLs, media captions, and external
certificates are untrusted content from an agent-execution perspective. An
autonomous discovery agent must not treat instructions embedded in those fields
as tool commands, policy, delegation, or permission.

The projection API and client adapters should:

- keep structured claim state separate from free-form presentation text
- mark source and content type for every narrative field
- sanitize or isolate active content and unsafe links
- never place producer text in MCP tool descriptions or system instructions
- require explicit tool arguments derived from the user's exploration goal
- prevent discovered content from selecting action tools or widening scope
- retain a read trace with query hash, tool calls, projection ids, versions, and
  result timestamps for debugging and abuse review

The read trace is observability, not execution authority or custody evidence.

### Claim-State Vocabulary

Product cards should expose structured status rather than a single provenance
score:

| Status | Meaning |
| --- | --- |
| `CLAIMED` | supplied by the producer or workshop but not yet adjudicated |
| `REGISTERED` | accepted into a governed source-registration record |
| `VERIFIED_FOR_CURRENT_PROFILE` | required evidence satisfies a named current policy/verifier profile |
| `PENDING_REVIEW` | evidence or authority requires human or policy-directed review |
| `REJECTED` | the relevant registration or verification path failed |
| `QUARANTINED` | the asset, batch, or case is blocked pending remediation |
| `PRESENTATION_ONLY` | AI narration, translation, generated preview, or other non-evidentiary content |

Do not publish a generic `SeedCore Provenance Score`. Scores hide which claim
was verified, under what policy, with which evidence, and whether a later
custody mismatch invalidated the current product state.

### Human-Readable Public Proof

Every public anchor should resolve to a canonical low-bandwidth proof page, for
example:

- `GET /verify/{public_anchor_ref}`

The page must work without an AI agent, plugin, account, or specialist
cryptographic knowledge. It should render claim-specific statements such as:

```text
Origin claim: verified for policy profile coffee-origin-v0
Declared collection window: 12-14 August 2026
Batch: LOT-42
Current custody verification: pending receiving scan
Presentation story: AI-assisted translation
```

The page should expose plain-language explanation first and technical detail on
demand. It should show:

- exact claim and status
- subject or batch reference
- named verification/policy profile
- `as_of` time and expiry/freshness state
- current verifier disposition
- safe evidence summary and source link
- presentation-only labels
- dispute, correction, or operator-review path

Icons and checkmarks may support comprehension, but color or a generic badge
must not hide partial, expired, review, rejected, or quarantined state.
AI-generated explanation or localization is a derived presentation. The
structured claim state remains canonical.

The strict MVP is server-rendered HTML with safe escaping, semantic markup,
basic responsive CSS, and no required client JavaScript. It must not depend on
a native application, WebGL/WebGPU viewer, 3D canvas, or map-client stack.
`explain_claim_state` should initially be deterministic and template-backed;
LLM narration or localization is deferred presentation content.

### On-Site Scan

For ordinary low-value goods, a QR code may identify the registration or public
projection. It must be described as an identifier, not clone-resistant proof.

A printed QR may point to a server response that changes over time, but the
printed mark itself is static and copyable. Do not call it a dynamic physical
anchor. It is suitable for opening the canonical proof page, not proving that
the scanned package is the registered physical package.

For a policy profile requiring stronger physical presence:

- use enrolled dynamic NFC or another challenge-response anchor
- bind the scan to the asset or package, workflow or session, nonce, device,
  observation time, and expected counter state
- preserve public-safe scan disposition without leaking raw UID, challenge,
  CMAC, key, or private location
- treat a successful scan as evidence, not authority or legal ownership

Reservations, navigation, recommendations, and ordinary low-value checkout do
not need an `ExecutionToken`. A later restricted release or custody transfer is
a separate governed action.

## Presentation And Generated Content

### Product Principle: Verified Spine, Creative Sidecar

SeedCore may support funny, vivid, locally distinctive storytelling without
turning generated content into evidence. The reusable pattern is:

```text
registered raw sources + current public-safe claim projection
  -> source-grounded creative proposal
  -> grounding, consent, safety, and disclosure checks
  -> producer-approved presentation artifact
  -> "Artisan Story & Lore" beside deterministic "Verified Origins"
```

The verified projection is the factual spine. A creative sidecar may add tone,
format, translation, and entertainment, but it cannot add truth status. A joke
is not verified merely because it was inspired by a verified record, and a
producer statement remains `CLAIMED` unless an admitted policy/profile has
verified that exact claim.

This boundary enables experiences such as an artisan confessional, a witty
travel-buddy explanation, or a short workshop audio story while preserving the
same proof semantics for humans and AI agents.

### Grounded Creative Artifact Contract

A derived story, comic, audio clip, reel, or widget should be represented as a
non-authoritative `GroundedCreativeArtifactV0`, not embedded into a claim or
evidence record. At minimum it should carry:

- artifact id, content kind, locale, and version
- subject ref, source projection id/version, and projection `as_of` time
- source artifact refs and transcript/time-span or structured-field citations
- a machine-readable distinction between `VERIFIED`, `REGISTERED`, `CLAIMED`,
  and `LORE` material used by the artifact
- persona/style id and version rather than an untracked free-form system prompt
- generator, model, template, and transformation versions
- synthetic-media disclosure, including synthetic or cloned voice state
- producer/rights-holder review and consent refs when a real person's name,
  likeness, voice, dialect, workshop ambience, or cultural material is used
- grounding and safety-check results, public visibility, expiry, content hash,
  and canonical correction/takedown path
- `presentation_is_authority: false`

Creative artifact citations explain what grounded the presentation. They do
not upgrade the cited statement, prove that a humorous event happened, or make
the generated artifact eligible for PDP, fingerprint, verifier, or custody
closure input.

### Creative Pipeline With Trust Gates

Creative generation begins only after the registration draft and its explicit
confirmation have completed. It must not reuse the draft extractor's output as
public truth or silently publish private intake media.

```text
one producer image + one producer voice memo
  -> private SourceRegistrationDraftV0 extraction
  -> producer correction and explicit registration confirmation
  -> governed registration decision and public-safe projection
  -> creative director proposes script/persona/format from allowlisted fields
  -> grounding validator maps every factual sentence to typed source refs
  -> consent, cultural-safety, impersonation, and public-redaction checks
  -> producer/authorized reviewer approves presentation release
  -> GroundedCreativeArtifactV0 published as presentation-only
  -> public page or discovery agent renders disclosure + source link
```

If grounding, consent, redaction, or claim-state checks fail, the system should
fall back to the deterministic proof card. It must not improvise missing facts.
Changing or revoking a source projection should mark dependent creative
artifacts stale or withdrawn; regeneration never edits the historical proof
record.

### Humor And Cultural-Safety Policy

Humor may exaggerate delivery, metaphor, timing, or persona. It must not
exaggerate factual claims. In particular, generated content must not invent or
upgrade:

- awards, certifications, ingredients, health or environmental benefits
- maker identity, cultural ownership, sacred meaning, family history, labor
  conditions, geographic origin, dates, quantities, prices, or custody events
- numerical details such as hours worked, storms survived, animals encountered,
  or injuries suffered unless they are explicitly sourced and correctly
  labelled as declared or verified
- endorsements or dialogue attributed to a real person

The service should also reject demeaning stereotypes, poverty tourism,
non-consensual jokes about a named person, imitation of a living person's voice
without explicit permission, and casual reuse of sacred or restricted cultural
material. A producer can select or reject a persona, edit jokes, withdraw
presentation consent, and request correction without being able to rewrite
immutable evidence or verifier history.

Synthetic voice, translated speech, dramatization, animation, and reconstructed
ambience must be disclosed in the media itself and in nearby text. An
"authentic local voice" should mean producer-approved language and tone, not an
undisclosed clone or a model's stereotype of a dialect.

### Format Tiers

The formats are sequenced so creative ambition does not expand the strict MVP:

| Tier | Allowed scope | Status |
| --- | --- | --- |
| MVP | safely escaped story/lore text; producer-approved still image; optional native HTML audio with transcript; deterministic verified-origin card directly adjacent | build only after the base proof contract is frozen |
| Bounded pilot | captioned comic carousel, 15-second subtitled reel, multilingual narration, simple flavor/craft quiz, or static comparison graphic; all pre-rendered and source-linked | feature-flagged, separately reviewed presentation experiment |
| Deferred research | image-to-video, synthetic/voice-cloned characters, personalized live personas, AR moments, 3D/WebGL experiences, or real-time multimodal generation | not part of the discovery or proof MVP |

No format may be required to understand claim state. Media must not autoplay;
audio needs a transcript, video needs captions, controls need keyboard access,
and motion must respect reduced-motion preferences. Low-bandwidth and no-script
users receive the same proof state and a text alternative.

### Public Proof-Card Composition

The canonical `/verify/{public_anchor_ref}` page may be engaging, but exact
claim state must remain visible above the fold. Its semantic order should be:

1. subject/batch identity, current disposition, `as_of`, and freshness
2. optional **Artisan Story & Lore** card with explicit generated/dramatized
   disclosure and source links
3. **Verified Origins** with claim-by-claim status and named policy/profile
4. **Producer-Declared Details** for sourced statements that are not verified
5. technical evidence detail and correction/dispute paths

For example, "the harvester says he was stung twice" belongs under declared
detail unless that exact event has admitted evidence. "100% natural nectar" is
not a verified statistic without a named claim, issuer, evidence, and policy
profile. A signing timestamp proves that SeedCore recorded a statement or
artifact at a time; it does not prove every sentence inside it.

The creative card may be visually prominent, but it cannot obscure a stale,
rejected, partial, or quarantined state. Agent clients should receive the same
typed separation and may summarize the story only with its
`PRESENTATION_ONLY` label and canonical source URL.

### Allowed Presentation Sidecars

- optimized 2D images and safe clips
- static 3D mesh, point cloud, or Gaussian-splat representation under a
  commercially reviewed implementation
- interactive product rotation or workshop snapshot
- multilingual text, voice, or video narration
- itinerary and accessibility summaries
- declared producer notes and sourced cultural context

### Required Controls

- raw evidence and derived presentation artifacts remain separate
- every presentation artifact carries source refs and transformation metadata
- AI narration is labelled and cites registered or declared source fields
- generated pixels cannot enter source registration, fingerprint comparison,
  PDP context, physical closure, or verifier evidence
- translation preserves claim status and does not upgrade `CLAIMED` to
  `VERIFIED`
- producers can review public stories without gaining authority to rewrite
  historical evidence or verifier outcomes
- public cards show pending, rejected, quarantined, and expired states clearly
- generated factual sentences are source-mapped and preserve the source
  claim's exact state
- rights, voice/likeness, cultural-use, and public-media consent are checked
  before publication
- a source correction, expiry, or revocation invalidates or withdraws dependent
  presentation artifacts without rewriting historical evidence

The presentation layer may be delightful. It must not become a softer route
around registration, policy, custody, or evidence requirements.

## Shared Contract Profiles

Avoid creating a separate local-commerce runtime. Reuse existing primitives
through typed profiles and projections.

| Candidate profile | Existing SeedCore foundation | Purpose |
| --- | --- | --- |
| `AgriculturalBatchRegistrationV0` | `TrackingEvent` + `SourceRegistration` | represent a source-registered divisible lot |
| `BatchTransformationV0` | evidence refs + transition receipts | record split, merge, processing, packing, and quantity conservation |
| `CraftObjectRegistrationV0` | source registration + rare-shoe visual evidence | represent a singular maker-linked artifact |
| `WorkshopCustodyCaseV0` | RCT workflow + approval envelope + token constraints | bind intake, work scope, parts, operator, and return custody |
| `LocalProducerPresentationV0` | non-authoritative artifact refs | keep generated stories and 3D assets outside evidence |
| `VerifiedLocalProvenanceProjectionV0` | registration and replay read models | expose redacted claim state to discovery and public proof |

### VerifiedLocalProvenanceProjectionV0

```json
{
  "contract_version": "seedcore.verified_local_provenance_projection.v0",
  "projection_id": "local-proof:craft-001",
  "subject_ref": "asset:craft-001",
  "subject_kind": "singular_artifact",
  "producer_display": {
    "name": "Example Family Loom",
    "region": "public-region-ref"
  },
  "claim_states": [
    {
      "claim": "maker_identity",
      "status": "VERIFIED_FOR_CURRENT_PROFILE",
      "profile_ref": "policy:craft-registration:v0"
    },
    {
      "claim": "natural_dye_material",
      "status": "CLAIMED",
      "profile_ref": null
    }
  ],
  "current_verifier_disposition": "verified",
  "public_evidence_refs": ["public-proof:craft-001"],
  "presentation_refs": ["presentation:craft-001:en"],
  "presentation_is_authority": false,
  "updated_at": "2026-08-14T06:00:00Z"
}
```

This projection is receipt-derived and read-only. Discovery and presentation
services cannot modify its claim states or current verifier disposition.

## Stable Candidate Reason Codes

Existing SeedCore reason codes should be reused where they already express the
failure. New codes should be frozen only with fixtures and policy mappings.

| Candidate reason code | Default posture | Meaning |
| --- | --- | --- |
| `PRODUCER_CREDENTIAL_INVALID` | deny / review | producer or maker identity does not meet the selected profile |
| `SITE_CLAIM_UNVERIFIED` | review | site or origin claim lacks required admitted evidence |
| `CERTIFICATION_ISSUER_NOT_ADMITTED` | deny claim | external issuer is unknown, revoked, expired, or out of scope |
| `BATCH_QUANTITY_BALANCE_MISMATCH` | quarantine | parent, child, loss, or conversion quantity does not reconcile |
| `BATCH_LINEAGE_BROKEN` | quarantine | split, merge, processing, or package lineage is incomplete |
| `CROSS_BATCH_REPLAY` | deny | evidence from one lot, producer, or season is reused for another |
| `CRAFT_FINGERPRINT_MISMATCH` | quarantine | observed artifact contradicts the registered object baseline |
| `MAKER_CLAIM_CONTRADICTED` | reject / quarantine | evidence contradicts the declared maker relationship |
| `WORK_ORDER_SCOPE_EXCEEDED` | deny | requested workshop operation is outside approved scope |
| `IRREVERSIBLE_OPERATION_APPROVAL_MISSING` | deny | destructive or irreversible work lacks explicit approval |
| `REPLACEMENT_PART_PROVENANCE_MISSING` | deny / review | required replacement-part evidence is absent |
| `RETURN_RECIPIENT_MISMATCH` | deny | release or return recipient is outside the authorized scope |
| `PRESENTATION_EVIDENCE_BOUNDARY_VIOLATION` | quarantine | generated or edited presentation content entered an evidence path |
| `PUBLIC_PROJECTION_STALE` | review | discovery or public proof is older than the current registration/verifier state |

The outcome taxonomy must keep `deny`, `review_required`, `quarantine`, and
claim exclusion distinct. Failure to verify one marketing claim does not
necessarily prove the product is counterfeit, while a physical-asset mismatch
may require immediate quarantine.

## Negative And Replay Fixture Matrix

### Shared Fixtures

1. producer declaration without an admitted identity or organization credential
2. valid app-integrity assertion bound to the wrong registration or workflow
3. valid media manifest with a factually false producer claim
4. generated presentation frame inserted into a raw-evidence path
5. public projection remains verified after a later quarantine event
6. static QR copied onto another product
7. external certificate with valid signature but wrong batch or expired scope
8. valid evidence replayed across producer, asset, batch, season, or customer

### Agriculture Fixtures

1. happy-path micro-lot registration, packing split, release, and receipt
2. child package quantities exceed parent quantity tolerance
3. undeclared merge of two origins
4. missing process-loss evidence
5. laboratory result whose sample custody does not bind to the batch
6. stale or breached transit-temperature evidence
7. recalled or quarantined parent lot used to authorize child release

### Artisan Fixtures

1. happy-path one-of-one registration and delivery
2. same product class but different physical artifact
3. copied maker mark with mismatched visual fingerprint
4. material claim unsupported while object identity still matches
5. undeclared restoration between registration and sale
6. valid visual match combined with missing buyer approval or expired authority
7. AI-generated story introduces an unsupported maker or cultural claim

### Workshop Fixtures

1. happy-path intake, approved repair, inspection, return, and receipt
2. operation outside approved work scope
3. irreversible operation without step-up approval
4. spending limit exceeded
5. unassigned operator attempts work
6. replacement part lacks required provenance
7. wrong item or missing accessory at return
8. wrong return recipient
9. final inspection absent
10. AI diagnosis submitted as if it were customer approval

Offline replay should validate the exact recorded registrations, policy
snapshots, approvals, tokens, receipts, evidence refs, transformations, and
verifier outcomes. It should not need to rerun probabilistic vision, discovery,
translation, or narration models to reproduce the authority decision.

## Privacy, Cultural, And Producer Protections

Local-producer scenarios can create surveillance, bargaining-power, and
cultural-appropriation risks even when the cryptography is correct.

Required safeguards:

- do not publish precise private farm, home, workshop, or storage coordinates
  by default
- separate public region labels from authority-tier zone evidence
- obtain explicit rights for worker, family, child, voice, image, and workshop
  capture
- avoid continuous worker monitoring as a shortcut for craft-method proof
- allow producer review of public presentation while preserving immutable
  evidence and verifier history
- record who supplied cultural-origin claims and whether an admitted community
  or guild authority supports them
- do not infer ethnicity, gender, economic status, labor conditions, or land
  rights from imagery
- minimize dependence on expensive hardware and provide assisted/offline
  capture paths without weakening evidence labeling
- expose fees, data retention, dispute ownership, and quarantine consequences
  to producers before enrollment
- prevent discovery ranking from silently treating missing expensive evidence
  as lower product quality

Verification should reduce substitution and opaque custody without forcing
micro-producers to surrender unnecessary private data or platform control.

## Strict MVP Implementation Constraints

| Direction | Build now | Reject or defer |
| --- | --- | --- |
| Discovery router and MCP | stateless read-only router over static projections; exactly `/query`, `/projections/{id}`, and `/anchors/{ref}` plus three thin MCP tools | recommendation engine, real-time negotiation, multi-agent bidding, dynamic marketplace protocols |
| Low-tech producer ingest | exactly one image plus one audio clip into an expiring typed draft; source-linked extraction and explicit human confirmation | native merchant app, general document workflow, continuous IoT ingestion, automatic registration |
| Consumer proof | safely escaped server-rendered `/verify/{anchor_ref}` claim page with deterministic explanation; optional source-grounded story text and consented still/audio remain presentation-only | native tourist app, generated reel pipeline, synthetic voice, WebGL/WebGPU or 3D viewer, complex map client, agent-only experience |
| Economic integration | existing payment or escrow webhook may record a flat service charge for a completed verification/export/closure product | token-linked billing, custom settlement engine, crypto token, liquidity pool, or on-chain governance |

The operational sequence is:

```text
producer submits one field/product image + one voice memo
  -> seedcore.producer.draft_registration_from_media
  -> strict extraction into SourceRegistrationDraftV0
  -> producer reviews/corrects and explicitly confirms
  -> TrackingEvent first writes
  -> SourceRegistration projection
  -> RegistrationDecision under the registration workflow
  -> read-only VerifiedLocalProvenanceProjectionV0
  -> discovery router / MCP or public anchor lookup
  -> agent explanation or server-rendered /verify page

optional consequential commerce or custody step
  -> separate proposed ActionIntent
  -> PDP admission and scoped ExecutionToken or deny
  -> actuator attempt, receipt, evidence, and replay closure
```

There is no "PDP registration" step and no unified proof-and-commerce authority
button. Registration adjudication, proof reading, and consequential execution
remain distinct contracts.

### Strict Draft Input

The v0 media tool accepts:

- exactly one image artifact ref
- exactly one audio artifact ref
- producer or assisted-operator principal context
- selected registration profile
- locale and optional declared public region
- idempotency key

The extractor may propose batch id, declared origin text, production or craft
date, and quantity/volume only when each value links to the image, transcript,
or explicit caller declaration. Device geolocation is a separate observed
claim; it must not be inferred from scenery or narration and called verified
origin.

The Pydantic boundary validates the draft schema and rejects unknown fields. It
does not validate factual truth. Raw artifacts, transcript, extraction trace,
model/version, missing fields, conflicts, and confidence must remain linked to
the draft.

### Strict Economic Boundary

Existing payment or escrow webhooks may record that a fixed service product was
paid, such as an export verification bundle or completed RCT closure package.
Payment must not mint, purchase, widen, or extend an `ExecutionToken`, change a
PDP decision, suppress quarantine, or convert incomplete evidence into verified
state.

Billing integration is deferred until the read-only and ingestion MVPs are
validated. No crypto, custom escrow, automated liquidity, or on-chain
governance is part of this slice.

## Sustainable Commercial Model Hypotheses

SeedCore should test an accessible, low-toll business model without turning
public discovery into a marketplace commission or making payment settlement an
authority source.

### Public Discovery Plane

The public Projection Discovery API, proof pages, and basic MCP discovery tools
should target free end-user access under fair-use limits. Rate limiting, abuse
controls, caching, privacy protections, and service-cost budgets still apply;
"free" must not imply an unlimited or unauthenticated bulk-extraction right.

The objective is broad agent compatibility and direct producer discovery
without a percentage tax on ordinary local sales.

### Consequential Verification Or Closure Fee

A small fixed fee may be tested when SeedCore produces a commercially valuable
verification or closure artifact, such as:

- an export-grade batch release and custody bundle
- a high-value artisan RCT handoff
- an insured customer-property workshop case
- an enterprise compliance or audit package

This is a fee hypothesis for verification, evidence processing, or governed
closure. It is not a payment-settlement fee, legal-title transfer, percentage
commission, or authority decision. Example prices or value thresholds must
remain illustrative until partner interviews, support costs, regional
affordability, fraud exposure, and unit economics are measured.

Policy admission and verifier outcomes must never depend on whether a producer
buys a higher marketing tier. Required safety or evidence costs should be
transparent before enrollment.

### Cooperative Or Regional Tier

Agricultural cooperatives, artisan guilds, workshop networks, exporters,
hotels, or municipal tourism programs may fund:

- hosted producer onboarding and assisted intake
- batch or artifact management
- operator exception and dispute workflows
- private partner projection fields
- regional reporting and audit exports
- support, training, and hardware enrollment

The hosted tier pays for operational capability. It must not buy favorable
verification, ranking, issuer trust, quarantine release, or access to unrelated
producer data.

## Pilot Metrics

### Shared Metrics

- percentage of public claims with explicit `CLAIMED`, `REGISTERED`, verified,
  rejected, review, or quarantine state
- raw-to-derived artifact linkage completeness
- cross-asset and cross-batch replay rejection rate
- public projection freshness after state changes
- producer capture time and assisted-support burden
- producer draft confirmation, correction, abandonment, and extraction-error
  rates
- operator review and quarantine rate
- successful offline replay rate
- customer understanding of claim state versus presentation content
- public proof-page comprehension, localization, accessibility, and
  low-bandwidth completion
- REST/MCP parity for projection version, freshness, claim state, and source URL
- percentage of agent answers that preserve `as_of` and presentation-only labels
- zero cases where discovery, narration, or presentation output creates
  execution authority
- creative factual-sentence citation coverage and claim-state preservation
- producer approval, correction, withdrawal, and takedown turnaround for public
  creative artifacts
- synthetic-media disclosure, caption, transcript, no-script, and low-bandwidth
  completion rates
- zero generated awards, certifications, ingredients, health claims, custody
  facts, or cultural claims without eligible typed sources

### Agriculture Metrics

- batch split/merge quantity reconciliation
- missing or invalid issuer evidence rate
- pack-to-parent lineage completeness
- telemetry gap and receiving-condition exception rate
- cost per registered lot and child package

### Artisan Metrics

- same-object versus same-class/different-object separation
- insufficient visual coverage and recapture rate
- maker/material/process claim completeness by profile
- condition-drift and undeclared-modification detection
- high-value custody handoff closure rate

### Workshop Metrics

- operations attempted outside approved scope
- approval turnaround for price or irreversible-operation changes
- parts-provenance completeness
- intake/return identity and accessory reconciliation
- customer dispute and exception-resolution rate
- percentage of cases closed with complete inspection and receipt evidence

Pilot thresholds must be calibrated with representative participants and named
policy owners. Attractive showcase engagement is not a substitute for evidence
quality, negative-path safety, or replay completeness.

## Recommended Adoption Sequence

### Step 0: Preserve And Verify The Current Wedge

Complete the rare-shoe RCT visual evidence, Shopify-shaped adapter, NFC/KMS
transition, policy, token, verification, and replay gates. Do not begin three
new production verticals simultaneously.

Exit condition:

- focused RCT and commerce contract checks remain green
- the discovery work introduces no write or alternate authority path

### Step 1: Freeze The Read-Only Projection Contract

Freeze `VerifiedLocalProvenanceProjectionV0`, claim-state vocabulary, freshness,
redaction, pagination, source links, public anchors, and structured explanation
responses before adding semantic search.

Exit condition:

- deterministic fixtures cover current, stale, rejected, review, quarantined,
  partial-claim, and presentation-only projections
- public and partner read scopes are explicit

### Step 2: Implement The Discovery Router And MCP Tools

Candidate first code slice:

- add `src/seedcore/api/routers/discovery_router.py`
- register it in `src/seedcore/api/routers/__init__.py`
- `POST /api/v1/discovery/query`
- `GET /api/v1/discovery/projections/{projection_id}`
- `GET /api/v1/discovery/anchors/{public_anchor_ref}`
- add runtime client methods in `src/seedcore/plugin/runtime_client.py`
- add tool names and thin wrappers in `src/seedcore/plugin/mcp_server.py`
- `seedcore.discovery.search`
- `seedcore.discovery.get_projection`
- `seedcore.discovery.explain_claim_state`

The router should initially query deterministic fixture or existing read-model
data through an allowlisted filter grammar and stable ordering. Semantic
ranking, recommendation, negotiation, and bidding are deferred beyond MVP.

Exit condition:

- every endpoint is demonstrably read-only
- prompt-injection and stale-cache fixtures preserve tool/action separation
- MCP and REST results agree on projection version and claim state
- router-registry and plugin tool-name tests cover the new surfaces
- the existing Gemini minimal read-only bundle is not widened implicitly; host
  exposure is a separate packaging decision after contract checks

### Step 3: Build Accessible Ingestion And Public Proof Adapters

- implement `SourceRegistrationDraftV0`
- place the draft contract with the existing source-registration models in
  `src/seedcore/models/source_registration.py`
- add a SeedCore-owned adapter under `src/seedcore/adapters/`
- add `seedcore.producer.draft_registration_from_media` as a draft-only helper
- constrain the draft helper to exactly one image and one audio clip
- create a safely escaped, server-rendered, low-bandwidth
  `/verify/{public_anchor_ref}` proof-page template
- require explicit producer/operator confirmation before governed first writes
- preserve declared, inferred, translated, and verified states separately
- reserve a presentation-only slot for source-grounded story text; keep it off
  by default until its artifact, citation, consent, and withdrawal contract is
  fixture-tested

Exit condition:

- media extraction cannot auto-confirm or produce a registration decision
- the public page is usable without an AI host and exposes partial/stale states
- static QR resolution is never described as clone-resistant physical proof
- the page requires no native app, client JavaScript, 3D renderer, or map stack
- extraction, confirmation, escaping/XSS, stale projection, missing media, and
  conflicting-field fixtures cover the negative paths

### Step 3A: Pilot The Grounded Creative Sidecar

This is a presentation experiment after Step 3, not a prerequisite for public
proof or a new authority service.

- freeze `GroundedCreativeArtifactV0` and source-span citation semantics
- begin with producer-approved text and one existing still or audio excerpt
- label `Artisan Story & Lore`, `Producer-Declared Details`, and
  `Verified Origins` as separate semantic regions
- add grounding, consent, redaction, impersonation, cultural-safety, expiry,
  correction, and withdrawal fixtures
- require deterministic fallback to the ordinary proof card
- evaluate a captioned comic or short pre-rendered reel only after the text
  pilot passes comprehension and false-claim thresholds

Exit condition:

- every factual story sentence maps to a typed source and preserves claim state
- generated media never enters evidence, fingerprint, PDP, or verifier inputs
- a stale/revoked projection withdraws or marks dependent stories stale
- producer and consumer testing confirms humor does not hide partial or adverse
  proof state

### Step 4: Package Vendor-Neutral Agent Integrations

- publish one canonical MCP server/package for the discovery tools
- provide host-specific manifests and examples for Codex, Gemini, and other
  compatible agent ecosystems
- provide TypeScript/Python SDK examples over the same API
- document endpoint trust, auth scopes, rate limits, freshness, and source URLs

Exit condition:

- host adapters do not maintain separate verification truth
- adding a new host requires no new policy or projection implementation
- discovery skills cannot silently invoke action tools

### Step 5: Activate One Scenario Fixture At A Time

1. agricultural registration and one split/pack transformation
2. one-of-one artisan transfer reusing rare-shoe visual/RCT contracts
3. workshop intake, bounded work, inspection, and return custody

Each scenario needs a separate reviewed activation decision. The fastest
source-registration reuse is the agricultural lot. The fastest RCT transfer
reuse is the one-of-one artisan object. The strongest proof that SeedCore
generalizes beyond trade is the customer-owned workshop custody case.

## Explicit Non-Goals

- no generic local-commerce marketplace
- no assumption that frontier-agent distribution eliminates the need for a
  canonical accessible proof page, producer confirmation, or operator support
- no global tourism or Journey 4Map platform
- no single numerical provenance score
- no SeedCore-issued organic, fair-trade, cultural, land-title, or maker claim
  without an explicit admitted issuer and policy profile
- no assumption that DID, GPS, App Attest, C2PA, QR, NFC UID, 3D model, or AI
  confidence proves physical truth by itself
- no continuous worker or family surveillance
- no generated pixels or narration in forensic evidence
- no undisclosed synthetic voice, invented real-person dialogue, or generated
  factual/cultural claim in public presentation
- no discovery model, product card, booking, or ordinary checkout minting an
  `ExecutionToken`
- no MCP tool, plugin, skill, or agent-specific adapter maintaining a separate
  verification truth or silently crossing from exploration into action
- no registration approval automatically authorizing packing, export, work,
  release, settlement, or custody closure
- no committed public pricing, value threshold, or fee schedule before partner
  and unit-economic validation
- no payment webhook buying, minting, extending, or otherwise affecting
  execution authority
- no legal-title or payment-settlement assertion in the current RCT baseline
- no displacement of the rare-shoe RCT must-win application

## Acceptance Criteria

This scenario expansion is ready to influence implementation only when:

1. batch, artifact, and work-order semantics remain separate profiles over the
   existing governed runtime
2. `TrackingEvent` remains the first write for source-registration evidence
3. registration decisions remain separate from action admission and execution
4. every consequential action maps to an accountable principal, typed
   `ActionIntent`, pinned policy, scoped token, evidence, receipt, and replay
5. presentation, discovery, and generated content remain non-authoritative
6. public projections state exactly which claim and policy profile is current
7. batch splits, merges, losses, and transformations preserve auditable lineage
8. artisan substitution, tag swap, condition drift, and unsupported maker
   claims have distinct outcomes
9. workshop scope, price, irreversible operations, parts, operators, and return
   recipients are explicitly constrained
10. negative fixtures prove stale, missing, replayed, cross-bound, generated,
    and out-of-scope inputs fail safely
11. privacy, cultural authority, producer cost, and dispute ownership have named
    human owners
12. activation of any pilot is a separate reviewed decision and does not imply
    activation of the other scenarios
13. media-first ingestion produces an expiring source-linked draft and requires
    explicit producer or authorized-operator confirmation
14. public proof remains understandable and accessible without an AI agent or
    plugin
15. MCP, plugin, skill, and SDK discovery clients preserve current projection
    state and cannot silently invoke action tools
16. commercial tiers cannot buy favorable ranking, verification, policy,
    quarantine release, or access to unrelated producer data
17. creative artifacts preserve sentence-level source and claim-state labels,
    explicit synthetic-media disclosure, consent, and withdrawal behavior
18. humor, narrative, and rich media remain optional and cannot obscure or
    replace the deterministic proof experience

## Related SeedCore Docs

- [`README.md`](README.md)
- [`current_next_steps.md`](current_next_steps.md)
- [`source_registration_architecture.md`](source_registration_architecture.md)
- [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md)
- [`rare_shoe_rct_visual_evidence_adapter_v0.md`](rare_shoe_rct_visual_evidence_adapter_v0.md)
- [`second_hand_luxury_trade_evolution.md`](second_hand_luxury_trade_evolution.md)
- [`immersive_commerce_and_governed_trade_architecture.md`](immersive_commerce_and_governed_trade_architecture.md)
- [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md)
- [`physical_telemetry_processing_contract.md`](physical_telemetry_processing_contract.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md)
- [`owner_creator_external_sdk_and_plugin_surface.md`](owner_creator_external_sdk_and_plugin_surface.md)
