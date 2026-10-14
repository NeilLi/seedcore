# SeedCore Inside: OEM Partnership Brief

Date: 2026-10-14
Status: Draft for partner review; no outreach, agreement, kit availability or commercial terms are established

## Partner Proposal

**Make an affordable robot kit easier to use and easier to trust.** SeedCore
proposes open reference firmware and browser lessons so a supported kit can
connect to a laptop/Chromebook, run a bounded supervised experiment and explain
the outcome through action evidence.

The OEM owns the body, electrical design, manufacturing and hardware warranty.
SeedCore provides the reviewed authority/evidence integration, reference
firmware, conformance fixtures and optional supported governance services.

## What Exists And What A Design-In Would Build

| Available foundation | Proposed partner deliverable |
| --- | --- |
| Browser planar lessons and 1/2/3-link orbit studio; 13,242-byte dual-ABI Wasm core | Physical connection and onboarding for one qualified board/body profile |
| Shared PDP, scoped tokens, revocation and Rust verification primitives | Enforced MCU admission/command path, enrolled identity and action-bound hardware evidence |
| Pinned Microduck native model and local team contracts | Separately accepted robot adapter, firmware release and supported deployment |

The browser studio currently simulates local experiments. Pre-flashed Fast
Spine firmware, WebSerial robot control, a one-click flasher and an OEM badge
are planned work. Demonstrate them only after their release gates pass.

## First Design-In Scope

Use one 1–3 DOF tabletop kit with one ESP32-S3 controller and one reviewed
STS3215 TTL bus/power profile. Preserve Microduck's native `robotd` ownership
on that separate integration. Defer BLE, alternate MCUs and additional bodies
until the first kit is independently reproducible.

The first offer includes a device/profile manifest, teacher/operator start and
stop controls, one bounded lesson, negative-case fixtures, update/recovery
instructions and a repair/support ownership matrix. No child-facing camera
cloud service or dataset contribution is needed for the first lesson.

Planning targets are a $12 recurring controller BOM and selected kits below
$300 excluding an existing host. Quote actual volume, power, assembly/test,
yield, packaging, freight/tax and support separately. Ten-second repeat connect
and 30-second flash are benchmark goals on a named supported configuration,
not advertised universal onboarding times.

## Responsibilities

| Partner / role | Required contribution |
| --- | --- |
| OEM / ODM | Schematic and bus/power details, sample/profile access, firmware ingress inventory, traceable parts, factory QA, enclosure/mechanical limits and warranty/repair route |
| SeedCore runtime / firmware | Versioned authority/session binding, device enforcement, failure fixtures, evidence integration, browser release and supported update policy |
| Trust / commercial role | IP/license inventory, issuer/release key governance, contracting and data-processing boundaries |
| Field / support role | Bench qualification, assembly/QA where selected, training, supervised lesson feedback and incident/support measurements |

Agree who provisions each device identity, handles key rotation/revocation,
retains manufacturing records and pays for update/support work before a factory
batch. A pre-flashed binary alone is insufficient for a trusted enrollment.

## Stage Proposal

1. **Technical fit:** review one schematic/runtime, one lesson and candidate
   unit economics; select a named supported profile.
2. **Engineering samples:** qualify up to 10 units, including invalid authority,
   unplug, restart, local stop, capture failure and update/recovery cases.
3. **Supervised delivery:** start at one site and progress toward 3–5 only when
   usefulness, repeat setup and support evidence pass.
4. **Factory pilot:** advance through 25 and up to 100 cumulative kits after
   demand, cash, yield and support reviews. The count is a planning ceiling.
5. **Design-in / distribution:** qualify one shipping profile before targeting
   2–3 OEM relationships in Apr–Sep 2027.

The [execution plan](../development/strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
owns the target windows. Required M2/M3/M4-equivalent acceptance for this kit
precedes a physical demo, regardless of the marketing calendar.

## Commercial Architecture

Keep the basic runtime/firmware open under the intended Apache-2.0 model,
subject to dependency/license review. Open hardware files need an explicitly
chosen license. No mandatory royalty is required to use Apache-licensed code.

Validate separate paid agreements for co-branding, conformance maintenance,
factory provisioning, identity components and contracted engineering/support.
Governance / Cloud Workbench subscriptions cover hosted policy administration,
roles, fleet records and verified replay. Local deadline/watchdog enforcement
must continue during a cloud outage. Price and revenue shares remain to be
negotiated; no partner margin or volume is assumed.

“SeedCore Inside” identifies the reviewed integration. “SeedCore Verified”
identifies a particular conformance profile, firmware/body revision and test
record. It does not certify all variants, guarantee physical safety or replace
product/regulatory obligations. Define badge use, withdrawal, version changes
and support terms before granting it.

## Target Ecosystems And Evidence Packet

Seeed Studio and M5Stack are initial ecosystem candidates. Waveshare, Hiwonder, Yahboom and other kit vendors are additional
unqualified candidates. No endorsement, compatible current SKU or agreement
is claimed. Rank actual candidates by accessible engineering contact, board
and servo fit, manufacturing/update ownership and demonstrated institutional
distribution before making an offer.

Prepare a one-page profile/BOM, split-screen allow/deny/revoke trace, signed
evidence and verifier result where accepted, conformance checklist, flashing
recovery guide, one lesson and a support/economics estimate. Contact and
publication require separate authorization.

Evaluate relevant innovation challenges against current eligibility and customer
needs. Programme participation and funding are not established by this brief.

## Draft Opening

> We are building SeedCore, an open trust runtime for affordable robot kits.
> Our browser simulation and authority/evidence foundations are available; we
> are qualifying one physical reference profile. We propose a small design-in
> that keeps your hardware and warranty ownership clear while giving users
> browser lessons, bounded AI execution and explainable action records. The
> first discussion would review one kit, one lesson and the joint qualification
> and support plan.

This text is a draft and has not been sent.
