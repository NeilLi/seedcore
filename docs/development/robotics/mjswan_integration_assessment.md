# mjswan: applicability and integration decision

Date: 2026-10-16
Status: Source assessment complete; conditional integration candidate, no runtime imported

## Decision

Evaluate **mjswan 0.11.9** as the first interactive MuJoCo/ONNX candidate for
CW-S02/CW-S03. Reuse its scene packaging, viewer and policy machinery where the
qualification below succeeds. Do not add it to SeedCore's core dependencies or
replace either existing simulator yet. The source review establishes useful
capabilities and concrete integration gaps; it is not a browser benchmark or
Microduck compatibility result.

Keep CW-A01's assembly/joint/net contract next in the
[delivery schedule](central_world_remaining_delivery_schedule.md). The
fixed-base tabletop gesture remains the first supported simulation target;
Microduck locomotion retains its independent model/training gates. No hardware
is connected, and this decision does not enable WebSerial or firmware release.

| Suggestion | Decision for current SeedCore |
| --- | --- |
| Reuse an established MuJoCo/ONNX viewport | Conditional adoption candidate in CW-S02/CW-S03; prove the control and state-ownership seams before committing to a fork |
| Replace `tools/mini-sim` | Retain the custom planar engine, lessons and native/Wasm invariants; it does not implement arbitrary MJCF, contacts or biped locomotion |
| Use Python Builder for skill packaging | Evaluate as an isolated build tool, with pinned assets and output inspection; a generated mjswan manifest is not a SeedCore skill/admission contract |
| Port Microduck with `mjlab-to-mjswan` | Reuse its preflight/parity method after reconciling versions and exact task/actuator support; not an immediate export path |
| Intercept ONNX output and clamp | Replace with a reviewed admission/enforcement seam covering processed commands and every physics substep; no silent alteration of an admitted payload |
| Hot-swap policies and perturb robots | Exploration features first; admitted runs require bound policy/state revisions and recorded disturbances |
| Adopt WebXR, Cloud and community publishing | Defer; not needed for the January authoring/simulation alpha |

## Verified upstream facts and corrections

