# Source Registration Architecture

This note maps a high-authority honey-origin registration workflow onto the current SeedCore architecture.

## Goal

Support an app-layer feature where a source claim is not a plain form submit. It is a governed registration flow that:

- ingests visual provenance from high-resolution honeycomb and seal imagery
- ingests environmental telemetry from the collection site
- ingests chemical and spectroscopic bio-signatures
- evaluates the claim against policy and grading rules
- produces a replayable registration record before any downstream packing or release step

## Normalization Baseline

The current baseline should match the governed ingress model described in [source-registration-events.md](/Users/ningli/project/seedcore/docs/references/source-registration-events.md).

SeedCore normalizes source declarations, vision scans, seal checks, environmental readings, and operator commands into one governed `TrackingEvent` stream before planning begins.

That means the normalization component is not only a parser. It is the ingress layer that:

- captures immutable `TrackingEvent` records
- projects those events into `SourceRegistration`
- prepares deterministic attributes for policy and planning
- calls the cognitive service as a core capability for semantic refinement, multimodal interpretation, and conflict resolution during normalization

`SourceRegistration` remains the app-facing aggregate, but it is no longer the first write.

## Current SeedCore Fit

The current framework already provides most of the runtime skeleton:

- API ingress persists tasks as a thin pipe in [src/seedcore/api/routers/tasks_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/tasks_router.py)
- governed ingress for tracking events already exists in [src/seedcore/api/routers/tracking_events_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/tracking_events_router.py)
- `SourceRegistration` projection logic already exists in [src/seedcore/ops/source_registration/projector.py](/Users/ningli/project/seedcore/src/seedcore/ops/source_registration/projector.py)
- `TaskPayload` already carries multimodal and routing metadata in [src/seedcore/models/task_payload.py](/Users/ningli/project/seedcore/src/seedcore/models/task_payload.py)
- the coordinator already refines `params.multimodal`, calls Eventizer, and persists multimodal context in [src/seedcore/services/coordinator_service.py](/Users/ningli/project/seedcore/src/seedcore/services/coordinator_service.py)
- deterministic normalization and multimodal refinement already exist in [src/seedcore/services/eventizer_service.py](/Users/ningli/project/seedcore/src/seedcore/services/eventizer_service.py)
- cognitive reasoning and semantic enrichment already exist in [src/seedcore/services/cognitive_service.py](/Users/ningli/project/seedcore/src/seedcore/services/cognitive_service.py)
- governed fact persistence already exists in [src/seedcore/services/fact_service.py](/Users/ningli/project/seedcore/src/seedcore/services/fact_service.py)
- audit evidence already exists through `EvidenceBundle` in [src/seedcore/models/evidence_bundle.py](/Users/ningli/project/seedcore/src/seedcore/models/evidence_bundle.py)
- snapshot-scoped policy evaluation already exists through PKG and `snapshot_id`

The gap is not orchestration. The gap is consolidating the new event-stream-first baseline into a clear domain contract. Today the runtime can accept multimodal payloads and governed tracking events, but the app layer and planning layer still need one explicit normalization story that ties `TrackingEvent`, `SourceRegistration`, Eventizer, and cognitive service together.

## Recommendation

Do not build this as a special front-end-only workflow.

Build it as a first-class governed domain flow:

1. App layer emits source declarations, scans, readings, and operator commands as governed `TrackingEvent`s
2. SeedCore persists the append-only event stream as the first write
3. SeedCore projects the stream into `SourceRegistration` as the app-facing aggregate
4. The normalization component enriches the projected state with deterministic parsing plus cognitive service interpretation
5. Coordinator runs a policy-backed registration workflow on that normalized projection
6. Facts, evidence, and verdicts are persisted as the system of record
7. Packing-line release remains a later `ActionIntent` step, not part of registration itself

## Architectural Change

Retain `SourceRegistration` as the domain aggregate, but make `TrackingEvent` the first write.

This should be separate from `Task`.

- `Task` remains the orchestration envelope
- `TrackingEvent` becomes the governed ingress log
- `SourceRegistration` becomes the projected app-facing system of record

That split matters because the app needs a stable object whose lifecycle is:

- `draft`
- `ingesting`
- `verifying`
- `approved`
- `quarantined`
- `rejected`

`Task` does not model that lifecycle well enough on its own, and `SourceRegistration` should not be overloaded to act like the raw ingress log.

## Proposed Domain Model

### 1. SourceRegistration

Suggested fields:

- `registration_id`
- `source_claim_id`
- `lot_id`
- `producer_id`
- `rare_grade_profile_id`
- `status`
- `claimed_origin`
- `collection_site`
- `collected_at`
- `snapshot_id`
- `created_at`
- `updated_at`

