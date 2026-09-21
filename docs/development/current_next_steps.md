# Current Next Steps

Date: 2026-09-21
Status: Canonical active execution queue — Microduck and robotics integration

The next stage targets a governed Microduck action with observable execution
and replayable evidence. The [portfolio decision](application_directions.md)
sets priorities; the [integration plan](robotics/microduck_integration_plan.md)
defines the boundary. These milestones are planned, not completed integration.

The [physical AI strategy](robotics/physical_ai_strategy.md) explains the product
goal. The [robot execution proposal](robotics/robot_execution_contract.md)
defines reusable session, interruption and evidence requirements; its proposed
bindings need explicit schema review before implementation.

The [multi-robot team layer](robotics/multi_robot_team_architecture.md) now provides
organ reservations, independent cognitive proposals, bounded agent tasks and
coordinator round/verification barriers. Connect it to admitted Microduck
execution and evidence adapters after M1–M3; local contract tests do not complete
those milestones.

## Execution Order

| Stage | Deliverable | Exit condition |
| --- | --- | --- |
| M0 — Pin and inspect | Runtime/RL commits, policy digest, hardware/simulator profile, RPC and observation inventory | Reproducible manifest; attachment discrepancies resolved for the selected revision |
| M1 — Establish simulation | Explicit fake-I/O and MuJoCo profiles, read-only health/state, golden observations | Startup causes no unrequested movement; observations and ONNX outputs match the pinned contract |
| M2 — Govern one intent | Bounded velocity and stop through the existing gateway and HAL boundary | Invalid, expired, replayed, revoked, wrong-endpoint and out-of-scope requests cause no motion |
| M3 — Close evidence | Action-bound telemetry, receipts, replay and RESULT_VERIFIER | Allowed case closes with sufficient evidence; missing/stale/conflicting evidence is rejected or quarantined |
| M4 — Supervised hardware | One enrolled duck, bounded workspace, measured limits and local stop | Reviewed simulator results and hardware measurements support a repeatable allowed/denied demonstration |
| M5 — Evaluate RL candidates | Reproducible comparison of a baseline and candidate | Reviewed metrics, export parity and rollback artifact; deployment separately admitted |

M0–M3 are the immediate queue. M4 depends on hardware readiness. M5 may run
offline alongside simulation once the baseline is fixed. Start with a compatible
upstream policy; training is not a prerequisite for the first adapter.

## Immediate Work

- Record runtime/RL revisions, policy hash, model, normalization, joint ordering,
  home offsets, action shape, transport and telemetry contract.
- Confirm heartbeat semantics, competing-client behavior and stop behavior.
- Choose one walking profile before adding tricks, rollers or grasping.
- Track unresolved facts in the [source ledger](robotics/microduck_source_ledger.md).
- Reuse gateway, token validation, revocation, receipt and verifier paths.
- Distinguish simulator and hardware identities; fail explicitly when requested
  hardware is unavailable.
- Define command refresh without replaying single-use tokens or extending expiry.
- Bind state/outcomes to action, endpoint, runtime and policy.
- Exercise the integration plan's negative cases before declaring completion.
- Freeze measurable command-age, revocation-freshness, stop-response and
  evidence-closure limits for the selected profile before acceptance runs.
- Inventory all command ingress and remove development bypasses from the
  admitted deployment profile; test token enforcement at the actual boundary.
- Distinguish task completion, observed interruption and unresolved physical
  state in the operator timeline and verifier records.

## After The First Integration

Package the accepted skill and its conformance fixtures using the
[skill proposal](robotics/robot_skill_contract.md). Test reuse with an external
developer and then a second robot adapter before expanding into a studio or
fleet product. Record integration effort, reused contracts and body-specific
changes. These are conditional follow-ons, not new M0–M3 prerequisites.

## Customer Discovery Alongside Engineering

The [service operating plan](robotics/robot_service_operating_plan.md) applies
the founder-led capacity decision: one active hardware integration and at most
one live pilot initially. Its S0–S3 business stages run alongside M0–M5 without
replacing technical acceptance.

Use the [customer delivery model](robotics/robot_solution_delivery.md) to turn
ordinary requests into one defined function before selecting hardware:

- Prepare a need brief: intended user, current workaround, setting, budget,
  permissions, supervision and measurable outcome.
- Compare candidate bodies against required capabilities and support costs;
  verify current specifications and availability before making a recommendation.
- Specify one small function and how the customer will start, stop and recover
  it. Record limitations and a non-robot alternative where appropriate.
- Agree customer acceptance criteria and trial/support scope. Evaluate usefulness
  and repeat use separately from runtime authorization and evidence closure.
- Classify requested work as configuration, supported integration or research;
  set an effort/spending cap and next decision before committing to implementation.
- Name the support owner, vendor/repair route, expected support hours and rollback
  procedure before a customer trial. Count founder delivery and support time.

Discovery materials can be prepared now; contacting prospective customers is
a separate activity requiring authorization. Customer hardware trials require
both an accepted need/function brief and completed engineering gates for the
selected robot and environment. A second adapter should serve a validated need.
M5 remains learning/promotion; skill packaging is a follow-on, not a renumbered M5.

## Hardware And Learning

Use measured bounds and an operator-supervised workspace. Record latency,
stop behavior, stale-sensor handling and local preemption; simulator success
alone does not close hardware acceptance.

Use the [RL study](robotics/microduck_rl_study.md) for offline experiments.
Preserve the baseline for rollback and version evaluation evidence for each
candidate. Reward metrics remain separate from authorization.

## Verification

Run from the repository root when implementing the integration:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
pytest tests/test_robot_sim_week4_integration.py tests/test_result_verifier_telemetry_contract.py tests/test_signed_edge_telemetry_closure_refs.py -q
```

These are existing regressions, not Microduck acceptance tests. Add dedicated
transport, authority and golden-observation tests as M1–M3 are implemented.

For learning/flywheel changes:

```bash
pytest tests/test_flywheel_harness.py tests/test_energy.py -q
```

Stop repeated deterministic gate failures and surface verifier/runbook evidence.

## Maintained And Deferred

Maintain RCT trust/proof regressions. Defer RCT visual expansion, city persistence
promotion, producer/service lifecycle, tourist journeys, creative media and
additional hardware platforms unless needed by the Microduck milestone.
Their former order remains in the
[previous queue](archive/historical/current_next_steps_before_microduck_2026-09-17.md).
