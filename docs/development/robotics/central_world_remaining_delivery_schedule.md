# Central World: remaining delivery schedule

Date: 2026-10-22
Status: Phase 2 offline and CW-S01 synthetic compiler/native-parity slices passed locally; CW-S01 real-source handoff and CW-S02 browser acceptance remain open

The [master engineering plan](central_world_engineering_plan.md) owns the
12-week calendar, architecture and CW gate definitions. This document owns the
remaining work-package order, owner roles, dependencies and review artifacts.
The [acceptance matrix](central_world_acceptance_matrix.md) owns the required
positive, negative and fault evidence. CW-A01 has a verified v2 authoring candidate;
the entries below describe required acceptance and remaining work. A draft
schema or schedule does not grant permission to operate hardware.

## Baseline and execution order

Phase 1 software is committed as `c16b805`: strict component schema, 12 draft
records, original GLB proxies, native Microduck reference, read-only viewer and
validation. The combined registry/read-only/model suite passed 107 tests,
including 29 registry checks. Local Chrome rendered all 12 meshes; desktop and
mobile viewport checks passed. These are software/proxy checks, with no exact
supplier data, physical fit, trained-policy compatibility or hardware approval.

The [CW-A01 exit record](central_world_cw_a01_acceptance_plan.md) now addresses
the eight findings from draft `9c5aaf7` in assembly v2. Local software acceptance
passed 117 Python and 71 Node tests. The
[CW-A02 entry/acceptance record](central_world_cw_a02_authoring.md) now records
the bounded offline authoring slice, dependency/license decision and browser/store
evidence. The [CW-A03 placement record](central_world_cw_a03_snapping.md) now
adds local snapping/ghost/numeric/subtree evidence. The
[CW-A04 DRC/BOM record](central_world_cw_a04_drc.md) closes Phase 2's offline
software scope with pure worker DRC, routing proposals, field-linked findings,
3D rotated/parallel-axis mass/inertia and unknown-aware BOM. The **CW-S01 restricted
assembly-to-MJCF compiler/native-parity slice** is implemented on synthetic
supported serial-tabletop fixtures; real-source readiness/handoff is next,
followed by separately pinned CW-S02 browser runtime qualification.
Keep **CW-D01** open in parallel for data collection;
unknown physical facts block physical readiness, not graph/UI development.
Missing Microduck checkpoint outputs block its locomotion policy lane, not a
separately declared fixed-base tabletop gesture simulation.

Use one active implementation package per implementer. Owner roles are
responsibilities, not assumed staffing or public personal assignments. Before
starting a package, record its owner role, bounded effort, exact supported
subset, dependency pins, acceptance fixtures and review date. Resolve repeated
deterministic failures from their evidence; do not weaken thresholds to preserve
the calendar. No spending, procurement or external contact is authorized here.

| Owner role | Responsibility |
| --- | --- |
| Integration lead | Dependency/capacity decisions, contract versions and gate review |
| Catalog/mechanical curator | Exact sources, drawing/port/frame and electrical data review |
| Studio/TypeScript lead | Pure graph/DRC code, canvas/store adapters and browser UX |
| Simulation/policy lead | MJCF compiler, native/browser parity, bounded workers and policy compatibility |
| Trust/firmware lead | Live admission, enrollment, immutable device limits and update/recovery evidence |
| Verification/delivery reviewer | Independent negative cases, scoped replay, operator lesson and launch packet |

## Carry-over: qualified data (Week 2, 26 October–1 November)

| ID | Deliverable / owner | Entry and review evidence | State |
| --- | --- | --- | --- |
| CW-D01 | Exact first ESP32-S3 board, servo, power and chassis records; catalog/mechanical curator | Identify SKU/revision, dated source/quote, pin ownership, connectors/rails, tolerances, source rights, sensor frames and hard limits. Preserve current drafts; create new reviewed revisions rather than mutating saved-build identities. | [19 Oct inventory recorded](m0_cw_d01_register_2026_10_19.md); exact unit/drawing/ratings qualification open |

