# From A Person's Need To A Working Robot Function

Date: 2026-09-21
Status: Proposed customer service and delivery model; customer demand and economics unvalidated

## Customer Promise

**SeedCore helps people choose a small robot for a real need, build the
functions they want, and keep those functions working within agreed limits.**

People should be able to describe an outcome without choosing a model, SDK or
control protocol. SeedCore's team translates that outcome into a feasible
solution. The [trust runtime](robot_execution_contract.md) supplies the
permission, interruption and evidence foundation underneath it.

The customer-facing unit is a **robot solution**: a defined job, suitable
hardware, configured functions, operating limits, acceptance evidence and a
support plan. Internally, it may compose several governed skill attempts.
Customer acceptance of the solution does not replace per-action authorization.

## Discover The Job Before Choosing The Body

Start with a short conversation and, where necessary, a workspace walkthrough.
Record a need brief containing:

| Question | Decision it informs |
| --- | --- |
| What do you want to happen, for whom, and how often? | One observable outcome and intended users |
| How is it done today, and what is difficult about it? | Baseline and whether a robot adds value |
| Where will it operate, and who else will be present? | Space, surfaces, supervision and operating conditions |
| Does the job need movement, physical contact, sensing or simply expression? | Required body capabilities; a mobile robot is not assumed |
| What may it see, hear, retain or send elsewhere? | Data collection and processing permissions |
| What budget, setup effort and maintenance can you accept? | Total ownership cost and support feasibility |
| What should happen when it cannot complete the job? | Visible failure, stop control and human fallback |
| How will we know it helped? | Customer acceptance criteria agreed before implementation |

The result may be a robot solution, a simpler screen/speaker/tool, a smaller
scope, or a decision to defer. A need brief is an advisory planning artifact;
it is not a delegation or execution credential.

## Hardware Selection And Delivery

| Step | SeedCore team delivers | Exit condition |
| --- | --- | --- |
| Understand | Need brief, existing workflow and alternatives | Customer recognizes the problem and desired outcome |
| Compare | Shortlist with fit, limitations, dated sources, costs and support assumptions | Required capabilities supported; unknowns assigned a validation step |
| Specify | One function, interaction flow, permissions, workspace and acceptance plan | Customer understands both behavior and boundaries |
| Prototype | Simulation or fixture demonstration with explicit limitations | Functional and negative cases reproducible; no hardware claim from simulation alone |
| Validate | Supervised trial on the selected body and intended setting | Measured results meet both customer criteria and runtime/hardware gates |
| Hand over | Configured function, plain instructions, stop/recovery practice and support contact | User can operate and interrupt it without developer tools |
| Maintain | Versioned updates, issue diagnosis, rollback and periodic fit review | Changes remain within reviewed scope or receive renewed review |

For each candidate, check actuator/sensor fit, controllable interfaces, local
stop behavior, command-path coverage, privacy controls, parts/repair support,
runtime compatibility and continuing costs. Price and availability must be
checked when recommending or quoting. Distinguish vendor claims from SeedCore
tests; disclose referral or resale interests if present. Record why rejected
options failed to fit. Do not buy hardware or commit the customer to a service
as part of an advisory comparison.

Microduck remains the engineering reference. A customer's need determines their
hardware choice. A second adapter is justified when a validated need requires
it and its integration cost is supportable; it tests reuse for that body, not
universal robot compatibility.

## First Customer Experiments

Begin discovery with adults who can supervise a bounded activity, including
individual creators and small-business owners. These are candidate experiments,
not validated segments or claims that a particular robot can perform them.

| Expressed need | Small function to investigate | Evidence of usefulness |
| --- | --- | --- |
| “Make my exhibit more engaging.” | An operator-triggered gesture and short explanation in a marked area | Visitors understand it; the operator can start/stop it; setup effort is acceptable |
| “Help me present something in my studio or shop.” | An on-demand introduction using reviewed content from a fixed position | Useful information delivered with manageable interruptions and support needs |
| “Give my hobby robot a personal routine.” | A short owner-triggered expressive sequence within supported capabilities | Owner can configure, repeat and stop it; limits are understood |

Agree numeric trial criteria and a comparison with the existing workflow before
testing. Measure usefulness and repeat use alongside technical completion.
Avoid selecting a scene solely because a robot demo is visually impressive.

Requests involving carrying objects, public roaming, unattended monitoring or
care may be recorded during discovery. They require separate feasibility and
acceptance work and are outside the initial supervised pilot scope.

## A Product People Can Operate

The customer interface should answer: “What can it do?”, “When is it allowed?”,
“What data does it use?”, “How do I stop it?” and “What happened last time?”
Prioritize task setup, clear permissions, start/stop controls, understandable
status and help. Put detailed evidence and diagnostics in a support view.

Keep the function's result separate from a friendly response. Saying “done”
cannot close an unobserved action. Explain an incomplete or interrupted attempt
plainly and offer only supported recovery steps. Remote support access needs
its own explicit grant; a support subscription is not standing robot authority.

## Reuse And Business Model

Begin as a team-delivered service: needs assessment, selection advice, scoped
implementation and optional ongoing support. Test which deliverables customers
value and what they will pay for before fixing prices or subscription promises.
Separate hardware, customization, third-party usage and support costs.

Turn repeated solutions into reviewed templates containing a need profile,
compatible hardware profiles, interaction flow, versioned skills, permissions,
acceptance cases and support instructions. Templates reuse engineering while
each installation still validates its local conditions and grants. They are
not pre-authorized execution or an open skill marketplace.

Track time to useful first run, customer repeat use, setup/support hours,
interventions and unresolved attempts, cost to deliver, and how much the next
installation reuses. An interesting custom project becomes a repeatable offer
only when another customer has the same need and the delivery/support burden
is sustainable. Keep private recordings and customer data out of shared
templates unless separately authorized.

## Two Tracks And A Shared Release Gate

The [service operating plan](robot_service_operating_plan.md) turns this model
into a founder-led workflow: one initial offer and supported profile, bounded
customization, stage owners, acceptance measures, support responsibilities and
delivery economics. Use it to decide whether to accept, rescope or defer work.

Customer discovery can proceed while engineering completes M0–M4. A bounded
motion demonstration validates the runtime; it does not establish customer
demand or the usefulness of a custom function.

Before a customer hardware trial, require both a reviewed need/acceptance brief
and completed technical gates for the selected robot, skill and environment.
The [active queue](../current_next_steps.md) owns this sequencing. This document
authorizes no outreach, purchases, deployment or hardware operation by itself.
