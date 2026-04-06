# Governance-Aware Learning Next Stage Plan

Date: 2026-04-06
Status: Working implementation plan for the post-Q2/Q3 bridge

## Purpose

This document defines the next higher implementation stage after the current
`Restricted Custody Transfer` hardening sequence:

**turn learned models from a black box into a compilable governance component
that strengthens SeedCore's trust slice without weakening the synchronous PDP
boundary.**

This plan exists because SeedCore is now at a point where the next meaningful
upgrade is not "add more model capability" in the abstract. The next upgrade is
to make learning systems useful inside the existing trust boundary:

- distillation to compress complex reasoning into bounded, replayable artifacts
- abstention tuning so models stop hallucinating authority
- governance-aware RL in simulation so robotics policies learn contract
  compliance natively
- proof/refinement loops that improve evidence quality without bypassing
  verification

## Core Rule

The rule for this stage is:

> The model may learn. SeedCore still decides.

That means:

- the final governed `allow` / `deny` / `quarantine` / `escalate` decision
  stays in the pinned, synchronous hot path
- learned systems may propose, preflight, score, refine, explain, simulate, or
  abstain
- learned systems do not become an unbounded alternate authorization path

## Why This Stage Exists

The repository already has the ingredients for a more serious learning loop:

- strict `seedcore.agent_action_gateway.v1` request boundaries
- replay-verifiable artifacts and strict triple-hash verification
- signed telemetry refs and closure evidence
- `seedcore-verify` and host verification scripts
- early distillation and tuning seams under `src/seedcore/ml/`
- simulation/training placeholders and VLA sidecar work

The missing piece is program shape. Today those seams are sidecar or exploratory.
This plan turns them into a bounded productization track.

## Non-Goals

This stage does not aim to:

- replace the PDP with an LLM
- let RL policies authorize physical execution on their own
- train a general foundation model inside SeedCore
- reopen the frozen RCT contracts just to make model training easier
- turn SeedCore into a broad robotics training platform

## What "Compilable Governance Component" Means

A learned component is acceptable in SeedCore only if it can be reduced to one
or more bounded outputs such as:

- typed scores
- typed reason-code predictions
- typed trust-gap predictions
- abstain / halt decisions
- contract-shaped evidence refinements
- simulator action policies that still require a valid `ExecutionToken`

Acceptable learned outputs are:

- schema-validated
- version-pinned
- replay-linkable
- promotable through shadow/canary style gates
- fail-closed when uncertain or out of scope

## Existing Repo Seams To Build On

These are the best entry points already present in the repo:

- `src/seedcore/ml/distillation/vla_distillation.py`
  - teacher escalation and trace-replay distillation orchestration
- `src/seedcore/tools/distillation_tools.py`
  - teacher and fine-tuning tool wrappers
- `src/seedcore/ml/distillation/sample_store.py`
  - sample persistence that can be extended from VLA traces to governance data
- `src/seedcore/ml/ml_service.py`
  - model serving, distillation, promotion, and shadow-scoring home
- `src/seedcore/tools/training_tools.py`
  - current placeholder training tools that can be upgraded into real simulation
    and reward plumbing
- `scripts/host/verify_rct_replay_strict.py` and `seedcore-verify`
  - verification feedback loop for trust-proof refinement
- `docs/development/vla_2026_optimizations.md`
  - useful robotics-side guidance, but it must remain subordinate to the trust
    slice

## Program Objectives

This next stage should deliver five outcomes.

### 1. Distilled Policy Scaffolds

Distill complex teacher reasoning into bounded student outputs that support the
stateless PDP rather than replacing it.

Target outputs:

- trust-gap prediction
- reason-code prediction
- obligation suggestion
- explanation scaffold
- preflight risk classification

### 2. HALT / Abstention Behavior

Tune model behavior so uncertainty about authority becomes an explicit,
contract-shaped abstention rather than improvisation.

Target outputs:

- `unsure_of_authority`
- `insufficient_evidence`
- `stale_context`
- `scope_mismatch`
- `requires_manual_review`

### 3. Trust-Proof Refinement

Use verification feedback to improve the generation and repair of
replay-verifiable bundles and `trust_proof` material.

Target outputs:

- higher first-pass verification success
- fewer malformed evidence bundles
- deterministic repair suggestions instead of free-form retries

### 4. Governance-Aware RL In Simulation

Train robot policies so contract compliance is part of the reward function, not
an afterthought bolted on after motion planning.

Target outputs:

- unauthorized-zone aversion
- token-scope compliance
- E-STOP preference over unsafe completion
- better evidence capture discipline in sim

### 5. Promotion Discipline

Every learned component must have a route from offline experiment to
shadow-scored production use without bypassing existing trust contracts.

## Execution Order

The next stage should be scheduled in six windows after the current contract and
operability work.

### Window G: 2026-06-08 to 2026-06-28

Goal:

- freeze the governance-learning data and evaluation contract

Must land:

- one `GovernanceLearningSampleV1` schema for:
  - request
  - decision
  - trust gaps
  - obligations
  - evidence summary
  - final verification outcome
- one export path from replay/verification artifacts into training samples
- one negative-example corpus from `deny`, `quarantine`, `escalate`, stale
  context, and mismatch cases
- one baseline evaluation harness measuring exactness against contract-shaped
  outputs

### Window H: 2026-06-22 to 2026-07-19

Goal:

- build the first distilled reasoning scaffold in shadow mode

Must land:

- teacher prompt/spec for RCT preflight and explanation scaffolds
- one student artifact that predicts bounded outputs such as:
  - `reason_code`
  - `trust_gap_codes`
  - `required_obligations`
  - `abstain`
