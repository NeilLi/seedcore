# Robotics component cooperation strategy

Date: 2026-10-20
Status: Source-reviewed strategy proposal; partner access, compatibility and commercial demand unvalidated
Repository baseline: `7f9d846`; local source and current planning documents inspected

## Recommendation

Develop cooperation around **qualified components, governed execution and
reusable evidence**. SeedCore's current Central World catalog and assembly
tools provide an entry point; its trust runtime supplies the admission and
verification boundary. Preserve the affordable maker/STEM and OEM offer.

Prioritize technical diligence on **D-Robotics**, **Orbbec** and **Viam**.
D-Robotics is a candidate edge-compute substrate, Orbbec a perception/capture
supplier, and Viam a potential adapter/distribution partner with substantial
product overlap. This ranking is SeedCore's judgment about architectural fit,
not a finding that any supplier is compatible, available or willing to partner.
It does not select a board, replace the ESP32-S3 fixture or start three integrations.

Prepare force/tactile evidence requirements for Bota Systems and Contactile.
Keep industrial modular arms, dexterous hands and proprietary general robot
brains as conditional expansion. The next implementation package remains
CW-A04; Microduck's native M0–M4 gates remain open.

Use the [integration architecture](../integrations/robotics_partner_integration_architecture.md),
[development roadmap](../robotics/robotics_ecosystem_integration_roadmap.md) and
[pilot briefs](../../application/robotics_component_partner_pilot_briefs.md)
to turn this assessment into reviewable work.

## What the standardization thesis gets right

Reusable sensing, compute, mechanical modules and software interfaces can
reduce repeated integration work. SeedCore can test whether a versioned
component/profile improves setup, support and evidence collection across
installations. That is a concrete cooperation hypothesis.

Distinguish four different achievements: modularity within one vendor's system,
a documented API, an independently implementable interface, and demonstrated
interoperability between vendors. The supplied list contains examples of the
first two; the sources reviewed do not establish one common robotics standard
across all ten companies. Mechanical fit, electrical compatibility, observation
semantics, authority and evidence each need their own qualification.

Specialized compute alone does not resolve those boundaries. More TOPS cannot
establish model compatibility, maximum command age, observed stopping or a
trustworthy signer. A business case also needs recurring user value and
supportable delivery costs; no market-size or profitability estimate is assumed.

## Industry opportunities and SeedCore fit

| Cooperation industry | Useful customer outcome | SeedCore contribution to validate | Development posture |
| --- | --- | --- | --- |
| Affordable kit OEMs and education delivery | A repeatable browser lesson with understandable start/stop and results | Catalog/build identity, bounded sessions, conformance and operator evidence | Current distribution/customer wedge; existing OEM brief owns kit scope |
| Edge AI compute and development boards | Local perception or proposals within a measured latency/power budget | Pinned model/runtime profile, authority separation and comparable evaluation | First diligence priority; add compute only when the existing-host baseline has a measured gap |
| 3D perception and human demonstration capture | Calibrated observations or reusable adult research recordings | Capture lineage, clock/coverage accounting and separately controlled reuse | Perception evaluation before a wearable dataset program |
| Force/torque and tactile sensing | Understand contact, grip loss or excessive force in a bounded task | Calibration-aware evidence and observable task predicates | Later manipulation research; no new physical profile now |
| Modular industrial automation | Reconfigure a cell while preserving traceability and qualification | Build/profile change invalidation, admission and replay | Customer-funded or explicitly budgeted feasibility after the first supported offer |
| General robot intelligence | Compare or substitute a behavior provider on one known embodiment | Provider-specific proposal/control boundary, pinned behavior and independent outcome verification | Monitor access and semantics; preserve local-controller ownership |

## Assessment of all ten candidates

Priority means diligence order, not procurement or an integration commitment.
**Prepare** fits the current architecture; **conditional** needs a new task or
profile; **monitor** has a substantial access, scope or control-boundary gap.
All ten remain unqualified by SeedCore.

