# Robotics component cooperation: draft pilot briefs

Date: 2026-10-20
Status: Internal drafts; no contact, partner agreement, procurement or deployment

These briefs support the [cooperation strategy](../development/strategy/robotics_component_cooperation_strategy_2026.md)
and [integration roadmap](../development/robotics/robotics_ecosystem_integration_roadmap.md).
They complement the [SeedCore Inside OEM brief](oem_partnership_brief.md), which
continues to own the first affordable-kit design-in. None of the ten assessed
companies is an established SeedCore partner.

## Common proposal

SeedCore is building an open trust runtime for affordable physical AI. Current
foundations include browser simulation, canonical component/assembly authoring,
a read-only Microduck adapter and bounded host-simulation evidence. Native
governed motion, MCU firmware/enrollment and physical qualification remain open.

The proposed cooperation is a **small, reproducible integration on one named
profile**, with clear responsibilities and an independent evidence packet.
Begin with offline or read-only evaluation. Scale only after useful repeat
delivery and accepted support/update responsibilities.

The partner benefit to test is lower integration and institutional-adoption
effort. SeedCore's benefit is a reusable, supportable profile. Neither benefit
is established by an attractive demo or by preparing this brief.

## Brief A: D-Robotics local-compute feasibility

**User problem to validate:** a named perception/proposal workload cannot meet
its latency, power or connectivity needs on the current host. If the existing
host meets the lesson's needs, defer this pilot.

