# Investor Application Copy

## One-Sentence Pitch

SeedCore is a governed execution runtime that controls what AI agents and
autonomous systems are allowed to execute in high-trust physical workflows.

## Short Application Pitch

Agent frameworks help AI decide what to do. Prompt guardrails control what AI
says. SeedCore controls what AI is allowed to execute.

SeedCore sits between AI intent and real-world action. Before execution
authority can exist, it verifies explicit delegation, policy scope, asset
state, custody context, hardware authority, and evidence requirements.

Unlike an agent framework or a prompt guardrail, SeedCore is a deterministic
execution gate. It rejects ambient authority, issues short-lived,
scope-bound execution authority only when policy admits the action, and
produces replayable evidence chains that can be verified after the fact.

The core runtime is implemented and contract-tested. The current commercial
wedge is Restricted Custody Transfer: high-value physical asset movement where
AI intent, authentication, delegated authority, custody telemetry, and verifier
closure must all agree before the transfer is accepted.

The first vertical proof scene is a rare collectible shoe transfer. It is not a
sneaker marketplace. It is a compact, investor-readable demonstration of the
broader SeedCore pattern for luxury goods, logistics, robotics handoff,
industrial asset custody, lab samples, and other regulated physical workflows.

## Final Investor Narrative

SeedCore is a governed execution runtime for autonomous systems.

As AI agents and robotic workflows move from recommendation into execution,
enterprises need a way to prove that actions were authorized, scoped,
evidenced, and replay-verifiable before those actions are accepted. SeedCore
provides that execution gate.

The runtime sits between AI intent and real-world action. It checks explicit
delegation, policy scope, asset state, custody context, hardware authority,
and evidence requirements. Only when those gates pass does SeedCore issue
short-lived, scope-bound execution authority for the exact actor, asset,
operation, location, and time window.

After execution, SeedCore binds signed telemetry and evidence back to the
evaluated request and produces proof surfaces that can be replayed later. If
scope, authority, telemetry, or evidence does not match, the workflow denies
or quarantines instead of silently continuing.

The core runtime is implemented and contract-tested, including Agent Action
Gateway v1, scoped execution authority, Policy Decision Point flow, evidence
bundle primitives, result verification, proof rendering, and replay
verification foundations.

We are now packaging SeedCore into a focused commercial wedge: Restricted
Custody Transfer for high-value physical assets. The first proof scene is a
rare collectible shoe transfer, where the system must bind authentication,
buyer-agent intent, delegated approval, bounded custody authority, signed
handoff telemetry, delivery telemetry, and replay verification into one proof
chain.

The rare-shoe scene is not the company. It is the smallest vivid proof of a
larger infrastructure pattern: governed execution for autonomous systems
operating in high-trust physical workflows.

## Founder Summary

I am Neil Li, founder and architect of SeedCore.

Profile: Ex-Motorola and Alibaba. UESTC.

My work focuses on AI agent infrastructure, governed execution, memory and
state systems, and verifiable autonomous workflows.

I am building SeedCore because I believe the next major gap in AI
infrastructure is trusted execution. As agents become more capable, the
important question is not only whether they can reason, but whether their
actions can be authorized, constrained, observed, and verified when they touch
real systems. SeedCore is my attempt to build that trust/runtime layer.

## What We Are Looking For From Investors

I am looking for investor and advisor support turning SeedCore from a strong
technical runtime into a focused commercial company.

The main support I want from investors, VCs, accelerators, and strategic
advisors is:

- commercial wedge refinement around Restricted Custody Transfer
- structured customer discovery with logistics, luxury goods, robotics, and
  regulated physical-workflow buyers
- pilot design and partner introductions
- founder coaching on enterprise wedge, pricing, and go-to-market sequencing
- investment support and fundraising readiness
- Korea and Asia market access
- deep-tech founder network
- guidance around TIPS or related government programs where relevant

SeedCore needs the discipline of a focused wedge, not only more technical
breadth. The immediate goal is to convert a working runtime into a pilot-ready
company narrative, a small number of credible buyer conversations, and a demo
that makes the trust problem obvious to non-technical decision makers.

## Traction And Current Stage

SeedCore is in early commercialization. The core runtime baseline is
implemented and contract-tested, and the current work is packaging that
baseline into a pilot- and investor-ready vertical demo.

Implemented technical baseline:

- Agent Action Gateway v1
- scoped execution-authority lifecycle
- Policy Decision Point architecture
- generic Restricted Custody Transfer runtime
- evidence bundle primitives
- result verification flow
- proof rendering foundation
- operator and public proof surfaces
- replay verification foundation
- generic RCT signoff fixtures

Rare-shoe verticalization completed so far:

- `CollectibleShoeRegistration` read model
- deterministic rare-shoe fixture set
- rare-shoe gateway adapter into Agent Action Gateway v1
- happy-path replay bundle
- dynamic NFC clone / tamper fail-closed test
- cross-asset replay fail-closed test
- delayed-telemetry policy test
- public/operator proof redaction mapping

Market signal:

- public GitHub repository has generated organic investor interest
- inbound investor and accelerator interest
- clear initial wedge around Restricted Custody Transfer
- rare-shoe vertical selected as the first compact commercial proof scene

SeedCore is beyond the idea stage. It is an implemented technical framework
being converted into a focused commercial company.

## Next 30 Days

The next 30 days are focused on moving from local proof to publishable demo and
pilot discovery.

Completed or underway:

- final investor application copy
- one-page SeedCore overview
- rare-shoe fixture directory
- `CollectibleShoeRegistration` read model
- rare-shoe gateway adapter
- proof-path tests for happy path, NFC clone / tamper, cross-asset replay, and
  delayed telemetry
- `rare_shoe_happy_path_replay_bundle.json`
- public/operator proof redaction mapping

Remaining near-term deliverables:

- README section for the Rare-Shoe RCT demo
- five-minute demo walkthrough recording
- five-slide architecture / investor deck
- first customer discovery list and interview script
- pilot hypothesis for one initial buyer segment

Application phrasing:

```text
SeedCore's generic Restricted Custody Transfer runtime is implemented and
contract-tested. We have now verticalized the first rare-shoe proof scene with
deterministic fixtures, gateway adapter, replay bundle, fail-closed toxic-path
tests, and public/operator proof redaction. The next step is demo packaging
and pilot discovery.
```

## Short Form Answers

### What Problem Are You Solving?

AI agents are moving from recommendations into real-world execution, but most
systems still treat a logged-in agent, tool call, or workflow step as enough
authority to act. That is risky for physical assets, robotics, logistics,
regulated operations, and high-value commerce. SeedCore solves the gap between
AI intent and trusted execution by making authority explicit, scoped,
evidence-conditioned, and replay-verifiable.

### What Is Your Solution?

SeedCore is a governed execution runtime. It receives agent intent, evaluates
delegation and policy, checks asset and custody state, verifies required
evidence, issues bounded execution authority only on allow, and then binds
signed telemetry back to the evaluated request for replay and proof.

### Why Now?

Agentic AI is becoming operational. Enterprises will not only ask whether an
agent produced the right recommendation; they will ask whether an agent was
allowed to execute, whether the execution matched policy, and whether the
evidence can be verified later. That trust layer is still missing.

### Why This First Wedge?

Restricted Custody Transfer is a narrow but high-consequence workflow. It
forces the system to bind authentication, delegated authority, physical
custody, telemetry, and proof. Rare collectible shoes make the failure modes
easy to understand, while the same pattern extends to broader high-value
physical workflows.
