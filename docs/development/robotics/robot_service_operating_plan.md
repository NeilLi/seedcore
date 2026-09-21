# Robot Service Operating Plan

Date: 2026-09-21
Status: Proposed operating plan for a founder-led team; budget, demand and hardware readiness unconfirmed

## Operating Decision

Build the service through **one repeatable customer outcome on one supported
hardware profile**, then expand when delivery and support evidence justify it.
The long-term mission remains broad. The initial offer must be narrow enough
that a small team can reproduce it and own its failures.

This plan operationalizes the [customer delivery model](robot_solution_delivery.md).
Use a founder-led team of one or two core people, with specialist help as
needed. Available hours and specialist access still need to be established.
Maintain one active engineering integration and at most one live customer pilot initially.
An additional prospect may participate in discovery without creating another
delivery commitment.

The main scaling risk is the multiplication of robot models, firmware versions,
behaviors, environments and support arrangements. Limit the tested combinations
explicitly. A supported robot means a tested body/runtime/skill/environment
profile, not every device carrying the same product name.

## 1. Choose A Small First Offer

A candidate is an **operator-triggered robot presentation for a staffed studio
or exhibit**: one short routine, reviewed content, a defined operating area,
visible start/stop controls and a fallback explanation. It is a hypothesis to
test with potential users, not a hardware recommendation or validated market.

It offers a concrete way to observe usefulness, interruptions, setup effort
and repeat use. Compare it with an ordinary presentation or screen. If the
robot contributes only first-day novelty, reduce or stop the offer rather than
adding capabilities to make it appear more useful.

Select the first offer using these conditions:

- The problem recurs and an accessible person owns it.
- The user can describe the current workaround and what improvement matters.
- A bounded function can be evaluated with an adult present.
- Existing supported capabilities can plausibly perform it.
- The user can provide a trial setting, feedback and a realistic budget range.
- Another prospective user appears to have substantially the same need.

No weighted score can compensate for a missing essential capability or an
unresolved execution boundary. If the candidate offer does not fit Microduck,
record the mismatch and make an explicit priority decision: keep Microduck as
an engineering experiment and defer the offer, or revise the integration queue.
Do not quietly start a second hardware program alongside the first.

## 2. Move Through Decisions Before Making Larger Commitments

| Stage | Output | Owner | Proceed only when | If the evidence is weak |
| --- | --- | --- | --- | --- |
| Need qualification | One-page need brief and observed/current workflow | Solution lead | A recurring job, user and useful outcome are identifiable | Reframe once or decline the project |
| Feasibility | Hardware capability record and bounded experiment | Robotics lead | Required interfaces and behavior have evidence; unknowns have a test and effort cap | Offer a paid feasibility result, narrower scope or no-go |
| Pilot definition | Function scope, price assumptions, acceptance measures and support terms | Solution lead with engineering review | Customer expectations and technical limits agree | Resolve scope before promising delivery |
| Build and bench test | Versioned skill/profile, failure cases and reproducible evidence | Robotics/runtime leads | Required software and selected hardware gates pass | Diagnose; repeated deterministic failures require review |
| Customer trial | Observation log, outcome measures and operator feedback | Delivery/support owner | Customer value, technical behavior and support burden are acceptable | Correct within budget, reduce scope or end the trial |
| Repeat delivery | Same offer at another installation | Solution lead | Most behavior is reused and support effort is supportable | Keep it bespoke or stop productizing it |

Each stage has a named owner, next decision date, maximum engineering effort
and spending ceiling set before it starts. No amount is assumed or authorized
here. An unresolved fact at the ceiling becomes an explicit defer, rescope or
stop decision; it does not silently become another development sprint.

Discovery and cheap presentation mockups may run while M0–M3 progress. Physical
customer trials depend on M4-equivalent acceptance for the selected profile.
Readiness is determined by evidence, not elapsed weeks.

## 3. Make Discovery Produce A Usable Specification

As an initial learning batch, propose roughly 6–10 conversations within one
candidate segment and 2–3 observations of the current workflow. These are
planning quantities, not statistical validation or permission to contact people.
Favor concrete recent examples over “Would you like an AI robot?” reactions.
Separate the buyer, daily operator and people who encounter the robot.

Use a single solution record throughout delivery:

| Record section | Required information |
| --- | --- |
| Job | User, trigger, task frequency, current workaround and unmet need |
| Outcome | Observable result, comparison baseline and intended benefit |
| Setting | Location, surfaces, people, connectivity and supervision |
| Scope | Included behavior, excluded behavior and allowed customization |
| Hardware | Candidate profile, vendor claims, tested capabilities and unknowns |
| Permissions | Motion/data limits, accountable operator and required approvals |
| Acceptance | Metrics, test conditions, denominators, sample plan and thresholds |
| Commercial | One-time work, recurring costs, support allowance and change policy |
| Recovery | User stop/fallback instructions, escalation and rollback owner |
| Decision | Open questions, effort cap, next review and go/rescope/stop result |

