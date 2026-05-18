# SeedCore Development Docs

Date: 2026-04-18  
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
- Strategic delegation thesis and frontier alignment:
  [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md)
- Execution-token lifecycle and capability hardening:
  [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)

Start here for the active spine:

1. [`current_next_steps.md`](current_next_steps.md) - what is done now, current
   status, and immediate execution order.
2. [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md) - stage
   goals, workstreams, sequencing, and canonical positioning.
3. [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) - current
   verification/operator product surface and contract-level UX behavior.
4. [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) section 4.1 -
   operator legibility layer (queue signals, replay verdict, deterministic +
   optional LLM copilot API).
5. [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md) -
   collectible rare-shoe transfer as a commercial vertical scene on the same
   RCT contract: authentication registration first, bounded custody authority
   second, replayable proof last.
6. [`policy_graph_builder_implementation_plan.md`](policy_graph_builder_implementation_plan.md) -
   technical memo for turning customer business rules into executable,
   testable Policy Knowledge Graphs that compile into PDP rules, authority
   constraints, evidence requirements, reason codes, and replay fixtures.
7. [`gated_action_dx_layer.md`](gated_action_dx_layer.md) - lightweight DX spec
   for declaring governed action boundaries without making developers manually
   wire PDP calls, execution tokens, evidence bundles, verifier outcomes, and
   replay proof chains.
8. [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md) -
   implementation contract for making hardware-bound signer identity, signed
   telemetry, asset anchors, zone evidence, and verifier replay central to
   physical execution proof.
9. [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md) -
   strategic memo connecting SeedCore's implemented delegation path to
   cryptographic multi-hop authority, WIMSE-style agent identity, AIP/Biscuit
   capability attenuation, ReBAC graph paths, SCITT-style evidence, and
   hardware-backed intent.
10. [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md) -
   lifecycle memo for `ExecutionToken` as a short-lived deterministic
   capability artifact, including mint/withhold semantics, TTL bounding,
   constraint freezing, delegated subtokens, replay, quarantine, and candidate
   hardening with DPoP, RATS, Macaroons/Biscuit, IEEC, and outbox reliability.

## 3. Stage Goals And Status Map

This table is the shortest answer to "what stage are we in?"

| Stage | Goal | Current status | Canonical docs |
| :--- | :--- | :--- | :--- |
| 0. Runtime substrate | Build the Python/Ray execution and agent foundation | Done baseline | [`archive/historical/project_stage_milestone_summary.md`](archive/historical/project_stage_milestone_summary.md) |
| 1. Zero-trust execution boundary | Make all high-risk actions tokenized, revocable, and receipt-bound | Materially implemented | [`current_next_steps.md`](current_next_steps.md) |
| 2. PKG policy and authz graph | Pin decisions to a snapshot and compile a deterministic hot-path graph | Implemented, still being hardened | [`pkg_authz_graph_rfc.md`](pkg_authz_graph_rfc.md), [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md), [`pdp_authz_graph_staging_rollout.md`](pdp_authz_graph_staging_rollout.md) |
| 3. Replay and proof surface | Expose replayable verification so third parties can inspect outcomes | Implemented | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md), [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md) |
| 4. RCT contract freeze | Lock one must-win workflow, artifact chain, and business-state truth table | Done for Slice 1 | [`archive/historical/killer_demo_execution_spine.md`](archive/historical/killer_demo_execution_spine.md), [`archive/historical/next_killer_demo_contract_freeze.md`](archive/historical/next_killer_demo_contract_freeze.md) |
| 5. Trust hardening | Prove signer provenance, TPM/KMS policies, and operational drills | Checkpoint crossed, not fully closed | [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md), [`tpm_fleet_rollout_maturity_decision_memo.md`](tpm_fleet_rollout_maturity_decision_memo.md) |
| 6. Multi-party governance | Make approval envelopes and dual-control workflows authoritative end to end | Partially implemented | [`archive/historical/next_killer_demo_contract_freeze.md`](archive/historical/next_killer_demo_contract_freeze.md), [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md) |
| 7. Hot-path operability | Promote `shadow -> canary -> enforce` with parity, latency, and rollback evidence | Contract + observability implemented; **remote Kind topology green** for core gates and drills; full **verification API inside cluster** still the open topology milestone | [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md), [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md), [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md), [`kube_topology_validation_q2_signoff.md`](kube_topology_validation_q2_signoff.md) |
| 8. Verification product surface | Make operator/replay UX contract-driven and legible without weakening proof | Advanced and active | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) |
| 9. Rust proof kernel | Move strict verification and authority-bearing kernels toward deterministic Rust packages | Scaffolded and growing | [`rust_workspace_proposal.md`](rust_workspace_proposal.md), [`language_evolution_map.md`](language_evolution_map.md) |
| 10. External agent boundary | Expose one narrow stable gateway for agent-originated requests | **v1 productized in-repo**: strict schema, correlation, reference adapter, commerce field mapping, MCP `seedcore.agent_action.evaluate` | [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md), [`gemini_phase1_quickstart.md`](gemini_phase1_quickstart.md) |
| 11. Sidecar innovation tracks | Keep robotics/VLA and deep twin research from diluting the commerce RCT story | Sidecar: intake/twin tracks support the wedge as **upstream evidence**, not a second product center | [`vla_2026_optimizations.md`](vla_2026_optimizations.md), [`source_registration_architecture.md`](source_registration_architecture.md), [`persistent_twin_service_track.md`](persistent_twin_service_track.md) |
| 12. Governance-aware learning | Introduce distillation, abstention tuning, proof refinement, and simulation RL as bounded trust-slice components, wired as a four-node governed self-improvement loop (Advisory Student, Scenario Generator, Governance Reward Scorer, Governance Learning Sample Store) over a **typed verdict taxonomy** (`clean_allow` / `clean_deny` / `near_miss_*` / `quarantine` / `escalate` / `verification_mismatch` / `stale_context`) rather than a scalar reward | Planned next-stage track | [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md), [`current_next_steps.md`](current_next_steps.md) |

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
- PKG/RCT contract alignment through manifest, taxonomy, decision-graph, and
  triple-hash replay binding
