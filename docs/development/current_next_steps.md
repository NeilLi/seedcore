# Current Next Steps

This document tracks the next-stage priorities for SeedCore based on the
repository as it exists today.

It is intentionally written to balance two things:

- the strong baseline SeedCore already has
- the practical, wedge-first roadmap needed to make that baseline
  enterprise-credible

The goal is not to describe a perfect future state all at once. The goal is to
define the next 12-18 months in a way that is ambitious, believable, and
product-relevant.

## Zero-Trust RCT Expansion Roadmap

SeedCore is building a trust runtime for AI actions in high-consequence
environments. The next RCT platform expansion should increase autonomous reach
by making the execution boundary narrower, more typed, and more replayable, not
by letting advisory AI inherit authority. The structural rule stays:

```text
AI proposal -> Agent accountability -> PDP admission -> ExecutionToken attempt
-> HAL / actuator action -> receipt -> verifier / replay closure
```

Read the six steps below as the bridge from the four-plane model
(`Intelligence -> Control -> Execution -> Infrastructure`) into the current
workspace. Each step names the existing anchor and the next hardening target.

### Step 1: Formalize `ActionIntent` For Governed RCT Nodes

The expansion boundary begins where untrusted planning is transformed into a
deterministic authorization request.

- **Current anchors:** [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md),
  [`src/seedcore/api/routers/agent_actions_router.py`](../../src/seedcore/api/routers/agent_actions_router.py),
  and [`src/seedcore/models/action_intent.py`](../../src/seedcore/models/action_intent.py).
- **Safety target:** require every governed RCT execution node to carry a typed
  `ActionIntent` with principal/delegation, asset or resource, operation,
  bounded scope, TTL, freshness requirements, and stable request hash.
- **Precision target:** keep provenance adjudication, source registration, and
  advisory planning outside the authority surface until they are converted into
  explicit execution intents or admitted context refs. Do not let a broad
  workflow object become an implicit `ActionIntent`.

### Step 2: Keep The PDP Synchronous, Stateless, And Fail-Closed

The PDP is the safety boundary. It admits or rejects a bounded request against a
pinned policy and context snapshot; it does not perform open-ended agent
reasoning at decision time.

- **Current anchors:** [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md),
  [`policy_gate_matrix.md`](policy_gate_matrix.md), and
  [`src/seedcore/ops/pdp_hot_path.py`](../../src/seedcore/ops/pdp_hot_path.py).
- **Safety target:** fail closed on stale context, missing signed context,
  missing policy snapshot, ambiguous asset state, unknown delegation, or
  unverifiable telemetry preconditions.
- **Precision target:** pass only typed, freshness-aware, policy-admitted fields
  into the authority path. Memory, LLM advice, eval scores, and flywheel feedback
  remain advisory unless transformed into explicit policy inputs.
- **Freshness target:** for causality-sensitive mutations, require a verified
  signed mutation receipt plus `local_view_watermark >= required_watermark`
  before evaluation; barrier timeout, replay, session mismatch, or expired epoch
  returns a fail-closed result and no `ExecutionToken`.

### Step 3: Tokenize The Handoff Before Any Mutation

An allow decision permits only a scoped attempt. It is not settlement, custody
closure, or blanket execution authority.

- **Current anchors:** [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md),
  [`gated_action_dx_layer.md`](gated_action_dx_layer.md), and
  [`src/seedcore/sdk/gated_action.py`](../../src/seedcore/sdk/gated_action.py).
- **Safety target:** mint short-lived `ExecutionToken`s only on admitted allow
  paths; withhold tokens for deny, expired, stale, quarantine, and preflight-only
  paths.
- **Precision target:** bind each token to the exact request hash, policy
  snapshot, execution constraints, endpoint, and payload hash expected by the
  downstream actuator or platform mutation.
- **Operational target:** route RCT mutations through a unified governed
  entrypoint so actuator calls, custody-state writes, NFC scan transitions, and
  settlement updates all reject missing, expired, replayed, or scope-mismatched
  tokens.
- **Receipt target:** upstream governed mutations should return signed receipts
  with monotonic sequence or log-offset bounds so follow-on PDP checks can prove
  read-your-own-writes freshness instead of trusting a client-supplied token.

### Step 4: Make Evidence And Replay The Accountability Plane

Evidence closes the loop. The RCT platform should be able to reconstruct the
governed path without trusting ambient runtime state or operator memory.

- **Current anchors:** [`replay_bundle_transparency_anchoring_design.md`](replay_bundle_transparency_anchoring_design.md),
  [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md),
  and [`src/seedcore/ops/evidence/materializer.py`](../../src/seedcore/ops/evidence/materializer.py).
- **Safety target:** every mutation attempt emits receipt-bound evidence with
  policy receipt refs, token refs, payload hashes, telemetry refs, signer chain,
  verifier outcome, and quarantine or rejection reason when closure fails.
- **Precision target:** isolate ambient time and ID generation behind explicit
  providers at replay-critical boundaries. Existing Python paths that still call
  `datetime.now(...)` or `uuid.uuid4()` directly should be treated as hardening
  targets for deterministic audit reproduction.
- **Accountability target:** custody graph and replay projections may be
  asynchronous, but they must remain receipt-derived, append-only, and
  verifier-readable; async projection lag must not weaken the PDP decision.

### Step 5: Admit Physical Telemetry Without Making It Authority

Rare-shoe RCT makes the platform concrete: physical proof matters, but hardware
signals are evidence inputs. They do not settle custody or bypass the PDP.

- **Current anchors:** [`virtual_nfc_simulation_plan.md`](virtual_nfc_simulation_plan.md),
  [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md),
  and [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md).
- **Safety target:** require signed hardware or simulated-HAL telemetry refs
  where policy demands them, including asset binding, challenge freshness,
  signer identity, zone evidence, and tamper/quarantine semantics.
- **Precision target:** redact raw UID, challenge, key, geolocation, and private
  operator data from public proof while preserving hash-bound verifier metadata
  for operator forensics and replay.
- **Expansion target:** graduate from fixture-backed NFC simulation to enrolled
  hardware only after key management, signer identity, freshness windows,
  revocation, and quarantine behavior are explicit and tested.

### Step 6: Gate Admission With Contract Tests And Negative Drills

Autonomous expansion should be admitted by tests that prove bad paths stop
before execution, not by demos that only show happy paths.

- **Current anchors:** [`agent_system_eval_schedule.md`](agent_system_eval_schedule.md),
  [`gated_action_dx_layer.md`](gated_action_dx_layer.md),
  `scripts/host/verify_q2_verification_contracts.sh`, and
  `scripts/host/verify_authz_graph_rfc_phases.sh`.
- **Required admissions:** deterministic replay validation; missing or expired
  token rejection; stale telemetry failure; signer-chain violation; replay /
  clone detection; policy snapshot mismatch; scope mismatch; and receipt
  linkage back to the original `ActionIntent`.
- **Runbook rule:** when deterministic gates fail repeatedly, stop autonomous
  iteration and surface the verifier/runbook evidence for human review. The
  platform can self-diagnose and propose patches, but promotion, custody
  clearance, production deploys, and quarantine release remain policy-admitted
  or human-reviewed actions.

## Status Update (2026-06-22, Window G Governance-Learning Contract & Schema Freeze)

**Done (2026-06-22).** Implemented the full Window G contract freeze slice for governance-aware learning and distillation.

- **Models:** Defined strict Pydantic v2 models for `GovernanceFeatureVector`, `GovernanceEvidenceSummary`, and `GovernanceLearningSampleV1` in [governance_learning.py](../../src/seedcore/models/governance_learning.py) and registered them in [__init__.py](../../src/seedcore/models/__init__.py).
- **Exporter:** Created `GovernanceLearningSampleExporter` in [exporter.py](../../src/seedcore/ops/governance_learning/exporter.py) to build samples from supplied `ActionIntent`, `EvidenceBundle`, and verifier outcome artifacts. Ensures fail-closed error handling when snapshot/evidence/replay links are absent.
- **Verdict Scorer:** Updated `GovernanceRewardScorer` in [governance_reward.py](../../src/seedcore/ml/reward/governance_reward.py) to align with canonical verdict taxonomy (`near_miss_allow`, `near_miss_deny`, etc.), ensuring only verified clean allows can become positive reward and `verification_mismatch`/lockout outcomes are never treated as positive reward.
- **Sample Store:** Generalised [sample_store.py](../../src/seedcore/ml/distillation/sample_store.py) to write `GovernanceLearningSampleV1` records to a governance-specific JSONL file.
- **Scenario Curriculum:** Expanded `GovernanceScenarioGenerator` in [governance_scenarios.py](../../src/seedcore/ml/curriculum/governance_scenarios.py) with advanced coordinate-redirect, replay-injection, tampered-signature, and missing-cosignature synthetic intent probes.
- **Contract Tests:** Added [test_governance_learning_harness.py](../../tests/test_governance_learning_harness.py) to validate schema checks, exporter boundaries, verdict isolation, and generator probes.

## Status Update (2026-06-23, Infrastructure Hardening Verification)

**Done (2026-06-23).** Reviewed and hardened the SeedCore infrastructure
hardening slice against the live baseline, then verified the local runtime and
Rust/Python test paths.

- **Authz graph rollout:** Staged compiled-authz-graph rollout behavior in
  [pdp_hot_path.py](../../src/seedcore/ops/pdp_hot_path.py) and
  [governance.py](../../src/seedcore/coordinator/core/governance.py) now keeps
  baseline authority for shadow stages, emits warning metadata for divergence,
  preserves full fail-closed behavior by default, and avoids leaking candidate
  `ExecutionToken` or governed-receipt fields into non-authoritative stages.
- **Workload identity:** `ActionIntent` and agent-action principal models now
  carry optional `spiffe_id` and `dpop_jkt` fields, with router propagation in
  [agent_actions_router.py](../../src/seedcore/api/routers/agent_actions_router.py)
  and verification helpers in [workload.py](../../src/seedcore/ops/identity/workload.py).
  SPIFFE/DPoP identity is treated as identity evidence, not standalone
  execution authority; session or actor proof remains required.
- **Revocation-safe caching:** [ray_cache.py](../../src/seedcore/ops/pkg/authz_graph/ray_cache.py)
  now includes revocation epoch and token-counter version in decision cache keys,
  caps positive decision caching to a short TTL, and preserves negative/deny
  caching semantics.
- **Protobuf transport spike:** Added
  [pdp_hot_path.proto](../../src/seedcore/ops/pdp_hot_path.proto),
  [pdp_hot_path_pb2.py](../../src/seedcore/ops/pdp_hot_path_pb2.py), and
  [pdp_protobuf_serialization.py](../../src/seedcore/ops/pdp_protobuf_serialization.py)
  as a mirror transport profile for hot-path request/response payloads without
  changing the authoritative PDP contract.
- **Rust/PyO3 test contract:** Feature-gated `seedcore-proof-py` so Rust
  workspace tests run with `--no-default-features` while Python-extension
  packaging keeps the `pyo3/extension-module` default. Updated
  [README.md](../../README.md) to document the verified Rust command and fixed
  the proof bridge unit-test fixture/env isolation in
  [lib.rs](../../rust/crates/seedcore-proof-py/src/lib.rs).
