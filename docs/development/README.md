# SeedCore Development Docs

Date: 2026-09-21
Status: Canonical development map; physical AI runtime, Microduck reference integration

SeedCore is developing a **trust runtime for physical AI**, with small robots
as the first integration focus and Microduck as the reference target. The
reusable unit is a governed skill attempt: accountable intent, bounded
authority, local enforcement and evidence of the outcome.

The team-facing product work starts with people's needs: help a customer choose
suitable hardware, implement a useful function, and operate it with support.
The [customer delivery model](robotics/robot_solution_delivery.md) connects that
service to the runtime. Customer discovery and engineering run alongside each
other; a hardware trial must satisfy both acceptance tracks.

For the founder-led delivery process, use the
[service operating plan](robotics/robot_service_operating_plan.md): one supported
profile and live pilot initially, with explicit scope, support and expansion gates.

Start with the [physical AI strategy](robotics/physical_ai_strategy.md), the
[active queue](current_next_steps.md), the
[Microduck integration plan](robotics/microduck_integration_plan.md), and the
[robotics reading map](robotics/README.md). The
[portfolio decision](application_directions.md) explains what is active,
maintained, or deferred.

## Development Map

| Area | Purpose | Next-stage posture |
| --- | --- | --- |
| [Robotics](robotics/README.md) | Customer solution delivery, reusable runtime contracts, Microduck integration and supporting research | Primary focus |
| [Trust runtime](trust-runtime/README.md) | Accountability, intent admission, PDP, tokens, revocation | Shared foundation |
| [Evidence](evidence/README.md) | Telemetry, receipts, replay, verifier closure, persistent twins | Build the Microduck evidence path |
| [Learning](learning/README.md) | Evaluation, flywheel, memory, retrieval, advisory agents | Supporting research |
| [Operations](operations/README.md) | Local environment, rollout, failure drills, remediation | Simulator and supervised hardware bring-up |
| [Reports](reports/README.md) | Dated test analyses and engineering reports | Supporting reference; claims retain their source and verification status |
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

1. [Physical AI strategy](robotics/physical_ai_strategy.md) and [customer delivery model](robotics/robot_solution_delivery.md): customer needs, product thesis, adoption tests and claim limits.
2. [Current next steps](current_next_steps.md) and [application directions](application_directions.md): sequence and portfolio decision.
3. [Robot execution proposal](robotics/robot_execution_contract.md) and [skill package proposal](robotics/robot_skill_contract.md): intended reusable contracts; not shipped schemas.
4. [Microduck architecture](robotics/microduck_architecture_study.md) and [RL study](robotics/microduck_rl_study.md): onboard boundaries, policy inputs and pinned-source corrections.
5. [Microduck integration plan](robotics/microduck_integration_plan.md): adapter and evidence work.
   [Multi-robot team architecture](robotics/multi_robot_team_architecture.md) describes
   the implemented coordination layer for cooperative work and competitive play.
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

Robotics documents marked **proposed** add design requirements, not implemented
token fields or permission grants. Admission, local control and evidence closure
have separate deadlines. A passing software contract test does not establish
hardware readiness, sensor truth or physical safety certification.

## Maintenance

- Place new work in its topic folder and update that folder's index.
- Keep the root queue short; put implementation details in the owning plan.
- Label new documents as active plans, supporting contracts, research, or historical.
- Record source revision and distinguish upstream behavior from SeedCore proposals.
- Preserve deferred work without presenting it as a current prerequisite.
- Update incoming and relative links when moving a document.
- Use the [path migration table](document_path_migration.md) to find former flat-layout paths.
- Keep the root `phase0_contract_freeze_manifest.json` path used by verification tooling.