This record prevents sales promises, implementation details and support
expectations from diverging. Customer agreement to the record is not an
ExecutionToken or blanket permission to change robot behavior.

## 4. Select Hardware Through A Small Capability Register

Research broadly when necessary, but initially maintain one admitted deployment
profile and a short list of candidates. For each capability record the exact
hardware/firmware/runtime revision, source and date, test method, measured
limits, unresolved questions and support owner.

Use four states: **vendor-claimed**, **bench-observed**, **accepted for a named
profile**, and **unsupported/unknown**. An attractive demonstration must not
silently promote a device from one state to another.

Evaluate task fit, controllable command paths, local interruption, sensing,
offline behavior, update/rollback, parts and repair, software dependencies and
total ongoing cost. Verify current price and availability before a quote.
Record procurement, physical repair and replacement responsibilities before
the trial. Prefer a small supervised pilot with accessible hardware over
stocking inventory before demand and repair logistics are understood.

The [Microduck plan](microduck_integration_plan.md) and
[source ledger](microduck_source_ledger.md) remain the technical reference.
Actual body capabilities must constrain the service promise.

## 5. Separate Configuration, Integration And Research

| Work class | Example | Delivery treatment |
| --- | --- | --- |
| Configuration | Reviewed script/content, language, schedule or an existing gesture choice | Bounded package with revalidation when behavior or permissions change |
| Supported integration | Connect an existing admitted skill to an approved event source | Estimated project with adapter tests and explicit scope |
| New capability research | New locomotion, manipulation, perception or robot body | Separate feasibility work; no fixed outcome promise before evidence |

Use an interaction flow plus a small set of versioned skills. Keep presentation
content, skill parameters, device profile and grants separate. A request such
as “make it faster” or “remember every visitor” is a scope/permission change,
not cosmetic personalization.

Reuse existing models and robot runtimes where they fit. New training is not a
default customization step. Build only the SeedCore components needed by the
first complete outcome: admission, adapter/session handling, required evidence,
basic operator controls and recovery. Reuse the existing code where it satisfies
the contract; do not require a new fleet console, marketplace or visual studio
to deliver the pilot.

Changes move through versioned test and admission steps. A customer request,
remote-support session or generated patch cannot directly modify a running
robot's authority or local limits.

## 6. Validate Value, Execution And Support Separately

Agree metrics before the trial. Keep the pilot profile, test conditions and
sample count with every result; small pilot counts do not demonstrate a
universal reliability level.

| Dimension | Useful measures | Decision |
| --- | --- | --- |
| Customer value | Desired outcome versus baseline, repeat voluntary use, operator effort and intent to continue at stated terms | Is this worth using? |
| Task performance | Completed valid tasks / eligible attempts; latency distribution; interruptions and failed attempts | Does it work often enough for the agreed job? |
| Governance | Denied, expired, revoked and bypass attempts; local-stop behavior; unresolved evidence | Are permission and outcome claims supported? |
| Operability | Setup time, independent start/stop/recovery, confusing states | Can the customer operate it? |
| Support | Tickets, engineer minutes per deployment, repeat faults, vendor dependencies | Can SeedCore sustain it? |

Track expected policy denials separately from failed valid tasks, while
retaining both in the action record. Report incomplete/uncertain attempts
explicitly; do not remove them from metrics to improve a success percentage.
Observe multiple uses after the initial demonstration to detect novelty effects.

Include startup/restart, lost connectivity, stale input, permissions changes,
interruption and missing evidence, using the existing acceptance contracts.
Customer enthusiasm cannot waive a failed technical gate. Equally, passing
every gate cannot substitute for a useful customer outcome.

## 7. Design Support Before Handover

Define support hours, contact channel, included help, escalation and response
expectations before the pilot. Distinguish acknowledgement of an issue from a
promise to restore service by a particular time. Avoid availability commitments
the small team cannot staff.

| Responsibility | Initial owner |
| --- | --- |
| Daily setup, approved workspace, charging and local stop | Trained customer operator |
| SeedCore configuration, admitted behavior and evidence diagnosis | SeedCore support owner |
| Physical repair, vendor firmware faults and spare parts | Named manufacturer/repair partner under its actual support terms |
| Permission expansion, deployment and quarantine clearance | Existing human-reviewed or policy-admitted process |

Provide a concise start/stop/recovery guide, a known-good configuration and a
versioned diagnostic bundle with minimum necessary data. Obtain a separate,
time-bounded grant for remote access. No permanent remote actuation authority
is implied by a maintenance subscription.

