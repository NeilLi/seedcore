# PolicyGraph Builder Implementation Plan

Date: 2026-05-15  
Status: Technical memo / implementation plan

## Purpose

SeedCore already defines and enforces a narrow execution boundary for
high-consequence autonomous actions. The next commercial question is how
customers define that boundary precisely enough for SeedCore to enforce it.

This memo proposes **SeedCore PolicyGraph Builder**: a policy-construction
system that helps customers turn operational rules into executable, testable,
and replayable authority boundaries.

The product framing:

```text
SeedCore helps customers construct the policy graph that defines execution
authority.
```

The technical framing:

```text
SeedCore PolicyGraph Builder compiles customer policy intent into:

- a Policy Knowledge Graph
- PDP-enforceable rule inputs
- authority-token constraints
- evidence requirements
- stable reason codes
- redaction rules
- happy-path and toxic-path fixtures
- replay verifier expectations
```

## Positioning

Agent frameworks help AI decide what to do. Prompt guardrails control what AI
says. SeedCore controls what AI is allowed to execute.

PolicyGraph Builder extends that promise by helping customers define execution
authority in the first place.

The goal is not to ask customers to write policy code from scratch. The goal is
to guide them from vague business rules such as:

```text
Only allow safe transfers.
```

to enforceable policy such as:

```text
A collectible asset transfer is allowed only if:

- the asset has approved source registration
- authentication is fresh within the configured policy window
- buyer delegation is active
- declared value is below approved spend limit or has step-up approval
- origin and destination zones match approved custody scope
- telemetry is signed by an authorized device
- closure evidence binds to the same asset_id and workflow_join_key
```

This is a policy compiler for autonomous execution, not a generic rules editor.

## Current Runtime Context

PolicyGraph Builder should be additive to the existing SeedCore runtime. It
should not replace the current enforcement path.

Existing runtime surfaces that PolicyGraph Builder should compile toward:

- `seedcore.agent_action_gateway.v1`
- PDP / hot-path evaluation
- PKG snapshots and taxonomy material
- short-lived `ExecutionToken` lifecycle
- approval envelopes and delegated authority
- evidence bundles and transition receipts
- signed edge telemetry closure refs
- `RESULT_VERIFIER`
- public proof and operator forensic surfaces

The initial template should target the current product wedge:

```text
High-value collectible transfer / rare-shoe Restricted Custody Transfer
```

## Policy Package Format

PolicyGraph Builder should adopt the useful part of agent-readable Markdown
formats: structured metadata for deterministic tooling plus semantic prose for
reviewers and operators. The SeedCore version should be a **policy package**,
not a hot-path `POLICY.md` that the PDP reads directly at request time.

The machine-readable header is a compile-and-test input. It declares the typed
policy graph, evidence requirements, reason codes, fixtures, redaction rules,
and runbook references that should be compiled into PDP-adjacent artifacts and
replay tests. The Markdown body explains rationale, operator handling, and
customer-facing semantics. The authority-bearing runtime remains the compiled
policy snapshot, PDP evaluation, scoped `ExecutionToken`, evidence closure, and
verifier outcome.

Illustrative package shape:

```yaml
---
policy_package: rare_shoe_rct_v1
status: draft
pdp_contract: seedcore.agent_action_gateway.v1
policy_snapshot_ref: policy_snapshot:rare_shoe_rct:v1
required_context:
  - source_registration
  - buyer_delegation
  - approval_envelope
  - signed_delivery_telemetry
evidence_requirements:
  - id: origin_scan
    signer_profile: enrolled_or_fixture_device
    freshness_sla: policy_defined
    binds:
      - asset_id
      - workflow_join_key
reason_codes:
  - REGISTRATION_NOT_APPROVED
  - TELEMETRY_SIGNATURE_INVALID
  - CROSS_ASSET_REPLAY
runbooks:
  quarantine: result_verifier_quarantine_remediation_runbook.md
fixtures:
  happy_path: rust/fixtures/transfers/allow_case
  toxic_paths:
    - rust/fixtures/transfers/deny_missing_approval
    - rust/fixtures/transfers/quarantine_stale_telemetry
---

## Business Rule

Human-readable policy rationale, approval semantics, exception handling,
operator runbook notes, and fixture expectations live here.
```

