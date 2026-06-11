# Virtual NFC Simulation Plan

Date: 2026-06-10
Status: Implemented and verified simulation-first NFC proof lane

## Purpose

This document turns the private virtual NFC prototyping note into a
SeedCore-native repo plan.

The goal is to prototype dynamic NFC challenge-response evidence before real
hardware is available. The simulation must strengthen the Restricted Custody
Transfer proof chain without weakening SeedCore's core rule:

```text
AI intent should not automatically become execution authority.
The model can propose. The Agent is accountable. The PDP decides.
The actuator executes. The evidence closes the loop.
```

Virtual NFC fixtures are evidence inputs. They do not mint authority, clear
quarantine, settle custody, or replace the PDP, `ExecutionToken`, signed
telemetry, or verifier replay paths.

## Implementation Status

As of 2026-06-11, the first simulation lane is implemented and verified:

- `src/seedcore/ops/evidence/nfc_verification.py` contains the pure
  Pydantic-backed verifier helper:
  `verify_dynamic_nfc_evidence(evidence, context, *, clock=None)`.
- `tests/fixtures/nfc/` contains deterministic fixtures for happy path,
  replay / clone, stale scan, tamper state, wrong asset, and missing required
  field cases.
- `tests/test_nfc_verification.py` proves stable `allow`, `deny`, and
  `quarantine` outcomes and verifies that challenge nonce, challenge response,
  CMAC ref, raw UID, and root-key material stay out of the result projection.
- `src/seedcore/models/rare_shoe_rct.py` delegates the rare-shoe dynamic NFC
  check to the generic helper while preserving the existing uppercase
  rare-shoe reason-code behavior for compatibility.
- `src/seedcore/ops/evidence/materializer.py` exposes replay-visible NFC
  metadata under `policy_verification.nfc_verification` and redacts
  authority-tier challenge and key material.

Workspace verification was completed after implementation:

- focused NFC / RCT / edge telemetry pytest slice: passed;
- evidence contracts / materializer / replay service pytest slice: passed;
- full Python test suite: 1329 tests passed;
- `scripts/host/verify_q2_verification_contracts.sh`: passed;
- `scripts/host/verify_authz_graph_rfc_phases.sh`: passed;
- TypeScript workspace typechecks and tests: passed;
- `git diff --check`: passed.

## Scope

The first implementation models dynamic NFC as a deterministic fixture lane for
rare-shoe Restricted Custody Transfer and hardware-anchored telemetry.

Implemented:

- JSON fixtures for fresh scan, replay / clone attempt, stale scan, and tamper
  state;
- a deterministic mock verifier for UID binding, nonce causality, scan-counter
  monotonicity, challenge-response hash, freshness, and tamper state;
- pytest coverage that proves allow, deny, and quarantine outcomes are stable;
- replay-visible reason codes and evidence references.

Still out of scope for this simulation lane:

- a production NFC key-management service;
- a vendor-specific NTAG integration;
- a new authority path outside the Agent Action Gateway / PDP / verifier
  contracts;
- a UI-first proof surface before the machine-readable evidence contract is
  stable.

## Simulation Contract

Dynamic NFC evidence should arrive as typed telemetry context associated with a
signed edge telemetry ref.

```json
{
  "observed_at": "2026-06-10T12:00:00Z",
  "freshness_seconds": 2,
  "max_allowed_age_seconds": 60,
  "evidence_refs": ["evidence:nfc-scan-001"],
  "nfc_payload": {
    "asset_ref": "asset:rare-shoe:001",
    "workflow_join_key": "sha256:workflow...",
    "nfc_uid_hash": "sha256:d8a9f3b1...",
    "scan_counter": 42,
    "challenge_nonce": "nonce-2026-06-10-abcd",
    "challenge_response_hash": "sha256:cmac-output-hash-here",
    "cmac_ref": "mock-key:ntag424:asset-001:v1",
    "tamper_state": "clear",
    "anchor_profile_ref": "profile:nxp-ntag424-dna-fixture-v1"
  }
}
```

Required properties:

- raw NFC UID values stay out of public proof projections;
- `asset_ref` and `workflow_join_key` bind the scan to the same governed
  custody workflow as the gateway evaluation and closure telemetry;
- `observed_at`, `freshness_seconds`, and `max_allowed_age_seconds` stay
  replay-visible;
- `challenge_nonce` is transaction-scoped and must match a nonce issued for the
  workflow;
- `scan_counter` is monotonic for the registered physical anchor;
- `challenge_response_hash` is deterministic in fixtures and replaceable by a
  real CMAC adapter later;
- `tamper_state != "clear"` never settles as accepted.

## Verification Checks

The virtual verifier performs these checks in order:

| Check | Required behavior | Default outcome |
| --- | --- | --- |
| Schema completeness | Required NFC fields are present and typed | `quarantine` |
| Asset binding | `asset_ref` matches the evaluated request asset | `deny` |
| Workflow binding | `workflow_join_key` matches the governed custody workflow | `quarantine` |
| Freshness | observed scan age is within `max_allowed_age_seconds` | `quarantine` |
| UID binding | `nfc_uid_hash` matches the registered asset anchor | `deny` |
| Nonce causality | `challenge_nonce` matches the issued transaction nonce | `deny` |
| Counter monotonicity | `scan_counter` is greater than the stored anchor counter | `deny` |
| Mock challenge response | recomputed fixture hash matches `challenge_response_hash` | `deny` |
| Tamper state | `tamper_state == "clear"` | `quarantine` |

