# Mini simulation contracts

SIM-1 contracts for the existing JavaScript planar arm. This package is local
learning infrastructure and has no authority, HAL or hardware dependencies.

`src/index.ts` is the source of truth. The locked TypeScript compiler in `ts/`
emits `apps/mini-robot-simulator/sim-contracts.js` and `sim-contracts.d.ts`.
The namespace works in classic workers and browser scripts; Node tests use its
CommonJS export. Commit both generated files so learners need no build tools.

```bash
npm --prefix packages/mini-sim-contracts run build
node tools/mini-sim/verify.cjs
```

The verifier typechecks in a temporary directory, rejects stale generated files,
checks JavaScript syntax and runs numerical, protocol and UI tests. No new npm
dependencies are needed when the repository's `ts/` workspace is installed.

## Supported compiler profile

`compile(settings)` accepts only the five declared teaching settings in
`schemas/lesson-settings.schema.json`. It emits an immutable versioned planar
descriptor, uniform-rod inertias, fixed joint/body source-to-index maps,
`nq=nv=2`, feature declarations and SHA-256 content identities. This is a narrow
compiler for one known topology; general tree compilation remains SIM-3.

The existing right-handed Y-up planar frame stays explicit. Its future Z-up
embedding is `[x,y,z] -> [x,-z,y]`; no saved planar observations are reinterpreted.
SI units and the analytic uniform-rod center inertia `mass*length²/12` are
declared, rather than inferred from a visual asset. GLB support remains later work.

The model digest covers the descriptor, engine version, frame, physics
parameters and capabilities. The recipe digest additionally covers the model
digest, fixed step, duration, observation period, initial state and versioned
controller settings. The compiler constructs canonical objects in a fixed key
order; input key order does not matter. The synchronous ASCII SHA-256 routine is
bounded to 8 KiB and checked against Node's crypto implementation. These hashes
identify content; they do not authenticate browser records.

## Worker v2

`schemas/command.schema.json`, TypeScript types and
`tests/mini-sim/planar-golden.json` describe the public commands. Every command
binds `protocol`, `runId`, `revision`, `sequence`, `applicationTick`,
`modelDigest` and `recipeDigest`. Unknown fields and unsupported versions fail.
A reset validates settings and both digests before replacing the active run.
Run IDs and accepted sequences strictly increase, including across resets.

`reset` requests tick zero. Administrative `start`, `pause`, and `step` apply
at the next worker boundary. Their requested tick may lag in-flight work, and
replies report the actual `appliedTick`; future administrative ticks fail.
`step` advances eight fixed physics ticks. `set-control` instead requires an
exact current/future tick below 2880 and valid bounded control settings. The
worker acknowledges `queued` with `appliedTick=null`, then emits `applied` before
integrating that tick's interval. Same-tick inputs apply in sequence order.
Late inputs and more than 32 pending inputs fail without changing current work.
Setting edits in the learner UI still reset the experiment.

Replies bind the run, revision and digests, carry an increasing `frameSequence`,
and distinguish accepted command sequence from snapshot ordering. The UI retains
in-flight pause samples but rejects duplicate/stale frames, backwards ticks,
unknown command sequences and invalid observation coverage. Completion requires
all 361 observations, from tick 0 through 2880. Errors disable saving/replay.

## Binary ownership and load

Exactly three 96-byte `ArrayBuffer`s hold up to two sampled observations apiece.
Each row consists of six Float64 values: `[tick,time,q1,q2,v1,v2]`. Unused rows are
zeroed. Values remain doubles; rendering never writes back into the engine.
State metadata and small acknowledgements remain structured cloned.

The worker transfers a snapshot with `bufferId`, `frameSequence`, `sampleCount`
and `buffer`. After copying observations, the page returns the buffer with
`{protocol,type:'recycle',bufferId,frameSequence,buffer}` and a transfer list.
This ownership message has no command sequence or run identity: a buffer from a
replaced run must still be returned. Only the current loan generation and exact
capacity are accepted. Buffer returns do not advance physics or acknowledge a
pending command.

Pool exhaustion suspends scheduling until a buffer returns. Pause/reset remain
acknowledgeable without a free buffer, and reset retains the same pool. One
timer advances at most eight fixed steps. Monotonic wall deadlines compensate
computation time; long delays rebase the schedule instead of building an
unbounded catch-up queue. No timestep changes or tick/sample drops occur.
Diagnostics report active wall time (excluding deliberate pauses), simulated
time, real-time ratio, maximum chunk duration, buffer waits and pool occupancy.
Exports include these diagnostics, model/recipe identity and applied inputs.
They support recorded playback, not resumable checkpoints.

## Browser measurement

From the repository root, serve `python3 -m http.server 8766 --bind 127.0.0.1`
and open `/tools/mini-sim/browser-qualification.html` in a foreground tab.
The harness runs all three lessons plus a 250 ms UI stall with withheld buffers.
It checks real transfers, pause latency, complete coverage and exact comparison
against the direct engine. A foreground RAF measures harness frame intervals,
not the full learner renderer. Wall pacing allows one 16.7 ms timer quantum over
a six-second run; induced load is accepted only with a reported buffer wait.
Browser results are device-specific and separate from deterministic tests.
See the dated report in `tools/mini-sim/` for evidence and outstanding release
device, startup, renderer and tablet qualification.
