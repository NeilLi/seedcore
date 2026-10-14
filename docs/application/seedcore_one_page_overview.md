# SeedCore One-Page Overview

Date: 2026-10-14
Status: Current positioning; physical firmware, pilots and commercial adoption are planned

**SeedCore is the open trust runtime for affordable physical AI.** It connects
AI proposals to bounded robot execution and verifiable action evidence.
Browser-first maker and supervised STEM kits are the first adoption focus.

## The Problem And Product

An accessible robot kit still needs usable software, clear operator permissions,
predictable interruption and understandable records of what happened. A model
proposal or browser connection alone should not authorize motor access.

SeedCore's intended flow is:

```text
AI proposal -> accountable Agent -> PDP -> scoped ExecutionToken
  -> enrolled boundary / local controller -> observed attempt
  -> signed evidence from a configured signer -> verification / replay
```

The native robot controller keeps control-loop and local-stop responsibility.
Admission, continuous local enforcement and evidence closure have separate
deadlines. Camera capture/egress and research sharing need their own permissions.

## Three Pillars

| Pillar | Offer |
| --- | --- |
| SeedCore Inside | Open reference firmware and browser lessons for supported OEM robot kits |
| Auditable classroom governance | Teacher/operator roles, bounded sessions, capture/egress controls and verifiable replay |
| Opt-in sim-to-real telemetry | Versioned adult/research trajectories for calibration and evaluation, with separate rights and retention |

## Product Differentiation

SeedCore combines browser-first tools, bounded execution authority and
verifiable evidence with qualified hardware profiles. Differentiation must be
shown through independent integration, trusted releases and repeatable support.
Partner agreements and regulatory outcomes are not established by the plan.

## Evidence And Next Milestone

Available foundations include browser planar lessons and a 1/2/3-link orbit
studio, a 13,242-byte dual-ABI Wasm core, pinned Microduck native MJCF data,
shared PDP/token/revocation/evidence paths and Rust token/signature/replay
verification. On 2026-10-14, local checks passed 78 simulator tests and 88
model/workbench tests.

Microduck HAL integration, MCU Fast Spine firmware, physical WebSerial control,
enrolled robot signing and hardware acceptance remain planned. SIM-3's planar
slice is delivered; broader dynamics/encoder/worker/oracle gates remain open.
The Microduck 61/14 policy mapping is not a universal robotics data schema.

The next target is a split-screen bounded-motion demonstration with denial,
revocation/interruption and sufficient evidence for the profile actually shown.
A physical demo requires authority, evidence and hardware gates; fixtures stay
labeled.

## Schedule And Business Model

Q4 2026 targets M1/M2 and the golden reference; Q1 2027 targets M3/M4, one
supervised pilot and staged developer kits. Q2–Q3 2027 targets a first OEM
design-in and LeRobot-family adapter. Q4 2027–Q1 2028 targets qualified fleets
and paid Governance / Cloud Workbench. Dates and adoption counts depend on
technical, demand and support evidence.

Keep local tools and proposed basic firmware open. Validate paid OEM
provisioning/conformance/support and institutional hosted governance, roles,
fleet records and replay. Selected kits below $300 and a $12 controller BOM
are design targets with explicit exclusions, not current prices. Data
contribution is optional; badge conformance is not safety certification.

See the [execution plan](../development/strategy/seedcore_physical_ai_execution_plan_2026_2028.md),
[OEM brief](oem_partnership_brief.md) and
[current next steps](../development/current_next_steps.md).
