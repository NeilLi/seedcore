# SeedCore Project Stage Milestone Summary

Date: 2026-03-27

## Purpose

This document summarizes SeedCore's stage milestones based on a serious
repository-level review of the codebase as it exists today.

It is not a marketing roadmap.

It is intended to answer a more practical question:

> What stages has SeedCore actually passed, what stages are partially real, and
> what stages still remain open before the core trust-runtime story is truly
> finished?

The summary below is grounded in the current repository structure, runtime
entrypoints, API surfaces, test suite, local deploy tooling, Rust workspace,
TypeScript trust surfaces, and the active roadmap documents.

## Review Basis

This summary is based on direct review of the following repo areas:

- root architecture and positioning in `README.md`
- active roadmap and execution-spine docs under `docs/development/`
- Python runtime entrypoints and router registry under `src/seedcore/`
- PKG, replay, custody, and evidence paths under `src/seedcore/ops/` and
  `src/seedcore/api/routers/`
- Rust workspace layout and transfer fixtures under `rust/`
- TypeScript verification, proof, and operator surfaces under `ts/`
- local runtime/deploy scripts under `deploy/local/`
- verification and regression harnesses under `tests/` and `scripts/host/`

This was a broad architecture and implementation review.
It was not a line-by-line audit of every file in the repository.

## Current Project Shape

SeedCore is best understood today as a three-layer system:

1. Python runtime and orchestration plane
2. Rust proof/kernel direction for deterministic authority-bearing artifacts
3. TypeScript verification and product surfaces

That split is not accidental.
It is explicitly described in
[language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md)
and already reflected in the repo layout:

- Python runtime: [src/seedcore](/Users/ningli/project/seedcore/src/seedcore)
- Rust kernel workspace: [rust](/Users/ningli/project/seedcore/rust)
- TypeScript trust/product workspace: [ts](/Users/ningli/project/seedcore/ts)

The project is no longer just a cognitive-agent architecture.
It is actively being refocused into a governed execution and verification
runtime, anchored to the [North Star: Autonomous Trade Environment](north_star_autonomous_trade_environment.md).
The current focus is on one must-win workflow:

- `Restricted Custody Transfer`