Required guardrails:

- a package can propose policy intent, but only compiled snapshots and the PDP
  can admit execution authority;
- front matter values that affect authority must be schema-validated and
  fixture-tested before promotion;
- runbook prose cannot relax a deny, quarantine, revocation, or verifier
  failure;
- missing, ambiguous, or uncompiled package fields fail closed during
  admission testing;
- any generated policy diff must include structured diagnostics and replay
  fixture results before review.

## Customer-Facing Policy Questions

Most customers cannot start with a policy graph. They can answer operational
questions.

PolicyGraph Builder should start with six guided questions:

1. What actions can happen?
2. Who or what is allowed to request, approve, execute, and verify them?
3. Which assets or resources are affected?
4. Under what conditions is the action allowed?
5. What evidence must be collected?
6. What happens if something does not match?

For rare-shoe RCT:

| Question | Example answer |
| --- | --- |
| Actions | register asset, request transfer, mint custody authority, origin scan, delivery scan, close custody |
| Actors | buyer, buyer agent, seller, authenticator, vault operator, courier device, verifier |
| Assets | authenticated collectible shoe |
| Conditions | registration approved, authentication fresh, buyer delegated, order bound to asset |
| Evidence | NFC scan, signed telemetry, condition image, handoff proof |
| Failure outcomes | deny, quarantine, operator review, security event, authority revocation |

## Policy Precision Ladder

SeedCore should help customers mature policies through five levels.

| Level | Shape | Runtime value |
| --- | --- | --- |
| 1. Natural-language policy | "Only allow authenticated shoes to be transferred by approved couriers." | Useful for discussion, not enforceable |
| 2. Structured checklist | authentication approved, courier approved, asset not quarantined, scan evidence required | Better, still incomplete |
| 3. Typed policy rule | `ALLOW CUSTODY_TRANSFER IF ...` | Enforceable |
| 4. Policy graph | `Actor -> Delegation -> ActionIntent -> Asset -> EvidenceRequirement -> AuthorityToken -> VerifierOutcome` | Explainable and maintainable |
| 5. Replay-tested policy | happy and toxic fixtures validate the policy | Commercially valuable |

SeedCore should sell Level 5: policy correctness under adversarial cases.

## Policy Knowledge Graph

A flat rules file becomes hard to maintain. SeedCore should model execution
authority as a graph of actors, assets, actions, evidence, and outcomes.

### Minimal Node Types

- `Actor`
- `Role`
- `Delegation`
- `ActionIntent`
- `Asset`
- `AssetState`
- `PolicyRule`
- `PolicySnapshot`
- `AuthorityToken`
- `Device`
- `Zone`
- `EvidenceRequirement`
- `TelemetryEvent`
- `ApprovalEnvelope`
- `VerifierOutcome`
- `RiskFlag`
- `ExceptionRunbook`

### Minimal Edge Types

- `Actor HAS_ROLE Role`
- `Actor HAS_DELEGATION Delegation`
- `Delegation AUTHORIZES ActionIntent`
- `ActionIntent TARGETS Asset`
- `Asset HAS_STATE AssetState`
- `Asset LOCATED_IN Zone`
- `ActionIntent REQUIRES EvidenceRequirement`
- `Device AUTHORIZED_FOR Zone`
- `Device SIGNS TelemetryEvent`
- `TelemetryEvent BINDS_TO Asset`
- `PolicyRule EVALUATES ActionIntent`
- `PolicySnapshot CONTAINS PolicyRule`
- `AuthorityToken GRANTS ActionIntent`
- `VerifierOutcome VALIDATES EvidenceRequirement`
- `RiskFlag BLOCKS ActionIntent`
- `ExceptionRunbook HANDLES RiskFlag`

### Example Explainable Denial

Instead of only returning:

```text
Denied.
```

SeedCore should explain:

```text
Denied: CROSS_ASSET_REPLAY

quote_ref quote:883 is bound to asset:shoe:A.
delivery telemetry binds to asset:shoe:B.
Policy rule rare_shoe_rct.asset_binding.v1 blocks closure.
Outcome: deny + verifier quarantine.
```

