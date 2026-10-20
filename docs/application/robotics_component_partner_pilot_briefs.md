# Mini-robotics component cooperation: draft pilot briefs

Date: 2026-10-20
Status: Revised internal drafts; no outreach, supplier agreement, procurement or deployment

These briefs implement the revised [strategy](../development/strategy/robotics_component_cooperation_strategy_2026.md)
and [roadmap](../development/robotics/robotics_ecosystem_integration_roadmap.md).
They replace the earlier D-Robotics, Orbbec and Viam-first proposals. The
[SeedCore Inside OEM brief](oem_partnership_brief.md) still owns the affordable-kit
design-in. No listed supplier or open-source maintainer is an established partner.

## Common proposal

Help a builder assemble, understand and repeat **one small desktop robot lesson**
using an existing computer, a serviceable mechanism and clear local start/stop
behavior. Family/STEM is a supervised use scenario, not an established child-safe
product category. Optional LLM drafting stays outside motor authority.

SeedCore currently provides browser authoring/simulation, offline DRC/BOM and
bounded host-simulation evidence. Custom-build simulation, physical MCU
firmware/enrollment and qualification remain open. Begin source/model reviews
without connecting hardware; a physical phase needs its exact accepted profile.

A potential supplier contributes applicable documentation, test access and
repair/update support. A research maintainer can clarify source artifacts and
reproduction requirements. SeedCore contributes reviewed build/interface
mappings, a bounded lesson and an independent setup/evidence packet. Lower
integration/support effort is the hypothesis to test, not an established benefit.

## Brief A: Existing one-to-three-servo mini fixture

**User outcome:** build and repeat one bounded tabletop motion lesson before
adding an arm, leg or advanced joint family.

**Proposal:** close the current ESP32-S3 / STS3215 TTL fixture facts using the
[CW-D01 register](../development/robotics/m0_cw_d01_register_2026_10_19.md).
Progress from one servo to three only after the applicable acceptance evidence.
Reuse current contracts; this brief does not choose a replacement controller.

