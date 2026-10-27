# CW-S01: restricted assembly-to-MJCF compiler and native parity

Date: 2026-10-23
Status: Local compiler/native parity and Mini Studio offline handoff delivered; CW-S02 fixed-preset local runtime recorded separately; physical starter and broader runtime/live/hardware qualification remain open
Review: CW-SIM-01

## Scope and approved gate decision

The 21 October sprint requests a restricted compiler in
[`@seedcore/wasm-sim-bridge`](../../../ts/packages/wasm-sim-bridge/README.md),
native compile/FK/mass/range checks and the Oct 21–27 regression window check.
CW-A01..A04 supply the source baseline; no hardware or new actuator SDK is needed.

Preflight found a conflict in the requested overall-DRC-pass prerequisite:
the authoritative [assembly validator](../../../src/seedcore/robotics/assembly.py)
accepts declared actuator outputs only with `simulation_proxy` geometry, while
[CW-A04](central_world_cw_a04_drc.md) emits `MECHANICAL_PROXY_UNQUALIFIED` for
proxy geometry. Marking a test actuator drawing-reviewed would violate v2;
changing unknown ratings would invent evidence.

The user approved preserving the gate/blocked starter, using synthetic positive
fixtures, and defining a **separate offline simulation-readiness check**.
`seedcore.cw-s01.simulation-readiness.v1` defers only the blocked physical-fit
finding `MECHANICAL_PROXY_UNQUALIFIED` for offline compilation. Every other
finding/conflict remains blocking. It never rewrites the original report to
`pass`, grants authority, or closes physical acceptance. This conservative
policy still blocks unknown cost/electrical data even where a later, separately
reviewed simulation policy might distinguish more categories.

## Implemented boundary

The pure TS compiler accepts a fixed chassis root, one serial chain, rigid
mounts and one to three explicit revolute outputs. Limits are 32 bodies,
1 m per primitive dimension and 5 kg modeled total, as software scope/resource
bounds. Floating/branched/prismatic or inferred articulation is refused.

It checks component/assembly schemas, exact catalog/part bytes, intrinsic
component consistency, catalog port mating, actuator limits, electrical endpoint
semantics and a freshly recomputed full DRC report. Generated standalone
component validation extends the existing CSP-safe schema generator; no
runtime schema code generation is required.

Generated MJCF contains only primitive box geometry and explicit COM/full
inertias. Parent-part joint axes/pivots are converted into child-body coordinates;
nonzero joint references preserve the declared rest pose. Position and ideal
torque modes have explicit control and force ranges. Velocity limits are
metadata, **not an MJCF enforcement claim**. Proxy contacts are disabled, with
no electrical/thermal dynamics or physical servo fidelity asserted.

The canonical model identity covers XML, scope and the entire manifest, including
compiler/subset/readiness versions, assembly/catalog/electrical/report digests,
DRC options and actuator/timestep settings. Cached artifacts must match
independently retained current bindings. Visual paths are constrained but never
loaded; the compiler emits no mesh/include/plugin or filesystem-loading hook.

## Synthetic positives and actual starter rejection

[`cw-s01.ts`](../../../ts/tests/fixtures/cw-s01.ts) constructs separately named,
re-pinned **in-memory synthetic source documents**. They retain valid proxy
actuator geometry and use explicit mathematical power/cost inputs; these are
not supplier quotations or qualified ratings. One rotated non-actuator fixture
has non-diagonal inertials and an offset COM. Python independently validates
the exact component bytes and full assembly semantics before native compilation.

Twelve models cover one/two/three joints, aligned/rotated frames, nonzero rest
angles and position/ideal-torque actuation. No committed catalog part, starter
digest, pinout or physical profile is changed. With this compiler's default
DRC options, the actual starter remains `blocked` and has simulation-blocking
findings after the physical-fit finding is deferred. No successful native model
for the real starter is emitted.

## Verification and evidence

```bash
# Rebuild contracts, DRC and compiler; require native MuJoCo parity
node tools/robotics/verify-mjcf.cjs

# Recheck existing authoring/DRC/API surfaces and the new compiler unit tests
node tools/robotics/verify-authoring.cjs
```

The compiler verification includes:

- **16 TS tests** for determinism/scope, actual starter rejection, source and
  report freshness, forged pass/mass, unsupported graph/root/joint, component
  schema/port/net semantics, invalid inertia, traversal/XML injection and stale
  model/settings bindings.
- **13 native Python tests**, using pinned MuJoCo **3.15.0**: authoritative
  Python assembly validation, native compilation of the 12 models, independent
  Rodrigues/transform FK at reference/zero/range/interior states, per-body and
  subtree mass, COM/full tensor parity with CW-A04, joint/actuator ranges and
  preservation of actual-starter rejection. No engine fallback is permitted.

Retained local evidence is `artifacts/robotics/cw-s01/verification.json` and
`models/cases.json`; generated XML/manifest identities and source hashes are
recorded. `--skip-native` produces an explicit native-not-run result and cannot
claim the native acceptance above. CI runs the full verifier after installing
the existing pinned `robotics-sim` extra and retains its report.

## Oct 21–27 simulation/session window check

The unmodified baseline passed 97 TS authoring/DRC/workspace tests and 14 FastAPI
tests before compiler work. Independent checks passed:

After the changes, the authoring verifier passed **113 workspace TS tests and
14 FastAPI tests**, including all original authoring/DRC regressions and the
new compiler tests, with workspace typechecking and generated-validator checks.

