# SeedCore Design Notes

This is a living conceptual note for SeedCore. It captures enduring design intent and should not be treated as a migration log or implementation checklist.

## Runtime Intent

SeedCore is a zero-trust runtime for custody-aware digital twins where AI judgment, accountable agents, and real-world execution are separated by explicit policy and evidence boundaries.

Core intent:

- keep AI advisory by default
- require policy-verified authorization before high-consequence actions
- preserve replayable evidence for each governed state transition

## Plane Model (Current)

SeedCore uses a practical multi-plane model:

- **Intelligence Plane**: reasoning, planning, and context hydration
- **Control Plane**: policy evaluation, surprise/drift gating, execution decisioning
- **Execution Plane**: accountable agents and tool/actuator handoff
- **Infrastructure Plane**: distributed runtime substrate, data services, and telemetry

The plane model is a design aid for system boundaries. It is not a strict package/module taxonomy.

## Judgment vs Authority

A stable system boundary in SeedCore is the split between judgment and authority:

- `TaskPayload` carries planning and routing context
- `ActionIntent` carries an accountable, policy-evaluable action contract
- authorization occurs only after policy allow and tokenized handoff

This keeps the runtime auditable, deny-by-default, and safe under model uncertainty.

## Fast Path and Escalation

SeedCore favors low-latency default handling for routine cases, with deliberate escalation for high-surprise or high-risk situations. In practice:

- routine decisions stay on the hot path
- surprising states escalate to deeper reasoning and stricter governance
- execution remains policy-constrained in both paths

## Design Guardrails

When introducing new components, preserve these guardrails:

- no direct LLM-to-actuator execution bypassing policy checks
- no hidden side effects without signed or verifiable receipts
- no coupling that prevents deterministic replay of high-consequence workflows

## Canonical References

For normative implementation details and active execution priorities, use:

- [Architecture Overview](architecture/overview/architecture.md)
- [Zero-Trust Custody and Digital-Twin Runtime](architecture/overview/zero_trust_custody_digital_twin_runtime.md)
- [SeedCore 2026 Execution Plan](development/seedcore_2026_execution_plan.md)
- [Agent Action Gateway Contract](development/agent_action_gateway_contract.md)
