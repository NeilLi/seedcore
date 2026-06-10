# Hardware-Anchored Telemetry MVP Contract

Date: 2026-05-17
Status: Lightweight implementation contract

## Purpose

This contract turns [ADR 0010](../architecture/adr/adr-0010-hardware-anchored-telemetry-execution-proof.md) into a small implementation target.

The goal is to make SeedCore's physical execution proof chain concrete:

```text
ExecutionToken lifecycle
+ hardware-bound signer
+ signed telemetry
+ asset anchor
+ zone evidence
+ verifier replay
```

The first milestone is not a full hardware platform. The first milestone is a contract and fixture lane proving that a high-consequence physical action cannot be accepted on software authority alone.

## Spark-Era Note

RTX Spark / DGX Spark-class machines should be modeled as local agent
workstations or simulation substrates unless they are explicitly enrolled as
evidence-producing devices. They may sign proposal, simulation, diagnostic, or
workload provenance, but that provenance is not physical closure by itself.

For Restricted Custody Transfer:

```text
agent workstation provenance explains who proposed or diagnosed
edge/robot telemetry proves what happened physically
PDP + ExecutionToken + verifier outcome decide whether closure is admissible
```

This keeps Spark-era local autonomy useful without letting local compute become
execution authority.

## Existing Baseline

SeedCore already has several pieces this MVP should reuse:

- `SignedEdgeTelemetryRefV0` and `EdgeTelemetryEnvelopeV0` in `src/seedcore/models/edge_telemetry.py`
- `telemetry_refs` on Agent Action Gateway closure request/response
- closure validation requiring `telemetry_refs[*].asset_ref` to match the evaluated request asset
- evidence bundles that persist `telemetry_refs`
- forensic materialization that exposes ordered telemetry refs
- RESULT_VERIFIER and replay paths for source-preserving verification
- TPM/KMS runbooks for stronger signer posture

This contract narrows those pieces into one implementation target for high-consequence physical execution.

## Core Rule

For high-consequence physical workflows:

```text
ExecutionToken permits an attempt.
Hardware-anchored telemetry proves physical closure.
Verifier replay decides whether the chain held.
```

If hardware-anchored telemetry is required by policy and is missing or invalid, the action must not settle as accepted.

## RATS Vocabulary Alignment

This MVP should use IETF RATS terminology when the implementation moves beyond
fixture signer checks into real attestation:

| RATS role / object | SeedCore mapping |
| :--- | :--- |
| Attester | physical endpoint, simulator endpoint, TPM/KMS/TEE-backed signer, or trusted edge node |
| Evidence | signed telemetry envelope, signer proof, attestation quote, asset anchor, zone evidence |
| Verifier | `seedcore-verify`, RESULT_VERIFIER, or replay verifier path |
| Appraisal Policy | PKG policy snapshot, signer trust bundle, revocation lists, attestation freshness rules |
| Attestation Result | replay/verifier output that can admit, deny, or quarantine closure |
| Relying Party | gateway closure path, twin settlement service, operator proof surface |

For the broader token lifecycle framing, see
`docs/development/execution_token_lifecycle_management.md`.

## Contract Objects

### 1. DeviceIdentity

Represents an enrolled physical endpoint or simulator endpoint.

```json
{
  "device_id": "device:jetson-orin-01",
  "edge_node_ref": "node:jetson-orin-01",
  "device_profile": "prototype_edge",
  "hardware_fingerprint": "sha256:...",
  "signer_key_ref": "key:edge:jetson-orin-01:p256:v1",
  "attestation_level": "prototype",
  "trusted_for_zones": ["handoff_bay_3"],
  "trusted_for_evidence": ["origin_scan", "delivery_scan", "weight_cell"],
  "status": "active"
}
```

Allowed `device_profile` values for the MVP:

- `simulator`
- `prototype_edge`
- `trusted_edge`

Allowed `status` values:

- `active`
- `revoked`
- `quarantined`

### 2. HardwareSignerRef

Represents the signing key used by the physical endpoint.

