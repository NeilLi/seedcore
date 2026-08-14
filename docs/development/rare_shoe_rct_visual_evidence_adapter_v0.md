# Rare-Shoe RCT Visual Evidence Adapter v0

Date: 2026-08-14
Status: Latest application plan; contract and pilot design, not yet a production implementation

## Purpose

This document defines the next application slice for SeedCore's collectible
rare-shoe Restricted Custody Transfer (RCT) wedge.

The slice adds a computer-vision **evidentiary sidecar** that helps answer a
narrow question:

```text
Is the physical shoe observed at handoff or delivery materially consistent
with the shoe registered at origin?
```

It does not create a 3D marketplace, a global spatial map, a digital-twin
product, or a new source of execution authority. It extends the existing
rare-shoe RCT proof chain with replay-bound visual evidence.

The product boundary remains:

```text
AI or vision system proposes an observation
Agent remains accountable for the requested action
PDP evaluates typed, policy-admitted context and evidence requirements
ExecutionToken scopes one admitted custody attempt
actuator / operator performs the handoff
RESULT_VERIFIER replays the evidence and closes or quarantines the case
```

## Strategic Judgment

### Accept: Static Visual Evidence For RCT

Rare shoes remain the first legible commercial vertical. The visual pipeline
should strengthen three existing RCT concerns:

1. the listed asset and the physical asset can diverge
2. an authenticated asset can be swapped after registration
3. condition can drift between origin, handoff, and delivery

The useful output is therefore a hash-bound spatial or geometric fingerprint,
capture-quality record, and comparison disposition that can be inspected and
replayed with the rest of the custody evidence.

### Reject: A Parallel 2D-to-4D Product

A rare shoe is normally treated as a static physical asset during inspection.
The time axis that matters to SeedCore is the discrete custody sequence:

```text
registration -> origin custody -> handoff -> transit -> delivery -> closure
```

It is not a continuous deformation field over `x, y, z, t`. Dynamic 4D
Gaussian splatting, venue mapping, POI systems, geographic tile servers,
booking integrations, and global scene publishing do not advance the current
RCT wedge.

### Reject: Generative Pixels In Forensic Evidence

Zero123++, Stable Video Diffusion, SDXL inpainting, and similar generative
view-synthesis tools must not fill occluded regions, invent textures, or
produce pixels used by authentication, comparison, PDP input, or verifier
closure.

If a future experience surface uses a generated view, it must be:

- clearly marked as synthetic presentation content
- stored separately from raw and derived forensic artifacts
- excluded from fingerprint generation and comparison
- absent from policy-admitted evidence
- linked to its source ingredients and transformation record

The default v0 posture is simpler: do not generate missing evidence.

## Technology Adoption

### Adopt For The v0 Pilot

| Capability | Technology posture | RCT use |
| --- | --- | --- |
| Guided mobile capture | iOS native capture with ARKit first | pose hints, metric-scale assistance, frame coverage, overlap, distance, and blur guidance |
| Client-integrity signal | Apple App Attest | bind a server challenge and capture request to a legitimate app instance; not proof of the physical scene |
| Media lineage | SHA-256 manifests; pilot C2PA Content Credentials | bind raw media and declared transformations; not proof that the depicted claim is true |
| Object isolation | SAM 2 with pinned model/version metadata | derive masks while preserving every raw frame |
| Static reconstruction | COLMAP with pinned configuration | recover camera geometry, sparse/dense structure, and comparison artifacts |
| Artifact storage | SeedCore-owned object-storage adapter | preserve raw captures, masks, reconstruction outputs, manifests, and redacted projections |
| Operator inspection | existing verification UI plus optional lightweight Three.js view | compare origin and later observations without turning the viewer into custody truth |

Capture thresholds such as minimum frame occupancy, overlap, blur, and distance
are policy-profile inputs. Values such as `60%` object occupancy or `70%`
neighboring-view overlap may be useful starting hypotheses, but they must not be
presented as validated production thresholds until measured on the pilot
dataset.

