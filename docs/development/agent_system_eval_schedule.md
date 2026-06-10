# Agent System Evaluation Schedule

Date: 2026-06-10
Status: Working schedule for SeedCore-native AI system evals

## Purpose

This schedule turns the AI evaluation discussion into a SeedCore development
track.

The point is not to make SeedCore depend on a specific vendor eval product. The
point is to treat AI-system behavior the way the runtime already treats
governed execution: fixture-backed, replayable, regression-tested, and tied to
evidence rather than intuition.

For SeedCore, the useful eval unit is the governed workflow, not an isolated
model answer:

```text
agent proposal
-> bounded preflight or gateway request
-> PDP decision
-> ExecutionToken posture
-> evidence bundle or no-execute result
-> replay / verifier outcome
-> typed verdict
```

This schedule complements
[`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md).
That plan defines the Scenario Generator, Governance Reward Scorer, Learning
Sample Store, and Advisory Student loop. This schedule defines the eval
fixtures, regression slices, and promotion gates that make the loop measurable.

## Cross-Schedule Rule

Every eval must preserve SeedCore's authority boundary:

```text
The eval can measure, compare, score, and regress behavior.
The eval cannot authorize execution.
```

OpenAI-style eval tooling, trace grading, custom graders, local harnesses, or
CI scripts may all be used as measurement infrastructure. None of them may
issue an `ExecutionToken`, override PDP output, clear quarantine, reinterpret
`RESULT_VERIFIER`, or promote `shadow` to `enforce`.

## What Must Be Evaluated

SeedCore needs four eval families first:

1. **Decision evals** - does the system choose the expected
   `allow` / `deny` / `quarantine` / `escalate` outcome for a contract-shaped
   Restricted Custody Transfer case?
2. **Policy evals** - does stale context, missing approval, scope mismatch,
   wrong asset, wrong zone, signer failure, or incomplete telemetry fail closed
   with the correct reason codes?
3. **Forensic evals** - after an admitted attempt, is the evidence chain
   complete, replayable, hash-bound, and accepted or rejected by the verifier
   for the right reason?
4. **Agent-governance evals** - when an agent asks for authority, does it use
   the explicit preflight/gateway path, respect no-execute responses, surface
   missing evidence, and avoid inventing authority?

These evals are system-level regression tests. They should consume real
SeedCore contracts and outputs wherever possible:

- `seedcore.agent_action_gateway.v1` request fixtures
- `ActionIntent` / PDP decisions and reason codes
- `ExecutionToken` posture and constraints
- `EvidenceBundle` and signed telemetry refs
- replay bundle hashes and verifier outcomes
- `GovernanceLearningSampleV1` typed verdicts

## Required Metrics

Each eval run should emit:

- exact decision match rate
- reason-code match rate
- fail-closed coverage for toxic paths
- replay parity rate
- evidence bundle completeness
- verifier outcome match rate
- agent no-execute compliance rate
- hallucinated-authority count
- stale-context abstention rate
- near-miss coverage by `trust_gap_codes`

For learned or advisory components, report the model/scaffold result beside the
runtime result. The runtime result remains authoritative.

## Window S0: 2026-06-10 To 2026-06-21

Goal:

- define the SeedCore eval contract and seed corpus

Must land:

- one `AgentSystemEvalCaseV1` schema that references, rather than copies,
  gateway request, PDP decision, evidence, replay, verifier, and typed-verdict
  artifacts;
- a seed corpus covering at least happy path, deny, quarantine, stale context,
  missing evidence, signer violation, cross-asset replay, and coordinate tamper;
- a mapping from existing host/CI gates to the four eval families above;
- documentation that eval outputs are measurement artifacts only.

Exit criteria:

- every seed case has an expected decision family, expected reason-code family,
  and expected verifier posture;
- no eval case can be interpreted as an execution token or promotion approval.

## Window S1: 2026-06-22 To 2026-07-12

Goal:

- build the baseline regression harness for RCT system behavior

Must land:

- a local harness that runs the seed corpus through the same preflight,
  gateway, PDP, replay, and verifier surfaces used by existing tests;
- JSONL or equivalent machine-readable output for eval results;
- summary metrics for decision match, reason-code match, replay parity, and
  verifier outcome match;
- CI wiring for the minimum toxic-path slice.

Exit criteria:

- the harness can compare current runtime behavior to expected contract
  outcomes without using an LLM grader;
- failures point to the contract layer that regressed: gateway, PDP, evidence,
  replay, verifier, or agent behavior.

## Window S2: 2026-07-13 To 2026-08-09

Goal:

- add agent workflow and advisory-scaffold evals

Must land:

- trace-style cases for agent preflight, no-execute behavior, tool selection,
  missing-evidence reporting, and abstention;
- a grader contract that checks whether advisory outputs are bounded to
  `reason_code`, `trust_gap_codes`, `required_obligations`, `abstain`, or
  explanation scaffold fields;
- tests proving an agent or advisory student cannot convert an eval pass into
  execution authority.

Exit criteria:

- agent behavior is measurable across model, prompt, tool, and memory changes;
- hallucinated authority and ignored no-execute results are counted as hard
  failures.

## Window S3: 2026-08-03 To 2026-08-30

Goal:

- add forensic and proof-quality evals

Must land:

- eval cases for malformed evidence bundles, missing telemetry refs, stale
  signer posture, replay tamper, outbox delay, and verifier mismatch;
- a structured parser for strict replay verification output;
- a comparison view showing proposed proof repairs beside deterministic
  verifier outcomes.

Exit criteria:

- proof-refinement assistance improves malformed-example pass rate in shadow;
- verified production artifacts are never automatically mutated by the
  refinement loop.

## Window S4: 2026-08-24 To 2026-09-27

Goal:

- connect eval results to governance-aware learning without expanding
  authority

Must land:

- export from eval results into `GovernanceLearningSampleV1`;
- near-miss ranking by trust-gap vector and distance-to-boundary;
- negative-example handling for `verification_mismatch` and `stale_context`;
- one simulation-only evaluation slice for governance-aware policy behavior.

Exit criteria:

- learning samples are replay-linkable and typed;
- no stale-context or verifier-mismatch sample can become positive
  authorization training material.

## Window S5: 2026-09-21 Onward

Goal:

- use evals as promotion evidence for advisory and shadow components

Must land:

- trend dashboards or artifact summaries for eval metrics across runtime,
  prompt, model, policy, and scaffold changes;
- a release checklist requiring eval evidence before changing advisory
  scaffolds, policy-assistant behavior, proof-refinement flows, or agent
  self-regulation prompts;
- operator-visible comparisons between learned/advisory outputs and actual
  governed decisions.

Exit criteria:

- eval evidence can support reviewable promotion of advisory or shadow
  components;
- enforce-mode, quarantine clearance, and production trust-state mutation still
  require the existing PDP, verifier, and operator promotion controls.

## Non-Goals

This schedule does not:

- replace existing deterministic unit or integration tests;
- make a model grader the source of truth for governed decisions;
- make OpenAI Evals, or any other hosted eval platform, a production
  dependency;
- score business success separately from trust-runtime correctness;
- authorize execution, clear quarantine, or promote enforcement.

## Read With

- [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)
- [`policy_gate_matrix.md`](policy_gate_matrix.md)
- [`gated_action_dx_layer.md`](gated_action_dx_layer.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`freshness_sla_edge_stress_schedule.md`](freshness_sla_edge_stress_schedule.md)
- [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md)