- **Verification:** Focused hardening tests passed:
  `pytest tests/test_pdp_authz_graph_rollout_stages.py tests/test_workload_identity.py tests/test_authz_cache_security.py tests/test_pdp_protobuf_serialization.py -q`
  (`23 passed`). The local `deploy/local/` runtime was brought up and
  `bash scripts/host/verify_authz_graph_rfc_phases.sh` passed both its focused
  pytest phase (`79 passed`) and live `127.0.0.1:8002` phase (`8 passed,
  0 failed`). Rust workspace verification now passes with
  `cargo test --manifest-path rust/Cargo.toml --workspace --no-default-features`
  (`79 passed`).

## Status Update (2026-06-23, Governance-Learning Windows H-K Adoption Review)

**Docs aligned (2026-06-23).** Reviewed the proposed Windows H-K plan for
distilled reasoning, HALT/abstention tuning, trust-proof refinement, and
simulation-based governance validation.

- **Decision:** Apply the plan as a deeper breakdown of the existing
  [Governance-Aware Learning Next Stage Plan](governance_aware_learning_next_stage_plan.md),
  not as a new parallel planning tree.
- **Path correction:** Do not create top-level `docs/governance_learning/`,
  `src/governance_learning/`, or `src/simulation/` roots for this work. Route
  follow-on docs through `docs/development/`, and route implementation through
  existing `src/seedcore/ml/...`, `src/seedcore/ops/governance_learning/...`,
  verifier, replay, and sample-store surfaces.
- **Next live window:** Window H should start with advisory taxonomies,
  deterministic teacher labels from PDP/verifier/schema/token/replay outcomes,
  replay-derived datasets, and shadow-only student evaluation. The student
  artifact cannot become a final PDP, mint or expand `ExecutionToken`s, alter
  evidence, or clear verifier failures.
- **Safety posture:** Windows I-K are valid only if abstention remains a safe
  no-execute/manual-review recommendation, refinement produces candidate
  patches with replay/audit provenance, and simulation success does not imply
  physical deployment readiness.
- **Window J refinement safety:** Adopt the repair-safety matrix,
  `authority_effect` taxonomy, `RefinementRecommendationV1` recommendation
  shape, and `dev_repair` / `staging_shadow` / `production_advisory` operating
  modes as formal design requirements for the trust-proof refinement phase.
  The adopted form is intentionally narrower than the outside note: hash,
  signature, key, trust-anchor, attestation, revocation, replay, transparency,
  and evidence co-signature failures are diagnostic/manual-review only; only
  representation-only fixture repairs can be auto-applied in dev, and every
  candidate still requires replay.

## Status Update (2026-06-26, Window H Offline Governance-Advisory Scaffold)

**Done (2026-06-26).** Landed the first Window H scaffold as a strictly
offline, shadow-only advisory learning loop in commit `58fa58d`
(`feat: add governance advisory shadow scaffold`).

- **Advisory contract:** Added
  [governance_advisory.py](../../src/seedcore/models/governance_advisory.py)
  with strict `GovernanceAdvisoryOutputV1` validation. Student outputs are
  bounded to advisory fields and schema-enforced as `shadow_only=True`,
  `final_authority=False`, and `student_final_authority_usage=0`.
- **Teacher labels:** Added
  [labeler.py](../../src/seedcore/ops/governance_learning/labeler.py) to derive
  deterministic advisory labels from `GovernanceLearningSampleV1` records. The
  labeler abstains for every case except already-verified clean allows and does
  not reinterpret PDP or verifier outcomes.
- **Replay-derived dataset:** Added
  [governance_dataset.py](../../src/seedcore/ml/distillation/governance_dataset.py)
  to encode a fixed feature order from `features` and `evidence_summary`, attach
  teacher labels, and split train/eval rows deterministically by `sample_id`
  hash.
- **Offline student and evaluator:** Added
  [governance_student.py](../../src/seedcore/ml/models/governance_student.py)
  and
  [governance_shadow_eval.py](../../src/seedcore/ml/distillation/governance_shadow_eval.py).
  The v1 student is a conservative exact-row baseline that abstains on unknown
  rows; the evaluator measures taxonomy validity, reason-code match,
  trust-gap precision/recall, abstention match, false-safe advisories, and
  authority usage.
- **Contract tests:** Added
  [test_governance_shadow_eval.py](../../tests/test_governance_shadow_eval.py)
  for teacher-label mapping, strict authority-invariant validation, stable
  dataset encoding/splitting, conservative student fallback, and false-safe /
  authority-usage checks. Verification passed with
  `pytest tests/test_governance_learning_harness.py tests/test_governance_shadow_eval.py -q`
  (`14 passed`) and `git diff --cached --check`.
- **Deferred by design:** No live PDP hook, coordinator hook, ML service route,
  XGBoost/Ray training path, model serving endpoint, or promotion path was
  added in this slice.

## Status Update (2026-06-29, Window H Live Shadow Advisory Contract)

**Done (2026-06-29).** Implemented the contract-first live shadow advisory
slice while preserving the PDP authority boundary.

- **Isolated shadow metrics:** Added a governance-advisory telemetry store in
  [shadow_parity_log.py](../../src/seedcore/ops/governance_learning/shadow_parity_log.py)
  with separate JSONL/SQLite paths under `.local-runtime/governance_shadow_advisory`
  and `SEEDCORE_GOVERNANCE_SHADOW_LOG` / `SEEDCORE_GOVERNANCE_SHADOW_DB`
  overrides. These events do not write to the compiled-authz hot-path parity DB.
- **Explicit ML service contract:** Added
  `POST /xgboost/governance/advisory` and
  `POST /xgboost/governance/train_shadow_student` in
  [ml_service.py](../../src/seedcore/ml/ml_service.py). The current backend is
  the conservative exact-row `GovernanceShadowStudent`; training is an explicit
  operator/CI-triggered action and refuses artifacts with false-safe or
  authority-usage metrics.
- **Opt-in PDP hook:** Added `SEEDCORE_ENABLE_GOVERNANCE_SHADOW_ADVISORY`,
  `SEEDCORE_GOVERNANCE_SHADOW_ADVISORY_URL`, and
  `SEEDCORE_GOVERNANCE_SHADOW_QUEUE_SIZE` handling in
  [pdp_hot_path.py](../../src/seedcore/ops/pdp_hot_path.py). The hook enqueues
  best-effort shadow advisory work after the authoritative PDP response exists;
  it never changes disposition, `ExecutionToken`s, obligations, quarantine
  state, or evidence.
- **Sandbox probe:** Added
  [test_gvisor_compat_probe.sh](../../scripts/host/test_gvisor_compat_probe.sh)
  as a separate runsc compatibility signal. It skips cleanly when local gVisor
  prerequisites are unavailable.
- **Verification:** Focused tests passed:
  `pytest tests/test_governance_shadow_live_advisory.py -q` (`7 passed`),
  `pytest tests/test_governance_learning_harness.py tests/test_governance_shadow_eval.py -q`
  (`14 passed`),
  `pytest tests/test_hot_path_parity_log.py tests/test_governance_shadow_eval.py -q`
  (`8 passed`), and
  `pytest tests/test_safety_doctrine_boundaries.py -q` (`2 passed`).
  `bash scripts/host/verify_q2_verification_contracts.sh` passed. The gVisor
  probe script passed syntax validation and skipped at runtime because `runsc`
  is not installed locally.

## Status Update (2026-06-22, Policy-Governed RAG Research Adoption Review)

**Docs aligned (2026-06-22).** Reviewed policy-governed RAG research against
SeedCore's existing ADR 0008/0009 and governed RAG contract slice. The
repo-native conclusion is: adopt the governance shape, not a new RAG product
center or premature vendor stack.

- **Adoption review:** Added
  [policy_governed_rag_research_adoption_review.md](policy_governed_rag_research_adoption_review.md)
  to capture the deeper mapping from contracts/control, manifests/trails, and
  receipts/verification into SeedCore's PDP, evidence, verifier, and replay
  semantics.
- **Contract refinement:** Extended the
  [RAG Evidence Bundle and Trace Contract](../architecture/contracts/rag_evidence_bundle_trace_contract.md)
  with a future `RAGReceipt` profile, verifier-owned minimal evidence set,
  degraded `abstained` / `lite_receipt` semantics, and side-channel-safe
  denied-candidate telemetry.
- **ADR alignment:** Updated ADR 0008 and ADR 0009 to preserve the narrower
  SeedCore claim: denied chunks must not enter model-visible context under the
  enforced contract. Receipts prove process integrity and replay closure; they
  do not mint execution authority or prove the LLM answer is globally true.
- **Stack posture:** Keep existing SeedCore signer profiles and JSON receipts
  as the MVP path. JOSE/JWS, COSE/CBOR, SCITT-style transparency, NLI
  verifiers, vector databases, and enterprise connectors remain profile-gated
  follow-ons after the controlled-source RAG lane and replay validator are
  green.
- **Implementation truth check:** The codebase currently has the vendor-neutral
  RAG models, allow-only promotion guard, and focused contract tests. It does
  not yet have an end-to-end governed RAG service path: production retrieval
  adapters, PDP decision minting, guarded prompt assembly, bundle-membership
  verifier checks, trace cross-validation, receipt signing, and side-channel
  telemetry tests remain explicit next slices under the same authority boundary.

## Status Update (2026-06-17, Immutable Policy Anchor & Graph Mutation Gate)

**Done (2026-06-17).** Added the first contract-level "Immutable Policy Anchor & Graph Mutation Gate" slice for protecting the active PDP path against AI-origin graph or policy snapshot promotion attempts.

- **Models:** Defined `MutationIntent` and graph-bound `CoSignedPromotionReceipt` envelopes in [mutation_intent.py](../../src/seedcore/models/mutation_intent.py) and registered them in [__init__.py](../../src/seedcore/models/__init__.py).
- **PDP Hardening:** Enhanced active compiled authz graph resolution in `_resolve_compiled_authz_index` ([governance.py](../../src/seedcore/coordinator/core/governance.py)) to detect AI-origin signatures from explicit graph inputs as well as active manager lookups. Provenance detection is prefix-scoped to `agent:` and `ai:` refs so ordinary principals such as `principal:agent-1` do not quarantine the graph.
- **Promotion Boundary:** Un-co-signed AI-origin graph inputs fail closed and drop back to the pinned fallback path. Co-sign receipts must be bound to the target graph version and snapshot hash and must come from an administrative/hardware signer class (`kms:` or `tpm:`); the current slice validates receipt structure and binding, while full signature verification remains a later key-registry/KMS integration step.
- **Contract Enforcement:** Integrated `trust_alert` propagation through `_finalize_policy_decision_contract`, the hot-path decision view, and governed receipts so replay/audit surfaces can distinguish policy hijack quarantine from ordinary deny paths.
- **PKG Manager Integration:** Added registration and retrieval APIs for co-signed promotion receipts on `PKGManager` ([manager.py](../../src/seedcore/ops/pkg/manager.py)).
- **Adversarial Verification:** Added the "Autonomous Policy Hijack" drill to the commerce drill matrix ([test_rct_commerce_drill_matrix.py](../../tests/test_rct_commerce_drill_matrix.py)) to verify lockout behavior for un-co-signed or incorrectly bound AI-origin graph inputs and the absence of a hijack alert only when the receipt is bound to the active graph.