| Candidate | Verified offering and correction to supplied framing | Cooperation hypothesis / SeedCore seam | Priority and first unresolved question |
| --- | --- | --- | --- |
| **D-Robotics** | Official documentation describes RDK boards/modules and Sunrise silicon. X5 is one concrete candidate; its advertised 10 TOPS is a vendor specification, not a SeedCore benchmark. [RDK suite](https://developer.d-robotics.cc/rdk_x_doc/en/RDK), [X5](https://developer.d-robotics.cc/en/rdkx5). | Run a pinned perception/proposal workload on a Linux host; retain native robot control or the separately qualified Fast Spine MCU. Offer a reproducible governed reference profile if it solves a real deployment gap. | **Prepare, first.** Can the selected model, conversion toolchain and runtime meet output-parity, tail-latency, memory, thermal and landed-cost requirements? |
| **Orbbec** | Supplies robotics/3D vision. Its August announcement distinguishes an EGO RGB-D series from a **Dual-Ego prototype**. Orbbec describes itself as publicly listed, so this is an ecosystem-company list rather than ten early-stage startups. [Capture announcement](https://www.orbbec.com/news/scaling-real-world-data-for-physical-ai-orbbec-showcases-robot-free-data-collection-hardware-platform-at-roscon-jp-2026/), [company](https://www.orbbec.com/company/). | Start with one local, calibrated RGB-D recording for the evidence path. Consider adult egocentric demonstrations only when a named learning task and data rights justify them. | **Prepare, second.** Which exact shipping SKU/SDK exposes timestamps, calibration and loss indicators, and permits the intended offline recording/export? |
| **Viam** | Provides machine/component APIs, modules and deployment/data infrastructure. It also markets agent tooling, enforced limits and reusable skills, overlapping SeedCore's product surface. Its SDK is not proof that every device is supported. [Architecture](https://docs.viam.com/operate/reference/architecture/), [current positioning](https://www.viam.com/). | A narrowly scoped adapter could reuse hardware connectivity while SeedCore owns the declared admission/evidence contract. Distribution is plausible only if both parties see value beyond existing controls. | **Prepare, third; partner and competitor.** Can all relevant mutating paths be fenced at the executor, and does incremental buyer value justify another runtime? |
| **Bota Systems** | Manufactures six-axis force/torque sensors; these measure a wrench, distinct from spatial fingertip touch. SensONE documentation lists integration interfaces and software support. [SensONE](https://botasys.com/force-torque-sensors/sensone/). | A calibrated wrench stream could support contact evidence and later bounded force-sensitive tasks. Start from a licensed recording; select a sensor range only against a specific fixture. | **Conditional: sensing research.** What range, noise, overload, tare, mounting frame and sampled timing fit the task and kit economics? |
| **Contactile** | PapillArray measures local force/displacement/vibration and slip/friction properties; product material also describes tactile-native two-finger grippers. [Products](https://contactile.com/products/), [technology](https://contactile.com/novel-optical-sensing-technology/). | Compare tactile-assisted grasp evidence with a vision-only baseline on a future accepted manipulation profile. Separate sensor observation from any gripper's autonomous control. | **Conditional: sensing research.** Are raw signals, derived estimates, calibration, replaceable surfaces and local grip-control bounds exposed and supportable? |
| **RobCo** | Offers configurable modular industrial robots and an integrated software stack. Its catalog supports multiple axis counts; this does not demonstrate cross-vendor interchangeable joints or live hot-swapping. [Modular robots](https://www.rob.co/en-us/technology/hardware/modular-robots), [integrated solutions](https://www.rob.co/en-us/solutions/offerings/integrated-solutions). | Study versioned cell/build profiles and requalification after reconfiguration. A later cell integrator could use governed task admission and evidence exports. | **Conditional: industrial demand.** Are CAD/controller interfaces and interrupt/evidence hooks accessible under suitable terms, with a named cell-support owner? |
| **Inovo Robotics** | Publishes modular-arm manuals, CAD, URDF and an API link. The inspected manual is dated January 2023 and marked pre-release; public documentation does not confirm current supply, support or dynamic payload adjustment. [Downloads](https://inovorobotics.com/downloads/), [manual 5.6.0 v19](https://inovorobotics.com/wp-content/uploads/2023/06/URD-0002-User-Manual-Inovo-Robotics-Modular-Arm-5.6.0-v19.pdf). | A source-reviewed arm model could later exercise assembly import and configuration-change evidence, subject to model rights and a separately qualified controller. | **Conditional: industrial demand.** What configuration, current controller release, support route and availability can actually be established? |
| **Mimic** | Its July 2026 release presents the M1 hand, U1 wearable and in-house software as a **full-stack platform**. A generally available universal bolt-on hand API is not established by that release. [Full-stack announcement](https://www.mimicrobotics.com/blog/solving-dexterity-a-full-stack-approach). | Future demonstration/behavior provenance and constrained hand-task evaluation. Mechanical attachment alone would not establish policy transfer. | **Monitor.** Does an accessible developer package expose the hand/controller, demonstration rights and independent stop/evidence seams? |
| **Skild AI** | Describes cross-embodiment intelligence with both high-level and high-frequency low-level policies. The reviewed sources do not establish an open, universally deployable SDK. [Technical description](https://www.skild.ai/blogs/building-the-general-purpose-robotic-brain). | Evaluate one supported skill/provider integration. High-level outputs can be proposals; low-level outputs require an authority-enforcing boundary before actuator dispatch. | **Monitor.** Is a bounded control surface available on the selected body without taking unreviewed ownership of the motor path? |
| **Field AI** | Describes embodiment-agnostic autonomy and industrial mobile-robot applications. This is evidence of a vendor offering, not identical deployable binaries or certified behavior on every chassis. [Solutions](https://www.fieldai.com/solutions), [technical/company announcement](https://www.fieldai.com/news/fieldai-announces-over-400m-in-funds-raised-to-advance-embodied-ai-at-scale). | A future inspection mission could combine zone/time/task admission with local autonomy and outcome evidence. It would be a different customer and physical profile. | **Monitor.** Are mission limits, cancellation, localization uncertainty and evidence exports exposed on an accessible supported robot? |

Official pages were checked on **2026-10-20**. Product statements above are
vendor-documented or vendor-claimed, not independently measured. Undated live
pages are discovery references; selected SDKs, manuals, licenses and binaries
must be revision-pinned before implementation. The supplied secondary lists
are leads, not acceptance evidence. Prices, lead times, partner interest and
commercial access remain unknown for every candidate.

## Current SeedCore foundation and the integration gap

| Inspected surface | Available foundation | Gap a cooperation must close |
| --- | --- | --- |
| [Component registry](../../../packages/component-registry/README.md) | Twelve draft/proxy parts, strict schema and exact asset/catalog pins | No qualified supplier parts; new exact revisions and source rights need review |
| [Assembly v2](../../../packages/component-registry/assemblies/README.md) and [Mini Studio](../../../ts/apps/mini-studio/README.md) | Canonical assemblies, immutable revisions and proxy placement | CW-A04 DRC/BOM and later import/simulation/admission remain separately gated |
| [Microduck driver](../../../src/seedcore/hal/drivers/microduck.py) | Explicit read-only adapter; hardware profile rejects | Native controlled motion, independent training parity and M2–M4 remain open |
| [Fast Spine session](../../../src/seedcore/robotics/fast_spine/session.py) and [profile](../../../packages/robotics-profiles/fast-spine-v1/profile.json) | In-process simulation session, token/watchdog/framing foundation | MCU firmware, execution ingress isolation, enrollment and physical measurements |
| [Simulation evidence](../../../src/seedcore/robotics/fast_spine/evidence.py) and [Rust kernel](../../../rust/README.md) | Scoped host-signed simulation receipts and verification | Sensor/vendor capture is a different assurance class; hardware claims need an accepted capture/signer path |

This strategy adds no vendor SDK, catalog entry, runtime binding or physical
qualification.

## Cooperation and commercial model

| Model | Partner supplies | SeedCore supplies / possible paid value | Proof needed |
| --- | --- | --- | --- |
| Reference integration | Exact SDK/firmware, test access, engineering support | Adapter, governed example, conformance fixtures and maintained profile | Independent setup, complete ingress inventory and reproducible accepted scope |
| OEM design-in | Manufactured kit, QA, repair and update ownership | Provisioning/conformance maintenance, supported lessons and optional governance | Existing G0–G4 evidence, useful repeat delivery and actual support cost |
| Research data cooperation | Licensed recordings, calibration and capture metadata | Coverage/provenance processing and task evaluation | Rights, retained samples and held-out improvement; no required school-data contribution |
| Industrial co-delivery | Named customer/cell and accountable integrator | Task admission and evidence integration | Budgeted feasibility, observable limits, local interruption and sustainable support |

Commercial differentiation must be measured, particularly with Viam. Test
whether independent verification, cross-provider records or institution-specific
delegation solve a problem beyond the supplier's native controls. If they do
not, reuse the supplier without building another governance layer, or defer.
Certification fees, exclusivity, revenue shares and dataset revenue are not
assumed. SeedCore's existing open/paid boundaries remain in the
[18-month plan](seedcore_physical_ai_execution_plan_2026_2028.md).

## Decisions for the next review

1. Keep CW-A04, exact first-fixture data and native Microduck acceptance as the
   implementation priorities. Review cooperation evidence alongside those tasks.
2. Use the pilot briefs to collect missing interface/version/access facts for
   the three prepare candidates; retain an explicit unknown where evidence is absent.
3. Select at most one adapter experiment after a measured need, an effort cap
   and capacity are recorded. A licensed replay or simulated device is a valid
   first result; label its scope accurately.
4. Advance sensing/manipulation or industrial work only through an explicit
   portfolio decision with a customer outcome and separate profile/support budget.

The [active queue](../current_next_steps.md) owns immediate sequencing. The
[18-month plan](seedcore_physical_ai_execution_plan_2026_2028.md) owns dates and
G0–G5. This proposal supplies candidate choices and experiments within those
gates; it creates no external commitments.
