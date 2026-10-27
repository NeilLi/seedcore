# Mini-robotics ecosystem integration roadmap

Date: 2026-10-20
Status: Revised supporting backlog; research only until separately selected for implementation

The [strategy](../strategy/robotics_component_cooperation_strategy_2026.md)
now prioritizes the existing small TTL fixture, ODRI open-design study and exact
CubeMars compact-joint feasibility. The [architecture](../integrations/robotics_partner_integration_architecture.md)
and [pilot briefs](../../application/robotics_component_partner_pilot_briefs.md)
define boundaries and experiment scope. This replaces the prior compute,
capture and middleware-first cooperation sequence.

The [base/attachment product analysis](../strategy/mini_robotics_base_attachment_product_analysis.md)
adds two-tier starter/attachment pricing, a Robosen reference review and a
shared-dock hypothesis. It changes packaging/validation questions, not the
implementation order or the existing research caps.

## Preserve the delivery order

The `ba0d132` research baseline had local CW-A01 v2 through CW-A04 offline
evidence. The [26 October active queue](../current_next_steps.md) now records
[CW-S01 compiler/handoff](central_world_cw_s01_mjcf.md),
[CW-S02 fixed-preset runtime](central_world_cw_s02_mujoco.md) and
[CW-S03 offline preflight](central_world_cw_s03_preflight.md) as delivered locally;
CW-S04 bounded gesture/replay is next. Full policy execution and broader
runtime/device/deployment qualification remain open. The catalog contains twelve
draft/proxy parts; Fast Spine is simulation-only and exact fixture qualification
is open. Microduck retains its separately pinned native M0–M4 lane.