## Status Update (2026-06-12, Local Autonomous Application Signal)

The local autonomous application investigation is now captured in
[rtx_spark_autonomous_era_investigation.md](rtx_spark_autonomous_era_investigation.md).
The planning signal is urgent but narrow: RTX Spark / DGX-class workstations,
Windows local-agent primitives, frontier coding and security agents, and
agentic creative/scientific application surfaces make asynchronous digital
workers more plausible in 2026. They can propose, simulate, diagnose, repair,
and package evidence faster than traditional human-reviewed loops can absorb.

Immediate priority adjustment:

1. Treat Agent Self-Regulation as Q3-critical infrastructure, not a sidecar.
2. Make local-agent provenance visible in Execution Replay Studio.
3. Keep hardware roles separate: Spark-class workstations can sign proposal or
   simulation provenance; edge/robot devices produce physical closure evidence.
4. Treat application-agent output from coding, creative, scientific, or
   security tools as advisory unless transformed into typed policy inputs,
   fixtures, evidence refs, or reviewable patches.
5. Use AI-led self-healing to accelerate diagnosis, fixtures, patches, and gate
   runs, but stop at reviewable promotion.
6. Keep Restricted Custody Transfer as the proving ground.

Authority remains unchanged:

```text
Local autonomous applications can accelerate autonomy.
Only PDP allow + scoped ExecutionToken + evidence closure + verifier acceptance
can admit high-consequence execution.
```

## Status Update (2026-06-15, One-Month Stack Triage)

A deeper stack investigation is useful for June planning, but it should be
applied as a staged trust-runtime hardening overlay rather than as an
immediate production mandate. The correct read is:

```text
Adopt the authority-sharpening pieces now.
Spike the hot-path performance pieces behind existing contracts.
Defer vendor-specific production substrate choices until the simulator,
staging, and replay evidence justify them.
```

This month should prioritize the parts that strengthen the current RCT wedge
without changing SeedCore's authority semantics:

1. **Staging authz graph rollout.** Treat
   `SEEDCORE_PDP_USE_ACTIVE_AUTHZ_GRAPH=true` as the controlled staging
   promotion target, following
   [pdp_authz_graph_staging_rollout.md](pdp_authz_graph_staging_rollout.md).
   Do not promote production enforce behavior until snapshot alignment,
   allow/deny fixtures, rollback, and deny-spike checks are green.
2. **Result-verifier telemetry acceptance.** Keep RESULT_VERIFIER embedded by
   default and make `result_verifier_job_seconds_total`,
   `result_verifier_watermark_lag_seconds`, queue outcome counts, and
   quarantine mutations part of the monthly gate evidence. A dedicated verifier
   service remains an ADR-triggered deployment shape, not a default refactor.
   First implementation step: `scripts/host/verify_result_verifier_telemetry_contract.sh`
   now runs the always-on telemetry schema/dashboard contract gate without
   requiring the optional Postgres verifier lane.
3. **Edge Trust Adapter v0.1 via fixtures.** **Done (2026-06-16).** Implemented the thin enrollment and
   signer models for `DeviceIdentity` and `HardwareSignerRef`, along with `AssetAnchor`,
   `ZoneEvidence`, and `EdgeTrustEnrollmentBundle` in [edge_trust.py](../../src/seedcore/models/edge_trust.py).
   Built the `FixtureEdgeTrustAdapter` and integrated edge trust validation checks into the evidence
   verifier flow [verification.py](../../src/seedcore/ops/evidence/verification.py). Fully validated
   all failure modes (revoked signers, quarantined devices, zone/profile mismatches, stale telemetry)
   via unit and integration tests.
4. **Evidence state-binding extension.** Pull the lightweight
   `prior_state_binding`, `result_state_binding`, and `causal_parent_refs`
   work from ADR 0005 into the replay/evidence plan if it fits the current
   closure surface. These fields improve replay causality; they do not create
   a new settlement store.
5. **Hot-path transport and crypto spike.** Evaluate Protobuf or FlatBuffers as
   an internal mirror and benchmark Rust/PyO3 CMAC/KDF paths, while keeping
   JSON-LD as the canonical replay/export surface and the existing PDP/token
   contract as the authority boundary. The transport side is now scoped in
   [hot_path_transport_serialization_spike.md](hot_path_transport_serialization_spike.md):
   start with Protobuf v3 as a measured internal mirror, keep FlatBuffers as a
   later Rust-first candidate, and avoid zero-allocation / zero-decoding claims
   until benchmark artifacts prove them.
6. **Authz graph engine evolution.** Treat the next graph-engine enhancement as
   a benchmark-gated future-performance track, not a rewrite prerequisite for
   the current RCT wedge. [ADR 0011](../architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md)
   freezes the rule: tuple import/export and deep-path benchmarks come first;
   Ray hot-path promotion, path flattening, CSR/CSC layouts, Rust/PyO3 kernels,
   and memory-mapped graph artifacts require measured pressure. The schedule
   lives in [authz_graph_engine_evolution_plan.md](authz_graph_engine_evolution_plan.md).
7. **Counter-ledger acceleration behind the explicit ledger.** Redis,
   Dragonfly, Lua, WATCH pipelines, or RESP3 client-side caching may be
   benchmarked as near-local acceleration for monotonic counter admission, but
   the ledger remains explicit and fail-closed. Cache success cannot replace
   verifier, token, or evidence closure.
8. **Ingress and programmatic identity as guarded setup.** If the GKE path is
   active this month, IAP/Gateway API work should protect operator/admin
   surfaces and bypass public trust routes deliberately. DPoP, SPIFFE/SPIRE,
   WIMSE-aligned workload identity, and brokered transaction tokens should be
   modeled as hardening targets for programmatic callers, not as permission to
   skip gateway/PDP evaluation.
9. **Two-stage RAG authorization only where a retrieval surface exists.** Any
   agent-facing document or memory retrieval must coarse-filter first and then
   run fine-grained PDP or policy checks before chunks reach rerankers, LLMs,
   proof UIs, or operator copilots. Denied candidates should be invisible to
   downstream model context. The first implementation slice is now the
   vendor-neutral contract and promotion guardrail in
   [`src/seedcore/models/rag.py`](../../src/seedcore/models/rag.py) and
   [`src/seedcore/ops/rag/authorization_boundary.py`](../../src/seedcore/ops/rag/authorization_boundary.py):
   only explicitly allowed chunk decisions become `RAGEvidenceItem`s, while
   denied or missing-decision candidates are reduced to aggregate counts before
   downstream model context is assembled. The next safe slice is a signed
   controlled-source adapter plus PDP decision callout, followed by guarded
   prompt assembly, verifier bundle-membership checks, trace cross-validation,
   and then `RAGReceipt` / minimal-evidence-set / side-channel-safe telemetry
   tests, as scoped in
   [policy_governed_rag_research_adoption_review.md](policy_governed_rag_research_adoption_review.md)
   and the
   [RAG Evidence Bundle and Trace Contract](../architecture/contracts/rag_evidence_bundle_trace_contract.md).
   Qdrant, Milvus, Triton, JOSE/JWS, COSE/CBOR, SCITT transparency, NLI
   verifiers, and cross-encoder adapters remain later integration steps under
   this boundary.

The following should not become June blockers:

- replacing Cloud KMS, current KMS/NTAG staging, or fixture crypto with
  CloudHSM/on-prem HSM by default;
- requiring IGX Thor, ConnectX/RDMA, or production attestation hardware before
  simulator and Jetson-profile evidence contracts pass;
- introducing Debezium/CDC, Kafka, ring buffers, or shared-memory IPC as
  authority-bearing shortcuts;
- starting NVIDIA cuOpt integration unless it stays a post-validation sidecar
  with route candidates checked by SeedCore after optimization. The first
  accepted slice is the route-plan schema and deterministic post-validator in
  [`src/seedcore/models/optimization.py`](../../src/seedcore/models/optimization.py)
  and
  [`src/seedcore/ops/optimization/post_validation.py`](../../src/seedcore/ops/optimization/post_validation.py),
  which can allow, deny, or quarantine proposals but never mint execution
  authority;
- treating Protobuf, FlatBuffers, Pydantic Core, Rust, Redis, or Dragonfly as
  authority sources. They are implementation choices under PDP, token, replay,
  and verifier contracts.
- treating RAG receipts, minimal evidence sets, JOSE/JWS, COSE/CBOR, SCITT
  registration, vector stores, or model-based claim verifiers as authority
  sources. They are proof, transport, substrate, or verifier-profile choices
  under SeedCore's existing PDP/evidence/replay boundary.

## Status Update (2026-05-25, Execution Replay Studio Drafted)

The next "Visualize It" step is now captured in
[execution_replay_studio_development_plan.md](execution_replay_studio_development_plan.md).
Execution Replay Studio is a read-only forensic expansion of the existing
replay/verification surface, not a new authority path.

It should make one governed execution inspectable end to end:

- execution steps from request through verifier outcome;
- policy snapshots, decision hashes, approval/scope fields, and context hashes;
- signed telemetry refs, payload hashes, freshness, and replay/nonce status;
- signer chains, trust-bundle membership, and revocation posture;
- deterministic reproduction commands for replay bundles and offline verifier
  checks.

Immediate adoption order:

1. compose a fixture-backed Studio payload from existing `verification-detail`,
   `replay`, and runtime replay endpoints;
2. add `/studio?workflow_id=...` as an advanced operator-console route linked
   from the current replay page;
3. render the execution step rail, artifact inspector, policy snapshot panel,
   telemetry hash verifier, signer chain validator, and reproduction panel;
4. add happy-path, stale-telemetry, signer-violation, and replay-tamper tests;
5. keep public proof narrow and keep Studio operator/internal unless access
   control explicitly permits richer forensics.

## Status Update (2026-05-22, Agentic Intent Orchestration Lane Proposed)

SeedCore should keep the current Kafka delegated RCT ingress as the
high-assurance v1 lane and add a separate stateful workflow lane for broader
agentic intent. The implementation plan is now captured in
[agentic_intent_orchestration_plan.md](agentic_intent_orchestration_plan.md).

Immediate adoption order:

1. Freeze and regression-protect `seedcore.intent.delegated.v0` as the narrow
   Restricted Custody Transfer lane.
2. Add durable workflow/saga persistence for future
   `seedcore.intent.workflow.v1` envelopes before any new execution behavior.
3. Add workflow ingress classification so Kafka can persist agentic workflows
   without blocking on human approval, telemetry, or long-running execution.
4. Admit broader operations as policy-governed nodes, but graduate them to
   execution only after planner, token, tool, evidence, replay, and toxic-path
   contracts exist.
5. Make `SCAN -> TRANSFER_CUSTODY` the first multi-node workflow milestone,
   reusing the existing Agent Action Gateway for the custody-transfer node.

