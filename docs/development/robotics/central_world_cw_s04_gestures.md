# CW-S04: bounded tabletop gestures and captured replay

Date: 2026-10-28
Status: Local synthetic simulation slice implemented; actual starter, longer timelines, live admission, signed physical evidence and hardware qualification remain open
Review: CW-MOM-01
Owner role: Studio/simulation with verification review

## Scope and runtime boundary

The [26 October allocation](../current_next_steps.md) selected a declarative
tabletop gesture and replay after the [CW-S02 fixed-preset runtime](central_world_cw_s02_mujoco.md)
and [CW-S03 offline preflight](central_world_cw_s03_preflight.md). This slice uses
the existing synthetic fixed-base serial position profile: MuJoCo 3.15.0,
`dt=0.002`, `kp=1`, one to three joints, at most five assembly bodies (plus
MuJoCo's world body), and **at most 120 steps / 240 ms**.
It does not extend the qualified runtime duration or enable a trained policy.
The actual starter retains its full DRC blockers and nine simulation blockers.

Every draft and replay explicitly declares `scope: offline_simulation_only`,
`physicalAcceptance: false`, and `executionAuthority: none`. The virtual LED
is a captured-timeline display annotation, not an electrical output, a catalog
device or firmware control. No Agent/PDP/token fields, production gates,
signer roots, catalog sources or physical profiles change.

## Declarative timeline and analytic checks

[`gesture.ts`](../../../ts/packages/wasm-sim-bridge/src/gesture.ts) defines
`seedcore.cw-s04.gesture.v1` and the pure `seedcore.cw-s04.hermite.v1` compiler.
The raw JSON parser rejects duplicate decoded keys, nonfinite/unsafe values,
unsupported fields and inputs above 64 KiB. Direct JS inputs use the same
bounded JSON validation. There is no executable code, arbitrary effect,
camera/network output, inference provider or privileged script path.

A draft binds the exact revision, assembly, catalog, full DRC and model digests,
plus the current local authority epoch. This epoch is a freshness fence, not
an authority grant. There must be exactly one explicitly named track for each
model joint. Joint order is canonicalized to the model order; position units
are radians and derivative units are rad/s and rad/s².

Each track has 2–32 strictly increasing integer-tick knots, a declared positive
velocity/acceleration ceiling and explicit position/velocity at each knot.
Every track spans the timeline, starts at the model home, and has zero first/last
velocity. The compiler solves derivative roots analytically to check interior
position extrema, interior velocity extrema and acceleration endpoints of every
cubic segment. Position must fit both joint and position-actuator ranges;
the declared velocity ceiling cannot exceed the model metadata. Acceleration
is an explicit simulation target ceiling, not a qualified hardware limit.

Finite loops (1–4) require a position/velocity-continuous seam. `timeScale`
0.25–4 rescales velocity and acceleration and is rechecked; scaled knots and
the whole attempt must remain integer ticks within the 120-step budget.
Virtual LED cues are ordered integer ticks with closed hex colors. Other
effects and implicit frame/units conversions are rejected. Changing names,
curves, loops, timing or bindings changes the compiled digest. Retained
compiled data is cloned and recursively frozen. Evaluation returns exact authored
positions at knot ticks and loop seams, avoiding polynomial roundoff at those ticks.

These are **target-command bounds**. They do not establish observed tracking,
observed velocity/acceleration limits, jerk limits, torque/contact behavior,
electrical/thermal behavior, collision freedom or physical stopping.

## Worker execution and interruption

The shipped [CW-S02 worker](../../../ts/apps/mini-studio/src/cw-s02-worker.ts)
independently recompiles a supplied gesture and checks its expected digest and
clock before loading the engine. Invalid gestures never fall back to the
deterministic rehearsal controller. The existing controller remains available
for explicitly selected CW-S02 rehearsals.

CW-S04 evaluates the compiled target at each next simulation tick, using
`policyDecimation=1` and the existing state-owning bounded executor. Every
substep retains the existing control range, generation/epoch/model,
deadline/freshness, force/state, clock/stall and capture-overflow fences.
No clamping, timestep enlargement, dropped required capture or automatic resume
is introduced. Engine/Wasm pins and CSP-safe static invokers remain unchanged.

Operator stop waits for a worker acknowledgement and retains actual partial
samples before disposal. Revocation, hidden-tab faults and capture overflow
retain partial evidence where available. A missing acknowledgement or failed
startup is labeled capture unavailable. Draft, undo/redo, model/settings and
gesture edits terminate old workers and clear stale compilation/replay; late
results cannot restore an obsolete attempt.

## Replay integrity and UI

[`gestureReplay.ts`](../../../ts/packages/wasm-sim-bridge/src/gestureReplay.ts)
defines `seedcore.cw-s04.replay.v1`. It retains the compiled gesture, worker
summary and original samples, with a canonical bundle digest. Inspection
requires independently retained current build/gesture/generation bindings and
`captureDigest`, calculated from the original worker terminal summary and samples
with `gestureCaptureDigest`. This digest is retained before any import; imported
JSON cannot replace it by rewriting observations and recalculating embedded hashes.
It checks closed summary/attempt/sample shapes, scope/profile, recompilation,
digests, finite vector dimensions,
contiguous ordered physics ticks, deadlines, exact authored controls,
terminal counters/reasons, cleared-force accounting, mutation guard inventory,
zero interrupted controls, capture/final-state agreement and the existing wall-time-independent physics
trace digest. Missing, reordered, conflicting or altered evidence is rejected.

The read-only projection distinguishes `completed_simulation_capture` from
`interrupted_simulation_capture`. A partial attempt cannot be relabeled complete.
The Studio scrubber displays captured target and observed joint values and a
virtual LED cue; it does not step physics or dispatch controls. Export rechecks
current bindings. Raw replay import is capped at 256 KiB and requires this
session's independently retained original capture identity; an unsuccessful startup
without a capture cannot enable import. Reload does not silently
trust an imported bundle's self-declared expectations.

These captures are **unsigned local simulation artifacts**. Hash consistency
does not authenticate a publisher/signer or prove sensor/physical truth. This
projection does not close CW-G02's signed evidence/revoked-key/quarantine work.

To exercise the UI in Mini Studio:

1. In **Simulation**, load **Offline Simulation Reference (Synthetic)**.
2. Select **Position** and apply the qualified rehearsal settings.
3. Open **Moments** and create the tilt/return example; inspect or edit its timeline JSON.
4. Validate the full curves, then rehearse the gesture. Stop is available during startup and execution.
5. Inspect the scoped outcome, scrub captured samples and download replay JSON.

## Reproduction and local evidence

```bash
# Source rebuild, typechecks, focused Wasm/refusal tests and required native parity.
node tools/robotics/verify-cw-s04.cjs

# Also run the full Studio/browser regressions on shipped CSP-patched workers.
node tools/robotics/verify-cw-s04.cjs --browser
```

The focused suite contains **46 TS checks**, including independent analytic
extrema goldens, safe endpoints with an unsafe curve interior, loops/time scaling,
stale bindings, exact target capture, deterministic Wasm rollouts, partial
stop/revoke/overflow, zero-step acknowledged stop, exact knots, the five-body
scope limit, and replay tampering/coverage (including fully rehashed rewrites and
conflicting terminal metadata). **Seven native Python cases**
independently calculate Hermite targets and compare all 120 uninterrupted steps
of aligned/rotated 1/2/3-joint fixtures and the Studio reference at `atol=1e-12`,
`rtol=0` for native/Wasm state. The shipped Chrome exercise adds **nine CW-S04
groups** covering the UI, worker refusal, Node/browser physics-trace identity,
export/import, rehashed observation tampering, read-only scrub, operator stop and
stale startup races. The full authoring run passed **241 workspace TS tests,
22 FastAPI tests, 45 Chrome groups and 2 native downloaded-bundle tests**.
The shared runtime regressions also passed: CW-S02 **18 TS + 15 native**;
CW-S03 **43 TS + 7 Python**, including all **16 CPU artifact replay cases**,
with both real policy candidates still blocked.

The verifier writes source hashes, scope, included/skipped lanes, fixture/model/
gesture/trace identities and actual-starter rejection to
`artifacts/robotics/cw-s04/verification.json`. Native captures are retained in
`models/cases.json`; browser runs additionally retain `browser-replay.json`,
`browser-verification.json` and an inspector screenshot. A non-browser run
explicitly reports `checks_passed_browser_not_run`; it cannot claim Chrome
acceptance. CI adds the required native lane and retains its reports.

## Handoff and remaining gates

This closes the local synthetic CW-S04 allocation within the existing 240 ms
profile. Longer gestures, physical LED output, general bodies, torque gestures,
policies and device/deployment qualification need separate reviewed acceptance.
The next integration package is **CW-G01**, exact build/behavior/endpoint binding
through the accountable Agent and trusted PDP, followed by CW-G02 evidence
projection and later export/release work. CW-D01, full CW-S03 inference/runtime,
Microduck M1–M4 and hardware G1/G2 remain open. No simulation result admits
physical execution.
