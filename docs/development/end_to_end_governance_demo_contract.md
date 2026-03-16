# End-to-End Governance Demo Contract

## Goal

Decide exactly what the demo proves and what it does not.

This contract freezes scope for the first closed-loop SeedCore demonstration of:

```text
Tracking Event -> Policy Decision -> Execution Token -> Signed Evidence Bundle
```

## Objective

Move from "functional architecture" to one deterministic, replayable, end-to-end governance flow.

## Frozen Demo Decisions

### Action path

- `RELEASE` with an approved `SourceRegistration`

### Actuator target

- simulator-backed mocked endpoint

This means the demo proves governed execution against a controlled endpoint without requiring live robotics hardware or vendor-specific instability.

### Demo start point

- `POST /api/v1/source-registrations`

This is the chosen entrypoint because it already emits and projects governed `TrackingEvent`s, which keeps the demo aligned with the current event-stream-first architecture.

### What counts as "signed"

- current HMAC signing is sufficient

For this demo:

- `ExecutionToken.signature` is the proof that the PDP authorized the action
- `EvidenceBundle.execution_receipt.signature` is the proof that the execution result was sealed into an auditable receipt

Hardware-rooted attestation, TEE-backed signing, and asymmetric key infrastructure are explicitly out of scope for this phase.

## What The Demo Proves

- SeedCore accepts governed provenance ingress through the canonical API.
- SeedCore projects ingress into a decisionable registration state.
- SeedCore blocks physical `RELEASE` unless the referenced `SourceRegistration` is approved.
- SeedCore derives an `ActionIntent` and returns a signed `ExecutionToken` on allow.
- SeedCore sends the governed action to a controlled simulator-backed endpoint.
- SeedCore returns a signed `EvidenceBundle` that ties execution back to the intent, token, and telemetry context.

## What The Demo Does Not Prove

- real robot hardware reliability
- hardware-rooted sensor attestation
- TEE-backed execution
- production-grade custody ledger settlement
- multi-asset concurrency
- generalized policy coverage for all physical actions
- regulatory certification

## Canonical Flow

```text
1. Create SourceRegistration
2. Persist TrackingEvents via the registration API
3. Submit registration for decision
4. Fetch approved RegistrationDecision
5. Create RELEASE action task referencing that approval
6. Coordinator derives ActionIntent
7. PDP evaluates ActionIntent
8. PDP returns signed ExecutionToken
9. Simulator-backed mocked endpoint executes
10. Runtime attaches signed EvidenceBundle
```

## Required API Calls

### Happy path

1. `POST /api/v1/source-registrations`
2. `POST /api/v1/source-registrations/{registration_id}/submit`
3. `GET /api/v1/source-registrations/{registration_id}/verdict`
4. `POST /api/v1/tasks`
5. `GET /api/v1/tasks/{task_id}`
6. Optional: `GET /api/v1/tasks/{task_id}/logs`

### Deny path

1. `POST /api/v1/source-registrations`
2. Optional: `POST /api/v1/source-registrations/{registration_id}/submit`
3. `POST /api/v1/tasks`
4. `GET /api/v1/tasks/{task_id}`

## Policy Gate Rule

The frozen rule for this demo is:

> A `RELEASE` action is allowed only if the `ActionIntent` references an approved `SourceRegistration`, and that approval is bound to the action through `source_registration_id` and, when present, `registration_decision_id`.

Expected deny conditions:

- missing `source_registration_id`
- referenced registration has no approved decision
- referenced approval does not match the required `registration_decision_id`
- invalid or expired `ActionIntent`

## Expected ExecutionToken Fields

The demo must show these fields in the allow-path response:

- `token_id`
- `intent_id`
- `issued_at`
- `valid_until`
- `contract_version`
- `signature`
- `constraints.action_type`
- `constraints.target_zone`
- `constraints.asset_id`
- `constraints.principal_agent_id`
- `constraints.source_registration_id`
- `constraints.registration_decision_id`

## Expected EvidenceBundle Fields

The demo must show these fields in the final task result or result metadata:

- `intent_ref`
- `executed_at`
- `telemetry_snapshot.executed_by.organ_id`
- `telemetry_snapshot.executed_by.agent_id`
- `telemetry_snapshot.zone_checks.target_zone`
- `telemetry_snapshot.vision`
- `telemetry_snapshot.sensors`
- `telemetry_snapshot.gps`
- `telemetry_snapshot.endpoint_responses`
- `execution_receipt.receipt_id`
- `execution_receipt.proof_type`
- `execution_receipt.signature`
- `execution_receipt.payload_hash`
- `execution_receipt.signed_payload.intent_id`
- `execution_receipt.signed_payload.token_id`
- `execution_receipt.signed_payload.policy_decision`
- `execution_receipt.actuator_endpoint`
- `execution_receipt.actuator_result_hash`