## Product Workflow

### Step 1: Choose a Policy Template

The customer should not start from a blank page.

Initial template library:

- high-value collectible transfer
- warehouse robotics handoff
- industrial part custody
- lab sample transfer
- luxury goods authentication
- autonomous procurement
- restricted API execution

For the MVP, only implement:

```text
high_value_collectible_transfer / rare_shoe_rct_v1
```

The rare-shoe template should preload:

- seller
- buyer
- buyer agent
- authenticator
- vault operator
- courier
- NFC or scan device
- verifier
- asset registration
- authentication freshness
- condition grade
- origin scan
- delivery scan
- quarantine path
- public/operator proof redaction defaults

### Step 2: Define Assets And States

Guided questions:

```text
What assets are controlled?
What states can they be in?
Which states allow execution?
Which states block execution?
```

Rare-shoe example:

Allowed states:

- `AUTHENTICATED_REGISTERED`
- `VAULTED_SECURE`

Blocked states:

- `REGISTRATION_PENDING`
- `QUARANTINED_ANOMALY`
- `ISOLATED_SECURITY_EVENT`
- `DISPUTED`
- `STOLEN`
- `LOCKED`

### Step 3: Define Actions

Guided questions:

```text
What actions can users, agents, devices, or verifiers request?
```

Rare-shoe MVP actions:

- `REGISTER_ASSET`
- `REQUEST_TRANSFER`
- `MINT_CUSTODY_AUTHORITY`
- `ORIGIN_SCAN`
- `DELIVERY_SCAN`
- `CLOSE_CUSTODY`
- `QUARANTINE_ASSET`
- `REVOKE_AUTHORITY`

Each action should declare:

- required actor
- required asset state
- required evidence
- allowed scope
- possible outcomes
- stable reason codes

### Step 4: Define Authority

SeedCore should force customers to separate four powers:

- request
- approve
- execute
- verify

Rare-shoe example:

| Role | Authority |
| --- | --- |
| Buyer agent | can request transfer |
| Buyer | can approve spend |
| Vault operator | can release asset |
| Courier device | can execute scan |
| SeedCore verifier | can close or quarantine |

This avoids ambient-authority drift: an authenticated actor is not automatically
authorized to execute.

### Step 5: Define Evidence Requirements

Policy authoring should be evidence-first.

Guided question:

```text
What would prove this action was legitimate?
```

Rare-shoe transfer evidence:

- approved source registration
- authentication packet and freshness timestamp
- origin NFC or scan event
- delivery NFC or scan event
- signed device telemetry
- condition image or image hash
- seal or tamper state
- timestamp
- zone match
- asset binding to `asset_id`
- workflow binding to `workflow_join_key`

Each evidence requirement should specify:

- issuer
- format
- freshness window
- signature requirement
- asset binding fields
- redaction level
- verification method
- failure reason code

### Step 6: Define Toxic Paths

Customers often over-specify happy paths and under-specify failures. SeedCore
should make toxic-path design mandatory.

Rare-shoe toxic paths:

- registration not approved
- authentication stale
- buyer delegation missing
- approval envelope invalid
- declared value requires step-up approval
- hardware anchor mismatch
- dynamic NFC proof invalid
- telemetry stale
- telemetry signature invalid
- cross-asset replay
- condition drift
- public proof redaction required

Each toxic path maps to:

- `deny`
- `quarantine`
- `escalate`
- `review_required`
- security isolation
- authority revocation

## Policy Libraries

To make policy construction efficient, SeedCore should provide reusable
primitive libraries.

### Actor Library

- buyer
- seller
- agent
- operator
- courier
- device
- authenticator
- verifier
- admin
- auditor

### Action Library

- register
- request
- approve
- mint authority
- handoff
- scan
- deliver
- close
- quarantine
- revoke

### Evidence Library

- signature
- timestamp
- location
- NFC scan
- image hash
- weight check
- condition grade
- approval envelope
- authenticator verdict
- order binding

### Toxic-Path Library

