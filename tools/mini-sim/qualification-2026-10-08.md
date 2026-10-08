# SIM-2 local qualification — 2026-10-08

Inspected starting commits: `8fd7598` (private research-report sync) and `ea4ee16`
(SIM-1 contracts/qualification). The latter is the simulator foundation; the
former does not change the app. This change implements the documented next
narrow C++/Wasm/checkpoint stage without changing SeedCore execution boundaries.

## Numerical and build checks

- Clang and LLD 23.1.2; Node 22.16.0; macOS Darwin 25.5.0, arm64.
- Same C++ source compiled natively and as freestanding Wasm, f64 arithmetic,
  fast math and FP contraction disabled. `sin`/`cos` are host imports.
- Artifact: 3,738 bytes, 128 KiB fixed linear memory. Build and module SHA-256
  are recorded in `apps/mini-robot-simulator/physics-build.json`; the loader
  verifies the actual received bytes. Invalid/missing Wasm has no JS fallback.
- Twelve native invariant groups, twelve Wasm-adapter invariant tests and
  45 contract/worker/UI/reference tests pass. CMake/CTest also passes using
  AppleClang 21.0.0.21000101 on this host.
- All 2,880 ticks of each of three lessons compared independently with JS:
  maximum native error 3.997e-14; maximum Wasm error 2.842e-14. Declared bound:
  1e-8 over angle (rad), angular velocity (rad/s) and time (s).
- Full measurements: [physics-qualification.json](physics-qualification.json).
- Restoring tick 80 with two ordered tick-81 control changes produces exactly
  the uninterrupted same-build observation sequence through tick 2,880.
  Bad build/recipe/state/control/tick/queue restores are atomic rejections;
  a restored tick-zero run still emits its initial observation.

The specialized C ABI retains no state or pointers; callers own model/state
buffers. The worker checkpoint stores all additional future-influencing state:
active control, ordered pending inputs, integer tick and initial-sample status.
There are no sensors, RNG, contacts or controller integrators in this profile.
General opaque model/state handles are deferred to the tree-engine stage.

## Browser measurements and learner flow

Chrome 155.0.0.0 on this Mac; browser reports 8 hardware threads and 8 GiB
`deviceMemory`. These are browser-reported values, not measured renderer RSS.

The final foreground harness passed all three lessons and the 250 ms stall.
Every case retained 361 observations, finished at tick 2,880 and met 1e-8 trace
agreement. Full report: [browser-qualification-2026-10-08.json](browser-qualification-2026-10-08.json).

| Case | p95 RAF interval | Pause acknowledgement | Active wall time | Samples |
| --- | ---: | ---: | ---: | ---: |
| Reach | 9.10 ms | 0.40 ms | 6003.60 ms | 361 |
| Gravity | 9.00 ms | 0.40 ms | 6003.10 ms | 361 |
| Heavy | 9.00 ms | 0.30 ms | 6002.40 ms | 361 |
| Reach + induced stall | 9.20 ms | 1.10 ms | 6253.20 ms | 361 |

The harness's normal wall-time budget remains six seconds plus one observation
period (16.67 ms). The induced stall instead requires an explicit buffer-wait
diagnostic and complete observations. No threshold was widened for this change.

An earlier run overlapping native compilation passed numerical, coverage, RAF
and pause gates but **failed** the gravity wall-time gate: 6220.70 ms active,
125.20 ms maximum chunk, two buffer waits and all 361 observations retained.
The repeat followed completion of compilation; it does not erase that loaded
result or establish a hard real-time guarantee under arbitrary desktop load.

Learner UI checked in Chrome:

1. Predict success and run the reaching lesson to measured completion.
2. Reset, single-step to tick 8, then save progress from the worker checkpoint.
3. Reset, choose the saved local JSON through the native file picker, and observe
   paused tick 8 with matching gap, speed and submitted prediction.
4. Continue to six seconds; full coverage checks pass and the lesson settles.
5. Inspect the desktop layout, including save/resume controls, and preserve the
   [completed learner screenshot](learner-ui-2026-10-08.jpg).

The browser-extension file-selection helper lacked file-URL permission on this
host; the ordinary native chooser completed the check without changing browser
permissions. The application itself reads the selected file locally.

## Limits and repeatability

This is local engineering evidence for one smooth two-link model. No contact,
joint limits, free base, imported robot, hardware fidelity, hardware commands,
governed execution or release-device qualification is claimed. Tablet,
cross-browser, cache/offline reopening, memory RSS and moderated learner testing
remain open. Checkpoints require the same actual Wasm build; host transcendental
math still prevents a universal bitwise cross-platform promise.

Repeat from the repository root:

```sh
node tools/mini-sim/build-physics.cjs
node tools/mini-sim/verify.cjs
node tools/mini-sim/verify-physics.cjs --report
```

Serve the repository over HTTP, then open
`/tools/mini-sim/browser-qualification.html`. The checked-in 2026-10-07 SIM-1
report remains historical evidence for the JS worker, not the current backend.
