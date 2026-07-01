# SeedCore Development Docs

Date: 2026-06-29
Status: Canonical entrypoint for `docs/development/`

This page is the "read this first" map for the development docs. It organizes
the directory around one progression:

```text
final ambition -> current wedge -> what is done -> current status -> next work
```

## 1. Final Ambition

SeedCore's long-range ambition is to become the **trust slice** for
high-consequence autonomous work, especially commerce workflows where economic
intent (order, quote, value) must stay bound to physical custody, scoped
execution, and replayable proof. Humans and agents propose actions; SeedCore
decides what is admissible under pinned policy and delegated authority; physical
systems emit evidence; and the runtime preserves a forensic chain that can
survive adversarial review.

Canonical north-star references:

- [`north_star_autonomous_trade_environment.md`](north_star_autonomous_trade_environment.md)
  (local Kafka rollout plan: [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md))
- [`seedcore_north_star_architecture_v1.2.0.pdf`](assets/seedcore_north_star_architecture_v1.2.0.pdf)
  - visual companion deck; the Markdown North Star remains canonical
- [`rtx_spark_autonomous_era_investigation.md`](rtx_spark_autonomous_era_investigation.md)
  - market-signal memo for why local autonomous applications, RTX Spark /
    DGX-class compute, and frontier agents accelerate the need for governed
    execution without becoming authority sources
- [`seedcore_2027_high_vertical_direction.md`](seedcore_2027_high_vertical_direction.md)
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md)
  - canonical explanation of why SeedCore is a trust runtime rather than a
    traditional cybersecurity product

## 2. Current Program Center (Commerce Fulfillment Wedge)

The current product wedge is **Agent-Governed Restricted Custody Transfer**:
the governed handshake between a digital transaction and a physical custody
transition. It is not generic robotics and not a broad trust platform.

That means the active docs should be read through one question:

- does this move the dual-approved, scope-bound, replay-verifiable transfer
  workflow closer to a pilotable commerce trust product (economic identity +
  physical scope + policy + proof in one chain)?

**Commerce integration spine (repo, not aspirational):**

- Narrow **Shopify-Sandbox-shaped** mapping into gateway asset and fingerprint
  fields (`product_ref`, `quote_ref`, `declared_value_usd`,
  `forensic_context.fingerprint_components.economic_hash`):
  [`src/seedcore/adapters/shopify_sandbox_commerce_adapter.py`](../../src/seedcore/adapters/shopify_sandbox_commerce_adapter.py)
- Reference evaluate path that composes strict `seedcore.agent_action_gateway.v1`
  payloads from simplified inputs (including optional commerce transaction):
  [`src/seedcore/adapters/rct_agent_action_gateway_reference_adapter.py`](../../src/seedcore/adapters/rct_agent_action_gateway_reference_adapter.py)
- External contract and MCP evaluate surface:
  [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md),
  [`gemini_phase1_quickstart.md`](gemini_phase1_quickstart.md)
- AP2 / payment-protocol boundary and alignment memo:
  [`ap2_seedcore_rct_alignment_memo.md`](ap2_seedcore_rct_alignment_memo.md)
- Strategic delegation thesis and frontier alignment:
  [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md)
- Recursive delegation control-plane architecture:
  [`agentic_delegation_control_plane.md`](agentic_delegation_control_plane.md)