CW-D01 closes only for the selected profile. Do not require all 12 families to
be qualified before the first tabletop alpha. Tuya T5, SG90/camera variants and
additional bodies may stay draft. A proxy-only assembly remains a valid offline
development fixture and must remain visibly unqualified.

## Phase 2: assembly and DRC (Weeks 3–5, 2–22 November)

| ID / target | Deliverable / proposed home | Depends on | Owner / exit artifact |
| --- | --- | --- | --- |
| CW-A01 · W2–W3 | Versioned assembly contract, canonical digest rules and fixtures; component-registry schemas with additive TS contract bindings | CW1 software | Integration + Studio: schema/golden report for nodes, occupied ports, mechanical tree, electrical nets and explicit joints; graph edits/imports reject invalid candidates atomically |
| CW-A02 · W3 | Mini Studio shell, immutable draft store, selection, undo/redo and canvas adapter; `ts/apps/mini-studio` and `ts/packages/robot-canvas` | CW-A01 | Studio: [19 Oct local slice](central_world_cw_a02_authoring.md) includes dependency/license decision, first starter import/export, keyboard selection, stale-asset failure and browser report; later authoring/DRC/physics remain separate |
| CW-A03 · W4 | 15 mm candidate snapping, mating transform, ghost preview and accessible numeric placement | CW-A01, CW-A02 | Studio + mechanical curator: [19 Oct proxy slice](central_world_cw_a03_snapping.md) passes transformed-parent, normal/twist, occupied-port/cycle, deterministic candidate and undo checks; physical mating remains unqualified |
| CW-A04 · W5 | Pure DRC worker, routing proposals, field-linked findings and unknown-aware BOM; `ts/packages/drc-solver` | CW-A01, CW-A02; CW-D01 for physical pass | Studio + reviewer: [20 Oct offline slice](central_world_cw_a04_drc.md) passes UART/I2C/GPIO/rail/mass negative matrix, epoch-fenced stale-worker rejection and reviewed starter findings; synthetic fixtures labeled as such; physical pass remains gated on CW-D01 |

CW-A01 separates rigid mounting from kinematic articulation. A snapped edge is
not automatically a revolute joint, and an actuator capability does not define
a pivot or axis. Specify fixed/revolute joint records, rest transforms, unit
axis/pivot frames, stable joint IDs, output versus housing attachment, actuator
mapping and permitted ranges for the initial supported subset. The present
component schema has no complete articulated-output model. Any needed extension
requires a reviewed version and fixtures; do not infer these facts from a box
mesh, port normal or part name.

The [v2 implementation](../../../packages/component-registry/assemblies/README.md)
meets the initial contract with assembly-owned, explicitly labeled proxy output
declarations and direct-parent actuation. Component v1 stays unchanged; those
declarations do not claim real servo-horn geometry or hardware channel ratings.
CW-A02 must use v2 and add the browser text-import/immutable-store path; it must
not treat the structural TypeScript validator as full catalog/DRC qualification.

Freeze graph bounds, canonical number/property handling and cross-language hash
fixtures before binding later admission to a build. Reference exact part bytes,
versions and asset digests. Every successful edit creates a new revision;
undo/redo restores a revision, not an old runtime admission.

DRC groups actual compatible bus/protocol/voltage/duplex resources. Servo IDs
are unique within a reviewed bus/profile, not a global `1..N` assignment that
mixes Feetech and Dynamixel. I2C checks addresses and pull-ups. GPIO checks the
named board's reserved/shared functions. Power checks each rail, conversion,
headroom, wiring/fusing and thermal capacity; a distribution board is not a
higher-capacity source. A missing value yields **blocked**, not zero load.
Findings bind the exact assembly/electrical-plan digest and never grant motion.