The verifier returns a disposition and reason code. It must not mint
`ExecutionToken`s. For an `allow` disposition, normal PDP / gateway behavior
still decides whether an execution token can be minted. For a `deny` or
`quarantine` disposition, no new execution authority may be created from that
scan.

## Fixture Matrix

The first fixtures live under `tests/fixtures/nfc/`.

| Fixture | File | Simulated state | Expected disposition | Reason code |
| --- | --- | --- | --- | --- |
| Happy path scan | `nfc_happy_path.json` | Fresh nonce, valid counter, valid mock CMAC, tamper clear | `allow` | `rct_nfc_scan_verified` |
| Replay / clone attack | `nfc_replay_attack.json` | Counter reused or nonce / mock CMAC mismatch | `deny` | `dynamic_nfc_proof_invalid` |
| Stale scan | `nfc_stale_scan.json` | Scan exceeds freshness SLA | `quarantine` | `nfc_scan_too_stale` |
| Tampered tag | `nfc_tampered_tag.json` | `tamper_state != "clear"` | `quarantine` | `hardware_tamper_detected` |
| Wrong asset scan | `nfc_wrong_asset.json` | UID hash binds to a different registered asset | `deny` | `nfc_asset_anchor_mismatch` |
| Missing required field | `nfc_missing_required_field.json` | Required NFC field absent | `quarantine` | `nfc_payload_incomplete` |

The generic verifier exposes the lowercase reason-code taxonomy shown here.
The rare-shoe adapter preserves the older uppercase rare-shoe reason codes
while also returning the generic NFC reason code for newer callers.

## Resolved Design Decisions

### Tamper State

Default behavior: `tamper_state != "clear"` returns `quarantine` and routes the
asset / workflow to isolation or manual inspection.

This is not a clean proof of a cloned counterparty; it is evidence that the
physical anchor may be damaged, removed, swapped, or otherwise unreliable. The
runtime should withhold new execution authority and surface the verifier
evidence. If an active `ExecutionToken` is already bound to the affected
workflow, revocation should be handled through the normal token lifecycle and
operator / policy-admitted remediation path, not by a standalone NFC helper.

### Monotonic Counter Scope

The monotonic counter ledger is scoped to the registered physical anchor:

```text
nfc_uid_hash + anchor_profile_ref -> highest_observed_scan_counter
```

It must not reset after a custody workflow completes. Workflow-local records may
store the counter observed at origin and delivery for replay, but the anti-replay
ledger persists across workflows. Replacing a tag requires a new source
registration or anchor-rotation event with explicit evidence.

### Mock CMAC Key Management

Use deterministic fixture key derivation instead of one static key shared by all
tags.

For tests, derive a simulated tag key from a mock root plus stable fixture
identity:

```text
mock_tag_key = HMAC-SHA256(
  mock_root_key,
  nfc_uid_hash + "|" + anchor_profile_ref + "|" + cmac_ref
)
```

The mock root key must live in test configuration or fixtures only. Production
work should replace this helper with a hardware / KMS / vendor adapter and must
not infer production key posture from the fixture KDF.

## Implemented Order

1. Defined the fixture payloads and a tiny fixture registry for expected asset
   anchors, issued nonces, and highest observed counters.
2. Implemented a pure verifier helper under
   `src/seedcore/ops/evidence/nfc_verification.py`.
3. Added unit tests for every fixture in this document.
4. Bound NFC verification into the rare-shoe RCT evidence check after the helper
   had stable dispositions and reason codes.
5. Ensured replay materialization can expose the NFC
   evidence refs, freshness values, UID hash, anchor profile, reason code, and
   verifier disposition.

## Acceptance Criteria

The simulation lane is accepted because:

1. happy-path fixture NFC evidence can be verified deterministically;
2. replay / clone fixtures deny without minting authority;
3. stale and incomplete fixtures quarantine fail-closed;
4. tamper-state fixtures quarantine and do not settle custody as accepted;
5. monotonic counters persist per registered physical anchor across workflows;
6. mock CMAC behavior is deterministic and tag-specific in tests;
7. replay output explains the NFC check result without exposing raw NFC UID or
   production key material;
8. simulator evidence is clearly distinguishable from production
   hardware-anchored evidence.

## Related Documents

- [Rare-Shoe Restricted Custody Transfer Demo Spec](rare_shoes_collecting_transfer_demo_spec.md)
- [Hardware-Anchored Telemetry MVP Contract](hardware_anchored_telemetry_mvp_contract.md)
- [Freshness SLA Edge Stress Schedule](freshness_sla_edge_stress_schedule.md)
- [Execution Token Lifecycle Management](execution_token_lifecycle_management.md)
- [Gated Action DX Layer](gated_action_dx_layer.md)