Triage into configuration/content, application/runtime, and hardware faults.
Loss of trustworthy control or unexplained motion invokes the reviewed local
response, preserves evidence and blocks unreviewed resume. Repeated deterministic
gate failures stop autonomous retries and surface verifier/runbook evidence.

Test updates on the known profile, use an agreed maintenance window, preserve
rollback and revalidate affected behavior. Define how the customer can pause
the service, export permitted records, remove access and end support. If parts
or vendor support disappear, reassess the offer rather than silently shifting
that burden to the customer.

## 8. Keep The Economics Visible

Separate feasibility, implementation and ongoing support in the proposed offer.
Price only after estimating effort and testing willingness to pay. A feasibility
engagement can end with a useful no-go finding; uncertain research must not be
hidden inside a promised ready-to-use function.

For planning, track:

```text
deployment contribution = service revenue
  - delivery labor (including founder time)
  - installation/travel and third-party costs
  - hardware subsidy, if any
  - expected included support/rework

recurring contribution = recurring service revenue
  - support labor - cloud/model costs - allocated service/replacement costs
```

These are operating estimates before shared overhead and taxes, not profit
forecasts or pricing advice. Keep reusable R&D visible separately; do not hide
customer-specific engineering or repair work as platform investment. Track
estimated versus actual hours and cash timing for every pilot.

Set an explicit learning budget if the first pilot is subsidized. Scaling needs
a credible path to positive contribution at the intended terms. Repeat faults
or support exceeding the allowance should trigger fixes, narrower scope or a
revised offer before adding installations.

## 9. Assign Roles Without Assuming A Large Team

| Responsibility | Accountable work |
| --- | --- |
| Solution lead | Need discovery, scope, customer expectation and commercial decision |
| Robotics/integration lead | Device fit, adapter, local behavior and hardware measurements |
| Runtime/verification lead | Authority boundary, evidence and release checks |
| Delivery/support owner | Installation guide, training, diagnostics and ongoing incident ownership |

One person may hold several roles. Identify gaps explicitly and bring in an
experienced reviewer or specialist for unfamiliar hardware/control work before
customer operation. Do not substitute extra software features for missing
operational competence. The customer's operator remains a necessary role.

In a weekly review, inspect actual customer evidence, one technical blocker,
support load, hours/cost against budget and the next go/rescope/stop decision.
Reserve capacity for support and regression work before accepting new build
work. A backlog is not a customer delivery promise.

## 10. First Planning Horizon And Expansion Rules

Use the following as a learning sequence, with dates set after staffing and
hardware availability are confirmed. The business stages do not rename M0–M5.

For the first planning cycle, prepare the offer and solution record, inventory
available hardware and founder hours, identify the highest-risk interface
unknown for M0, and set the discovery/feasibility effort caps. The next decision
is whether one need and one feasible body justify a trial commitment. Avoid
promising a customer delivery date until that decision has evidence.

| Stage | Work to finish | Expansion decision |
| --- | --- | --- |
| S0 — Define | One candidate offer, solution-record template, support boundary and effort caps | Start focused discovery when outreach is authorized |
| S1 — Establish fit | Initial discovery batch, one prospective trial partner, capability register, customer acceptance plan | Commit to a bounded pilot only if need and feasibility agree |
| S2 — Prove delivery | M0–M4 for the selected profile, one supervised customer trial and measured delivery/support cost | Continue only if both useful and technically admissible |
| S3 — Repeat | Second customer using substantially the same solution and measured setup/support effort | Productize the shared template if reuse is real |

The next robot body is justified when a repeated customer need requires it,
the initial offer has stable ownership/support and an explicit integration
budget exists. A broader studio is justified when repeated manual work shows
what should be automated. Wider autonomy requires its own acceptance evidence.

Stop or rescope when no recurring need emerges, required interfaces cannot be
governed, a physical limit cannot be observed/enforced, usefulness disappears
after novelty, or support costs cannot fit the intended offer. A no-go decision
is a valid way to preserve capacity for a better use case.

## Basis And Limits

The staged need/prototype decisions adapt the principles in the
[GOV.UK discovery guide](https://www.gov.uk/service-manual/agile-delivery/how-the-discovery-phase-works)
and [alpha guide](https://www.gov.uk/service-manual/agile-delivery/how-the-alpha-phase-works).
They support understanding the problem and testing uncertain assumptions before
larger commitments; they do not validate SeedCore's market or timetable.

The capability register and repeatable test approach are informed by
[NIST's robot evaluation review](https://www.nist.gov/publications/advancing-capabilities-industrial-robots-through-evaluation-benchmarking-and).
That work concerns industrial robot measurement; applying its measurement
principles here is an engineering judgment, not a certification claim for small
robots. Sources reviewed 2026-09-21.

All staffing, first-offer and batch-size choices above are proposed SeedCore
operating decisions. No customer contact, spending, hardware operation or
deployment is authorized by this document.