## Canonical Happy-Path Dataset

### Dataset intent

Prove a single approved source registration can authorize a governed `RELEASE` and produce a signed evidence artifact.

### Step A: Create source registration

```json
{
  "source_claim_id": "claim-demo-001",
  "lot_id": "lot-demo-001",
  "producer_id": "producer-demo-001",
  "rare_grade_profile_id": "rare-grade-demo",
  "claimed_origin": {
    "zone_id": "vault_alpha",
    "country": "TH",
    "altitude_meters": 2430
  },
  "collection_site": {
    "site_id": "site-demo-001",
    "name": "Demo Collection Site"
  },
  "collected_at": "2026-03-13T10:00:00Z",
  "artifacts": [
    {
      "artifact_type": "honeycomb_macro_image",
      "uri": "s3://seedcore-demo/happy/honeycomb_macro.jpg",
      "sha256": "happy-honeycomb-sha256",
      "captured_at": "2026-03-13T10:01:00Z",
      "captured_by": "operator-demo",
      "device_id": "cam-demo-01",
      "content_type": "image/jpeg",
      "metadata": {
        "lens": "macro"
      }
    },
    {
      "artifact_type": "seal_macro_image",
      "uri": "s3://seedcore-demo/happy/seal_macro.jpg",
      "sha256": "happy-seal-sha256",
      "captured_at": "2026-03-13T10:02:00Z",
      "captured_by": "operator-demo",
      "device_id": "cam-demo-02",
      "content_type": "image/jpeg",
      "metadata": {
        "lens": "macro"
      }
    }
  ],
  "measurements": [
    {
      "measurement_type": "gps",
      "value": 2438.7,
      "unit": "meters",
      "measured_at": "2026-03-13T10:03:00Z",
      "sensor_id": "gps-demo-01",
      "quality_score": 0.99,
      "metadata": {
        "lat": 18.801,
        "lon": 98.921,
        "altitude_meters": 2438.7
      }
    },
    {
      "measurement_type": "purity_score",
      "value": 0.992,
      "unit": "ratio",
      "measured_at": "2026-03-13T10:04:00Z",
      "sensor_id": "lab-demo-01",
      "quality_score": 0.97,
      "metadata": {}
    },
    {
      "measurement_type": "spectral_match_score",
      "value": 0.961,
      "unit": "ratio",
      "measured_at": "2026-03-13T10:05:00Z",
      "sensor_id": "spec-demo-01",
      "quality_score": 0.96,
      "metadata": {}
    }
  ]
}
```

### Step B: Submit source registration

Request:

```text
POST /api/v1/source-registrations/{registration_id}/submit
```

Expected outcome:

- registration enters governed evaluation flow
- a `RegistrationDecision` is created
- latest verdict is `approved`

### Step C: Create governed RELEASE task

This request happens only after the approval verdict is available.

```json
{
  "type": "action",
  "description": "Release approved demo lot from vault_alpha to outbound handoff",
  "domain": "provenance",
  "run_immediately": true,
  "params": {
    "intent": "release",
    "interaction": {
      "mode": "coordinator_routed",
      "assigned_agent_id": "agent-demo-01",
      "conversation_id": "conv-demo-release-001"
    },
    "routing": {
      "required_specialization": "VAULT_OPERATOR",
      "target_organ_hint": "mock_release_endpoint",
      "tools": ["policy.lookup", "iot.release"]
    },
    "multimodal": {
      "location_context": "vault_alpha",
      "gps": {
        "lat": 18.801,
        "lon": 98.921
      },
      "detections": [
        {
          "label": "sealed_box",
          "confidence": 0.93
        }
      ]
    },
    "resource": {
      "asset_id": "lot-demo-001",
      "target_zone": "vault_alpha",
      "source_registration_id": "{registration_id}",
      "registration_decision_id": "{approved_decision_id}"
    },
    "executor": {
      "specialization": "VAULT_OPERATOR"
    },
    "governance": {
      "require_action_intent": true,
      "requires_approved_source_registration": true
    }
  }
}
```

### Happy-path success conditions

- `GET /api/v1/source-registrations/{registration_id}/verdict` returns `approved`
- `POST /api/v1/tasks` accepts the `RELEASE` task
- task result includes governance context with an allowed policy decision
- task result includes a signed `ExecutionToken`
- task result includes a signed `EvidenceBundle`
- `EvidenceBundle.execution_receipt.actuator_endpoint` identifies the simulator-backed mocked endpoint

## Canonical Deny-Path Dataset

### Dataset intent

Prove that SeedCore denies `RELEASE` when the source registration approval requirement is not satisfied.

### Deny condition

- use a valid registration identifier
- omit `registration_decision_id` and do not wait for approval, or reference a registration with no approved verdict

### Deny-path RELEASE task