- Execution-token lifecycle and capability hardening:
  [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- Legible local advisory memory:
  [`legible_local_memory_vault.md`](legible_local_memory_vault.md)

**Architecture posture for the supporting ecosystem:**

The PDP remains internal, synchronous, deterministic, and stateless at decision
time. The infrastructure around it should evolve in these specific directions:

- Sufficient context is a hard precondition for execution authority, not a
  retrieval-confidence score. Before `allow`, the request package must be
  schema-complete, cryptographically verifiable where policy requires it,
  causally fresh, SLA-compliant, and replay-bound through evidence such as
  `state_binding_hash`.
- Signed Context Envelopes and caveat-style attenuation, informed by Biscuit and
  Macaroons, push cryptographically verifiable context into requests instead of
  making the PDP perform hot-path user-attribute lookups.
- Causality tokens, informed by SpiceDB `ZedToken` and Zanzibar zookie
  semantics, let a request demand context at least as fresh as the user's last
  relevant action, closing "New Enemy" and "Ghost Resource" races.
- Signed mutation receipts sharpen those causality tokens into replayable
  watermarks: the PDP may evaluate only after the receipt signature, scope,
  session binding, token epoch, and local-view watermark prove the request is at
  least as fresh as the admitted upstream mutation.
- CDC-backed subscribed local views, informed by Debezium-style architectures,
  keep approval, custody, delegation, resource, and edge state near the PDP for
  synchronous low-latency reads.
- Zanzibar-style external graph PDPs stay future-facing only. They may matter
  for massive relationship scale, but the current wedge keeps the default hot
  path compiled, near-local, and focused on restricted custody, evidence, and
  execution-token semantics.
- Authorization graph engine upgrades are benchmark-gated by
  [ADR 0011](../architecture/adr/adr-0011-benchmark-gated-authz-graph-engine-evolution.md):
  tuple import/export and structural benchmarks come before path flattening,
  Ray hot-path promotion, CSR/CSC layouts, or Rust/PyO3 graph kernels.

Start here for the active spine:

1. [`current_next_steps.md`](current_next_steps.md) - what is done now, current
   status, and immediate execution order.
2. [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md) - stage
   goals, workstreams, sequencing, and canonical positioning.
3. [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) - current
   verification/operator product surface and contract-level UX behavior (including the Section 4.1 operator legibility layer with queue signals, replay verdict, and the deterministic + optional LLM copilot API).
4. [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md) -
   "Visualize It" development step for an advanced forensic replay UI that
   makes execution steps, policy snapshots, telemetry hashes, signer chains,
   and timeline reproduction inspectable without adding new authority.
5. [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md) -
   collectible rare-shoe transfer as a commercial vertical scene on the same
   RCT contract: authentication registration first, bounded custody authority
   second, replayable proof last.
6. [`ap2_seedcore_rct_alignment_memo.md`](ap2_seedcore_rct_alignment_memo.md) -
   boundary memo for using AP2 as the upstream agent-payment protocol while
   keeping SeedCore focused on custody, evidence, and replay-valid closure.
7. [`policy_graph_builder_implementation_plan.md`](policy_graph_builder_implementation_plan.md) -
   technical memo for turning customer business rules into executable,
   testable Policy Knowledge Graphs that compile into PDP rules, authority
   constraints, evidence requirements, reason codes, and replay fixtures.
8. [`policy_governed_rag_research_adoption_review.md`](policy_governed_rag_research_adoption_review.md) -
   adoption review for policy-governed RAG research. Use it with ADR 0008, ADR
   0009, and the RAG trace contract when turning document or memory retrieval
   into signed, replayable, side-channel-safe evidence without making RAG,
   receipts, or model-selected citations authority-bearing.
9. [`kg_rag_research_reference.md`](kg_rag_research_reference.md) -
   KG / GraphRAG research reference for efficient graph retrieval,
   path-centric evidence, agentic graph query tools, and graph foundation
   models. Use it as roadmap input for governed retrieval only; graph-derived
   context, paths, Cypher answers, and inferred KG edges remain non-authority
   until promoted through PDP, evidence, verifier, and replay boundaries.
10. [`zero_cold_start_policy_evolution_ultra.md`](zero_cold_start_policy_evolution_ultra.md) -
   ULTRA design reference mapping inductive relational reasoning into future
   zero-cold-start policy analysis. Treats link predictions as
   non-authoritative policy package, fixture, or diagnostic proposals that must
   still pass review, schema validation, fixture testing, snapshot compilation,
   PDP, token, evidence, and verifier boundaries.
11. [`gated_action_dx_layer.md`](gated_action_dx_layer.md) - lightweight DX spec
   for declaring governed action boundaries without making developers or coding
   agents manually wire PDP calls, execution tokens, evidence bundles, verifier
   outcomes, and replay proof chains. **MVP implemented and targeted-test
   validated:** the SDK surface (`src/seedcore/sdk/gated_action.py`) provides
   `@gated_action`, `using_evaluator`, `set_executor`, and `GovernedResult` for
   RCT shadow and guarded enforce flows; the MCP helper
   `seedcore.agent_action.check_policy` exposes explicit-authority preflight
   checks; and `src/seedcore/sdk/schema_exporter.py` exports path-qualified
   gated-action manifests for PDP/PKG scaffolding.
12. [`seedcore_flywheel_harness.md`](seedcore_flywheel_harness.md) -
   harness guardrail for the energy flywheel: deterministic gates, circuit
   breaker posture, legible cycle artifacts, and the rule that adaptive tuning
   never becomes execution authority.
13. [`agent_system_eval_schedule.md`](agent_system_eval_schedule.md) -
   staged schedule for turning AI-system eval discipline into SeedCore-native
   regression fixtures across decision, policy, forensic, and agent-governance
   behavior without making eval tooling an authority source.
14. [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md) -
   bounded governance-learning plan for Window G/H-K: strict
   `GovernanceLearningSampleV1` records, deterministic teacher labels,
   conservative advisory students, isolated live-shadow advisory telemetry, and
   future XGBoost/HALT/refinement/simulation work that remains non-authoritative.
15. [`statistical_model_audit_shadow_contract.md`](statistical_model_audit_shadow_contract.md) -
   shadow-only contract for using statistical model audits, including
   Regularized f-Divergence Kernel Tests, as promotion and review evidence
   without changing PDP, `ExecutionToken`, replay, or `RESULT_VERIFIER`
   authority.
16. [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md) -
   implementation contract for making hardware-bound signer identity, signed
   telemetry, asset anchors, zone evidence, and verifier replay central to
   physical execution proof.
17. [`physical_telemetry_processing_contract.md`](physical_telemetry_processing_contract.md) -
   development contract for turning multi-rate embodied telemetry into
   replay-grade physical episode traces, alignment quality gates, digital-twin
   parity checks, and LeRobot-compatible sidecar exports without making data
   processing an authority source.
18. [`virtual_nfc_simulation_plan.md`](virtual_nfc_simulation_plan.md) -
   implemented simulation-first dynamic NFC challenge-response fixture lane for
   rare-shoe RCT, including fail-closed replay, stale-scan, wrong-asset, and
   tamper-state outcomes without treating mock NFC evidence as authority.
19. [`persistent_counter_ledger_plan.md`](persistent_counter_ledger_plan.md) -
   implementation track for the explicit, anchor-scoped monotonic NFC counter
   ledger that prevents replay across workflows without making the pure NFC
   verifier instantiate storage.
20. [`kms_ntag_transition_plan.md`](kms_ntag_transition_plan.md) -
   staged transition plan for KMS-backed NTAG 424 DNA verification as a
   profile-specific shadow adapter before any production hardware enforcement.
21. [`freshness_sla_edge_stress_schedule.md`](freshness_sla_edge_stress_schedule.md) -
   staged stress schedule for establishing freshness-SLA metrics across RCT
   fixtures, Jetson prototype edge, IGX/T5000 trusted edge, and robotics
   handoff environments without treating Spark/DGX workstations as physical
   closure authority.
   - Read with ADR 0001's sufficient-context rule: stale local views, missing
     signed envelopes, missing required fields, and missing `state_binding_hash`
     inputs are fail-closed authorization conditions, not retriable LLM context
     gaps.
22. [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md) -
   strategic memo connecting SeedCore's implemented delegation path to
   cryptographic multi-hop authority, WIMSE-style agent identity, AIP/Biscuit
   capability attenuation, ReBAC graph paths, SCITT-style evidence, and
   hardware-backed intent.
23. [`agentic_delegation_control_plane.md`](agentic_delegation_control_plane.md) -
   control-plane memo for recursive agent delegation: root context anchoring,
   signed agent identity/capability credentials, per-hop attenuation, visible
   tool calls, out-of-band approval, child-run closure, and replayable
   delegation lineage.
24. [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md) -
   lifecycle memo for `ExecutionToken` as a short-lived deterministic
   capability artifact, including mint/withhold semantics, TTL bounding,
   constraint freezing, delegated subtokens, replay, quarantine, and candidate
   hardening with DPoP, RATS, Macaroons/Biscuit, IEEC, and outbox reliability.
25. [`legible_local_memory_vault.md`](legible_local_memory_vault.md) -
   development memo for an Obsidian-compatible Markdown memory vault that makes
   advisory memory, admitted facts, rejected claims, and operator notes readable
   and editable without making memory an authority source.
26. [`persistent_twin_settlement_real_world_ai_operations.md`](persistent_twin_settlement_real_world_ai_operations.md) -
   distilled reference for persistent twin settlement as a real-world AI
   reliability pattern: pluggable settlement protocols, proof-vector
   accumulation, append-only compensation, and cryptographic integrity for
   evidence.
27. [`gvisor_and_sandbox_hardening_strategy.md`](gvisor_and_sandbox_hardening_strategy.md) -
   sandbox hardening and verifier bridge strategy: subprocess-first, PyO3-ready
   verifier bridge architecture, and phased container runtime sandboxing rollout.
28. [`second_hand_luxury_trade_evolution.md`](second_hand_luxury_trade_evolution.md) -
   sidecar vertical reference for mapping the Restricted Custody Transfer (RCT)
   runtime baseline to high-value second-hand luxury trading without changing
   the current authority path.



## 3. Stage Goals And Status Map

This table is the shortest answer to "what stage are we in?"

| Stage | Goal | Current status | Canonical docs |
| :--- | :--- | :--- | :--- |
| 0. Runtime substrate | Build the Python/Ray execution and agent foundation | Done baseline | [`archive/historical/project_stage_milestone_summary.md`](archive/historical/project_stage_milestone_summary.md) |
| 1. Zero-trust execution boundary | Make all high-risk actions tokenized, revocable, and receipt-bound | Materially implemented | [`current_next_steps.md`](current_next_steps.md) |
| 2. PKG policy and authz graph | Pin decisions to a snapshot and compile a deterministic hot-path graph | Implemented, still being hardened | [`pkg_authz_graph_rfc.md`](pkg_authz_graph_rfc.md), [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md), [`pdp_authz_graph_staging_rollout.md`](pdp_authz_graph_staging_rollout.md), [`authz_graph_engine_evolution_plan.md`](authz_graph_engine_evolution_plan.md) |
| 3. Replay and proof surface | Expose replayable verification so third parties can inspect outcomes | Implemented | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md), [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md) |
| 4. RCT contract freeze | Lock one must-win workflow, artifact chain, and business-state truth table | Done for Slice 1 | [`archive/historical/killer_demo_execution_spine.md`](archive/historical/killer_demo_execution_spine.md), [`archive/historical/next_killer_demo_contract_freeze.md`](archive/historical/next_killer_demo_contract_freeze.md) |
| 5. Trust hardening | Prove signer provenance, TPM/KMS policies, and operational drills | Checkpoint crossed, not fully closed | [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md), [`tpm_fleet_rollout_maturity_decision_memo.md`](tpm_fleet_rollout_maturity_decision_memo.md) |
| 6. Multi-party governance | Make approval envelopes and dual-control workflows authoritative end to end | Partially implemented | [`archive/historical/next_killer_demo_contract_freeze.md`](archive/historical/next_killer_demo_contract_freeze.md), [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md) |
| 7. Hot-path operability | Promote `shadow -> canary -> enforce` with parity, latency, and rollback evidence | Contract + observability implemented; **remote Kind topology green** for core gates and drills; full **verification API inside cluster** still the open topology milestone | [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md), [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md), [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md), [`kube_topology_validation_q2_signoff.md`](kube_topology_validation_q2_signoff.md) |
| 8. Verification product surface | Make operator/replay UX contract-driven and legible without weakening proof | Advanced and active; Studio follow-on drafted | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md), [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md) |
| 9. Rust proof kernel | Move strict verification and authority-bearing kernels toward deterministic Rust packages | Scaffolded and growing | [`rust_workspace_proposal.md`](rust_workspace_proposal.md), [`language_evolution_map.md`](language_evolution_map.md) |
| 10. External agent boundary | Expose a stable agent-action gateway and public SDK for developer convenience | **v1 productized + Agent Self-Regulation baseline landed**: `@gated_action` shadow/enforce wrapper, SDK preflight, telemetry checks, thread-local evaluator/executor utilities, explicit-authority MCP `check_policy`, schema exporter scaffolding, reference adapters, and MCP evaluate path | [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md), [`gated_action_dx_layer.md`](gated_action_dx_layer.md) |
| 11. Sidecar innovation tracks | Keep robotics/VLA/WAM and deep twin research from diluting the commerce RCT story | Sidecar: intake/twin/world-action tracks support the wedge as **upstream evidence**, not a second product center | [`vla_2026_optimizations.md`](vla_2026_optimizations.md), [`world_action_model_architecture_reference.md`](world_action_model_architecture_reference.md), [`source_registration_architecture.md`](source_registration_architecture.md), [`persistent_twin_service_track.md`](persistent_twin_service_track.md) |
| 12. Governance-aware learning | Introduce distillation, abstention tuning, proof refinement, simulation RL, and statistical model audits as bounded trust-slice components, wired as a four-node governed self-improvement loop (Scenario Generator, Governance Reward Scorer, Governance Learning Sample Store, Advisory Student) over a **typed verdict taxonomy** (`clean_allow` / `clean_deny` / `near_miss_*` / `quarantine` / `escalate` / `verification_mismatch` / `stale_context`) rather than a scalar reward | Window G schema/sample contracts and Window H offline + opt-in live shadow advisory contract implemented; still never authority-bearing | [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md), [`agent_system_eval_schedule.md`](agent_system_eval_schedule.md), [`statistical_model_audit_shadow_contract.md`](statistical_model_audit_shadow_contract.md), [`current_next_steps.md`](current_next_steps.md) |
| 13. AI-led self-healing | Let assistants diagnose degraded-edge failures, reproduce fixtures, propose scoped patches, run gates, and prepare reviewable promotions | New guarded workstream; no direct production mutation, quarantine clearance, or enforce promotion | [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md), [`current_next_steps.md`](current_next_steps.md) |