```json
{
  "signer_key_ref": "key:edge:jetson-orin-01:p256:v1",
  "algorithm": "p256",
  "trust_anchor_type": "software_dev_key",
  "public_key_fingerprint": "sha256:...",
  "device_id": "device:jetson-orin-01",
  "valid_from": "2026-05-17T00:00:00Z",
  "valid_until": null,
  "revocation_id": "rev:edge:jetson-orin-01:p256:v1"
}
```

Allowed `trust_anchor_type` values for the MVP:

- `software_dev_key`
- `tpm`
- `kms`
- `tee`

The MVP may use `software_dev_key` in fixtures, but production claims should require `tpm`, `kms`, or `tee` where the deployment profile demands it.

### 3. AssetAnchor

Represents the asset binding observed by the device.

```json
{
  "asset_ref": "asset:rare-shoe:001",
  "product_ref": "product:rare-shoe:sku-001",
  "anchor_type": "nfc_scan",
  "anchor_hash": "sha256:...",
  "observed_at": "2026-05-17T10:01:00Z"
}
```

Allowed `anchor_type` values for the MVP:

- `nfc_scan`
- `qr_scan`
- `vision_fingerprint`
- `manual_fixture`

### 4. ZoneEvidence

Represents the place/scope binding observed by the device.

```json
{
  "zone_ref": "handoff_bay_3",
  "coordinate_ref": "warehouse://north/handoff_bay_3",
  "evidence_type": "device_zone_claim",
  "observed_at": "2026-05-17T10:01:00Z",
  "confidence": 1.0
}
```

Allowed `evidence_type` values for the MVP:

- `device_zone_claim`
- `gps_fix`
- `uwb_fix`
- `manual_fixture`

### 5. SignedTelemetryEnvelope

The MVP should reuse `EdgeTelemetryEnvelopeV0` as the first signed telemetry payload shape.

```json
{
  "contract_version": "seedcore.edge_telemetry_envelope.v0",
  "telemetry_id": "telemetry_001",
  "edge_node_ref": "node:jetson-orin-01",
  "asset_ref": "asset:rare-shoe:001",
  "observed_at": "2026-05-17T10:01:00Z",
  "sensor_kind": "weight_cell",
  "samples": [
    {
      "t_offset_ms": 0,
      "value": 1.0
    }
  ],
  "payload_sha256": "sha256:...",
  "nonce": "nonce_001",
  "signer": {
    "key_ref": "key:edge:jetson-orin-01:p256:v1",
    "algorithm": "p256",
    "signature_b64": "..."
  }
}
```

### 6. SignedTelemetryRef

Closure should carry digest refs, not necessarily raw telemetry payloads.

The MVP should continue using `SignedEdgeTelemetryRefV0`:

```json
{
  "contract_version": "seedcore.edge_telemetry_envelope.v0",
  "telemetry_id": "telemetry_001",
  "asset_ref": "asset:rare-shoe:001",
  "edge_node_ref": "node:jetson-orin-01",
  "observed_at": "2026-05-17T10:01:00Z",
  "sensor_kind": "weight_cell",
  "payload_sha256": "sha256:...",
  "signer_key_ref": "key:edge:jetson-orin-01:p256:v1"
}
```

## Required Verification Checks

The MVP verifier path should check:

1. required telemetry refs are present for the workflow;
2. `asset_ref` matches the original evaluated request asset;
3. `edge_node_ref` maps to an enrolled active `DeviceIdentity`;
4. `signer_key_ref` maps to a trusted non-revoked signer;
5. telemetry `observed_at` is inside the authority window or accepted delayed-submission window;
6. telemetry nonce or payload hash has not been replayed for a different workflow;
7. zone or coordinate evidence matches `authority_scope`;
8. telemetry payload hash matches the signed envelope when the raw envelope is available;
9. trust anchor profile matches the deployment lane;
10. evidence bundle and replay materialization include the telemetry refs used for closure.

## Failure Modes