## Status Update (2026-05-21, Bounded Autonomy Acceleration & Self-Regulation Drill Landed)

SeedCore has landed and targeted-test validated the **Gated Action DX MVP** and
the first **Agent Self-Regulation drill**. The SDK namespace
(`src/seedcore/sdk/`) now gives autonomous coding and action agents (like
Antigravity and Codex) a bounded way to inspect, simulate, propose, and repair
system behaviors. The strategic shift is to make SeedCore **autonomy-ready**
without letting autonomy become unchecked authority.

The core planning rule for agentic interactions is now:

```text
Agents may evaluate, simulate, diagnose, and propose.
The PDP, verifier, and operator promotion gates still decide what is allowed.
```

This creates an accelerated, higher-priority overlay across the existing RCT plan:

1. **Gated Action DX + self-regulation drill landed.** The
   `@gated_action(...)` decorator, thread-local evaluator/executor injection,
   and `GovernedResult` are implemented at
   `src/seedcore/sdk/gated_action.py` for one RCT path with shadow and guarded
   enforce modes. Enforce mode requires an allow decision with an
   `ExecutionToken` and configured executor before business logic can run. The
   new drill harness at `src/seedcore/drills/agent_self_regulation.py` and
   `scripts/host/verify_agent_self_regulation_drill.sh` generates a real gated
   action manifest, runs MCP `seedcore.agent_action.check_policy` with explicit
   authority, and captures reviewable replay/evidence refs.
2. **Bounded autonomy interface.** Treat MCP `seedcore.agent_action.evaluate`
   / `seedcore.agent_action.check_policy` and the gateway SDK surface as the
   primary **Agent Self-Regulation** lane. Agents can ask SeedCore whether a
   proposed action is admissible, but they cannot bypass PDP evaluation, and
   the SDK decorator prevents silent permissive execution.
3. **Governance-aware learning earlier.** Pull the Scenario Generator and
   Governance Reward Scorer forward as simulation and training infrastructure
   for coding/action agents. They remain shadow/simulation only: they consume
   PDP, replay, and `RESULT_VERIFIER` outcomes, but never issue or override
   `ExecutionToken`s.
4. **AI-led self-healing as staged autonomy.** Add a workstream where
   assistants run degraded-edge drills, diagnose telemetry/outbox failures,
   propose patches, execute host/CI gates, and open reviewable changes. Live
   production mutation remains blocked until explicit promotion criteria,
   rollback behavior, and operator approval are defined.
5. **Keep RCT as the proving ground.** Rare-shoe RCT remains the must-win
   commerce fulfillment scene. The autonomy work makes this workflow faster to
   build, test, verify, and repair under automated agent assistance.

Freshness-SLA schedule:

- The staged test order is now captured in
  [freshness_sla_edge_stress_schedule.md](freshness_sla_edge_stress_schedule.md):
  RCT fixture/simulator first, Jetson Orin prototype edge second, IGX Thor /
  T5000 trusted edge third, and robotics handoff environments after the
  telemetry contract is stable.
- The control metric across those lanes is Convergence P99 Latency: if the
  local PDP view cannot prove it is at least as fresh as the incoming causality
  token, the action must fail closed rather than silently downgrade freshness.
- RTX Spark / DGX Spark-class machines stay in the proposal, simulation,
  diagnosis, and repair lane unless explicitly enrolled as evidence-producing
  devices; they are not substitutes for deterministic physical closure
  evidence.

Agent-system eval schedule:

- The system-level eval track is now captured in
  [agent_system_eval_schedule.md](agent_system_eval_schedule.md): decision
  evals, policy evals, forensic evals, and agent-governance evals over the
  same gateway, PDP, replay, verifier, and typed-verdict contracts that govern
  the runtime.
- Treat OpenAI-style eval tooling as measurement infrastructure only. The
  durable SeedCore requirement is a portable regression harness that survives
  prompt, model, memory, tool, and agent-workflow changes without becoming an
  authority source.
- The eval outputs can support advisory/scaffold promotion evidence, but they
  cannot issue `ExecutionToken`s, clear quarantine, override
  `RESULT_VERIFIER`, or promote `shadow` to `enforce`.
- Statistical model audits are now scoped in
  [statistical_model_audit_shadow_contract.md](statistical_model_audit_shadow_contract.md):
  Regularized f-Divergence Kernel Tests may support model promotion, privacy /
  unlearning review, and advisory drift detection, but their
  `StatisticalModelAuditV1` outputs are shadow-only evidence. They can block a
  candidate promotion or trigger engineering review; they cannot verify a
  specific governed execution or mutate trust state.

Immediate priority order:

1. **Landed and targeted-test verified:** Gated Action DX + Agent
   Self-Regulation drill over one RCT path (`src/seedcore/sdk/`,
   `src/seedcore/drills/agent_self_regulation.py`,
   `scripts/host/verify_agent_self_regulation_drill.sh`);
2. **Completed:** the self-regulation drill is wired into the standard
   host/CI-aligned degraded-edge matrix, including deny, quarantine, stale
   telemetry, out-of-bounds, and missing-evidence stop-before-execution cases;
3. **Initial Studio slice landed:** the fixture-backed
   `seedcore.execution_replay_studio.v0` payload and
   `/studio?workflow_id=...` operator route are now implemented as a read-only
   forensic expansion of the replay surface. Next Studio work is to deepen the
   artifact inspector, policy snapshot fields, telemetry hash checks, signer
   chain validation, and toxic-path fixture coverage;
4. **Next:** close the local verification-surface rehearsal through
   `deploy/local/`: run the host API/HAL plus
   `deploy/local/run-verification-api.sh`, then
   `deploy/local/verify-rct-verification-surface.sh` to prove runtime audit
   generation, verification queue/detail/replay/runbook reads, and the
   productized surface protocol against one local RCT audit row;
5. After the local gate is green, close deployment-realistic proof topology by
   repeating the same evidence path in Kind/Kubernetes with the verification API
   in the same cluster as the already-green hot-path gates. Kafka is a
   delegated-intent/readiness-drill follow-on, not the blocker for
   verification-surface signoff;
6. Continue rare-shoe RCT proof-bundle and toxic-path expansion as the
   commercial scene feeding Studio and public proof. The virtual NFC simulation
   lane is now implemented and verified, so remaining rare-shoe work should
   build on that evidence contract rather than re-defining dynamic NFC.
7. When model-promotion, privacy/unlearning, or advisory-drift audits enter the
   eval lane, use
   [statistical_model_audit_shadow_contract.md](statistical_model_audit_shadow_contract.md)
   as the boundary: statistical audit outputs may block promotion or trigger
   review, but never enter PDP, token, custody, or `RESULT_VERIFIER`
   authority.

## Status Update (2026-05-15, Commercial RCT Vertical Scene)

The next commercial-grade demo scene should be **Collectible Rare-Shoe
Restricted Custody Transfer**, documented in
[rare_shoes_collecting_transfer_demo_spec.md](rare_shoes_collecting_transfer_demo_spec.md).

This does not change the product center. It makes the existing commerce RCT
wedge more legible by binding a high-value physical collectible to:

- source-registration-first authentication and provenance
- buyer/seller/order/quote/value context
- explicit delegated authority and approval envelopes
- signed NFC/scan/edge telemetry evidence
- RESULT_VERIFIER quarantine and replayable proof

Immediate implementation order:

1. Add rare-shoe source-registration fixtures for authentication packet, NFC
   binding, condition grade, and provenance refs.
2. Add a gateway fixture/adapter path that maps listing, quote, order, value,
   buyer delegation, and destination scope into
   `seedcore.agent_action_gateway.v1`, including stable rare-shoe reason
   codes and `workflow_join_key` expectations.
3. Completed virtual NFC simulation lane: deterministic fixture-backed origin /
   delivery scan evidence now covers happy path, replay / clone, stale scan,
   wrong asset, tamper state, missing required field, and replay-visible
   redacted verifier metadata. Real NFC hardware remains an extension
   interface, not a prerequisite for the proof chain.
4. Add the golden replay/proof bundle
   `rare_shoe_happy_path_replay_bundle.json` so the demo can be inspected
   through public proof, operator forensics, forensic video proof, and replay
   surfaces early.
5. Extend the commerce degraded-edge drill matrix with rare-shoe toxic paths:
   authentication mismatch, NFC challenge failure, delayed telemetry,
   signer-chain violation, condition drift, and cross-asset replay.
6. Keep public proof narrow while operator forensics shows the richer
   authentication and telemetry chain; publish hash-bound forensic video proof
   linked to replayable receipts for human inspection.

Verification note (2026-06-11): workspace validation for the virtual NFC lane
passed the focused NFC/RCT/edge pytest slice, evidence/materializer/replay
pytest slice, full Python test suite (`1329` tests),
`scripts/host/verify_q2_verification_contracts.sh`,
`scripts/host/verify_authz_graph_rfc_phases.sh`, TypeScript workspace
typechecks/tests, and `git diff --check`.

## Status Update (2026-04-10, Remote Kube Topology)

Latest live deployment-topology status:

- the remote GCP VM + Kind path is now green for the core runtime topology:
  - SeedCore API, Ray/KubeRay, ingress, and HAL simulation are live through the
    checked-in `build.sh` and `deploy/` path
  - `/health`, `/readyz`, `/api/v1/pdp/hot-path/status`, and
    `verify_hot_path_observability.sh` are aligned and passing against the
    kube-backed API
- degraded coverage has moved beyond host-only verification:
  - the live Redis dependency-loss drill passes in the kube topology
  - runtime remains operational through outage and recovery with no mismatches
    and no rollback trigger
- the hot-path deployment baseline is now stable enough to guide bridge work in
  this topology:
  - latest benchmark: `40` requests, `0` mismatches, `0` errors,
    `p50 ~111ms`, `p95 ~139ms`, `p99 ~156ms`
  - live gate posture: `runtime_ready=true`, `authz_graph_ready=true`,
    `graph_freshness_ok=true`, `alert_level="ok"`

Important boundary:

- this topology still does **not** include Kafka or the verification API, so
  it is not yet a complete external-surface or productized-verification
  topology

Immediate decision:

- begin only the narrow, read-only Q3 bridge work needed for external-agent
  debugging against the hot-path/runtime read contract
- keep the Gemini-visible surface at the existing minimal read-only bundle, and
  expose only the live-safe subset in topologies that do not yet have the
  verification API

Reference:

- [Kube Topology Validation Q2 Signoff](kube_topology_validation_q2_signoff.md)

## Status Update (2026-04-07)

Latest repo-aligned critical-path status:

- `RESULT_VERIFIER` P0 is now implemented inside the coordinator runtime for
  the RCT trust slice:
  - intake polls `digital_twin_event_journal` and advances a durable high
    watermark in `result_verifier_runtime_state`
  - verification work is persisted through `result_verifier_jobs` and
    `result_verifier_outcomes` with `FOR UPDATE SKIP LOCKED` worker claims
  - replay validation reuses the same `ReplayService` verification path as the
    operator/API replay surface