- stale evidence
- wrong asset
- expired authority
- revoked signer
- condition drift
- tamper detected
- missing approval
- cross-asset replay

## Precision Requirements

Efficiency is not enough. SeedCore policy construction must be precise.

PolicyGraph Builder should require:

- typed fields
- explicit state machines
- stable reason codes
- policy snapshots
- deterministic evaluation
- fixture tests
- redaction rules
- authority windows
- asset binding
- signature validation
- replay expectations

The most important precision rule:

```text
Every policy rule should produce a stable reason code.
```

Rare-shoe reason-code examples:

- `REGISTRATION_NOT_APPROVED`
- `AUTHENTICATION_STALE`
- `AUTHENTICATION_VERDICT_INVALID`
- `BUYER_DELEGATION_MISSING`
- `VALUE_STEP_UP_REQUIRED`
- `HARDWARE_ANCHOR_MISMATCH`
- `DYNAMIC_NFC_PROOF_INVALID`
- `TELEMETRY_SIGNATURE_INVALID`
- `CROSS_ASSET_REPLAY`
- `CONDITION_DRIFT_DETECTED`

## Correct Implementation Placement

The correct placement is split across the existing SeedCore / `pkg-simulator`
boundary.

Do **not** create a second policy runtime or a separate simulator inside
SeedCore. The repository already has three relevant surfaces:

- `pkg-simulator` is the human-facing policy workbench for drafting, scenario
  design, and comparing policy outcomes.
- `src/seedcore/api/routers/policy_assistant_router.py` already exposes
  scenario-pack preflight over existing `agent-actions/evaluate` with
  `no_execute=true`.
- `src/seedcore/ops/pkg/authz_graph/` already owns the runtime authorization
  graph ontology, projection, compiled index, and graph manager.

PolicyGraph Builder should therefore be implemented as a **workbench plus
compiler lane**:

```text
pkg-simulator
  owns customer-facing authoring, guided questions, visual graph editing,
  scenario-pack UX, and draft review.

SeedCore API
  owns canonical typed contracts, deterministic validation, preflight,
  compilation outputs, snapshot publication, and reason-code semantics.

SeedCore PKG / authz_graph
  owns compiled authorization graph semantics and runtime evaluation inputs.

Agent Action Gateway / PDP / RESULT_VERIFIER
  remain the only runtime execution authority path.
```

### pkg-simulator Placement

Use `pkg-simulator` for the interactive PolicyGraph Builder product:

```text
/Users/ningli/project/pkg-simulator/pages/
  PolicyAssistantPage.tsx          # guided policy workflow already exists
  PolicyStudio.tsx                 # advanced snapshot/rule authoring
  SandboxSimulator.tsx             # scenario/testing surface

/Users/ningli/project/pkg-simulator/components/policy-assistant/
  PolicyIntentStep.tsx
  PolicyDraftStep.tsx
  PreflightStep.tsx
  ScenarioPackStep.tsx
  ReviewCommitStep.tsx

/Users/ningli/project/pkg-simulator/services/
  policyAssistantService.ts        # draft assembly, scenario-pack generation
  seedcoreService.ts               # calls SeedCore API
  snapshotService.ts               # snapshot lifecycle UI

/Users/ningli/project/pkg-simulator/types/
  policyAssistant.ts               # UI/session policy draft types
```

Near-term `pkg-simulator` additions for PolicyGraph Builder:

- add `PolicyGraphTemplate` and `PolicyGraphDraft` UI types
- add rare-shoe RCT template selection
- add actor/action/asset/evidence wizard panels
- add graph visualization over compiled `AuthzGraphSnapshot`-shaped output
- add scenario-pack generation for rare-shoe happy/toxic paths
- call SeedCore for validation, preflight, compile/dry-run, and compare

### SeedCore Placement

Use SeedCore for canonical contracts and deterministic backend work:

