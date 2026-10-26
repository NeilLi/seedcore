# Current Next Steps

Date: 2026-10-26
Status: Canonical active execution queue — CW-S01 handoff and CW-S02 fixed-preset runtime delivered locally; CW-S03 offline preflight delivered; CW-S04 bounded gesture/replay next; real-source/physical and live gates remain open

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
policy candidates blocked with exact reasons. Full policy execution remains
gated; CW-S04 bounded gesture/replay is next. Source qualification stays open
under CW-D01.
The runtime work progresses toward a bounded attempt with an understandable
allow/deny/interruption timeline and sufficient verifier evidence. Use the
[18-month execution plan](strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
for Oct 2026–Mar 2028 targets and the dated 14 Oct–12 Nov tactical schedule.
The [portfolio decision](application_directions.md) owns scope, while the
[Microduck integration plan](robotics/microduck_integration_plan.md) owns native
M0–M5 acceptance.

## Current Baseline And Execution Order

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
local offline software evidence, completing Phase 2's offline authoring/DRC scope;
subsequent Phase 3–5 packages remain planned/open.

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
| 1 (next package) | CW-S04 | Bounded tabletop gesture and replay; trained policy optional | CW-S02 fixed-preset local profile; do not infer Microduck policy compatibility |
| Separately gated | CW-S03 inference/runtime | Compatible policy/model/actuator mapping, independent training/export and browser operator/timing evidence | Resume from the preflight blockers; artifact replay alone does not qualify this lane |
| 2 | CW-G01–CW-L03 | Live admission/replay, design pack, curated fork flow and alpha review | CW3 evidence; firmware/physical provisioning remains conditional |

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
rights gaps. CW-S04 follows the completed CW-S03 preflight; unsupported CAN/CAN FD work, a new joint/body
or an extra pilot is not a prerequisite. Select at most one later commercial
or open-joint experiment against a measured mini-task need and existing CW/M/G
gates. The prior compute/capture/middleware-first sequence is superseded;
industrial cells and large humanoids receive no new allocation here.

Within the same research cap, use the
[base/attachment product analysis](strategy/mini_robotics_base_attachment_product_analysis.md)
to review reusable-dock packaging, complete starter cost and incremental
print/active-pack cost. Keep rails/connectors unselected and ID discovery
non-authoritative; no dock PCB, catalog part, survey or hardware build is added
to the implementation queue. Optional gesture JSON drafting remains a CW-S04
candidate; CW-S02 local runtime and CW-S03 preflight are delivered; CW-S04 is next.

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