```bash
.venv/bin/python -m pytest tests/test_fast_spine_sessions.py tests/test_fast_spine_studio.py tests/test_fast_spine_rust.py tests/test_fast_spine_protocol.py tests/test_mujoco_workbench.py tests/test_model_package.py -q
.venv/bin/python -m pytest tests/test_microduck_readonly.py -q
.venv/bin/python scripts/robotics/review_m0_pins.py
```

The first command passed **153 tests**, the read-only adapter suite **33**, and
the local pin review reported **9 candidate pins matched**. Existing dependency
deprecation warnings remain; no version upgrade was made.

Actual Chrome checked the delivered split-screen Session Lab on loopback:
the independent Wasm tree pane loaded, a three-servo host simulation was
admitted, deadline fencing produced `verified_interrupted`, and expired
permission was denied with no new session. The temporary server was stopped.
`artifacts/robotics/cw-s01/window-check.json` records these observations.

Keep classifications distinct: Microduck is read-only native model evaluation;
Session Lab uses a host simulation fixture issuer; wire tests are protocol
fixtures; **no physical hardware is connected or qualified**. These checks do
not close production PDP, MCU/enrollment or stopping-time gates.

## 23 October: Studio handoff and offline reference

Preflight confirmed the canonical next package and the missing Studio wiring.
The proposed task's finding counts were outdated: the current physical starter
has **10 blocked DRC findings**, of which **9 block simulation** after physical
proxy fit is deferred. They are two `GPIO_PINS_UNASSIGNED`, one each of
`UART_PROTOCOL_UNKNOWN` and `UART_LOGIC_VOLTAGE_UNKNOWN`, two each of
`POWER_UNKNOWN_RATING` and `POWER_RAIL_UNCONNECTED`, and `BOM_UNPRICED_PARTS`.
The committed physical catalog/starter bytes and readiness policy are unchanged.

Owner roles: Studio/TypeScript and simulation integration, with verification
review. Bounded scope/review date: 23 October local CW-S01 handoff only, using
the existing compiler subset and pinned toolchain/native MuJoCo 3.15.0. No
browser physics engine, policy, source qualification or hardware work is included.

[`packages/simulation-fixtures/cw-s01/reference.json`](../../../packages/simulation-fixtures/cw-s01/reference.json)
provides a separately pinned two-joint **Offline Simulation Reference** and three
synthetic component sources. Every source is explicitly mathematical, with
`provenance: synthetic_fixture`, `physicalAcceptance: false` and authority none.
Synthetic power inputs/$1 estimates are not supplier ratings or quotations.
The API validates the exact part pins, existing proxy assets and authoritative
assembly semantics; edits use the same validator. Physical/synthetic source
mixing is rejected. Both profiles retain the full DRC result; only the reference
is eligible for the existing conservative simulation-readiness policy.

Mini Studio's **Simulation** tab now exposes readiness, exact blocking/deferred
findings, position/ideal-torque mode, timestep and position gain. It compiles
deterministic `seedcore.cw-s01.model.v1` artifacts, shows source/model identity,
body/joint/actuator mappings, rest angles, velocity metadata and limitations, and
copies/downloads canonical model JSON or exact MJCF XML bytes.

Exports bind `{revisionDigest, assemblyDigest, catalogDigest, drcDigest,
authorityEpoch}` plus an independently retained model digest. Pending loads,
edits and undo/redo clear old artifacts immediately; current full DRC and source
checks precede recompilation. Undo can restore identical model bytes while the
local authority epoch advances. Invalid settings and unsupported graphs refuse
compilation. Switching profiles fences late catalog responses and allows a
fresh retry when returning to a profile.

Verification on 23 October:

- `node tools/robotics/verify-mjcf.cjs`: **18 TS tests + 15 native Python tests**,
  now covering 14 models, including both committed Studio reference modes with
  independent native FK/mass/inertia/range checks.
- `node tools/robotics/verify-authoring.cjs --browser`: workspace typechecking,
  **134 TS tests, 22 FastAPI tests, 27 Chrome exercise groups**, and **2 native
  tests on the actual downloaded Studio bundles**. Browser XML and canonical
  model bundles are byte-identical to fresh source compilation in both modes.
  Tests cover exact physical starter blockers, synthetic provenance, copy and
  download, settings rejection, joint edits, pending-load invalidation,
  undo/redo epochs, stale catalog responses, reload and mobile overflow.

Evidence: `artifacts/robotics/cw-s01/verification.json`, `models/cases.json`, and
`studio/{verification.json,browser-verification.json,browser-handoff.json}`.
The `studio/` directory also retains downloaded XML/model bundles and a browser
screenshot. These are local working-tree checks, not a committed release.
`--skip-python` omits API/native checks; `--browser` is required for browser
handoff evidence. Neither omission can claim the full handoff verification.

## Remaining work

CW-S01's offline Studio handoff is available through the separately pinned
synthetic reference. [CW-S02](central_world_cw_s02_mujoco.md) now delivers the
pinned `@mujoco/mujoco@3.15.0` browser worker, clocks, bounded capture, and
per-substep control gate (`CW-SIM-02..04`). Real-source physical starter
readiness remains CW-D01 work; never silently fill unknown fields or reuse
synthetic sources as product qualification. The
[26 October CW-S03 preflight](central_world_cw_s03_preflight.md) records CPU
artifact replay and both blocked policy-runtime candidates; full policy execution
remains gated. The [active queue](../current_next_steps.md) selects CW-S04 bounded
gesture/replay next. CW-G/F live/firmware work remains separately gated.
