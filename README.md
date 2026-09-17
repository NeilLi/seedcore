# SeedCore

[![Unit Tests](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/NeilLi/seedcore/actions/workflows/unit-tests.yml)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

SeedCore is an application studio building experiences for places, journeys,
and real things. The public story starts at [seedcore.ai](https://seedcore.ai/):
five application worlds make the work legible before the runtime details begin.

This repository contains the application prototypes, governed execution
runtime, proof surfaces, and development contracts behind that story. Its
application layers let people explore, ask, preview, and use experiences while
the trust boundary underneath remains explicit.

The next development stage focuses on **Microduck and robotics integration**:
simulation, bounded agent-to-robot intent, physical telemetry, and replayable
execution proof. Start with the
[robotics development map](docs/development/robotics/README.md) and
[active queue](docs/development/current_next_steps.md). Existing application
prototypes remain available; their expansion is deferred behind this focus.

## Start with the applications

The website presents one portfolio rather than five unrelated products:

| Application world | The experience | Current repository connection |
| --- | --- | --- |
| **Digital City** | Ask for a nearby café, maker, garden, or small detour and turn the answer into a walk. | `apps/neighborhood-guide` — working Godot prototype with a Blender-rendered entrance and Foundry Lane district. |
| **Tourist Design Studio** | Turn a favorite detail from a trip into a souvenir a visitor can preview and help design. | Website interaction and application contracts; [experience references](docs/development/applications/experiences/README.md). |
| **Family Journey** | Follow a story, find a clue, and make the destination part of the shared adventure. | Journey and city contracts in `docs/development/applications/city/journey_driven_digital_city_experience.md`. |
| **Craft & Collectibles** | Discover handmade pieces and treasured finds with maker stories, materials, care, and provenance. | Restricted Custody Transfer and local-producer proof contracts in `docs/development/`. |
| **Robot Moments** | Let a friendly tabletop robot guide a small activity while people choose what happens next. | [Microduck integration](docs/development/robotics/microduck_integration_plan.md) is the next-stage robotics focus; robot output does not grant authority. |

The application layer may discover, explain, visualize, recommend, collect
preferences, and preview an ordinary experience. It may not authorize its own
actions. Booking, payment, custody movement, policy changes, deployment,
quarantine clearance, and other high-consequence mutations remain governed
actions.

## The application-layer contract

SeedCore separates the part a person experiences from the part that grants
execution authority:

```
person / operator
  -> application layer
       discover • ask • plan • preview • tell a story
  -> accountable Agent
  -> ActionIntent
  -> Policy Decision Point (PDP)
  -> scoped ExecutionToken or PolicyDeny
  -> actuator / provider
  -> evidence bundle and transition receipt
  -> replay / RESULT_VERIFIER
  -> verified, rejected, review, or quarantine
```

Application output is advisory or presentational until a named action enters
the Agent Action Gateway and passes the PDP. A memory, model suggestion,
retrieved fact, generated story, route, simulation, or flywheel adjustment does
not become authority merely because an application displays it.

| Application layers do | The trust runtime decides |
| --- | --- |
| Discover places, people, objects, and stories | Whether a proposed action is admissible |
| Match a request to a small journey or route | Which principal, scope, and policy apply |
| Preview a design, itinerary, handoff, or interaction | Whether a bounded `ExecutionToken` may be minted |
| Show source, freshness, claim state, and uncertainty | Whether revocation, evidence, and context checks pass |
| Ask for confirmation and operator correction | Whether execution closes with replayable proof |

This is a trust runtime, not a traditional cybersecurity detector. It governs
execution inside an environment and produces proof of what happened afterward.

## The first application entrance: Digital City

`apps/neighborhood-guide` is the current end-to-end application slice. It opens
to a 2D navigation entrance, then leads into a small interactive 3D district:

- the entrance is an original orthographic Blender render with five destination
  cards and four scene hotspots;
- **Explore**, **Makers**, **Craft**, and **Your guide** markers lead to the
  corresponding local experience;
- the district supports place selection, tag-based matching, garden detours,
  pedestrian route previews, visitor movement, pause/resume, replay, and reset;
- route and place state are presentation and discovery state only; no route
  starts a booking, payment, custody action, or external write.

Run it locally:

```bash
cd apps/neighborhood-guide
godot --path .
```

The editable scene is
[the Blender entrance source](apps/neighborhood-guide/assets/blender/neighborhood_entrance.blend).
The app image is
[the rendered entrance](apps/neighborhood-guide/assets/illustrations/entrance_render.png).
To re-render after editing the Blender source:

```bash
cd apps/neighborhood-guide
blender --background assets/blender/neighborhood_entrance.blend --python tools/render_entrance_blender.py
godot --headless --path . --editor --quit
```

Read the application-specific guide in
[apps/neighborhood-guide/README.md](apps/neighborhood-guide/README.md).

## Runtime foundation beneath the apps

The application portfolio is built on a deterministic execution and proof
runtime for high-consequence workflows. Its current baseline includes:

- Agent Action Gateway v1 and stateless PDP evaluation;
- active authorization-graph checks and AI-origin mutation gates;
- short-lived, scoped, revocable `ExecutionTokens`;
- replayable evidence bundles, signed receipts, and transition evidence;
- coordinator-embedded `RESULT_VERIFIER` with fail-closed mismatch handling;
- Rust proof-kernel paths and TypeScript verification surfaces; and
- read-only city discovery, public/protected redaction, and local-producer
  provenance contracts.

The first authority-bearing vertical remains Agent-Governed Restricted Custody
Transfer (RCT), currently expressed through the collectible rare-shoe custody
handoff. The broader application layers make discovery, storytelling, and
ordinary coordination useful around that trust spine without inheriting its
authority.

## Repository map

| Path | Role |
| --- | --- |
| `apps/neighborhood-guide` | Godot application layer, Blender source, 2D entrance, 3D district, and local interaction checks |
| `src/seedcore` | Python runtime, PDP-facing APIs, gateway, discovery, custody, evidence, and coordinator services |
| `rust` | Offline and embedded proof-kernel implementation plus transfer fixtures |
| `ts/apps` and `ts/packages` | Verification API, operator console, proof surface, and typed contracts |
| `tests` | Runtime, discovery, evidence, replay, custody, and application contract tests |
| `docs/development` | Active application directions, contracts, promotion gates, and current queue |
| `docs/architecture` | Architecture decisions and runtime topology |
| `scripts/host` | Focused host verification and operational checks |

The public website is maintained as the application-facing companion project at
[seedcore.ai](https://seedcore.ai/). Its five-scene narrative is the product
entry point; this repository supplies the prototypes and governed foundation.

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

### Add an application surface

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

The application portfolio is not a generic coding-agent harness, marketplace,
super app, municipal authority, utility-control platform, or traditional
cybersecurity product. This repository does not activate a global marketplace,
legal cadastre, emergency dispatch system, licensed transport operation, or
real escrow rail.

Do not make memory, retrieval, model output, generated media, discovery,
simulation, route planning, or flywheel feedback an authority source. Do not
introduce a governed mutation without an accountable principal, explicit PDP
decision, scoped and non-revoked token, actuator evidence, and verifier closure.

## Further reading

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
