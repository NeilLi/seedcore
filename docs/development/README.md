# SeedCore Development Docs

Date: 2026-04-03  
Status: Canonical entrypoint for `docs/development/`

This page is the "read this first" map for the development docs. It organizes
the directory around one progression:

```text
final ambition -> stage goals -> what is done -> current status -> next plan
```

## 1. Final Ambition

SeedCore's long-range ambition is to become the **trust slice** for
high-consequence autonomous work: humans and agents propose actions, SeedCore
decides what is admissible under pinned policy and delegated authority, physical
systems emit evidence, and the runtime preserves a replayable forensic chain
that can survive adversarial review.

Canonical north-star references:

- [`north_star_autonomous_trade_environment.md`](north_star_autonomous_trade_environment.md)
  (local Kafka rollout plan: [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md))
- [`seedcore_2027_high_vertical_direction.md`](seedcore_2027_high_vertical_direction.md)
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)

## 2. Current Program Center

The current product wedge is **Agent-Governed Restricted Custody Transfer**.
That means the active docs should be read through one question:

- does this move the dual-approved, scope-bound, replay-verifiable transfer
  workflow closer to a pilotable trust product?

Start here for the active spine:

1. [`current_next_steps.md`](current_next_steps.md) - what is done now, current
   status, and immediate execution order.
2. [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md) - stage
   goals, workstreams, sequencing, and canonical positioning.
3. [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md) - current
   verification/operator product surface and contract-level UX behavior.
4. [`operator_legibility_mvp.md`](operator_legibility_mvp.md) - operator legibility
   layer (queue signals, replay verdict, deterministic + optional LLM copilot API).

## 3. Stage Goals And Status Map

This table is the shortest answer to "what stage are we in?"

| Stage | Goal | Current status | Canonical docs |
| :--- | :--- | :--- | :--- |
| 0. Runtime substrate | Build the Python/Ray execution and agent foundation | Done baseline | [`project_stage_milestone_summary.md`](project_stage_milestone_summary.md) |
| 1. Zero-trust execution boundary | Make all high-risk actions tokenized, revocable, and receipt-bound | Materially implemented | [`current_next_steps.md`](current_next_steps.md) |
| 2. PKG policy and authz graph | Pin decisions to a snapshot and compile a deterministic hot-path graph | Implemented, still being hardened | [`pkg_authz_graph_rfc.md`](pkg_authz_graph_rfc.md), [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md), [`pdp_authz_graph_staging_rollout.md`](pdp_authz_graph_staging_rollout.md) |
| 3. Replay and proof surface | Expose replayable verification so third parties can inspect outcomes | Implemented | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md), [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md) |
| 4. RCT contract freeze | Lock one must-win workflow, artifact chain, and business-state truth table | Done for Slice 1 | [`killer_demo_execution_spine.md`](killer_demo_execution_spine.md), [`next_killer_demo_contract_freeze.md`](next_killer_demo_contract_freeze.md) |
| 5. Trust hardening | Prove signer provenance, TPM/KMS policies, and operational drills | Checkpoint crossed, not fully closed | [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md), [`tpm_fleet_rollout_maturity_decision_memo.md`](tpm_fleet_rollout_maturity_decision_memo.md) |
| 6. Multi-party governance | Make approval envelopes and dual-control workflows authoritative end to end | Partially implemented | [`next_killer_demo_contract_freeze.md`](next_killer_demo_contract_freeze.md), [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md) |
| 7. Hot-path operability | Promote `shadow -> canary -> enforce` with parity, latency, and rollback evidence | Implemented in contract, still needs topology-real validation | [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md), [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md), [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md) |
| 8. Verification product surface | Make operator/replay UX contract-driven and legible without weakening proof | Advanced and active | [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md), [`operator_legibility_mvp.md`](operator_legibility_mvp.md) |
| 9. Rust proof kernel | Move strict verification and authority-bearing kernels toward deterministic Rust packages | Scaffolded and growing | [`rust_workspace_proposal.md`](rust_workspace_proposal.md), [`language_evolution_map.md`](language_evolution_map.md) |
| 10. External agent boundary | Expose one narrow stable gateway for agent-originated requests | v1 contract drafted and being productized | [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md), [`gemini_phase1_quickstart.md`](gemini_phase1_quickstart.md) |
| 11. Sidecar innovation tracks | Preserve robotics/VLA and source-registration ideas without distracting from the RCT wedge | Sidecar, not current center | [`vla_2026_optimizations.md`](vla_2026_optimizations.md), [`source_registration_architecture.md`](source_registration_architecture.md), [`persistent_twin_service_track.md`](persistent_twin_service_track.md) |

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
- Agent Action Gateway v1 schema hardening and idempotency behavior
- PKG/RCT contract alignment through manifest, taxonomy, decision-graph, and
  triple-hash replay binding
- operator console **legibility layer**: case verdict strip, replay verdict,
  anomaly-first queue (`operator_signals`), deterministic copilot panel, and
  optional **`GET /api/v1/verification/operator/copilot-brief`** (stored
  prompts + strict LLM validation with citations / `uncertainty_notes`; see
  [`operator_legibility_mvp.md`](operator_legibility_mvp.md) and
  `docs/schemas/operator_copilot_brief_v0.schema.json`)

