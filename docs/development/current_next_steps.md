# Current Next Steps

Date: 2026-10-14
Status: Canonical active execution queue — golden reference, governed motion and supervised STEM/OEM preparation

The immediate outcome is one bounded robot attempt with an understandable
allow/deny/interruption timeline and sufficient verifier evidence. Use the
[18-month execution plan](strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
for Oct 2026–Mar 2028 targets and the dated 14 Oct–12 Nov tactical schedule.
The [portfolio decision](application_directions.md) owns scope, while the
[Microduck integration plan](robotics/microduck_integration_plan.md) owns native
M0–M5 acceptance.

## Current Baseline And Execution Order

SIM-1/SIM-2 are locally delivered. SIM-3 has a delivered planar 1/2/3-link studio
slice, with broader gates open. Microduck model pinning is complete; the full
runtime/policy/hardware deployment manifest is still needed. No Microduck HAL
adapter, Fast Spine firmware or physical WebSerial bridge is present.

| Stage | Next deliverable | Exit condition | Target window |
| --- | --- | --- | --- |
| M0 deployment freeze | Runtime/RL/policy pins, 61/14 semantics, transport, board and watchdog inventory alongside the pinned body model | Reproducible profile; units, ordering, normalization and unresolved source claims explicit | Oct 2026 |
| M1 | Read-only native adapter, explicit fake-I/O/MuJoCo/hardware identities and golden vectors | No startup motion; observations and ONNX outputs match pinned semantics within frozen tolerances | Oct–Dec 2026 |
| M2 | One bounded velocity/stop session through gateway/PDP/token/native boundary | Invalid, expired, forged, replayed, revoked, wrong-endpoint and out-of-scope requests cannot dispatch motion | Oct–Dec 2026 |
| M3 | Action-bound telemetry, signer provenance, receipts, replay and RESULT_VERIFIER | Sufficient evidence closes; missing/stale/conflicting evidence is rejected or quarantined | Begin Q4 2026; complete Q1 2027 |
| M4 | One supervised Microduck profile on its native runtime | Measured latency/stop/fault behavior and repeatable allowed/denied/interrupted evidence | Q1 2027, after M1–M3 |
| M5 | Offline baseline/candidate comparison and separately admitted promotion | Reproducible evaluation, export parity, reviewed metrics and rollback artifact | Supporting lane after the baseline is pinned |

Dates are planning targets. Model ingestion does not close all M0 deployment
facts, and the arm fixture does not complete Microduck M4. M5 keeps its learning
meaning; skill packaging and commercial stages are separate follow-ons.

## First 30-Day Work Packages

1. **14–20 Oct:** freeze the deployment profile, golden-vector plan and one
   ESP32-S3 / STS3215 TTL bench fixture. Review the
   [Fast Spine protocol proposal](robotics/fast_spine_protocol_spec.md), trust
   roots, session/deadline semantics and command ingress. Record BOM quotes,
   hardware access and effort limits.
2. **21–27 Oct:** establish M1 read-only simulation and a split-screen shell
   using the current planar `tree-lab.html`. Add admission/session fixtures and
   preserve distinct simulator, protocol-fixture and hardware labels.
3. **28 Oct–3 Nov:** implement M2 session/refresh/stop and minimum M3 evidence;
   progress single-servo to three-servo bench checks only after the relevant
   authority gate. A physical demo requires the selected profile's evidence
   and hardware acceptance, even before full Microduck M3/M4 are complete.
4. **4–10 Nov:** prepare a reviewed ESP32-S3 firmware/flasher release candidate,
   flash/recovery instructions, one supervised lesson and the
   [OEM packet](../application/oem_partnership_brief.md). Public release waits
   for release review; RP2350 flashing and BLE remain separate later work.
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
