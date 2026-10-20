# Mini Studio

Local CW-A02/CW-A03/CW-A04 authoring shell for frozen assembly v2 and original proxy geometry.
Imports are atomic: raw JSON, catalog semantics and pinned assets must validate
before the candidate replaces the visible draft. The Place parts tab adds 15 mm proxy snapping, translucent ghosts, numeric
placement and subtree moves through the immutable store. The DRC & BOM tab runs
the epoch-fenced pure DRC worker (`@seedcore/drc-solver`), surfacing routing
proposals, 3D rotated/parallel-axis mass/COM/inertia, unknown-aware BOM and
field-linked findings. No runtime admission or
hardware routes are supplied.

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
