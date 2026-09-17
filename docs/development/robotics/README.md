# Robotics Development

Date: 2026-09-17
Status: Primary next-stage development area

Microduck is the selected integration target. Start with the plan and source
ledger before implementing a driver or selecting a learned policy.

| Document | Role |
| --- | --- |
| [Microduck integration plan](microduck_integration_plan.md) | Active plan: boundaries, stages, evidence, failure cases |
| [Microduck architecture study](microduck_architecture_study.md) | Daemons, bus ownership, intent and control |
| [Microduck RL study](microduck_rl_study.md) | Observations, rewards, transfer, evaluation |
| [Microduck source ledger](microduck_source_ledger.md) | Pinned sources, discrepancies, unresolved facts |
| [Supplied studies](sources/README.md) | Original user material with provenance |
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

Read the [trust contracts](../trust-runtime/README.md) and
[evidence contracts](../evidence/README.md) alongside robotics work.