- fail-closed enforcement is now authoritative rather than aspirational:
  - replay mismatches immediately write `verification_failed` or
    `verification_quarantined` twin/custody mutations
  - governance lockout marker `result_verifier_lockout` is persisted with
    `authority_source=result_verifier`
  - policy evaluation, closure, and settlement handoff now hard-deny from
    authoritative twin state when verifier lockout/quarantine is present
- migrations `133_result_verifier.sql` and
  `134_result_verifier_runtime_state.sql` are part of the local init path, and
  the runtime is controlled through `SEEDCORE_RESULT_VERIFIER_*` env flags.
- the main remaining P0 hardening work is operational rather than conceptual:
  - add deeper Postgres integration coverage for journal -> job -> outcome ->
    gate denial
  - stress `SKIP LOCKED` multi-worker contention behavior
  - document quarantine remediation / operator runbook handling

## Status Update (2026-04-08, Memory Refactor)

Latest repo-aligned memory-subsystem status:

- the bounded memory refactor is now materially underway rather than
  speculative:
  - caller-facing contracts exist for `WorkingMemory`, `SemanticMemory`, and
    `IncidentMemory`
  - `MemoryRuntime` now owns the main semantic-storage boundary
    (`PgVectorStore` + `Neo4jGraph`) and exposes shared facades
  - legacy tiered-memory exports have been narrowed behind
    `seedcore.memory.legacy`
- semantic-memory contract drift has been repaired:
  - `HolonFabric`, pgvector, and Neo4j now align on upsert/search/delete/stats
    enough for contract-level tests to pass
  - task-outcome promotion now maps onto `HolonType.EPISODE`
  - local host runtime support for Neo4j-backed semantic memory is wired
    through `deploy/local/*`
- caller migration has progressed beyond the initial bridge/tools slice:
  - `CognitiveMemoryBridge` already depends on `WorkingMemory` and
    `SemanticMemory`
  - `ToolManager`, `memory_tools.py`, `FindKnowledgeTool`,
    `CollaborativeTaskTool`, and query-tool registration now prefer
    `semantic_memory`
  - organism / organ / agent local `ToolManager` wiring and Ray tool shards now
    prefer `semantic_memory=runtime.semantic` when they already hold a
    `MemoryRuntime`
  - `CognitiveCore` retrieval now routes through `SemanticMemoryService` in
    `HolonFabricRetrieval`, including correct enum-to-scope-value normalization
  - `CognitiveCore` now exposes `attach_shared_semantic_memory(...)`, and
    `CognitiveOrchestrator` can inject shared semantic memory into all worker
    cores to reduce compatibility-era re-wrapping
- state/telemetry work is improved but not fully unified:
  - `MemoryAggregator` now polls semantic stats through the service/runtime
    facade and supports injected `semantic_memory`, `memory_runtime`, and
    `mw_manager`
  - incident telemetry now supports injected/runtime-provided
    `IncidentMemoryService` with contract-shaped status output
  - when `state_service` runs as a separate process, it may still open its own
    telemetry-only PG/Neo4j pools unless injected with a shared runtime
- test coverage now includes:
  - semantic contract tests
  - cognitive bridge tests
  - Neo4j relationship sanitization tests
  - memory aggregator/runtime lifecycle tests
  - cross-layer memory tool integration tests
- the main remaining memory work is now cleanup and unification, not basic
  contract repair:
  - reduce compatibility-first `HolonFabric` fallback usage where internal
    callers can require `semantic_memory`
  - continue normalizing residual HolonFabric-era logs/docstrings toward
    semantic-memory terminology (code path mostly migrated)
  - runtime ownership policy is now decided:
    organism owns the primary semantic-storage runtime in its process, and
    state-service should consume remote memory stats rather than defaulting to
    its own PG/Neo4j bootstrap
  - implement the organism -> state-service memory telemetry boundary and push
    local state-service runtime bootstrap behind explicit fallback/dev mode
  - decide whether to add live-backend semantic integration lanes beyond fast
    mock/contract tests
  - keep `HolonClient` retired (already removed) and avoid reintroducing
    compatibility adapters in new code
  - either migrate flashbulb/legacy MFB paths onto `IncidentMemory` or keep
    them explicitly quarantined as legacy-only

## Status Update (2026-04-02)

Latest repo-aligned critical-path status:

- `VerificationSurfaceProjection` freeze pass is implemented for the Q2
  verification API and UI surfaces, including explicit versioned projection
  models and deterministic business-state mapping with `pending_approval`.
- verification service contract namespace is now `/api/v1/verification/*`
  (legacy `/api/v1/transfers/*` and `/api/v1/assets/forensics` paths are
  retired in the TS verification service layer).
- `AgentActionGateway` request boundary is now strict and externally stable for
  `seedcore.agent_action_gateway.v1`, with required identity/scope/hardware
  fields, deterministic schema invariants, canonical request hashing, and 24h+
  idempotency retention.
- Screen 2 side-by-side audit trail is now contract-driven (`request/authority`
  + `decision/artifacts` + `physical/closure`) and correlated through one
  workflow join key.
- Screen 1 queue surface is now implemented with filterable trust buckets and
  readiness/blocker views (`/api/v1/verification/transfers/queue` + operator
  `/queue`).
- Screen 4 replay/verification detail is now implemented through
  `seedcore.verification_detail.v1` at
  `/api/v1/verification/workflows/{workflow_id}/verification-detail`.
- hot-path semantics have been hardened for production gating:
  strict parity threshold (`1000/1000`), dependency and latency gates, durable
  parity evidence persistence, and rollback triggers.
- hot-path status now emits additive observability signals for operators and
  scraping (`alert_level`, structured alerts, gauges, optional deployment role)
  to support Kubernetes/Ray operational wiring.
- hot-path now also exposes Prometheus text at `/api/v1/pdp/hot-path/metrics`
  for scrape-first deployments.
- dedicated replay and runbook verification routes are now implemented under
  `/api/v1/verification/*`, and failure panels can surface operator runbook
  links from the same projection-driven detail/replay payloads.
- queue rows now carry `product_ref`, `updated_at`, and `trust_alerts`, with the
  `trust_alert` filter preserved through drill-down links.
- runtime parity is now supported for the asset-ref REST forensics path
  (`/api/v1/verification/assets/{asset_ref}/forensics`) using subject-based
  runtime replay lookup.
- the edge-telemetry envelope now has an exported JSON Schema artifact at
  `docs/schemas/edge_telemetry_envelope_v0.schema.json`.
- first forensic-block JSON-LD contract freeze pass is implemented with schema
  artifacts, strict runtime validation, explicit `forensic_block_id`, and
  closure/materialization consistency checks.
- host benchmark harness now supports configurable request delay and jitter
  (`scripts/host/benchmark_rct_hot_path.py`) to simulate edge-ish timing noise
  during load evidence collection.
- Window A host-first acceptance closure is now implemented and passing:
  host verification executes the same fixture + drill acceptance slices as CI,
  and hot-path observability status/metrics checks are validated by a live host
  script with hardened metrics parsing diagnostics.

## Status Update (2026-04-06, Governance-Aware Learning Plan)

- **Window E/F (signed edge telemetry refs + minimal Gemini read bundle)** is
  implemented as an additive contract pass:
  - `SignedEdgeTelemetryRefV0` and `telemetry_refs` on
    `AgentActionClosureRequest` / `AgentActionClosureResponse`, with duplicate
    `telemetry_id` rejection, non-empty `payload_sha256` / `signer_key_ref`, and
    strict `asset_ref` binding to the evaluated request asset at closure time.
  - Closure-built evidence bundles persist `telemetry_refs`; forensic
    materialization surfaces ordered refs under `physical_evidence.telemetry_refs`
    and derives `physical_presence_hash` from ordered signed
    `payload_sha256` values when such refs are present (inline snapshot fallback
    unchanged when absent).
  - `tests/test_edge_telemetry_schema_sync.py` locks exporter output to
    `docs/schemas/edge_telemetry_envelope_v0.schema.json`; additional envelope
    fixture `sample_envelope_v0_weight.json` and RCT shared
    `signed_edge_telemetry_closure_refs.json` align refs with envelopes.
  - Plugin `GEMINI_MINIMAL_READ_ONLY_BUNDLE`, `GET /info` field
    `gemini_minimal_read_only_bundle`, and standardized read wrappers:
    `seedcore.hotpath.status` is `read_only` with full contract JSON under `data`
    (preserving `observability`); verification reads unchanged
    (`ok`, `read_only`, `source_url`, `data` / `text`).

## Status Update (2026-04-06)

- **Post-Q2/Q3 governance-aware learning plan is now defined** as the next
  higher implementation stage:
  - the goal is not to replace the synchronous PDP, but to introduce
    distillation, abstention tuning, proof refinement, and governance-aware RL
    as bounded supporting components
  - the canonical planning doc is
    [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)
  - the execution rule remains:
    - the model may learn
    - SeedCore still decides
  - the initial sequence is:
    - freeze governance-learning sample schemas and exports
    - build a shadow-only distilled reasoning scaffold
    - add HALT-style authority abstention tuning
    - build a trust-proof refiner around strict replay verification
    - add governance-aware RL in simulation only

## Status Update (2026-04-03)

- Deployment observability closure for hot-path metrics/status:
  - wired `SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE` through the checked-in deployment
    paths (host/docker/k8s/ray) and added default Docker labeling (`docker`).
  - extended CI contract test to assert full JSON status <-> Prometheus text
    gauge alignment (including `*_authz_graph_ready`, `*_latency_slo_met`,
    `*_runtime_ready`, parity counters, and `*_latency_p99_ms` when present).
  - updated `scripts/host/verify_hot_path_observability.sh` to validate
    status/metrics consistency against real status payloads.
- Agent Action Gateway productization (May slice; implemented 2026-04-03):
  - reference adapter builds strict `seedcore.agent_action_gateway.v1` evaluate
    requests from simplified inputs:
    `src/seedcore/adapters/rct_agent_action_gateway_reference_adapter.py`
  - Shopify-Sandbox-shaped commerce mapping into `asset.product_ref`,
    `asset.quote_ref`, `asset.declared_value_usd`, and
    `forensic_context.fingerprint_components.economic_hash`:
    `src/seedcore/adapters/shopify_sandbox_commerce_adapter.py`
  - deterministic RCT correlation for replay lookup, including UUID-safe
    `audit_id` fallback when `governed_receipt.audit_id` is absent and explicit
    `replay_state` / `replay_lookup.preferred_key` semantics:
    `src/seedcore/adapters/rct_gateway_correlation.py`
  - persisted owner/delegation/agent validation now runs as a read-only gateway
    guard with `shadow` rollout mode, `enforce` fail-closed mode, and a short TTL
    cache for the added identity-fact lookup.
  - MCP tool `seedcore.agent_action.evaluate` (adapter input -> gateway call ->
    correlation) in `src/seedcore/plugin/mcp_server.py`
  - contract and E2E tests: `tests/test_agent_action_gateway_productization.py`
  - host real-call verifier:
    `scripts/host/verify_agent_action_gateway_productization_real_calls.py` and
    `scripts/host/verify_agent_action_gateway_productization_real_calls.sh`

## Why This Lives Outside The Root README