Primary proof docs:

- [`restricted_custody_transfer_demo_signoff_report.md`](restricted_custody_transfer_demo_signoff_report.md)
- [`current_next_steps.md`](current_next_steps.md)
- [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md)

## 5. Current Status

As of 2026-04-03, the project is in **Q2 operational closure + early Q3
bridge**:

- host-first acceptance closure is implemented and passing
- verification and replay contracts are frozen enough to be product-facing
- the remaining risk is no longer "does the concept exist?"
- the remaining risk is "does the same trust story hold under
  deployment-realistic topology, adversarial drills, and external-agent
  integration pressure?"

Use [`current_next_steps.md`](current_next_steps.md) as the live status log.

## 6. Next Plan

Near-term execution order:

1. Validate acceptance and observability gates in real Kubernetes/Ray
   deployments, not only host mode.
2. Expand stale-graph, dependency outage, replay injection, and coordinate
   tamper drills on the RCT slice.
3. Keep the four-screen verification surface stable while building the first
   narrow external-agent adapter against `seedcore.agent_action_gateway.v1`.
4. Advance edge telemetry closure and signed forensic-block linkage without
   reopening frozen projection contracts.
5. Convert TPM/KMS signer runbook drills into repeatable operational evidence.
6. Introduce **local Kafka** for intent, telemetry, and policy-outcome streams
   per [north_star_autonomous_trade_environment.md](north_star_autonomous_trade_environment.md)
   — follow the phased schedule in [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md)
   (compose, topics, flagged producers, degradation semantics).

Primary planning docs:

- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`edge_telemetry_evidence_closure_draft.md`](edge_telemetry_evidence_closure_draft.md)
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md)

## 7. How To Read The Rest Of This Directory

### Active execution and contracts

- [`current_next_steps.md`](current_next_steps.md)
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md)
- [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md)
- [`operator_legibility_mvp.md`](operator_legibility_mvp.md) — deterministic +
  optional LLM copilot brief; links verification API and UI guardrails
- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`pkg_snapshot_rct_alignment_research.md`](pkg_snapshot_rct_alignment_research.md)
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md)
- [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md)
- [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md)

### Historical or frozen references

- [`project_stage_milestone_summary.md`](project_stage_milestone_summary.md)
- [`killer_demo_execution_spine.md`](killer_demo_execution_spine.md)
- [`next_killer_demo_contract_freeze.md`](next_killer_demo_contract_freeze.md)
- [`restricted_custody_transfer_demo_signoff_report.md`](restricted_custody_transfer_demo_signoff_report.md)
- [`end_to_end_governance_demo_contract.md`](end_to_end_governance_demo_contract.md)
- [`contract_freeze_zero_trust_terms.md`](contract_freeze_zero_trust_terms.md)

### Architecture companion notes

- [`north_star_autonomous_trade_environment.md`](north_star_autonomous_trade_environment.md)
  (cluster posture includes Kafka; local rollout → [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md))
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md) — phased
  local broker, topics, and producer order for intent / telemetry / policy outcomes
- [`seedcore_2027_high_vertical_direction.md`](seedcore_2027_high_vertical_direction.md)
- [`language_evolution_map.md`](language_evolution_map.md)
- [`rust_workspace_proposal.md`](rust_workspace_proposal.md)
- [`persistent_twin_service_track.md`](persistent_twin_service_track.md)

### Sidecar or lower-priority research tracks

- [`source_registration_architecture.md`](source_registration_architecture.md)
- [`source_registration_tracking_event_sequence.md`](source_registration_tracking_event_sequence.md)
- [`source_registration_tracking_event_curl_collection.md`](source_registration_tracking_event_curl_collection.md)
- [`vla_2026_optimizations.md`](vla_2026_optimizations.md)
- [`autonomous_verifier_agents_decision_memo.md`](autonomous_verifier_agents_decision_memo.md)
- [`baseline_task_types_analysis.md`](baseline_task_types_analysis.md)
- [`agent_capability_skills_relationships.md`](agent_capability_skills_relationships.md)
- [`agent_capability_skills_quick_reference.md`](agent_capability_skills_quick_reference.md)

### Local operations and protocol references

- [`HAL_TESTING.md`](HAL_TESTING.md)
- [`local-macos-8gb.md`](local-macos-8gb.md)
- [`policy_gate_matrix.md`](policy_gate_matrix.md)
- [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md)
- [`phase0_contract_freeze_manifest.json`](phase0_contract_freeze_manifest.json)
- [`evidence_bundle_example.json`](evidence_bundle_example.json)

### Archived redirect notes

- [`seedcore_positioning_narrative.md`](seedcore_positioning_narrative.md)

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
- `operator_legibility_mvp.md` = operator legibility + copilot API contract and
  env flags (keep in sync with `ts/services/verification-api` and operator console)

If a doc becomes historical, mark it explicitly and point back to one of the
canonical files above.
