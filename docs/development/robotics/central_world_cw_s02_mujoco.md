# CW-S02: pinned browser MuJoCo 3.15.0 worker adapter, clocks, bounded capture and per-substep control gate

Date: 2026-10-23
Status: Local offline Wasm/native parity, bounded worker clocks/capture and per-substep control gate delivered; physical starter qualification, CW-S03 policy compatibility and CW-S04 timelines remain open
Review: CW-SIM-02, CW-SIM-03, CW-SIM-04

## Scope and engine selection decision

Following the [mjswan source assessment](mjswan_integration_assessment.md) and
the delivered [CW-S01 Studio handoff](central_world_cw_s01_mjcf.md#23-october-studio-handoff-and-offline-reference),
CW-S02 qualifies the browser physics runtime, physics/policy clocks, independent UI snapshots, complete
bounded telemetry capture and per-substep control enforcement for the
`seedcore.cw-s01.model.v1` (`fixed_tabletop_serial_boxes_v1`) model subset.

Upstream `mjswan 0.11.9` pins `@ttktjmt/mujoco@3.11.0`, requires a DOM
`HTMLElement`, and lacks a public per-substep control veto or worker-owned state
contract. Official Google DeepMind [`@mujoco/mujoco@3.15.0`](https://www.npmjs.com/package/@mujoco/mujoco)
(`Apache-2.0`) is now published and matches SeedCore's frozen Python native
baseline version (`mujoco==3.15.0`). Per the rescoping rule in
[`mjswan_integration_assessment.md`](mjswan_integration_assessment.md#bounded-qualification-work-and-stop-conditions),
CW-S02 pins `@mujoco/mujoco@3.15.0` directly behind the SeedCore adapter
contract (`seedcore.cw-s02.mujoco-wasm-st.v1`).

| Artifact | Pinned value |
| --- | --- |
| Package | `@mujoco/mujoco@3.15.0` (`Apache-2.0`, Google DeepMind) |
| Runtime profile | `seedcore.cw-s02.mujoco-wasm-st.v1` (single-threaded Wasm, works with or without `SharedArrayBuffer`) |
| `mujoco.wasm` bytes | `10370402` |
| `mujoco.wasm` SHA-256 | `d59c489dd521c80af6965756c5b90daff549fa281566544e4540c170d937633d` |
| `mujoco.js` bytes | `293619` |
| `mujoco.js` SHA-256 | `a5d5f00c4c16d327cf8275f88ddd47c857a5e9baec8ca4174d676fe299267a0c` |
| Qualified dynamics settings | `dt=0.002 s`, position `kp=1` or ideal torque; at most 120 substeps (Studio runs 60), parity decimation 10 |
| Planar SIM-3 fallback | Explicitly forbidden (`PLANAR_FALLBACK_FORBIDDEN`) |

## Implemented boundary

### 1. Pinned Wasm asset verification and CSP-safe worker bundle (`CW-SIM-02`)

[`mujocoAsset.ts`](../../../ts/packages/wasm-sim-bridge/src/mujocoAsset.ts)
verifies exact byte length, the 8-byte WebAssembly magic/version header, and the
SHA-256 digest before `WebAssembly.compile` or Emscripten instantiation.
Streaming fetches via `readPinnedMujocoWasm` abort immediately if the stream
exceeds the pinned byte count, is truncated, or matches the 13,242-byte planar SIM-3
binary (`PLANAR_SIM3_WASM_BYTES = 13242`); 128 KiB is its linear memory size. Silent fallback to the planar engine
is impossible.

When bundling [`cw-s02-worker.ts`](../../../ts/apps/mini-studio/src/cw-s02-worker.ts)
in [`build.mjs`](../../../ts/apps/mini-studio/build.mjs), the build verifies the
exact SHA-256 of `@mujoco/mujoco/mujoco.js` and replaces Embind's two dynamic
`new Function(...)` invoker generators (`craftInvokerFunction` and
`__emval_get_method_caller`) with static closure invokers. As a result,
`dist/cw-s02-worker.js` contains zero `eval(` or `new Function` calls and
executes under `script-src 'self' 'wasm-unsafe-eval'`, while the main editor
(`/`, `/index.html`, `/app.js`) retains its strict no-eval policy without
`'wasm-unsafe-eval'`.

### 2. Model loader and native/Wasm numerical parity (`CW-SIM-02`)

[`mujocoRuntime.ts`](../../../ts/packages/wasm-sim-bridge/src/mujocoRuntime.ts)
accepts only current `CompiledMjcf` (`seedcore.cw-s01.model.v1`) bundles verified
by `assertCompiledModelCurrent`. A closed, 128 KiB XML grammar permits only
CW-S01 primitive elements/attributes and software bounds before engine compilation.
It rejects assets/includes/plugins, replication, arbitrary memory/solver settings,
extra state and unsupported extensions. After compiling
the XML in Wasm, `MujocoModelSession` verifies `nbody`, `njnt`, `nq`, `nv`,
`nu`, `opt.timestep`, body names/IDs, hinge joint names/IDs/rest angles/ranges,
and actuator transmission/mode/gains against the manifest. Ranges are checked
against pinned XML declarations (CW-S01 v1 does not include range metadata).
The loader retains frozen copies of model/binding/range data and frees Wasm C++
heap objects (`MjData.delete()`, `MjModel.delete()`) on `dispose()`.

[`test_cw_s02_parity.py`](../../../tests/test_cw_s02_parity.py) compares all
**14 synthetic CW-S01 models** (`serial-{1,2,3}-{aligned,rotated}-{position,torque}`
plus `studio-reference-{position,torque}`) between `@mujoco/mujoco@3.15.0` Wasm
and native Python `mujoco==3.15.0`:

- Model mass, subtree mass, body inertia, `qpos0`, joint ranges, and actuator
  control/force ranges and gains match within `1e-12`.
- Five multi-state `mj_forward` FK snapshots per model (70 states total) match
  native `xpos`, `xquat`, `xmat`, `xipos`, `ximat`, and `subtree_com` within
  `1e-12`.
- Full uninterrupted 120-substep native/Wasm rollouts match `qpos`, `qvel`,
  `qfrc_actuator`, and `xpos` at **absolute tolerance `1e-12`, relative tolerance
  zero**, for all 14 models. Native state is never reset or replaced with Wasm
  state between steps. Position cases explicitly recompile their source fixtures
  with `kp=1`, `dt=0.002`; torque cases retain `dt=0.002`.
- The CSP-patched Chrome worker independently runs the same 14 models for 120
  steps each and matches those parity references. This tests the shipped static
  invokers, not just the upstream Node module. The single-thread profile also
  runs in a top-level browser page without COOP/COEP or `SharedArrayBuffer`.

The review reproduced up to 1.29 rad/s uninterrupted position divergence at the
compiler default `kp=10`. The previous native test masked that divergence by
resetting native state at every step and limiting uninterrupted position checks
to 10 steps. CW-S01 defaults/exports remain unchanged. CW-S02 dynamics rejects
unqualified settings; the Studio offers an explicit **Apply qualified rehearsal
settings** action that changes the compiled model digest. This is a separate
runtime profile assumption, not a relaxed tolerance or physical servo rating.

### 3. State-owning clocks, bounded capture and per-substep control gate (`CW-SIM-03`, `CW-SIM-04`)

[`mujocoWorker.ts`](../../../ts/packages/wasm-sim-bridge/src/mujocoWorker.ts)
implements `MujocoBoundedExecutor`, which owns `MjModel` and `MjData` and guards
all six declared mutation paths (`ctrl`, `qfrc_applied`, `xfrc_applied`,
`qpos_qvel_act_state`, `opt_timestep`, `policy_model_switch`):

- **Physics/policy clocks & stall fencing (`CW-SIM-03`):** Physics advances by
  integer ticks at the frozen model `timestepSeconds`, evaluates control
  proposals at integer `policyDecimation`, and limits catch-up to
  `maxSubstepsPerBatch` (8). Monotonic clock rollback (`CLOCK_ROLLBACK_FENCED`),
  stalls exceeding `maxStallMs` (`CLOCK_STALL_FENCED`), or hidden-tab events
  (`TAB_HIDDEN_FENCED`) fence the attempt without enlarging `dt` or dropping
  captured samples. Both direct steps and batches enforce stall/deadline checks;
  the worker refreshes its monotonic clock at each step and after control callbacks.
  UI snapshots remain separate from physics; no render-rate target is claimed.
- **Complete bounded capture (`CW-SIM-03`):** Every executed substep records
  `tick`, `policyStep`, `simTimeSeconds`, `monotonicMs`, `qpos`, `qvel`, `ctrl`,
  `qfrcActuator`, `xpos`, and `clearedExternalMutations`. Buffer exhaustion
  fences the attempt with `CAPTURE_OVERFLOW` **before** `mj_step` runs so an
  uncaptured substep never executes. Callers receive copies of retained samples.
  `traceDigest` binds model identity, dt, policy decimation and sample fields
  except measured wall timestamps; those timestamps remain in captured samples.
  Thus scheduling jitter does not change the deterministic simulation digest.
- **Per-substep control veto & mutation clearing (`CW-SIM-04`):** Before every
  single `mj_step`, the executor verifies shadow state integrity
  (`EXTERNAL_STATE_TAMPERED` if `qpos`, `qvel`, or `act` was mutated outside the
  step, including time and solver warmstart state), zeroes and counts any unauthorized `qfrc_applied` or `xfrc_applied`
  disturbances, checks attempt deadline and revocation (`REVOKED` /
  `ATTEMPT_DEADLINE_EXPIRED`), and validates the active control proposal's
  `generation`, `authorityEpoch`, `modelDigest`, monotonic expiration window,
  dimension, finiteness, and actuator `ctrlrange`. Out-of-range controls are
  vetoed (`CONTROL_OUT_OF_RANGE`) rather than silently clamped, including tiny
  overruns. Expiry is inclusive (`now >= deadline`). All gates run again after a
  control callback; callback errors stop the executor. Non-finite engine state
  or unexpected reset/time fails explicitly instead of reporting completion.

MuJoCo documents time and warmstarts as integration inputs in its
[state/reproducibility reference](https://mujoco.readthedocs.io/en/stable/programming/simulation.html#state-and-control).
These are offline simulation fences, not production PDP admission.

### 4. Mini Studio CW-S02 worker rehearsal

The Mini Studio **Simulation** tab now includes a bounded **CW-S02 · Pinned
Browser MuJoCo 3.15.0 Rehearsal** panel backed by `/cw-s02-worker.js` and
`/mujoco.wasm`. It remains disabled while the physical starter is loaded (10 DRC
blockers / 9 simulation blockers). When a simulation-ready model is compiled,
the operator can run or stop a 60-substep rehearsal (`dt = 0.002` s, decimation
`10`, `6` policy updates), inspect the runtime profile, Wasm SHA-256, final
`qpos`/`qvel`, and deterministic `traceDigest`, and view the full worker
inspection/summary JSON. Draft edits, undo/redo, parameter changes, operator
stop, or tab hiding immediately terminate and fence any active worker. Startup
has a timeout and per-run cancellation token; stale startup errors and duplicate
generations cannot dispose a newer run. Hidden/revoked startup is fenced before
model initialization. Browser regression tests exercise these races and all
Studio interruption triggers.

## Verification and evidence

```bash
# Rebuild workspaces, run CW-S02 TS unit/negative matrix, export Wasm rollouts, and verify native MuJoCo 3.15.0 parity
node tools/robotics/verify-cw-s02.cjs

# Verify CW-S01 compiler/native baseline
node tools/robotics/verify-mjcf.cjs

# Full authoring, API, headless Chrome (including CW-S02 worker rehearsal) and downloaded-bundle native checks
node tools/robotics/verify-authoring.cjs --browser
```

- `node tools/robotics/verify-cw-s02.cjs`: **18 TS tests + 15 native Python
  parity tests** across all 14 synthetic models.
- `node tools/robotics/verify-mjcf.cjs`: **18 TS tests + 15 native Python tests**.
- `node tools/robotics/verify-authoring.cjs --browser`: **152 workspace TS tests,
  22 FastAPI tests, 36 headless Chrome checks**, and **2 downloaded-bundle native
  tests** with zero console/page errors and strict CSP.

Retained local artifacts: `artifacts/robotics/cw-s02/verification.json`,
`artifacts/robotics/cw-s02/models/cases.json`, and
`artifacts/robotics/cw-s02/browser-rehearsal.json`, `browser-verification.json`
and `browser-parity.json`. The latter retains actual worker samples for all
14 models, comparison error, aggregate elapsed time and browser-reported
user-agent/platform/concurrency. This is local Chrome evidence, not a hardware
stop-time or broad device-performance qualification. `verify-cw-s02.cjs` marks
`browser_included: false`; actual patched-worker checks require
`verify-authoring.cjs --browser`.

## Remaining work

CW-S02 closes local offline software qualification for `CW-SIM-02`, `CW-SIM-03`,
and `CW-SIM-04` on the `fixed_tabletop_serial_boxes_v1` fixtures at the explicit
rehearsal settings. Broader models/settings, target-device timing, portal/iframe
deployment and rendering/capture export qualification remain separate. The
localhost editor intentionally forbids framing; local COOP/COEP checks do not
qualify another deployment. Physical starter
qualification remains blocked on `CW-D01`. The [26 October CW-S03 preflight](central_world_cw_s03_preflight.md)
now records exact policy/model/adapter blockers without qualifying policy
execution. **CW-S04** (declarative tabletop joint/LED gesture timeline, bounded
interpolation and replay projection) is next; full CW-S03 policy inference
remains conditional on its independent references and browser evidence.