**Phase exit:** a maker can assemble the one supported proxy/reviewed starter,
see reproducible findings and preserve its revisions. The two-minute assembly
target must be measured with a named starter/browser/user task. A proxy pass
does not close CW-D01, native M2 or physical G2.

## Phase 3: physics, policies and Robot Moments (Weeks 6–8, 23 November–13 December)

The optional [browser performance lab](browser_performance_pipeline.md) now
provides transport/display infrastructure evidence on the existing synthetic
planar backend. It is a supporting experiment, not completion of CW-S02's
MuJoCo/model/control/capture acceptance. Its stack table records later SIMD,
policy and remote-compute qualification without changing these dependencies.

The supporting [static scene lab](static_scene_streaming.md) now adds pinned
Draco HLOD streaming and origin rebasing on original visual-only mini-workbench
data. Static rendering is independent of model/control/capture qualification.

| ID / target | Deliverable / proposed home | Depends on | Owner / exit artifact |
| --- | --- | --- | --- |
| CW-S01 · W6 | Restricted assembly-to-MJCF compiler; `ts/packages/wasm-sim-bridge` | CW-A01, CW-A04; explicit joint model | Simulation: first fixed-base tabletop subset, generated primitive geometry/inertials/actuators, native MuJoCo compile/FK/mass/range comparison and unsupported-subset report |
| CW-S02 · W7 | Pinned browser MuJoCo worker adapter, clocks, bounded buffers and runtime profiles | CW-S01; selected engine/build review | Simulation + Studio: native/browser parity, worker/resource/fault report, isolation/header/embedding tests and named-device timing; no silent planar fallback |
| CW-S03 · W7–W8 | Compatible ONNX adapter and skill manifest candidate; `packages/skill-packages` | CW-S02 plus independent policy/model references | Simulation/policy: policy bytes/license/export provenance, explicit observation/action map and input/output/timing parity; unsupported body/policy combinations refuse to run |
| CW-S04 · W8 | Joint/LED gesture timeline, bounded interpolation, simulation trace and replay projection | CW-A01, CW-S02; CW-S03 only for policy-driven behaviors | Studio + verification: authored wave/tilt fixture, curve-extrema/loop/edit tests, stop/fault/coverage report and scoped outcome display |

Keep CW-S01 within declared primitive geometry and at most the reviewed tabletop
joint subset. GLB visualization alone is not a valid MuJoCo articulation or
mesh-conversion path. Broader branched/floating-base/CAD imports need separate
support and parity evidence. Keep native Microduck as an imported pinned model;
do not rebuild it with STS3215/ESP32 draft parts or change its controller ownership.

The [21 October CW-S01 record](central_world_cw_s01_mjcf.md) delivers the local
compiler/native-parity slice on synthetic sources. The user-approved separate
offline readiness policy defers only `MECHANICAL_PROXY_UNQUALIFIED`; the full
DRC result stays unchanged and all other findings block compilation. The real
starter remains blocked; resolving its data/handoff is separate from passing
the synthetic slice. CW-S02/browser and hardware acceptance remain open.

CW-S02 explicitly distinguishes the current planar custom engine from general
MuJoCo Wasm. Freeze engine version, compiler options, model digest, physics dt,
policy cadence and capture units. Simulation workers own state; rendering and
host/browser stalls cannot silently enlarge dt or drop required capture.
Qualify an explicit single-thread profile if offered. Local top-level isolation
does not establish that a portal/subdomain/iframe deployment is isolated.

Use the [mjswan source assessment](mjswan_integration_assessment.md) as the
CW-S02/CW-S03 candidate decision. Start with API feasibility: the reviewed 0.11.9
engine lacks a public per-control veto, worker state-ownership contract and full
telemetry export. Its MuJoCo 3.11.0 pin needs explicit reconciliation with
SeedCore 3.15.0; do not install it into the frozen environment. Qualify a small
generic extension before performance/policy work, or rescope to official Wasm
bindings under the same adapter contract if a large private fork is required.

