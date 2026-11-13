# 12 November: route/status review and next priority

Date: 2026-11-12
Timezone: Asia/Bangkok (UTC+07:00)
Status: Engineering assessment and active work plan; human release decisions remain open
Inspected source: `b86fd3bb4c2a7599ae496c74de79dd71848ff663` on `main`; clean before this documentation review

**Later 12 November trial update:** the participant reported that the practice
workspace did not present a recognizable robot or explain why to use Movement.
The [robot/task-flow repair](cw_l02_task_flow_2026_11_12.md) records the blocker,
local implementation and revised trial handoff. The original engineering
assessment and packet references below retain their earlier scope. Independent
retry is now the next trial task; the human finding is still open.

## Assessment

**Continue the direction, rescope dependent physical dates, and prioritize
independent validation over another Studio feature.** The implemented local
authoring, bounded simulation, PDP admission and evidence components support
the README's trust-runtime goal. They do not yet establish a repeatable physical
product or the complete native Microduck integration.

This review read all 379 lines of the root README at the inspected revision,
the development map and guardrails, active queue, 18-month strategy, day-30
sheet, native integration plan, source register and CW acceptance records.
It inspected route registration, the local Studio/admission services, trial
tooling, retained evidence and fresh checks. Remote CI and a deployed stack
were not assessed. No physical operation was performed.

The original 11–12 November checkpoint should record a scoped engineering
rescope, rather than imply that its planned native/firmware/bench outputs
have arrived. Physical milestone dates require a new estimate after source,
reference, firmware, fixture and ownership availability are known. The January
authoring/simulation alpha remains a target subject to CW-L03 review.

## Current routes and delivered scope

| Surface | Inspected state | Consequence for the goal |
| --- | --- | --- |
| Main API | `src/seedcore/api/routers/__init__.py` registers 14 supported router specs; `src/seedcore/main.py` mounts them under `/api/v1`, with the Agent Action Gateway conditional on its mount flag | Intent/identity/policy/evidence routes exist; a registry test does not establish deployed integration. Legacy routers are excluded from the active registry. |
| Default Studio, `127.0.0.1:8767` | Read-only requests to starter, simulation reference, placement catalog and app bundle returned 200; served `app.js` matched the current build | Offline authoring and the synthetic lesson are available. The full Microduck explorer is display-only. |
| `/api/cw-g01/profile` | Running Studio returned `configured: false`, `physicalAcceptance: false` | Its ordinary lesson is not a configured governed attempt. Do not infer PDP admission or signed evidence from that lesson's unsigned capture. |
| Opt-in `/api/cw-g01/*` | Separate configured service supplies admit/start/cancel/status/capture; unconfigured operations fail closed. State-changing routes require same-origin JSON | Real PDP, scoped token, durable claim and native execution are exercised locally; production authenticated intake/context refresh remains separate. |
| `/api/cw-g02/{request_id}/evidence` and `/verify` | Known-attempt original exports and verification use configured signing and separately retained context/trust | Local signed simulation proof exists. General historical recovery and production/hardware evidence are still separate acceptance work. |
| Native Microduck | Pinned model/read-only adapter and artifact goldens; independent checkpoint evidence and runtime integration remain open | Neither the visual explorer nor the synthetic tabletop qualifies trained walking or M2–M4. |
| Physical fixture / firmware | CW-D01 inventory remains unqualified; no connected fixture recorded | Exact unit, connector/power, firmware, signer enrollment and measured stop/fault evidence precede physical acceptance. |

The runtime implementation preserves the intended separation between proposal,
accountability, policy, execution and evidence within its named local scope.
That is a sound foundation. The remaining work is connecting and qualifying
these boundaries for a selected real profile, then demonstrating repeat use.

## Gaps in priority order

| Priority | Gap | Concrete next output and acceptance |
| --- | --- | --- |
| P0 | CW-L02 has repeated automated preparation but no independent observation | One adult maker follows the existing lesson; record actual timing, assistance, task failures, keyboard/readability, privacy, downloads and resume/recovery in the bound observation. Fix observed blockers before CW-L03 review. |
| P0 before release | Supported environment and named support/rollback ownership are absent | Record tested browser/device and named accountable owners, review the exact candidate and rollback procedure, then obtain a separate scoped human release decision. |
| P1 | First-use rehearsal does not demonstrate the governed trust loop | After the first observation, prepare a separately scoped operator walkthrough of existing configured G01/G02 allow/deny/interruption and signed verification. Use reviewed local simulation configuration; never auto-create production approvals or turn the default offline lesson into authority. |
| P1 native | M1 lacks independent training/export reference, recorded policy rights and exact runtime/body/actuator compatibility | Produce an evidence-intake checklist and acceptance cases from existing profile/preflight contracts; ingest independent references when available, preserve frozen tolerances and explicit missing/blocked outcomes. Replayed ONNX output cannot substitute for training-reference output. Native policy execution follows qualification. |
| P1 physical | CW-D01 source facts, firmware/enrollment and physical stop/capture evidence are open | Reconcile exact applicable drawings/unit revision, connector convention, regulated/derated rails and controller ownership. Review firmware source/build/recovery and profile G0/G1 before a one-servo bench; G2 precedes a physical demo. |
| P2 deployment | Full live shared authz and optional Postgres acceptance are unavailable | Reproduce them against an explicitly configured local/staging stack when that surface is selected. Current unit/fixture passes do not close these lanes. |
| P2 commercial | No measured setup/support economics or repeat delivery | Use trial results to populate effort assumptions; obtain real quotations and repeat-use evidence before kit/site expansion. Existing price targets are not validated costs. |

