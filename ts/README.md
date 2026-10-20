# SeedCore TypeScript Workspace

This workspace is the first trust-surface TypeScript slice for SeedCore.

Current packages:

- `@seedcore/contracts`: typed contracts + runtime parsers for Rust verifier JSON outputs
- `@seedcore/verification-console`: CLI that invokes `seedcore-verify summarize-transfer`
- `@seedcore/verification-api`: TS verification facade over `seedcore-verify`
- `@seedcore/proof-surface`: TS proof pages (`/transfer` and `/asset`)
- `@seedcore/drc-solver`: pure deterministic assembly/electrical/mass DRC solver, routing proposals, unknown-aware BOM and epoch-fenced worker coordinator (`CW-A04`)
- `@seedcore/robot-canvas`: offline assembly store, verified proxy assets, pure mating proposals and a Three.js ghost/rest-pose adapter
- `@seedcore/mini-studio`: localhost v2 assembly authoring, import/export, selection, undo/redo, numeric/magnetic placement and worker DRC/BOM inspector
- `@seedcore/operator-console`: TS operator workflow surface for Restricted Custody Transfer

Quick start:

```bash
npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run verify:transfer -- --dir ../rust/fixtures/transfers/allow_case
```

If `seedcore-verify` is not in your `PATH`, set:

```bash
SEEDCORE_VERIFY_BIN=../rust/target/debug/seedcore-verify
```

Run proof surface stack:

```bash
npm --prefix ts run serve:verification-api
```

In another terminal:

```bash
npm --prefix ts run serve:proof-surface
```

In another terminal for workflow operations:

```bash
npm --prefix ts run serve:operator-console
```

Then open:

- `http://127.0.0.1:7072/transfer?dir=rust/fixtures/transfers/allow_case`
- `http://127.0.0.1:7072/asset?dir=rust/fixtures/transfers/allow_case`
- `http://127.0.0.1:7073/`

Mini Studio (offline proxy authoring):

```bash
node tools/robotics/verify-authoring.cjs
.venv/bin/python scripts/robotics/serve_mini_studio.py --port 8767
```

Open `http://127.0.0.1:8767`. See the [scope and acceptance record](../docs/development/robotics/central_world_cw_a02_authoring.md).