- operator console **legibility layer**: case verdict strip, replay verdict,
  anomaly-first queue (`operator_signals`), deterministic copilot panel, and
  optional **`GET /api/v1/verification/operator/copilot-brief`** (stored
  prompts + strict LLM validation with citations / `uncertainty_notes`; see
  section 4.1 of [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) and
  `docs/schemas/operator_copilot_brief_v0.schema.json`)

Primary proof docs:

- [`archive/historical/restricted_custody_transfer_demo_signoff_report.md`](archive/historical/restricted_custody_transfer_demo_signoff_report.md)
- [`current_next_steps.md`](current_next_steps.md)
- [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md)

## 5. Current Status

As of **2026-04-18**, the project is in **Q2 operational closure -> Q3 external
integration**, still on one wedge:

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

Real near-term execution order (commerce-coherent):

1. **Close deployment-realistic proof topology**: same cluster runs that already
   pass hot-path gates **plus** verification API where operator/replay
   acceptance requires it; treat Kafka as transport follow-on per
   [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md).
2. Keep the four-screen verification surface contract-stable while hardening
   **external-agent** debugging (minimal Gemini read bundle, gateway correlation,
   commerce adapters)—no parallel "second demo."
3. Add the rare-shoe RCT fixture path as a commercial vertical scene:
   source-registration artifacts for authentication/provenance, gateway
   adapter inputs for listing/quote/order/value, signed edge telemetry for
   NFC/scan handoff, hash-bound forensic video proof, and proof-surface checks
   that keep public proof narrow.
4. Advance edge telemetry closure and signed forensic-block linkage without
   reopening frozen projection contracts.
5. Convert TPM/KMS signer runbook drills into repeatable operational evidence.
6. Start the governance-aware learning track only after the current trust slice
   remains stable under the above pressures:
   [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)

Primary planning docs:

- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
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
- [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
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
- [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md)
  — category framing reference for external messaging, partner docs, and README
  language
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md) — phased
  local broker, topics, and producer order for intent / telemetry / policy outcomes
- [`memory_module_refactor_spec.md`](memory_module_refactor_spec.md) — draft plan
  for narrowing `memory/` into explicit working / semantic / incident contracts
  aligned to the current trust-runtime architecture
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
- `north_star_autonomous_trade_environment.md` = final ambition and long-range
  architecture reference
- `local_kafka_streams_schedule.md` = local Kafka transport rollout (intent,
  telemetry, policy outcomes) aligned to the north-star cluster table
- operator legibility + copilot API contract = section 4.1 of
  `q2_2026_audit_trail_ui_spec.md` (keep in sync with
  `ts/services/verification-api` and operator console)

If a doc becomes historical, mark it explicitly and point back to one of the
canonical files above.
