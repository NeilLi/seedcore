# Central World: acceptance and suggestion traceability

Date: 2026-10-19
Status: Phase 1, CW-A01 v2 and CW-A02 local offline software evidence available; later gates open

Use with the [master plan](central_world_engineering_plan.md) and
[remaining delivery schedule](central_world_remaining_delivery_schedule.md).
The IDs below are planning/review references, not runtime reason codes or new
production contracts. A passing software test does not authorize a device.

The CW-A01 draft `9c5aaf7` had eight reproduced review findings. The
[v2 exit record](central_world_cw_a01_acceptance_plan.md) now maps each to passing
regression evidence: 117 Python and 71 Node tests, independent numeric fixtures,
live cross-language parity and a build with no preexisting contracts output.
CW-ASM-01's initial offline software scope passes locally. The
[CW-A02 record](central_world_cw_a02_authoring.md) adds CW-ASM-02 store/browser
evidence: immutable revisions, selection, undo/redo, raw import, stale/failed
asset rejection and recovery. DRC, dynamics and hardware acceptance remain open.
The [19 October source inventory](m0_cw_d01_register_2026_10_19.md) records the
window review without closing CW-CAT-01 qualification.

## Required evidence by work package

| Review ID / owner package | Positive case | Required rejection or fault case | Retained review artifact |
| --- | --- | --- | --- |
| CW-CAT-01 / CW-D01 | Exact revision, source and drawing/ratings resolve for the chosen board/servo/rails | Missing SKU, unknown rating, changed drawing/asset, unqualified mount | Versioned profile/source register; unknowns explicitly open |
| CW-ASM-01 / CW-A01 | Same reviewed assembly serializes/imports with stable joint/part references and digest | Changed part bytes/version; missing node/root; cyclic/multiple-parent graph; duplicate occupied port; unsupported joint model | Contract/golden hash and atomic-import/edit report |
| CW-ASM-02 / CW-A02 | Selection and undo/redo preserve immutable revision contents | Slow/failed asset fetch or stale async result overwrites a newer build | [CW-A02 browser/state report](central_world_cw_a02_authoring.md) with exact revision joins; local software slice passed |
| CW-SNAP-01 / CW-A03 | Child aligns under a translated/rotated parent with declared mate transform | Quaternion order/norm error, incompatible gender/standard, bad normal/twist, invalid graph after drop | Numeric transform fixtures and visual/keyboard exercise |
| CW-DRC-01 / CW-A04 | Compatible bus/protocol/voltage receives stable unique device IDs and valid resources | Mixed protocols, duplicate/unsupported IDs, unavailable/boot/USB/flash pin, duplicate I2C address or incompatible pull-up/logic voltage | Findings tied to build/net digest and field refs |
| CW-DRC-02 / CW-A04 | Per-rail peak/continuous load fits reviewed derated conversion and wiring budget | Unknown load/rating, brownout margin missing, overloaded BEC/wire/fuse, double-counted MCU or summed currents at unlike voltages | Power calculation with explicit assumptions and blocked/conflict distinction |
| CW-DRC-03 / CW-A04 | COM/inertias and BOM use common units and declared component transforms | Inertia about wrong origin/units; discarded off-diagonal terms; unknown price treated as free | Model/mass checks and cost subtotal plus unpriced count |
| CW-SIM-01 / CW-S01 | Supported fixed-base assembly compiles and matches native FK/mass/joint/actuator reference | Inferred joint axis, unsupported branch/root, invalid inertia, asset traversal, stale DRC/model digest | Generated model/source digest and native parity report |
| CW-SIM-02 / CW-S02 | Named browser engine/profile reproduces the frozen reference within declared tolerances | Missing Wasm, version/build mismatch, numerical divergence, worker failure or unsupported model silently uses planar preview | Explicit runtime/profile and native/browser parity/failure report |
| CW-SIM-03 / CW-S02 | dt/policy/render clocks and complete bounded capture survive a UI stall | Catch-up enlarges dt, queue/buffer overflow, hidden tab resumes old attempt, required samples lost | Clock/buffer/coverage trace and stop outcome |
| CW-SIM-04 / CW-S02, CW-G01 | State-owning executor gates processed controls at each substep and discards stale async output | UI-only/raw-output hook misses command joints, external PD, reset/event/force mutation or an expired/revoked attempt; policy switch reuses admission | Mutation-path inventory, veto/coverage fixtures and generation/deadline trace; simulation enforcement does not establish hardware trust |
| CW-POL-01 / CW-S03 | Correct pinned policy/model/adapter meets independent export/training and timing references | Changed body/joint order/normalization/home, missing checkpoint output, nonfinite/unbounded action, unsupported operator or inference deadline | Input/output vectors, artifact provenance and refusal report |
| CW-MOM-01 / CW-S04 | Joint/LED gesture has declared units, interpolation and bounded extrema | Endpoints pass but intermediate curve exceeds bounds; loop/time-stretch/edit reuses old admission; undeclared camera/network output | Compiled behavior identity, extrema and edit-invalidation report |
| CW-AUTH-01 / CW-G01 | Trusted service admits the exact reviewed build/behavior/endpoint under current delegation | Browser self-signs profile; missing registration/context; expired/future/forged/replayed/revoked/wrong-endpoint token; changed config/profile/payload | Existing-token admission/claim/dispatch trace; rejected cases dispatch no motion |
| CW-AUTH-02 / CW-G01, CW-F02 | Bounded refresh proceeds until admitted deadline; local stop remains effective | Heartbeat extends intent, stale authority/command, wall/monotonic rollback, reconnect or packet clears latched stop | Local fence/queue/state trace; no automatic resume |
| CW-EVID-01 / CW-G02 | Independent expected bindings and trusted keys verify complete captured evidence under its true scope | Missing/gapped/stale/conflicting samples; reused action/boot/config refs; bad/revoked signer; host simulation labeled as hardware | Original receipt/bundle plus verifier disposition and source refs |
| CW-PACK-01 / CW-E01 | Deterministic design archive has declared hashes, rights and unresolved-cost/net status | Path traversal, oversized/decompression payload, CSV formula, changed asset, unlicensed/missing CAD or proxy called print-ready | Archive inventory, extraction/CSV tests and draft/qualified projection |
| CW-NVS-01 / CW-F01 | Reviewed config ABI matches pinned official-generator bytes and actual partition layout | Truncated/wrong namespace/type/blob/page data, wrong board/offset, unsigned or stale/broader limits, embedded private keys | Golden partitions, configuration digest/signature and layout checks |
| CW-HW-01 / CW-F02 | Accepted one-servo fixture progresses to three with measured failure response | Browser/link/cloud loss; bad ingress; MCU reset/brownout; local stop; signer/capture failure; interrupted flash and rollback | Board/image/config/fixture pins; separate propagation, response-initiation and observed-stop measurements |
| CW-GAL-01 / CW-L01 | Curated pinned build forks with source/license ancestry and a new identity | Fork inherits token/qualification/device identity; missing dependencies; unreviewed asset becomes trusted | Fork/curation report and immutable lineage record |
| CW-UX-01 / CW-L02 | Independent adult maker completes the named alpha task and can inspect/stop/recover | Keyboard-only path blocked; unexplained failure; account/camera/egress required for basic simulation; stale results look current | Task observation, help/assist log and accessibility/privacy findings |
| CW-REL-01 / CW-L03 | Reviewed publication candidate has supported scope, deployment/rollback plan and support owner | Missing host/account authorization, unqualified physical claim, failed package gate or unresolved repeat-delivery issue | Go/rescope/defer record tied to exact release artifacts |