The root README should explain what SeedCore is, how it runs, and why the
architecture matters.

The exact next-stage plan changes faster than the high-level architecture
summary. As verification improves and the runtime hardens, this document can be
updated without turning the root README into a moving target.

## Baseline That Already Exists

SeedCore is no longer a conceptual architecture. The repository already
contains a functioning governed execution baseline.

The following should be treated as present, not future work:

- short-lived execution tokens with TTL enforcement
- Redis-backed token revocation and HAL emergency cutoff controls
- HAL transition receipts with verification paths
- evidence bundles that bind policy, execution, and transition artifacts into
  replayable closure
- asset fingerprint capture, signed HAL capture envelopes, and replay-friendly
  evidence models
- public replay, trust-page, and verification workflow surfaces
- DID, delegation, and signed-intent support on the external surface
- TPM-backed and KMS-backed signer hardening paths already exercised in repo
- staged PKG authz-graph rollout through Phase 5, including:
  - decision-centric ontology
  - multihop authority paths
  - explanation payloads such as `matched_policy_refs` and
    `missing_prerequisites`
  - decision-graph vs enrichment-graph split
  - shard-aware Ray authz cache routing

This means the next stage is not about adding more concepts for their own sake.
It is about converting the existing governed execution baseline into a
product-grade trust runtime for high-trust, multi-party environments.

The next higher stage after that is now also explicit:

- use learned systems only where they strengthen the trust slice through
  bounded, replay-linkable, fail-closed behavior
- do not let learning become an alternate authorization path

## Strategic Objective

The right objective for the next stage is:

**Make SeedCore the most credible runtime for irrefutable, multi-party governed
execution and forensic replay in high-trust supply-chain and
asset-sensitive environments.**

That is a better objective than "solve all trusted autonomy problems" because
it forces the roadmap to stay wedge-first, operational, and commercially
legible.

This objective is anchored to the
[North Star: Autonomous Trade Environment](north_star_autonomous_trade_environment.md),
which defines the runtime as a "Trust Slice" where human oversight is shifted
from monitoring execution to defining policy.

The guiding discipline for this stage is:

- one wedge: high-trust, multi-party supply chain and asset transfer
- one proof surface: governed receipts and replayable verification
- one scaling logic: a compiled hot-path decision graph with cryptographic trust
  anchors
- one design lens: SeedCore as a verifiable agentic ledger, not only a
  controller

## Control-Plane Moat Confirmation

The final technical value proposition is achievable if SeedCore keeps the
current ADR direction and does not dilute the authority boundary.

The moat is the orchestration, not any single borrowed pattern:

- Biscuit/Macaroon-style attenuation for scoped, portable authority envelopes;
- Zanzibar/SpiceDB-style revision freshness for "at least as fresh as this
  mutation" context checks;
- CDC-driven local projections for custody, approval, delegation, resource, and
  edge state;
- a compiled, stateless PDP decision core over pinned inputs;
- replayable forensic evidence that proves why authority was granted, denied,
  quarantined, or revoked.

This lets SeedCore aim for a control plane that is fast without making the
security boundary a distributed-system bottleneck. The important distinction is:

- the Rust/compiled decision core can pursue microsecond-class evaluation;
- the served gateway and `/pdp/hot-path/evaluate` surface must continue to be
  promoted by measured millisecond SLOs, parity evidence, freshness gates, and
  rollback readiness;
- graph-engine upgrades such as tuple round trips, path flattening, Ray
  production routing, CSR/CSC layouts, or Rust/PyO3 kernels are governed by
  [ADR 0011](../architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md)
  and should advance only after benchmark evidence shows they are needed;
- no cache, LLM, memory lookup, or advisory enrichment becomes authority unless
  it is converted into typed, freshness-aware, policy-admitted context.

## Updated Design Lens: Verifiable Agentic Ledger

The strongest way to describe the next-stage architecture is:

**SeedCore should behave like a black-box flight recorder for autonomous
commerce.**

That means the runtime is responsible not only for saying "allow" or "deny,"
but for preserving a verifiable chain answering all of these after the fact:

- who had authority
- which hardware exercised that authority
- which physical location or custody boundary was in scope
- which economic transaction was allowed
- which evidence proved the physical act actually happened
- which reasoning and policy chain led to the release of funds or transfer

Operationally, that lens sharpens four design commitments:

- every high-consequence action should produce a durable digital fingerprint
- authority should be delegated and narrowly scoped, never broad and ambient
- physical and economic state must converge into one replayable evidence chain
- failures should be explainable through deterministic forensic replay rather
  than post-hoc log digging

Diagram positioning and deployment posture should stay explicit:

- top (`Brain/Intent`): humans and AI agents initiate high-consequence requests
- bottom (`Sandboxes/Reality`): economic and physical systems emit evidence
- center (`SeedCore`): PDP plus forensic evidence integrator and replay anchor
- cluster role: SeedCore runs as a high-availability trust slice service, not a
  best-effort sidecar

## Canonical Digital Fingerprint Chain

For the canonical 2026 workflow, the minimum provenance story should bind four
evidence classes into one chain:

- economic transfer proof:
  - `Order_ID`
  - transaction or quote hash
- physical presence proof:
  - shelf, zone, or coordinate binding
  - point-cloud, image, or lidar-derived hash
- runtime reasoning proof:
  - policy decision hash
  - reason trace or inference-log hash
- actuator proof:
  - trajectory hash
  - motor torque, weight, or other physical-effort telemetry hash

Integration baseline for this stage:

| Component | SeedCore interaction |
| :--- | :--- |
| Confluent Kafka | intent + telemetry ingress, policy outcome / scoped authority egress |
| Ray / Kubernetes | shard-aware compiled decision graph execution for hot path |
| Redis | revocation and emergency cutoff signaling |
| Cloud KMS | signer hardening for policy and transition artifacts |
| Durable forensic store | persistence of signed forensic blocks for replay and audit |

The point is not to force every integration to emit the exact same modalities on
day one. The point is to ensure that every high-value transfer can answer, in a
single replay chain:

- what was bought or transferred
- where the actor actually was
- why SeedCore allowed it
- what physical deed was actually performed

## Next Stage: Productizing Irrefutable Governed Execution

The next stage should focus on four priorities.

Operationally, those priorities should be executed as one productionization
program rather than as separate security, observability, and UX initiatives.

The dependency order should stay clear:

- first harden the trust boundary
- then make the trust runtime operable and visible
- then expose that trust boundary through a narrow product surface
- then expand multi-party governance on top of a runtime that is already
  defensible and operable

Once that program is materially closed, the next-stage implementation track is:

- governance-aware learning through distillation, abstention tuning, proof
  refinement, and simulation RL
- canonical plan:
  [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)
- Window J proof refinement must follow the plan's repair-safety contract:
  candidate patches are typed recommendations with `authority_effect`, source
  provenance, replay requirement, and review status; production remains
  advisory/read-only.

## Program Lock: One Must-Win Workflow

In the next phase, all workstreams must prove value against one canonical
workflow:

**Restricted Custody Transfer**

This means:

- every Phase A, B, C, and D deliverable must improve the same dual-approved,
  replay-verifiable transfer flow
- anything that does not improve that flow is second-tier for this phase
- registration intake remains important, but as an upstream prerequisite chain
  to the transfer proof surface rather than as the product center of gravity

For 2026, the most useful concrete expression of that workflow is a
**Forensic Handshake**:

- Agent-B (buyer-side) requests a restricted transfer or purchase intent
- Agent-S (seller-side or inventory-side) validates delegated authority and
  reserves the item
- SeedCore binds the request to a product identity, physical scope, and bounded
  execution token
- the physical actor produces shelf or handover evidence before closure
- payment or transfer finalization happens only when the physical and economic
  evidence chains agree

The execution spine for that rule now lives in
[killer_demo_execution_spine.md](archive/historical/killer_demo_execution_spine.md).

## Immediate Execution Order

The next implementation order remains locked to Restricted Custody Transfer
Slice 1, but the repository is no longer at the planning-only stage.

### Slice 1 Implementation Status

Completed in repo:

- `TransferApprovalEnvelope` is now a first-class runtime object with versioned
  persistence and append-only transition history
- Restricted Custody Transfer no longer trusts embedded approval payloads in
  `approval_context` as authoritative truth
- `/api/v1/pdp/hot-path/evaluate` resolves persisted approval state before
  policy evaluation
- hot-path shadow status and parity plumbing remain in `shadow` mode and are
  covered by the targeted RCT pytest slice
- replay and proof projections now recover approval metadata from persisted
  policy-case authority data
- host verification scripts no longer rely on synthesized approval state for
  the main RCT sign-off flow
- productized surface verification now fails closed when no runtime `audit_id`
  is available

### Slice 1 Live Sign-Off Closure (Completed 2026-03-30)

Closed in runtime-up evidence:

- hot-path parity accounting now includes canonical `quarantine` at run level
  (`run_parity: 4/4 ok, 0 mismatched`)
- captured full runtime matrix with explicit `audit_id` links:
  - `allow`: `ba05655c-9351-4783-97f1-fc6774c4f38b`
  - `deny`: `a65bbee7-023a-44fa-9e9d-75e0164102e4`
  - `quarantine`: `21dcb295-644a-465b-a505-064e6908c99c`
  - `escalate`: `28ac9873-3e8f-430f-9681-224fdad44286`
- allow-path artifact chain now carries non-null `approval_envelope_id`,
  `approval_envelope_version`, `approval_binding_hash`, `policy_receipt_id`,
  and `transition_receipt_ids`
- replay + verification surfaces are cross-surface consistent for captured
  identifiers (with status/proof intentionally keeping narrow business-state
  shape)
- productized surface protocol is green against captured runtime evidence
- offline Rust replay-chain verification is green for all four captured runtime
  audit chains
- hardened signer provenance captured on allow path for both `PolicyReceipt`
  and `TransitionReceipt` with KMS key ref `kms:rct-live-signoff-p256`

Capture bundle:

- `.local-runtime/rct_live_signoff/20260330T061828Z`

### Post-Closure Queue

What should be done next:

1. ~~Freeze and version the captured runtime sign-off bundle as a release
   artifact.~~ **Done (2026-04-01).** Canonical tree: `tests/fixtures/demo/rct_signoff_v1/`
   with `manifest.json` checksums; machine verification:
   `python scripts/tools/verify_rct_signoff_bundle.py`; release record and tarball:
   `release/rct_slice1_live_signoff_v1/README.md`.
2. ~~Promote capture verification into a repeatable CI/host gate (shadow parity +
   runtime matrix + replay-chain verify).~~ **Partially done (2026-04-02).**
   Host verification path updated and aligned to `/api/v1/verification/*`;
   full CI policy gate adoption remains open.
3. ~~Define explicit criteria for any future `shadow` -> `enforce` hot-path
   promotion.~~ **Done (2026-04-02).** Promotion semantics now include strict
   parity, latency SLO, dependency health, and rollback triggers.
4. ~~Freeze the first forensic-handshake contract additions:~~ **Done
   (2026-04-02).**
   - ~~transaction-scoped authority binding~~
   - ~~device fingerprint binding~~
   - ~~forensic block field set~~
   - ~~replay export shape~~