## 4. What Is Done

Treat these as real repo capabilities, not aspirational roadmap items:

- governed execution baseline with `ActionIntent`, short-lived
  `ExecutionToken`, HAL enforcement, revocation, and emergency cutoff
- signed transition receipts, evidence bundles, replay surfaces, and
  verification workflows
- Slice 1 Restricted Custody Transfer sign-off bundle and contract freeze
- Q2 verification namespace and operator/proof surfaces under
  `/api/v1/verification/*`
- hot-path promotion semantics, parity evidence persistence, Prometheus status
  export, and rollback triggers
- Agent Action Gateway v1 schema hardening, idempotency, **commerce-shaped**
  field binding (reference + Shopify-sandbox adapters), and MCP evaluate path
- **Gated Action DX MVP and Agent Self-Regulation surface**: `@gated_action`
  now supports shadow and guarded enforce mode at
  `src/seedcore/sdk/gated_action.py`. Enforce mode requires an allow decision
  with an `ExecutionToken` and a configured executor before business logic can
  run, preserving fail-closed behavior at the SDK boundary. Targeted tests cover
  fail-closed evaluator/executor paths, thread-local isolation, telemetry
  evidence validation, no-execute shadow behavior, and post-execution closure
  failures.
- **Explicit-authority MCP policy helper**:
  `seedcore.agent_action.check_policy` is registered in
  `src/seedcore/plugin/mcp_server.py` as a high-level preflight helper for
  agents. It requires caller-provided `buyer_did`, `delegation_id`, and
  `session_token` or `actor_token`; it no longer fabricates delegation or
  identity defaults.