The 240 ms / at most 0.001 rad practice movement is an explicit usability
question for the observation. A participant may not perceive movement or reach
Stop during the run. Record the result; do not extend the envelope or count an
unexercised stop as a pass to improve the demonstration.

## Selected schedule: 13–16 November

Times below are effort budgets and dependency order. A participant is available
in principle; the user will provide the session time and owner names. No session
time, named owner or release approval is inferred from that availability.

| Target | Owner role | Task and finish condition |
| --- | --- | --- |
| 13 Nov, 09:00 | Project lead | Review the next-task handoff and confirm trial logistics; a scheduled chat follow-up does not book the participant. |
| 13 Nov, agreed session, 45–60 min | Independent adult maker + observer | Verify the prepared packet, run the existing lesson without advance coaching, retain actual observation and downloaded artifacts. Keep setup time distinct from lesson time. |
| After observation, up to half a day | Studio implementer + reviewer | Triage findings by completion, comprehension and recovery impact; fix blocking issues, rerun affected checks and prepare a new bound candidate if inputs changed. Preserve earlier observation against its original candidate. |
| 13 Nov if the session is unavailable; otherwise 16 Nov, 3–4 hours | Native integration lead | Prepare the M1 reference-intake/acceptance contract using existing deployment/preflight structures. Inventory missing checkpoint/export bytes, policy rights and actuator/runtime mapping; assign required artifact owners. Implement bounded offline intake/parity handling only where independent evidence is available. |
| 16 Nov, 1–2 hours | Hardware/integration reviewer | Refresh CW-D01 blocker ownership and evidence availability. No connector, power, firmware or physical pass without applicable reviewed evidence. Re-estimate dependent physical dates. |
| After observation, issue disposition and owners | Human release reviewer | Decide CW-L03's named local authoring/simulation scope. Until then retain DEFER. Physical and production release require their own evidence and decision. |

If independent references or hardware facts are unavailable, record the exact
missing artifacts and ownership. Do not spend the allocation on another visual
feature or widen the supported robot/profile set. A missing deterministic gate
is surfaced with verifier/runbook evidence, not repeatedly retried or waived.

## Fresh verification on 12 November

Logs are under `artifacts/robotics/strategy-review-2026-11-12/`.

| Check | Fresh result | Limit |
| --- | --- | --- |
| `node tools/robotics/verify-cw-l01.cjs --browser` | Source builds/typecheck; 309 TS tests; 57 focused Python checks; beginner and full-model browser exercises; seven gallery Chrome groups passed | Local prepared software, not a human trial or release. |
| `.venv/bin/python tools/robotics/verify-cw-l02-trial.py` | 33 focused packet/preflight tests and five actual startup/packet groups passed; owned startup probes 0.757 s / 0.951 s | Machine startup measurements, not maker setup times; human observation remains pending. |
| API registry + CW-G01/G02 + Fast Spine focused Python suites | 275 passed, two skipped, with strict native/Rust requirements enabled | Existing Rust executable used, not a fresh Rust source build. Two optional actual-browser candidate/capture lanes were not requested in this combined run; the fresh L01 browser run does not replace those governed lanes. |
| `bash scripts/host/verify_q2_verification_contracts.sh` in project venv | Enabled lanes passed | Optional RESULT_VERIFIER Postgres integration explicitly skipped. |
| `bash scripts/host/verify_authz_graph_rfc_phases.sh` | 79 focused tests passed; overall command exited 1 at live HTTP stage | Connection refused to `127.0.0.1:8002/api/v1/pkg/status`; full live qualification unavailable. No retry loop or bypass. |
| `review_m0_pins.py` and `freeze_fast_spine_protocol.py` | Nine candidate pins matched; frozen schemas/framing/simulation limits matched | Source/protocol inventory, not independent checkpoint parity or hardware qualification. |

The retained CW-S03 reports still describe both real policy-runtime candidates
as blocked. That runner was not rerun in this review; the fresh M0 pin check is
not a replacement for artifact replay or missing training evidence.

Fresh trial handoff:
`artifacts/robotics/cw-l02-trials/2026-11-12-review-ready-01/`, on separate port
8784, prepared after the review documentation. Run its README commands and
verify before and after recording the observation. Source/build/preparation
changes require a fresh packet; pending fields never count as a pass.

The existing Studio on 8767 and browser drafts remain intact. Documentation
changes are local for review; no commit, push, deployment, outreach, procurement
or physical acceptance follows from this assessment.
