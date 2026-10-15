# Robotics Development

Date: 2026-10-14
Status: Primary development area; native reference, Fast Spine fixture and supervised STEM/OEM delivery

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
| [18-month execution schedule](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md) | Active Q4 2026–Q1 2028 targets, three pillars, delivery responsibilities, phase gates and 14 Oct–12 Nov tactical work |
| [Fast Spine protocol](fast_spine_protocol_spec.md) | Implemented host simulation v1 framing/session/evidence; proposed physical WebSerial/MCU profile; no firmware implemented |
| [Simulation-first acceptance](simulation_first_acceptance.md) | Local ONNX paths, source/profile pins, read-only adapter, independent replay goldens, bounded-session studio and open hardware/training gates |
| [Central World engineering plan](central_world_engineering_plan.md) | 19 Oct–10 Jan component/assembly/DRC/browser/governance workstream; Phase 1 foundation delivered, later stages gated |
| [Component registry](../../../packages/component-registry/README.md) | Strict four-block schema, 12 illustrative drafts, hashed GLBs, semantic linter and local read-only viewer; no qualified hardware or execution authority |
| [Day-30 review sheet](day30_simulation_review.md) | Early evidence inventory, missing physical measurements and go/rescope/defer criteria |
| [Customer solution delivery](robot_solution_delivery.md) | Proposed service: needs discovery, hardware fit, custom functions, customer acceptance and support |
| [Service operating plan](robot_service_operating_plan.md) | Small-team execution: first offer, scope limits, delivery gates, team roles, support and economics |
| [Robot execution and evidence contract](robot_execution_contract.md) | Proposed reusable boundary: admission, local enforcement, sessions, partitions and evidence limits |
| [Governed robot skill packages](robot_skill_contract.md) | Proposed packaging, permission, isolation and promotion contract; no loader/studio implemented |
| [Robot Learning Studio solution](robot_learning_studio_solution.md) | Proposed mission workflow grounded in the PKG and hotel simulators; browser/custom-engine decision, contracts, evidence and curriculum |
| [Mini robot simulator implementation architecture](mini_robot_simulator_implementation_plan.md) | Proposed C++/Wasm engine, compiled assets, state, sensors, batches and browser delivery; current-app inspection and SIM-1–SIM-6 acceptance gates |
| [Mini Robot Lab prototype](../../../apps/mini-robot-simulator/README.md) | Delivered planar lessons and 1/2/3-link orbit studio slice; broader SIM-3 gates open; no hardware or governed execution connection |
| [Multi-robot team architecture](multi_robot_team_architecture.md) | Implemented organ/agent/cognitive/coordinator contracts; live adapter gates |
| [PythonRobotics applicability](pythonrobotics_assessment.md) | Source review and implemented offline planar navigation baseline; advisory only, no hardware connection |
| [MuJoCo development workbench](mujoco_development_workbench.md) | Implemented native model/experiment foundation, internal agent tools and external package inspection; browser workspace planned |
| [Model package ingestion](model_package_ingestion.md) | Implemented versioned integrity manifests, MJCF/URDF loader and pinned Microduck model with mass/joint/tree parity checks |
| [Robot design toolkit assessment](robot_design_toolkit_assessment.md) | Accepted research recommendation: Rhoban/Onshape first, FreeCAD/RobotCAD second; sources, conversion fidelity and proposed CAD-to-MuJoCo integration |
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
| [Embodied AI research report](../reports/embodied_ai_research_report.md) | Archived external literature; timing, benchmark and safety claims require qualification in the architecture reference |
| [Embodied AI architecture reference](embodied_ai_architecture_reference.md) | Reviewed research interpretation: industrial giants vs DIY mini-robotics paradigm shift, "slow brain, fast spine" receding-horizon action chunking, and Microduck milestone focus |
| [Mini-robotics developer blueprint](mini_robot_developer_blueprint.md) | Proposed board/TTL fixture, quoted cost targets, authenticated firmware/session requirements and gated browser-to-hardware workflow |
| [OEM partnership brief](../../application/oem_partnership_brief.md) | Draft SeedCore Inside design-in, open/paid boundaries, QA, support and staged kit distribution |

## Repository Starting Points

| Existing surface | Reuse or gap |
| --- | --- |
| [HAL interfaces](../../../src/seedcore/hal/interfaces.py) | Capabilities and proprioception; review fit for Microduck intents |
| [HAL service](../../../src/seedcore/hal/service/main.py) | Actuation and token checks; verify the new driver cannot bypass them |
| [Generic simulator](../../../src/seedcore/hal/drivers/robot_sim_driver.py) | Fixture/PyBullet substrate; not a Microduck body model |
| [Revocation](../../../src/seedcore/hal/custody/execution_token_revocation.py) | Shared revocation validation |
| [Simulator tests](../../../tests/test_robot_sim_week4_integration.py) | Existing regression coverage; Microduck tests still needed |
| [Microduck read-only driver](../../../src/seedcore/hal/drivers/microduck.py) | Offline MuJoCo and explicit fake-I/O profiles implemented; native admitted RPC motion remains M2 work |

The generic HAL includes configurable token enforcement and development token
handling. M2 must establish a reviewed deployment profile and command-path
coverage; the existence of validation helpers does not prove that every
physical ingress is governed. Hardware attestation, skill isolation and a
portable edge package also need explicit implementation and validation.

Read the [trust contracts](../trust-runtime/README.md) and
[evidence contracts](../evidence/README.md) alongside robotics work.
