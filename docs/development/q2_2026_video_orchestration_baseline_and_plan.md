# Q2 2026 Video Orchestration Baseline And Plan

Date: 2026-05-14
Status: Draft plan grounded in the current `docs/development/` baseline

## Purpose

This note translates the SeedCore Video Orchestration direction into a Q2
engineering plan using the repository as it exists now.

The strategy is intentionally conservative: build the verifiable media custody
and discovery substrate first, then attach richer temporal comprehension later.
The autonomous "Story Graph" should not become the Q2 critical path.

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

What is not yet present:

- no first-class `RawVideoAsset` / media ledger aggregate
- no object-storage adapter or bucket policy contract specifically for raw
  video, proxy renditions, thumbnails, clips, or transcript artifacts
- no streaming binary hash workflow that computes SHA-256 while accepting large
  video uploads
- no video-specific ingestion job model for Ray workers
- no media segment / keyframe / transcript / scene table
- no legal-rights or usage-rights model tied to media assets
- no video-discovery API or read model
- no Story Graph persistence contract
- no topology signoff proving large media ingestion under Kubernetes/Ray

## Planning Implication

Do not build video orchestration as a separate product surface in Q2. Build it
as a bounded sidecar on the existing trust/runtime spine:

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

## Q2 Goal

By the end of Q2, SeedCore should be able to ingest a video, prove the exact
bytes that entered the system, record provenance and rights metadata, run a
Ray-managed processing workflow, and expose a replayable operator/read API for
the resulting media artifacts.

Success means an operator can answer:

- what video was ingested
- who or what submitted it
- where the raw and proxy assets live
- what SHA-256 hashes bind the raw file and derived artifacts
- what rights and retention constraints apply
- what processing jobs ran
- whether the media ledger projection matches the immutable ingress evidence

## Phase 1: Custody And Ingestion Engine

Target window: mid-May through June 2026

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

Do not expose mutation/control tools to external agents in Q2. Follow the same
read-only rule used for the current Gemini-visible verification bundle.

## Discovery Layer Scope

Q2 discovery should be intentionally modest:

- searchable title / filename / owner / submitter / tags
- duration, codec, resolution, ingest timestamp
- keyframe references
- transcript reference if produced
- scene summary as an artifact, not as authority

Out of scope for Q2:

- autonomous Story Graph
- cross-video narrative inference
- automated legal-rights interpretation
- settlement or release decisions based on video semantics

## Acceptance Criteria

The Q2 video custody slice is acceptable when:

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

## Work Plan

### Week 1: Baseline Contract

- Freeze the media-ledger schema and status vocabulary.
- Decide whether `RawVideoAsset` is a new aggregate or a specialization of the
  source-registration artifact model. Recommendation: new aggregate, because
  raw video lifecycle, proxy derivation, retention, and rights are materially
  different from source-registration evidence.
- Add a short ADR or development note tying video custody to the existing
  tracking-event and evidence-bundle model.

### Week 2: Storage And Hashing

- Add the storage adapter interface.
- Implement local filesystem or MinIO-compatible dev storage.
- Implement streaming SHA-256 computation.
- Add mismatch behavior and tests.

### Week 3: Postgres Ledger

- Add migrations and SQLAlchemy models for raw video assets, media artifacts,
  media rights profiles, and ingestion jobs.
- Add projection helpers from video tracking events to media ledger rows.
- Add idempotency constraints around `asset_id`, `raw_sha256`, and derived
  artifact hash.

### Week 4: API Slice

- Add create/read endpoints for media assets.
- Add artifact and ledger read endpoints.
- Keep write-side scope narrow: ingest/register only.
- Add contract tests and fixture payloads.

### Week 5: Ray Ingestion Worker

- Add a Ray-backed ingestion job runner.
- Produce metadata artifact first; proxy/keyframes can follow behind feature
  flags if local tooling varies.
- Persist job transitions as governed tracking events.

### Week 6: Verification Readback

- Add the media verification endpoint.
- Bind media refs into `EvidenceBundle.media_refs` for at least one fixture.
- Add mismatch/quarantine runbook entries for hash mismatch, missing object,
  and derived artifact drift.

### Week 7: Discovery Index

- Add a read model for basic search/filter.
- Index only deterministic metadata and references to derived artifacts.
- Keep scene summaries and transcripts as non-authoritative artifacts.

### Week 8: Topology Drill

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

## Recommended Next Implementation Slice

Start with the smallest vertical:

1. `RawVideoAsset` + `MediaArtifact` models and migration
2. local storage adapter with streaming SHA-256
3. `POST /api/v1/media-assets` ingest/register endpoint
4. `GET /api/v1/media-assets/{asset_id}/verification`
5. one Ray job that extracts metadata and records a derived artifact

That slice proves the custody and ingestion engine without committing the team
to full video understanding or Story Graph autonomy in Q2.
