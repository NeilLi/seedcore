# SeedCore Development Docs

Date: 2026-08-20
Status: Canonical entrypoint for `docs/development/`

SeedCore is a trust runtime for high-consequence AI actions. These documents
are organized around the product path from application intent to admitted
execution and replayable closure.

```text
application intent
  -> accountable Agent
  -> ActionIntent
  -> PDP decision
  -> scoped ExecutionToken
  -> actuator
  -> evidence and RESULT_VERIFIER closure
```

AI, memory, retrieval, discovery, simulation, creative content, and learning may
propose or explain. None of them becomes execution authority by itself.

## Start Here

| Question | Canonical document |
| --- | --- |
| What applications are active, adjacent, or deferred? | [`application_directions.md`](application_directions.md) |
| What should be built next? | [`current_next_steps.md`](current_next_steps.md) |
| What is the product and trust-runtime category? | [`../../README.md`](../../README.md), [`trust_runtime_category_distinction.md`](trust_runtime_category_distinction.md) |
| What are the non-bypassable gates? | [`policy_gate_matrix.md`](policy_gate_matrix.md) |
| How is the adaptive flywheel kept non-authoritative? | [`seedcore_flywheel_harness.md`](seedcore_flywheel_harness.md) |

## Application Portfolio

The current portfolio has one authority-bearing commercial wedge and bounded
expansion tracks around it.

| Direction | Role | Current posture |
| --- | --- | --- |
| Rare-shoe Restricted Custody Transfer | Must-win governed execution product | Runtime/proof baseline plus strict visual schemas, canonical hashes, and deterministic replay fixtures implemented; benchmark and runtime integration remain |
| Local producer discovery and proof | Adjacent provenance and public-proof application | Read-only discovery, confirmed intake, MCP, and proof-page slice defined; production verticals require separate activation |
| Grounded producer storytelling | Presentation sidecar | Source-cited text and existing consented still/audio only; generated media remains deferred and non-evidentiary |
| Sovereign agent-native city bootstrap | Foundation and discovery track | Closed-world fixture, three-table persistence with isolated PostgreSQL schema-restore/reseed parity, and read-only REST discovery verified under `bootstrap_sim`; review and service flows precede governed actions |

Read the portfolio decision, dependencies, and promotion gates in
[`application_directions.md`](application_directions.md).

### Rare-Shoe RCT

- [`rare_shoes_collecting_transfer_demo_spec.md`](rare_shoes_collecting_transfer_demo_spec.md)
  — the commercial custody-handoff scene.
- [`rare_shoe_rct_visual_evidence_adapter_v0.md`](rare_shoe_rct_visual_evidence_adapter_v0.md)
  — raw-capture, fingerprint, comparison, and generative-exclusion contract.
- [`virtual_nfc_simulation_plan.md`](virtual_nfc_simulation_plan.md)
  — deterministic dynamic-NFC simulation and negative cases.
- [`second_hand_luxury_trade_evolution.md`](second_hand_luxury_trade_evolution.md)
  — non-activating reuse reference for broader luxury trade.

### Local Producers And Public Proof

- [`local_producer_provenance_and_rct_scenario_expansion.md`](local_producer_provenance_and_rct_scenario_expansion.md)
  — producer provenance, read-only discovery, accessible intake, public proof,
  and grounded creative sidecar.
- [`source_registration_architecture.md`](source_registration_architecture.md)
  — canonical source-registration boundary.
- [`owner_creator_external_sdk_and_plugin_surface.md`](owner_creator_external_sdk_and_plugin_surface.md)
  — vendor-neutral external distribution and adapter boundary.

### AI-Era Journey Digital City And Sovereign Bootstrap

- [`agent_native_digital_city_platform.md`](agent_native_digital_city_platform.md)
  — long-range ecosystem and plane separation.
- [`journey_driven_digital_city_experience.md`](journey_driven_digital_city_experience.md)
  — tourist demand, owner-controlled local-business participation, visual
  journeys, Pattaya reference scope, and product measurements.
- [`sovereign_digital_city_bootstrap_plan.md`](sovereign_digital_city_bootstrap_plan.md)
  — founder-operated topology, delivery slices, simulators, and acceptance
  gates.
