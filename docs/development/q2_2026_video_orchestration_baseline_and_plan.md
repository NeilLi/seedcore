# Q2 2026 Video Orchestration Extension Baseline And Plan

Date: 2026-05-14
Status: Public extension plan aligned with SeedCore's governed execution focus

## Purpose

This note translates the SeedCore Video Orchestration direction into an
engineering extension plan using the repository as it exists now.

This plan is scoped as an extension of SeedCore's primary governed execution
runtime direction. The current flagship workflow remains **Restricted Custody
Transfer**, while video/media orchestration demonstrates how the same trust
runtime can extend to media-heavy autonomous workflows.

Video/media orchestration should currently be treated as:

- proof of extensibility
- a future vertical
- a useful evidence modality
- a secondary demonstration that the same trust runtime can govern media-heavy
  workflows

The intent is continuity: media orchestration is an extension surface for the
trust runtime, not a separate product category.

The engineering strategy is intentionally conservative: if this track is
activated, build the verifiable media custody and discovery substrate first,
then attach richer temporal comprehension later. The autonomous "Story Graph"
is treated as a later-stage capability built on top of verifiable media
custody.

## Strategic Positioning

SeedCore's public category is a governed execution runtime for autonomous
systems. It sits between AI intent and real-world execution, issuing bounded
authority and producing replayable proof that the action was authorized,
executed, and closed under policy.

Core positioning:

```text
SeedCore is a governed execution runtime for autonomous systems.
```

Near-term execution story:

```text
AI requested action
  -> SeedCore policy checks
  -> delegated authorization
  -> controlled execution
  -> evidence sealing
  -> replayable proof
```

The flagship demo remains **Restricted Custody Transfer**, especially the
autonomous repair / high-trust handoff scenario. Video becomes one possible
evidence and orchestration extension after that story is tight.

## Current Baseline

The current development center is still the commerce Restricted Custody
Transfer wedge, not video orchestration. The relevant reusable baseline is the
trust runtime around custody, governed ingress, evidence, replay, Ray, and
deployment validation.

Already present and reusable:

- Ray / KubeRay deployment is a real runtime substrate. The Q2 docs record a
  green remote Kind topology for API, Ray/KubeRay, ingress, HAL simulation,
  Redis resilience, and hot-path observability in
  [`kube_topology_validation_q2_signoff.md`](kube_topology_validation_q2_signoff.md).
- PostgreSQL is the authoritative metadata store for the active trust slice.
  Source registration, tracking events, custody state, verifier jobs, audit
  records, and result-verifier state all already use Postgres-backed models and
  migrations.
- Governed ingress exists through `TrackingEvent`. The source-registration
  path already treats immutable events as the first write, projects them into a
  stable domain aggregate, and stores SHA-256 hashes for event payloads and
  artifacts.
- Source registration is the closest current analog to video custody. It has
  `SourceRegistration`, `TrackingEvent`, `SourceRegistrationArtifact`,
  `SourceRegistrationMeasurement`, and `RegistrationDecision`, plus app-facing
  routes and a normalizer/projector path.
- Evidence bundles and HAL capture envelopes already support `media_refs`.
  These are currently references, not a complete media ledger, but they give
  the proof surface a place to bind video/image hashes into replayable
  artifacts.
- The result verifier, replay service, verification API, runbook lookup, and
  operator console contracts already establish the rule that proof must survive
  replay and adversarial inspection.
- Kafka is planned and partially implemented as transport/observability, not
  authority. Local topics and optional publishers exist, but Kafka is not yet
  the source of truth for evidence.

Planned extension work:

- define a first-class `RawVideoAsset` / media ledger aggregate
- add an object-storage adapter and bucket policy contract for raw video, proxy
  renditions, thumbnails, clips, and transcript artifacts
- implement streaming binary hashing so SeedCore can compute SHA-256 while
  accepting large video uploads