**Proposal:** compare the same permitted recorded inputs and pinned model
semantics on the existing CPU baseline and one exact RDK configuration. X5 is
a diligence candidate, subject to model fit and access. Review the official
[RDK suite](https://developer.d-robotics.cc/rdk_x_doc/en/RDK) and
[conversion workflow](https://developer.d-robotics.cc/rdk_x_doc/en/Advanced_development/toolchain_development/intermediate/ptq_process)
before selecting hardware or claiming acceleration.

| Responsibility | Draft scope |
| --- | --- |
| Partner contribution to request | Exact board/module revision, supported OS/SDK/toolchain versions, conversion examples, license/redistribution terms, support route and test access |
| SeedCore work | Baseline/candidate harness, versioned input/output mapping, late-output rejection and performance/evidence report |
| Deliverables | Pinned model/conversion/runtime manifest, accuracy/parity report, end-to-end timing and resource measurements, cost/support estimate and go/defer recommendation |
| Completion decision | Frozen parity/deadline requirements met on the named configuration and a measurable advantage over the baseline; otherwise preserve the baseline |

Questions for a future technical discussion: which operators and tensor formats
run on the BPU, which remain on CPU, what conversion changes numeric behavior,
what artifacts may be redistributed, and how are OS/runtime updates pinned and
rolled back? Record price, lead time, board access and specialist support as
unknown until evidenced.

**Scope limit:** no motor bus, robot motion, replacement Fast Spine firmware or
new hardware trust-root claim. Compute can generate proposals; the accepted
native controller/MCU boundary retains execution ownership.

## Brief B: Orbbec calibrated observation replay

**User problem to validate:** a specific perception/evaluation task needs
calibrated depth or synchronized observations absent from the current path.

**Proposal:** evaluate one licensed adult bench recording from an exact
shipping RGB-D device and SDK. Record source timestamps, clock relation,
intrinsics/extrinsics, depth scale, raw/derived lineage and missing samples.
The [Orbbec capture announcement](https://www.orbbec.com/news/scaling-real-world-data-for-physical-ai-orbbec-showcases-robot-free-data-collection-hardware-platform-at-roscon-jp-2026/)
describes several capture configurations; a Dual-Ego prototype is not a
substitute for confirmed access to a supported product.

| Responsibility | Draft scope |
| --- | --- |
| Partner contribution to request | Exact device/firmware/SDK, calibration and timestamp documentation, sample recording with explicit evaluation rights, export format and support route |
| SeedCore work | Read-only recording adapter, validity/coverage checks, replay projection and provenance report with true capture assurance |
| Deliverables | Versioned recording/calibration manifest, clock/gap report, replay example, permitted-use record and useful-task comparison |
| Completion decision | Required metadata and rights exist; deliberate frame loss, stale calibration and changed-stream cases are detected; the recording improves the named evaluation |

Questions: are device and host timestamps both available, how is synchronization
validated, which depth values are measured versus model-enhanced, what happens
at drop/overflow, and can recordings be exported and deleted without a required
cloud dependency? Confirm the selected product's actual terms and behavior.

**Scope limit:** no child-facing capture, default cloud egress, bulk dataset
collection or robot actuation. A later adult EGO study needs a named learning
objective, accessible hardware, consent/recording rights and a separately
budgeted retargeting/evaluation design. Human video is not a robot action trace.

## Brief C: Viam interoperability and overlap assessment

**User problem to validate:** the current adapter imposes repeated device-setup
work or blocks a distribution path that Viam could materially improve.

**Proposal:** map one simulated or read-only Viam machine's resources and
configuration revision into SeedCore's observation/profile conventions. In
parallel, inventory all paths that could mutate hardware before considering
governed motion. Review Viam's [platform architecture](https://docs.viam.com/operate/reference/architecture/)
and [session behavior](https://docs.viam.com/dev/reference/apis/sessions/).

| Responsibility | Draft scope |
| --- | --- |
| Partner contribution to request | Supported module/SDK versions, simulator/read-only setup, resource/configuration semantics, session/stop behavior, export/deployment terms and engineering contact |
| SeedCore work | Small observation/resource adapter, ingress/ownership map, setup comparison and governance-overlap assessment |
| Deliverables | Resource-to-profile mapping, version pins, revision-change fixtures, session/reconnect review and go/defer decision |
| Completion decision | Reproducible read-only integration and measurable setup/distribution benefit; live feasibility proceeds only if every relevant mutating ingress can be fenced |

Questions: how are raw/generic commands, motion services, UI teleoperation,
module installation and configuration updates controlled? What happens when
two clients use one resource, a client reconnects or an update changes a module?
Can original logs and records be exported under acceptable terms?

The commercial question is explicit: which customer needs SeedCore's independent
verification or institution-specific authority records in addition to Viam's
native capabilities? If no distinct need emerges, defer the extra dependency.
**Scope limit:** no claim that middleware authentication/session heartbeats
implement SeedCore's action admission, freshness or evidence contract.

## Later sensing and industrial briefs

| Candidates | First bounded cooperation concept | Evidence required before a pilot is committed |
| --- | --- | --- |
| Bota Systems / Contactile | Licensed force/tactile replay, then one accepted contact/grasp task if needed | Exact sensor/gripper revision, raw/derived semantics, calibration/range/saturation, timestamps, control ownership and replacement/support costs |
| RobCo / Inovo | Configuration/model study for one actual industrial customer task | Current supply/support, licensed CAD/URDF, controller ingress, interrupt/recovery semantics, task budget and accountable cell integrator |
| Mimic | One hand demonstration/control feasibility study | Accessible hardware/API, joint/action mapping, wearable/recording rights and an independent local-stop/evidence interface |
| Skild AI / Field AI | One provider skill/mission boundary study on a supported body | Developer access, high-/low-level control ownership, bounded cancellation, model/version pins and independent telemetry/outcome export |

No general-purpose hand, industrial arm or outdoor inspection profile is added
to SeedCore's current supported offer through these concepts. Source evidence
and qualification gaps for every candidate are in the strategy assessment.

## Common review and commercial terms to resolve

Before an experiment, assign an owner, comparison baseline, numeric limits,
sample plan, effort cap, next review and access/recording permissions. Before
physical work, also establish the profile's G0–G2-equivalent evidence, enrolled
identity where required, local stop and repair/support ownership.

The draft cooperation record should cover artifact/data ownership and licenses,
engineering-sample terms, supported versions, factory/enrollment responsibility
where relevant, update/rollback and end-of-support, incident escalation,
reproducible acceptance, public claims and any badge use. Do not assume free
samples, volume discounts, exclusivity, co-marketing or revenue sharing.

Track integration/setup/support hours, actual resource and hardware costs,
eligible-task results, denied/interrupted/uncertain attempts and independent
reproduction. Propose paid integration or conformance maintenance only when
these measurements support a useful offer. Research export remains optional
and separately controlled.

The prepared handoff is the selected brief plus its source/fit record, scope,
version pins, failure cases, evidence requirements and go/rescope/defer review.
These are local draft documents; no messages have been sent.
