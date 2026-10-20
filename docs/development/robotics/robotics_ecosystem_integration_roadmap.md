# Robotics ecosystem integration roadmap

Date: 2026-10-20
Status: Proposed cooperation backlog integrated with existing CW/M/G gates; no vendor implementation scheduled as an immediate prerequisite

Use with the [cooperation strategy](../strategy/robotics_component_cooperation_strategy_2026.md),
[integration architecture](../integrations/robotics_partner_integration_architecture.md)
and [pilot briefs](../../application/robotics_component_partner_pilot_briefs.md).
The [active queue](../current_next_steps.md) owns immediate execution;
the [18-month plan](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
owns dates and G0–G5; the [CW schedule](central_world_remaining_delivery_schedule.md)
and [acceptance matrix](central_world_acceptance_matrix.md) own authoring gates.
COOP identifiers below are planning references, not new runtime reason codes,
acceptance gates or permission grants.

## Preserve the current delivery order

As refreshed on 20 October against `01c9af0`, CW-A01 v2 through CW-A04 have local
offline software evidence, including worker DRC and unknown-aware BOM. CW-S01
restricted assembly-to-MJCF compilation is the next package.
The component catalog has twelve draft/proxy records, with exact first-fixture
qualification open. Microduck remains the native reference; the Fast Spine
one-to-three-servo fixture remains a bounded bench package. No hardware is
connected or qualified in the current source-register baseline.

Cooperation work should first improve the next package's evidence requirements
and future adapter decisions. None of the ten candidates is a prerequisite for
CW-S01, the January authoring/simulation alpha or Microduck training parity.
Keep one active implementation package per implementer and one supported
physical profile/one live pilot initially. A Linux inference-host evaluation
does not qualify a second robot or replace the chosen MCU.

## Work packages and review artifacts

Owner roles are proposed responsibilities, not staffing assignments. Confirm an
actual owner and effort budget before implementation. Windows are review
targets; conditional work moves with its dependencies.

| ID / target review | Scope and owner role | Entry conditions | Reviewable exit artifact | Current state |
| --- | --- | --- | --- | --- |
| **COOP-00 / 20 Oct 2026** | Source assessment, architecture and pilot drafts; integration lead | Current repo/plan inspection and official-source review | This four-document packet, all-ten candidate assessment, corrections and unresolved facts | Documentation prepared; vendor qualification open |
| **COOP-01 / 21 Oct–12 Nov** | Fit/source record for D-Robotics, Orbbec and Viam; integration lead + reviewer | Existing CW-S01/M0 work retains priority | Three short records with exact product/interface references, known/unknown fields, access/dependency/license gaps and a go/defer decision | Proposed supporting research; no SDK import or new catalog parts |
| **COOP-02 / by 10 Jan 2027 alpha review** | Review reusable observation/proposal/ingress requirements against accepted CW and session contracts; runtime reviewer | CW-A04 findings available; owner/capacity confirmed | Contract-gap matrix and one offline fixture design for the highest-value gap; extend existing contracts only if required | Conditional design work; January alpha does not depend on it |
| **COOP-03 / Apr–Sep 2027 ecosystem review** | At most one D-Robotics compute experiment; inference/integration owner | Measured existing-host gap; exact board/toolchain access, permitted sample data and capped effort; capacity decision | CPU baseline vs selected runtime parity/performance report, version pins, late-output handling and cost/support estimate | Candidate; board access, budget and need unknown |
| **COOP-04 / Apr–Sep 2027 ecosystem review** | Choose one Orbbec capture experiment **or** one Viam connectivity experiment; observation/runtime owner | COOP-01 fit review, a named user need and capacity after the current integration | Licensed recording with calibration/coverage/replay report, or simulated/read-only machine mapping with complete mutation-ingress assessment | Candidate alternative to COOP-03; a second experiment needs a new queue/capacity decision |
| **COOP-05 / after repeat delivery, review at phase 3** | One external integrator reproduces an accepted adapter; delivery + verification roles | Applicable M/G and CW gates pass; maintainer, support/update route and commercial scope assigned | Independent setup, negative authority/closure cases, release pins, recovery and setup/support hours | Conditional; no OEM agreement or badge granted |
| **COOP-06 / phase 4 or separately funded feasibility** | Force/tactile, industrial arm, hand or general-brain expansion; portfolio owner | Repeated customer need, existing offer supportable, separate profile/budget and accessible interfaces | One bounded task comparison and go/rescope/defer decision under unchanged authority/evidence gates | Deferred; Bota, Contactile, RobCo, Inovo, Mimic, Skild and Field AI remain research candidates |

COOP-03/04 are alternatives for the first experiment: select compute, capture
or connectivity. They do not commit the team to a sequence of vendor adapters.
Choosing an alternative to the 18-month plan's LeRobot/model-provider work
requires an explicit queue/capacity decision. A second experiment needs its own
review after the first result.

COOP-03/04 can be brought forward only by a recorded active-queue and capacity
decision tied to a measured blocker or accepted customer need. This is not an
automatic early-start option. If the host baseline works, defer compute. If
perception is unnecessary for the first lesson, defer capture. If Viam adds no
measured value beyond the existing adapter, defer that dependency.

## First review: evidence to collect

Use one fit record per prepare candidate:

```text
Candidate and intended user outcome:
Exact product/SKU and public documentation revision:
SDK/runtime/firmware/toolchain versions and licenses: known / unknown
Observation/command APIs, units and frames:
Timestamp, calibration, loss/validity and evidence export support:
All mutating ingress and local interruption ownership:
Offline operation, update/rollback and support route:
Available test access and permitted recordings: known / unknown
Baseline comparison and measurable gap:
Expected engineering/support effort and actual cost evidence:
Unresolved questions, owner role, next review:
Decision: prepare / offline feasibility / defer
```

For D-Robotics, record the exact host workload and why the existing computer
cannot meet it. For Orbbec, select between ordinary perception and wearable
demonstrations; do not treat them as one interchangeable camera product. For
Viam, identify the precise distribution/connectivity benefit and control-plane
overlap before writing an SDK wrapper. The pilot briefs specify the questions.

Proposed capacity caps for the next review are **two person-days total** for
COOP-01 and **one person-day** for the COOP-02 design review, only if available
after committed work. These are planning caps, not assumed capacity or spending
approval. Reduce or defer them when CW/native delivery needs that time.
At the cap, unresolved supplier facts stay unknown; record a defer decision.

## Map cooperation work to existing acceptance

| Integration requirement | Existing owner / acceptance | Additional experiment evidence |
| --- | --- | --- |
| Exact supplier part, drawing, electrical and source rights | CW-D01 / CW-CAT-01 | New reviewed part revision, actual source/quote where relevant; no qualification by marketing claim |
| Canonical configuration and reconfiguration invalidation | CW-A01–CW-A03 / CW-ASM-01/02 | Vendor-config-to-build mapping, changed-input and stale-admission cases |
| Unknown-aware cost, power and compatibility | CW-A04 / CW-DRC-01–03 | Preserve unknown load/rail/price; never report an unpriced sensor/board as free |
| Model import and numeric parity | CW-S01–CW-S03 / CW-SIM-01, CW-POL-01; Microduck M1 separately | New-body/model mapping and independent reference; compute conversion cannot close training parity |
| Admission, execution ingress and local fencing | CW-G01 / CW-AUTH-01/02; G0/G1; native M2 or fixture equivalent | Alternate RPC/UI/config paths, SDK sessions, second-client handoff and reconnection |
| Capture, signer and outcome coverage | CW-G02 / CW-EVID-01; M3 and G2 as applicable | Sensor clock/calibration/loss and capture-assurance record; original vendor/host artifacts preserved |
| Physical stop/fault qualification | CW-F01/F02 / CW-HW-01; native M4 and G2 | Measured behavior on the exact controller/body; a sensor or SDK check gives no hardware credit |
| External adoption and maintenance | G3/G4; service operating plan | Independent setup, recovery/update, repair and support-cost evidence |
| Paid fleet use | G5 | Actual multi-device fault isolation, retained evidence, recurring cost and repeat-use demand |

An offline recording or simulated machine can complete its own experiment
without satisfying physical gates. Report skipped/unavailable checks as gaps.
No new cooperation score or partner logo overrides an existing gate.

## Experiment selection and success measures

Select one experiment with the largest **demonstrated** gap it can resolve per
unit of available effort. Set thresholds and a sample plan before evaluation;
do not invent acceptance numbers from vendor TOPS, frame rates or videos.

| Experiment | Baseline and primary measure | Other required observations | Stop/defer condition |
| --- | --- | --- | --- |
| Edge compute | Same pinned inputs/model semantics on current host vs candidate; output error and input-to-proposal p50/p95/p99 | Late-output rejection, load/thermal duration, peak memory, measured power, exact hardware and price/support basis | Incompatible model/operators, unmet frozen tolerance/deadline or no useful improvement |
| RGB-D capture | Existing recording path vs one permitted sensor recording; valid calibrated samples and gap accounting | Clock error, calibration reproducibility, raw/derived lineage, loss/storage burden and replay determinism under declared tolerance | Required metadata/rights absent, unreliable coverage or no task need |
| Viam connectivity | Existing SeedCore adapter vs simulated/read-only Viam path; independent setup effort and mapping completeness | Revision changes, resource naming, sessions, every mutation route, offline/export and ongoing dependency/support cost | Unfenceable motor ingress or no incremental user/integrator value |
| Later tactile/industrial work | Same accepted task without added capability vs candidate; eligible-task outcomes and damage/drop/error observations | Calibration/uncertainty, intervention, stop and closure results, actual support/fixture cost | New embodiment exceeds approved scope or cannot enforce/observe required limits |

Retain failed attempts and uncertain closure in reported denominators. Separate
expected policy denials from valid-task failures. Evidence verification and
customer usefulness each need to pass; neither compensates for the other.

## Decision and handoff

Every review records source/artifact pins, scope, positive/negative evidence,
unavailable checks, measurements versus frozen limits, actual hours/cost,
support owner and go/rescope/defer decision. A selected implementation becomes
one explicit item in the active queue. Repeated deterministic failures invoke
the existing verifier/runbook review process.

Successful offline work may lead to an adapter proposal. Physical admission,
device enrollment, procurement, outreach, releases and public claims retain
their existing authorization and acceptance processes. Drafting this roadmap
establishes none of those activities. No additional bodies, SoM or telemetry
marketplace is added to the current offer.