```text
src/seedcore/models/
  policy_graph_builder.py          # Pydantic contracts for template/draft/compile reports

src/seedcore/api/routers/
  policy_assistant_router.py       # extend existing route rather than creating a new router

src/seedcore/ops/pkg/authz_graph/
  ontology.py                      # existing graph node/edge model
  manifest.py                      # existing policy-authored edge manifests
  projector.py                     # graph projection
  compiler.py                      # compiled authz index and transition checks

src/seedcore/ops/pkg/
  compare_service.py               # existing snapshot-vs-snapshot simulator support
  compiler_service.py              # existing rules -> Rego/WASM pipeline

tests/fixtures/policy_graph/
  templates/rare_shoe_rct_v1.json
  cases/rare_shoe_happy_path.json
  cases/rare_shoe_authentication_stale.json
  cases/rare_shoe_cross_asset_replay.json
  cases/rare_shoe_nfc_clone.json

tests/
  test_policy_graph_builder_contracts.py
  test_policy_graph_builder_compile_report.py
  test_policy_graph_builder_scenario_pack.py
```

SeedCore should expose canonical API endpoints by extending
`policy_assistant_router.py`, because this is an advisory / preflight /
simulation lane, not a runtime enforcement router.

## API Placement

Prefer these additive endpoints under the existing policy-assistant namespace:

### Template Listing

```text
GET /api/v1/policy-assistant/policy-graph/templates
GET /api/v1/policy-assistant/policy-graph/templates/{template_id}
```

Returns available templates and their required actors, assets, actions,
evidence, and toxic-path defaults.

### Draft Validation

```text
POST /api/v1/policy-assistant/policy-graph/drafts/validate
```

Takes a client-held draft from `pkg-simulator` and checks:

- missing actor/action/asset definitions
- ambiguous request/approve/execute/verify authority
- missing evidence requirement
- missing reason code
- missing redaction rule
- unhandled toxic path

The MVP does not need SeedCore to persist every intermediate draft. Let
`pkg-simulator` own draft session state until the user explicitly commits or
publishes.

### Compilation / Dry Run

```text
POST /api/v1/policy-assistant/policy-graph/drafts/compile
```

Produces:

- graph nodes and edges compatible with `AuthzGraphSnapshot`
- policy edge manifests compatible with `PolicyEdgeManifest`
- PDP / gateway preflight inputs
- authority-token constraints
- evidence requirements
- reason-code taxonomy
- redaction policy
- simulation expectations
- a build report with blockers and warnings

### Simulation

```text
POST /api/v1/policy-assistant/scenario-pack/evaluate
```

Reuse the existing endpoint for scenario execution. PolicyGraph Builder should
generate richer scenario packs, but the backend evaluation path should remain
the current `no_execute=true` Agent Action Gateway preflight path.

### Snapshot Compare

```text
POST /api/v1/pkg/snapshots/compare
```

Use the existing PKG snapshot compare endpoint for baseline-vs-candidate
behavior drift. This is already explicitly described as a PKG simulator service.

### Publication

```text
POST /api/v1/policy-assistant/policy-graph/drafts/publish-dry-run
```

Creates or returns a candidate dry-run `PolicySnapshot` / graph manifest bundle.
Enforce-mode activation remains separate and must use the existing PKG snapshot
promotion / activation flow.

## Compiler Responsibilities

Example customer rule:

```text
Only trusted couriers can move high-value authenticated shoes.
```

Compiler output:

- graph edges:
  - `Courier HAS_ROLE ApprovedCourier`
  - `Device AUTHORIZED_FOR Zone`
  - `ActionIntent TARGETS Asset`
  - `ActionIntent REQUIRES OriginScan`
  - `ActionIntent REQUIRES DeliveryScan`
- PDP predicates:
  - declared value threshold
  - approved courier membership
  - valid delegation
  - valid approval envelope
  - unblocked asset state
- authority-token constraints:
  - asset id
  - origin zone
  - destination zone
  - authorized device
  - validity window
- evidence requirements:
  - signed origin scan
  - signed delivery scan
  - asset-bound telemetry
- reason codes:
  - `VALUE_STEP_UP_REQUIRED`
  - `COURIER_NOT_AUTHORIZED`
  - `TELEMETRY_SIGNATURE_INVALID`
  - `CROSS_ASSET_REPLAY`
- simulation cases:
  - allowed transfer
  - missing courier approval
  - stale telemetry
  - cross-asset replay

## Rare-Shoe MVP Policy

