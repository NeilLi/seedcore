# SeedCore Physical AI Execution Plan: Q4 2026–Q1 2028

Date: 2026-10-14
Cooperation addendum: 2026-10-20
Status: Canonical 18-month planning schedule; dates, costs and adoption counts are targets, not completed milestones or commitments

## Positioning And First Offer

**SeedCore is the open trust runtime for affordable physical AI: browser-first
robot experiments, bounded execution authority and verifiable action evidence.**
The initial distribution wedge is maker and supervised STEM hardware, targeting
selected reference kits below $300 excluding an existing host computer. That
price is a design goal; it is not the established cost of Microduck.

The prospective moat comes from repeatable firmware, hardware qualification,
trusted releases and supported deployments. Independent integration and
sustainable delivery must demonstrate that advantage.

Start with one browser lesson: an operator proposes a short tabletop-arm move,
sees admission or denial, interrupts an admitted attempt and inspects its
evidence. Microduck remains the native-runtime reference for the 61/14 policy
interface. A simple arm is the constrained Fast Spine bench fixture; accepting
that fixture does not complete Microduck M4.

The [physical AI strategy](../robotics/physical_ai_strategy.md) owns positioning;
the [active queue](../current_next_steps.md) owns the next work items. Device and
simulator acceptance remain in their existing M0–M5 and SIM-1–SIM-6 plans.

## Evidence Baseline On 2026-10-14

| Surface | Present evidence | Remaining qualification |
| --- | --- | --- |
| SIM-1 / SIM-2 | Worker lessons, versioned contracts, C++/Wasm planar dynamics and checkpoint continuation | Broader browser/device release checks |
| SIM-3 | Delivered fixed-base planar 1/2/3-link dynamics with a 3D orbit view; dual-ABI Wasm is 13,242 raw bytes | Branching/spatial dynamics, encoder sampling, worker-v3 and independent MuJoCo comparisons remain open |
| M0 model pinning | Microduck 0.1.0 MJCF, integrity manifest, mass/joint/actuator parity | Complete the deployment manifest: runtime, policy, normalization, hardware, transport and watchdog pins |
| M1–M4 | Generic HAL, token/revocation and evidence components exist | Microduck-specific driver, governed sessions, robot evidence closure and supervised physical acceptance remain planned |
| Rust proof kernel | Token, signature, receipt and replay verification code and CLI exist | A signed Microduck outcome and enrolled device signer are not established by that code |
| Fleet coordination | Local team contracts, reservations and dispatch/verify/halt ports exist | Durable live-adapter integration and 10–30 robot classroom qualification remain planned |

Local checks on this date: the simulator runner passed **78 Node.js tests**,
12 native planar invariant groups, six native tree groups and 12 Wasm
invariants. Model/workbench checks passed **88 Python tests**. These are
software/model results, not physical hardware or classroom acceptance.

## Delivery Responsibilities

| Responsibility | Accountable work | Deliverable before scale |
| --- | --- | --- |
| Supply chain / manufacturing | Component quotations, DFM, servo sourcing, ODM firmware integration and factory test | Revision-specific BOM, supplier alternatives, traceable lots and manufacturing test records |
| Trust / commercial | Proposed commercial/IP stewardship, release trust roots, enterprise contracts, cloud/model procurement and institutional partnerships | Documented IP/license chain, signer governance, customer/data terms and a current provider-availability matrix |
| Engineering / field delivery | Bench engineering, small-batch assembly/QA, operator training and supervised field feedback | Repeatable build/test instructions, support owner, pilot evidence and actual landed-cost records |