Evaluate packaging the same fixture as a **reusable dock starter kit** plus
printable attachment designs. Keep one complete first lesson in the starter;
review a passive shape change before promising a new actuated mechanism. The
[product analysis](../development/strategy/mini_robotics_base_attachment_product_analysis.md)
separates price hypotheses from actual starter/attachment costs, while the
[dock design](../development/integrations/robotics_partner_integration_architecture.md#reusable-desktop-dock-and-attachment-discovery)
keeps rails, connectors, mounting and discovery provisional. No new physical
profile or customer study is launched by this brief.

| Responsibility | Draft scope |
| --- | --- |
| Supplier/integrator contribution to request | Exact board/servo revision, current drawings and connector views, electrical/load data, harness/supply options, source terms and repair/support route |
| SeedCore work | Known/unknown source record, assembly/model mapping, firmware/session/ingress plan and qualification fixtures |
| Deliverables | Dock concept/source gap record, reviewed rail/pin/harness plan when supported by evidence, complete starter versus incremental attachment costs, lesson/setup guide and allow/deny/interruption evidence for each accepted scope |
| Completion | Exact fixture passes the applicable CW/M/G gates, with local stop behavior and independent setup recorded; otherwise remain simulation-only |

Open questions include the connector-numbering conflict, regulated supply and
peak load, USB backfeed, torque/holding behavior on timeout, exact unit access
and actual kit cost. Do not apply a generic 12 V/24 V recommendation to this
servo. Neither browser DRC nor the $12 controller-parts target is a wiring plan
or a supplier quote.

## Brief B: ODRI open mini-actuator source and fabrication study

**User outcome:** an academic or experienced maker can understand and reproduce
one small torque-controlled joint with a realistic tool/process budget.

**Proposal:** select one upstream actuator revision, starting from the
[ODRI project](https://open-dynamic-robot-initiative.github.io/) and
[hardware source](https://github.com/open-dynamic-robot-initiative/open_robot_actuator_hardware).
Study one actuator/test stand, its controller/encoder/calibration chain and
printed/machined dependencies. Begin with source/model feasibility; this is
not a commitment to a Solo robot or a home-printer-only build.

| Responsibility | Draft scope |
| --- | --- |
| Maintainer/community facts to establish | Exact source version, applicable notices, build instructions, required electronics/tooling and known reproduction issues |
| SeedCore work | Source manifest, fabrication/inspection record design, joint/axis/unit mapping and unsupported-contract gap review |
| Deliverables | Pinned CAD/BOM/code references, process/tool access and cost/effort record, single-joint model/comparison plan and go/defer recommendation |
| Completion | Independent reproduction appears feasible within the named lab's process, mass and budget; any built unit has an inspection/calibration record before powered qualification |

Do not substitute arbitrary filament, printer settings, motor, encoder or
gearing while retaining an acceptance claim for the original design. Record
failed prints, machined work and rework in costs. Physical closed-loop control
and evidence remain a later accepted phase; an open license supplies no motion
authority.

## Brief C: Compact commercial-joint feasibility, CubeMars first

**User outcome:** a named small arm or leg test stand needs a capability that
the small-servo baseline demonstrably cannot provide.

**Proposal:** investigate one exact AK40-10 configuration, using the
[source-reviewed comparison](../development/strategy/robotics_component_cooperation_strategy_2026.md#assessment-of-the-seven-supplied-initiatives).
Disambiguate revision, driver inclusion, protocol/firmware and control mode.
Begin with a source/model/interface study. COOP-03 and the ODRI COOP-04 study
are alternatives for the first later implementation experiment.

| Responsibility | Draft scope |
| --- | --- |
| Supplier facts/access to establish | Applicable datasheet/CAD/manual, firmware/control-mode revision, bus/bridge details, loaded limits, local stop semantics, price/availability and repair route |
| SeedCore work | Whole-build mass/cost comparison, axis/feedback mapping, supply/thermal/ingress analysis and proposed contract gaps |
| Deliverables | Exact source/profile candidate, read-only/offline fixture, unsupported-bus review and measured-gap versus complexity decision |
| Completion | Candidate fits the named lesson's total mass, complete system budget and support needs; live bench work waits for accepted bus/driver/profile and power/stop evidence |

No current CAN/CAN FD schema/routing support is implied. Vendor protection or
MIT/servo mode names do not establish accepted local authority, calibrated
output torque or a stopping bound. Keep direct vendor tools and alternate bus
paths in the ingress inventory.

## Conditional mini-mechanism options

| Candidate | Appropriate first concept | Facts needed before an experiment |
| --- | --- | --- |
| RealMan WHJ03 | One compact precision joint for a lab desktop arm | Exact model/controller/CAN FD, feedback and stopping/holding behavior, supply/regeneration handling, CAD and complete cost |
| Bonsystems BCSA Micro | Finger-sized mechanism feasibility | Revisioned mass/voltage/torque data, driver/protocol, mounting, actual access, replacement and support terms |
| igus Apiro or exact ReBeL module | Modular low-load teaching mechanism | Separate gearbox from integrated joint, exact motor/encoder/controller, mount/weight, bus, CAD rights and actual cost |
| OpenQDD V1 | Larger DIY actuator design/assembly reference | Resolve artifact terms and complete build/process costs; do not present it as the micro or under-$100 family baseline |
| RP1/ROMOMO | Documentation/test-method reference only | No humanoid or 48 V joint integration allocated to the current mini offer |

Primary sources, corrections and unverified facts are maintained in the
[strategy](../development/strategy/robotics_component_cooperation_strategy_2026.md).
The previous compute, RGB-D capture, middleware, tactile and industrial-arm
briefs are deferred; a later named mini task and capacity decision are required
to reopen any of them.

## Review and handoff

Assign an owner, baseline lesson, numeric requirements, sample plan, effort cap,
process/test access and next review before an experiment. Use the roadmap's
bounded research caps. Review complete cost and repair/setup effort; historical
project BOMs and vendor headlines are not current landed-kit quotations.

Before any physical phase, establish exact unit/build identity, accepted
controller and mutation ingress, source and signal rails, local stop behavior,
required capture/signer assurance and applicable CW/M/G evidence. Adult bench
qualification precedes a proposed supervised lesson; public product claims
follow the accepted scope.

Resolve artifact ownership/notices, redistribution, supported revisions,
manufacturing/QA where relevant, update/rollback, repair, end-of-support and
incident responsibilities. No free samples, badge, exclusivity, co-marketing or
revenue share is assumed. Propose paid integration or conformance maintenance
only after repeat useful delivery and support measurements.

The handoff is one selected brief plus source/fit record, scope, version pins,
failure cases, cost/effort evidence, open gates and go/rescope/defer decision.
These are local drafts; no external messages have been sent.