| Failure | Default outcome | Reason code |
| --- | --- | --- |
| Missing required telemetry | `quarantine` | `signed_telemetry_missing` |
| Unknown signer key | `quarantine` | `telemetry_signer_unknown` |
| Revoked signer key | `deny` | `telemetry_signer_revoked` |
| Wrong asset | `deny` | `telemetry_asset_mismatch` |
| Wrong zone/coordinate | `deny` | `telemetry_scope_mismatch` |
| Stale telemetry | `quarantine` | `telemetry_too_stale` |
| Observed outside authority window | `deny` | `telemetry_outside_authority_window` |
| Replay nonce/hash reuse | `deny` | `telemetry_replay_detected` |
| Payload hash mismatch | `quarantine` | `telemetry_payload_hash_mismatch` |
| Insufficient trust anchor for profile | `escalate` | `telemetry_trust_anchor_insufficient` |

Exact reason-code spelling may be aligned with existing gateway and verifier taxonomy during implementation. The behavior is the important contract.

## MVP Fixture Matrix

Create fixtures for:

1. `valid_hardware_anchored_closure`
   - token, signer, asset, zone, telemetry, and replay all match.
2. `missing_signed_telemetry`
   - policy requires telemetry, closure omits refs, result quarantines.
3. `wrong_asset_telemetry`
   - telemetry `asset_ref` differs from request asset, result denies.
4. `wrong_zone_telemetry`
   - zone evidence contradicts `authority_scope`, result denies.
5. `stale_telemetry`
   - observed time violates freshness window, result quarantines.
6. `revoked_signer`
   - signer is enrolled but revoked, result denies.
7. `replayed_telemetry`
   - same nonce or payload reused for another workflow, result denies.
8. `simulator_evidence_in_trusted_profile`
   - simulator/dev signer used where trusted-edge profile requires hardware trust, result escalates.

## 30-Day Implementation Target

The first implementation should stay narrow:

1. Define a small enrollment fixture for `DeviceIdentity` and `HardwareSignerRef`.
2. Add a policy/profile flag that marks telemetry as required for one RCT path.
3. Extend existing closure tests to cover signer, asset, zone, freshness, and replay checks.
4. Ensure `EvidenceBundle.telemetry_refs` contains every ref used for closure.
5. Ensure replay materialization exposes the telemetry refs and signer refs.
6. Add verifier checks that fail closed on missing or contradictory hardware evidence.
7. Keep simulator fixtures explicitly labeled as `device_profile=simulator` or `attestation_level=prototype`.

Do not start by building a full hardware enrollment service, remote attestation platform, or vendor-specific trusted-edge stack.

For the staged freshness-SLA rollout across simulator, Jetson prototype edge,
IGX/T5000 trusted edge, and robotics handoff environments, see
[Freshness SLA Edge Stress Schedule](freshness_sla_edge_stress_schedule.md).

## Acceptance Criteria

The MVP is accepted when:

1. a high-consequence closure cannot settle as accepted without required signed telemetry;
2. a closure with the wrong asset cannot settle as accepted;
3. a closure with the wrong zone or coordinate cannot settle as accepted;
4. revoked or unknown signer keys fail closed;
5. stale telemetry fails closed;
6. replayed telemetry fails closed;
7. evidence bundles carry the signed telemetry refs used for closure;
8. replay output can explain which device, signer, asset, zone, and telemetry payload were used;
9. simulator evidence is distinguishable from production hardware-anchored evidence.

## Positioning

The product story should be:

```text
SeedCore does not only issue software permission.
SeedCore binds permission to hardware-witnessed physical evidence and replay.
```

A compromised cloud agent should not be able to fake real-world execution because it lacks the device key, hardware signer, asset anchor, zone evidence, and telemetry chain.

## Related Documents

- [ADR 0010: Hardware-Anchored Telemetry as Execution Proof](../architecture/adr/adr-0010-hardware-anchored-telemetry-execution-proof.md)
- [ADR 0003: IGX Thor Trusted Edge Profile](../architecture/adr/adr-0003-igx-thor-trusted-edge-profile.md)
- [Agent Action Gateway Contract](agent_action_gateway_contract.md)
- [Edge Telemetry Evidence Closure Draft](edge_telemetry_evidence_closure_draft.md)
- [Virtual NFC Simulation Plan](virtual_nfc_simulation_plan.md)
- [TPM Fleet Rollout Runbook](tpm_fleet_rollout_runbook.md)
- [Rare-Shoe RCT Demo Spec](rare_shoes_collecting_transfer_demo_spec.md)