- **Gated action schema scaffolding**:
  `src/seedcore/sdk/schema_exporter.py` scans `@gated_action` declarations and
  emits path-qualified manifest IDs, avoiding duplicate function-name
  collisions when generating PDP/PKG scaffolds.
- PKG/RCT contract alignment through manifest, taxonomy, decision-graph, and
  triple-hash replay binding
- operator console **legibility layer**: case verdict strip, replay verdict,
  anomaly-first queue (`operator_signals`), deterministic copilot panel, and
  optional **`GET /api/v1/verification/operator/copilot-brief`** (stored
  prompts + strict LLM validation with citations / `uncertainty_notes`; see
  section 4.1 of [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) and
  `docs/schemas/operator_copilot_brief_v0.schema.json`)
- **Virtual NFC simulation lane**: `src/seedcore/ops/evidence/nfc_verification.py`
  now provides a pure deterministic dynamic NFC verifier for fixture evidence;
  `tests/fixtures/nfc/` covers happy path, replay / clone, stale scan, tamper,
  wrong asset, and incomplete payload cases; rare-shoe RCT delegates to the
  helper while preserving compatibility reason codes; and replay materialization
  exposes redacted NFC verifier metadata without challenge or key material.
- **Window H live governance advisory shadow contract**:
  `src/seedcore/ml/ml_service.py` exposes
  `POST /xgboost/governance/advisory` and
  `POST /xgboost/governance/train_shadow_student` over conservative and
  XGBoost `GovernanceShadowStudent` backends. Candidate students are evaluated
  before activation, rejected artifacts cannot replace the active student, and
  `src/seedcore/ops/pdp_hot_path.py` can enqueue opt-in best-effort shadow
  advisory comparisons after the authoritative PDP response is built; and
  `src/seedcore/ops/governance_learning/shadow_parity_log.py` stores advisory
  telemetry in a separate `.local-runtime/governance_shadow_advisory` JSONL /
  SQLite lane. This does not affect PDP disposition, `ExecutionToken`s,
  obligations, evidence, quarantine, verifier, or compiled-authz parity DBs.

