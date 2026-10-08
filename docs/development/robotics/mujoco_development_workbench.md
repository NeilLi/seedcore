# MuJoCo robot development workbench

Date: 2026-10-08
Status: Implemented native development foundation; general imports and browser workbench planned

## Decision

Use MuJoCo as the physics backend for SeedCore's general robot-development
workbench. Internal agents help a user specify a mechanism, draft a controller,
run experiments and interpret recorded results. SeedCore remains responsible
for agent accountability and, on a separate admitted path, execution authority
and evidence closure. MuJoCo supplies simulated dynamics, not hardware truth.

The current browser application is useful for introductory two-link lessons and
custom-engine research. Its existing JS/native/Wasm parity checks establish
agreement among those implementations; they do not establish a general rigid-body
contact model or hardware fidelity. Growing a new contact solver, articulated
model importer and sensor engine is a substantial independent research program.
MuJoCo lets robot-development work use an established engine while the small
educational application remains available.

The user selected a **general robot-development workbench** as the first target,
not a Microduck-only integration. The implemented authoring subset is a first
vertical slice of that workbench, not a claim to support every robot.

## Source and engine choice

The integration pins the official Python package to **MuJoCo 3.15.0**, installed
and exercised on macOS arm64 with Python 3.12.3 and NumPy 1.26.4.
The package includes the native engine; cloning and building the whole upstream
repository is unnecessary for this integration.
[Official Python bindings](https://mujoco.readthedocs.io/en/stable/python.html),
[versioned package](https://pypi.org/project/mujoco/3.15.0/).

MuJoCo models articulated mechanisms with contact, actuators and sensors. MJCF
is its native authoring format; its broader importer capabilities do not imply
that SeedCore has implemented those import workflows.
[Modeling guide](https://mujoco.readthedocs.io/en/stable/modeling.html),
[upstream repository](https://github.com/google-deepmind/mujoco).

Browser delivery remains possible: DeepMind provides canonical JavaScript/
TypeScript bindings and precompiled Wasm in `@mujoco/mujoco`. The versioned
documentation marks the bindings as work in progress. Browser compatibility,
memory ownership, asset loading, worker scheduling and numerical differences
still need qualification. Use the single-threaded build for an initial worker
prototype; the multithreaded build requires cross-origin isolation.
[Versioned Wasm documentation](https://github.com/google-deepmind/mujoco/blob/3.15.0/wasm/README.md).

## Implemented foundation

| Surface | Current behavior |
| --- | --- |
| Typed drafts | Primitive serial mechanisms with 1–6 hinge links, configurable axes, masses, lengths, damping, ranges and torque limits |
| Floating base | Box base with a free joint; an empty chain is a falling-body/contact experiment |
| Model construction | Asset-free MJCF with a floor, bounded motor actuators, encoders, joint velocities, tip position and base IMU sensors |
| Experiments | Passive, constant torque or torque-limited PD position control; configurable initial joint state, timestep and criteria |
| Bounds | Up to 10,000 steps, 20 simulated seconds and 1,001 trace samples; one active job per tool registration budget |
| Trace and measurements | Joint state, control, actuator force, synthetic sensors, energy, contact points/pairs, peak joint speed, limit excursions, saturation and final joint error |
| Provenance | Unique attempt ID, recipe and generated-model SHA-256, adapter/engine version, Python/NumPy and system/architecture |
| Comparison | Preserves timing, initial joint state, gravity, floating-base mode, base height, friction, joint count, joint control task and acceptance criteria |
| Internal agent tools | `simulation.mujoco.build`, `.run` and `.compare` through existing ToolManager and Ray shard registration |
| Agent helper | Provider-neutral draft → validate → build → run → findings helper for an existing agent; one bounded attempt per invocation |

Code lives in [`mujoco_workbench`](../../../src/seedcore/robotics/mujoco_workbench)
and [`mujoco_tools.py`](../../../src/seedcore/tools/mujoco_tools.py).
The motor command limit is a simulation parameter, not a granted hardware limit.
Joint constraints are MuJoCo soft constraints; traces report excursions rather
than claiming a perfectly rigid stop. Adjacent primitive bodies are excluded
from mutual contact because their capsule geometry overlaps at the hinge.
Non-adjacent body and floor contacts remain enabled.

Each run owns fresh `mjModel` and `mjData`. The runner checks native warnings and
non-finite state each tick and stops on numerical failure. It never substitutes
the old browser engine, PyBullet or pose fixtures for an unavailable MuJoCo engine.
Derived sensors are recomputed at the recorded state, and the final tick is
captured even when it is not a sample interval boundary.

`criteria_met` means only that the explicitly requested checks passed in this
simulation. No criteria gives `completed_unassessed`; a warning gives
`numerical_failure`. These states are not a `RESULT_VERIFIER` verdict, signed
physical evidence or permission to deploy a controller. Recipe hashes identify
the experiment input, not cryptographic proof of the recorded output.

## Run and review

Install into the existing repository Python environment:

```bash
.venv/bin/python -m pip install 'mujoco==3.15.0'
# For a normal package installation, the optional extra is seedcore[robotics-sim].
```

Run from the repository root:

```bash
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py build \
  --mjcf-output artifacts/robotics/mini-robot.xml --output artifacts/robotics/mujoco-model.json
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py run \
  --example arm --output artifacts/robotics/mujoco-arm.json
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py run \
  --example contact --output artifacts/robotics/mujoco-contact.json
PYTHONPATH=src .venv/bin/python scripts/robotics/mujoco_workbench.py compare \
  --output artifacts/robotics/mujoco-comparison.json
```

The CLI also accepts `--spec path.json`: a `RobotSpec` for build, an
`ExperimentSpec` for run, or a `ComparisonSpec` for compare. An output's `request`
field is the complete editable recipe. Output directories are created as needed.
The optional native viewer can inspect the exported model:

```bash
.venv/bin/python -m mujoco.viewer --mjcf=artifacts/robotics/mini-robot.xml
```

That viewer is an independent exploratory session, not replay of an experiment.
Opening it does not establish an admitted robot session. The passive viewer API
has a separate macOS `mjpython` requirement; the workbench CLI is headless and
does not need that launcher.

## Internal-agent workflow

Set `SEEDCORE_ENABLE_MUJOCO_TOOLS=1` in the environment of the SeedCore runtime
and its tool shards, then restart those processes. The opt-in registration is
wired into OrganismCore single/sharded initialization and BaseAgent's local
ToolManager fallback. It requires the pinned dependency on each worker.
Disabled registration does not import the native engine. Registration failures
are surfaced, and existing tool RBAC still applies. This work did not launch
the live distributed runtime or connect a live model provider.

For an existing developer-owned manager, explicitly call
`await register_mujoco_tools(manager)`. An internal agent can then:

1. Clarify the user's mechanism, intended motion, units and measurable outcome.
2. Propose a JSON design/controller and inspect it with `simulation.mujoco.build`.
3. Run the recipe with `simulation.mujoco.run` and cite measured trace/metric fields.
4. Compare a candidate with `simulation.mujoco.compare` under the same task and
   acceptance criteria; explain tradeoffs and remaining uncertainty.
5. Return the model, recipe and results for user review. A failed check requires
   review of its diagnostics, not an automatic relaxation of the check.

[`RobotDevelopmentAssistant`](../../../src/seedcore/robotics/mujoco_workbench/assistant.py)
accepts an existing agent ID, ToolManager, a caller-provided asynchronous JSON
cognitive adapter and an operator/developer experiment template. The adapter
returns only robot parameters, controller parameters and rationale. It cannot
change the template's time budget, initial state or criteria, supply routing or
mint authority. The rationale is labeled advisory; deterministic findings refer
to `experiment.checks.*`. The helper does not create new actors or tune itself
until a gate passes. Connecting the cognitive adapter to a deployed model remains
the application's responsibility, as with `RobotCognitivePlanner`.

No tool accepts arbitrary Python, raw MJCF, file paths, plugins, external assets,
hardware endpoints or tokens. These tools compute ephemeral results rather than
writing files, memory or policy. The developer CLI can explicitly export files.
They are therefore development computation tools, not an alternate actuator
path. Live motion must still follow Agent → ActionIntent → PDP → bounded token/
session → local enforcement → physical telemetry → independent closure.

## Qualification and measured example

On this Mac, the three-second arm comparison retained the same 0.05 rad final
error and 10 rad/s peak-speed criteria:

| Controller | Final maximum joint error | Peak joint speed | Outcome |
| --- | --- | --- | --- |
| PD gains 12 / 1 | 0.05720 rad | 7.042 rad/s | Error criterion failed |
| PD gains 48 / 1 | 0.01410 rad | 18.217 rad/s | Speed criterion failed |

The second controller improves final tracking but violates the speed criterion.
Neither candidate is accepted by the recipe. This is a useful agent explanation
and review case, not a tuning success or permission to move hardware.
The free-body experiment produced four floor contact points and settled near its
0.04 m base half-height. That result validates this synthetic fixture only.

Verification:

- 121 focused tests passed across the workbench, ToolManager schemas, existing
  robot-team runtime and navigation sandbox. Native checks include analytic free
  fall, floor contact, sensor/state agreement, torque limits, fresh-instance
  repeatability, numerical warnings, comparison scope and internal agent routing.
- Q2 contract checks passed; the optional Postgres integration lane was skipped.
- Authorization: 79 unit tests passed; the live phase could not connect to the
  API at `127.0.0.1:8002`. Live service verification remains unverified.
- Native MuJoCo rendering was exercised on this Mac. Browser rendering and
  native/browser physics parity were not tested.

## Remaining development sequence

1. **Model packages and imports:** reviewed MJCF/URDF packages with asset hashes,
   limits, sensor contracts and frame checks. Qualify an actual Microduck model
   separately; the primitive builder is not its body model. Add articulated trees,
   transmissions and actuator calibration where required by the selected robot.
2. **Interactive workspace:** a 3D browser scene, model inspector, conversation,
   experiment comparison and recorded replay. Stream native-engine results first;
   qualify the canonical Wasm worker for local no-install physics where it fits.
   Each run has one physics-state owner; UI animation cannot overwrite it.
3. **Development evaluations:** task-specific scenarios, parameter sweeps,
   missing/noisy/delayed sensors and regression packs. Preserve failed gates and
   model/recipe identity. Add MJX/Warp only when batch throughput requires it.
4. **Hardware and governed simulation:** measured mass/inertia/friction, backlash,
   latency and sensor behavior; validated runtime adapter, bounded sessions,
   revocation, interruption, authenticated capture and independent closure.

This work supports the [Microduck integration plan](microduck_integration_plan.md)
and [execution contract](robot_execution_contract.md) without claiming their
hardware gates are complete. Simulation can shorten development cycles; improved
hardware fidelity still requires measurements and validation against a real body.