```json
{
  "type": "action",
  "description": "Attempt release without approved source registration",
  "domain": "provenance",
  "run_immediately": true,
  "params": {
    "intent": "release",
    "interaction": {
      "mode": "coordinator_routed",
      "assigned_agent_id": "agent-demo-01",
      "conversation_id": "conv-demo-release-deny-001"
    },
    "routing": {
      "required_specialization": "VAULT_OPERATOR",
      "target_organ_hint": "mock_release_endpoint",
      "tools": ["policy.lookup", "iot.release"]
    },
    "multimodal": {
      "location_context": "vault_alpha"
    },
    "resource": {
      "asset_id": "lot-demo-deny-001",
      "target_zone": "vault_alpha",
      "source_registration_id": "{registration_id_without_approval}"
    },
    "governance": {
      "require_action_intent": true,
      "requires_approved_source_registration": true
    }
  }
}
```

### Deny-path failure conditions

- policy decision is `allowed = false`
- task returns an error path such as `policy_denied`
- no execution is sent to the simulator-backed mocked endpoint
- no final success evidence artifact is produced for actuation

## Demo Artifacts

The demo package must contain:

- API transcript
- architecture diagram
- sample payloads
- expected final evidence JSON

### 1. API transcript

The transcript must capture:

- request and response for registration creation
- request and response for registration submit
- request and response for verdict lookup
- request and response for action task creation
- final task fetch with governance metadata and evidence

### 2. Architecture diagram

The diagram must show:

```text
SourceRegistration API
  -> TrackingEvent projection
  -> RegistrationDecision
  -> RELEASE task
  -> ActionIntent
  -> PDP
  -> ExecutionToken
  -> simulator-backed mocked endpoint
  -> EvidenceBundle
```

### 3. Sample payloads

The payload pack must include:

- happy-path registration payload
- happy-path action payload
- deny-path action payload
- final expected evidence JSON

### 4. Expected final evidence JSON

The final evidence document should resemble:

```json
{
  "intent_ref": "governance://action-intent/{intent_id}",
  "executed_at": "2026-03-13T10:10:10Z",
  "telemetry_snapshot": {
    "executed_by": {
      "organ_id": "mock_release_endpoint",
      "agent_id": "agent-demo-01"
    },
    "captured_at": "2026-03-13T10:10:10Z",
    "vision": [
      {
        "label": "sealed_box",
        "confidence": 0.93
      }
    ],
    "sensors": [
      {
        "source": "tool",
        "tool": "iot.release",
        "device_id": "mock-release-001",
        "status": "ok"
      }
    ],
    "gps": {
      "lat": 18.801,
      "lon": 98.921
    },
    "zone_checks": {
      "target_zone": "vault_alpha",
      "current_zone": null
    },
    "endpoint_responses": [
      {
        "source": "output",
        "tool": "iot.release",
        "endpoint_response": {
          "actuator_endpoint": "tool://iot.release/mock-release-001",
          "status": "ok",
          "device_id": "mock-release-001",
          "result_hash": "{actuator_result_hash}"
        }
      }
    ]
  },
  "execution_receipt": {
    "receipt_id": "{receipt_id}",
    "proof_type": "hmac_sha256",
    "signature": "{receipt_signature}",
    "payload_hash": "{payload_hash}",
    "signed_payload": {
      "intent_id": "{intent_id}",
      "task_id": "{task_id}",
      "executed_at": "{executed_at}",
      "token_id": "{token_id}",
      "actuator_result_hash": "{actuator_result_hash}",
      "actuator_endpoint": "tool://iot.release/mock-release-001",
      "policy_decision": {
        "allowed": true
      }
    },
    "actuator_endpoint": "tool://iot.release/mock-release-001",
    "actuator_result_hash": "{actuator_result_hash}"
  }
}
```

## Acceptance Criteria

This scope is frozen when all of the following are true:

- the team uses `POST /api/v1/source-registrations` as the demo ingress
- the demo action is `RELEASE`
- the execution target is the simulator-backed mocked endpoint
- HMAC signatures are accepted as sufficient for the phase
- one happy-path dataset and one deny-path dataset are fixed and versioned
- every demo rehearsal uses the same API transcript structure and evidence output shape

## Out Of Scope Changes During This Phase

Do not add any of the following during week 1 unless the current plan becomes blocked:

- live hardware robot control
- Tuya-specific production hardening
- new approval workflows beyond the one frozen rule
- multi-step release choreography
- UI polish
- TEE integration
- asymmetric signing migration
- generalized custody ledger closeout

## References

- [Source Registration And Tracking Event Reference](/Users/ningli/project/seedcore/docs/references/source-registration-events.md)
- [Source Registration Architecture](/Users/ningli/project/seedcore/docs/development/source_registration_architecture.md)
- [Task Routing Payload Reference](/Users/ningli/project/seedcore/docs/references/task_payload_router.md)