- add a video-specific ingestion job model for Ray workers
- add media segment, keyframe, transcript, and scene-index tables
- bind legal-rights and usage-rights metadata to media assets
- expose a video-discovery API and read model
- defer Story Graph persistence until the verifiable media ledger is stable
- capture topology signoff for large media ingestion under Kubernetes/Ray

## Planning Implication

Video orchestration should build on the existing trust/runtime spine:

```text
object storage bytes
  -> hash-addressed RawVideoAsset
  -> governed TrackingEvent stream
  -> Postgres media ledger projection
  -> Ray ingestion jobs
  -> EvidenceBundle / verification read surface
  -> discovery index
```

The Q2 deliverable should be a trustworthy media ledger and ingestion path, not
autonomous narrative understanding.

Product implication:

- RCT is the buyer-facing wedge.
- Video is an expansion proof.
- Media custody should be explained as another case where autonomous systems
  need authorized, replayable, auditable execution.
- The media plan should reinforce the current RCT roadmap and demo story.

## Readiness Criteria Before Active Video Work

The video track is most useful once these foundations are in place:

1. The Restricted Custody Transfer demo is polished enough to show in under
   five minutes.
2. The product narrative can be stated in one sentence:

   ```text
   We prevent autonomous systems from operating without accountable
   authorization and verifiable closure.
   ```

3. The demo package has a clear buyer, workflow, and pain statement.
4. The verification surface can show request, authority, execution evidence,
   and replay outcome without source-code explanation.
5. At least one pilot-style conversation is in motion around governed
   autonomous execution, high-trust handoff, robotics/logistics, controlled
   inventory movement, or enterprise automation.

Until these criteria are satisfied, this document is best read as an
implementation-ready extension plan rather than the active critical path.

## Extension Goal

When activated, this track should prove that SeedCore can ingest a video, prove
the exact bytes that entered the system, record provenance and rights metadata,
run a Ray-managed processing workflow, and expose a replayable operator/read API
for the resulting media artifacts.

Success means an operator can answer:

- what video was ingested
- who or what submitted it
- where the raw and proxy assets live
- what SHA-256 hashes bind the raw file and derived artifacts
- what rights and retention constraints apply
- what processing jobs ran
- whether the media ledger projection matches the immutable ingress evidence

## Phase 1: Custody And Ingestion Engine

Target window: after the RCT demo package is stable

Goal: establish the Verifiable Media Ledger and high-speed ingestion pipeline.

### 1. Contract Freeze

Create a minimal media custody contract before implementation spreads across
the repo.

Proposed domain objects:

- `RawVideoAsset`
  - `asset_id`
  - `source_ref`
  - `owner_ref`
  - `submitted_by`
  - `raw_uri`
  - `raw_sha256`
  - `byte_size`
  - `content_type`
  - `duration_ms`
  - `codec_summary`
  - `status`
  - `rights_profile_id`
  - `retention_policy_id`
  - `created_at`
  - `updated_at`
- `MediaArtifact`
  - `artifact_id`
  - `asset_id`
  - `artifact_type`
  - `uri`
  - `sha256`
  - `byte_size`
  - `content_type`
  - `derivation`
  - `created_by_job_id`
- `MediaRightsProfile`
  - `rights_profile_id`
  - `owner_ref`
  - `license_scope`
  - `allowed_uses`
  - `restricted_uses`
  - `expires_at`
  - `policy_snapshot_id`
- `VideoIngestionJob`
  - `job_id`
  - `asset_id`
  - `workflow`
  - `status`
  - `ray_task_ref`
  - `started_at`
  - `completed_at`
  - `failure_reason`

Status vocabulary:

- `received`
- `hashing`
- `registered`
- `processing`
- `ready`
- `quarantined`
- `rejected`

### 2. Storage Boundary

Add a small storage abstraction before binding to one cloud provider.

Required behavior:

- write raw bytes to object storage or local dev storage
- compute SHA-256 from the accepted byte stream
- reject mismatched caller-provided hashes
- store raw, proxy, thumbnail, transcript, and derived JSON artifacts under
  deterministic object prefixes