### Pilot Or Benchmark Later

- Android capture with Play Integrity after the iOS flow is stable
- GLOMAP if measured reconstruction scale or latency makes COLMAP the
  bottleneck
- an alternative commercial-compatible static 3D or Gaussian-splatting
  implementation only if it improves operator inspection materially
- YOLO-World or Cutie only if measured SAM 2 failure modes justify another
  model and dependency
- optical microscopic or calibrated macro capture when consumer-phone imagery
  cannot resolve the required wear, stitch, material, or sole features

### Research Only Unless Licensing Changes

- DUSt3R and MASt3R may be offline benchmarks for difficult, low-feature
  captures, but the published implementations/checkpoints carry non-commercial
  restrictions and must not become a commercial runtime dependency without a
  separate license review.
- The original Inria 3D Gaussian Splatting implementation is likewise a
  research/evaluation reference, not an assumed commercial dependency.
- A research benchmark result is advisory evidence about a candidate pipeline;
  it cannot promote that pipeline into the authority path.

## Security And Truth Boundaries

### App Integrity Is Not Scene Truth

Apple App Attest and Android Play Integrity can strengthen the claim that a
request came from an expected app instance or recognized device environment.
They do not prove:

- that the camera observed the claimed physical shoe
- that the camera was not pointed at a screen or high-quality replica
- that GPS, wall-clock time, or sensor readings are physically truthful
- that the operator has legal ownership
- that no synthetic content entered through another path

The signals must be treated as signed context inputs inside a broader policy
and evidence decision.

### Media Provenance Is Not Factual Truth

Hashes and C2PA manifests can show content binding, lineage, declared edits,
and tamper evidence. They cannot by themselves prove the underlying physical
claim. A valid media manifest can still describe a counterfeit shoe.

### Vision Confidence Is Not Authority

A visual `MATCH` is an observation produced by an admitted evidence adapter.
It can satisfy one policy-required evidence prerequisite only when all of the
following also hold:

- the raw capture and transformation lineage are present
- the capture session binds to the same asset and workflow
- the capture and comparison profiles are policy-admitted and version-pinned
- required quality gates pass
- the evidence is fresh for the relevant custody transition
- the signer and client-integrity evidence meet the policy profile
- the NFC or other hardware anchor binds to the same session when required
- all non-visual delegation, approval, commerce, quarantine, and authority
  gates also pass

The vision adapter never mints an `ExecutionToken`, mutates custody, releases
quarantine, or closes a verifier job.

### Raw Evidence Must Survive Every Derivation

SAM 2 masks, keyframes, point clouds, descriptors, meshes, thumbnails, and
comparison overlays are derived artifacts. The raw media manifest must remain
available to operator forensics and replay according to retention policy.

Public proof should expose redacted hashes, capture phase, verifier outcome,
and safe previews. It must not expose raw NFC material, private location,
unredacted microscopic evidence, device secrets, or restricted operator data.

## Capture And Session Binding

The capture flow should co-bind visual media and physical-anchor evidence to
one server-originated challenge.

```text
SeedCore issues capture_session_id + one-time nonce + expected asset/workflow
  -> mobile app starts guided capture
  -> app obtains fresh NFC challenge-response when the profile requires it
  -> app hashes canonical capture request + media manifest + NFC proof ref
  -> App Attest assertion binds the client-data hash
  -> backend verifies app assertion, nonce, asset, workflow, and freshness
  -> raw media is sealed before derived processing begins
```

The binding should include at least:

```text
capture_binding_hash = sha256(
  contract_version
  + capture_session_id
  + asset_id
  + workflow_join_key
  + capture_phase
  + server_nonce_hash
  + raw_capture_manifest_hash
  + nfc_proof_ref_or_null
  + authorized_device_ref
  + observed_at
)
```