The inspected source is commit
[`8f57ab5024de57a577c17e6ca7bb3d31f6ae7518`](https://github.com/ttktjmt/mjswan/tree/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518).
On the review date, GitHub main and the npm package's `gitHead` matched this
revision; PyPI and npm reported **0.11.9**, rather than the suggested 0.8.0.
These are dated observations, not floating dependency specifications.

| Area | Observed contract / implication |
| --- | --- |
| Distribution | Python `Builder` exports a static application/document; npm exports `createEngine(element, options)` and scene/policy interfaces. Both distribution paths exist. |
| Physics dependency | Python pins `mujoco==3.11.0`; npm aliases `mujoco` to `@ttktjmt/mujoco@3.11.0`. SeedCore's model/workbench baseline is 3.15.0. The alias is not SeedCore's planned official `@mujoco/mujoco` package. Source/build equivalence and model parity remain unproved. |
| Training dependencies | The optional exporter pins `mjlab==1.6.0`. SeedCore's inspected Microduck RL revision pins `mjlab==1.3.0`. Installing both into the existing environment is not a compatible integration plan. |
| Inference | `OnnxModule` imports `onnxruntime-web/wasm` and selects `executionProviders: ['wasm']`. WebGPU is not an available backend of this reviewed policy path. |
| State ownership | The public engine requires an `HTMLElement`, creates WebGL rendering and runs an asynchronous physics/policy loop in its runtime. “Headless” means no React UI requirement here; it does not establish a DOM-free, worker-owned physics engine. Wasm pthreads are a separate option. |
| Public hooks | `loadScene`, `setPolicy`, playback, commands, events and subscriptions are exposed. There is no public per-action/per-substep authorization veto or complete telemetry snapshot/export hook. State subscriptions primarily expose UI state. |
| Control application | Internal `stepPhysics` reapplies `applyAction` for each decimation substep. Control can be a position/velocity target, torque or another supported actuator mode; external PD can recompute torque from changing state. A raw policy vector is not always the final actuator command. |
| Failure behavior | The inference routine catches/logs errors and returns; the outer loop can still step physics using the last action. Missing term graphs can warn/skip. SeedCore needs explicit fault propagation and fencing instead of accepting those demo recovery paths as governed execution. |
| Scene input | `loadScene` takes model bytes, normally a zipped MJCF `.mjz`, or a version-specific `.mjb`. In-memory assembled XML needs a reviewed asset/container adapter; there is no visual assembly editor. |
| Hosting | Multithreaded MuJoCo is opt-in and requires COOP/COEP. Single-thread mode exists; its actual model/device behavior must still be measured. Isolation is not a blanket prerequisite for every single-thread application. |
| Packaging | The snapshot declares Node >=24.19.0, npm >=11.10.0 and React 18 dependencies. Review these alongside the proposed React 19 canvas integration and lock transitive dependencies. |

Primary source files:
[Python dependencies](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/pyproject.toml),
[npm manifest](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/package.json),
[engine interfaces](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/src/engine/types.ts),
[engine creation](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/src/engine/createEngine.ts),
[inference](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/src/core/policy/OnnxModule.ts),
[runtime](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/src/core/engine/runtime.ts),
[action application](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/src/mjswan/template/src/core/action/applyAction.ts).
Release metadata: [PyPI 0.11.9](https://pypi.org/project/mjswan/0.11.9/) and
[npm registry](https://registry.npmjs.org/mjswan/0.11.9).

Apache-2.0 is present in the inspected
[license](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/LICENSE).
Retain applicable licenses/notices and review the separately distributed model,
policy, mesh and dependency rights. The official
[MuJoCo README](https://github.com/google-deepmind/mujoco#bindings) links mjswan
as an extension of browser bindings. That link does not establish institutional
support, a contributor's affiliation or suitability for SeedCore's gates.

## Microduck is a separate compatibility decision

The inspected training source is
[`cb70b792312d559a4da09064d92009079671815f`](https://github.com/pollen-robotics/microduck_rl/tree/cb70b792312d559a4da09064d92009079671815f).
Its [dependency pins](https://github.com/pollen-robotics/microduck_rl/blob/cb70b792312d559a4da09064d92009079671815f/pyproject.toml)
and BAM/friction/backlash/delay actuator configurations require explicit
preflight against mjswan's supported action/actuator behavior. Do not replace
training dynamics with generic PD and describe the result as equivalent.

The upstream
[`mjlab-to-mjswan` skill](https://github.com/ttktjmt/mjswan/blob/8f57ab5024de57a577c17e6ca7bb3d31f6ae7518/skills/mjlab-to-mjswan/SKILL.md)
was inspected as pipeline documentation, not executed. Its useful requirements
include unsupported-term preflight, explicit policy joint/home/encoder metadata
and independent numerical parity. Merely tracing/building a task is insufficient.
Perform any migration/export experiment in a disposable environment; never
upgrade SeedCore's frozen runtime or the pinned training environment implicitly.

SeedCore already has an ONNX candidate and 16 upstream-derived observation/action
artifact cases. Matching training-checkpoint/export outputs are still missing;
artifact replay does not close that gap. Preserve the pinned 61/14 contract:
48 state/history components plus 13 command components, previous **raw** policy
action, exact full-precision home/order, embedded normalization and 20 ms policy
period. Do not add a generic phase clock or apply normalization twice. A modified
body, backlash model or different task needs its own compatibility profile.
Check action clipping order too: mjswan applies its configured raw-action clamp
before recording previous actions. That configuration must reproduce the pinned
training/runtime contract, not silently change Microduck's history inputs.
See [simulation-first acceptance](simulation_first_acceptance.md) and the
[Microduck contract](../../../src/seedcore/robotics/microduck_contract.py).

## Required SeedCore integration shape

```text
Assembly + explicit joints -> reviewed model/behavior/profile digests
                                      |
Agent -> PDP -> existing ExecutionToken + bound session specification
                                      |
policy or gesture proposal -> enforcement inside the state-owning executor
                                      |
                    approved controls -> MuJoCo substeps
                                      |
              captured observations/actions/events -> scoped replay/verifier
```

The governance boundary is inside control application, not a layer reached after
the simulator has already acted. Validate both raw outputs and processed commands,
units and finite values; recheck the active generation/deadline/revocation after
asynchronous inference and immediately before substeps. Use monotonic wall time
for lease/freshness limits separately from simulation time. Bound queues/capture;
late inference, overflow, hidden-tab suspension and faults fence the attempt.

The current `ExecutionToken` does not acquire new torque/velocity fields through
this proposal. Bind reviewed limits through the existing payload/spec digest
contract. A transformation may run only when it is part of the admitted behavior;
otherwise deny or return for new admission. Zero `ctrl` is not a universal safe
pose or stop for position-controlled actuators.

Inventory command-driven joints, external PD, events, resets, auto-reset,
policy/scene changes and pointer/XR forces as well as ONNX output. Policy/model
switches fence the old attempt and require compatible state plus fresh admission.
Disable disturbances during admitted runs unless declared, bounded and captured;
a PRNG seed alone cannot replay interactive input. Do not treat custom MDP
plugins as untrusted skill code: they are trusted executable extensions.

Browser-local checks support a scoped simulation experience. They are not a
hardware trust root. Signed evidence needs an explicitly trusted host/device
signer and accurate source bindings; a browser log is not automatically an
action-bound signed receipt. The Rust kernel verifies evidence; it does not mint
receipts. Existing host-signed rehearsal evidence remains simulation-only.

## Bounded qualification work and stop conditions

These are acceptance substeps of CW-S02/CW-S03, not a second delivery calendar.
Before implementation, freeze the owner, effort cap, fixtures and thresholds.
CW-S02 can rehearse the seam with explicit fixture authority. Live Agent/PDP
integration remains CW-G01; a fixture pass cannot close that gate.

1. **API feasibility first:** produce a small design/patch showing worker-owned
   state, a veto before control/substeps, generation-fenced asynchronous work and
   bounded telemetry export. Test every control/state mutation path. Prefer a
   generic upstream extension; do not build on a monkey-patched private method
   or an observation plugin pretending to be an authorization hook.
2. **Model/engine qualification:** use one fixed-base primitive fixture. Record
   engine source/build/binary hashes, dt, solver/actuator options and model digest;
   compare native/browser compile, FK, mass, actuator order and short rollouts
   against frozen tolerances. An isolated native 3.11.0 comparison characterizes
   mjswan; it does not qualify SeedCore's existing 3.15.0 model package. Any version
   migration requires a new reviewed baseline, not a silent downgrade.
3. **Bounded attempt and performance:** use a declarative gesture before learned
   locomotion. Exercise invalid/expired/revoked authority, stale inference, policy
   swap, pause/reset, tab stall, worker crash and capture overflow. Record build
   size/load/memory, physics and inference p50/p95, render FPS and missed deadlines
   on named devices. Compare equivalent supported tasks; the 13 KB planar engine
   and a contact-rich biped engine do not establish comparative accuracy/speed.
4. **Policy qualification:** run frozen input/output vectors under the actual
   browser ORT build, then closed-loop native/browser traces for the exact body
   and policy. Do not equate 60 FPS rendering with a sustained 50 Hz policy loop,
   or use upstream demo success to close Microduck training parity.

If the worker/control/capture seams require a substantial private fork, defer
the full mjswan runtime and evaluate the separately pinned official MuJoCo Wasm
bindings behind the same SeedCore adapter contract. Reuse only the portions that
remain maintainable. No fallback may silently become the planar engine or bypass
governance to preserve a demo. Record go/rescope/defer under
[CW-SIM/CW-POL acceptance](central_world_acceptance_matrix.md).

This review changed planning documents only. No mjswan dependency was installed,
no source was copied, and no browser/native benchmark, policy export, hardware
test or live PDP integration was performed.
