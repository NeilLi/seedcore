# SeedCore Physical AI Strategy

Date: 2026-09-21
Status: Active product direction; adoption hypotheses and future capabilities are unvalidated

## Product Thesis

**SeedCore is a trust runtime for physical AI: it governs which agent may ask
which robot to do what, under which limits, and preserves evidence of the
attempt.** Small robots are the first integration focus. Microduck is the
reference target, not the boundary of the product.

The customer-facing mission is to **help people discover a useful job for a
small robot, choose suitable hardware, and implement and support the functions
they need**. The team delivers that service; the runtime provides its reusable
technical foundation. People should not need robotics expertise to describe
their desired outcome. See the
[customer delivery model](robot_solution_delivery.md).

The strategic bet is that more accessible robots and more independently
authored behaviors will increase the need for portable authority and evidence
contracts. This is a hypothesis, not a market-size or adoption forecast. The
first task is to validate a real customer need alongside the engineering
boundary needed to deliver it. More robot choices alone do not establish demand
for SeedCore's service or willingness to pay.

The product should fit between an agent/application and a robot's existing
runtime. Its reusable unit is a **governed skill attempt**: a versioned skill,
an accountable principal, bounded authority, local enforcement and a verifiable
outcome. A cute persona can attract users; this contract is what other teams
could depend on.

## Customers, Delivery Partners And First Proof Point

The intended customers include ordinary robot owners, creators and small
organizations who can describe a useful function but need help selecting and
adapting a robot. Start discovery with supervised activities whose usefulness
and limits can be evaluated directly. Robotics developers, labs and hardware
partners are early technical collaborators and may also be customers.

Run two tracks: customer discovery identifies the job and success criteria;
engineering establishes a trustworthy execution path. A customer trial needs
both. A successful bounded-motion test does not prove that the intended
function solves a worthwhile problem.

The first engineering proof point is deliberately small: an agent proposes a short move in
a marked test area, the operator sees its limits, SeedCore admits or denies
it, the robot attempts it, and a timeline explains completion or interruption.
Show allowed, denied and interrupted attempts together. The first product
artifact is a reproducible integration and its evidence, not a skill store.

| Stage | User value to validate | Evidence needed before expansion |
| --- | --- | --- |
| Needs assessment and hardware fit | Turn an ordinary request into a feasible, useful function | Reviewed need brief, alternatives, constraints and acceptance criteria |
| One supervised Microduck | Bounded AI behavior with understandable outcomes | M0–M4 demonstration and reproducible failure cases |
| Reusable skill packaging | Install/change behavior without silently expanding authority | Package admission, isolation and rollback tests |
| A second robot adapter | Reuse the same authority/evidence concepts across bodies | Independent developer integration; documented body-specific differences |
| Small teams of robots | Explain partial execution and reconcile shared resources | Durable ownership, per-robot closure and measured local enforcement |
| Household companions | Owner/guest boundaries and control of captured media | Separate privacy, access, recovery and household evaluation work |

Needs assessment can start immediately. Customer hardware trials depend on
the selected profile's technical acceptance; broader household autonomy is a
later scope than a supervised personal routine.

Child interaction, eldercare, assistive navigation and unattended operation are
not first-pilot use cases. They introduce requirements the present simulator
and governance tests do not establish.

## Where SeedCore Fits

| Component | Responsibility | SeedCore's integration responsibility |
| --- | --- | --- |
| LLM, VLA or behavior planner | Propose intent using observations | Keep proposals separate from authority and bind the selected artifact |
| Training/simulation tools | Produce and evaluate candidate policies | Admit promotion separately; distinguish simulation from hardware evidence |
| Robot SDK and middleware | Transport requests and expose device capabilities | Map reviewed skills to an authenticated endpoint; constrain alternate paths |
| Onboard controller | Balance, actuator control, local interlocks and recovery | Deliver bounded intent; accept refusal and report observed interruption |
| SeedCore trust runtime | Accountability, policy, tokens, revocation and evidence closure | Make the complete boundary reproducible for an integrator |
| Product application | Interaction, persona, explanations and operator controls | Display permissions and uncertainty without minting authority |

