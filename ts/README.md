# SeedCore TypeScript Workspace

This workspace provides browser studios, deterministic authoring/DRC libraries,
and trust/proof surfaces for local development and successive robot designs.
Prepared authoring workflows require no remote LLM account.

## Package Map by Role

### 1. Central World DIY Robot Authoring, Snapping & DRC (`CW-A01`–`CW-A04`)

Interactive edits and imported candidate JSON use the local validation and
immutable-store path. DRC reports findings for accepted drafts; custom-build
simulation and live admission remain subsequent packages.

- `@seedcore/contracts`: typed contracts + runtime parsers for Rust verifier JSON outputs and `seedcore.assembly.v2` (`parseStrictJson` with duplicate-key rejection and `seedcore.jcs-safe-integers.v1` canonicalization)
- `@seedcore/robot-canvas`: offline `AssemblyStore` (32-entry / 2 MiB history, `authorityEpoch` fencing), verified proxy assets, pure `15 mm` / `5°` mating proposals (`CW-SNAP-01`) and a Three.js ghost/rest-pose adapter
- `@seedcore/drc-solver`: pure deterministic assembly/electrical/mass DRC solver (`CW-DRC-01..03`), point-to-point/star routing proposals, 3D rotated/parallel-axis inertia, unknown-aware BOM and epoch-fenced worker coordinator (`CW-A04`)
- `@seedcore/wasm-sim-bridge`: CW-S01 restricted primitive MJCF compiler with separately versioned offline simulation readiness and native parity tests; actual starter stays blocked, browser worker remains CW-S02
- `@seedcore/mini-studio`: localhost v2 assembly authoring shell (`http://127.0.0.1:8767`) with import/export, selection, undo/redo, numeric/magnetic placement and worker DRC/BOM inspector

### 2. Trust & Proof Surfaces

- `@seedcore/verification-console`: CLI that invokes `seedcore-verify summarize-transfer`
- `@seedcore/verification-api`: TS verification facade over `seedcore-verify`
- `@seedcore/proof-surface`: TS proof pages (`/transfer` and `/asset`)
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
