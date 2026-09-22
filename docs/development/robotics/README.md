# Robotics Development

Date: 2026-09-21
Status: Primary next-stage development area

SeedCore's robotics direction is a reusable trust runtime for physical AI.
Microduck is the selected reference integration. Read the strategy for product
scope, the proposed contracts for intended behavior, and the integration plan
and source ledger before implementing a driver or selecting a learned policy.

Customer work starts with a person's desired outcome. The team helps assess
the need, select hardware, customize functions, validate results and provide
support. Microduck is the reference integration, not a mandatory customer choice.

| Document | Role |
| --- | --- |
| [Physical AI strategy](physical_ai_strategy.md) | Active direction: first users, product scope, adoption hypotheses and assessment of supplied suggestions |
| [Customer solution delivery](robot_solution_delivery.md) | Proposed service: needs discovery, hardware fit, custom functions, customer acceptance and support |
| [Service operating plan](robot_service_operating_plan.md) | Founder-led execution: first offer, scope limits, delivery gates, team roles, support and economics |
| [Robot execution and evidence contract](robot_execution_contract.md) | Proposed reusable boundary: admission, local enforcement, sessions, partitions and evidence limits |
| [Governed robot skill packages](robot_skill_contract.md) | Proposed packaging, permission, isolation and promotion contract; no loader/studio implemented |
| [Multi-robot team architecture](multi_robot_team_architecture.md) | Implemented organ/agent/cognitive/coordinator contracts; live adapter gates |
| [Microduck integration plan](microduck_integration_plan.md) | Active plan: boundaries, stages, evidence, failure cases |
| [Owner recognition and following](microduck_owner_following_design.md) | Research/proposal: perception, identity, local following, session enforcement and staged acceptance |
| [Microduck architecture study](microduck_architecture_study.md) | Daemons, bus ownership, intent and control |
| [Microduck RL study](microduck_rl_study.md) | Training/deployment flow, 61/14 interface, BAM/backlash, reward design, model variants and policy handover |
| [Microduck source ledger](microduck_source_ledger.md) | Pinned sources, discrepancies, unresolved facts |
| [Supplied studies](sources/README.md) | Original user material with provenance |
| [RL architecture infographic](sources/microduck_rl_architecture_user_supplied.md) | Preserved image, panel reading map and claim qualifications |
| [HAL bridge testing](HAL_TESTING.md) | Earlier Reachy simulation guide; not Microduck bring-up |
| [Reachy demo runbook](reachy_mini_seedcore_demo_runbook_20260414.md) | Dated demo and trust-boundary presentation reference |
| [World Action Model reference](world_action_model_architecture_reference.md) | Related research |
| [VLA optimizations](vla_2026_optimizations.md) | Related research |

## Repository Starting Points

| Existing surface | Reuse or gap |
| --- | --- |
| [HAL interfaces](../../../src/seedcore/hal/interfaces.py) | Capabilities and proprioception; review fit for Microduck intents |
| [HAL service](../../../src/seedcore/hal/service/main.py) | Actuation and token checks; verify the new driver cannot bypass them |
| [Generic simulator](../../../src/seedcore/hal/drivers/robot_sim_driver.py) | Fixture/PyBullet substrate; not a Microduck body model |
| [Revocation](../../../src/seedcore/hal/custody/execution_token_revocation.py) | Shared revocation validation |
| [Simulator tests](../../../tests/test_robot_sim_week4_integration.py) | Existing regression coverage; Microduck tests still needed |
| Microduck driver and RPC adapter | Not present at this revision; planned in M1–M2 |

The generic HAL includes configurable token enforcement and development token
handling. M2 must establish a reviewed deployment profile and command-path
coverage; the existence of validation helpers does not prove that every
physical ingress is governed. Hardware attestation, skill isolation and a
portable edge package also need explicit implementation and validation.

Read the [trust contracts](../trust-runtime/README.md) and
[evidence contracts](../evidence/README.md) alongside robotics work.