### 2. SourceRegistrationArtifacts

Each artifact is append-only and hash-addressed.

Suggested fields:

- `artifact_id`
- `registration_id`
- `artifact_type`
- `uri`
- `sha256`
- `captured_at`
- `captured_by`
- `device_id`
- `content_type`
- `metadata`

Artifact types:

- `honeycomb_macro_image`
- `seal_macro_image`
- `environment_telemetry_batch`
- `gps_fix`
- `spectroscopy_scan`
- `pollen_analysis`
- `purity_analysis`

### 3. SourceRegistrationMeasurements

Normalize high-value measurements instead of burying them only in JSON.

Suggested fields:

- `registration_id`
- `measurement_type`
- `value`
- `unit`
- `measured_at`
- `sensor_id`
- `quality_score`
- `raw_artifact_id`

Measurement types:

- `oxygen_level`
- `humidity`
- `altitude_meters`
- `latitude`
- `longitude`
- `pollen_count`
- `purity_score`
- `spectral_match_score`

### 4. SourceRegistrationVerdict

Persist the result of registration governance as a distinct record.

Suggested fields:

- `registration_id`
- `decision`
- `grade_result`
- `confidence`
- `policy_snapshot_id`
- `rule_trace`
- `reason_codes`
- `decided_at`

## TaskPayload Extension

Add a dedicated envelope under `params.source_registration`.

Do not overload generic `params.multimodal` as the only source of truth.

When a task is created from the registration flow, it should reference the normalized event stream and the projected aggregate together.

Recommended shape:

```json
{
  "type": "registration",
  "domain": "provenance",
  "params": {
    "source_registration": {
      "registration_id": "uuid",
      "ingress_event_ids": ["evt-1", "evt-2"],
      "claim_kind": "origin_ritual",
      "producer_id": "string",
      "lot_id": "string",
      "rare_grade_profile_id": "string",
      "claimed_origin": {
        "zone_id": "string",
        "site_id": "string",
        "altitude_meters": 2430
      },
      "artifacts": [
        {
          "artifact_type": "honeycomb_macro_image",
          "uri": "s3://...",
          "sha256": "..."
        }
      ],
      "measurements": {
        "oxygen_level": {"value": 18.4, "unit": "percent"},
        "humidity": {"value": 67.2, "unit": "percent"},
        "gps": {"lat": 18.801, "lon": 98.921, "altitude_meters": 2438.7},
        "pollen_count": {"value": 184000, "unit": "ppm"},
        "purity_score": {"value": 0.992, "unit": "ratio"},
        "spectral_match_score": {"value": 0.961, "unit": "ratio"}
      },
      "normalization": {
        "source": "tracking_event_projection",
        "stream_kinds": [
          "source_declaration",
          "provenance_scan",
          "telemetry",
          "operator_request"
        ],
        "cognitive_enrichment_required": true
      }
    },
    "multimodal": {},
    "governance": {
      "workflow": "source_registration",
      "require_registration_verdict": true
    }
  }
}
```

Why:

- app layer gets a stable contract
- planning can trace every projected field back to immutable ingress events
- coordinator keeps using the existing task pipeline
- multimodal processing still works, but now as a child of a governed aggregate projection
- cognitive service is explicitly part of normalization instead of being treated as a late-stage optional add-on

## Governance Model

Do not force source registration through the current `ActionIntent` contract.

`ActionIntent` is the wrong abstraction for this phase because registration is not an actuator command. It is a provenance adjudication workflow.

Add a parallel governance artifact:

- `RegistrationIntent`
- `RegistrationDecision`

Minimal `RegistrationDecision` fields:

- `registration_id`
- `policy_snapshot`
- `allowed`
- `decision`
- `reason_codes`
- `required_followups`
- `rare_grade_result`

Then keep the existing `ActionIntent` model for later steps such as:

- release to packing line
- quarantine movement
- sealed vault transfer

That preserves the README architecture: judgment first, authorization later.

## Coordinator Workflow

Represent this as a proto-plan stored in `task_proto_plan`.

Recommended workflow stages:

1. `verify_artifact_integrity`
2. `extract_visual_features`
3. `validate_site_telemetry`
4. `validate_geo_altitude_claim`
5. `validate_bio_signature`
6. `evaluate_rare_grade_policy`
7. `persist_registration_facts`
8. `emit_registration_verdict`

This fits the current coordinator and plan executor well:

- coordinator determines workflow and route
- plan executor materializes domain-specific validation steps
- fact service records governed outcomes

## Where Existing Components Should Be Extended

### API Layer

Add an app-facing router instead of exposing only `/tasks`.

Suggested surface:

- `POST /source-registrations`
- `GET /source-registrations/{registration_id}`
- `POST /source-registrations/{registration_id}/artifacts`
- `POST /source-registrations/{registration_id}/submit`
- `GET /source-registrations/{registration_id}/verdict`

The router should:

- persist `SourceRegistration`
- persist artifacts and measurements
- enqueue the orchestration task
- return app-friendly status and read models

### Coordinator

Add a workflow branch keyed on:

- `type == "registration"` or
- `params.governance.workflow == "source_registration"`

Coordinator changes should:

- require the new envelope plus linked ingress event IDs
- normalize provenance inputs from the governed event stream into deterministic attributes
- call cognitive service as a core normalization capability for semantic extraction, evidence correlation, and ambiguity resolution
- synthesize a registration proto-plan from the normalized projection
- produce `RegistrationDecision`

### Eventizer / Multimodal Refinement

Extend the current multimodal path to understand provenance modalities:

- macro-image feature extraction metadata
- seal pattern detection
- site telemetry bundles
- spectroscopy summaries

Eventizer should remain the deterministic normalization layer for structure, canonical fields, and modality classification.

The cognitive service should be treated as the paired semantic layer inside the normalization component:

- interpret vision and telemetry evidence that does not reduce cleanly to rule-based extraction
- reconcile cross-modal inconsistencies before planning
- emit normalized semantic annotations that validators and planners can trust

Do not ask either Eventizer or cognitive service to become the chemistry engine. Domain validation should still happen in dedicated validators.

### Fact Service

Persist registration facts with explicit predicates, for example:

- `lot:LOT123 originated_from zone:RARE_GROWTH_A7`
- `registration:REG123 has_visual_seal_match true`
- `registration:REG123 has_environmental_match true`
- `registration:REG123 has_bio_signature_match true`
- `registration:REG123 awarded_grade rare_grade`

This makes the result queryable by PKG and replay tools.

### Evidence

Extend `EvidenceBundle.telemetry_snapshot` to include registration evidence classes:

- `visual_provenance`
- `environmental_fingerprint`
- `chemical_bio_signature`
- `artifact_hashes`
- `validator_outputs`

For registration, evidence is not only execution telemetry. It is adjudication telemetry.

## Validation Subsystems

The main missing runtime piece is a validator layer behind the coordinator.

Add domain validators as callable adapters:

- `VisualProvenanceValidator`
- `EnvironmentalFingerprintValidator`
- `BioSignatureValidator`
- `RareGradePolicyEvaluator`

Expected behavior:

- take normalized registration input
- return deterministic scores, thresholds, reason codes, and raw trace
- remain independently testable

These can be local Python services first. They do not need to be folded into the generic Eventizer path, but they should consume the same normalized projection produced by Eventizer plus cognitive service.

## Read Model For The App Layer

The app should not reconstruct status from raw tasks, facts, and evidence.

Provide a dedicated read model:

- registration header
- artifact checklist
- validator statuses
- current verdict
- exception reasons
- replay links

Suggested derived fields:

- `overall_status`
- `visual_status`
- `environmental_status`
- `biosignature_status`
- `rare_grade_status`
- `quarantine_reason_codes`
- `packing_eligibility`

## Data Storage Guidance

Use both normalized tables and existing JSON evidence.

Recommended split:

- normalized tables for app queries, rule evaluation, and reporting
- raw JSON blobs for original artifact metadata and validator traces
- facts for governance/audit linkage
- task/result/proto-plan for orchestration

Do not store everything only in `tasks.params`. That will make the app layer brittle and reporting expensive.

## Release Flow Separation

Registration approval should not itself authorize packing-line execution.

Use a two-step model:

1. registration proves provenance and grade eligibility
2. downstream operational workflow emits a separate `ActionIntent` for physical release

That keeps custody and provenance aligned with the current SeedCore zero-trust model.

## Minimal Implementation Path

Phase 1:

- standardize `TrackingEvent`-first ingress across the app-facing flow
- add or finalize `SourceRegistration` tables and projection wiring
- add app-facing API
- add `params.source_registration`
- add coordinator workflow branch
- wire cognitive service into normalization for provenance-heavy registrations
- persist verdict as facts plus JSON result

Phase 2:

- add dedicated validator adapters
- extend evidence bundle with registration sections
- add app read model endpoints

Phase 3:

- connect registration approval to downstream release gating
- require approved registration before packing-line `ActionIntent`

## Key Design Decision

The app layer should integrate against `SourceRegistration`, not directly against generic tasks.

SeedCore should still orchestrate with tasks internally, but the business object for this feature must be a provenance-specific aggregate projected from a governed event stream, with Eventizer and cognitive service acting as the core normalization capability before planning and decisioning.
