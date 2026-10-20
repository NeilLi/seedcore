# Mini-robotics component cooperation strategy

Date: 2026-10-20
Status: Revised proposal for lightweight desktop and supervised family/STEM robotics; no supplier qualification or agreement
Repository baseline: `ba0d132`; CW-A04 offline DRC/BOM complete, CW-S01 next

## Recommendation

Focus cooperation on **small smart servos, printable structures and reproducible
single-joint modules** for hobbyists, academic labs and consumer-product
prototypes. SeedCore supplies build identity, bounded authority and evidence;
the selected controller retains local motor control. The entry experience is a
local computer, browser authoring and a useful small-robot lesson.

Package this as an **affordable reusable base-station starter kit**, followed
by **modular, 3D-printable attachments**. Include a usable first mechanism and
lesson, then expose the real incremental cost of passive parts versus added
servos/sensors. The [base/attachment product analysis](mini_robotics_base_attachment_product_analysis.md)
uses Robosen's Mini platform as a source-reviewed reference and defines price
tests, complete-cost economics and demand validation. It does not establish
consumer preference, a shipping dock, fixed rails or a $20–$50 active-pack cost.

This revision supersedes the earlier priority on D-Robotics, Orbbec and Viam.
Those remain optional dependencies when a measured mini-robot task needs them.
Industrial cells, general-purpose hands, large humanoids and fleet middleware
are outside the current cooperation backlog. The previous broad assessment is
retained in Git history (`3bbb729`); it is not the current shortlist.

Use three levels:

1. **First delivery:** complete exact-part diligence for the existing ESP32-S3 /
   STS3215 TTL candidate, progressing one servo to three under current gates.
   This is the smallest change to the current kit, catalog and Fast Spine plan.
2. **Bounded supporting research:** study ODRI's small open actuator architecture
   and the exact CubeMars AK40-10 revision as alternative future references.
   Begin with documents/model/interface feasibility; select at most one later
   experiment after a demonstrated need and capacity review.
3. **Conditional options:** RealMan WHJ03 for a compact precision joint,
   Bonsystems BCSA Micro for a finger-sized task, and an exact igus module for
   modular mechanics. OpenQDD is a larger DIY research reference; RP1/ROMOMO is
   a humanoid reference outside the mini-kit scope.

CW-S01 and native Microduck acceptance retain implementation priority. This
proposal creates no new catalog parts, driver, bus support or physical profile.
See the [architecture](../integrations/robotics_partner_integration_architecture.md),
[roadmap](../robotics/robotics_ecosystem_integration_roadmap.md) and
[pilot briefs](../../application/robotics_component_partner_pilot_briefs.md).

## What mini/family means here

“Mini/family” describes a proposed product experience: desktop scale, manageable
assembly, serviceable parts and supervised use. It is not a safety certification
or evidence that a small actuator is child-ready. Freeze total robot mass,
reach, payload, joint limits, supply, mounting and stopping requirements for the
named lesson before selecting a joint. Small size and low supply voltage do not
by themselves bound pinch force, stored energy or gravity-driven motion.

Prefer an existing host computer, local operation and replaceable commodity
parts. Evaluate **complete build cost**, including controller/bridge, supply,
cables, brackets, printing, tools, shipping and repair. The existing selected-kit
below-$300 and controller-parts $12 figures remain design targets from the
[18-month plan](seedcore_physical_ai_execution_plan_2026_2028.md), not quotations
or prices for these candidates. Academic research can have a separate budget;
it must not silently become the family-kit baseline.

## Assessment of the seven supplied initiatives

Priority below is SeedCore's judgment about fit, not a procurement decision.
Manufacturer/project statements are discovery evidence, not SeedCore tests.