Canonical serialization and versioning are required. A client-supplied hash is
not trusted until the server reconstructs and verifies it from the admitted
fields.

Co-binding narrows replay and substitution opportunities, but it does not prove
physical co-location by itself. The policy profile may additionally require a
short freshness window, operator identity, zone evidence, continuous capture,
or supervised inspection.

## Processing Flow

```text
raw capture + signed session binding + optional NFC proof
  -> immutable raw manifest and retention record
  -> capture-quality evaluation
  -> SAM 2 masks with model/version metadata
  -> COLMAP pose and static reconstruction artifacts
  -> fingerprint extraction and quality summary
  -> origin-to-observation comparison
  -> VisualEvidenceComparisonV0
  -> policy-admitted evidence reference in ActionIntent context
  -> PDP admission decision or policy-directed review / quarantine routing
  -> scoped ExecutionToken only on a complete admitted path
  -> custody attempt and signed transition receipt
  -> replay / RESULT_VERIFIER closure
```

The processing pipeline must fail closed as an evidence producer when required
raw artifacts, bindings, versions, or quality metadata are missing. That
failure does not automatically mean the shoe is counterfeit; it means the
evidence is insufficient for the requested policy path.

## Contract Sketch

### VisualEvidenceObservationV0

`VisualEvidenceObservationV0` represents one capture phase. It is a derived
evidence artifact, not an `ActionIntent` and not an authority artifact.

```json
{
  "contract_version": "seedcore.visual_evidence_observation.v0",
  "evidence_id": "visual-evidence:shoe-001:delivery:001",
  "capture_session_id": "capture-session:001",
  "capture_phase": "delivery",
  "asset_id": "asset:shoe:player-exclusive-001",
  "workflow_join_key": "sha256:workflow",
  "authorized_device_ref": "device:ios:capture-001",
  "observed_at": "2026-08-14T05:00:00Z",
  "server_nonce_hash": "sha256:nonce",
  "capture_binding_hash": "sha256:capture-binding",
  "client_integrity": {
    "profile": "apple_app_attest",
    "assertion_ref": "attest-assertion:001",
    "client_data_hash": "sha256:client-data",
    "verifier_disposition": "verified"
  },
  "physical_anchor_ref": {
    "required": true,
    "nfc_proof_ref": "nfc-proof:001",
    "binding_disposition": "verified"
  },
  "raw_capture_manifest": {
    "artifact_ref": "archive://visual/shoe-001/delivery/001/raw",
    "payload_sha256": "sha256:raw-manifest",
    "frame_count": 180,
    "raw_preserved": true,
    "c2pa_manifest_ref": "c2pa:manifest:001"
  },
  "capture_quality": {
    "profile_ref": "visual-capture-profile:rare-shoe-v0",
    "coverage_disposition": "pass",
    "blur_disposition": "pass",
    "scale_disposition": "pass",
    "calibration_disposition": "pass",
    "quality_metrics_ref": "artifact://visual-quality/001"
  },
  "processing": {
    "segmentation_profile": "sam2:pinned-version",
    "reconstruction_profile": "colmap:pinned-version-and-config",
    "generative_fill_used": false,
    "derived_manifest_hash": "sha256:derived-manifest"
  },
  "fingerprint": {
    "fingerprint_profile_ref": "shoe-spatial-fingerprint:v0",
    "spatial_fingerprint_hash": "sha256:fingerprint",
    "descriptor_artifact_ref": "artifact://visual-descriptors/001",
    "geometry_artifact_ref": "artifact://visual-geometry/001"
  },
  "signer_ref": "signer:visual-evidence-adapter-001"
}
```

### VisualEvidenceComparisonV0

The comparison record binds one later observation to an approved registration
baseline.

