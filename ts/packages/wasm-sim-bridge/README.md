# Restricted assembly-to-MJCF compiler

This package also exports experimental, visual-only `frameTransport`,
`FixedTickClock` and `PlanarLab` utilities used by Mini Studio's separate
[browser performance lab](../../../docs/development/robotics/browser_performance_pipeline.md).
They provide bounded transferable/shared snapshots and a pinned synthetic SIM-3
fixture. They do not run compiled MJCF or implement the CW-S02 MuJoCo adapter.
The CW-S01 compiler API and readiness policy below remain unchanged.

The CW-S01 / CW-SIM-01 compiler slice (21 October) compiles the supported
assembly v2 subset to deterministic, asset-free MJCF and a digest-bound
manifest. Its [23 October Studio handoff](../../../docs/development/robotics/central_world_cw_s01_mjcf.md)
and the separate [CW-S02 fixed-preset MuJoCo adapter](../../../docs/development/robotics/central_world_cw_s02_mujoco.md)
are delivered locally. This package also supplies the CW-S03 offline preflight
described below; full policy execution remains blocked. The
[active queue](../../../docs/development/current_next_steps.md)
now records the local CW-S04 slice below and selects CW-G01 admission integration
next. These slices create no hardware route or
execution authority; real starter and broader runtime qualification remain open.

## Supported subset

- Fixed chassis root, a serial chain of at most 32 bodies and one to three
  explicitly actuated revolute joints; declared rigid mounts are retained.
- `opposed_z_rx_pi` rest poses and `parent_part` joint/output axes and pivots;
  catalog port mating and actuator simulation limits are checked independently
  of the structural assembly validator. No axes are inferred from meshes.
- Primitive box geometry, supplied COM and full six-component inertia tensors.
  Software subset caps are 1 m per component dimension and 5 kg total modeled
  mass; these are resource/scope limits, not physical safety ratings.
- Explicit position or **ideal torque** actuator mode. Position gain defaults
  to 10 and timestep to 0.002 s as versioned model assumptions. Control/force
  ranges are emitted; velocity limits are retained as metadata and are not
  enforced by MJCF. No contact, electrical, thermal or real-servo fidelity claim.

The root is fixed to the world. A joint's axis/pivot is transformed from the
parent-part frame to the child-body frame required by MJCF. `ref` preserves
the declared nonzero rest angle: reference geometry occurs at that angle,
not necessarily at zero. Each body has an explicit inertial; static fusion
and automatic inertia repair are disabled. Collision response is disabled
for proxy boxes.

## Separate offline simulation-readiness policy

`seedcore.cw-s01.simulation-readiness.v1` is a separate result, approved for this
slice after identifying a contract conflict: v2 outputs require proxy actuator
geometry, while CW-A04 flags proxy geometry as physically unqualified.

The compiler verifies raw catalog/part hashes, strict component/assembly
schemas and relevant intrinsic/mating/electrical semantics, then **recomputes
the entire DRC report** with the supplied options. Any missing, stale or changed
report is rejected. Only the blocked `MECHANICAL_PROXY_UNQUALIFIED` finding is
deferred for offline simulation. Every other finding and every conflict stays
blocking, including unknown electrical ratings and unpriced parts. The original
DRC report is never converted to `pass`; physical acceptance remains false.

The real `tabletop-starter.sc-assembly.json` therefore still fails compilation.
Positive tests use separately named, re-pinned **synthetic** documents with
explicit mathematical power/cost assumptions; the committed catalog and starter
are unchanged. Non-diagonal inertias on a synthetic non-actuator part exercise
full tensor handling without granting physical qualification.

## API and identity

`CompilerInput` supplies an assembly, raw catalog/index and component documents,
the current complete DRC report, optional DRC evaluation options, and an explicit
actuator mode. `assessSimulationReadiness` returns the separate readiness result;
`compileAssemblyToMjcf` refuses blocked inputs and emits XML plus a manifest.

`modelDigest` hashes the canonical **whole artifact payload** (XML, manifest and
scope, excluding the digest itself). It binds compiler/subset/policy version,
assembly/catalog/electrical/report identities, DRC options and model settings.
It is not just an XML hash or a signature. `assertCompiledModelCurrent` checks
cached bytes against independently retained current assembly/catalog/DRC/model
bindings. Supplying an artifact's own hashes as trusted context provides no
independent freshness or authentication.

Catalog provenance labels are inherited input classifications, not device
attestation. Visual paths are constrained but **never opened** by the compiler;
only the declared box and inertial data enter MJCF. Verify visual asset bytes in
the existing registry/authoring pipeline when using them for rendering. The
compiler exposes no XML include, mesh loading, filesystem access or plugin hook.