Primary proof docs:

- [`archive/historical/restricted_custody_transfer_demo_signoff_report.md`](archive/historical/restricted_custody_transfer_demo_signoff_report.md)
- [`current_next_steps.md`](current_next_steps.md)
- [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md)

## 5. Current Status

As of **2026-06-29**, the project is in **Q2 operational closure -> Q3 bounded
agent integration**, still on one wedge:

- The **June stack triage is now applied**: staged authz-graph rollout,
  RESULT_VERIFIER telemetry gates, Edge Trust Adapter fixtures, evidence
  causality fields, hot-path transport/crypto benchmarks, counter-ledger
  acceleration, guarded ingress identity, and retrieval authorization are the
  month-level hardening priorities. None of these substrate choices bypasses
  PDP allow, scoped `ExecutionToken`, evidence closure, or verifier acceptance.
- The **local autonomous application market signal is now explicit**:
  RTX Spark / DGX-class hardware, Windows local-agent primitives, frontier
  coding/security agents, and agentic creative suites make asynchronous digital
  workers more practical in 2026. This strengthens urgency for SeedCore's
  trust-runtime wedge, but it does not change the authority rule: local agent
  capability, model output, and application-agent output are proposal,
  simulation, diagnosis, or evidence substrates, not execution permission.
- **Commerce RCT** remains the only must-win workflow; docs and code should
  default to "order/quote/value + physical scope + token + evidence" language.