```json
{
  "contract_version": "seedcore.visual_evidence_comparison.v0",
  "comparison_id": "visual-comparison:shoe-001:delivery:001",
  "asset_id": "asset:shoe:player-exclusive-001",
  "workflow_join_key": "sha256:workflow",
  "baseline_evidence_ref": "visual-evidence:shoe-001:registration:001",
  "observed_evidence_ref": "visual-evidence:shoe-001:delivery:001",
  "comparison_profile_ref": "shoe-visual-comparison:v0",
  "outcome": "MATCH",
  "confidence_summary": {
    "score": 0.97,
    "calibration_profile_ref": "shoe-visual-calibration:v0",
    "threshold_profile_ref": "policy:rare-shoe-visual-thresholds:v0"
  },
  "quality_disposition": "sufficient",
  "condition_delta_ref": "artifact://condition-delta/001",
  "reason_codes": [],
  "payload_sha256": "sha256:comparison",
  "signer_ref": "signer:visual-evidence-adapter-001"
}
```

The numerical score above is illustrative fixture data, not a production
threshold or claimed accuracy. Production profiles must be calibrated on a
representative dataset and admitted through the normal policy promotion path.

## Outcome Taxonomy

The adapter emits a small, stable evidence taxonomy:

| Adapter outcome | Meaning | Default RCT handling |
| --- | --- | --- |
| `MATCH` | admitted comparison profile found sufficient consistency | may satisfy the visual-evidence prerequisite; every other PDP gate still applies |
| `MISMATCH` | material contradiction with the registered baseline | quarantine with `SPATIAL_FINGERPRINT_MISMATCH` or `CONDITION_DRIFT_DETECTED` |
| `INSUFFICIENT_COVERAGE` | evidence cannot support a comparison | withhold authority when visual evidence is required; recapture or review |
| `ANOMALY_FLAGGED` | suspicious or out-of-profile observation needs inspection | `review_required` or quarantine according to policy |

An adapter outcome and a runtime decision are deliberately separate. For
example, `MATCH` plus an expired approval envelope is still a deny, while
`INSUFFICIENT_COVERAGE` is not equivalent to a counterfeit verdict.

## Stable Reason Codes

Reuse existing rare-shoe reason codes where they already express the failure:

- `SPATIAL_FINGERPRINT_MISMATCH`
- `CONDITION_DRIFT_DETECTED`
- `FORENSIC_VIDEO_BINDING_INVALID`
- `HARDWARE_ANCHOR_MISMATCH`
- `DYNAMIC_NFC_PROOF_INVALID`
- `TELEMETRY_STALE`
- `CROSS_ASSET_REPLAY`

Add visual-adapter-specific codes only where no existing code is precise:

| Reason code | Default outcome | Meaning |
| --- | --- | --- |
| `VISUAL_EVIDENCE_REQUIRED` | `deny` | policy requires a visual evidence ref and none is present |
| `VISUAL_CAPTURE_BINDING_INVALID` | `deny` | capture nonce, asset, workflow, device, raw manifest, or physical-anchor binding does not verify |
| `VISUAL_RAW_CAPTURE_MISSING` | `quarantine` | derived evidence exists but its required raw source archive or manifest is absent |
| `VISUAL_CAPTURE_INSUFFICIENT_COVERAGE` | `review_required` | capture fails the admitted coverage/quality profile |
| `VISUAL_PIPELINE_PROFILE_NOT_ADMITTED` | `deny` | processing or comparison profile is unknown, unpinned, revoked, or outside policy |
| `VISUAL_GENERATIVE_TRANSFORM_DETECTED` | `quarantine` | a generative transform contaminated a forensic artifact path |
| `VISUAL_COMPARISON_UNCALIBRATED` | `review_required` | comparison output lacks an admitted calibration and threshold profile |

The implementation must not collapse `review_required`, `deny`, and
`quarantine` into a single boolean.

## Negative And Replay Fixtures

Contract work should land deterministic fixtures before live-model integration.
The fixture set should include:

1. same asset, same workflow, valid capture and NFC bindings, sufficient
   coverage, visual `MATCH`
2. different shoe substituted at delivery, visual `MISMATCH`
3. same product model but different physical pair
4. sole or heel region omitted, producing `INSUFFICIENT_COVERAGE`
5. motion-blurred or underexposed capture
6. capture manifest changed after the App Attest client-data hash was produced
7. valid visual artifact replayed into another asset or workflow
8. stale capture outside the custody authority window
9. correct static NFC UID but invalid dynamic challenge-response
10. SAM 2 mask error with raw frames still available for review
11. missing raw archive with apparently valid derived descriptors
12. unadmitted model or reconstruction profile
13. generated or inpainted frame inserted into the forensic path
14. condition drift without identity mismatch
15. valid visual match combined with expired delegation or approval, proving
    that vision cannot authorize custody alone

Offline replay must reproduce the binding and policy disposition from artifact
refs and signed manifests without trusting a loose request payload or rerunning
the vision models. Model reruns may be diagnostic comparisons, but the verifier
replays the exact recorded artifacts and admitted profile refs.

## Operator And Public Surfaces

### Operator View

The verification console should show:

- origin, handoff, and delivery capture phases on the custody timeline
- raw-manifest and derived-manifest hashes
- capture-binding and NFC-binding dispositions
- capture-quality gates and missing regions
- pinned segmentation, reconstruction, fingerprint, and comparison profiles
- side-by-side safe previews and optional 3D inspection
- comparison outcome, calibrated score, reason codes, and condition delta
- exact PDP decision, token status, transition receipt, and verifier outcome
- recapture, inspection, and quarantine runbook links

The UI must make `vision outcome` and `SeedCore decision` visibly distinct.

### Public Proof

The public projection may show:

- that origin and delivery visual evidence were hash-bound
- the safe capture phases and timestamps at an appropriate precision
- the final verifier disposition
- a redacted forensic video or image proof ref
- safe model/profile identifiers when useful

It must not expose raw descriptors, high-resolution microscopic captures,
precise private location, device assertion payloads, NFC secrets, or authority-
tier operator evidence.

## Pilot Admission Metrics

The pilot should measure before selecting production thresholds:

- same-pair and different-pair separation across shoes of the same model
- false-match and false-mismatch rates by capture profile
- insufficient-coverage and recapture rates
- sensitivity to lighting, blur, camera model, surface wear, and occlusion
- condition-drift detection separate from identity consistency
- capture time and operator burden
- processing latency, storage cost, and replay artifact size
- percentage of cases requiring human review
- reproducibility of comparisons under pinned profiles
- 100% preservation of raw-to-derived hash linkage in admitted fixtures
- 100% fail-closed behavior for binding, replay, missing-raw, and generative-
  contamination negative fixtures

No model should be promoted from shadow evidence to a policy-required adapter
until the dataset, calibration, failure modes, runbook, version pinning,
rollback, and commercial license have been reviewed.

## Implementation Slices

### Slice V0: Contract Freeze

- land `VisualEvidenceObservationV0` and `VisualEvidenceComparisonV0` schemas
- freeze capture phases, outcome taxonomy, and reason codes
- define canonical serialization and capture-binding hash construction
- define raw/derived artifact retention and redaction rules
- add schema and hash-vector tests

### Slice V1: Deterministic Fixtures

- add happy-path and all negative fixture payloads
- extend the rare-shoe replay bundle with visual evidence refs
- add verifier tests for asset/workflow/session binding
- prove `MATCH` cannot bypass delegation, approval, token, or quarantine gates
- prove replay works without rerunning SAM 2 or COLMAP

### Slice V2: Offline Capture And Processing Spike

- build one local iOS guided-capture prototype or fixture-equivalent capture
- preserve raw frames and generate the signed raw manifest first
- run SAM 2 and COLMAP behind a SeedCore-owned adapter interface
- emit pinned processing metadata and derived artifact hashes
- keep the spike shadow-only and outside live execution authority

