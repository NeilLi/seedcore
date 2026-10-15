# SeedCore Mini Robot Lab

Status: Local browser research prototype; SIM-1/SIM-2 delivered and the narrow SIM-3 planar 1/2/3-link orbit studio slice implemented. Broader SIM-3 gates remain open. Status checked 2026-10-14.

The additional `session-lab.html` pairs the tree studio with a localhost-only
bounded controller rehearsal. It requires the Python host below; the original
lessons continue to work from a static server. No hardware is connected.

```bash
# From the repository root, with the project environment and Rust verifier built:
.venv/bin/python scripts/robotics/serve_session_lab.py
```

Open `http://127.0.0.1:8766/studio/session-lab.html`. The host owns simulation
keys, token checks, single-use claims and an independent watchdog; the browser
proposes fixed lesson cases and downloads signed simulation evidence. The Wasm
pane is an independent dynamics preview. This does not invoke the production
PDP or provide physical robot control. See the
[acceptance guide](../../docs/development/robotics/simulation_first_acceptance.md)
for verification, model paths and open gates.

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

## Planar tree studio

Open `tree-lab.html` (or use the navigation) for one-, two- and three-link
presets with an orbit camera and analytical state inspector. The camera is 3D;
the fixed-base revolute physics remains planar at z=0, with no contacts or
joint stops. Drag with mouse/touch, or focus the canvas and use arrow keys to
orbit and +/− to zoom.

The studio advances fixed 1/480-second steps according to elapsed wall time,
independent of display refresh rate. It caps catch-up at 48 steps per frame;
long stalls slow simulated time without enlarging the timestep or skipping
physics ticks. Hiding the tab pauses until Run is selected again. Model,
gravity and damping edits pause and reset; target and motor changes apply
from the next step. This narrow studio runs on the UI thread; worker-v3
integration and browser performance qualification remain open.

Physics/load errors stop visibly. Reset recovers numerical failures; Retry
loading retries a failed or mismatched Wasm download. Export State saves the
current model and digest, engine build, controller, tick and diagnostics as
local research simulation JSON. It contains no replay history and cannot be
imported as a checkpoint. The 2D lessons retain their existing save/restore flow.

## Implemented Physics

`packages/mini-physics` owns the C++ dynamics used by the browser worker.
`physics.js` remains the independent reference and UI kinematics helper. Both
implement this same restricted model:

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
Tablet, cross-browser and full release budgets remain unqualified. The
[native/Wasm core and checkpoint documentation](../../packages/mini-physics/README.md)
records SIM-2 build ownership, numerical evidence and resume semantics.

## Learning And Execution Boundaries

The original static lessons run isolated local experiments. They do not call SeedCore's
gateway, mint execution authority, control hardware or produce authenticated
robot execution evidence. Feedback uses deterministic lesson rules and measured
simulation values, without an AI service. JSON downloads identify their source
as local research simulation and include model, settings and recorded samples.

Replay reads samples without advancing physics. **Save experiment** exports
recorded observations. To resume calculating later, pause and choose **Save
progress**, then use **Resume saved progress** to load that JSON. Saved progress
requires the same engine build and includes all observations through its tick;
malformed or incompatible files are rejected. No file is uploaded.

Editing settings resets the
experiment and invalidates its previous observations. Hiding the browser tab
pauses the experiment. A future physical-robot connection must use the existing
Agent/PDP/token/edge/evidence boundary and separate integration acceptance.

The broader [learning studio solution](../../docs/development/robotics/robot_learning_studio_solution.md)
describes the mission, agent and governance design. The user's subsequent
direction is browser delivery without installation and a new physics engine
as a core research objective. Blender remains a potential asset-authoring tool;
Godot and MuJoCo remain useful references and comparison environments.

## Verify

Developer checks require Node.js, Clang and the existing locked TypeScript
toolchain in `ts/node_modules`; rebuilding Wasm also requires LLVM wasm-ld.
Learners need none of these:

```bash
# From the repository root:
node tools/mini-sim/verify.cjs
# After changing TypeScript contracts:
npm --prefix packages/mini-sim-contracts run build
```

The verifier checks generated contracts and asset syntax, then runs 78 Node.js
tests, 12 invariants against the planar Wasm adapter, 12 native planar invariant
groups and six native tree groups. The dual-ABI Wasm module is 13,242 raw bytes.
It compares all 2,880 physics ticks of each lesson across JS/native/Wasm with an
explicit 1e-8 tolerance, checks module/build identity and fixed memory, and tests
exact checkpoint continuation, invalid restores and learner save/import behavior.
See [numerical measurements](../../tools/mini-sim/physics-qualification.json).
The [SIM-2 qualification report](../../tools/mini-sim/qualification-2026-10-08.md)
records browser timings, the earlier loaded timing miss and end-to-end save/resume.

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
2. SIM-2 narrow C++/Wasm and complete checkpoint slice is implemented and numerically checked.
3. The planar 1/2/3-link tree and 3D orbit view are implemented; qualify broader trees, encoders, worker-v3 and independent MuJoCo comparisons.
4. Validate floating bodies, contacts, friction, joint limits and further sensors.
5. Add independent-instance batches and measure headless throughput.
6. Qualify robot imports and a separate governed SeedCore simulation bridge.

Learner usability and browser size/performance are checked throughout. Broader
SIM-3 and SIM-4–SIM-6 capabilities remain planned. Device/performance
qualification remains open alongside the delivered local slices.

The [18-month execution plan](../../docs/development/strategy/seedcore_physical_ai_execution_plan_2026_2028.md)
sets commercial target windows. The proposed
[Fast Spine bridge](../../docs/development/robotics/fast_spine_protocol_spec.md)
requires separate authority, evidence and physical acceptance; this app currently
contains neither WebSerial robot control nor authenticated hardware receipts.

Each expansion needs independent numerical and behavioral acceptance evidence.
Reduced coordinates alone do not guarantee contact stability, and a successful
animation does not establish physical accuracy.