- **Collectible rare-shoe transfer** is now the recommended commercial-grade
  vertical scene for the commerce RCT wedge, because it makes authentication,
  provenance, high-value policy gates, physical handoff, and replayable proof
  concrete without changing the underlying runtime category.
- Host-first and CI gates for verification contracts and degraded-edge drills
  are implemented; **remote Kind + GCP-style topology** is green for API,
  Ray, ingress, HAL, hot-path status/metrics, and scripted kube verification
  (see [`kube_topology_validation_q2_signoff.md`](kube_topology_validation_q2_signoff.md)).
- A **kube verification lane** is checked in (`deploy/verify-kube-topology.sh`);
  running the **verification API and full four-screen capture inside the same
  cluster** (plus optional Kafka) is the next topology milestone—not more
  feature surface area.
- `RESULT_VERIFIER` fail-closed enforcement is in production posture for the RCT
  slice, including source-preserving Rust replay verification and
  token-specific CRL revocation on terminal mismatch; remaining risk is
  operational hardening (DB integration tests, multi-worker contention,
  quarantine runbooks)—see top of [`current_next_steps.md`](current_next_steps.md).
- The autonomy-ready overlay is now explicit: coding and action agents may use
  evaluate/preflight, simulation, diagnosis, and patch-proposal loops, but the
  PDP, verifier, and operator promotion gates remain the only authority path.
- The latest Agent Self-Regulation implementation has been review-fixed and
  targeted-test verified: `@gated_action` enforce mode is token/executor gated,
  MCP `check_policy` requires explicit authority and identity, and the gated
  action schema exporter preserves duplicate function names with path-qualified
  action IDs.
- The virtual NFC simulation lane for the rare-shoe RCT scene is implemented
  and workspace-verified. It strengthens physical-presence evidence with
  deterministic fixture CMAC checks, monotonic counters, freshness, tamper, and
  wrong-asset coverage while remaining evidence-only and non-authority-bearing.
- **Window H governance-aware learning** now has both the offline advisory
  scaffold, an opt-in live shadow advisory contract, and a gated XGBoost shadow
  backend. Shadow predictions are schema-bounded, explicit-training only, and
  logged in an isolated advisory telemetry store; rejected candidates cannot
  become active, and advisory outputs can expose false-safe signals for review
  but cannot alter PDP decisions, mint tokens, update evidence, or clear
  quarantine.

Use [`current_next_steps.md`](current_next_steps.md) as the live status log.

## 6. Next Plan

Cleanup note: the RCT commerce degraded-edge drill expansion is now complete.
It is no longer active next-plan work. The shipped coverage is preserved in
`tests/test_rct_commerce_drill_matrix.py` and enforced by
`scripts/host/verify_q2_degraded_edge_drill_matrix.sh`: stale graph, PKG
outage, approval-store outage, approval-resolver fail-closed, Redis bus
fallback, commerce-adapter HTTP timeout, coordinate tamper, cross-product
replay injection, and replay-router workflow-key assertions all keep evidence
tied to `product_ref` / `order_ref` / `quote_ref` / `workflow_join_key`.

Real near-term execution order (commerce-coherent and autonomy-ready):

1. **Apply the June one-month stack triage before expanding roadmap scope.**
   The current priority is staging authz-graph rollout, RESULT_VERIFIER
   telemetry gates, Edge Trust Adapter fixtures, evidence causality fields,
   hot-path transport/crypto benchmarks, explicit counter-ledger acceleration,
   guarded ingress identity, and two-stage retrieval authorization. These are
   trust-runtime hardening tasks under the existing PDP, `ExecutionToken`,
   evidence, replay, and verifier contracts.
2. **Use the autonomous-application investigation to sharpen Q3 urgency
   without expanding scope.** Keep
   [`rtx_spark_autonomous_era_investigation.md`](rtx_spark_autonomous_era_investigation.md)
   tied to Agent Self-Regulation, hardware-anchored telemetry, Replay Studio,
   and AI-led self-healing. The useful read is "applications are becoming
   autonomous work systems that need governed admission," not "SeedCore should
   become a general OS agent, creative suite, scientific workbench, or coding
   department."
3. **Landed and acceptance-wired: Gated Action DX + Agent Self-Regulation drill**
   over one RCT path. The SDK supports shadow and guarded enforce modes; MCP
   `check_policy` exposes explicit-authority preflight; the schema exporter
   creates path-qualified gated-action manifests; and
   `scripts/host/verify_agent_self_regulation_drill.sh` captures reviewable
   replay/evidence refs without live mutation. The deny/quarantine/stale
   telemetry/out-of-bounds/missing-evidence variants are now enforced through
   `scripts/host/verify_q2_degraded_edge_drill_matrix.sh`.
