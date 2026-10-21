# Robotics Development

Date: 2026-10-20
Status: Primary development area; native reference, Fast Spine fixture and supervised STEM/OEM delivery

SeedCore's robotics direction is a reusable trust runtime for physical AI.
Microduck is the selected reference integration. Read the strategy for product
scope, the proposed contracts for intended behavior, and the integration plan
and source ledger before implementing a driver or selecting a learned policy.

Customer work starts with a person's desired outcome. The team helps assess
the need, select hardware, customize functions, validate results and provide
support. Microduck is the reference integration, not a mandatory customer choice.

## Reference builder workflow

For builders, researchers and supervised STEM work, the target workflow has
three roles. Offline authoring and prepared lessons need no cloud account:

- **Optional remote proposer:** drafts candidate assembly JSON or task intents. Authoring validation, DRC findings and execution admission have separate responsibilities.
- **Local development computer:** runs Mini Studio (`:8767`), Session Lab (`:8766`), native MuJoCo/ONNX tools and Python/Rust verification. Session Lab's issuer is simulation-only; live Agent/PDP integration remains a separate gate.
- **Successive robot designs:** begin with proxy authoring; the one-to-three-servo fixture requires separate qualification. Sensor-head and arm variants need explicit profile/support decisions. Microduck is a separately pinned native reference with 14 policy actions and 15 physical channels; it is not assembled from the draft catalog. Custom-build simulation and physical receipts remain gated.

| Document | Role |
| --- | --- |
| [Physical AI strategy](physical_ai_strategy.md) | Active direction: first users, product scope, adoption hypotheses and assessment of supplied suggestions |
| [18-month execution schedule](../strategy/seedcore_physical_ai_execution_plan_2026_2028.md) | Active Q4 2026–Q1 2028 targets, three pillars, delivery responsibilities, phase gates and 14 Oct–12 Nov tactical work |
| [Mini-robotics cooperation strategy](../strategy/robotics_component_cooperation_strategy_2026.md) | Seven supplied joint/open-hardware initiatives assessed; existing TTL fixture first, ODRI/CubeMars source studies and earlier ten candidates reclassified |
| [Reusable base and printable attachments](../strategy/mini_robotics_base_attachment_product_analysis.md) | Two-tier complete starter/attachment proposal, Robosen evidence/limits, price tests and complete cost/contribution analysis |
| [Ecosystem integration roadmap](robotics_ecosystem_integration_roadmap.md) | Revised COOP-00–06 mini-fixture/joint backlog mapped to CW/M/G; CW-S01 remains next and later commercial/open-joint experiments are alternatives |
| [Partner integration architecture](../integrations/robotics_partner_integration_architecture.md) | Small-fixture control/evidence, supply and fabrication boundaries; CAN/CAN FD remains an unsupported-contract gap |
| [Fast Spine protocol](fast_spine_protocol_spec.md) | Implemented host simulation v1 framing/session/evidence; proposed physical WebSerial/MCU profile; no firmware implemented |
| [Simulation-first acceptance](simulation_first_acceptance.md) | Local ONNX paths, source/profile pins, read-only adapter, independent replay goldens, bounded-session studio and open hardware/training gates |
| [Central World engineering plan](central_world_engineering_plan.md) | 19 Oct–10 Jan component/assembly/DRC/browser/governance workstream; Phase 1 & Phase 2 offline scope delivered, later stages gated |
| [Central World remaining schedule](central_world_remaining_delivery_schedule.md) | CW-A01–CW-L03 work packages, owner roles, dependencies and deliverables for phases 2–5; Phase 2 (`CW-A01..A04`) passed locally, next is `CW-S01` |
| [CW-A01 acceptance closure](central_world_cw_a01_acceptance_plan.md) | Assembly v2 candidate addresses eight findings; local software exit passed with reproducible evidence; CW-A02 handoff |
| [CW-A02 authoring store](central_world_cw_a02_authoring.md), [CW-A03 snapping](central_world_cw_a03_snapping.md) & [CW-A04 DRC/BOM](central_world_cw_a04_drc.md) | Delivered Phase 2 offline authoring store, `15 mm` / `5°` proxy snapping, pure worker DRC, 3D rotated inertia, and unknown-aware BOM |
| [CW-S01 compiler and native parity](central_world_cw_s01_mjcf.md) | Local restricted MJCF compiler and synthetic native parity; separate offline readiness preserves the blocked actual starter; browser/live/hardware work remains open |
| [Central World acceptance matrix](central_world_acceptance_matrix.md) | Required negative/fault/parity/measurement evidence and traceability for the suggested features |
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
| [mjswan integration assessment](mjswan_integration_assessment.md) | Source-reviewed 0.11.9 candidate for CW-S02/CW-S03; engine/training version reconciliation and worker/control/capture qualification required; no runtime imported |
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
| [Component partner pilot briefs](../../application/robotics_component_partner_pilot_briefs.md) | Existing TTL fixture, ODRI source/fabrication study and conditional CubeMars compact-joint feasibility; other mini mechanisms remain task-dependent |

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
