# SeedCore Mini Robot Lab

Status: Early browser research prototype; initial worker isolation added 2026-10-05.

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

## Worker Boundary: First SIM-1 Slice

`simulation-worker.js` owns integration and its integer tick. The page uses
`physics.js` only for initial state, rendering and observation metrics. Each
worker callback advances eight fixed steps (1/60 simulated second), then yields.
There is at most one scheduled callback; delayed callbacks slow the experiment
without enlarging the timestep or skipping simulation ticks. Each run stops at
2,880 ticks and supplies all 361 observations, including the initial state.

Commands use `seedcore.mini-lab.worker.v1` with `type`, `runId`, `revision` and
`sequence`. `reset` also carries the existing lesson settings. Supported commands
are `reset`, `start`, `pause` and `step`. A reset needs a strictly newer run ID;
other commands must match the active run/revision. Accepted command sequences
increase across resets. Replies identify the command sequence and applied tick,
with state, new samples and status. Invalid commands leave the worker run intact.

The UI waits for command acknowledgements, retains samples already in flight
during pause, and ignores responses from replaced runs/revisions. A setting
change or reset cancels the worker timer and clears the previous observations.
Worker failures or a five-second acknowledgement timeout stop the experiment
visibly; Reset creates a new worker when necessary. There is no UI-thread
physics fallback. Hidden-tab pausing happens when the visibility event and
worker command are processed; browser scheduling is not a hard real-time stop.

This small step keeps JavaScript and structured-cloned messages. TypeScript,
compiled model schemas/digests, future-tick commands, transferable buffer pools,
resumable checkpoints and performance qualification remain later work in the
[implementation plan](../../docs/development/robotics/mini_robot_simulator_implementation_plan.md).

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

Developer checks require Node.js, but using the application does not:

```bash
node --test physics.test.cjs simulation-worker.test.cjs app-worker.test.cjs
node --check physics.js
node --check app.js
node --check simulation-worker.js
```

The 12 physics tests cover kinematics, positive-definite inertia, gravity and
Coriolis energy identities, static equilibrium, energy conservation and
dissipation, controller convergence, torque limits, timestep refinement,
repeatability and invalid-input rejection. Eight worker tests exercise the actual
worker entry point in a Node VM with structured cloning and controlled timers:
all three lesson trajectories match the direct engine exactly, and pause/resume,
reset, stale/invalid commands, single stepping and completion preserve run state.
Four UI-boundary tests cover stale replies, in-flight pause samples,
acknowledgement timeout/recovery and hidden-tab pausing during a pending start.
They establish the tested model's scope, not contact dynamics or hardware fidelity.

Browser checks for the worker slice: single stepping, pause/resume, normal target
completion, recorded replay, gravity lesson selection and reset during a run.
Responsive-device coverage,
cross-browser qualification and a public deployment remain follow-up work.

## Next Research Gates

The [implementation architecture](../../docs/development/robotics/mini_robot_simulator_implementation_plan.md)
defines the proposed SIM-1–SIM-6 sequence following inspection of SeedCore and
its related apps on 2026-10-05:

1. Complete SIM-1 contracts and qualification; initial worker isolation and command envelopes are implemented.
2. Port the reference model to an owned C++ core with native and Wasm builds.
3. Develop compiled tree models, articulated dynamics, encoders and a 3D view.
4. Validate floating bodies, contacts, friction, joint limits and further sensors.
5. Add independent-instance batches and measure headless throughput.
6. Qualify robot imports and a separate governed SeedCore simulation bridge.

Learner usability and browser size/performance are checked throughout. Beyond
the initial worker slice, these remain planned capabilities.

Each expansion needs independent numerical and behavioral acceptance evidence.
Reduced coordinates alone do not guarantee contact stability, and a successful
animation does not establish physical accuracy.