- keep Postgres as metadata truth and object storage as byte truth

Suggested local URI shape:

```text
s3://seedcore-media/raw/{asset_id}/source
s3://seedcore-media/proxy/{asset_id}/proxy.mp4
s3://seedcore-media/keyframes/{asset_id}/{frame_id}.jpg
s3://seedcore-media/metadata/{asset_id}/ffprobe.json
```

Development can start with local filesystem or MinIO-compatible storage, but
the contract should use object-storage semantics from the beginning.

### 3. Governed Ingress

Reuse the current TrackingEvent-first approach.

Add video-oriented event types or map them through a new media aggregate:

- `raw_video_received`
- `raw_video_hash_computed`
- `media_rights_declared`
- `proxy_asset_created`
- `keyframe_extracted`
- `transcript_created`
- `scene_index_created`
- `video_ingestion_failed`

Each event should carry:

- stable `asset_id`
- `uri`
- SHA-256 where applicable
- device / submitter / owner references
- correlation id
- policy snapshot id where rights or governance checks are involved

This mirrors source registration: the event stream is the first write, and the
media ledger is a projection.

### 4. Ray Processing Workflow

Use Ray for long-running and parallel media jobs, but keep the authoritative
ledger in Postgres.

Initial Ray workflow:

1. claim a `VideoIngestionJob`
2. run metadata extraction (`ffprobe` or equivalent)
3. produce proxy rendition
4. extract sparse keyframes
5. create low-risk discovery metadata
6. persist `MediaArtifact` rows and tracking events
7. mark the asset `ready` or `quarantined`

The Ray worker should be idempotent by `asset_id` + source hash. Re-running a
job against the same raw hash must not duplicate artifacts.

### 5. Verification Surface

Add only read-side verification in Q2.

Minimal endpoints:

- `POST /api/v1/media-assets`
- `GET /api/v1/media-assets/{asset_id}`
- `GET /api/v1/media-assets/{asset_id}/ledger`
- `GET /api/v1/media-assets/{asset_id}/artifacts`
- `GET /api/v1/media-assets/{asset_id}/verification`

Verification response should include:

- raw hash status
- artifact hash status
- event-chain summary
- rights profile summary
- processing job summary
- replay or runbook links for mismatch/quarantine

External agent access should remain read-only in this phase, following the
same rule used for the current Gemini-visible verification bundle.

## Discovery Layer Scope

Discovery should be intentionally modest:

- searchable title / filename / owner / submitter / tags
- duration, codec, resolution, ingest timestamp
- keyframe references
- transcript reference if produced
- scene summary as an artifact, not as authority

Out of scope for this extension phase:

- autonomous Story Graph
- cross-video narrative inference
- automated legal-rights interpretation
- settlement or release decisions based on video semantics

## Acceptance Criteria

The video custody slice is acceptable when:

- a raw video can be ingested through a local/dev API without loading the full
  file into memory
- SHA-256 is computed by SeedCore and stored on the ledger
- a caller-provided hash mismatch is rejected or quarantined
- raw/proxy/keyframe/metadata artifacts are stored with stable URIs and hashes
- a Ray ingestion job can be retried without duplicate artifacts
- Postgres migrations create the media ledger tables
- `GET /media-assets/{asset_id}/verification` can explain the asset state from
  ledger rows and tracking events
- at least one fixture proves raw ingest -> Ray processing -> ledger projection
  -> verification readback
- the docs explicitly state that media events and ledger rows are evidence
  inputs, not policy authority by themselves

These criteria should reinforce the central SeedCore claim:

```text
SeedCore governs autonomous execution and proves closure.
```

## Work Plan

### Stage 0: RCT Demo And Market Focus

Recommended preparation before active video implementation:

- tighten the Restricted Custody Transfer demo around one clear scene:
  autonomous repair transfer, robotics handoff, warehouse transfer, controlled
  inventory movement, or another high-trust workflow
- produce a concise external narrative:
  problem, wedge, product, demo proof, expansion path
