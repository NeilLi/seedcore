# SeedCore

[![Unit Tests](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**A trust runtime for physical AI.**

SeedCore's team aims to help people identify what they want a small robot to
do, choose suitable hardware, and build and support the functions they need.
The trust runtime is the technical foundation for delivering those solutions.

SeedCore governs whether an AI agent may act, issues bounded execution
authority, and verifies evidence of the attempt. The current focus is small
robots, with **Microduck as the first integration target**.

Models provide plans and personalities. SeedCore connects those proposals to
accountable agents, explicit permissions, revocable execution and an evidence
trail. The robot's onboard controller retains control of its motors and local
safety behavior.

**Current status:** the repository contains the governance and proof foundation,
HAL interfaces, generic simulation and local multi-robot orchestration contracts.
The Microduck adapter, bounded motion sessions and hardware acceptance are
planned work. This is not a claim of production readiness or certified physical
safety.

Start with the [physical AI strategy](docs/development/robotics/physical_ai_strategy.md),
[development map](docs/development/README.md) and
[active integration queue](docs/development/current_next_steps.md).

## Why small robots

As more people build robot behaviors, an application needs to answer more than
“can the model generate a command?” It needs to identify who permitted the
attempt, constrain its duration and capabilities, handle interruption, and
explain the observed outcome.

The customer starts with a need: an engaging exhibit, a personal robot routine,
or help presenting something in a studio or shop. SeedCore's proposed service
is to clarify the job, compare hardware, implement a bounded function, validate
it with the user, and provide ongoing support. Initial trials target activities
an adult can supervise. Customer demand and delivery economics need validation.

Internally, the reusable unit is a **governed skill attempt** across robot bodies
and AI models. Robotics developers and hardware partners help deliver these
solutions. Microduck is the first engineering reference; each customer's need
determines which body fits. Read the
[customer delivery model](docs/development/robotics/robot_solution_delivery.md).

## How it fits

```text
application / model proposes
  -> accountable Agent creates ActionIntent
  -> Policy Decision Point (PDP) allows or denies
  -> short-lived, scoped, revocable ExecutionToken
  -> robot execution boundary validates authority and command limits
  -> onboard controller attempts the action; local safety may refuse or stop
  -> action-bound telemetry and receipts
  -> replay / RESULT_VERIFIER closes or rejects the evidence
```

Admission, local enforcement and evidence closure have different deadlines.
Network policy calls and evidence upload stay outside the balance/control loop.
A local stop must remain effective when the planner or network is unavailable;
resuming requires valid authority. These are robotics integration requirements,
not claims that the pending adapter already enforces them.

| Layer | Owns |
| --- | --- |
| Application, persona and AI planner | Interaction and proposed intent |
| SeedCore Agent and PDP | Accountability, delegation and bounded authorization |
| SeedCore edge execution boundary | Token/session validation, command bounds and revocation enforcement |
| Native robot runtime | Motor control, balance, local interlocks and physical response |
| Evidence pipeline and RESULT_VERIFIER | Authenticated records, closure checks and replay |

A token establishes permission under policy; it cannot guarantee physical safety.
An actuator acknowledgement does not prove task completion. Signed telemetry
establishes provenance and integrity under its capture/key assumptions, not
sensor truth. Read the proposed
[robot execution contract](docs/development/robotics/robot_execution_contract.md)
for timing, partitions, recovery and evidence limits.

## What exists and what comes next

| Surface | Repository status | Evidence or next gate |
| --- | --- | --- |
| Agent Action Gateway, PDP, tokens and revocation | Implemented foundation | [Policy gates](docs/development/policy_gate_matrix.md) and existing regression suites |
| Receipts, telemetry closure, Rust proof kernel and TypeScript proof surfaces | Implemented foundation | Existing custody and verifier fixtures; robotics capture/closure still needs integration |
| HAL, Reachy drivers and generic robot simulator | Existing integration surfaces | [Robotics map](docs/development/robotics/README.md); not a Microduck dynamics model |
| Multi-robot proposals, reservations and closure barriers | Implemented local orchestration | [Team architecture](docs/development/robotics/multi_robot_team_architecture.md); in-memory ownership, live adapters pending |
| Microduck driver and bounded motion session | Planned, M0–M3 | Pinned runtime/profile, admission, local interruption and action-bound evidence |
| Supervised Microduck hardware | Planned, M4 | Measured limits and repeatable allowed/denied/interrupted cases |
| Portable skill packages and studio | Proposed follow-on | [Skill contract](docs/development/robotics/robot_skill_contract.md); enforcement before distribution |

Repository code and local tests establish only their stated scope. They do not
prove all command paths are governed on a deployed robot. The existing HAL has
configurable development behavior; a robotics deployment must close alternate
paths and enforce the reviewed profile before claiming coverage.

## First demonstration

An agent proposes a short bounded move in a supervised test area, followed by
a stop. The operator can inspect the request, granted limits, observed motion
and verifier outcome. The same demonstration must show denial, expired or
revoked authority, lost command input and missing evidence.

The sequence is: pin the runtime and policy, establish read-only simulation,
admit one bounded session, close its evidence, then measure the behavior on
supervised hardware. Learning produces candidate policies; it does not authorize
installation or motion. See the
[Microduck plan](docs/development/robotics/microduck_integration_plan.md).

You can inspect the existing team proposal layer without a robot or model API:

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/plan_team_demo.py --scenario football
PYTHONPATH=src .venv/bin/python scripts/robotics/plan_team_demo.py --scenario work
PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_robot_team_runtime.py
```

These commands assume the repository Python environment is installed. The demos
print proposed tasks using fixtures; they do not mint tokens, move robots or
prove a successful physical match.

## Existing applications and regression foundation

Restricted Custody Transfer (RCT), including the rare-shoe handoff, remains a
reference for delegated authority, receipts, revocation and replay regressions.
Robotics reuses that foundation while adding continuous local enforcement and
interrupted or uncertain physical outcomes.

The [public application studio](https://seedcore.ai/) presents city, travel,
family, craft and robot experiences. Those experiences can showcase the runtime.
Their expansion is deferred behind the current robotics integration.

The existing [Digital City prototype](apps/neighborhood-guide/README.md) remains
available with its Blender entrance, Godot district, route previews and local
interaction checks:

```bash
cd apps/neighborhood-guide
godot --path .
```

Its discovery and route previews do not authorize bookings, payments or custody
movement. See [application directions](docs/development/application_directions.md)
for maintained and deferred work.

## Repository map

| Path | Role |
| --- | --- |
| `src/seedcore/robotics` | Team proposals, robot bindings, reservations and closure barriers |
| `src/seedcore/hal` | Driver interfaces, actuator admission, simulation and revocation |
| `apps/neighborhood-guide` | Existing Godot and Blender application prototype |
| `src/seedcore` | Python runtime, PDP-facing APIs, gateway, discovery, custody, evidence, and coordinator services |
| `rust` | Offline and embedded proof-kernel implementation plus transfer fixtures |
| `ts/apps` and `ts/packages` | Verification API, operator console, proof surface, and typed contracts |
| `tests` | Runtime, discovery, evidence, replay, custody, and application contract tests |
| `docs/development` | Robotics strategy, integration plans, shared contracts and current queue |
| `docs/architecture` | Architecture decisions and runtime topology |
| `scripts/host` | Focused host verification and operational checks |

## Development paths

### Run the host-mode runtime

For macOS or laptop development, use the host-mode helpers in
[deploy/local/README.md](deploy/local/README.md):

```bash
brew services start postgresql@17
brew services start redis
PGUSER=$(whoami) bash deploy/local/init-full-db-direct.sh
bash deploy/local/run-api.sh
bash deploy/local/run-hal.sh
bash deploy/local/run-task-stack.sh start
```

The usual local endpoints are API ingress at `http://127.0.0.1:8002`, HAL at
`http://127.0.0.1:8003`, and Ray Serve at `http://127.0.0.1:8000`.

### Run the proof and operator surfaces

```bash
cargo test --workspace --no-default-features --manifest-path rust/Cargo.toml
cargo build -p seedcore-verify --manifest-path rust/Cargo.toml
npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run build
```

Transfer-proof example:

```bash
cargo run -q --manifest-path rust/Cargo.toml -p seedcore-verify -- summarize-transfer --dir rust/fixtures/transfers/allow_case
```

### Add a governed skill or application

Start with the smallest coherent person-facing loop:

1. define the person, moment, and ordinary outcome;
2. use reviewed fixtures or public-safe projections with source and freshness;
3. keep routes, recommendations, stories, simulations, and previews advisory;
4. add operator correction and visible uncertainty where claims can change;
5. introduce a named governed action only after its `ActionIntent`, PDP policy,
   token constraints, evidence, replay, and verifier behavior are specified; and
6. promote production, secrets, custody closure, quarantine clearance, and
   policy changes only through human review or an explicit policy gate.

The active sequence is maintained in
[docs/development/current_next_steps.md](docs/development/current_next_steps.md).
The portfolio decisions and boundaries are in
[docs/development/application_directions.md](docs/development/application_directions.md).

## Verification

Start with the repository gates named in [AGENTS.md](AGENTS.md):

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

For the Digital City application:

```bash
cd apps/neighborhood-guide
./tools/check_environment.sh
./tools/validate_project.sh
```

For focused Python, TypeScript, and Rust checks:

```bash
pytest tests/test_flywheel_harness.py tests/test_energy.py -q
npm --prefix ts run typecheck
cargo test --workspace --no-default-features --manifest-path rust/Cargo.toml
```

When a deterministic gate fails repeatedly, stop autonomous iteration and
surface the verifier output and runbook evidence for review.

## Boundaries and non-goals

SeedCore focuses on execution authority and evidence. It does not replace a
robot controller, physics simulator or hardware safety engineering. Unattended
household operation, child/eldercare use, public skill distribution and additional
hardware rollouts require work beyond the current pilot. It is not a generic
coding-agent harness, marketplace or traditional cybersecurity detector.

Do not make memory, retrieval, model output, generated media, discovery,
simulation, route planning, or flywheel feedback an authority source. Do not
introduce a governed mutation without an accountable principal, explicit PDP
decision, scoped and non-revoked token, actuator evidence, and verifier closure.

## Further reading

- [Physical AI strategy](docs/development/robotics/physical_ai_strategy.md)
- [Robot execution contract proposal](docs/development/robotics/robot_execution_contract.md)
- [Governed skill package proposal](docs/development/robotics/robot_skill_contract.md)
- [Microduck RL architecture and sim2real study](docs/development/robotics/microduck_rl_study.md)
- [Public application studio](https://seedcore.ai/)
- [Development map](docs/development/README.md)
- [Application directions](docs/development/application_directions.md)
- [Current next steps](docs/development/current_next_steps.md)
- [Policy gate matrix](docs/development/policy_gate_matrix.md)
- [Trust-runtime category distinction](docs/development/trust_runtime_category_distinction.md)
- [Architecture overview](docs/architecture/overview/architecture.md)
- [Agent Action Gateway contract](docs/development/trust-runtime/agent_action_gateway_contract.md)
- [ExecutionToken lifecycle](docs/development/trust-runtime/execution_token_lifecycle_management.md)
- [Rare-shoe RCT demo specification](docs/development/applications/rct/rare_shoes_collecting_transfer_demo_spec.md)
- [Flywheel harness](docs/development/seedcore_flywheel_harness.md)

## License

SeedCore is licensed under the Apache-2.0 License. See [LICENSE](LICENSE).
