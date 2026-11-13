# Current Next Steps

Date: 2026-11-12
Status: Canonical active execution queue — local gallery, lesson and CW-L02 source-bound trial preparation delivered; independent maker observation not tested and CW-L03 release deferred; physical and production gates remain open

The CW-A02 offline Mini Studio authoring slice is locally implemented: v2 raw
import/export, immutable revisions, selection, undo/redo and stale-load rejection.
Its [entry and acceptance record](robotics/central_world_cw_a02_authoring.md)
records the canvas decision and software evidence. The [CW-A03 proxy placement slice](robotics/central_world_cw_a03_snapping.md) now
adds magnetic candidates, non-committing ghosts and atomic numeric/subtree
placement. The [CW-A04 DRC/BOM slice](robotics/central_world_cw_a04_drc.md) closes
Phase 2's offline software scope with pure worker DRC, routing proposals,
field-linked findings, 3D rotated/parallel-axis mass/inertia and unknown-aware BOM.
The [CW-S01 compiler/native-parity slice](robotics/central_world_cw_s01_mjcf.md)
is now implemented for synthetic supported serial-tabletop fixtures. A separate
versioned offline simulation-readiness result defers only proxy physical fit;
the full DRC report and actual starter remain blocked. The 23 October Studio
handoff adds an explicitly synthetic offline reference, readiness/manifest
inspection and deterministic XML/model exports. The reviewed CW-S02 worker now
adds pinned single-thread MuJoCo, full 120-step native/Chrome parity at explicit
`dt=0.002`, position `kp=1` or ideal torque, and bounded control/capture fences.
The [26 October CW-S03 preflight](robotics/central_world_cw_s03_preflight.md)
now reproduces available artifact replay and reports both native and tabletop
policy candidates blocked with exact reasons. The
[28 October CW-S04 slice](robotics/central_world_cw_s04_gestures.md) now provides
bounded declarative target curves, a virtual LED cue, per-step simulation
controls and read-only captured replay within the existing 120-step / 240 ms
synthetic position profile. Full policy execution remains gated; CW-G01 live
admission has a named local synthetic review; production integration remains open. The [28 October CW-G01 preparation slice](robotics/central_world_cw_g01_admission.md)
adds current build/gesture/endpoint candidates and trusted review/per-joint-limit
preparation of the existing PolicyCase. Live token/claim/dispatch acceptance
is now exercised by the [29 October scoped local adapter](robotics/central_world_cw_g01_admission.md#29-october-service-owned-local-simulation-adapter):
configured service signing, Rust token verification, durable claims, native
per-step enforcement and read-only 3D capture replay. Its local synthetic scope
does not qualify production intake or physical endpoints. Source qualification
stays open under CW-D01.
The runtime work progresses toward a bounded attempt with an understandable
allow/deny/interruption timeline and sufficient verifier evidence. Use the
[18-month execution plan](strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
for Oct 2026–Mar 2028 targets and the dated 14 Oct–12 Nov tactical schedule.
The [portfolio decision](application_directions.md) owns scope, while the
[Microduck integration plan](robotics/microduck_integration_plan.md) owns native
M0–M5 acceptance.

## Current Baseline And Execution Order

### 12 November maker-trial blocker: robot and task clarity

The participant reached the practice workspace but could not identify a robot
or a reason to choose Movement. This is a comprehension blocker, recorded as
partial human feedback against the original candidate. The
[task-flow repair](robotics/cw_l02_task_flow_2026_11_12.md) adds explicit robot
choices, named robot anatomy, a persistent goal/next-action guide, checked
preparation and planned-versus-measured joint charts under the existing limits.
**Next: independently retry this revised candidate**, retaining the original
observation. Implementation and automated checks cannot close the human finding.
CW-L03 remains deferred; native M1 and CW-D01 retain their separate gaps.

The participant then requested a complete default robot instead of component
geometry. The [later correction](robotics/cw_l02_task_flow_2026_11_12.md#later-12-november-correction-full-robot-by-default)
makes the full Microduck pose workspace the default even with a saved lab draft,
adds a concrete head-turn/save-pose task, and moves the synthetic fixture into
Advanced lab. Retry this latest candidate; returning to raw geometry is now an
explicit lab choice. Full-model physics/policy acceptance remains separate.

### 12 November engineering review and selected next task

The [route/status review](robotics/route_review_2026_11_12.md) inspected clean
baseline `b86fd3bb`, the full root README, active routes, retained packets and
fresh local checks. Engineering recommendation: **continue local simulation;
rescope dependent physical dates; defer alpha and physical release** pending
their distinct evidence. This is not a human release decision.

**P0 — CW-L02 independent adult-maker observation** is the next delivery task,
targeted for **13 November**, subject to participant and observer availability.
Allow 45–60 minutes, then up to half a day for observed blockers and affected
checks. Record actual setup/lesson times, assistance, accessibility, downloads,
recovery and the distinction between full-model display and synthetic rehearsal.
Support and rollback owners must be named before CW-L03 review. Do not repeat
preparation or add gallery features as a substitute for missing human evidence.

**P1 — native M1 evidence intake and CW-D01 qualification** follows, or becomes
the bounded engineering task when no participant is available. Inventory the
independent checkpoint/export reference, normalization, policy rights,
runtime/body/actuator compatibility and exact fixture drawing/rail gaps. Assign
roles, required artifacts and explicit blocked dispositions before planning
native M2 implementation or firmware. The review schedules this work for
13–16 November without assuming reference or hardware availability. Existing
artifact goldens do not close training parity.

The default Studio on port 8767 serves the current build but reports
`configured: false` for `/api/cw-g01/profile`. Its ordinary synthetic lesson
does not demonstrate the governed signed-evidence path. Keep that integration
visible as a separate acceptance task. The live shared authz stage is unavailable
with port 8002 offline; optional Postgres remains skipped. Fresh local passes
and their limits are recorded in the review.

SIM-1/SIM-2 are locally delivered. SIM-3 has a delivered planar 1/2/3-link studio
slice, with broader gates open. The [simulation-first acceptance record](robotics/simulation_first_acceptance.md)
now includes a pinned offline Microduck source/policy candidate, a read-only HAL
adapter, 16 upstream-derived observation/ONNX artifact goldens, and a split-screen
bounded-session rehearsal. Token claim/refresh/revocation, authenticated framing,
an independent host watchdog and Python/Rust simulation receipt checks exist.
No hardware is connected. Independent training-checkpoint outputs, native
Microduck governed motion, MCU firmware and physical WebSerial remain open.
The simulation-only profile does not close full G0/G1/G2 or Microduck M2–M4.

An opt-in [browser performance lab](robotics/browser_performance_pipeline.md)
now exercises separate scalar Wasm physics and OffscreenCanvas/WebGPU render
workers, bounded transferable/shared snapshots and WGSL display FK. Its actual
device measurements and faults support future runtime work; this synthetic
planar profile does not consume CW-S01 MJCF, close CW-S02 or qualify hardware.
Use its stack-adoption table for SIMD/pthreads, ONNX/WebNN and remote simulation
experiments; keep engine/model/capture gates ahead of editor-wide migration.

On 22 October the supporting [static scene lab](robotics/static_scene_streaming.md)
adds pinned NASA HLOD traversal, original Draco meshes, cache/download/decode
bounds, fixed-origin display rebasing and degraded coarse fallback. It is a
separate visual experiment; it does not add collision geometry or close CW-S02.
The [22 October review decisions](robotics/browser_robotics_studio_stack_architecture.md#22-october-review-decisions)
retained CW-S02 as the next runtime slice; the 23 October fixed-preset
[CW-S02 record](robotics/central_world_cw_s02_mujoco.md) now supplies local evidence. An editor backdrop remains optional view work; beginner Robot Moments
follow the bounded runtime and gesture checks, without requiring a trained policy.

The user-selected next product workstream is the
[Central World Phase 1 foundation and 12-week plan](robotics/central_world_engineering_plan.md).
Its strict component schema, 12 draft/proxy records, source pins, linter and
read-only part viewer are implemented. Exact supplier/drawing/pin/rail data
remain open. Keep native M0–M4 acceptance intact; CW assembly/DRC/simulation and
deployment stages have separate gates. January's default target is an authoring
and simulation alpha; hardware and publication depend on their own acceptance.

The CW-A01 v1 draft is committed as `9c5aaf7`. Its
[acceptance closure](robotics/central_world_cw_a01_acceptance_plan.md) now provides
a v2 software candidate addressing all eight findings: shared canonical bytes,
catalog-byte pins, schema/graph conformance and explicit connection semantics.
Build-from-source acceptance passed 117 Python and 71 Node tests, including live
cross-language parity. CW-A02 can use this
documented v2 contract; no hardware, dynamics or live-execution gate is closed.

The [mjswan source assessment](robotics/mjswan_integration_assessment.md)
is complete. Version 0.11.9 is a conditional CW-S02/CW-S03 candidate, with
engine/training version conflicts and missing public worker/control/capture
seams to resolve first. No runtime was imported or benchmarked. This decision
does not block CW-A02 authoring or close Microduck training parity.

For the native lane, obtain the missing training/export references and reconcile
runtime/body/policy compatibility; bind the native boundary to live authority;
implement/cross-build MCU enforcement; then qualify one servo before three.
Offline Central World authoring proceeds independently; missing hardware or
Microduck training references do not block an explicit proxy graph or separately
declared tabletop gesture. Use one active implementation package per implementer.
Firmware packet preparation, the supervised simulation lesson and review sheet
are available in the acceptance guide and [lesson](../application/seedcore_session_lesson.md).

## Immediate Central World Queue

The [remaining delivery schedule](robotics/central_world_remaining_delivery_schedule.md)
owns detailed order and owner roles; the
[acceptance matrix](robotics/central_world_acceptance_matrix.md) owns tests and
measurement artifacts. CW-A01 v2, CW-A02, CW-A03 and CW-A04 now have passing
local offline software evidence, completing Phase 2's offline authoring/DRC scope.
Phase 3's CW-S01 handoff, CW-S02 fixed-preset runtime and CW-S03 offline preflight
also have local evidence. CW-S04's bounded synthetic gesture/replay slice is
delivered locally. CW-G01's preparation and local synthetic native-admission
adapter are available for review; production context/deployment remains gated.
Full policy execution and later live/release
gates remain open.

| Order | Package | Next reviewable result | Dependency |
| --- | --- | --- | --- |
| Software exit passed | CW-A01 v2 | Corrected contract, starter and retained regression evidence | [Exit record](robotics/central_world_cw_a01_acceptance_plan.md); simulation/proxy scope |
| Supporting data | CW-D01 | [19 October source inventory](robotics/m0_cw_d01_register_2026_10_19.md) recorded before window boundary | Exact unit/drawing/pin/rail qualification remains open |
| Local software slice passed | CW-A02 | [Mini Studio, raw import, immutable store and browser evidence](robotics/central_world_cw_a02_authoring.md) | Offline proxy scope; no runtime admission |
| Local software slice passed | CW-A03 | [15 mm snapping, ghost/numeric placement and atomic reparenting](robotics/central_world_cw_a03_snapping.md) | Proxy-only CW-SNAP-01 evidence; explicit joints preserved |
| Local software slice passed | CW-A04 | [Pure worker DRC, routing proposals, 3D mass/inertia and unknown-aware BOM](robotics/central_world_cw_a04_drc.md) | Offline CW-DRC-01..03 passed; physical pass awaits CW-D01 |
| Local compiler/parity and Studio handoff passed | CW-S01 | [Offline synthetic reference, readiness inspector, deterministic MJCF/model exports and native/browser handoff evidence](robotics/central_world_cw_s01_mjcf.md#23-october-studio-handoff-and-offline-reference) | Actual starter: 10 DRC blockers / 9 simulation blockers; physical source qualification stays open under CW-D01 |
| Local Wasm worker/parity/veto slice passed | CW-S02 | [Pinned `@mujoco/mujoco@3.15.0` worker adapter, clocks, bounded capture, per-substep control veto and native/browser parity](robotics/central_world_cw_s02_mujoco.md) | Local fixture profile at dt=0.002, position kp=1 or torque passed (`CW-SIM-02..04`); broader model/device/deployment checks remain open; no planar fallback; live Agent/PDP admission remains CW-G01 |
| Local offline preflight passed | CW-S03 preflight | [Pinned inventory, 16-case CPU artifact replay and deterministic compatibility/refusal reports](robotics/central_world_cw_s03_preflight.md) | Full CW-POL-01 remains open: both real policy-execution candidates blocked; no checkpoint/browser qualification |
| Local synthetic slice passed | CW-S04 | [Bounded Hermite timeline, virtual LED, per-step target controls, interrupted capture and read-only replay](robotics/central_world_cw_s04_gestures.md) | Synthetic position profile only: dt=0.002, kp=1, at most 120 steps / 240 ms; no physical or policy authority |
| Separately gated | CW-S03 inference/runtime | Compatible policy/model/actuator mapping, independent training/export and browser operator/timing evidence | Resume from the preflight blockers; artifact replay alone does not qualify this lane |
| Named local review passed; broader integration gated | CW-G01 | [5 Nov independent review](robotics/cw_g02_exit_review_2026_11_05.md) of the real PDP/configured signer, Rust verification, durable claim, native substep/stop/revocation and captured replay | Local fixture context only; production authenticated intake/context refresh, deployment and physical paths require separate qualification |
| Named local review passed; full package promotion separate | CW-G02 | [Known-attempt inspector](robotics/central_world_cw_g02_evidence.md): independently provisioned trust, paired Python/Rust reports, original signed downloads, bounded import and actual Chrome/native handoff evidence | [Independent baseline review](robotics/cw_g02_exit_review_2026_11_05.md) passed with exact source/artifact integrity; general historical lookup and production/physical evidence remain separate |
| Named local draft review passed; final handoff closed 6 Nov | CW-E01 | [Draft Build Pack](robotics/central_world_cw_e01_build_pack.md): deterministic pinned archive, full DRC, unknown-aware BOM, unreviewed-net SVG and current-revision Studio download | 305 workspace tests, nine Chrome groups and independent actual-ZIP checks; no qualified wiring, print assets, firmware or hardware |
| Local candidate passed | CW-L01 | [Curated local gallery and fork flow](robotics/central_world_cw_l01_gallery.md), pinned source/dependency checks, distinct draft IDs and source/license ancestry | 309 workspace tests and seven Chrome groups; no public upload, inherited authority or physical qualification |
| Automated exercise passed; independent observation pending | CW-L02 | [Guided synthetic lesson and observation sheet](robotics/central_world_cw_l02_maker_lesson.md): inspect, fork, customize, rehearse, inspect capture and export | Independent adult-maker timing, accessibility, support, privacy and failure observations remain required |
| Deferred until independent evidence and release review | CW-L03 | [Alpha review decision](robotics/central_world_cw_l03_alpha_review.md), exact source/build inventory and release prerequisites | Actual maker observation, supported devices, support/rollback owner and a separate release decision |

## 10 November priority: refreshed CW-L02 candidate

The selected next package is **CW-L02 maker-trial readiness**, following the
committed beginner UI and full Microduck visual explorer (`b71d022d`). The
[10 November schedule](robotics/cw_l02_daily_plan_2026_11_10.md) refreshes the
participant lesson, source/build inventory, browser/startup checks and a new
trial packet. The refresh passes 309 TS tests, 57 focused Python checks, the
beginner/full-model browser exercises, seven gallery groups and five startup
checks. The fresh local packet is
`artifacts/robotics/cw-l02-trials/2026-11-10-microduck-ready-01/`. The full Microduck view is display-only; the supported synthetic
simulation remains separate. This closes software preparation only. Independent
adult-maker timing/accessibility/failure observations and named support/rollback
owners remain required before CW-L03 can receive a separate release decision.

## 9 November afternoon priority

The [afternoon plan](robotics/cw_l02_daily_plan_2026_11_09.md) selects CW-L02
trial readiness: a source-bound local trial packet, startup preflight, first-use
and recovery checks, and an independent maker observation if a participant is
available. CW-L03 consumes the resulting evidence; absent observation or release
ownership keeps its decision deferred. The inspected baseline is `f99479a2`.
The trial tools now pass 29 focused checks, the source-built gallery/browser gate
and five actual startup/packet groups. Q2 available lanes passed; optional
Postgres was skipped and the live authz phase was unavailable after 79 focused
checks passed. The post-stop port-preflight issue is fixed, and a fresh packet is
ready. The operator reported the maker exercise **not tested**. Independent
observation and release ownership therefore remain pending; the daily handoff
records exact artifact locations and the next step.

## 6 November gallery and lesson implementation

CW-L01 now offers the byte-pinned tabletop source and canonical-pinned synthetic
reference in the local gallery. Each fork creates a new draft identity and stores
source/license provenance in the exported assembly. The seven-group browser gate
checks unchanged-draft failure behavior, unique IDs, a real Build Pack and the
guided synthetic rehearsal. The [independent maker sheet](robotics/central_world_cw_l02_maker_lesson.md)
is prepared but has no participant results. The [alpha record](robotics/central_world_cw_l03_alpha_review.md)
therefore records **DEFER**, not a publication or physical approval. Continue
the CW-D01 source/rail and M1 training-reference lanes separately.

## 6 November final handoff

The outstanding CW-E01 verification manifest and delivery record are complete.
At that handoff the source-built browser gate passed **305 TS tests and nine
Chrome groups**; the recorded CW-E01 and CW-G02 hashes matched. The subsequent
CW-L01 work reran those gates with the updated source and 309 workspace tests.
The
[delivery record](robotics/cw_e01_daily_plan_2026_11_05.md#actual-delivery-record)
distinguishes the 5 November work from this final 6 November closeout and records
the skipped/unavailable lanes. CW-L01 was the following implementation; its
local candidate is now recorded above. No full package, production or physical
promotion is implied.

## 5 November priority and agent allocation

The [afternoon execution plan](robotics/cw_e01_daily_plan_2026_11_05.md) assigns
three agents: independent local CW-G01/CW-G02 exit review, the CW-E01 draft
exporter, and its current-revision Studio download/browser exercise. The
coordinator owns integration checks and this queue. The inspected `36fceb1`
baseline was clean. The target is one reviewable offline draft design pack,
with exact source/hash inventory, full DRC, unknown-aware BOM and explicitly
unresolved wiring; supported synthetic models may include existing MJCF output.
The named local evidence review passed, and the draft pack is implemented with
305 workspace tests, nine Chrome groups and independent archive/source/binding
checks. The shared Q2 verification script passed available lanes; optional
Postgres remains skipped, and the authz live phase remains unavailable at port
8002 after 79 focused tests passed. The [delivery record](robotics/cw_e01_daily_plan_2026_11_05.md)
retains exact results and artifacts. Hardware, firmware, full policy execution
and production intake retain their existing gates. The draft slice's independent
review and final 6 November handoff are complete; prepare CW-L01's curated local
gallery/fork flow next.

## 4 November priority task

The [afternoon plan](robotics/cw_g02_daily_plan_2026_11_04.md) now delivers the
read-only Evidence Inspector for a configured service's known terminal attempt.
It verifies both languages against server-retained context and operator-pinned
trust, preserves original signed bytes/reports, and fences stale replies. The
local slice passes 14 focused TS checks, 22 trusted API/config checks and nine
Chrome groups; actual completed/stopped downloads match both independent CLIs
and native replay. The 111 evidence / 139 regression / 49 Rust tests remain
required. Review the named local CW-G02 evidence before selecting the following
CW-E01 design-pack package. General historical lookup and production/physical
qualification remain separate; no full package promotion is recorded here.

## 3 November priority task

The [today plan](robotics/cw_g02_daily_plan_2026_11_03.md) now has a reviewable
independent Rust verifier for existing CW-G02 bundles. The local source-built
gate passes 111 evidence tests, 139 admission/Fast Spine regressions and 49 Rust
contract tests, with 82 canonical vectors and 110 retained agreement records.
Both languages verify original bytes, separately expected context/trust,
authorization windows and sample coverage. The next bounded task is the
read-only Studio verification/import surface and actual browser-export evidence.
The plan retains the inspected `636fb87` baseline and the scoped completion
record; full CW-G02 and production/physical acceptance remain open.

## 2 November work plan

The [afternoon plan](robotics/cw_g02_daily_plan_2026_11_02.md) now has a
[reviewable CW-G02 Python foundation](robotics/central_world_cw_g02_evidence.md):
original-artifact retention, explicitly configured host-signed terminal bundles,
read-only download and independent offline verification against separately saved
admission context and trust/revocation snapshots. Actual PDP/native completed
and stopped fixtures retain original artifacts; gapped and revoked-key cases
are quarantined. Full CW-G02 acceptance still requires the additive Rust
adapter/parity and Studio/browser evidence; broader CW-G01 production and
physical gates remain open. The plan retains the inspected baseline and
afternoon time box and records today's fresh full CW-G01 browser/native
regression pass separately from the still-pending CW-G02 browser surface.

## Native Reference Milestones

| Stage | Next deliverable | Exit condition | Target window |
| --- | --- | --- | --- |
| M0 deployment freeze | Runtime/RL/policy pins, 61/14 semantics, transport, board and watchdog inventory alongside the pinned body model | Reproducible profile; units, ordering, normalization and unresolved source claims explicit | Oct 2026 |
| M1 | Close independent training/export and runtime/body/policy compatibility around the delivered read-only adapter and artifact goldens | No startup motion; observations and ONNX outputs match independent pinned references within frozen tolerances | Oct–Dec 2026 |
| M2 | One bounded velocity/stop session through gateway/PDP/token/native boundary | Invalid, expired, forged, replayed, revoked, wrong-endpoint and out-of-scope requests cannot dispatch motion | Oct–Dec 2026 |
| M3 | Action-bound telemetry, signer provenance, receipts, replay and RESULT_VERIFIER | Sufficient evidence closes; missing/stale/conflicting evidence is rejected or quarantined | Begin Q4 2026; complete Q1 2027 |
| M4 | One supervised Microduck profile on its native runtime | Measured latency/stop/fault behavior and repeatable allowed/denied/interrupted evidence | Q1 2027, after M1–M3 |
| M5 | Offline baseline/candidate comparison and separately admitted promotion | Reproducible evaluation, export parity, reviewed metrics and rollback artifact | Supporting lane after the baseline is pinned |

Dates are planning targets. Model ingestion does not close all M0 deployment
facts, and the arm fixture does not complete Microduck M4. M5 keeps its learning
meaning; skill packaging and commercial stages are separate follow-ons.

## First 30-Day Work Packages

1. **14–20 Oct:** reconcile the candidate deployment pins, request independent
   checkpoint/export references and record missing board/fixture facts. Review the
   [Fast Spine protocol proposal](robotics/fast_spine_protocol_spec.md), trust
   roots, session/deadline semantics and command ingress. Record BOM quotes,
   hardware access and effort limits.
2. **21–27 Oct:** reproduce the delivered read-only adapter, split-screen session
   rehearsal and negative authority checks; advance Phase 3 CW-S01 restricted
   assembly-to-MJCF compilation on the delivered CW-A01–CW-A04 authoring/DRC baseline.
   Preserve distinct simulator, protocol-fixture and hardware labels.
3. **28 Oct–3 Nov:** advance live native M2 admission/session/stop integration and
   minimum M3 requirements beyond the delivered host simulation. Bench checks
   remain conditional on a fixture; progress one servo to three only after the relevant
   authority gate. A physical demo requires the selected profile's evidence
   and hardware acceptance, even before full Microduck M3/M4 are complete.
4. **4–10 Nov:** review the firmware/toolchain/board qualification inventory,
   delivered release-packet preparer, supervised lesson and
   [OEM packet](../application/oem_partnership_brief.md). A firmware release
   candidate requires actual reviewed source/build and recovery evidence;
   CW-F01/CW-F02 remain the conditional later lane. RP2350/BLE are separate work.
5. **11–12 Nov:** review traces, verifier outcomes, measured timing, quotations,
   setup/support estimates and the next backlog. Choose go/rescope/defer from
   evidence; move dependent dates when a gate slips.

The day-30 deliverable may be simulation plus protocol/bench evidence if
hardware or signing is not ready. Do not advertise a physical signed-receipt
demo using fixture output. For the hero case, deny an out-of-envelope proposal,
then revoke an admitted session and report measured response. A clamped plan
must remain inside admitted transform semantics or return for renewed admission.

## Native Reference And Fast Spine Fixture

Microduck remains the native `robotd` / 61-observation / 14-action reference.
Its controller owns balance, motor bus and local safety. The 1–3 DOF arm is a
bounded fixture for the proposed MCU protocol and browser onboarding. It is
not a second supported commercial profile until qualification and capacity
permit that decision.

Freeze profile-specific command age, revocation-context freshness, local
deadline, stop behavior and evidence coverage before acceptance. Claim a
single-use token once per session; command refresh cannot widen scope, extend
expiry or revive a fenced attempt. Reconnect must not replay buffered motion.
Inventory alternate ingress/debug paths and test enforcement at the actual
execution boundary. Preserve local stop during loss of browser, gateway or cloud.

Record revocation propagation, response initiation and observed stopping time
or distance separately. CRC and serial-port permission are not authentication.
The Rust kernel verifies artifacts; captured data needs an enrolled signer
before it can be called signed hardware evidence.

## Customer, OEM And Data Preparation

Target one repeatable supervised STEM/maker lesson on one accepted profile.
Start with one live pilot; expand toward 3–5 pilot sites and up to
100 cumulative developer kits after useful repeat delivery, QA, cash and
support reviews. Hardware qualification, trust/release and field-support
responsibilities are in the execution plan.

Prepare a need/function brief, customer acceptance criteria, hardware fit,
operator controls, warranty/repair route and delivery/support cost estimate.
Use the [delivery model](robotics/robot_solution_delivery.md) and
[service operating plan](robotics/robot_service_operating_plan.md). Candidate
OEMs, pilots, incorporation and grant funding are not established agreements.
Preparing a packet does not authorize contacting prospects or placing orders.

The revised [mini-robotics cooperation assessment](strategy/robotics_component_cooperation_strategy_2026.md)
prioritizes the existing TTL fixture gap record, ODRI source/fabrication study
and exact CubeMars compact-joint feasibility. These share the proposed
two-person-day COOP-01 research cap in the
[ecosystem roadmap](robotics/robotics_ecosystem_integration_roadmap.md), only when
capacity remains after committed work. Use the
[pilot briefs](../application/robotics_component_partner_pilot_briefs.md) to
record exact versions, complete mass/power/cost, fabrication, interface and
rights gaps. CW-S04's local synthetic slice follows the completed CW-S03 preflight;
CW-G01 is next. Unsupported CAN/CAN FD work, a new joint/body
or an extra pilot is not a prerequisite. Select at most one later commercial
or open-joint experiment against a measured mini-task need and existing CW/M/G
gates. The prior compute/capture/middleware-first sequence is superseded;
industrial cells and large humanoids receive no new allocation here.

Within the same research cap, use the
[base/attachment product analysis](strategy/mini_robotics_base_attachment_product_analysis.md)
to review reusable-dock packaging, complete starter cost and incremental
print/active-pack cost. Keep rails/connectors unselected and ID discovery
non-authoritative; no dock PCB, catalog part, survey or hardware build is added
to the implementation queue. Optional LLM-drafted gesture JSON uses the same
bounded CW-S04 parser as manual edits; no provider connector is required or
implemented. CW-S04 is delivered locally; CW-G01 admission integration is next.

Opt-in telemetry begins with adult bench data. Keep capture and external camera
egress disabled by default; separately review permissions, retained samples,
dataset rights and privacy. Use body-specific vectors under a common evidence
envelope, rather than applying Microduck's 61/14 mapping to every kit.

## Verification And Follow-Ons

When implementing M1–M3, use the integration plan's negative cases and focused
robot/evidence tests, plus relevant shared authority checks:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
pytest tests/test_robot_sim_week4_integration.py tests/test_result_verifier_telemetry_contract.py tests/test_signed_edge_telemetry_closure_refs.py -q
```

These existing regressions do not replace dedicated Microduck/transport tests.
For simulator/model status, use `node tools/mini-sim/verify.cjs` and model/workbench
tests. For learning changes, preserve the
[flywheel gates](seedcore_flywheel_harness.md). Repeated deterministic failures
require verifier/runbook review.

Package accepted skills and test an external integrator before adding a new
body. SIM-3 remainder and SIM-4–SIM-6 are a conditional research lane; native
MuJoCo acceptance can progress independently. Fleet scale, a custom SoM and
hosted Workbench follow repeat-use, support and paid-demand evidence.

Maintain RCT proof regressions. RCT visual expansion, city persistence,
producer/service lifecycle, tourist journeys and creative media remain
deferred unless needed by the active reference. Earlier ordering is retained
in the [historical queue](archive/historical/current_next_steps_before_microduck_2026-09-17.md).
