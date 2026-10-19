# Mini Studio

Local CW-A02 authoring shell for frozen assembly v2 and original proxy geometry.
Imports are atomic: raw JSON, catalog semantics and pinned assets must validate
before the candidate replaces the visible draft. No runtime admission or
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