Fixtures can use synthetic electrical/model data for software tests. Label that
provenance and keep hardware qualification open. A test fixture's trusted key
is never a production enrollment root. Test missing-tool/dependency skips must
be reported as missing acceptance rather than successful parity.

## Measurements to freeze before evaluation

| Goal | Required measurement | Claim boundary |
| --- | --- | --- |
| Two-minute assembly | Named starter, initial state, user instructions, device/browser, assistance and task success | A target until independently observed; generic or unfamiliar robots are separate cases |
| Responsive 3D/60 FPS | Frame-time distribution, dropped work, scene/model size and thermal/load conditions | Rendering is distinct from physics/policy cadence and is not a real-time safety guarantee |
| 50 Hz policy | Inference timing/backpressure, observation freshness, deterministic adapter and compatible model | Microduck-specific policy contract; not universal custom-build support |
| Threaded browser Wasm | Actual isolation/secure context, workers and cross-origin asset/portal arrangement | Local top-level success does not qualify an embedded deployment or every Chromebook |
| Under-three-minute provisioning | Permission selection, image/config transfer, enrollment, verification, boot readiness and recovery separately | No claim while firmware/board/profile or recovery is unqualified |
| Stop behavior | Revocation propagation, local response initiation and observed stopping time/distance under load | Configured watchdog polling or queue ACK is not measured physical stopping |
| BOM and delivery cost | Dated SKU/volume, known subtotal/unpriced count, power/assembly/test/yield/shipping/support boundaries | Draft family costs remain unknown; no purchase or pricing promise |