Microduck's pinned architecture assigns control and bus ownership to `robotd`.
Reachy Mini also separates a client SDK from a daemon that handles hardware and
safety checks. These are useful integration boundaries; their existence does
not establish SeedCore enforcement. Sources:
[Microduck architecture](https://github.com/pollen-robotics/microduck/blob/768e1922715942d8c6aa5254c6d1cd35cf099482/docs/design/architecture.md),
[Reachy Mini concepts](https://huggingface.co/docs/reachy_mini/SDK/core-concept)
(reviewed 2026-09-20; the latter is unpinned).

Use the native Microduck interface first. ROS 2 or micro-ROS adapters should be
added when a selected device needs them. Choosing middleware, a Rust daemon,
or a new single-board computer does not by itself create a trustworthy
execution boundary. Ray, Redis and Postgres can support orchestration and
evidence services; a network round trip to them must not be required to stop
the robot locally.

## What To Keep From Custody Work

Keep delegated authority, endpoint binding, revocation, authenticated receipts,
replay validation and incomplete-evidence handling. Preserve RCT as a regression
reference rather than making shoe handoffs the opening robotics story.

Do not map a custody transaction directly onto every control tick. A robot
attempt has duration, changing observations, interruption and uncertain physical
outcomes. A receipt can prove that a command was admitted or acknowledged
without proving it completed. The
[runtime contract proposal](robot_execution_contract.md) defines that distinction.

## Assessment Of The Supplied Suggestions

| Suggestion | Decision | Reason and implementation consequence |
| --- | --- | --- |
| Two-speed authorization | Adopt with three explicit responsibilities | Admission, local continuous enforcement and asynchronous evidence closure have different deadlines |
| New `TaskExecutionToken` / kinematic PDP | Defer a new token type | Start with the existing `ExecutionToken`; version and review robot-specific bindings without changing frozen constraints silently |
| Fixed 1 Hz / 50–200 Hz rates | Replace with measured budgets | Control periods, command age and stopping behavior depend on the selected body and runtime |
| ReBAC skill manifests | Adopt as a proposed package contract | Identity relationships and grants need argument limits plus actual process/device/network isolation |
| Episodic black box | Adopt as an evidence timeline | Replay validates captured records; exact perception reconstruction needs retained inputs and reproducible model state |
| Signed sensor frames detect spoofing/drift | Narrow the claim | A valid signature establishes provenance/integrity under its key assumptions, not physical truth or calibration |
| Simulation, studio, edge daemon | Reorder delivery | First prove one native adapter and local interruption; productize packaging after the boundary works |
| Production-ready foundation / guaranteed physical safety | Reject as unsupported | Existing code and contract tests do not establish deployed enforcement, all-path coverage or physical safety certification |

The attachment is advisory input to this strategy. Its claims are not a source
of implementation status. The [source ledger](microduck_source_ledger.md) and
linked repository code remain the evidence for the selected baseline.

### Closed-Loop Proof-Point Roadmap Review (2026-09-21)

The follow-up attachment contributes useful implementation candidates. It does
not establish live simulator availability, upstream RPC behavior, timing bounds
or commercial demand.

| Suggestion | Treatment |
| --- | --- |
| `MicroduckAdapter` with a Unix-socket proxy | Evaluate in M1–M2; protect the native socket, authenticate callers and test alternate ingress. A forwarding proxy alone does not establish enforcement. |
| Bounded session and sequence-numbered refresh | Consistent with the proposed contract; exact wire methods and watchdog behavior must come from the pinned executable runtime. |
| Fixed walking speeds, lease durations and 100 ms stopping | Illustrative only. Freeze profile-specific acceptance limits before testing, and distinguish stop-request latency from observed physical stopping. |
| Tiered telemetry and a rolling recorder | Adopt as a candidate capture design; always retain evidence required by the skill's outcome predicate. Hashes cannot recover discarded detail. |
| Commercial scenes and an audit console | Treat scenes as customer-discovery hypotheses. Ordinary users need function setup, permission, stop and help controls; diagnostics support those workflows. |
| Edge package in weeks 1–3; hardware in weeks 4–6 | Replace date promises with dependency gates and estimates after M0. Packaging and hardware readiness remain unvalidated. |
| Second adapter proves a universal runtime | It provides evidence of reuse across two specific bodies; choose it for an actual customer need. |
| Rename M5 to skill packaging | Preserve M5 as learning/promotion; packaging stays a separately named follow-on to avoid conflicting roadmaps. |

The suggested next-code-sprint and commit steps are advisory. This strategy
update does not implement an adapter or approve a repository commit, deployment
or robot operation.

## Adoption And Differentiation

The strongest prospective advantage is an integration kit containing stable
authority/evidence contracts, adapter conformance fixtures, realistic failure
traces and an understandable operator timeline. Each new adapter should reuse
those contracts while declaring its own physical limits. This is more useful
to validate than a broad claim to be the operating system for all robots.

Test the value with an external developer: can they integrate a new skill,
understand a denial, reproduce an interrupted attempt, and change the planner
without changing the permission model? Record elapsed integration effort and
where they needed SeedCore-specific knowledge. If the integration is too heavy,
reduce dependencies and improve the contract before adding more applications.

The initial commercial hypothesis is needs assessment, hardware selection,
scoped function implementation and optional support. Repeated customer jobs
should become reviewed solution templates backed by reusable skills and
adapters. Validate customer usefulness, delivery effort and support costs as
well as developer integration effort. Demand, pricing and willingness to pay
remain unvalidated; a marketplace or fleet service is not a prerequisite.

Execute this through the [service operating plan](robot_service_operating_plan.md).
For the founder-led stage, constrain work to one repeatable offer, one active
hardware integration and one live pilot. Separate configuration, integration
and research, then prove a second delivery of the same solution before widening
the supported combinations.

## Milestones And Decision Evidence

The [active queue](../current_next_steps.md) owns M0–M5. Extend beyond it only
after the preceding integration has evidence, not because a calendar date has
arrived.

| Measure | Record | Decision it supports |
| --- | --- | --- |
| Customer usefulness | Agreed job outcome versus the existing workflow, trial feedback and repeat use | Whether the solution is worth delivering |
| Delivery sustainability | Setup time, customization/support hours, continuing costs and template reuse | Whether another customer can be served sustainably |
| Authority coverage | Every command ingress and outcome of bypass/negative tests | Whether the claimed boundary is actually enforced |
| Admission overhead | p50/p95/p99 latency and failures under a named load/profile | Whether skill admission is usable |
| Local response | Worst observed stop latency/distance, command age, jitter, fault conditions | Whether the measured profile meets its reviewed limits |
| Evidence completeness | Attempts with correlated closure; missing records and unresolved outcomes | Whether operators can explain each attempt |
| Runtime footprint | CPU, memory, storage and offline behavior on the target board | Whether the edge boundary is practical |
| Integration effort | External developer time, changed components and support needed | Whether contracts are reusable |
| Portability | Reused contracts versus body-specific work on a second adapter | Whether SeedCore is becoming a component rather than a one-robot demo |

Set numeric pass thresholds in the selected profile before testing; do not
retrofit them to make a run pass. Tail latency and worst observed behavior are
measurements, not universal physical guarantees. Preserve failures and report
sample size, hardware, versions and test conditions.

## Documentation Contract

The root README leads with the product, present capabilities, first experiment
and limitations. This strategy explains why. The
[robot execution proposal](robot_execution_contract.md) and
[skill package proposal](robot_skill_contract.md) explain the intended design.
The [Microduck plan](microduck_integration_plan.md) owns device-specific work.
The [customer delivery model](robot_solution_delivery.md) connects needs,
hardware selection, custom functions, acceptance and support.

Use “implemented”, “locally tested”, “planned” and “hardware-validated” only
with their scope and evidence. Prefer **trust runtime for physical AI** over
“trusted operating runtime” when the latter might imply an operating system or
a physical safety guarantee. The public application studio can showcase robot
experiences while the repository explains the reusable runtime beneath them.
