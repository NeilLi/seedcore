# Restricted assembly-to-MJCF compiler

This package also exports experimental, visual-only `frameTransport`,
`FixedTickClock` and `PlanarLab` utilities used by Mini Studio's separate
[browser performance lab](../../../docs/development/robotics/browser_performance_pipeline.md).
They provide bounded transferable/shared snapshots and a pinned synthetic SIM-3
fixture. They do not run compiled MJCF or implement the CW-S02 MuJoCo adapter.
The CW-S01 compiler API and readiness policy below remain unchanged.

CW-S01 / CW-SIM-01, 2026-10-21. This package compiles the supported assembly v2
subset to deterministic, asset-free MJCF and a digest-bound manifest. It has no
browser worker, UI endpoint, hardware route or execution authority. CW-S02 owns
the future browser MuJoCo adapter.

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
and native MuJoCo checks. This handoff does not implement CW-S02 runtime physics.
