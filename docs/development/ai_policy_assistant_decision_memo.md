# AI Policy Assistant Decision Memo

Date: 2026-04-08  
Status: Proposed decision; baseline inspection passed on 2026-05-19

Implementation follow-up:

- [Policy Assistant MVP Spec (SeedCore API + Runtime)](/Users/ningli/project/seedcore/docs/development/policy_assistant_mvp_spec.md)
- [Policy Assistant MVP Spec (pkg-simulator UI + Integration)](/Users/ningli/project/pkg-simulator/docs/POLICY_ASSISTANT_MVP_SPEC.md)

## Implementation Status (2026-05-19)

Inspection result: the current SeedCore baseline now follows the four
policy-assistant guardrails in this memo:

- raw rule authoring is not the main consumer policy UX; the documented product
  lane remains a guided workbench / simulator
- assistant-initiated PKG activation is blocked unless it carries a reviewed
  simulation/preflight report, an explicit human confirmation ref, and
  `confirm_activation=true`
- the policy-assistant lane remains advisory / simulation / explanation, while
  runtime authority remains in the deterministic PKG activation, Agent Action
  Gateway, PDP, and verifier paths
- `/api/v1/pkg/status` now reports `runtime_posture` so product surfaces can
  distinguish current policy-checked behavior from full freeze certainty

Current PKG posture is still intentionally reported as **not full freeze
certainty**: generated RCT manifests still set `requires_signed_bundle=false`,
and strict replay / activation hardening controls remain environment-gated.
Until those controls are default-on, product copy should continue to describe
PKG outcomes as simulated, preflighted, and policy-checked rather than
absolutely frozen or irreversible.

Relevant runtime anchors:

- `src/seedcore/api/routers/policy_assistant_router.py` keeps scenario-pack
  evaluation on the `no_execute=true` preflight path
- `src/seedcore/api/routers/pkg_router.py` gates assistant-initiated activation
  and exposes `runtime_posture`
- `src/seedcore/ops/pkg/manager.py` persists active manifest posture, including
  `requires_signed_bundle=false` for the current shadow-only RCT manifest

## Decision

For general people, SeedCore should provide an AI assistant as a **policy coach + simulator**, not as a direct policy authority and not as a raw rule editor.

The assistant should:

- translate plain-language goals into typed policy fields
- run deterministic preflight and scenario simulation before any write
- explain outcomes in simple language with facts vs inferences separated
- require explicit human confirmation before policies are persisted or promoted

The assistant should not:

- mint authority on its own
- bypass SeedCore PDP or execution-token gates
- expose raw PKG rule authoring as the primary interface for non-expert users
- claim "absolute freeze certainty" until signed-bundle and replay hardening are default-on

## Why This Fits The Current Codebase

The code already supports two policy planes:

1. **Owner-level trust policy**
   Stored and enforced through identity/delegation/trust-preference APIs.
   Current concrete fields already include:
   - `max_risk_score`
   - `merchant_allowlist`
   - `required_provenance_level`
   - `required_evidence_modalities`
   - `high_value_step_up_threshold_usd`

2. **Authorization PKG policy**
   Stored as runtime snapshots, compiled artifacts, manifests, and checksum-validated activation material.

That split is good. It suggests a clean product shape:

- `SeedCore` remains the deterministic runtime and source of truth
- `pkg-simulator` becomes the human-facing workbench for drafting, testing, and comparing policy outcomes
- the AI assistant lives in the authoring/explanation lane, not the final authorization lane

This aligns with:

- `src/seedcore/api/routers/identity_router.py`
- `src/seedcore/coordinator/core/governance.py`
- `src/seedcore/plugin/mcp_server.py`
- `../pkg-simulator/docs/SEEDCORE_PHASE0_SCOPE.md`
- `../pkg-simulator/docs/SEEDCORE_PHASE1_SCHEMA.md`

## Product Recommendation

### 1. Give general users a guided policy setup flow, not PolicyStudio forms

Today, `../pkg-simulator/pages/PolicyStudio.tsx` is rule-centric. That is too low-level for normal people.

For general users, the assistant UX should ask for plain-language inputs such as:

- what kinds of actions the assistant may do
- what spending level is okay
- which merchants or channels are trusted
- when human approval is required
- what evidence is mandatory before high-risk actions
- what should always be blocked

The assistant then converts those answers into typed policy data, not free-form prose.