- [`sovereign_city_foundations_and_infrastructure.md`](sovereign_city_foundations_and_infrastructure.md)
  — city-domain, construction, network, facility, observation, incident, and
  temporal-twin contract.

### Incubation, Not Current Product Center

- [`tourist_design_studio_pilot_design.md`](tourist_design_studio_pilot_design.md)
- [`tourist_design_studio_delivery_schedule.md`](tourist_design_studio_delivery_schedule.md)
- [`godot_agent_operable_xr_runtime_plan.md`](godot_agent_operable_xr_runtime_plan.md)
- [`immersive_commerce_and_governed_trade_architecture.md`](immersive_commerce_and_governed_trade_architecture.md)

These experience tracks remain bounded presentation or pilot research. They do
not supersede RCT, make a marketplace active, or turn XR/3D output into
evidence or authority.

## Trust Runtime Contracts

### Intent, Accountability, And Delegation

- [`agent_action_gateway_contract.md`](agent_action_gateway_contract.md)
- [`agentic_delegation_control_plane.md`](agentic_delegation_control_plane.md)
- [`agentic_intent_orchestration_plan.md`](agentic_intent_orchestration_plan.md)
- [`verifying_delegation_frontier_ai_architectures.md`](verifying_delegation_frontier_ai_architectures.md)
- [`gated_action_dx_layer.md`](gated_action_dx_layer.md)

The model proposes. An accountable principal constructs the governed intent.
Delegation must be explicit, attenuated, and replayable.

### Policy And Authorization

- [`policy_gate_matrix.md`](policy_gate_matrix.md)
- [`pkg_authz_graph_rfc.md`](pkg_authz_graph_rfc.md)
- [`authz_graph_engine_evolution_plan.md`](authz_graph_engine_evolution_plan.md)
- [`policy_graph_builder_implementation_plan.md`](policy_graph_builder_implementation_plan.md)
- [`asset_centric_pdp_hot_path_contract.md`](asset_centric_pdp_hot_path_contract.md)
- [`pdp_authz_graph_staging_rollout.md`](pdp_authz_graph_staging_rollout.md)

The PDP remains synchronous, deterministic, and stateless at decision time.
Graph, policy, or model upgrades cannot promote themselves into the hot path.

### Execution Authority And Revocation

- [`execution_token_lifecycle_management.md`](execution_token_lifecycle_management.md)
- [`hot_path_enforcement_promotion_contract.md`](hot_path_enforcement_promotion_contract.md)
- [`hot_path_shadow_to_enforce_breakdown.md`](hot_path_shadow_to_enforce_breakdown.md)
- [`rct_control_posture_env_matrix.md`](rct_control_posture_env_matrix.md)
- [`safety_doctrine_enforcement_plan.md`](safety_doctrine_enforcement_plan.md)

An allow decision is not an ambient permission. Execution requires a fresh,
scoped, non-revoked token whose constraints survive through the actuator path.

### Evidence, Replay, And Verification

- [`productized_verification_surface_protocol.md`](productized_verification_surface_protocol.md)
- [`q2_2026_audit_trail_ui_spec.md`](q2_2026_audit_trail_ui_spec.md)
- [`execution_replay_studio_development_plan.md`](execution_replay_studio_development_plan.md)
- [`hardware_anchored_telemetry_mvp_contract.md`](hardware_anchored_telemetry_mvp_contract.md)
- [`physical_telemetry_processing_contract.md`](physical_telemetry_processing_contract.md)
- [`edge_telemetry_evidence_closure_draft.md`](edge_telemetry_evidence_closure_draft.md)
- [`result_verifier_quarantine_remediation_runbook.md`](result_verifier_quarantine_remediation_runbook.md)

Evidence must remain bound to the admitted action, inspectable, and replayable.
Missing or contradictory closure evidence fails closed or enters review or
quarantine.

## Delivery And Operations

- [`current_next_steps.md`](current_next_steps.md) — active execution order.
- [`seedcore_2026_execution_plan.md`](seedcore_2026_execution_plan.md) — annual
  program structure; use current next steps when priorities differ.
- [`kube_topology_validation_q2_signoff.md`](kube_topology_validation_q2_signoff.md)
  — topology verification record.