| Initiative | Source-reviewed offering and correction | Mini-robotics fit / proposed next step |
| --- | --- | --- |
| **CubeMars AK40-10 / AK45-10** | AK40-10 KV170's table lists 24 V, 185 g, 1.3 N·m rated and 4.1 N·m peak. The same page lists a V3.0 variant at 190 g and contains a conflicting 200 g marketing line. AK45-10 is a different, heavier configuration; do not transfer the 185 g figure or claim all variants accept 48 V. [Manufacturer specifications](https://www.cubemars.com/product/ak40-10-robotic-actuator.html). | **Prepare compact-joint feasibility.** Pin exact motor, driver and firmware; check mass and total system cost against the lesson. Review protocol/control semantics and a separate regulated supply. It is not a drop-in TTL servo. |
| **Bonsystems BCSA Micro** | The manufacturer's 16 January 2026 announcement describes an 18 mm cycloidal micro actuator for robotic finger joints. The announcement does not establish a complete voltage, mass, torque, protocol or retail-price specification. [Manufacturer announcement](https://en.bonsystems.com/media-center/product-video/micro-actuator-bcsa-micro-series-promotion-viedo/). | **Conditional micro-mechanism candidate.** Collect a revisioned datasheet, mounting drawing, driver/API and support/access facts before assessing a finger or miniature gripper. Do not assume hobby pricing or immediate stock. |
| **RealMan WHJ03** | The WHJ03-M-D33-100-N documentation lists 170 g, 33 × 48 mm, 3 N·m rated, 24/48 V and CAN FD. It also specifies an external discharge module for regenerative overvoltage under high loads/speeds. [Exact-model documentation](https://develop.realman-robotics.com/en/joints/parameter/WHJ03/). | **Conditional precision-joint candidate.** Suitable to investigate for a small lab arm; CAN FD, supply/regen handling, local stop behavior and landed cost are separate work. Compact does not establish family-kit suitability. |
| **igus Apiro / ReBeL / robolink** | Apiro is a modular plastic **worm-gear** system with manual/motor configurations; ReBeL includes a distinct integrated **strain-wave** motor/controller/encoder module. These are different product families, not one universal smart micro joint. [Apiro](https://www.igus.com/robot-components/modular-worm-gear), [ReBeL module](https://www.igus.com/product/RL-SE-105-70-0120). | **Conditional mechanics/teaching candidate.** Pick one exact gearbox/motor/controller combination. Confirm complete mass, CAD rights, feedback and budget; a gearbox alone is not a governed actuator. |
| **Open Dynamic Robot Initiative (ODRI)** | Publishes modular torque-controlled actuators, Solo and manipulation designs. The core-v1 reference uses a dual-stage timing belt, printed and machined parts; its documentation recommends precision printing for particular pulleys. The hardware repository declares BSD-3-Clause. [Project](https://open-dynamic-robot-initiative.github.io/), [core-v1 details](https://github.com/open-dynamic-robot-initiative/open_robot_actuator_hardware/blob/master/mechanics/actuator_module_v1/README.md), [hardware repository](https://github.com/open-dynamic-robot-initiative/open_robot_actuator_hardware). | **Prepare open-design study.** Review one pinned actuator version and its separate electronics/calibration chain, starting with a single-joint stand. A home FDM printer and off-the-shelf motor alone do not reproduce the complete system. |
| **aaedmusa OpenQDD V1** | Provides STEP/STL, electronics, code and BOM archives. The creator's 2023 page reports 935 g, a 9:1 planetary drive, ODrive S1 and a historical $247 build cost: the supplied “micro / under $100” framing is unsupported. The inspected repository does not show a top-level license file; redistribution terms need clarification. [Creator specifications](https://www.aaedmusa.com/projects/openqdd), [source repository](https://github.com/aaedmusa/OpenQDD-V1). | **Research reference, defer family-kit integration.** Learn from its printable gearing and assembly approach. Do not treat the historical cost as a current quote or the actuator as a sub-kilogram robot's default joint. |
| **RoboParty RP1 / ROMOMO** | RP1 is presented as a full-stack humanoid platform. The inspected ROMOMO repository contains documentation/test materials, explicitly excludes firmware/source code, and lists 48 V modules; software is in separately licensed repositories. A public release does not establish printer-only fabrication or a micro-joint offering. [RP1 overview](https://github.com/Roboparty/RP1), [ROMOMO scope/specifications](https://github.com/Roboparty/ROMOMO). | **Outside the current mini backlog.** Retain as a source/test-documentation reference. Do not import the humanoid, training stack or motor modules into the family offer. The supplied launch date is not an integration requirement. |

Sources accessed **2026-10-20**. Live pages can change; selected manuals,
CAD/code, licenses and firmware must be pinned before implementation. Unless
explicitly identified as historical above, prices, current availability,
engineering access and partner interest remain unknown. These are companies
and community/research initiatives, not a verified list of 2026 startups or a
market-share ranking.

## Practical cooperation industries

| Cooperation area | First useful outcome | SeedCore's proposed contribution | Priority |
| --- | --- | --- | --- |
| Small smart-servo and affordable kit suppliers | Repeat one bounded desktop motion lesson | Exact build/profile identity, local session limits, evidence and setup guide | First: existing TTL fixture diligence |
| Shared dock, harness and printed attachment suppliers | Reuse power/control and replace a supported mechanism without buying another complete kit | Dock/attachment source records, compatibility and fresh admission after changes; whole-starter versus incremental-cost accounting | Proposed first-family packaging study within existing fixture scope |
| Printable chassis, brackets and educational mechanics | Assemble and repair a small arm/head or single-leg stand | Versioned CAD/source record, mount/axis mapping, unknown-aware BOM | First supporting design work; exact mechanical review still required |
| Open actuator/research communities | Reproduce one documented joint and explain control/dynamics | Source/build lineage, model comparison and test record | ODRI study first; no new full robot |
| Compact integrated BLDC joint suppliers | Improve a demonstrated capability beyond the servo baseline | One future adapter/profile and measured task comparison | One conditional experiment; CubeMars first feasibility candidate |
| Micro-mechanism and polymer gearbox suppliers | Solve a named finger or low-load mechanism need | Exact module/configuration identity and observable task evidence | Bonsystems / igus / RealMan only against task fit |
| Sensors and local AI compute | Add a required observation/proposal capability | Calibrated input and pinned evaluation on existing host first | Optional; no dedicated compute/camera/middleware prerequisite |

## Disposition of the previous integrations

The earlier ten-company review remains background research. This table replaces
its diligence priority without claiming that any product has changed.

| Previous candidates | Revised disposition for mini robotics |
| --- | --- |
| D-Robotics | Defer dedicated edge board until the existing local computer demonstrably cannot meet the task. |
| Orbbec | Optional compact-camera study only if depth is required; no wearable demonstration/data program in the first kit. |
| Viam | Defer additional middleware until repeated setup effort justifies it; a direct small-fixture adapter is the baseline. |
| Bota Systems / Contactile | Defer specialized force/tactile hardware until a qualified small manipulation task needs it. |
| RobCo / Inovo Robotics | Remove industrial-arm/cell work from the active cooperation backlog. |
| Mimic / Skild AI / Field AI | Monitor externally; no universal hand, general-brain or industrial navigation integration in the mini offer. |

## Current foundation and gaps

Central World has twelve draft/proxy parts, canonical assembly v2, immutable
revisions, proxy placement and offline CW-A04 DRC/BOM. CW-S01 custom-build
simulation is next. Microduck is a separately pinned native reference, not a
catalog-built robot or a replacement for the first fixture. Fast Spine remains
simulation-only; exact hardware, firmware, ingress isolation, enrollment and
physical stop evidence are open. See the [active queue](../current_next_steps.md)
and [source register](../robotics/m0_cw_d01_register_2026_10_19.md).

The current component/assembly/DRC contracts do **not** represent CAN or CAN FD
joint networks. Record those candidates in a source/fit document; do not encode
them as TTL UART or add undocumented schema fields. Their implementation would
need reviewed schema, validation, routing and driver work across the stack.

## Cooperation model and next decisions

Start with a reproducible source/fit record and a useful local lesson. A supplier
could contribute exact documentation, sample access and repair/update support;
a research maintainer could clarify artifacts and reproduction steps. SeedCore
could contribute reviewed mappings, conformance fixtures and an independent
setup/evidence packet. These are proposed exchanges, not established partners.

Keep one supported physical profile and one live pilot initially. Evaluate
setup/repair hours, complete kit cost, repeat lesson outcomes and independent
reproduction before proposing paid integration or maintenance. No exclusive
supply, badge, certification, free samples or telemetry revenue is assumed.

At the next review, close existing fixture facts first; spend bounded remaining
research time on ODRI and exact CubeMars feasibility. Select a later experiment
only when it resolves a named mini-robot need within mass, power, cost and
support constraints. Preserve local stop/control ownership and the existing
CW/M/G acceptance gates throughout.