Freeze numerical parity/latency/resource thresholds in the profile before
running acceptance. Record failures and proposed changes as new reviewed
revisions. Do not widen tolerances, hide dropped capture or reduce the test
matrix merely to obtain a green result.

## Blueprint suggestions and their implementation boundary

| Suggested feature | Applied engineering decision | Delivery owner |
| --- | --- | --- |
| Open `.sc-part.json` catalog | Delivered draft schema/index/GLBs; exact supplier/physical qualification remains CW-D01 | Component registry + CW-D01 |
| Magnetic 3D assembly | Add explicit graph/joint model and mate transform; validate atomic edits; 15 mm is only the capture proposal | CW-A01–CW-A03 |
| Automatic electrical wiring | Produce reviewable nets/findings per protocol, logic voltage and actual GPIO; unknown data blocks readiness | CW-A04 |
| Power warning and distribution recommendation | Per-rail capacity/efficiency/derating; distribution alone does not supply more power | CW-A04 |
| Dynamic MJCF from snapped parts | Compile a declared supported articulation subset and compare natively; part port normals alone cannot define joints | CW-S01 |
| mjswan + existing mini-sim | Conditional 0.11.9 candidate; [assessment](mjswan_integration_assessment.md) requires engine-version reconciliation, worker/control/capture seams and parity; retain the planar engine | CW-S02 |
| ONNX locomotion | Body/policy-specific adapter and independent references; missing Microduck checkpoint parity keeps that lane closed | CW-S03 |
| Robot Moments timeline | Declarative bounded gestures/LED outputs, edit invalidation and retained replay; no unreviewed privileged scripts | CW-S04 |
| Signed Hardware Capability Profile | Browser submits a candidate; enrolled trusted service validates/signs under reviewed policy; no authority from catalog self-assertion | CW-G01 |
| Green “Verified Safe” badge | Show exact scope/disposition: simulation evidence verified, hardware qualification open, interruption or quarantine | CW-G02 |
| Universal ESP32-S3/Tuya firmware | First qualify one exact ESP32-S3/TTL profile; Tuya and native Microduck retain separate deployment paths | CW-F01–CW-F02 |
| Browser JSON/CBOR → NVS | Require real configuration ABI/partition layout, official-generator goldens and authenticated bounds; no raw-JSON-as-NVS shortcut | CW-F01 |
| Printable/wiring/BOM ZIP | Ship only real owned/licensed print assets and reviewed-net drawings; flag unpriced/unknown/draft state | CW-E01 |
| Public gallery and part PRs | Curated local/read-only gallery first; preserve lineage, review contributions and separately authorize publication | CW-L01–CW-L03 |

## Exit packet

Each package review records: work-package ID, source/contract/dependency pins,
supported profile and input digests, positive and negative evidence, observed
measurements versus frozen thresholds, skipped/unavailable checks, known gaps,
reviewer role and decision. Execution reviews also retain token/claim/session
and signer context; keep private identities/credentials out of public documents.

Only mark the applicable gate passed for the exact supported scope. Preserve
the distinction between authored data, DRC readiness, admitted authority,
attempted behavior and verified outcome. The [active queue](../current_next_steps.md)
must reflect rescope/defer decisions and their dependent dates.