These are proposed responsibilities, not evidence of established facilities or
agreements. Evaluate shipping routes using actual origin, classification and
processing records. Assembly or re-export does not automatically change origin
or remove duties. The [US International Trade Administration's origin guidance](https://www.trade.gov/rules-origin-substantial-transformation)
describes the product-specific substantial-transformation assessment.

## Strategic Pillars And Delivery Order

| Pillar | Product and customer value | Validation before commercial claims |
| --- | --- | --- |
| A — SeedCore Inside | Open Fast Spine reference firmware plus browser lessons for supported OEM kits | An independent integrator flashes/enrolls one supported board, connects it and reproduces allowed, denied and interrupted attempts |
| B — Auditable classroom governance | Teacher/operator roles, bounded sessions, capture/egress permissions and replayable evidence | End-to-end enforcement, missing-evidence handling, privacy-path tests and institutional acceptance for the named profile |
| C — Opt-in sim-to-real telemetry | Versioned trajectories tied to model, calibration, action, signer and verifier result | Rights/consent and retention controls, retained samples, gap accounting and a measurable calibration/evaluation improvement |

A and B are the first offer. C starts with adult developer bench data and stays
optional; school participation must not depend on dataset contribution. The
61-dim observation / 14-dim action mapping belongs to the pinned Microduck
policy. Arm and future robot profiles declare their own dimensions, units and
ordering under a common evidence envelope.

The “Android + TrustZone” comparison expresses an ambition for portable
interfaces and execution isolation. It is not a claim of an OS, implemented
TrustZone across MCUs, certified physical safety or an industry-first product.

## 18-Month Schedule

The planning horizon is **October 2026–March 2028**. M stages retain their
existing meaning; M5 remains offline learning and separately admitted promotion.
If a gate slips, move its dependent work; do not release it to preserve a date.

| Phase / target window | Technical work | Hardware / supply chain | Commercial / ecosystem | Exit decision |
| --- | --- | --- | --- | --- |
| 1 — Golden reference; months 1–3, Oct–Dec 2026 | Close M0 deployment pins and M1 golden 61/14 observations; complete M2 native governed motion/stop; specify and bench-test the separate WebSerial Fast Spine profile; begin minimum M3 evidence for a physical demo | Choose one ESP32-S3 board and one TTL STS3215 fixture; quote a $12 controller BOM target; build up to 10 engineering units after bench gates | Prepare one split-screen demo and OEM/pilot briefs; target a public demo only after required authority, evidence and hardware gates | Reproducible allow/deny/interruption evidence; no motion on failed authority; measured disconnect/stop behavior; supportable first offer |
| 2 — Closed-loop proof and supervised pilots; months 4–6, Jan–Mar 2027 | Complete Microduck M3 and M4 on its native runtime; qualify the arm's physical bridge separately; deliver telemetry/replay and flash/enrollment recovery | Progress through 10 → 25 → up to 100 cumulative developer kits only after QA, demand, cash and support reviews; assembly and QA responsibilities recorded | Start one adult-supervised school/maker pilot; expand toward 3–5 pilot sites after repeat use and support evidence | Selected robot M0–M4 pass; one repeat delivery; named operator/support owners; useful lessons and sustainable support cost |
| 3 — OEM adoption and ecosystem adapters; months 7–12, Apr–Sep 2027 | Close remaining SIM-3 gates; stage SIM-4 contacts/sensors → SIM-5 batches → SIM-6 imports/governed bridge with independent acceptance; add one pinned LeRobot/SO-100-family adapter and one model-provider proposal adapter | Qualify one OEM kit first; expand toward 2–3 shipping OEM relationships after conformance and update/support tests | Publish a versioned SeedCore Verified conformance profile; seek OEM design-ins and an applicable innovation call; trial opt-in adult telemetry | External developer reproduces integration; at least one partner has a tested shipping profile; repeat-use/paid demand justifies the next adapter |
| 4 — Fleet governance and commercial scale; months 13–18, Oct 2027–Mar 2028 | Durable enrollment/reservations, per-robot authority and closure; qualify 3 → 10 → up to 30 robots; hosted Workbench for policy templates and replay; validate device-rooted evidence | Freeze a SoM only if volume and support justify it; select a currently supported secure element or qualified RP2350 secure partition, with enrollment/rotation/recovery tests | Offer paid Governance / Cloud Workbench subscriptions to validated schools, universities and labs; retain open local tools | Paid renewal/repeat use, positive recurring contribution target and tested fleet interruption/recovery; board/SoM investment justified by demand |

The SIM-4–SIM-6 lane is conditional research. Its full general-engine scope may
exceed phase 3 capacity; a qualified native MuJoCo path can serve an adapter
while browser dynamics research continues. Do not represent the current planar
Wasm engine as a Microduck digital twin or make general contact simulation a
prerequisite for the first governed hardware demonstration.

## Component ecosystem cooperation

The [component cooperation strategy](robotics_component_cooperation_strategy_2026.md)
and [ecosystem roadmap](../robotics/robotics_ecosystem_integration_roadmap.md)
provide candidate choices for the existing phase 3 ecosystem lane. D-Robotics,
Orbbec and Viam receive bounded technical diligence first; one later
offline/read-only experiment requires a measured need and available capacity.
These candidates compete for the existing adapter budget rather than adding
three concurrent integrations. Selecting an alternative to the planned
LeRobot/model-provider package requires an explicit queue/capacity decision.
Industrial arms, tactile manipulation, hands
and general robot brains require a separate scope/profile decision. Q4 work
continues to prioritize CW-A04, exact fixture data and native acceptance;
the January authoring/simulation alpha has no new supplier dependency.

## Gate Definitions

| Gate | Required review artifact | What it permits next |
| --- | --- | --- |
| G0 — Profile freeze | Runtime/model/policy digests, observation mapping, controller ownership, ingress inventory, trust roots and reviewed numeric limits | M1 parity and M2 implementation |
| G1 — Governed execution | Golden observations; startup without unrequested motion; invalid/expired/forged/replayed/revoked/wrong-endpoint tests; bounded session and watchdog traces | Supervised bench attempts on the selected profile |
| G2 — Physical evidence | Required M3 predicates and signer provenance; measured M4 stop/fault behavior; missing/stale/conflicting evidence rejection | A physical demo or pilot, restricted to the accepted profile |
| G3 — Repeat delivery | Operator lesson results, repeat use, setup/support hours, manufacturing QA and repair/update route | More sites and the next kit tranche |
| G4 — OEM conformance | Independent installation, ingress coverage, branded profile/version, factory enrollment, firmware update/rollback and failure traces | SeedCore Inside design-in / SeedCore Verified badge for that profile |
| G5 — Fleet / paid service | Multi-device fault drills, isolation, reservation recovery, retained audit coverage, tenant/privacy controls and measured recurring costs | Qualified fleet subscription; further scale subject to the same review |

G1 is necessary but insufficient for a physical showcase: G2 must cover the
demonstrated motion and evidence even if full Microduck M3 is scheduled later.
A mock receipt or protocol fixture must remain visibly labeled as such.

## First 30 Days: 14 October–12 November 2026

The subsequent [Central World product workstream](../robotics/central_world_engineering_plan.md)
targets 19 Oct–10 Jan for component standardization → assembly/DRC → separately
qualified browser MuJoCo/gesture rehearsal → conditional governed deployment →
alpha review. Its Phase 1 software foundation is implemented early; exact part
qualification and later phases are open. This can bring forward a browser
MuJoCo adapter without moving the custom engine's broader SIM-4–SIM-6 research
or weakening native M0–M4/G0–G2. Review capacity weekly; January defaults to a
simulation/authoring alpha when firmware/hardware gates are not ready.

The [remaining CW delivery schedule](../robotics/central_world_remaining_delivery_schedule.md)
owns work-package roles and dependencies, and the
[acceptance matrix](../robotics/central_world_acceptance_matrix.md) owns required
review evidence. CW-A01 v2 and the
[CW-A02 offline authoring slice](../robotics/central_world_cw_a02_authoring.md)
have local software evidence. The [CW-A03 placement slice](../robotics/central_world_cw_a03_snapping.md)
adds local proxy-mating evidence, and the
[CW-A04 DRC/BOM slice](../robotics/central_world_cw_a04_drc.md) closes Phase 2's
offline software scope; Phase 3 CW-S01 restricted assembly-to-MJCF compilation is
next. Exact physical data is CW-D01. Treat CW-F01/CW-F02 as a conditional firmware qualification lane
that may extend beyond its target, not an automatic November release promise.

**15 October simulation-first checkpoint:** no hardware is connected. The
[offline acceptance guide](../robotics/simulation_first_acceptance.md) records
the read-only adapter, pinned ONNX candidate, upstream-derived replay goldens,
bounded session/watchdog fixtures and Python/Rust simulation evidence. The
[supervised lesson](../../application/seedcore_session_lesson.md) and
[day-30 review sheet](../robotics/day30_simulation_review.md) are prepared.
These outputs advance the simulation lane; they do not close training parity,
native Microduck M2–M4, MCU release, physical stop measurements or G2.

| Dates | Primary owner role | Concrete output | Acceptance / next decision |
| --- | --- | --- | --- |
| 14–20 Oct | Project / integration lead | [19 Oct inventory recorded](../robotics/m0_cw_d01_register_2026_10_19.md); reconcile candidate M0 pins and delivered artifact goldens; request independent checkpoint/export references; record missing board/fixture facts and review [Fast Spine protocol](../robotics/fast_spine_protocol_spec.md) | Units/ordering and unknowns explicit; no unmeasured hardware freeze; record effort, quotations and availability as known or open |
| 21–27 Oct | Runtime / robotics lead | Reproduce delivered read-only/session/negative fixtures; advance CW-S01 restricted MJCF compilation from the accepted CW-A01–CW-A04 Phase 2 offline boundary | Startup remains read-only; rejected authority cannot dispatch; fixture scope stays distinct from live native integration |
| 28 Oct–3 Nov | Firmware / verification lead | Advance live native M2 and minimum M3 integration beyond the host rehearsal; define conditional one-servo → three-servo bench acceptance | Physical tests require a fixture and G1; public physical demo requires G2; offline CW work can proceed independently |
| 4–10 Nov | Browser / delivery lead | Firmware/source/toolchain/board readiness review, existing packet preparer and recovery requirements; refresh OEM packet and delivered lesson | Real release binary/installer only after qualified source/build/enrollment/recovery evidence; CW-F01/CW-F02 remain conditional later work |
| 11–12 Nov | Project lead / reviewer | Day-30 review pack: demo trace, denied/revoked cases, verifier dispositions, BOM quotes, onboarding timings, support assumptions and next-month backlog | Go/rescope/defer based on evidence; identify one OEM design-in candidate and one pilot candidate without assuming agreements |

The split-screen demo shows a VLM or recorded proposal attempting an
out-of-envelope move. The PDP denies it; an altered trajectory needs renewed
admission unless the admitted transform explicitly permits it. A second case
revokes an active session and shows measured propagation and observed stopping.
An enrolled signer produces captured evidence; Rust verifies it. A signed
verifier report, if offered, needs its own configured signing service.

Web flashing follows `esp-web-tools` on a reviewed ESP32-S3 release. RP2350 uses
a separate qualified UF2/update path. Public HTTPS hosting and user-selected
serial access are release requirements; test managed Chromebook policy and
actual browser/device combinations. Browser port permission does not authorize
motor access. See [ESP Web Tools](https://esphome.github.io/esp-web-tools/) and
[Chrome Web Serial documentation](https://developer.chrome.com/docs/capabilities/serial).

This schedule authorizes planning, not outreach, procurement, firmware flashing,
physical operation or public deployment. Drafts are ready for the next separately
authorized activity; no partner contact is implied by preparing them.

## Hardware Targets And Evidence Discipline

- **$12 reference board:** target recurring controller BOM at a quoted volume.
  Exclude servos, power supply, host, enclosure, freight, tax and non-recurring
  engineering explicitly. Record assembly/test/yield separately and publish a
  landed kit cost; a $1.50 MCU target is not a board quotation.
- **STS3215 fixture:** use its half-duplex TTL electrical interface, reviewed
  power and level handling. RS-485 is a separate servo/profile option, not a
  substitute transceiver for this part. [Feetech's STS3215 description](https://www.feetechrc.com/20210430-56680.html)
  identifies the TTL variant.
- **200–500 Hz:** interpolation target on one board; qualify loop jitter,
  authentication cost, servo-write/read cadence and watchdog behavior
  separately. Do not promise a 500 Hz full round trip on every servo.
- **10-second connect / 30-second flash:** experience targets for a named
  pre-enrolled kit, browser and connection. Report first-time permissions,
  enrollment, flash verification and recovery separately.
- **Hardware-rooted receipts:** select and qualify secure boot, key custody,
  provisioning and verifier-compatible algorithms. [RP2350](https://www.raspberrypi.com/products/rp2350/)
  documents Arm TrustZone support; it is not a feature of ESP32-S3 or a synonym
  for an external secure element. [Microchip's ATECC608B page](https://www.microchip.com/en-us/product/ATECC608B)
  currently marks that device not recommended for new designs; do not freeze
  the suggested ATECC608 family without a lifecycle review.

## Revenue And Capacity

| Offer | Free / open boundary | Paid value to validate |
| --- | --- | --- |
| Local developer tools | Existing Apache-2.0 Wasm core, contracts and proposed basic firmware; local lessons remain usable | Optional supported setup and training |
| Hardware / OEM | Open interfaces and basic firmware do not require a mandatory software royalty | Co-branded QA, conformance maintenance, factory provisioning/identity and contracted support; hardware license and badge terms specified separately |
| Governance / Cloud Workbench | Local authority enforcement and interruption remain effective during cloud loss | Hosted policy administration, school/lab roles, managed fleet records, verified replay and supported model routing; per-device or institution pricing tested with buyers |
| Telemetry | Contribution is optional and separately controlled | Later licensed adult/research datasets or calibration services only after quality, rights and buyer-demand validation |

Price support, cloud inference, replacements and provisioning explicitly. Track
hardware landed cost, one-time delivery contribution and recurring contribution
using the [service operating plan](../robotics/robot_service_operating_plan.md).
Do not make dataset sales, grant awards or hardware margins necessary for the
first software offer to work.

Assume a small delivery team with scoped firmware/manufacturing review. Keep one
active physical profile and one live pilot initially. The arm bench fixture is
a bounded work package: if it becomes a second product or needs extra staff,
make the capacity decision explicitly. Broad SIM research, BLE, multiple VLM
providers, a custom SoM and extra embodiments follow demonstrated need.

## Weekly Scorecard And Review

Record M/SIM gate evidence; blocked authority test coverage; p50/p95/p99
admission and revocation propagation; maximum observed stop time/distance;
command age, loop jitter and bus utilization; evidence gaps and dispositions;
first-time/repeat setup time; useful lesson completion and repeat use; support
hours; unit yield/landed cost; and paid conversion/renewal when available.

Freeze numeric limits per profile before running acceptance tests. Escalate
repeated deterministic failures with verifier/runbook evidence. At each monthly
review, change dependent dates and scope together rather than retroactively
weakening the gate.

For institutional work, review applicable privacy requirements, using the
[PDPC education guidance](https://www.pdpc.gov.sg/guidelines-and-consultation/2018/09/advisory-guidelines-for-the-education-sector)
and [children's data guidance](https://www.pdpc.gov.sg/guidelines-and-consultation/2024/03/advisory-guidelines-on-the-pdpa-for-childrens-personal-data-in-the-digital-environment)
against the actual capture/retention design. Camera egress and trajectory
contribution start disabled; consent and processor arrangements are distinct
from motion authorization. “SeedCore Verified” is a scoped conformance badge,
not regulatory certification. Innovation challenges may offer customer-discovery
routes; programme participation and grant funding are not assumed.

External sources checked 2026-10-14; recheck part lifecycle, programme terms,
provider availability and browser support before implementation or commitments.