5. Keep broader signer expansion and non-RCT hardening in later phases
   (outside Slice 1 closure scope).

Interpretation note:

- Item 2 (CI/host gate) should be prioritized before broadening deployment
  blast radius.
- `runtime_ready` wiring work is an environment/integration follow-up and should
  proceed in parallel, but is not a blocker to preserving the frozen sign-off
  artifact in item 1.

### Scheduled Next Key Plans (Apr 2026)

The next execution sequence should now move from contract freeze into
operational closure and external-boundary productization.

1. **Apr 2026 (early): Q2 acceptance gating**
   - completed: true
   - status: **host-first closure complete**.
   - verification-api HTTP fixture checks are required in CI
     (`scripts/ci/q2_verification_api_fixture_gate.sh`) and executed in host
     gate flow (`scripts/host/verify_q2_verification_contracts.sh`).
   - queue/detail/replay/runbook/forensics now run as one required acceptance
     matrix for the RCT slice.
   - remaining: validate the same gate envelope across real deployment
     topologies (K8s/Ray).
2. **Apr 2026 (mid): deployment observability closure**
   - completed: true
   - wire `SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE` through the actual deployment
     paths already checked into repo.
   - verify JSON-to-metrics export semantics by matching `/pdp/hot-path/status`
     against `/pdp/hot-path/metrics` in CI
     (`test_pdp_hot_path_metrics_exposes_prometheus_text`).
   - add a live host verification script to validate status <-> metrics consistency
     against real status payloads:
     `scripts/host/verify_hot_path_observability.sh`.
3. **Apr 2026 (late): degraded-edge and adversarial drill matrix**
   - completed: true
   - status: **drill matrix enforced in CI + host mode**, and the
     commerce-slice binding (product_ref / workflow join keys) is now a
     first-class assertion in the matrix.
   - expand the repeatable verification slice to include:
     stale-graph + stale telemetry (RCT hot-path drill matrix),
     intermittent-connectivity (synthetic flaky transport benchmark),
     coordinate tamper (agent action gateway coordinate mismatch),
     and replay-injection / authority mismatch (replay router tamper surfaces).
   - **commerce-shaped drill matrix** (`tests/test_rct_commerce_drill_matrix.py`,
     marked `rct_commerce_drill`): runs stale-graph, PKG dependency outage,
     approval-store outage (503 `dependency_unavailable`),
     approval-resolver raise (fail-closed), Redis bus outage fallback,
     commerce adapter HTTP timeout, coordinate tamper, and
     cross-product replay injection through the
     `seedcore.agent_action_gateway.v1` contract; every drill asserts the
     response `forensic_linkage` carries `product_ref`, `order_ref`,
     `quote_ref`, `workflow_join_key`, `audit_id`, and `request_id`.
     Replay-router tamper drills also assert `workflow_join_key` on
     verify/replay/artifact surfaces.
     `_build_forensic_linkage` in
     `src/seedcore/api/routers/agent_actions_router.py` is the single
     plumbing point — aligned with
     `src/seedcore/adapters/rct_gateway_correlation.py` so gateway join
     keys and replay lookup keys stay deterministic even on
     deny / quarantine outcomes.
   - enforce the drill bundle explicitly in CI and host mode via:
     `scripts/ci/q2_degraded_edge_drill_matrix.sh` and
     `scripts/host/verify_q2_degraded_edge_drill_matrix.sh`.
   - can move toward next check.
4. **May 2026 (early): Agent Action Gateway productization**
   - completed: true
   - status: **reference + commerce adapters, correlation contract, MCP evaluate
     tool, tests, and host verifier are in-repo** (2026-04-03).
   - reference adapter for the existing SeedCore MCP/plugin surface: builds v1
     gateway evaluate payloads without exposing internal coordinator schemas
     (`rct_agent_action_gateway_reference_adapter.py` + MCP
     `seedcore.agent_action.evaluate`).
   - narrow Shopify-Sandbox-shaped commerce adapter maps the canonical transaction
     story into `asset.product_ref`, `asset.quote_ref`,
     `asset.declared_value_usd`, and `forensic_context.fingerprint_components.economic_hash`
     (`shopify_sandbox_commerce_adapter.py`).
   - deterministic request -> decision -> replay linkage: correlation helper ties
     `request_id` to `intent_id`, UUID-safe `audit_id` when needed, and
     `replay_lookup` / `replay_state` for pending vs governed-audit-backed replay
     (`rct_gateway_correlation.py`); validated in unit tests and
     `verify_agent_action_gateway_productization_real_calls.*`.
5. **May-Jun 2026: edge telemetry and closure progression**
   - completed: true
   - status: **signed `telemetry_refs` on gateway closure, evidence bundle, and
     forensic materialization; schema drift test; extra envelope + RCT shared
     refs** (2026-04-06).
   - export JSON schema for `EdgeTelemetryEnvelopeV0`
   - persist envelope refs on the governed receipt / forensic path
   - extend fixtures so Q3 handshake work can rely on signed telemetry inputs
   - keep the schema exporter and checked-in schema file in sync as the
     contract evolves

6. **Jun 2026 onward: Gemini-visible read tools**
   - completed: true
   - status: **`GEMINI_MINIMAL_READ_ONLY_BUNDLE` + `/info` metadata; hot-path
     status aligned to verification read wrapper; docs/skills updated** (2026-04-06).
   - publish a minimal read-only tool bundle for verification queue, detail,
     replay, runbook lookup, and hot-path status/metrics
   - keep those tools narrow and operator-safe; they should expose the same
     frozen contracts rather than add new logic

Recommended dependency rule:

- finish item 1 before broadening environment blast radius
- run items 2 and 3 in parallel once CI gates are stable
- items 5 and 6 (edge telemetry closure refs + minimal Gemini read bundle) are
  complete as of 2026-04-06; next sequencing focus shifts to the following
  numbered priorities in this document, assuming operator and observability
  surfaces remain the first line of defense for external-agent failures

### Explicit Sidecar

The VLA track in
[vla_2026_optimizations.md](vla_2026_optimizations.md)
remains sidecar for this phase.

It may continue in parallel as research or future-performance work, but it is
not on the critical path for the must-win demo or for Slice 1 runtime
hardening.

### 1. Irrefutable Trust Anchors

SeedCore already issues bounded execution authority. The next step is to make
the trust boundary cryptographically defensible in environments where spoofing,
repudiation, or internal tampering are real concerns.

What to build:

- move critical HAL and evidence-signing flows behind TPM, HSM, or cloud
  KMS-backed signers where practical
- bind every high-value action to a device or node fingerprint, including agent
  identity, hardware attestation handle, and current physical context when
  available
- evolve execution tokens into transaction-specific authority:
  - valid for one workflow instance
  - valid for one asset or product identity
  - valid for one physical zone, shelf, or coordinate scope
  - invalid outside the expected handoff context
- make signer profile selection explicit across PDP, evidence, and
  transition-receipt paths
- support optional external anchoring for selected high-value receipts into a
  transparency log or enterprise audit ledger
- separate internal operational audit from externally shareable verification
  receipts
- define security validation gates for trust-critical surfaces such as signer
  paths, receipt verification, replay verification, and revocation flows
- treat targeted external review and adversarial testing of the trust boundary
  as part of release readiness for high-stakes workflows

Why this is feasible:

- this can start with cloud KMS-backed server-side signing
- it can use TPM-backed or device-bound signing for selected edge nodes instead
  of requiring universal hardware redesign
- transaction-specific scoping can start with asset id + zone id + policy
  snapshot binding before full coordinate granularity is required everywhere
- external anchoring can begin only for high-stakes transitions rather than
  every low-risk action
- security validation can begin with scoped threat modeling and targeted
  penetration testing of the cryptographic and replay boundary instead of a
  broad platform-wide certification effort

Strategic result:

SeedCore will move trust from application claims to cryptographically anchored
execution evidence and measurably reduce spoofing, replay, and revocation risk
at the execution boundary.

### 2. Multi-Party Execution Governance

The current runtime already supports deny-by-default, quarantine, and governed
receipts. The next step is to govern actions that cross organizational,
approval, and physical verification boundaries.

What to build:

- delegated authority chains across organizations, facilities, zones, devices,
  and agents
- buyer-side and seller-side handshake validation for selected high-value
  transfers
- dual authorization for selected high-risk transitions
- multi-signature release rules where:
  - the human request or approval is signature one
  - the physical verification event is signature two
  - funds or final transfer release happens only after both land
- explicit break-glass paths with elevated evidence obligations
- co-signed approvals for exceptional or blocked workflow overrides
- signed approval and delegation capture as part of the same governed receipt
  chain

Why this is feasible:

SeedCore does not need to model every legal or commercial workflow immediately.
It should start with a small number of high-value patterns:

- release from quarantine
- transfer of custody for a restricted lot
- physical verification before economic settlement
- emergency override of a blocked workflow

Multi-party governance is the canonical demo workflow, but initial
productionization should still prioritize trust hardening for the artifacts
that support that workflow.

Strategic result:

SeedCore becomes more than an internal policy gate. It becomes a runtime for
replayable, governed multi-party action with explicit release authority.

### 3. The Asset-Centric Hot Path And Forensic Ledger

The strongest technical discipline for the next stage is keeping the real-time
decision path small, deterministic, and operationally useful while preserving
enough state to replay failures like a flight recorder.

What to build:

- a compiled Decision Graph for synchronous PDP evaluation
- strict inclusion of only latency-critical entities:
  - principals
  - devices
  - facilities
  - zones
  - lots, batches, and twins
  - active custody state
  - live policy context
- versioned graph snapshots for reproducible decisions
- cached or precompiled path evaluation for the most common action types
- first-class quarantine and trust-gap outcomes
- synchronized state capture between governed digital state and physical
  execution state for the canonical workflow:
  - agent request and reason trace hash
  - approval envelope state
  - economic transaction state
  - twin mutation state
  - physical telemetry state
- a forensic block or ledger entry that binds:
  - decision and approval hashes
  - product or asset identity
  - physical location evidence
  - edge telemetry references
  - transition and policy receipt ids
  - replay ordering metadata
- critical-path tracing and decision-path visibility for the governed execution
  path, especially registration submission, PDP evaluation, signer selection,
  replay publication, and verification
- focused dashboards, trust-anomaly detection, and alerting for authz-graph
  health, deny and quarantine spikes, snapshot mismatches, signer failures,
  replay verification failures, and stuck registration workflows

Why this matters:

SeedCore should not behave like an academic graph platform that turns every
issue into a generic deny. In real operations, the correct governed outcome is
often:

- isolate the asset
- preserve state
- require manual review
- escalate an evidence or telemetry gap

The point is not tracing every microsecond. The point is giving operators
visibility into why actions were allowed, denied, quarantined, or slowed and
whether the runtime is still preserving its deterministic contract.

Strategic result:

SeedCore keeps the hot path explainable, fast, and deterministic even as the
broader ontology grows and the replay burden increases.

### 4. Productize The Verification Surface

The runtime's trust value has to be visible, not just internally correct.

What to build:

