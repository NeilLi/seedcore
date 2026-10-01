# SeedCore Mini Robot Lab

Status: Early browser research prototype, 2026-10-01.

A small learning application with an original two-link physics engine. Learners
predict a result, adjust joint targets, motor strength or arm mass, run an
experiment, and replay the calculated observations. The three prepared
experiments are reaching a star, turning motors off and trying a heavier arm.

## Run

Open `index.html` in a modern browser. All application assets are local; there
are no package installations, accounts, API keys or remote dependencies.

For a local HTTP preview, run from this directory:

```bash
python3 -m http.server 8766 --bind 127.0.0.1
```

Then open `http://127.0.0.1:8766`. A public deployment is not included.

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
first link. Positive y points upward. The UI advances at 480 physics steps per
simulated second and records observations at 60 samples per simulated second.
Rendering follows simulated time; this is not a real-time hardware controller.

The reaching lesson requires the tip to remain within 3 cm of its target and
below 0.05 m/s throughout the final half-second of a six-second experiment.
These are educational simulation criteria, not physical robot safety limits.

The model has no contact solver, collisions, mechanical joint stops, floating
base, actuator electrical dynamics, URDF/MJCF importer or Microduck model.
It is a first research case for a custom engine, not a general robotics engine.

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
node --test physics.test.cjs
node --check physics.js
node --check app.js
```

The 12 physics tests cover kinematics, positive-definite inertia, gravity and
Coriolis energy identities, static equilibrium, energy conservation and
dissipation, controller convergence, torque limits, timestep refinement,
repeatability and invalid-input rejection. They establish the tested model's
scope, not contact dynamics or hardware fidelity.

Browser checks performed during development: initial rendering, normal target
completion and entry into recorded replay. Responsive-device coverage,
cross-browser qualification and a public deployment remain follow-up work.

## Next Research Gates

1. Validate learner usability and browser performance for this small model.
2. Generalize model/state contracts and move scaled simulation into a worker.
3. Develop and verify tree kinematics and articulated dynamics, with reference comparisons.
4. Add contact and friction in isolated analytic test cases before walking models.
5. Evaluate a WebAssembly core, standard model import and Microduck fidelity.

Each expansion needs independent numerical and behavioral acceptance evidence.
Reduced coordinates alone do not guarantee contact stability, and a successful
animation does not establish physical accuracy.