### Slice V3: Visual Comparison Benchmark

- collect consented captures for a small but intentionally difficult shoe set
- include multiple pairs of the same model and size where possible
- evaluate identity consistency separately from condition drift
- calibrate quality gates and comparison scores
- document failure modes, licensing, compute, and operator burden
- select `continue`, `revise`, or `stop` based on measured evidence value

### Slice V4: Gateway And Verifier Integration

- admit only version-pinned evidence refs through typed gateway context
- add PDP fixtures for required, optional, stale, mismatch, and review paths
- materialize comparison refs into evidence bundles and operator forensics
- add quarantine and recapture runbook mappings
- keep all existing NFC, approval, commerce, token, and replay gates intact

### Slice V5: Supervised Pilot

- run shadow evaluation alongside the existing rare-shoe RCT demo
- require human review for ambiguous or anomalous visual outcomes
- promote a visual prerequisite only after pilot admission review
- retain a kill switch and profile rollback path
- publish a redacted proof example that distinguishes media provenance,
  physical evidence, policy decision, and custody closure

## Explicit Non-Goals

- no sneaker marketplace
- no legal-title assertion
- no global Journey 4Map
- no venue or tourist-discovery platform
- no continuous 4D scene reconstruction
- no blockchain or smart-contract registry requirement
- no generative completion of missing forensic evidence
- no claim that app or media attestation proves a genuine physical shoe
- no vision model directly issuing or widening an `ExecutionToken`
- no visual match directly closing custody or releasing quarantine

## Acceptance Criteria

The v0 plan is correctly implemented when:

1. every derived visual artifact links to preserved raw evidence and a canonical
   capture-session binding
2. capture, NFC, asset, workflow, device, and freshness bindings fail closed
   where policy requires them
3. visual `MATCH` remains only one evidence prerequisite and cannot bypass any
   authority gate
4. visual mismatch, condition drift, insufficient evidence, and anomalous
   evidence remain distinct outcomes
5. generative contamination cannot enter authentication, comparison, PDP, or
   verifier closure
6. offline replay validates recorded artifacts, hashes, profiles, decisions,
   receipts, and outcomes without rerunning probabilistic models
7. raw authority-tier evidence is available to authorized operator forensics
   but excluded from public proof
8. commercial dependency and model licenses are reviewed before promotion
9. negative fixtures prove cross-asset replay, missing raw evidence, stale
   capture, profile mismatch, and expired non-visual authority all fail safely
10. the application remains a vertical specialization of SeedCore RCT rather
    than a parallel computer-vision product

## Upstream References For Dependency Review

These links are research and implementation references, not endorsements or
authority sources. License and release status must be rechecked at adoption
time.

- Apple DeviceCheck and App Attest:
  <https://developer.apple.com/documentation/devicecheck>
- Android Play Integrity:
  <https://developer.android.com/google/play/integrity/overview>
- C2PA specifications: <https://spec.c2pa.org/specifications/>
- SAM 2: <https://github.com/facebookresearch/sam2>
- COLMAP: <https://github.com/colmap/colmap>
- DUSt3R: <https://github.com/naver/dust3r>
- MASt3R: <https://github.com/naver/mast3r>
- Inria 3D Gaussian Splatting:
  <https://github.com/graphdeco-inria/gaussian-splatting>

## Related SeedCore Docs

- [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md)
- [`current_next_steps.md`](current_next_steps.md)
- [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md)
- [`physical_telemetry_processing_contract.md`](physical_telemetry_processing_contract.md)
- [`virtual_nfc_simulation_plan.md`](virtual_nfc_simulation_plan.md)
- [`persistent_counter_ledger_plan.md`](persistent_counter_ledger_plan.md)
- [`kms_ntag_transition_plan.md`](kms_ntag_transition_plan.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md)