The first compiled rare-shoe policy should enforce:

1. Source registration is approved.
2. Authentication status is approved.
3. Authentication is fresh.
4. Asset is not quarantined, disputed, stolen, or locked.
5. Buyer or buyer agent has active delegation.
6. Approval envelope is valid.
7. Product, quote, order, and asset binding are consistent.
8. Declared value is within spend policy or has step-up approval.
9. Courier/device is authorized for origin and destination zones.
10. Origin and delivery telemetry are signed.
11. Telemetry binds to the same `asset_id` and `workflow_join_key`.
12. `RESULT_VERIFIER` closes the chain.
13. Public proof redacts raw NFC UID, raw telemetry, and authority-tier details.

## Simulation Cases

Every generated policy should include fixture expectations.

Minimum rare-shoe cases:

| Case | Expected outcome |
| --- | --- |
| happy path | allow and close |
| registration not approved | deny |
| authentication stale | quarantine |
| buyer delegation missing | deny |
| approval envelope invalid | deny |
| high-value step-up required | escalate |
| hardware anchor mismatch | deny |
| dynamic NFC proof invalid | deny |
| telemetry stale | quarantine |
| telemetry signature invalid | deny |
| cross-asset replay | deny |
| condition drift | quarantine |
| public proof redaction required | review required |

## Explainability Output

Every compiled policy should support graph-trace explanations for
`allow`, `deny`, `quarantine`, and `escalate`.

Example:

```json
{
  "decision": "deny",
  "reason_code": "CROSS_ASSET_REPLAY",
  "trace": [
    {
      "node": "quote:shoe-001",
      "edge": "BINDS_TO",
      "target": "asset:shoe:A"
    },
    {
      "node": "telemetry:delivery-001",
      "edge": "BINDS_TO",
      "target": "asset:shoe:B"
    },
    {
      "policy_rule": "rare_shoe_rct.asset_binding.v1",
      "outcome": "blocks_closure"
    }
  ],
  "operator_summary": "Delivery telemetry references a different asset than the approved quote/order binding.",
  "next_action": "quarantine_asset"
}
```

## Delivery Phases

### Phase 1: Schema And Rare-Shoe Template

- Define policy graph models.
- Add rare-shoe RCT template fixture.
- Add stable reason-code taxonomy.
- Add validation for required actors, assets, actions, evidence, and toxic
  paths.

### Phase 2: Draft Builder API

- Add template listing.
- Add draft creation from template.
- Add draft patch/update endpoint.
- Add completeness validation endpoint.

### Phase 3: Compiler

- Compile draft to graph nodes and edges.
- Compile graph to PDP-compatible rule inputs.
- Compile graph to authority-token constraints.
- Compile graph to evidence and redaction requirements.
- Emit a build report with warnings and blockers.

### Phase 4: Simulator

- Generate happy and toxic fixture expectations.
- Run simulation against existing RCT gateway/PDP surfaces where possible.
- Emit coverage report.

### Phase 5: Snapshot Publication

- Produce dry-run `PolicySnapshot`.
- Compare policy versions.
- Integrate with existing PKG snapshot promotion flow for later activation.

### Phase 6: Visualizer And Operator Traces

- Add graph view for customer-facing explanation.
- Add why-allowed / why-denied traces.
- Connect traces to operator proof surfaces.

## Acceptance Criteria

The MVP is credible when a customer can:

- start from the rare-shoe RCT template
- answer guided questions without writing policy code
- generate a typed policy graph
- compile the graph into enforceable runtime constraints
- simulate happy and toxic cases
- see stable reason codes for every failure
- publish a dry-run policy snapshot
- run an Agent Action Gateway request against that snapshot
- inspect a replayable allow/deny/quarantine explanation

## Customer Explanation

Use this wording:

```text
SeedCore helps you turn operational rules into executable policy.

You define:

- who can act
- what they can act on
- when they can act
- what evidence is required
- what should happen when evidence fails

SeedCore converts that into a policy graph, tests it against normal and
adversarial cases, and then enforces it at execution time.
```

Short category statement:

```text
SeedCore turns business rules into executable authority boundaries for
autonomous systems.
```