- [`local-macos-8gb.md`](local-macos-8gb.md) — constrained local environment.
- [`design_partner_demo_schedule.md`](design_partner_demo_schedule.md) — demo
  and partner validation schedule.
- [`freshness_sla_edge_stress_schedule.md`](freshness_sla_edge_stress_schedule.md)
  — edge freshness and failure testing.
- [`tpm_fleet_rollout_runbook.md`](tpm_fleet_rollout_runbook.md) — TPM rollout
  operations.

Repository-level startup and test commands remain in [`../../README.md`](../../README.md).

## Advisory Learning And Research

These tracks can create recommendations, diagnostics, fixtures, or promotion
evidence. They do not alter policy, mint tokens, execute actions, clear
quarantine, or close evidence by themselves.

### Learning And Evaluation

- [`seedcore_flywheel_harness.md`](seedcore_flywheel_harness.md)
- [`governance_aware_learning_next_stage_plan.md`](governance_aware_learning_next_stage_plan.md)
- [`governance_learning_window_g_plan.md`](governance_learning_window_g_plan.md)
- [`statistical_model_audit_shadow_contract.md`](statistical_model_audit_shadow_contract.md)
- [`agent_system_eval_schedule.md`](agent_system_eval_schedule.md)
- [`nous_instruction_tuning_patterns_for_seedcore.md`](nous_instruction_tuning_patterns_for_seedcore.md)

### Retrieval, Memory, And Reasoning

- [`policy_governed_rag_research_adoption_review.md`](policy_governed_rag_research_adoption_review.md)
- [`kg_rag_research_reference.md`](kg_rag_research_reference.md)
- [`zero_cold_start_policy_evolution_ultra.md`](zero_cold_start_policy_evolution_ultra.md)
- [`legible_local_memory_vault.md`](legible_local_memory_vault.md)
- [`memory_module_refactor_spec.md`](memory_module_refactor_spec.md)

### Multi-Agent, Embodied, And Infrastructure Research

- [`multi_agent_safety_research_alignment.md`](multi_agent_safety_research_alignment.md)
- [`world_action_model_architecture_reference.md`](world_action_model_architecture_reference.md)
- [`vla_2026_optimizations.md`](vla_2026_optimizations.md)
- [`gvisor_and_sandbox_hardening_strategy.md`](gvisor_and_sandbox_hardening_strategy.md)
- [`cubesandbox_dependency_integration_sketch.md`](cubesandbox_dependency_integration_sketch.md)
- [`rtx_spark_autonomous_era_investigation.md`](rtx_spark_autonomous_era_investigation.md)

## Protocol And Integration References

- [`ap2_seedcore_rct_alignment_memo.md`](ap2_seedcore_rct_alignment_memo.md)
- [`kafka_delegated_intent_ingress.md`](kafka_delegated_intent_ingress.md)
- [`local_kafka_streams_schedule.md`](local_kafka_streams_schedule.md)
- [`gemini_phase1_quickstart.md`](gemini_phase1_quickstart.md)
- [`agent_capability_skills_quick_reference.md`](agent_capability_skills_quick_reference.md)
- [`agent_capability_skills_relationships.md`](agent_capability_skills_relationships.md)

External protocols and clients may carry intent, identity, payment context, or
tool calls. They remain adapters around the SeedCore authority boundary.

## Archive

Superseded contracts, sign-off records, and historical status summaries live in
[`archive/README.md`](archive/README.md). A historical document may explain why
a decision was made, but it is not an active implementation plan unless a
current canonical document explicitly adopts it.

## Maintenance Rules

1. Keep [`application_directions.md`](application_directions.md) limited to
   portfolio decisions, track boundaries, dependencies, and promotion gates.
2. Keep [`current_next_steps.md`](current_next_steps.md) limited to the active
   queue, exit conditions, and verification commands.
3. Put durable interfaces and security invariants in contract documents, not
   status logs.
4. Move completed chronology and superseded decisions to `archive/` or rely on
   Git history; do not append indefinite dated updates to the active queue.
5. Label each new document as active, supporting, research, or historical.
6. Never describe advisory AI, memory, retrieval, learning, simulation, or
   presentation as an authority source.
