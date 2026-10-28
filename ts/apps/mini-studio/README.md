# Mini Studio

Local CW-A02/CW-A03/CW-A04 authoring and CW-S01 offline handoff shell for frozen assembly v2 and original proxy geometry.
Run it on a local development computer at `http://127.0.0.1:8767` to design
successive proxy robot assemblies. Snap parts interactively or import candidate
JSON from another tool, including an optional LLM. No cloud account is required.

Imports are atomic: raw JSON, catalog semantics and pinned assets must validate
before the candidate replaces the visible draft. The **Place parts** tab adds 15 mm proxy snapping, translucent ghosts, numeric
placement and subtree moves through the immutable store. The **DRC & BOM** tab runs
the epoch-fenced pure DRC worker (`@seedcore/drc-solver`), surfacing routing
proposals, 3D rotated/parallel-axis mass/COM/inertia, unknown-aware BOM and
field-linked findings. Accepted assembly changes advance `authorityEpoch` and
clear admission; stale async results cannot replace the current revision.
Selection and failed imports are distinct from accepted assembly changes.
No runtime admission or
hardware routes are supplied.

The **Simulation** tab runs the existing CW-S01 readiness policy and compiler
alongside full DRC. The physical starter stays blocked (10 DRC findings, 9
simulation blockers). Select **Load Offline Simulation Reference (Synthetic)**
for a separate pinned two-joint mathematical fixture; physical acceptance is
false and synthetic prices/power inputs are not supplier evidence. Select
position/ideal-torque mode, timestep and gain, inspect the manifest/mappings and
limitations, then copy/download `.mjcf.xml` or canonical `.cw-s01.model.json`.
Loads and edits clear old artifacts; undo/redo recompiles under a fresh epoch.
CW-S02 now adds a pinned single-thread MuJoCo worker rehearsal. Explicitly
apply its qualified settings (`dt=0.002`, position `kp=1` or ideal torque) to
compile a new model digest; CW-S01 defaults/exports stay available. Runs are
bounded to 60 substeps, with per-step control/capture gates and interruption
on edit, parameter change, undo/redo, stop or tab hide. Broader model/device and
portal/iframe qualification remain open.

The **Moments** tab adds CW-S04 declarative Hermite joint targets and virtual
LED cues for synthetic position fixtures with 1–3 joints and at most five
assembly bodies. Apply the qualified position settings, create or paste a
gesture, validate its complete curves, then rehearse up to 120 steps / 240 ms.
Stop retains partial capture when acknowledged. Edits invalidate old gestures
and replay; the scrubber reads captured targets and observations without stepping
physics. Replay import requires this session's original capture digest, retained
independently of the imported JSON. These unsigned simulation artifacts grant
no execution authority or physical qualification. Run
`node tools/robotics/verify-cw-s04.cjs --browser` for the focused native and full
Studio/browser checks; see the
[CW-S04 record](../../../docs/development/robotics/central_world_cw_s04_gestures.md).

`node tools/robotics/verify-authoring.cjs --browser` requires the pinned native
MuJoCo 3.15.0 environment as well as Chrome. It compares actual browser exports
to fresh compiler bytes and compiles the downloads natively. Evidence is retained
in `artifacts/robotics/cw-s01/studio/`. The separate full native compiler parity
runner remains `node tools/robotics/verify-mjcf.cjs`.

The optional [browser performance lab](../../../docs/development/robotics/browser_performance_pipeline.md)
at `/performance.html` runs the pinned synthetic planar Wasm fixture in a physics
worker and WebGPU in an OffscreenCanvas render worker. Compare transferable
matrices, atomically protected shared matrices, and shared angles with WGSL
display FK. Select load/500–1000 Hz target/duration and export measured results.
This page does not simulate the authored assembly or close CW-S02 acceptance.
An unavailable WebGPU adapter fails explicitly; the authoring page remains usable.
Without shared memory or isolation, shared modes and **Compare all three** are
disabled; **Run measurement** can still exercise transferable matrices with
worker WebGPU. No unavailable mode is counted as a successful comparison.

```bash
node tools/robotics/verify-browser-performance.cjs --browser
```

Run that command from the repository root. It requires a real Chrome WebGPU
adapter; omitting `--browser` explicitly reports that GPU/browser checks did not
run. See the linked record for capability, copy, timing and authority boundaries.

The [static scene lab](../../../docs/development/robotics/static_scene_streaming.md)
at `/scene.html` adds pinned NASA 3D Tiles HLOD traversal, background Draco
decoding, an OffscreenCanvas WebGL2 renderer, bounded caches and origin rebasing.
Its original mini-workbench visuals stay separate from one synthetic Wasm actor.
Corrupt detail latches a degraded coarse view while physics continues; static
visuals never become collision, DRC or motor data. The first profile is texture
free; KTX2/Basis and external CAD ingestion remain separate work.

```bash
node tools/robotics/verify-static-scene.cjs --browser
```

From the repository root:

```bash
npm --prefix ts ci
node tools/robotics/verify-authoring.cjs
.venv/bin/python scripts/robotics/serve_mini_studio.py --port 8767
```

Open `http://127.0.0.1:8767`. Add `--browser` to the verifier for the real-browser
exercise. See the [entry/acceptance record](../../../docs/development/robotics/central_world_cw_a02_authoring.md)
for supported scope, dependencies, history bounds and retained evidence.

See [CW-SNAP-01 scope and evidence](../../../docs/development/robotics/central_world_cw_a03_snapping.md)
for the fixed twist/capture policy and explicit-joint restrictions, and
[CW-DRC-01..03 scope and evidence](../../../docs/development/robotics/central_world_cw_a04_drc.md)
for the worker DRC, 3D inertia aggregation and unknown-aware BOM contract.