- shadow evaluation path in the ML service or equivalent offline harness
- promotion gates comparing teacher/student predictions with real hot-path
  outcomes

Success criteria:

- no use of the student artifact as the final PDP
- exact or taxonomy-valid output on the chosen evaluation slice

### Window I: 2026-07-13 to 2026-08-09

Goal:

- implement HALT-style abstention tuning for authority uncertainty

Must land:

- one abstention taxonomy for the agent boundary
- supervised fine-tuning dataset from failed preflights, denied requests,
  stale-context cases, and human escalation examples
- request-path behavior that routes abstention to:
  - preflight only
  - operator review
  - no-execute
- contract tests proving the tuned model does not "work around" missing
  authority or failed preflight checks

Success criteria:

- the tuned model abstains on authority ambiguity instead of inventing a path
- no regression in strict gateway or verification contracts

### Window J: 2026-08-03 to 2026-08-30

Goal:

- build the trust-proof refiner and verification agent

Must land:

- one verification-agent workflow that wraps strict replay verification
- one structured feedback parser for `seedcore-verify` or
  `verify_rct_replay_strict.py`
- one refinement loop that proposes contract-shaped repairs to malformed proof
  bundles
- one supervised fine-tuning or self-distillation pass over successful
  `trust_proof` artifacts and verified evidence bundles

Success criteria:

- improved replay-verification pass rate on held-out malformed examples
- no automatic mutation of already-verified artifacts in production paths

### Window K: 2026-08-24 to 2026-09-27

Goal:

- implement governance-aware RL in simulation only

Must land:

- one simulator reward contract including:
  - mission completion
  - zone compliance
  - token scope compliance
  - E-STOP / safety behavior
  - evidence capture completion
- one simulation backend path for Unitree B2/Z1 or equivalent environment
- one policy-distillation pass from the RL teacher into a bounded student policy
  artifact
- one evaluation slice proving the learned policy respects governance
  constraints more often than a naive baseline

Success criteria:

- unauthorized motion incurs heavy negative reward
- simulated execution still requires valid authority artifacts in the loop
- physical execution remains gated by SeedCore, not by the RL policy alone

### Window L: 2026-09-21 onward

Goal:

- promote the best learning components into controlled product use

Must land:

- one shadow lane for distilled reasoning scaffold outputs on live RCT traffic
- one operator-visible comparison surface between learned scaffold and actual
  governed decision
- one rollout policy for enabling:
  - preflight recommendation
  - explanation assist
  - proof refinement assist
  - simulation policy promotion

Success criteria:

- learning improves operator speed or evidence quality without weakening
  admissibility guarantees
- every promoted artifact is pinned, measurable, and reversible

## Detailed Workstreams

### Workstream 1: Distilled Reasoning Scaffold

Intent:

- compress expensive teacher reasoning into bounded structures that fit the
  stateless, synchronous trust model

Implementation direction:

- teacher runs offline on replay-rich RCT cases
- student predicts typed outputs, not free-form legal prose
- PDP consumes those outputs only in shadow or preflight until proven safe

Best first use cases:

- explanation scaffold generation
- trust-gap prediction
- obligation recommendation
- shadow reason-code prediction

### Workstream 2: HALT / Abstention Tuning

Intent:

- teach models to stop when authority is uncertain

Implementation direction:

- collect examples where SeedCore correctly denied, quarantined, or escalated
- fine-tune a smaller model to emit bounded abstention states
- treat abstention as a strength, not as failure

Best first use cases:

- agent gateway preflight
- operator copilot brief warnings
- edge-actor no-execute recommendations

### Workstream 3: Trust-Proof Refiner

Intent:

- make evidence and trust-proof generation more verification-native

Implementation direction:

- use strict verifier feedback as the training signal
- bias for exact schemas, hashes, and signature-related fidelity
- keep refinement out of the final decision path unless separately approved

Best first use cases:

- malformed bundle repair suggestions
- pre-submission bundle linting
- `trust_proof` completeness checks

### Workstream 4: Governance-Aware RL

Intent:

- make control policies learn SeedCore's authority boundary rather than collide
  with it

Implementation direction:

- reward success only when the simulated execution path also respects:
  - authority scope
  - zone constraints
  - safety/E-STOP rules
  - evidence capture obligations
- keep the teacher in simulation
- distill only bounded student artifacts downstream

Best first use cases:

- handover and pickup maneuvers
- custody-zone compliance
- anomaly-first E-STOP behavior

## Acceptance Gates

This stage should not be considered successful unless it can prove all of the
following:

- the final PDP remains deterministic and synchronous
- no learned component bypasses `ExecutionToken` or approval requirements
- learned outputs are schema-valid and replay-linkable
- abstention improves authority safety rather than reducing throughput through
  noise
- verification-agent/refiner outputs increase proof quality measurably
- simulation RL produces governance-aware behavior before any hardware exposure

## Suggested First Code Changes

The most practical first implementation sequence is:

1. generalize `sample_store.py` from VLA traces into governance-learning sample
   storage
2. add one sample exporter from replay/verification artifacts
3. add one offline evaluation harness for bounded `reason_code` and
   `trust_gap_codes`
4. upgrade `train.simulation` and `train.behavior` from placeholders into a
   real simulator/reward plumbing layer
5. add one verification-agent tool wrapper that shells around strict replay
   verification

This order gives SeedCore the data and evaluation spine before it commits to any
particular model family.

## Decision Rule

When prioritizing learning work, choose the option that makes this statement
truer:

> SeedCore can use learned systems to improve admissibility, abstention,
> evidence quality, and robotics safety without weakening the deterministic
> governance boundary.

If a proposed ML feature makes that statement weaker, it is probably sidecar.
