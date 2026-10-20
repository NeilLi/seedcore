# SeedCore Physical AI Strategy

Date: 2026-10-15
Component cooperation addendum: 2026-10-20
Status: Active product direction; hardware, adoption, costs and commercial outcomes require validation

## Product Thesis

**SeedCore is the open trust runtime for affordable physical AI.** It governs
which accountable agent may ask a robot to act, enforces bounded authority at
the execution boundary and preserves evidence of the attempt. Browser lessons
and reference firmware are the proposed adoption path for maker and supervised
STEM kits, targeting selected embodiments below $300 excluding an existing host.

SeedCore aims to combine affordable hardware with verifiable execution.
Its advantage must be earned through qualified profiles, trusted releases,
repeatable integration, support and usable evidence.

“Android + TrustZone” is a positioning analogy for common interfaces and
isolated execution. SeedCore is not claiming to be an OS, implement TrustZone on
every MCU or guarantee physical safety. The buyer-facing promise is simpler:
**open a browser, run a supervised robot lesson within agreed limits, and
understand why it moved or stopped.**

The [18-month plan](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
owns the dated schedule, gate definitions and revenue assumptions. The
[active queue](../current_next_steps.md) owns immediate work.

The [component cooperation strategy](../strategy/robotics_component_cooperation_strategy_2026.md)
assesses external compute, sensing, middleware, modular hardware and behavior
providers against this product direction. Its first diligence candidates are
D-Robotics, Orbbec and Viam; the [roadmap](robotics_ecosystem_integration_roadmap.md)
adds bounded research and conditional adapter experiments within the existing
schedule. SeedCore's role remains governed execution and evidence, with native
controllers retaining local control. CW-S01 and Microduck acceptance retain priority.

## Delivery Responsibilities

| Role | Strategic responsibility | Proof of advantage |
| --- | --- | --- |
| Supply chain / manufacturing | BOM sourcing, DFM, serial-servo kits and ODM pre-flashing | Quoted recurring/landed costs, reproducible QA and a supported design-in |
| Trust / commercial | Proposed IP/commercial stewardship, trust roots, institutional contracts and cloud/model procurement | Clean license/IP inventory, signer governance, provider terms and buyer acceptance |
| Engineering / field delivery | Bench engineering, small-batch QA and supervised field learning | Short iteration cycles, repeatable lessons, supportable installations and measured delivery cost |

These are proposed responsibilities, not evidence of established facilities or
agreements. Record provider availability, qualification evidence and actual
landed costs before an offer.

## Three Strategic Pillars

### A — SeedCore Inside

Offer an open Fast Spine reference plus a Browser Studio URL to manufacturers
of affordable robotic kits. Start with one ESP32-S3 / TTL servo fixture, then
one supported OEM kit. A pre-flashed release reduces installation effort;
qualification, enrollment and recovery make that release dependable.

The current browser foundation is the C++/Wasm planar lesson engine and the
1/2/3-link studio with a 3D orbit view. WebSerial control, firmware flashing and
authenticated MCU sessions remain planned. Ten-second repeat connection and
30-second flashing are measured-experience targets on a named profile, not
universal product claims.

The delivered component registry and read-only viewer add a draft authoring
foundation. The [Central World schedule](central_world_remaining_delivery_schedule.md)
stages assembly/DRC, browser MuJoCo/Robot Moments, live admission/replay,
design export and curated alpha review. Its
[acceptance matrix](central_world_acceptance_matrix.md) preserves unknown-data,
body/policy compatibility and signer/physical-evidence boundaries. A catalog
record does not qualify an OEM kit or authorize a firmware configuration.

The [developer blueprint](mini_robot_developer_blueprint.md) and
[Fast Spine protocol proposal](fast_spine_protocol_spec.md) define the proposed
implementation. Basic firmware should remain open; supported provisioning,
conformance maintenance and integration are separable commercial services.

### B — Auditable Classroom Governance

Make roles, motion permissions, local interruption, camera/egress permissions
and evidence review explicit for teacher-supervised STEM work. An institution
should be able to inspect allowed, denied and interrupted attempts and see
which records support a verifier result.

Motion authority is enforced at the admitted boundary and cannot be replaced
by a browser UI rule. Privacy claims also need enforcement at actual capture,
storage and network-egress paths; a signed motor token alone cannot prevent
video streaming. First lessons use local simulation or accepted physical
profiles without external camera uploads or dataset contribution.

Governance artifacts can support procurement discussions. They do not establish
legal compliance, physical safety certification or an industry-first product.
“SeedCore Verified” should name a versioned conformance profile, tested firmware
and body revision, with explicit coverage and withdrawal/update rules.

### C — Opt-In Sim-to-Real Telemetry

Begin with adult developer bench trajectories to measure backlash, friction,
servo calibration and model error. Bind retained samples to device, firmware,
model/calibration, admitted action, timing/sequence coverage, signer and verifier
disposition. Use a common evidence envelope with body-specific observation and
action schemas; 61 observations and 14 policy actions describe Microduck's
pinned policy, not every robot or every receipt.

Contribution must be optional with separate rights, consent, retention,
deletion and reuse controls. School participation is independent from research
sharing. Cryptographic integrity supports provenance under its key assumptions;
it does not prove sensor truth, calibration or dataset quality.

First validate a measurable improvement in calibration or held-out evaluation.
Dataset brokerage and large-network claims come after demonstrated data
quality and buyer demand. The telemetry product does not alter the existing
[energy flywheel's authority boundary](../seedcore_flywheel_harness.md).

## Reference Architecture And Claim Limits

```text
model proposes -> accountable Agent -> ActionIntent -> PDP
  -> scoped ExecutionToken -> enrolled execution boundary
  -> native controller or qualified MCU local enforcement
  -> observed attempt -> captured evidence / configured signer
  -> Rust verification / RESULT_VERIFIER / replay
```

High-level planning and local interpolation have separate deadlines. Evaluate
200–500 Hz MCU interpolation with bounded action chunks; measure bus writes,
telemetry reads, authentication and watchdog behavior separately. A local
revocation lookup does not establish end-to-end physical stopping time.

Small mass and compliance can reduce kinetic energy, but mini-robots still
require electrical, pinch, force, fall and stop-behavior review for the selected
profile. Physical limits come from hardware measurements; a workspace manifest
or simulation does not enforce them by itself.

Microduck remains the native `robotd` reference, with its balance and bus
ownership preserved. The small arm is a separate MCU bench fixture. The present
13,242-byte dual-ABI Wasm core handles fixed-base planar arms; it is not a
browser Microduck/MuJoCo digital twin, contact engine or firmware size measure.

The pinned body model is implemented. Complete its deployment manifest and
M1–M4 before claiming integrated Microduck execution. SIM-3's planar slice is
delivered; its broader qualification remains open. Existing Rust signature,
token and replay verification does not itself establish enrolled device signing
or a signed robot outcome.

## Execution And Revenue Sequence

| Target phase | Product outcome | Required advancement evidence |
| --- | --- | --- |
| Q4 2026 | Golden profile, M1/M2, constrained split-screen bench demo and minimum evidence | Actual authority/stop coverage and accepted evidence for anything shown physically |
| Q1 2027 | M3/M4, one supervised delivery, then 3–5 sites / up to 100 cumulative kits | Hardware acceptance, useful repeat use, QA, cash and support capacity |
| Q2–Q3 2027 | One LeRobot-family adapter and OEM design-in; conditional SIM research | Independent integration and one shipping conformance profile before 2–3 OEM targets |
| Q4 2027–Q1 2028 | Hosted governance and qualified fleets; SoM only if justified | 3 → 10 → 30 robot fault/recovery evidence, paid demand and sustainable recurring cost |

Within those targets, the 19 Oct–10 Jan Central World track can deliver a
simulation/authoring alpha independently of a physical showcase. Start with one
declared tabletop articulation; keep trained Microduck locomotion conditional
on independent references and model compatibility. Firmware/NVS/installer work
is a separate one-board qualification lane, not universal flashing support.

Keep the local physics core, contracts and proposed basic firmware open.
Validate paid OEM conformance/provisioning/support and hosted policy, roles,
fleet administration and replay. Target per-device or institutional SaaS
pricing after measuring support and inference costs. Basic Apache-licensed use
does not require an OEM royalty. Open hardware licensing and badge terms are
separate decisions.

The [customer delivery model](robot_solution_delivery.md) translates a need into
a function, hardware choice and acceptance plan. The
[service operating plan](robot_service_operating_plan.md) limits initial work to
one repeatable offer, one active physical profile and one live pilot. A bench
fixture must stay bounded; otherwise replan capacity explicitly.

The [OEM brief](../../application/oem_partnership_brief.md) prepares partner
discussions; it is not an agreement or outreach authorization. Innovation
programmes are optional routes whose current terms need checking, not assumed
funding.

## Decision Evidence And Document Contract

Track useful lesson completion/repeat use, independent integration effort,
onboarding and support hours, QA yield/landed kit cost, authority ingress
coverage, admission/revocation timing, observed stop behavior, evidence gaps
and verifier results. Measure paid conversion and renewal once offers exist.

Freeze numerical thresholds before testing. If a gate fails, preserve its trace,
review deterministic failures and move dependent schedule targets. No calendar
date, training score, model output or commercial interest grants execution
authority.

The root README reports present capabilities and target phases. This strategy
explains positioning. The 18-month plan owns dates; the active queue owns next
work; device/SIM plans and shared contracts own acceptance. Label implemented,
locally tested, planned and hardware-validated claims with their scope.