4. **Initial Execution Replay Studio slice landed:** the verification API now
   composes a read-only `seedcore.execution_replay_studio.v0` payload and the
   operator console exposes `/studio?workflow_id=...` from the replay page.
   Next Studio work is artifact-depth hardening: richer policy snapshot fields,
   telemetry hash verification, signer trust-bundle/revocation checks, and
   toxic-path fixture coverage
   ([`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md)).
5. **Close deployment-realistic proof topology**: same cluster runs that already
   pass hot-path gates **plus** verification API where operator/replay
   acceptance requires it; treat Kafka as transport follow-on per
   [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md).
6. Keep the four-screen verification surface contract-stable while hardening
   **external-agent** debugging (minimal Gemini read bundle, gateway correlation,
   commerce adapters)—no parallel "second demo."
7. Extend Studio across the rare-shoe commercial scene once the fixture-backed
   generic RCT Studio payload and operator route are stable.
8. Continue the rare-shoe RCT fixture path as a commercial vertical scene:
   source-registration artifacts for authentication/provenance, gateway
   adapter inputs for listing/quote/order/value, the now-implemented virtual
   NFC/scan evidence lane, hash-bound forensic video proof, and proof-surface
   checks that keep public proof narrow.
9. Advance edge telemetry closure and signed forensic-block linkage without
   reopening frozen projection contracts.
10. Continue Window H from the implemented gated XGBoost shadow backend toward
   broader replay-derived evaluation coverage and Window I abstention taxonomy
   hardening while keeping the advisory student outside the authority path:
   [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)
11. Define the first AI-led self-healing target around a degraded-edge or
   telemetry/outbox failure, with the repair loop ending in a reviewable patch
   and gate evidence rather than direct production mutation.
12. Convert TPM/KMS signer runbook drills into repeatable operational evidence.

Primary planning docs:

- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`rtx_spark_autonomous_era_investigation.md`](rtx_spark_autonomous_era_investigation.md)
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`ap2_seedcore_rct_alignment_memo.md`](ap2_seedcore_rct_alignment_memo.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`edge_telemetry_evidence_closure_draft.md`](edge_telemetry_evidence_closure_draft.md)
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md)
- [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)

## 7. How To Read The Rest Of This Directory

### Active execution and contracts

- [`north_star_autonomous_trade_environment.md`](north_star_autonomous_trade_environment.md)
  — long-range **autonomous trade** architecture (keep RCT as the shipped slice)
- [`current_next_steps.md`](current_next_steps.md)
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`rtx_spark_autonomous_era_investigation.md`](rtx_spark_autonomous_era_investigation.md)
  - 2026 market-signal memo for RTX Spark / DGX-class systems, local OS agents,
    autonomous code/repair agents, creative/scientific application agents, and
    why SeedCore should accelerate governed execution while rejecting
    hardware-, model-, or app-output-as-authority
- [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md)
- [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`legible_local_memory_vault.md`](legible_local_memory_vault.md)
- [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md)
- [`gated_action_dx_layer.md`](gated_action_dx_layer.md)
- [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md)
- [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md)
- [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md)
- [`rct_control_posture_env_matrix.md`](rct_control_posture_env_matrix.md) - operator
  env matrix for `dev/advisory` vs fail-closed `control-rct`
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md)
- [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md)
- [`hot_path_transport_serialization_spike.md`](hot_path_transport_serialization_spike.md)
- [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md)

### Historical or frozen references

- [`archive/historical/project_stage_milestone_summary.md`](archive/historical/project_stage_milestone_summary.md)
- [`archive/historical/killer_demo_execution_spine.md`](archive/historical/killer_demo_execution_spine.md)
- [`archive/historical/next_killer_demo_contract_freeze.md`](archive/historical/next_killer_demo_contract_freeze.md)
- [`archive/historical/restricted_custody_transfer_demo_signoff_report.md`](archive/historical/restricted_custody_transfer_demo_signoff_report.md)
- [`archive/historical/end_to_end_governance_demo_contract.md`](archive/historical/end_to_end_governance_demo_contract.md)
- [`archive/historical/contract_freeze_zero_trust_terms.md`](archive/historical/contract_freeze_zero_trust_terms.md)

### Architecture companion notes

- [`north_star_autonomous_trade_environment.md`](north_star_autonomous_trade_environment.md)
  (cluster posture includes Kafka; local rollout → [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md))
- [`seedcore_north_star_architecture_v1.2.0.pdf`](assets/seedcore_north_star_architecture_v1.2.0.pdf)
  — cleaned visual companion deck for the North Star; not a separate roadmap
- [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md)
  — category framing reference for external messaging, partner docs, and README
  language
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md) — phased
  local broker, topics, and producer order for intent / telemetry / policy outcomes
- [`memory_module_refactor_spec.md`](memory_module_refactor_spec.md) — draft plan
  for narrowing `memory/` into explicit working / semantic / incident contracts
  aligned to the current trust-runtime architecture
- [`legible_local_memory_vault.md`](legible_local_memory_vault.md) — local-first
  Markdown vault pattern for human-readable advisory memory, admitted/rejected
  claim mirrors, and privacy-preserving manual inspection
- [`seedcore_2027_high_vertical_direction.md`](seedcore_2027_high_vertical_direction.md)
- [`language_evolution_map.md`](language_evolution_map.md)
- [`rust_workspace_proposal.md`](rust_workspace_proposal.md)
- [`persistent_twin_service_track.md`](persistent_twin_service_track.md)

### Sidecar or lower-priority research tracks

- [`source_registration_architecture.md`](source_registration_architecture.md)
- [`source_registration_tracking_event_sequence.md`](source_registration_tracking_event_sequence.md)
- [`source_registration_tracking_event_curl_collection.md`](source_registration_tracking_event_curl_collection.md)
- [`vla_2026_optimizations.md`](vla_2026_optimizations.md)
- [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md) — bounded learning plan that converts VLA/distillation ideas into a trust-slice-aligned execution track
  - Window H status: strict advisory schema, deterministic labeler,
    replay-derived dataset, conservative and XGBoost shadow students, ML
    service advisory/train endpoints, isolated shadow telemetry, gated
    candidate activation, and opt-in PDP shadow hook are implemented.
- [`statistical_model_audit_shadow_contract.md`](statistical_model_audit_shadow_contract.md)
  — shadow-only contract for using statistical distribution tests as
    model-promotion and review evidence without entering authority-bearing
    replay or custody paths
- [`autonomous_verifier_agents_decision_memo.md`](autonomous_verifier_agents_decision_memo.md)
- [`baseline_task_types_analysis.md`](baseline_task_types_analysis.md)
- [`agent_capability_skills_relationships.md`](agent_capability_skills_relationships.md)
- [`agent_capability_skills_quick_reference.md`](agent_capability_skills_quick_reference.md)
- [`hermes_skill_synthetic_artifact_model.md`](hermes_skill_synthetic_artifact_model.md)
  - proposed documentation model for representing a Hermes Skill as a SeedCore
    synthetic artifact while preserving first-class runtime `skill` identity
- [`nous_instruction_tuning_patterns_for_seedcore.md`](nous_instruction_tuning_patterns_for_seedcore.md)
  - research note translating Hermes/Nous instruction-tuning patterns into
    SeedCore-specific post-training workstreams such as contract obedience,
    tool-call discipline, abstention, and evidence-grounded explanation

### Local operations and protocol references

- [`HAL_TESTING.md`](HAL_TESTING.md)
- [`local-macos-8gb.md`](local-macos-8gb.md)
- [`policy_gate_matrix.md`](policy_gate_matrix.md)
- [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md)
- [`phase0_contract_freeze_manifest.json`](phase0_contract_freeze_manifest.json)
- [`evidence_bundle_example.json`](evidence_bundle_example.json)

### Archived redirect notes

- [`archive/README.md`](archive/README.md)
- [`archive/operator_legibility_mvp.md`](archive/operator_legibility_mvp.md)
- [`archive/seedcore_positioning_narrative.md`](archive/seedcore_positioning_narrative.md)

## 8. Maintenance Rule

When changing this directory, avoid creating a second roadmap narrative unless
there is a strong reason. Prefer this ownership split:

- `README.md` in this directory = map, stage status, and document ownership
- `current_next_steps.md` = live status and immediate execution order
- `seedcore_2026_execution_plan.md` = workstreams, stage goals, and sequencing
- `q2_2026_audit_trail_ui_spec.md` = product surface and operator UX contract
  including any non-authoritative dashboard design-token companion
- `execution_replay_studio_development_plan.md` = advanced read-only forensic
  replay UI step over the existing verification/replay contracts
- `policy_graph_builder_implementation_plan.md` = policy-package authoring,
  structured metadata, customer policy graph templates, and compile/test
  expectations before PDP promotion
- `authz_graph_engine_evolution_plan.md` = future-performance schedule for
  tuple contracts, structural benchmarks, Ray/cache hardening, and native graph
  kernels, gated by ADR 0011
- `north_star_autonomous_trade_environment.md` = final ambition and long-range
  architecture reference
- `local_kafka_streams_schedule.md` = local Kafka transport rollout (intent,
  telemetry, policy outcomes) aligned to the north-star cluster table
- operator legibility + copilot API contract = section 4.1 of
  `q2_2026_audit_trail_ui_spec.md` (keep in sync with
  `ts/services/verification-api` and operator console)

If a doc becomes historical, mark it explicitly and point back to one of the
canonical files above.
