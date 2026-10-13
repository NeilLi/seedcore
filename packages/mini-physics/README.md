# SeedCore Mini Physics — SIM-2 and planar SIM-3 core

Owned C++17, double-precision, smooth fixed-base two-link arm. The browser's
prepared experiments now run this core in WebAssembly inside the existing
worker. `physics.js` remains an independent numerical reference and the UI's
kinematics/readout helper. No hardware connection or execution authority exists.

## Build and verify

From the repository root, with Clang and LLVM's `wasm-ld` installed:

```sh
node tools/mini-sim/build-physics.cjs
node tools/mini-sim/verify.cjs
node tools/mini-sim/verify-physics.cjs --report
```

`MINI_CXX` and `MINI_WASM_LD` select executable paths. The build script uses
`wasm-ld` on PATH outside Homebrew; this host uses Clang/LLD 23.1.2. There is no
Emscripten, WASI, C++ runtime, allocator, shared memory or network dependency in
the learner application. Only host `sin` and `cos` are imported. LLVM documents
the explicit export and import behavior at https://lld.llvm.org/WebAssembly.html.
Cross-platform bitwise reproducibility is not promised for these math imports.
The checked-in build manifest records the actual module's SHA-256 and toolchain;
the worker verifies the downloaded bytes against that digest before use.

Native library and tests can also be built with CMake:

```sh
cmake -S packages/mini-physics -B /tmp/seedcore-mini-physics
cmake --build /tmp/seedcore-mini-physics
ctest --test-dir /tmp/seedcore-mini-physics --output-on-failure
```

Clang/GCC-style floating-point flags are used. Windows/MSVC is unqualified.
Fast math and multiply-add contraction are disabled. The Wasm module has fixed
131,072-byte linear memory; its current size and digest are recorded in
`apps/mini-robot-simulator/physics-build.json`. Build artifacts are served locally.
Missing, corrupt or incompatible Wasm stops initialization, with no JS physics
fallback. Reset can create a replacement worker after a failure.

## Narrow ABI and ownership

`include/mini_physics.h` declares ABI 1. `mini_eval(operation, buffer, 32)` takes
caller-owned doubles, retaining no pointers or hidden mutable state. Operations
0–6 are terms, acceleration, constant-effort RK4 step, forward kinematics,
mechanical energy, bounded PD motor effort and controlled RK4 step. Prepared
lessons use operation 6; motor effort is recomputed at each RK4 stage in C++.

Inputs 0–5 hold model parameters, 6–10 hold q, velocity and time; 11–17 hold
effort, timestep, target, limit and motor switch. Output begins at 20. All
required input values and lengths are checked before output is written. Status
1 means invalid input, 2 singular inertia and 3 divergence. Native callers must
supply an actually allocated 32-double buffer; this is a C pointer boundary.
Each Wasm instance has its own scratch and memory, never transferred to the UI.
The wrapper copies only snapshots into the existing three-buffer transport pool.

This allocation-free specialized ABI deliberately precedes general model/state
handles, model imports and tree dynamics. `step` supports arbitrary JS callback
controls for reference compatibility by orchestrating RK4 around C++
accelerations. That callback path is not used by the prepared browser lessons.

## Planar serial-chain ABI

`include/mini_tree_physics.h` declares the additional ABI 2 entrypoints using
a separate 64-double buffer. It supports fixed-base planar chains with one to
three revolute joints, per-link COM/inertia and per-joint damping. It does not
implement branching or spatial dynamics. The existing browser worker still
uses ABI 1; `tree-physics-wasm.js` exposes ABI 2 for independent callers.

All results are validated before any output is published. Invalid link counts,
non-finite inputs and divergence leave the caller's buffer unchanged. The mass
solve uses LDL^T with pivots normalized by the largest mass-matrix diagonal;
pivots at or below 1e-14 reject ill-conditioned models without rejecting a
well-conditioned model solely for its mass scale.

Tree contracts retain numeric precision and hash UTF-8 canonical JSON. Nested
joint limits are immutable metadata; mechanical stops and encoder sampling are
not implemented. State vectors must match the link count; empty velocity or
torque vectors explicitly mean zero. Controlled steps require a complete target.
Rebuilding changes the module digest, so existing saved progress requires its
original matching build. Tree models previously rounded by the compiler must
be recompiled before comparing model identities.

## Complete resumable state

The C++ core is stateless across calls, so all integration state is explicit.
A worker checkpoint additionally captures the integer tick, current control,
ordered pending exact-tick inputs and whether tick-zero observation was emitted.
It binds the equation version, exact Wasm build, model and run recipe. Those
recipe identities include timestep, controller, duration and initial state.
There are no actuator integrators, RNG, sensors, contacts or warm starts in this
profile. New features must extend the checkpoint before claiming resumability.

Save is allowed only at a paused, ready or completed worker boundary. Restore
requires a fresh destination and validates everything before replacement. The
restore command sequence must exceed every saved pending input sequence;
transport frame counters, timers and transferable loans belong to the new run.
Pending input order and original sequence identities are retained; applied
reply envelopes acknowledge the current transport sequence, with the original
input sequence inside `input`. Restores resume paused, or ready at tick zero.

The learner's **Save progress** JSON also preserves observations, prediction,
lesson and applied inputs. **Resume saved progress** checks coverage and the
terminal snapshot, resets to a new run and restores after acknowledgement.
The file is read locally, with a 256 KiB bound. It is not uploaded. The existing
**Save experiment** remains a recorded playback export, not a checkpoint.
Content digests are compatibility identities, not authenticated robot evidence.

## Numerical evidence

`tools/mini-sim/physics-qualification.json` records this host's full 2,880-tick
traces for reaching, gravity and heavier-arm lessons. Native and Wasm each agree
with JS within 1e-8 rad/rad·s⁻¹ (time within the same scalar comparison budget);
the largest observed discrepancy is 3.997e-14. Twelve native invariant groups
and the original twelve invariants against the Wasm adapter pass. Worker tests
also prove exact same-build restore continuation with same-tick queued inputs,
invalid restore atomicity and tick-zero observation preservation.

This establishes software agreement for the stated model, not fidelity to a
physical robot. The model still has no collisions, contact, joint stops,
floating base, servo lag or imported robots. Browser performance and hardware
acceptance remain separate qualification gates.
