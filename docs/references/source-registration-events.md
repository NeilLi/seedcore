# Source Registration And Tracking Event Reference

This reference describes the governed ingress flow introduced for provenance-heavy source claims.

The runtime sequence is now:

```text
raw telemetry / scans / operator requests
  -> TrackingEvent stream
  -> SourceRegistration state projection
  -> RegistrationDecision
  -> later ActionIntent for physical packing or release
```

## 1. Why This Exists

`SourceRegistration` is no longer the first write.

Telemetry, provenance scans, seal checks, environmental readings, and operator requests now enter as first-class immutable `TrackingEvent` records before planning and decisioning begin.

This enforces:

- append-only ingress history
- replayable provenance
- separation between evidence capture and decisioning
- a clean handoff from registration approval to later `ActionIntent`

## 2. Core Contracts

### 2.1 TrackingEvent

Defined in [source_registration.py](/Users/ningli/project/seedcore/src/seedcore/models/source_registration.py#L98).

Canonical fields:

- `id`
- `registration_id`
- `event_type`
- `source_kind`
- `payload`
- `sha256`
- `captured_at`
- `producer_id`
- `device_id`
- `operator_id`
- `correlation_id`
- `snapshot_id`
- `projected_at`
- `created_at`

### 2.2 Event Types

- `source_claim_declared`
- `provenance_scan_captured`
- `seal_check_captured`
- `environmental_reading_recorded`
- `bio_signature_recorded`
- `operator_request_received`

### 2.3 Source Kinds

- `source_declaration`
- `provenance_scan`
- `telemetry`
- `operator_request`
- `system`

## 3. Projection Rule

`TrackingEvent` is the ingress log.

`SourceRegistration`, `SourceRegistrationArtifact`, and `SourceRegistrationMeasurement` are projections over that log.

Projection logic is implemented in [projector.py](/Users/ningli/project/seedcore/src/seedcore/ops/source_registration/projector.py#L29).

High-level projection behavior:

- `source_claim_declared` updates registration header fields
- `provenance_scan_captured` and `seal_check_captured` project into artifacts
- `environmental_reading_recorded` and `bio_signature_recorded` project into measurements
- `operator_request_received` can move the registration into `verifying`

## 4. SourceRegistration Lifecycle

Projected lifecycle states:

- `draft`
- `ingesting`
- `verifying`
- `approved`
- `quarantined`
- `rejected`

State transition notes:

- creation starts in `draft`
- claim declaration and evidence capture move it to `ingesting`
- submit operator events move it to `verifying`
- coordinator writes `RegistrationDecision`, which moves it to terminal decision states

## 5. API Surfaces

### 5.1 Tracking Event Ingress

Implemented in [tracking_events_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/tracking_events_router.py#L77).

Available endpoints:

- `POST /api/v1/tracking-events`
- `GET /api/v1/tracking-events`
- `GET /api/v1/tracking-events/{event_id}`
- `GET /api/v1/source-registrations/{registration_id}/tracking-events`

### 5.2 Source Registration API

Implemented in [source_registrations_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/source_registrations_router.py#L268).

Important behavior change:

- these endpoints now emit and project `TrackingEvent`s instead of directly treating artifacts and measurements as the original ingress source

## 6. Event Payload Conventions

### 6.1 Source Claim Declared

```json
{
  "source_claim_id": "claim-123",
  "lot_id": "lot-001",
  "producer_id": "producer-9",
  "rare_grade_profile_id": "rare-gold",
  "claimed_origin": {
    "zone_id": "zone-a",
    "altitude_meters": 2430
  },
  "collection_site": {
    "site_id": "site-7"
  },
  "collected_at": "2026-03-11T10:00:00Z"
}
```

### 6.2 Provenance Or Seal Scan

```json
{
  "artifact_type": "honeycomb_macro_image",
  "uri": "s3://bucket/honeycomb.jpg",
  "sha256": "abc123",
  "captured_at": "2026-03-11T10:01:00Z",
  "device_id": "cam-1",
  "metadata": {
    "lens": "macro"
  }
}
```

### 6.3 Environmental Or Bio-Signature Reading

```json
{
  "measurement_type": "gps",
  "value": 2438.7,
  "unit": "meters",
  "lat": 18.801,
  "lon": 98.921,
  "altitude_meters": 2438.7,
  "sensor_id": "gps-7"
}
```

### 6.4 Operator Request

```json
{
  "command": "submit_for_decision",
  "task_id": "uuid"
}
```

## 7. Decision Boundary

`RegistrationDecision` happens after projection, not before it.

That means the coordinator should evaluate the projected state of the registration rather than trusting a one-shot request payload.

This matches the current runtime implementation in [coordinator_service.py](/Users/ningli/project/seedcore/src/seedcore/services/coordinator_service.py#L1327).

## 8. Release Flow Separation

Physical packing or release still requires a later `ActionIntent`.

The PDP now rejects `PACK` and `RELEASE` actions unless they reference an approved `SourceRegistration`.

That enforcement lives in [governance.py](/Users/ningli/project/seedcore/src/seedcore/coordinator/core/governance.py#L193).

The intended split is:

1. `TrackingEvent` capture
2. `SourceRegistration` projection
3. `RegistrationDecision`
4. `ActionIntent`
5. `ExecutionToken`

## 9. Migration And Bootstrap

Database support for the event log is added in:

- [123_tracking_events.sql](/Users/ningli/project/seedcore/deploy/migrations/123_tracking_events.sql)

Bootstrap ordering is updated in:

- [init-full-db.sh](/Users/ningli/project/seedcore/deploy/init-full-db.sh#L30)

## 10. Practical Rule

For provenance-heavy workflows, do not model ingress as:

`request payload -> decision`

Model it as:

`ingress event -> projection -> decision`

That is now the reference path for source-claim handling in SeedCore.