CW-S03 is conditional for Microduck locomotion: exact checkpoint/export outputs
and runtime/model/policy compatibility are still open. Its 61/14 mapping is not
the action space of an arbitrary custom robot. Do not change frozen tolerances
to force WebGPU/Wasm parity. A keyframed tabletop gesture provides a useful
alpha path without claiming a balancing biped or a trained-policy transfer.

Within CW-S04, optionally import an LLM-drafted **declarative gesture JSON**
through the same bounded parser and compilation path as manual edits. Resolve
the named attachment/build and joint IDs, explicit units and interpolation;
check full-curve position/velocity/acceleration extrema and any supported
mode-specific bounds, loops and time scaling. A prompt such as “tilt the head
15 degrees” still needs an unambiguous joint/frame and feasible trajectory.
Keep camera/network effects separate and declared. DRC supplies assembly/power
readiness findings; it does not verify arbitrary motion or contact. Recompile
and invalidate admission after any draft edit. Native/browser model checks
cover declared tolerances; physical motion still needs CW-G01 and hardware
acceptance. A cloud account or LLM connector is not an alpha prerequisite.

The reviewed mjswan policy backend is Wasm-only. Its mjlab 1.6.0 exporter also
differs from the inspected Microduck training pin, mjlab 1.3.0. Preflight exact
task/actuator semantics and independent outputs in an isolated environment;
the upstream export skill does not establish automatic Microduck compatibility.

Skill packages initially contain declarative bounded data, not arbitrary
privileged scripts. Publisher provenance, compatibility and requested
capabilities do not authorize execution. Retain upstream licenses and notices;
the motion-editor snapshot remains a design reference until reuse permissions
are established. A separately authored timeline can proceed.

**Phase exit:** the supported starter runs one reproducible gesture with complete
scoped simulation replay and measured device/runtime behavior. A 60 FPS display
goal is separate from the policy/control rate and physical stopping evidence.

## Phase 4: trust, export and conditional provisioning (Weeks 9–10, 14–27 December)

| ID / target | Deliverable / proposed home | Depends on | Owner / exit artifact |
| --- | --- | --- | --- |
| CW-G01 · W9 | Reviewed build-freeze/capability-request contract and live Agent/PDP integration; existing robotics/gateway boundary | CW-A01, CW-A04, CW-S04; trusted profile evidence for hardware | Trust + verification: proposed versus granted limits, digest/signer context, exact existing-token binding and negative authority matrix |
| CW-G02 · W9–W10 | Scoped robot replay adapter into the existing verification/operator surfaces | CW-G01, retained traces; applicable signer evidence | Verification + Studio: source/binding/coverage projection, Python/Rust agreement and missing/conflicting/revoked-key quarantine cases; no replay write authority |
| CW-E01 · W10 | Reproducible design Build Pack exporter | CW-A04, CW-S04; rights and printable CAD for claimed print files | Studio + delivery: artifact/hash inventory, unknown-cost count, reviewed-net SVG, safe CSV/ZIP tests and explicit draft/qualified status |
| CW-F01 · W10, conditional | One-board firmware/configuration ABI and NVS golden comparison | CW-D01, actual reviewed ESP-IDF source/build/partition table; CW-G01 | Trust/firmware: source/build manifest, official-generator byte fixtures, config signature/digest limits and wrong-profile rejection; no device secrets in public partitions |
| CW-F02 · After CW-F01, conditional | ESP32-S3 installer/enrollment and one-servo → three-servo acceptance | CW-F01, device/ingress review, operator fixture and relevant G1 | Firmware + independent reviewer: boot/update/nonmoving state, watchdog/local stop, revocation, capture, signer and interrupted-flash/recovery measurements; physical demonstration also requires G2 |

CW-G01 freezes content as a candidate. A trusted service validates registered
endpoint/body/firmware/configuration context and signs a reviewed capability
profile only under its existing admission rules. Per-joint/resource limits
intersect device, operator/deployment policy and behavior request. Signing or
hashing a browser draft does not enroll it. Map reviewed scope through existing
payload/digest bindings; a change to frozen token fields needs explicit contract
review. Replaying a simulation trace never becomes physical admission.

