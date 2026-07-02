# SeedCore Agent Prompt Profile Design Sketch

**Date:** 2026-07-02  
**Status:** Sidecar strategy sketch, not an implementation commitment  
**Scope:** Adapt the useful parts of the `msitarzewski/agency-agents` prompt
profile pattern for SeedCore role legibility without changing the authority path.

## 1. Review Decision

SeedCore should adopt the prompt-framework idea only as a **prompt profile**
discipline: a repeatable way to make agent instructions, output envelopes, and
operator-facing explanations less ambiguous.

It must not be adopted as an authority layer. A prompt profile can shape what an
agent drafts or explains, but it cannot admit an action, mint or widen an
`ExecutionToken`, clear quarantine, override revocation, mutate custody state,
or close evidence.

The governing rule stays:

```text
AI proposal -> Agent accountability -> PDP admission -> ExecutionToken attempt
-> HAL / actuator action -> receipt -> verifier / replay closure
```

## 2. Repo-Truth Boundary

The current agent stack already has role and behavior machinery:

- `src/seedcore/agents/roles/specialization.py` defines `Specialization`,
  `RoleProfile`, RBAC metadata, default behaviors, and advisory skill context.
- `src/seedcore/agents/roles/generic_defaults.py` registers default profiles for
  `USER_LIAISON`, `DEVICE_ORCHESTRATOR`, `OBSERVER`, and related roles.
- `src/seedcore/agents/base.py` is the active generic agent substrate. The
  concrete `ConversationAgent`, `OrchestrationAgent`, and `ObserverAgent`
  classes are deprecated compatibility wrappers around that substrate.
- `src/seedcore/graph/agent_repository.py` persists agent and organ registry
  state. It does not currently store or load system-prompt templates.
- `CognitiveCore` performs cognitive/retrieval work, but the repo does not yet
  show a production path that dynamically loads role-keyed prompt profiles into
  every agent invocation.

Therefore this document is a future design reference. Any implementation should
start with explicit contracts and tests rather than wiring prompt text directly
into the authority path.

## 3. Prompt Profile Blueprint

Each SeedCore prompt profile should use four sections, but the sections should
be SeedCore-native:

```text
# Prompt Profile: [profile_name]
# Applies To: [Specialization or role profile]
# Authority Posture: advisory | proposal | read_only | verifier_explanation

## 1. Identity And Boundary
[What the agent is allowed to help with, and the authority it does not hold.]

## 2. Mission And Workflow
[The narrow workflow it supports, including where it must stop.]

## 3. Allowed Draft Artifacts
[The structured drafts, explanations, or diagnostics it may emit.]

## 4. Metrics And Escalation
[Quality checks, refusal/escalation conditions, and verifier-facing references.]
```

This keeps the agency-agents-style regularity while replacing broad persona
claims with SeedCore's trust-runtime boundary language.

## 4. SeedCore Profile Sketches

### 4.1. User Liaison Profile

**Applies to:** `Specialization.USER_LIAISON`, currently used by
`ConversationAgent` / `BaseAgent` chat behavior.

**Authority posture:** advisory and explanatory only.

**Mission:** explain governed outcomes, request missing operator context, and
render answers from authorized evidence.

**Allowed draft artifacts:**

- operator explanation drafts
- citation-bound RAG answer drafts over an authorized `RAGEvidenceBundle`
- clarification requests when evidence or policy context is insufficient

**Hard stops:**

- do not present memory, chat history, or retrieved context as authority
- do not expose hidden scratchpad reasoning as an output contract
- do not imply that a user question changes active policy, custody, quarantine,
  or verifier state
- do not cite denied RAG candidates except through aggregate denied-summary
  counts that are already permitted by the governed RAG contract

### 4.2. Delegation Lead Profile

**Applies to:** `Specialization.DEVICE_ORCHESTRATOR` and future recursive
delegation profiles.

**Authority posture:** proposal and scoping assistant only.

**Mission:** translate tasks into bounded candidate work packages and ensure
subtasks remain narrower than the parent request.

**Allowed draft artifacts:**

- candidate `ActionIntent` fields for downstream validation
- child-task envelopes with explicit parent context, requested scope, TTL, and
  closure expectations
- escalation notes when delegation lineage, scope, identity, approval, or
  freshness is missing

**Hard stops:**

- do not evaluate active policy graphs inside the prompt profile
- do not mint, widen, or refresh `ExecutionToken`s
- do not execute mutating tools without an admitted token-bearing path
- do not treat sub-agent output as custody closure or verifier acceptance

### 4.3. Forensic Observer Profile

**Applies to:** future verification-facing observer profiles. The existing
`Specialization.OBSERVER` is a cache-warming / monitoring profile, so forensic
closure should be anchored to `RESULT_VERIFIER` surfaces or explicit verifier
tools, not assumed from the `ObserverAgent` class name.

**Authority posture:** read-only diagnostic unless wired behind verifier-owned
runtime code.

**Mission:** compare declared state, telemetry references, policy receipts, and
replay artifacts; surface mismatches for verifier or operator review.

**Allowed draft artifacts:**

- mismatch reports with reason-code candidates
- replay/runbook references
- candidate quarantine or escalation recommendations
- validation-status logs that point to evidence refs without exposing raw
  private telemetry material

**Hard stops:**

- do not mutate digital-twin state from a prompt profile
- do not clear quarantine or mark closure accepted
- do not treat telemetry presence as custody settlement
- do not emit `RAGTrace` as a generic observer artifact unless the task is
  actually in the governed RAG lane

## 5. Integration Strategy

The safe implementation path is incremental:

1. Add prompt-profile metadata as a separate, non-authoritative companion to
   `RoleProfile`, or as an external config keyed by specialization.
2. Keep prompt rendering in the cognitive/advisory layer. The rendered prompt
   may influence drafts and explanations only.
3. Validate generated artifacts with existing schemas such as `ActionIntent`,
   `RAGEvidenceBundle`, `VerifiedRAGClaim`, `RAGTrace`, or future delegation
   envelopes before any downstream use.
4. Route every execution attempt through the existing PDP, `ExecutionToken`,
   HAL/actuator, evidence, replay, and `RESULT_VERIFIER` chain.
5. Add negative tests that prove prompt profile output cannot bypass policy,
   widen authority, cite denied evidence, or clear verifier failures.

## 6. Acceptance Criteria For Promotion

This sketch should remain sidecar until a narrow implementation slice proves:

- prompt profiles are loaded deterministically and versioned
- each profile contains an explicit authority posture
- generated drafts are schema-validated before use
- RAG prompt profiles render only authorized evidence
- delegation profiles cannot widen parent scope or TTL
- verifier-facing profiles can recommend escalation but cannot override
  verifier outcomes
- docs and tests continue to state that prompts are not authority sources

Until then, the value of the framework is legibility, consistency, and safer
drafting. SeedCore authority remains with deterministic policy admission,
scoped execution tokens, evidence closure, and replayable verifier outcomes.
