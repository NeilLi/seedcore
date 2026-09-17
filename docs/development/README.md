# SeedCore Development Docs

Date: 2026-09-17
Status: Canonical development map; Microduck and robotics integration are the next-stage focus

Microduck is the primary integration target for the next stage of SeedCore.
The work connects remote agent intent, local robot control, and replayable
execution evidence through the existing trust runtime.

Start with the [active queue](current_next_steps.md), the
[Microduck integration plan](robotics/microduck_integration_plan.md), and the
[robotics reading map](robotics/README.md). The
[portfolio decision](application_directions.md) explains what is active,
maintained, or deferred.

## Development Map

| Area | Purpose | Next-stage posture |
| --- | --- | --- |
| [Robotics](robotics/README.md) | Microduck architecture, RL, simulator and hardware integration; Reachy and WAM/VLA references | Primary focus |
| [Trust runtime](trust-runtime/README.md) | Accountability, intent admission, PDP, tokens, revocation | Shared foundation |
| [Evidence](evidence/README.md) | Telemetry, receipts, replay, verifier closure, persistent twins | Build the Microduck evidence path |
| [Learning](learning/README.md) | Evaluation, flywheel, memory, retrieval, advisory agents | Supporting research |
| [Operations](operations/README.md) | Local environment, rollout, failure drills, remediation | Simulator and supervised hardware bring-up |
| [Infrastructure](infrastructure/README.md) | Edge architecture, proof kernels, transport, hardware identity | Select work needed by the integration |
| [Integrations](integrations/README.md) | External agents, SDKs, ingress, capability interfaces | Reuse existing ingress |
| [Applications](applications/README.md) | RCT, city/producer, journey and creative tracks | RCT regression baseline; other expansion deferred |
| [Strategy](strategy/README.md) | Earlier annual plans and longer-range direction | Context; the active queue takes precedence |
| [Archive](archive/README.md) | Superseded queues, frozen records, sign-offs | Historical |
| [Assets](assets/README.md) | Architecture and presentation files | Supporting reference |

Each area index lists every document in its directory. Original dates and
implementation claims describe a document's own scope; filing a proposal
here does not promote it to an implemented feature.

## Reading Order

1. [Current next steps](current_next_steps.md): execution order and exit conditions.
2. [Application directions](application_directions.md): the Microduck focus decision.
3. [Microduck architecture](robotics/microduck_architecture_study.md): onboard boundaries.
4. [Microduck RL](robotics/microduck_rl_study.md): actor inputs, rewards, transfer, attachment corrections.
5. [Microduck integration plan](robotics/microduck_integration_plan.md): adapter and evidence work.
6. [Policy gates](policy_gate_matrix.md), [token lifecycle](trust-runtime/execution_token_lifecycle_management.md),
   and [physical telemetry](evidence/physical_telemetry_processing_contract.md): shared requirements.

## Authority And Document Precedence

```text
model proposes -> accountable Agent -> ActionIntent -> PDP
  -> scoped, non-revoked ExecutionToken -> robot execution boundary
  -> robotd local control and safety -> physical attempt
  -> evidence -> replay / RESULT_VERIFIER
```

The [policy gate matrix](policy_gate_matrix.md),
[flywheel harness](seedcore_flywheel_harness.md), and
[trust-runtime category reference](trust_runtime_category_distinction.md)
remain stable root entrypoints. Local robot safety may refuse or stop an
admitted action. Training results, model output, and telemetry do not mint
execution authority.

For scheduling, use this map, the portfolio decision, and the active queue
before older annual plans or application schedules. Durable contracts and ADRs
retain their authority within their scope; changing priority does not waive
their gates.

## Maintenance

- Place new work in its topic folder and update that folder's index.
- Keep the root queue short; put implementation details in the owning plan.
- Label new documents as active plans, supporting contracts, research, or historical.
- Record source revision and distinguish upstream behavior from SeedCore proposals.
- Preserve deferred work without presenting it as a current prerequisite.
- Update incoming and relative links when moving a document.
- Use the [path migration table](document_path_migration.md) to find former flat-layout paths.
- Keep the root `phase0_contract_freeze_manifest.json` path used by verification tooling.