CW-G02 extends existing read-only replay contracts. Preserve original artifacts
and exact verifier scope; do not convert host-signed simulated state into device
telemetry or treat a queue ACK as completion. Explain incomplete evidence using
the existing verifier/runbook path. New robot projections need additive schema
review; this schedule introduces no shipped endpoint or deny code.

CW-E01 may export a draft design record before hardware is ready. Include only
owned/licensed print-ready files when they actually exist; current GLB proxies
are not printable chassis. Wiring must identify unresolved nets rather than
invent connections. Export validation neither signs a hardware profile nor
establishes firmware readiness.

CW-F01/CW-F02 are a dependency lane, not a promise to create universal firmware
in two weeks. The repository currently has review-packet preparation tooling,
not a matching firmware image. Do not publish a fake binary, populated install
manifest or active flash control while these gates are open. Tuya T5 requires a
separate platform/update profile; Microduck follows its native runtime.

**Phase exit:** live scoped admission/replay and a correctly labeled design pack
for the supported simulation profile. Physical provisioning remains unavailable
unless the conditional lane supplies its own complete acceptance evidence.

## Phase 5: curated gallery and alpha review (Weeks 11–12, 28 December–10 January)

| ID / target | Deliverable / proposed home | Depends on | Owner / exit artifact |
| --- | --- | --- | --- |
| CW-L01 · W11 | Curated gallery manifest, local fork flow and source/license lineage; Mini Studio | CW-A01, CW-E01 | Studio + delivery: pinned entries/assets, safe preview, unavailable-dependency rejection and fork identity tests; no public write/upload API initially |
| CW-L02 · W11–W12 | Robot Moments lesson, operator help and site/embedding candidate | CW-S04, CW-G02, CW-L01 | Delivery + Studio: independent inspect → customize → rehearse → inspect result → export exercise; browser/keyboard/help/stop and privacy review |
| CW-L03 · W12 | Alpha release decision and publication candidate | CW-L02; all claims backed by the applicable gates | Integration + reviewer: exact source/build/artifact set, measured task/setup/support results, documented exclusions, rollback/support owner and go/rescope/defer decision |

Forks preserve source/license ancestry but receive new unqualified revisions.
Never carry a publisher's hardware qualification, signature, token or device
identity into an edited build. Third-party part PRs require independent schema,
asset rights/integrity, frame/dimension and electrical review before curation.
The existing draft registry is not a community trust root or an upload sandbox.

The January default is an authoring/simulation alpha. Reproduce the exercise
with an independent adult maker on named supported browsers; record failures
and assistance needed. Do not turn unmeasured two-minute assembly, 60 FPS,
three-minute provisioning or classroom adoption goals into launch claims.
Public hosting, DNS/account configuration, external outreach and community
publication require their own explicit authorization. A launch review packet
does not execute those actions.

## Handoffs and decision record

At each exit, attach source/contract/dependency pins, supported subset, fixture
inputs, positive and negative reports, runtime/profile label, retained traces,
known gaps and a reviewer decision. Store private operator/account information
outside public documents. Version a changed contract or budget and rerun affected
acceptance; a new date alone never advances a gate.

| Decision | Minimum recorded basis |
| --- | --- |
| Go | Required artifacts pass for the exact supported scope; next dependencies available |
| Continue proxy/offline work | Software checks pass; qualified data or hardware remains open and claims stay scoped |
| Rescope | Reduce supported bodies/features or move dependent dates while retaining failed evidence |
| Defer physical/public release | Missing device trust, stopping/capture/recovery, source rights, hosting review or repeat delivery evidence |

The [active queue](../current_next_steps.md) identifies the next package. The
master plan retains weekly dates; avoid maintaining separate competing calendars
inside implementation, partner or lesson documents.