## Verification

From the repository root, install the locked TS workspace and existing optional
`seedcore[robotics-sim]` environment, then run:

```bash
node tools/robotics/verify-mjcf.cjs
```

The runner rebuilds source dependencies, checks generated validators, runs the
compiler negative matrix, exports 14 synthetic models (including both Studio reference modes) and requires pinned
MuJoCo 3.15.0 parity. Python checks authoritative catalog/assembly semantics,
native compilation, independent FK at reference/zero/boundary/interior states,
body/subtree mass, COM/full inertias and joint/actuator ranges. No engine fallback
or hardware is used. `--skip-native` explicitly reports native checks not run.

Evidence: `artifacts/robotics/cw-s01/verification.json` and `models/cases.json`.
See the [implementation/acceptance record](../../../docs/development/robotics/central_world_cw_s01_mjcf.md)
and [existing acceptance matrix](../../../docs/development/robotics/central_world_acceptance_matrix.md).

Mini Studio now exposes this compiler and readiness policy through its
**Simulation** inspector. The explicitly selected reference is pinned separately
under `packages/simulation-fixtures/cw-s01/`; the physical catalog is unchanged.
The Studio retains revision/authority-epoch freshness fences outside model
content and checks source/DRC/model identity again before export. See
`node tools/robotics/verify-authoring.cjs --browser` for byte-identical download
and native MuJoCo checks. The separate CW-S02 single-thread adapter now qualifies explicit `dt=0.002`,
position `kp=1` or ideal torque on the 14 fixture sources for up to 120 steps.
`node tools/robotics/verify-cw-s02.cjs` checks strict uninterrupted native parity;
`verify-authoring.cjs --browser` also checks the actual CSP-patched Chrome worker,
single-thread/no-SAB operation, startup races and Studio interruptions. Compiler
default kp=10 is retained for export but refused by this runtime profile. See
[CW-S02 scope and review evidence](../../../docs/development/robotics/central_world_cw_s02_mujoco.md).

## CW-S03 offline policy compatibility preflight

`assessPolicyCompatibility(input)` checks bounded versioned policy/model/adapter
contracts against independently retained pins, exact observation/action and
joint/home semantics, actuator mapping, cadence and separately bound evidence
roles. It does not load ONNX, step physics, authorize motion or qualify a runtime.
`computePolicyAdapterDigest(adapter)` hashes the canonical adapter descriptor.
A synthetic positive is only `contract_consistent`; all reports retain
`physicalAcceptance: false`, authority none and runtime qualification not granted.

Run `node tools/robotics/verify-cw-s03.cjs --require-artifact-replay` from the
repository root for the strict local inventory/replay and refusal report. The
policy cache is never fetched implicitly. The default command records missing
optional artifacts/dependencies explicitly and cannot claim skipped replay as
acceptance. See the [CW-S03 record](../../../docs/development/robotics/central_world_cw_s03_preflight.md)
for the two blocked real candidates and the handoff to CW-S04.

## CW-S04 bounded synthetic gestures and captured replay

`compileGesture(raw, model, expectedBinding)` validates closed declarative
Hermite joint targets, virtual LED cues, loops and time scaling. Analytic
interior position/velocity and acceleration extrema must fit declared target
limits and model ranges. Revision/assembly/catalog/DRC/model/epoch bindings
and immutable compiled digests fence edits and stale asynchronous results.

The synthetic position profile retains dt=0.002, kp=1, one to three joints,
at most five assembly bodies plus the world body, and the existing
120-step / 240 ms maximum. The worker recompiles and checks the expected
gesture digest, then proposes controls through every existing CW-S02 substep
gate. `gestureFrameAtTick` only evaluates target data. `createGestureReplay`
and `inspectGestureReplay` retain/check original samples against independent
expected bindings and project completed versus interrupted simulation capture.
Their expected context requires `captureDigest`, obtained with
`gestureCaptureDigest(summary, samples)` from the original terminal worker capture
and retained independently of imported JSON. Recomputed embedded hashes cannot
replace that pin. Closed nested shapes, terminal counters/reasons and zero
interrupted controls are checked alongside capture coverage and trace integrity.
The Studio **Moments** tab scrubs captured targets/observations and virtual LED
cues without resimulation. Bundle/trace hashes are unsigned integrity checks,
not signer authentication, physical evidence or execution authority.

Run `node tools/robotics/verify-cw-s04.cjs --browser` for source rebuild, full-curve
refusal/binding/replay checks, independent native parity and shipped Chrome
exercise. See the [CW-S04 record](../../../docs/development/robotics/central_world_cw_s04_gestures.md)
for supported scope, use, retained artifacts and open CW-G01/G02/physical gates.