The [active queue](../current_next_steps.md), [remaining CW schedule](central_world_remaining_delivery_schedule.md)
and [18-month plan](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
continue to own implementation order, dates and staffing. No new joint, camera,
compute board or middleware is a prerequisite for the January authoring/simulation
alpha. Keep one active implementation package per implementer and one supported
physical profile/live pilot initially.

## Revised work packages

The COOP IDs are retained for continuity, but their scopes below supersede the
previous versions. In particular, COOP-03/04 no longer mean a D-Robotics,
Orbbec or Viam adapter. Proposed review windows are not delivery promises.

| ID / review window | Scope and owner role | Entry / dependencies | Reviewable exit | State |
| --- | --- | --- | --- | --- |
| **COOP-00 / 20 Oct 2026** | Mini-category and base/attachment product analysis; integration lead | Current repo and primary-source review | Revised cooperation packet, Robosen evidence/limits and two-tier pricing hypotheses; seven supplied initiatives assessed, earlier ten reclassified | Documentation prepared; product demand and hardware/vendor qualification open |
| **COOP-01 / 21 Oct–12 Nov** | Existing TTL fixture/shared-dock gap and cost record; ODRI and exact CubeMars source/fit records; integration lead + reviewer | Capacity after active CW-S04/native commitments | Dock concept/source gaps, complete starter versus incremental attachment costs, two concise candidate records and go/defer decision | Proposed supporting diligence; no parts/SDK imports, orders or customer outreach |
| **COOP-02 / by 10 Jan 2027 alpha review** | Mini-joint/dock interface and fabrication-gap review; runtime/mechanical reviewers | CW-A04 findings; source records and available capacity | One offline fixture design, mount/rail/connector unknowns, non-authoritative discovery flow, supported-schema/CAN gaps and reproduction dependencies | Conditional design review; no new live body or automatic motor enable |
| **COOP-03 / Apr–Sep 2027 ecosystem review** | One compact commercial-joint feasibility study, initially CubeMars; integration owner | Named gap in small-servo baseline; exact revision/docs/access and effort cap | Pinned model/protocol/source packet, complete system BOM, load/thermal/stop requirements and offline/read-only comparison | Candidate; a physical bench phase needs a separate accepted profile |
| **COOP-04 / same ecosystem window, alternative to COOP-03** | One ODRI actuator reproduction/model study; research + mechanical owner | Pinned upstream version, rights, electronics/calibration plan and fabrication access | Reproduction plan or unit build record, modeled/measured distinction, actual fabrication effort/cost and single-joint comparison | Candidate alternative; not a full Solo build or OpenQDD replacement commitment |
| **COOP-05 / after repeat accepted delivery** | External starter/attachment reproduction; delivery + verification roles | Applicable CW/M/G gates, support/repair/update owner and useful lesson | Independent first lesson and second-attachment use, changed-build admission tests, real setup/support hours and unit contribution | Conditional; no OEM/badge granted or assumed repeat-purchase rate |
| **COOP-06 / later named mini-task review** | WHJ03, BCSA Micro or exact igus module feasibility; portfolio owner | Current offer supportable; explicit miniature task, mass/cost/supply constraints and capacity | One source/interface/task comparison and go/rescope/defer decision | Conditional; OpenQDD/ROMOMO retained as background references, industrial cells excluded |

Select **COOP-03 or COOP-04**, not both as an automatic sequence. A later
experiment competes for the existing ecosystem/adapter budget. Replacing the
planned LeRobot/model-provider package requires a recorded queue/capacity
decision; a second experiment needs its own review after the first result.
Bringing an experiment forward requires a measured blocker and explicit queue
allocation, not vendor novelty.

Keep the proposed COOP-01 cap at **two person-days total**, shared across the
fixture gap update and both candidate records, only after committed work.
COOP-02 has a proposed **one-person-day** review cap. At the cap, leave facts
unknown and defer; do not assume free access, printing, samples or engineering.
These are effort limits, not procurement authorization.

Dock review and pricing-study design share those caps; reduce or defer other
supporting research when they consume the available time. A customer study,
new catalog part, hardware prototype or additional attachment requires an
explicit selected work package and the applicable access/capacity decision.

## First source/fit record

```text
User / lesson and why the current small-servo baseline is insufficient:
Exact module/SKU/revision or upstream commit and source hashes:
Required reach, payload, total mass, motion mode and duty cycle:
Claimed vs measured mass, torque (rated vs peak), speed and backlash:
Voltage range, supply vs phase current, thermal and regeneration requirements:
Bus/driver/firmware, command units/sign, feedback and local stop ownership:
CAD/mount/axis mapping, printed/machined parts and inspection dependencies:
Licenses, redistribution, supported versions and repair/update route:
Complete BOM and setup/fabrication/support effort: known / unknown
Shared dock/starter costs vs incremental passive or active attachment costs:
First-use contents, proposed price test and complete customer cost boundary:
Documentation/test access and exact-unit availability: known / unknown
Current schema/DRC/model gaps; unavailable checks:
Owner role, effort cap, next review and prepare / offline feasibility / defer:
```

The existing fixture uses its [CW-D01 source register](m0_cw_d01_register_2026_10_19.md).
For ODRI, select one actuator version and enumerate tooling/electronics rather
than assuming generic FDM reproduction. For CubeMars, disambiguate AK40-10
revisions and driver inclusion before comparing mass/cost or a supply. The
strategy contains the source evidence and corrections for every other candidate.

## Acceptance mapping

| Requirement | Existing owner / acceptance | Mini-joint evidence |
| --- | --- | --- |
| Exact part, source, drawing, electrical and rights | CW-D01 / CW-CAT-01 | Dated manual/unit revision, pin/rail review, artifact permissions and real price basis |
| Build/configuration identity | CW-A01–A03 / CW-ASM-01/02; live CW-G01/F01/F02 separately | Exact mount/axis/gearing and combined dock/attachment context; cloned/stale ID, changed-build and stale-admission cases; chip digest is a candidate, fabricated unit distinct from CAD |
| Unknown-aware power, cost and compatibility | CW-A04 / CW-DRC-01–03 | Known vs unknown complete BOM and supply loads; unsupported CAN/CAN FD remains a design gap |
| Assembly model and numeric comparison | CW-S01–S03 / CW-SIM-01, CW-POL-01 | Joint map/units, mass/inertia assumptions and independent reference; native Microduck M1 remains separate |
| Execution ingress and local fencing | CW-G01 / CW-AUTH-01/02; G0/G1 | Vendor tools, raw bus, calibration, second client, deadline/reconnect and all real mutation paths |
| Capture and outcome coverage | CW-G02 / CW-EVID-01; M3/G2 as applicable | Command/feedback clock, calibration/gaps and honest signer/capture class |
| Physical stop/fault qualification | CW-F01/F02 / CW-HW-01; M4/G2 as applicable | Exact fixture load/mount, observed stop/hold, power faults and returned braking energy where relevant |
| Reproduction and sustainable support | G3/G4 | Independent setup/repair, process substitutions, actual costs and repeat lesson demand |

An offline model, source review or read-only bus experiment can pass its own
scope while physical gates remain open. Preserve failed/uncertain attempts and
unavailable measurements in the report. No supplier score or small-robot label
substitutes for existing acceptance.

## Experiment measures and handoff

Compare against the simplest accepted small-servo implementation of the same
task. Freeze required ranges/tolerances, numeric limits, sample plan and cost
boundary before evaluating. Measure useful task outcomes, complete robot mass,
setup/repair time, actual BOM, controller/thermal load, observed stopping and
capture completeness when the experiment reaches the relevant physical scope.
Rated torque, peak holding torque and continuous duty are separate quantities;
current-derived torque estimates are not calibrated load measurements.

For open designs, also retain printing/machining failures, inspection/rework,
encoder/gearing calibration and substitution history. For integrated joints,
retain exact firmware/control mode and vendor-tool/bridge dependencies. Defer
when the mass, budget, fabrication access or interface burden defeats the
mini-robot lesson, even if a vendor benchmark is impressive.

Each handoff records scope, source/artifact pins, positive/negative evidence,
open gates, actual hours/cost, support owner and go/rescope/defer decision. A
selected implementation becomes one explicit active-queue item. Industrial
cells, humanoid expansion, dedicated AI boards, wearable datasets and fleet
middleware receive no new work allocation through this revision.
