# Mini-robotics product analysis: reusable base and printable attachments

Date: 2026-10-20
Status: Product/pricing hypotheses and engineering proposals; no launched SKU, price commitment or qualified dock
Research baseline: `ba0d132` plus the then-pending mini-robotics cooperation revision
Implementation status reviewed: 2026-10-27 against the 26 October active queue and package records

## Recommendation

Adopt a **two-tier hardware offer**: an affordable, useful base-station starter
kit, followed by modular attachments with downloadable printable designs.
Reuse the local computer, controller, power distribution and connection workflow
across one supported family of desktop mechanisms. Make the first lesson usable
without a cloud account or a second purchase.

This is a proposed way to reduce repeated setup and component cost. Robosen
provides a relevant product pattern; its catalog does not establish SeedCore's
consumer demand, conversion, margins or repeat purchases. Validate those before
committing to retail prices or tooling. Keep the existing small TTL fixture and
CW/M/G delivery boundaries from the [cooperation strategy](robotics_component_cooperation_strategy_2026.md)
and [active queue](../current_next_steps.md).

## Robosen reference: evidence and limits

Official pages accessed **2026-10-20**; US advertised prices are snapshots, not
landed prices, supplier costs or a comparable SeedCore quotation.

| Observed reference | What it supports | Limit on inference |
| --- | --- | --- |
| Mini Base lists **$69.99**, with the figure excluded. [US base](https://us.robosen.com/products/robosen-mini-base). | A reusable base is sold as a separate purchase. | This is not a complete first-play price or proof of its manufacturing cost. |
| WALL-E/EVE set lists **$159.99** and includes one universal base. [Exact set](https://us.robosen.com/products/mini-robot-wall-e). | Bundle contents matter when comparing acquisition cost. | Do not subtract the base price to infer a universal figure price or margin. |
| Collection lists Toy Story **from $99.99**, Minions **from $49.99**, and a Toy Story 5 set at **$179.99**. [US collection](https://us.robosen.com/collections/mini-robot). | There are multiple price/contents tiers. | “From” prices are variant-dependent; $99–$159 is not the whole lineup. |
| The official Mini overview describes four-axis servo control, plug-in character chips, Studio custom moves/sounds and one-click routine generation, plus Hub sharing. [Platform overview](https://www.robosen.com/us/mini-robot). | Reusable mechanics, content identity and creation tools form a coherent experience. | It does not document NFC/EEPROM technology, a public connector pinout, or proof that manual keyframing is the only creation mode. |

The reference suggests a reusable-platform or “cartridge” analogy. There is no
basis here to claim Robosen copied Nintendo, solved all consumer cost problems,
or has demonstrated a preference for SeedCore-style printable functional tools.
Licensed characters, immediate play, packaging and content may drive purchase
independently of modularity; their relative importance is unknown.

Do not treat a reported base weight as every figure's weight, assert a specific
pogo-pin construction or chip protocol without a manual/inspection, or infer
absence of all sensors/feedback/security from a retail page. A claim that
SeedCore is universally more intelligent or safer is not supported by either
product's currently available evidence.

## Tier 1: base-station starter kit

The intended buyer purchases one **Fast Spine Desktop Dock starter kit** for a
named desktop mechanism family. It includes the proposed controller/USB bridge,
reviewed power supply and distribution, harness, enclosure/baseplate, local
stop controls and a first useful mechanism/lesson. Include one reusable servo
or state clearly which complete mechanism/actuator pack is included. A bare
dock that cannot perform the advertised first lesson is not the starter offer.

The existing computer is separately owned; call it the **Local AI Station**.
The dock is an accessory to that computer, not another inference workstation.
A rechargeable battery, display, speaker, camera and NFC reader are not first
kit requirements. Evaluate a wired bench supply first to reduce duplicated
battery/charging work. A future battery kit needs its own profile and economics.

Test complete starter-kit price points such as **$79 / $99 / $129 USD** only
as research hypotheses, with the same included first lesson and disclosed tax,
shipping and printing requirements. These are not established feasible prices.
The Robosen base's $69.99 is a reference anchor, not a required SeedCore price.
The existing below-$300 selected-kit and $12 controller-parts targets retain
their original scope; neither is a new retail promise or a complete dock BOM.

## Tier 2: modular, printable attachments

Keep two fulfillment choices inside this tier: downloadable original CAD/build
files for self-printing, and optional supplied mechanical or active packs.
Choose and record appropriate file licenses. Local lessons and basic operation
remain available without a paid cloud subscription.

| Attachment type | What the builder reuses | Incremental cost to expose |
| --- | --- | --- |
| Passive shell/bracket or alternative tool geometry | Dock, controller, supply and the same moved/reused actuator set | Print material, fasteners, wear parts and assembly effort; no claim of extra independent DOF |
| Pan-tilt or three-DOF arm mechanism | Dock electronics/power only within its qualified capacity | Additional servos, cabling, bearings, sensor if required, print/assembly, changed load and qualification |
| Supplied mechanical/active pack | Same platform plus inspected parts and supported instructions | Manufacturing/test, packaging, shipping, repairs, support and any required new power capacity |

The suggested **$20–$50** is a hypothesis for an attachment's incremental retail
price or a maker's out-of-pocket build cost; label which one is being tested.
Do not use both meanings interchangeably. Price-test active packs at explicit
points such as $20 / $35 / $50 only after listing exactly which servos/sensors
are included. A printable file is not a free motor, and a $12 controller target
does not establish an active attachment's landed cost.

The initial mini family is sequential and **one attachment active at a time**.
Sharing a dock does not support simultaneous robot execution, shared authority
or automatic reuse of calibration. Start with a single-servo lesson; pan-tilt
and small-arm attachments remain later task/profile decisions. Different mass,
reach, axes or current can require requalification even with the same connector.

Do not force all actuators into the dock to mimic character toys. That can lower
passive-body cost but constrains kinematics and introduces mechanical transmission
interfaces. First reuse the dock electronics and a removable small-servo set;
compare a fixed-actuator base only if a specific mechanism family benefits.

## Price from complete economics

Maintain separate cost records for starter and each attachment: sourced parts,
assembly/test/yield, printing/rework, packaging, inbound freight/duties,
fulfillment, payment/channel fees, returns/warranty and support. Show included
versus extra items at the complete first-use price. Existing tools/printer
ownership and optional cloud inference costs must be explicit.

For a simple direct-sale illustration, let `P` be realized revenue excluding
sales tax, `r` variable fee fraction, `L` landed build cost, and `F` allocated
per-order fulfillment plus warranty/support reserve:

```text
unit contribution = P × (1 - r) - L - F
landed-cost ceiling for contribution fraction g = P × (1 - r - g) - F
N-design customer spend = starter + sum(attachment purchases/build costs)
                         + disclosed printing/tools/shipping/tax/optional services
```

Illustration only: at `P=$99`, `r=4%`, `g=35%` and `F=$12`, the landed starter
build must cost at most **$48.39**. For a `$35` attachment with the same fee and
contribution assumptions and `F=$8`, its ceiling is **$13.35**. These assumed
inputs are not quotes, accounting gross margins or measured support costs;
contribution still must cover engineering, tooling and other fixed costs.
Wholesale/channel economics require a separate realized-revenue calculation.

Evaluate the starter on a **one-kit buyer with no repeat purchase**. Do not
subsidize it using an unmeasured attachment rate or hypothetical cloud/data
revenue. Compare the builder's complete spend and setup time for one, two and
three designs against separately equipped kits. Count connector/ID overhead,
print failures, servo moving time, shared-dock downtime and support costs when
estimating reuse savings. Repeat orders must produce useful added functions,
not be required to unlock the first lesson.

## Differentiation to test

| Dimension | Robosen reference / known limit | SeedCore proposal and evidence needed |
| --- | --- | --- |
| Initial experience | Finished character products and reusable base/content tools | A complete first lesson with understandable assembly/setup; measure success and support burden |
| Expansion | Character interchangeability is publicly described | Original printable functional attachments; measure whether users actually build and use a second design |
| Creation | Studio already supports custom motion/audio and routine generation | Optional natural-language draft plus editable timeline; compare editing effort and rejected/invalid drafts |
| Perception | Retail pages do not establish every sensor/control detail | Cameras/IMUs only for a named accepted task; current draft catalog does not mean live perception or calibrated torque sensing |
| Trust | Reviewed retail material is insufficient for a protocol/security comparison | Scoped authority and evidence are SeedCore's design; physical enforcement/capture still need CW/M/G acceptance |
| Openness/support | Public marketing is not a license or complete API audit | Versioned original CAD/interfaces, explicit licenses, repair and reproducible build records; qualify each supported scope |

LLM output is an untrusted candidate. Offline DRC checks supported assembly,
electrical and supplied mass/cost data; it does not prove arbitrary gesture,
contact or torque safety. CW-S01/S02 simulation and CW-S04 curve checks can
reject specific modeled violations, not certify physical execution. The
implemented host rehearsal polls its watchdog at **5 ms**; no sub-millisecond
physical stopping result is established.

## Product tests before price or tooling commitments

Prepare research materials without starting outreach or taking orders. Compare
a complete standalone kit with a reusable starter plus one attachment at the
**same complete initial scope**, then show the incremental second/third design
cost. Vary price/contents openly; do not compare a bare dock with a complete toy.
Separate existing-printer makers, academic labs and households needing supplied
parts. Test a ready-to-use route as well as self-printing.

Record first successful bounded lesson, first-time/repeat setup and swap time,
failed prints/parts, help requests, willingness to pay at declared contents,
second-design completion/use, returns and actual contribution. Measure second
attachment interest separately from demonstrated purchase/use; freeze study
sample, task, limits and decision thresholds before execution. If most buyers
want one finished product, retain a complete starter/standalone option. A base
plus attachments is valuable only when repeat use outweighs its extra assembly
and interface burden.

## Engineering handoff and review

The [dock/discovery architecture](../integrations/robotics_partner_integration_architecture.md#reusable-desktop-dock-and-attachment-discovery)
owns the proposed module boundary, physical interface and non-authoritative ID
flow. Its first result is a concept/source/BOM review, not a new qualified
catalog part. The [roadmap](../robotics/robotics_ecosystem_integration_roadmap.md)
keeps this within COOP-01/02 capacity. The [26 October active queue](../current_next_steps.md)
selects CW-S04 bounded gesture/replay after local CW-S01 handoff, CW-S02
fixed-preset runtime and CW-S03 preflight. Full policy execution remains gated.
Optional LLM gesture import stays within CW-S04/CW-MOM-01 scope, while physical admission
and firmware/discovery are later CW-G01/CW-F01/F02 work.

Keep original printable attachments, conservative scope labels and independent
cost/authority/evidence review. A convincing product statement to test is:
**one local computer, one reusable dock, a growing set of small desktop projects**.
It is a proposal for one qualified family, not universal compatibility or a
current shipping product.