- signed, governed receipts for every high-value allow, deny, or quarantine
  outcome
- verification pages or APIs that can replay the full receipt chain from
  approval through transfer verification
- operator-facing workflow status APIs for Restricted Custody Transfer that
  expose:
  - prerequisite state
  - approval state
  - transfer readiness
  - governed tracking timeline
- a workflow-specific proof surface for Restricted Custody Transfer, with
  registration intake treated as an upstream prerequisite rather than the
  product center
- business-readable trust states such as verified, quarantined, rejected, and
  review required rather than raw graph-routing, signer, or replay failure
  details
- asset-centric forensic views tying together:
  - decision hash
  - policy snapshot
  - principal identity
  - custody transition
  - telemetry references
  - signature provenance
  - economic settlement status
- an audit-trail UI that can eventually show, side by side:
  - the natural-language or agent request
  - the digital transaction trail
  - the physical replay or evidence timeline
- public or partner-visible verification surfaces restricted to approved
  stakeholders

Why this is feasible:

SeedCore does not need a universal trust portal on day one. It needs a narrow
but impressive proof surface for one wedge:

- one asset class
- one transfer chain
- one evidence model
- one replay view

It can also start with one governed intake workflow that already matches the
trust story:

- one registration-to-transfer chain
- one operator status view
- one monitored path from prerequisite approval to transfer to replay
  verification

It should not begin as a generic admin dashboard. It should begin as a governed
operational surface for one high-trust workflow.

Strategic result:

SeedCore stops looking like a backend-only control layer and becomes a visible
trust product.

Phase D should therefore be executed as one constrained product wedge rather
than as a broad UX program.

The execution rules for this phase are:

- one asset class
- one transfer chain
- one evidence model
- one replay view
- one operator status surface

The core deliverables should be framed as product artifacts, not just backend
capabilities:

- provable outcomes: governed receipts and replay-verifiable receipt chains
- business-readable state translation: verified, quarantined, rejected, review
  required
- operator workflow visibility: prerequisite-to-transfer lifecycle for
  Restricted Custody Transfer
- asset-centric forensic context: a single view that binds policy, identity,
  custody, telemetry, settlement, and signature provenance
- external verification surface: a partner-visible trust page or API for
  approved stakeholders only

Authoritative Q2 product specification for this phase:

- [q2_2026_audit_trail_ui_spec.md](q2_2026_audit_trail_ui_spec.md)

If Phase D expands beyond that narrow proof surface before the canonical
workflow is demonstrably credible, it will dilute the product story and slow
the trust proof.

## 12-18 Month Execution Program

The next stage is best presented as a staged execution program rather than a
giant future-state promise.

It should be described and managed as one program that makes governed execution
defendable, operable, and usable in production.

### Phase A: Trust Hardening

Focus:

- KMS, TPM, or HSM-backed signing for selected receipt paths
- clearer signer provenance and signer policy profiles
- transaction-scoped authority binding to asset identity and physical scope
- optional external anchoring for high-value events
- verifier tooling for signature and signer-chain inspection
- security validation gates for signer, replay, and revocation surfaces before
  claiming enterprise-grade trust properties

Success condition:

SeedCore can produce receipt chains that are difficult to spoof, difficult to
erase, and easy to verify.

Current closure checkpoint for strict TPM attestation path:

- generate strict TPM fixtures with real AK cert + endorsement root + signed
  TPM quote: `python scripts/tools/generate_strict_tpm_receipt_fixtures.py`
- verify strict receipt offline with trust bundle only: `cargo run -q -p seedcore-verify -- verify-receipt --artifact fixtures/receipts/restricted_transition_receipt_strict_tpm_artifact.json --trust-bundle fixtures/receipts/restricted_transition_trust_bundle_strict_tpm.json`
- keep `seedcore-verify` strict fixture regression green
  (`verify_restricted_transition_receipt_strict_attestation_with_real_fixture`)
  before declaring Phase A mathematically closed
- operationalize fleet rollout using the TPM checklist and drills in
  [tpm_fleet_rollout_runbook.md](tpm_fleet_rollout_runbook.md)

### Phase B: Multi-Party Governance

Focus:

- delegated authority chains
- dual authorization
- human-plus-physical-verification multi-signature release rules
- break-glass workflows with elevated evidence
- cross-organization approval paths

Success condition:

SeedCore can govern one or two high-risk transitions that require more than one
approving authority and can prove why release authority was granted.

### Phase C: Operational Decision Engine And Forensic State Store

Focus:

- compiled decision graph discipline
- quarantine and trust-gap state as first-class outcomes
- fast-path evaluation and shard-aware cache routing
- deterministic explanation output for hot-path decisions
- critical-path tracing, dashboards, and alerting for trust-runtime failures and
  degraded decision readiness
- synchronized forensic-state capture linking policy, telemetry, and settlement
  state to the same governed event

Success condition:

SeedCore can answer real authorization questions quickly and explainably
without pulling broad enrichment context into the synchronous path, while still
recording enough converged state to replay the action later.

### Phase D: Verification Product Surface

Focus:

- governed receipts as the visible product artifact
- replay and trust-page UX for operators, auditors, and partners
- asset-centric trust history
- API and UI proof layer for third-party verification
- operator-facing status tracking and proof monitoring for Restricted Custody
  Transfer, with registration intake treated as its prerequisite chain
- business-readable trust-state translation for workflow outcomes and failure
  classes
- an audit-trail view that can correlate request, digital transaction, and
  physical replay evidence

Default build order:

1. freeze the workflow-specific status vocabulary and receipt-chain projection
2. expose operator-facing status APIs for prerequisite, approval, and transfer
   readiness
3. publish the asset-centric forensic view for the canonical transfer chain
4. expose partner-visible replay or trust-page verification for approved
   stakeholders
5. implement the four Q2 UI screens in order: transfer queue, transfer detail,
   asset-centric forensics, replay/verification view

Success condition:

SeedCore can show an externally legible chain of decision, execution, economic
settlement, and physical evidence for one specific high-value asset workflow,
with a business-readable status surface and replay-verifiable receipts that
approved third parties can inspect.

## Phase Done Means

- Phase A is done when the canonical transfer flow emits signed artifacts with
  verifier output, tamper checks, signer provenance, and device-bound authority
  binding that can be demonstrated end to end.
- Phase B is done when Restricted Custody Transfer can require dual approval and
  deterministic physical verification before releasing the final transfer or
  settlement path.
- Phase C is done when the PDP returns a bounded-latency explanation payload and
  the runtime preserves a replayable forensic state chain for the canonical
  workflow.
- Phase D is done when the canonical transfer flow has an externally legible
  proof surface showing business-readable state, artifact lineage, settlement
  linkage, and replay verification.

## Killer Demonstration

The roadmap should stay anchored to one demonstration that proves the category.

The best next-stage demonstration is:

**Restricted Custody Transfer with a Forensic Handshake: a high-value transfer
that requires deterministic policy evaluation, delegated authority, hardware
fingerprints, physical verification, and replayable third-party proof.**

If SeedCore can demonstrate that end to end, it will tell a much more credible
story than a broad list of trust claims.

The immediate next technical step for that demonstration is to freeze the
approval, authorization-output, forensic-block, and verification-surface
contracts for the next dual-authorization workflow before broad UI or signer
integration work begins. See
[killer_demo_execution_spine.md](archive/historical/killer_demo_execution_spine.md)
and
[next_killer_demo_contract_freeze.md](archive/historical/next_killer_demo_contract_freeze.md).

Phase 0 closure is now machine-checkable through
[phase0_contract_freeze_manifest.json](phase0_contract_freeze_manifest.json)
with the validation gate
`python scripts/tools/verify_phase0_contract_freeze.py`.

The current engineering sign-off state for that demo, including what is passed
offline and what still genuinely demands a live runtime proof, now lives in
[restricted_custody_transfer_demo_signoff_report.md](archive/historical/restricted_custody_transfer_demo_signoff_report.md).

The recommended multi-language boundary plan for that work now lives in
[language_evolution_map.md](language_evolution_map.md).

The concrete service/CLI-first Rust kernel proposal for that same track now
lives in
[rust_workspace_proposal.md](rust_workspace_proposal.md).

For post-2026 high-vertical staging (SeedCore trust boundary + IGX/Jetson
physical execution boundary), see:
[seedcore_2027_high_vertical_direction.md](seedcore_2027_high_vertical_direction.md).

## Red-Team Program

The forensic-ledger story only becomes credible if the failure modes are
deliberately exercised.

The first required adversarial drills should be:

- the man-in-the-middle physical redirect:
  - intercept coordinate or zone data
  - attempt to redirect the robot to the wrong shelf or handoff point
  - prove the mismatched fingerprint or scope binding blocks final settlement
- the authority leak:
  - simulate session-token theft or agent replay
  - prove SeedCore can identify the exact injection point and contain the blast
    radius
- the physical double-spend:
  - attempt to pick two items while paying or settling for one
  - prove telemetry or weight mismatch produces quarantine and replay-visible
    discrepancy

These should be release-gating drills for the canonical workflow, not optional
"security extras."

## Schema Recommendation

SeedCore should treat the first **Forensic Block** as a product-facing evidence
contract, not only an internal transport message.

Recommended choice:

- canonical external and replay-export shape: JSON-LD
- optional internal transport mirror for high-throughput node-to-node exchange:
  Protobuf

Rationale:

- JSON-LD fits the verification, trust-page, and third-party audit surface
  already present in the repo
- Protobuf can still be added later for Ray/Kubernetes transport after the
  external field set stabilizes
- choosing JSON-LD first avoids creating one internal truth schema and a second
  audit schema that drift immediately

## Messaging Guardrails

The next-stage narrative should stay ambitious without overclaiming.

Better positioning:

- "SeedCore is productizing irrefutable governed execution and forensic replay."
- "SeedCore is positioning to become a verifiable agentic ledger for
  high-trust, multi-party workflows."
- "SeedCore moves trust from application claims to cryptographically anchored
  execution evidence."
- "SeedCore governs execution within an environment; it is not a perimeter
  defense product."
- "SeedCore is a trust runtime with deterministic policy decisions and
  replayable proof, not a threat-detection engine."

Claims to avoid:

- "only viable execution runtime for 2026"
- "legally binding digital contracts" as a near-term product claim
- "full autonomous commerce stack" before the narrow wedge is demonstrably
  credible
- "cybersecurity platform" without explaining the execution-governance
  distinction
- "threat detection" or "threat intelligence" as if those were the PDP's core
  product jobs

More grounded alternatives:

- "well aligned with emerging provenance, auditability, and product-passport
  requirements in regulated supply chains"
- "governed, co-signed execution receipts for high-trust multi-party workflows"
- "a runtime for cryptographically defensible, replayable governed execution"
- "a trust runtime that decides admissibility and proves why a governed action
  was allowed"

Reference:

- [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md)
  is the canonical note for explaining this category boundary

## Practical Guidance

When the root README mentions roadmap direction, it should stay short and point
here.

This document should be updated when one of two things changes:

- the baseline has materially improved and a "future" item is now present
- the wedge strategy changes and the next-stage narrative needs to be tightened
