# SeedCore Mini Robot Lab

Status: Early browser research prototype; local SIM-1 contracts and qualification completed 2026-10-07.

A small learning application with an original two-link physics engine. Learners
predict a result, adjust joint targets, motor strength or arm mass, run an
experiment, and replay the calculated observations. The three prepared
experiments are reaching a star, turning motors off and trying a heavier arm.

## Run

Serve the app over HTTP(S) in a modern browser. All application assets are
local; learners need no packages, accounts, API keys or remote services.
Direct `file://` opening is unsupported because the simulation uses a worker.

For a local HTTP preview, run from this directory:

```bash
python3 -m http.server 8766 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8766`. A public deployment is not included.
The local server works without internet access; offline reopening from a
previously hosted site is not implemented.

## Implemented Physics

`physics.js` contains the original dynamics implementation, independent of the
browser and any external physics library:

- planar fixed-base arm with two revolute joints and uniform rigid links;
- configuration-dependent inertia, Coriolis terms, gravity and viscous damping;
- torque-limited proportional/derivative control with gravity compensation;
- fixed-step RK4 integration, forward kinematics and mechanical energy;
- explicit rejection of invalid inputs and numerical divergence.

Positions use radians, lengths meters, masses kilograms and torques N·m. The
first joint angle is measured from positive x; the second is relative to the
first link. Positive y points upward. The worker advances at 480 physics steps per
simulated second and records observations at 60 samples per simulated second.
Rendering follows simulated time; this is not a real-time hardware controller.

The reaching lesson requires the tip to remain within 3 cm of its target and
below 0.05 m/s throughout the final half-second of a six-second experiment.
These are educational simulation criteria, not physical robot safety limits.

The model has no contact solver, collisions, mechanical joint stops, floating
base, actuator electrical dynamics, URDF/MJCF importer or Microduck model.
It is a first research case for a custom engine, not a general robotics engine.

## Worker Boundary: SIM-1

`simulation-worker.js` owns integration and its integer tick. One callback
advances eight fixed steps, then yields. Monotonic deadlines compensate chunk
computation time; delayed work rebases wall pacing without enlarging the step or
skipping ticks. A six-second experiment records all 361 observations, including
tick zero. Exactly three reusable transferable buffers bound snapshot memory.
If the page stops returning buffers, physics waits while pause/reset remain
acknowledgeable. Old-run buffers are returned without becoming current samples.

`packages/mini-sim-contracts` supplies TypeScript source, JSON input/command
schemas, generated browser bindings and golden model/run fixtures. The narrow
compiler emits immutable planar descriptors, explicit frames and uniform-rod
inertias, stable body/joint indices and SHA-256 model and run-recipe identities.
It supports the existing two-link teaching model, not arbitrary articulations.

Commands use `seedcore.mini-lab.worker.v2` and bind run ID, model revision,
sequence, requested application tick and both digests. Reset validates settings
and identities before replacement. Start/pause/step apply at the next worker
boundary and acknowledge their actual tick. `set-control` queues exact-tick
bounded control changes, with a maximum of 32 pending inputs and distinct
queued/applied acknowledgements. The learner UI continues to reset when a
setting changes. Replies also carry monotonic frame sequences and load metrics.

The UI retains in-flight pause samples, rejects stale identities, duplicate
frames and incomplete observation coverage, and waits for acknowledgements.
Worker failures or a five-second acknowledgement timeout stop visibly; Reset
creates a new worker when needed. Hidden tabs request pause. Browser scheduling
is not a hard real-time stop. The page has no UI-thread physics fallback.

The [contract documentation](../../packages/mini-sim-contracts/README.md)
details schemas, tick semantics and buffer ownership. The
[local qualification report](../../tools/mini-sim/qualification-2026-10-07.md)
records three lesson traces, a UI stall and pinned laptop/browser measurements.
Tablet, cross-browser and full release budgets remain unqualified. Checkpoints
and the native/Wasm engine are SIM-2 work.

## Learning And Execution Boundaries

The application runs isolated local experiments. It does not call SeedCore's
gateway, mint execution authority, control hardware or produce authenticated
robot execution evidence. Feedback uses deterministic lesson rules and measured
simulation values, without an AI service. JSON downloads identify their source
as local research simulation and include model, settings and recorded samples.

Replay reads samples without advancing physics. Editing settings resets the
experiment and invalidates its previous observations. Hiding the browser tab
pauses the experiment. A future physical-robot connection must use the existing
Agent/PDP/token/edge/evidence boundary and separate integration acceptance.

The broader [learning studio solution](../../docs/development/robotics/robot_learning_studio_solution.md)
describes the mission, agent and governance design. The user's subsequent
direction is browser delivery without installation and a new physics engine
as a core research objective. Blender remains a potential asset-authoring tool;
Godot and MuJoCo remain useful references and comparison environments.

## Verify

Developer checks require Node.js and the existing locked TypeScript toolchain
in `ts/node_modules`; learners need neither:

```bash
# From the repository root:
node tools/mini-sim/verify.cjs
# After changing TypeScript contracts:
npm --prefix packages/mini-sim-contracts run build
```

The verifier typechecks and confirms generated artifacts, checks syntax and runs
37 tests: 12 original physics invariants, 12 worker/transfer/tick-input cases,
nine UI-boundary cases and four compiler/identity/golden-fixture cases. All
three worker lesson traces equal the direct reference exactly. Exhausted buffer
pools, reset with outstanding loans, same-tick inputs, stale digests and sequences,
queue capacity and incomplete completion are tested.

To repeat browser measurements, serve the repository root and open
`/tools/mini-sim/browser-qualification.html`. The harness reports foreground RAF
intervals, pause latency, wall pacing, buffer occupancy and exact trace/coverage
checks. These are local engineering measurements, not hardware fidelity or
release-device qualification. The learner UI was also checked for single
step/continue and successful target completion.

## Next Research Gates

The [implementation architecture](../../docs/development/robotics/mini_robot_simulator_implementation_plan.md)
defines the proposed SIM-1–SIM-6 sequence following inspection of SeedCore and
its related apps on 2026-10-05:

1. SIM-1 is locally implemented and measured; release-device qualification remains open.
2. Port the reference model to an owned C++ core with native and Wasm builds.
3. Develop compiled tree models, articulated dynamics, encoders and a 3D view.
4. Validate floating bodies, contacts, friction, joint limits and further sensors.
5. Add independent-instance batches and measure headless throughput.
6. Qualify robot imports and a separate governed SeedCore simulation bridge.

Learner usability and browser size/performance are checked throughout. Beyond
SIM-1, these remain planned capabilities.

Each expansion needs independent numerical and behavioral acceptance evidence.
Reduced coordinates alone do not guarantee contact stability, and a successful
animation does not establish physical accuracy.