### 2. Make the assistant produce drafts in two layers

For accuracy and safety, the assistant should draft:

- **Layer A: owner trust preferences**
  Use the existing SeedCore trust-preference surface now.

- **Layer B: explicit owner policy draft**
  Add a higher-level typed policy contract for budgets, categories, channels, approval chains, and delegated assistants.

The current trust-preference shape is useful, but too small to be the full general-user policy model. The Phase 1 schema proposal in `pkg-simulator` is the right next step.

### 3. Make simulation mandatory before policy save/promotion

The assistant should never say "your policy is good" based only on draft generation.

It should always run:

- owner-context preflight
- governed action preflight
- scenario pack evaluation
- snapshot-vs-snapshot compare when PKG behavior changes are involved

This is how the assistant becomes accurate and effective instead of merely fluent.

### 4. Reuse SeedCore's read-only copilot pattern for explanations

SeedCore already has the right explanation posture in the operator copilot work:

- one-line summary
- short bullets
- explicit facts
- explicit inferences
- citations to concrete fields

That same pattern should power policy explanations for general users. The explanation layer should stay read-only and evidence-bound even if the drafting layer is LLM-assisted.

## Recommended Architecture Split

### SeedCore responsibilities

- store owner identity, delegation, creator profile, and trust preferences
- evaluate preflight and final runtime decisions deterministically
- return deny codes, trust gaps, obligations, and approval requirements
- remain the only system that can mint execution authority
- expose stable references for replay, versioning, and audit

### pkg-simulator responsibilities

- host the conversational policy assistant UX
- collect plain-language user goals
- turn those goals into typed draft policies
- run what-if scenarios and compare outcomes across snapshots
- show side-by-side baseline vs candidate behavior before activation

### Assistant responsibilities

- draft
- simulate
- explain
- recommend

The assistant does **not** authorize.

## The Right User Flow

For general people, the best flow is:

1. **Intent capture**
   "What should the assistant be allowed to do for you?"

2. **Policy translation**
   Convert that into typed fields such as risk thresholds, merchant rules, evidence requirements, budgets, channel permissions, and approval chains.

3. **Scenario testing**
   Run representative scenarios:
   - safe/normal cases
   - borderline cases
   - obviously risky cases
   - missing-evidence cases

4. **Outcome explanation**
   Show:
   - what would be allowed
   - what would be blocked
   - what would escalate to approval
   - which policy field caused each result

5. **Human confirmation**
   Only after simulation review should the draft be written to SeedCore or promoted into PKG-related artifacts.

## Immediate Build Recommendation

Build the first version as a **General Policy Setup Assistant** on top of existing SeedCore surfaces, without waiting for full PKG freeze hardening.

### Phase 1

Ship a user-facing assistant that:

- writes current trust preferences
- calls `seedcore.owner_context.preflight`
- calls `seedcore.agent_action.preflight`
- tests a small curated scenario pack
- explains trust gaps and deny reasons in plain language

This can already help people set safer and more effective policy defaults.

### Phase 2

Add a first-class `OwnerPolicy` contract with typed fields for:

- categories
- budgets and limits
- merchant and marketplace trust rules
- publishing/channel authority
- approval chains
- delegated assistant permissions

This is the point where the assistant becomes broadly useful for general consumer and creator workflows.

### Phase 3

Promote PKG freeze claims only after default runtime hardening includes:

- signed-bundle enforcement
- compare-driven promotion discipline
- stricter replay verification enabled by default
- stronger manifest validation on activation

Until then, the assistant should describe outcomes as:

- simulated
- preflighted
- policy-checked

not as absolutely frozen or irreversible.

## What Not To Do

- Do not ship raw rule authoring as the main consumer policy UX.
- Do not let the assistant directly edit active runtime policy without simulation and confirmation.
- Do not mix "help me decide my policy" with "final runtime authority" into one opaque LLM action.
- Do not market current PKG behavior as full freeze certainty while `requires_signed_bundle` and strict replay controls remain optional.

## Bottom Line

The best decision is:

**Use SeedCore as the deterministic enforcement and proof layer, use `pkg-simulator` as the policy workbench, and position the AI assistant as an advisory drafting/simulation layer for humans.**

That gives general users something they can actually use:

- simple inputs
- typed policy outputs
- scenario-backed validation
- readable explanations
- explicit human control over final policy changes

It also fits the architecture that already exists, instead of fighting it.
