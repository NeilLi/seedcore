# Current Next Steps

Date: 2026-10-15
Status: Canonical active execution queue — simulation-first candidate delivered; native/physical gates open

The immediate product work is a versioned assembly/joint contract for one
tabletop starter, progressing toward a bounded attempt with an understandable
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

The user-selected next product workstream is the
[Central World Phase 1 foundation and 12-week plan](robotics/central_world_engineering_plan.md).
Its strict component schema, 12 draft/proxy records, source pins, linter and
read-only part viewer are implemented. Exact supplier/drawing/pin/rail data
remain open. Keep native M0–M4 acceptance intact; CW assembly/DRC/simulation and
deployment stages have separate gates. January's default target is an authoring
and simulation alpha; hardware and publication depend on their own acceptance.

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
measurement artifacts. All packages below remain planned/open.

| Order | Package | Next reviewable result | Dependency |
| --- | --- | --- | --- |
| 1 | CW-A01 | Assembly/joint/net schema, immutable revision/digest rules and invalid-graph fixtures | Delivered CW1 software; explicit proxy scope allowed |
| Supporting data | CW-D01 | Exact board/servo/rail/drawing source register | Unknown facts remain open; needed for physical DRC/qualification |
| 2 | CW-A02–CW-A04 | Mini Studio canvas/store, mating/snapping and worker DRC/BOM findings | CW-A01; physical pass also needs reviewed data |
| 3 | CW-S01–CW-S04 | Restricted MJCF/native parity, browser worker and bounded gesture replay | Accepted assembly/DRC; trained-policy lane has separate compatibility/reference gates |
| 4 | CW-G01–CW-L03 | Live admission/replay, design pack, curated fork flow and alpha review | CW3 evidence; firmware/physical provisioning remains conditional |

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
   rehearsal and negative authority checks; begin CW-A01 contract preparation.
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