That execution lock is defined in
[killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
and reinforced in
[current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md).

## Milestone Summary

### Stage 0: Cognitive Runtime and Agent Substrate

Status: established baseline

What this stage achieved:

- a substantial Python runtime for task ingestion, routing, control loops,
  agent behaviors, memory, ML, digital twin support, and service orchestration
- a real FastAPI entrypoint with router registration, DB initialization, and
  PKG manager bootstrap in
  [main.py](/Users/ningli/project/seedcore/src/seedcore/main.py)
- broad subsystem coverage across:
  - agents
  - cognitive
  - coordinator
  - dispatcher
  - hal
  - memory
  - services
  - monitoring

Why it matters:

- this is the substrate that made SeedCore more than a design memo
- it gave the project a real execution environment and developer runtime

What it did not yet solve by itself:

- deterministic authority
- strict proof semantics
- public trust visibility

Interpretation:

This stage is the architectural foundation.
It is necessary, but it is not the differentiating product milestone.

### Stage 1: Zero-Trust Execution Boundary

Status: materially implemented

What this stage achieved:

- `ActionIntent` as the accountable authorization request in
  [action_intent.py](/Users/ningli/project/seedcore/src/seedcore/models/action_intent.py)
- short-lived execution tokens and deny-by-default policy gating
- HAL-side token validation, revocation, and emergency cutoff controls
- evidence bundles and transition receipts for custody-bearing execution
- signed-intent support, DID/delegation handling, and external authority checks
- replay-ready governance audit records and receipt linkage

Repo evidence:

- [README.md](/Users/ningli/project/seedcore/README.md)
- [evidence_bundle.py](/Users/ningli/project/seedcore/src/seedcore/models/evidence_bundle.py)
- [governance_audit.py](/Users/ningli/project/seedcore/src/seedcore/models/governance_audit.py)
- [test_external_surface_verification.py](/Users/ningli/project/seedcore/tests/test_external_surface_verification.py)
- [test_transition_receipts.py](/Users/ningli/project/seedcore/tests/test_transition_receipts.py)
- [test_evidence_signing_verification.py](/Users/ningli/project/seedcore/tests/test_evidence_signing_verification.py)

Why it matters:

- this is the point where SeedCore stopped being "AI orchestration with policy
  language" and became a governed execution runtime
- the core trust rule became clear:
  AI may advise, but the runtime decides and evidence closes the loop

Interpretation:

This is one of SeedCore's most meaningful completed milestones.
It is the first place where the repo has a hard product thesis rather than just
technical ambition.

### Stage 2: Policy Knowledge Graph and Deterministic Policy Layer

Status: implemented and still maturing

What this stage achieved:

- PKG manager bootstrap inside API startup
- evaluator reload and snapshot activation APIs
- OTA policy distribution surfaces
- compiled authorization-graph path and status endpoint
- explanation-oriented decision output such as matched policy refs, missing
  prerequisites, and trust gaps
- growing test coverage around graph projection, compilation, manager behavior,
  parity, and router surfaces

Repo evidence:

- [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py)
- [src/seedcore/ops/pkg](/Users/ningli/project/seedcore/src/seedcore/ops/pkg)
- [test_pkg_authz_graph.py](/Users/ningli/project/seedcore/tests/test_pkg_authz_graph.py)
- [test_pkg_authz_graph_manager.py](/Users/ningli/project/seedcore/tests/test_pkg_authz_graph_manager.py)
- [test_authz_parity_service.py](/Users/ningli/project/seedcore/tests/test_authz_parity_service.py)
- [pdp_authz_graph_staging_rollout.md](/Users/ningli/project/seedcore/docs/development/pdp_authz_graph_staging_rollout.md)

Why it matters:

- this is the control-plane heart of SeedCore's policy story
- it moves policy from prompt guidance toward explicit runtime evaluation

What is still open:

- stronger closure on bounded latency and production hot-path discipline
- clearer separation between synchronous decision inputs and broader enrichment
- operational SLO proof for the compiled decision path

Interpretation:

This stage is real and important, but it is not "finished" in the product
sense yet.
It is better described as an operational policy engine in late hardening.

### Stage 3: Replay, Trust Page, and Verifiable External Surface

Status: materially implemented

What this stage achieved:

- replay APIs
- trust-page publishing
- public verification endpoints
- artifact projection for audit, token, subject, and public-id lookup paths
- end-to-end tests showing policy, execution, evidence, and trust-page
  continuity

Repo evidence:

- [replay_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/replay_router.py)
- [test_replay_router.py](/Users/ningli/project/seedcore/tests/test_replay_router.py)
- [test_end_to_end_product_verification.py](/Users/ningli/project/seedcore/tests/test_end_to_end_product_verification.py)
- [verify_end_to_end_product.sh](/Users/ningli/project/seedcore/scripts/host/verify_end_to_end_product.sh)

Why it matters:

- this is where SeedCore starts to become inspectable by someone other than the
  runtime itself
- it converts internal governance artifacts into an externally legible trust
  story

Interpretation:

This is another meaningful milestone because it gives SeedCore a visible proof
surface, not just internal correctness claims.

### Stage 4: Contract Freeze for the Must-Win Workflow

Status: done as architecture and program control

What this stage achieved:

- one canonical workflow lock:
  `Restricted Custody Transfer`
- one authoritative artifact chain from `TaskPayload` to verification surface
- one shared truth table for `allow | deny | quarantine | escalate`
- one machine-checkable phase-0 contract freeze gate

Repo evidence:

- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [phase0_contract_freeze_manifest.json](/Users/ningli/project/seedcore/docs/development/phase0_contract_freeze_manifest.json)
- [verify_phase0_contract_freeze.py](/Users/ningli/project/seedcore/scripts/tools/verify_phase0_contract_freeze.py)
- [test_phase0_contract_freeze.py](/Users/ningli/project/seedcore/tests/test_phase0_contract_freeze.py)

Why it matters:

- it prevents SeedCore from diffusing into a broad and vague trust platform
- it gives Python, Rust, and TypeScript one shared execution spine

Interpretation:

This is not a user-facing milestone, but it is one of the most important
governance milestones inside the repo.
It sharply improves implementation discipline.

### Stage 5: Phase A Trust Hardening

Status: significant checkpoint crossed, not fully finished

What this stage achieved:

- signer-provider abstractions
- hardened restricted-custody signing mode
- TPM-oriented strict attestation fixture path
- offline verification with artifact plus trust bundle
- optional transparency anchoring path for high-value receipts

Repo evidence:

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [tpm_fleet_rollout_runbook.md](/Users/ningli/project/seedcore/docs/development/tpm_fleet_rollout_runbook.md)
- [rust/fixtures/receipts](/Users/ningli/project/seedcore/rust/fixtures/receipts)
- [verify_evidence_signing.sh](/Users/ningli/project/seedcore/scripts/host/verify_evidence_signing.sh)
- [verify_zero_trust_pdp_contract.sh](/Users/ningli/project/seedcore/scripts/host/verify_zero_trust_pdp_contract.sh)

Why it matters:

- this is the stage that turns trust from a runtime claim into something closer
  to cryptographic evidence

What is still open:

- fleet rollout maturity
- operational signer drills
- stronger production closure beyond fixtures, local verification, and
  controlled paths

Interpretation:

Phase A is meaningfully real.
It should be described as trust hardening with a strong checkpoint passed,
rather than as a universally complete hardware trust program.

### Stage 6: Phase B Multi-Party Governance

Status: contractually framed, partially represented, not yet fully closed

What this stage achieved:

- clear `TransferApprovalEnvelope` design direction
- explicit dual-approval and break-glass scenarios in the roadmap and fixtures
- approval-oriented kernel direction in the Rust workspace plan
- Phase D UI/API work shaped around approval state and prerequisite state

Repo evidence:

- [next_killer_demo_contract_freeze.md](/Users/ningli/project/seedcore/docs/development/next_killer_demo_contract_freeze.md)
- [rust/fixtures/transfers/escalate_break_glass](/Users/ningli/project/seedcore/rust/fixtures/transfers/escalate_break_glass)
- [rust/fixtures/transfers/deny_missing_approval](/Users/ningli/project/seedcore/rust/fixtures/transfers/deny_missing_approval)
- [rust/fixtures/approval_envelopes](/Users/ningli/project/seedcore/rust/fixtures/approval_envelopes)

Why it matters:

- multi-party approval is central to the high-trust supply-chain wedge
- without it, SeedCore remains closer to a single-boundary authorization engine

What is still open:

- fully authoritative runtime approval lifecycle closure
- production-grade co-sign or dual-approval flow end to end
- stronger evidence of approval state transitions beyond contract framing and
  fixture scenarios

Interpretation:

Phase B is not vapor.
But it is still better described as "structured and partially implemented"
than "done."

### Stage 7: Phase C Operational Decision Engine and Asset-Centric Hot Path

Status: started with real implementation, still early

What this stage achieved:

- authz-graph status and refresh surfaces
- explicit hot-path discussion in the roadmap
- a new typed hot-path PDP endpoint:
  `POST /api/v1/pdp/hot-path/evaluate`
- deterministic fail-closed rules for:
  - graph not ready
  - snapshot mismatch
  - stale telemetry
  - asset custody mismatch

Repo evidence:

- [asset_centric_pdp_hot_path_contract.md](/Users/ningli/project/seedcore/docs/development/asset_centric_pdp_hot_path_contract.md)
- [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/models/pdp_hot_path.py)
- [pdp_hot_path.py](/Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py)
- [pkg_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/pkg_router.py)
- [test_pdp_hot_path_router.py](/Users/ningli/project/seedcore/tests/test_pdp_hot_path_router.py)

Why it matters:

- this is the stage that can make SeedCore fast, predictable, and operationally
  credible under real workflow pressure

What is still open:

- benchmark-driven latency closure
- parity proof versus broader evaluation paths
- stronger runtime observability tied to decision SLOs
- true production confidence that the hot path is the canonical path

Interpretation:

This is an important start, but still an early milestone.
The API and evaluator scaffold are meaningful because they create a real
boundary to harden, measure, and iterate.

### Stage 8: Phase D Verification Product Surface

Status: advanced and increasingly concrete

What this stage achieved:

- TypeScript verification API as a BFF layer
- narrow public proof surface
- operator console with status and forensic views
- stable verification contracts in the TS workspace
- fixture-backed and runtime-backed Phase D adapter shape
- business-readable state translation
- product verification protocol for sign-off

Repo evidence:

- [ts/services/verification-api/src/server.ts](/Users/ningli/project/seedcore/ts/services/verification-api/src/server.ts)
- [ts/services/verification-api/src/transferSources.ts](/Users/ningli/project/seedcore/ts/services/verification-api/src/transferSources.ts)
- [ts/packages/contracts/src/trustContracts.ts](/Users/ningli/project/seedcore/ts/packages/contracts/src/trustContracts.ts)
- [ts/apps/operator-console/src/ui.ts](/Users/ningli/project/seedcore/ts/apps/operator-console/src/ui.ts)
- [ts/apps/proof-surface/src/server.ts](/Users/ningli/project/seedcore/ts/apps/proof-surface/src/server.ts)
- [productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
- [verify_productized_surface.sh](/Users/ningli/project/seedcore/scripts/host/verify_productized_surface.sh)

Why it matters:

- this is the stage where SeedCore stops looking like invisible infrastructure
  and starts looking like a trust product

What is still open:

- stronger production access control for partner-visible surfaces
- sharper runtime parity across all workflow cases
- tighter linkage between cryptographic receipt validation and operator-visible
  product UX

Interpretation:

Phase D is one of the clearest recent advances in the repo.
It is no longer just a plan.
It already exists as product-facing software, even though the final trust story
still needs further hardening.

### Stage 9: Rust Proof and Verification Kernel Direction

Status: scaffolded direction, partial implementation through fixtures and CLI

What this stage achieved:

- a real Rust workspace with kernel crate boundaries
- deterministic transfer fixtures
- an offline verifier direction via `seedcore-verify`
- a multi-language boundary plan that keeps Rust focused on authority-bearing
  kernels

Repo evidence:

- [rust/Cargo.toml](/Users/ningli/project/seedcore/rust/Cargo.toml)
- [rust/README.md](/Users/ningli/project/seedcore/rust/README.md)
- [rust_workspace_proposal.md](/Users/ningli/project/seedcore/docs/development/rust_workspace_proposal.md)
- [language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md)

Why it matters:

- it shows that SeedCore has an intentional path for moving its strictest logic
  out of the dynamic runtime over time

Interpretation:

This is strategically important, but it is not yet the center of present-day
runtime behavior.
The Rust story is real, but still in transition from scaffold to kernel.

### Stage 10: External Tool Boundary Standardization on MCP

Status: done for the intended scope

What this stage achieved:

- MCP client and service boundary
- JSON-RPC tool lifecycle compliance
- safe-first exposed tool surface
- adapter-boundary discipline through `ToolManager`

Repo evidence:

- [protocol_adoption_2026.md](/Users/ningli/project/seedcore/docs/architecture/overview/protocol_adoption_2026.md)

Why it matters:

- it tightens the external tool boundary without forcing a large internal
  rewrite

Interpretation:

This is a meaningful infrastructure milestone, but it is secondary to the
Restricted Custody Transfer trust wedge.

### Stage 11: Robotics and VLA Optimization Track

Status: sidecar innovation track, not the current trust-runtime center

What this stage achieved:

- VLA safety and robotics-oriented planning in the docs
- updated safety-guard and simulation-validation direction

Repo evidence:

- [vla_2026_optimizations.md](/Users/ningli/project/seedcore/docs/development/vla_2026_optimizations.md)

Why it matters:

- it shows SeedCore still has a robotics and embodied-AI trajectory

Interpretation:

This is valuable, but it should currently be treated as a parallel innovation
track rather than the project's primary milestone ladder.
The core product story today is governed execution and verification.

## What SeedCore Has Actually Proven So Far

The strongest completed proof points in the current repo are:

- a real zero-trust execution boundary
- policy-first routing and evaluation
- replay and trust-page verification surfaces
- a disciplined contract freeze around one canonical workflow
- growing Phase D operator and partner-facing trust product surfaces

Those are the most meaningful milestones because they support the project's
main thesis directly.

## What Is Most Credible To Say About The Current Stage

The most accurate single-sentence summary is:

> SeedCore has moved beyond a cognitive-agent architecture and is now a
> functioning governed-execution runtime with real replay, proof, and
> verification surfaces, centered on a Restricted Custody Transfer wedge that
> is partially hardened and increasingly productized.

That is stronger and more credible than calling the system complete.

## Milestone Status Table

| Stage | Status | Short reading |
| :--- | :--- | :--- |
| Stage 0: Cognitive runtime substrate | Established | Broad runtime foundation exists |
| Stage 1: Zero-trust execution boundary | Implemented | One of the strongest completed milestones |
| Stage 2: PKG policy layer | Implemented, maturing | Real engine, still being hardened |
| Stage 3: Replay and trust surface | Implemented | External proof story is real |
| Stage 4: Contract freeze for RCT wedge | Done | Strong program control milestone |
| Stage 5: Trust hardening | Checkpoint crossed | Real progress, not universal closure |
| Stage 6: Multi-party governance | Partial | Structured and credible, not fully closed |
| Stage 7: Asset-centric hot path | Early | Real boundary created, needs operational proof |
| Stage 8: Verification product surface | Advanced | One of the clearest recent wins |
| Stage 9: Rust proof kernel direction | Scaffolded | Strategic path more than current center |
| Stage 10: MCP external boundary | Done | Good platform hygiene milestone |
| Stage 11: VLA/robotics optimization | Sidecar | Important, but not the core wedge |

## Recommended Executive Framing

If SeedCore needs a concise milestone narrative for internal planning, partner
discussion, or future docs, the best framing is:

1. Foundation built:
   the runtime, agent substrate, policy boundary, and evidence model exist.
2. Trust boundary proven:
   execution tokens, receipts, replay, trust pages, and verification flows are
   real.
3. Canonical wedge frozen:
   Restricted Custody Transfer is now the program center of gravity.
4. Productization underway:
   operator status, forensic views, and proof surfaces are already in repo.
5. Closure still required:
   hot-path performance, multi-party approval closure, and stronger trust
   hardening remain the next decisive milestones.

## Best Next Milestones To Close

If the project wants the cleanest next milestone sequence, the most valuable
closure points are:

1. Make Restricted Custody Transfer fully dual-approved and operationally
   undeniable end to end.
2. Prove the asset-centric PDP hot path under benchmarked latency and fail-safe
   conditions.
3. Tighten Phase D so operator, partner, and offline cryptographic
   verification tell the same trust story without gaps.

That sequence would make the current SeedCore story much easier to defend to a
serious external evaluator.