- define one buyer, one workflow, and one measurable pain
- frame SeedCore as a governed execution runtime rather than a generic agent
  framework
- use video/media only as an expansion proof in the final slide or appendix

### Stage 1: Baseline Contract

- Freeze the media-ledger schema and status vocabulary.
- Decide whether `RawVideoAsset` is a new aggregate or a specialization of the
  source-registration artifact model. Recommendation: new aggregate, because
  raw video lifecycle, proxy derivation, retention, and rights are materially
  different from source-registration evidence.
- Add a short ADR or development note tying video custody to the existing
  tracking-event and evidence-bundle model.

### Stage 2: Storage And Hashing

- Add the storage adapter interface.
- Implement local filesystem or MinIO-compatible dev storage.
- Implement streaming SHA-256 computation.
- Add mismatch behavior and tests.

### Stage 3: Postgres Ledger

- Add migrations and SQLAlchemy models for raw video assets, media artifacts,
  media rights profiles, and ingestion jobs.
- Add projection helpers from video tracking events to media ledger rows.
- Add idempotency constraints around `asset_id`, `raw_sha256`, and derived
  artifact hash.

### Stage 4: API Slice

- Add create/read endpoints for media assets.
- Add artifact and ledger read endpoints.
- Keep write-side scope narrow: ingest/register only.
- Add contract tests and fixture payloads.

### Stage 5: Ray Ingestion Worker

- Add a Ray-backed ingestion job runner.
- Produce metadata artifact first; proxy/keyframes can follow behind feature
  flags if local tooling varies.
- Persist job transitions as governed tracking events.

### Stage 6: Verification Readback

- Add the media verification endpoint.
- Bind media refs into `EvidenceBundle.media_refs` for at least one fixture.
- Add mismatch/quarantine runbook entries for hash mismatch, missing object,
  and derived artifact drift.

### Stage 7: Discovery Index

- Add a read model for basic search/filter.
- Index only deterministic metadata and references to derived artifacts.
- Keep scene summaries and transcripts as non-authoritative artifacts.

### Stage 8: Topology Drill

- Run the slice in the existing local or Kind topology.
- Capture evidence for ingest, processing retry, hash mismatch, and object
  missing/quarantine cases.
- Record which parts are topology-green and which remain local-only.

## Risks

- Large-file ingest can accidentally bypass the trust model if uploads are
  treated as generic task payloads. Keep binary bytes outside `tasks.params`.
- Object storage can become an unverified blob bucket unless every artifact is
  hash-bound and projected into Postgres.
- Ray can process media quickly, but Ray task state must not become authority.
  The ledger and tracking events remain the source of truth.
- Story Graph work can consume the quarter. Keep temporal comprehension as a
  later consumer of the verifiable media ledger.
- Rights metadata is easy to under-model. Even a small `MediaRightsProfile` is
  better than treating legal rights as free-form metadata.
- Category clarity is important. This track should be presented as an extension
  of the trust runtime, not as a standalone media product.

## Recommended Next Implementation Slice

Start here after Stage 0 is satisfied.

If the video extension becomes useful for a demo, start with the smallest
vertical:

1. `RawVideoAsset` + `MediaArtifact` models and migration
2. local storage adapter with streaming SHA-256
3. `POST /api/v1/media-assets` ingest/register endpoint
4. `GET /api/v1/media-assets/{asset_id}/verification`
5. one Ray job that extracts metadata and records a derived artifact

That slice proves the custody and ingestion engine without committing the team
to full video understanding or Story Graph autonomy in Q2.

## Public Narrative Usage

Use this plan as an extension note once the core wedge is established.

Primary SeedCore sentence:

```text
SeedCore is a governed execution runtime for autonomous systems.
```

Video extension sentence:

```text
The same runtime can also govern media-heavy workflows by making raw video,
derived artifacts, and discovery outputs hash-bound, rights-aware, and
replay-verifiable.
```

Category clarification:

```text
Media orchestration is one future vertical for the same trust runtime.
```
