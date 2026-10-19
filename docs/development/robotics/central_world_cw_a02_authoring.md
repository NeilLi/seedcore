# CW-A02: offline Mini Studio authoring shell and immutable store

Date: 2026-10-19
Owner role: Studio/TypeScript lead
Status: Local software slice implemented; physical and later CW gates open
Review scope: CW-ASM-02, one tabletop proxy starter

## Entry decision and bounded scope

CW-A01 v2 was rechecked from source at `9c8b1c0`: **117 Python and 71 Node tests**
passed, with the original 0.2.0 starter content digest
`2550d184c44a064c6ad6a2245a08f430f257c40ca8f3627e73eeb3fedd452acb`.
The 19 October entry is one bounded authoring slice, with a one-afternoon
implementation/review budget; unresolved physical data stays in the
[M0 / CW-D01 register](m0_cw_d01_register_2026_10_19.md). This is a scope/effort
cap, not a claim of measured engineering hours or added staffing.

Supported documents are `seedcore.assembly.v2` with
`seedcore.jcs-safe-integers.v1`, `offline_proxy_no_actuation` and
`opposed_z_rx_pi`. Rigid mounts and explicit direct-parent revolute output
records retain the CW-A01 bounds and semantics. The UI imports/exports complete
v2 builds, selects nodes/edges and edits the build name. Its pure store exposes
validated draft edits for later authoring tools. The accepted visual fixture is
the five-node tabletop starter, using frozen original box GLBs and structural
rest poses. Arbitrary CAD, visual snapping, routing/DRC, joint animation,
MuJoCo/ONNX policy execution and physical controls remain later packages.

A raw import rejects duplicate **decoded** JSON keys, including escaped names,
before schema validation. Historical v1 drafts are rejected without migration.
UTF-8 text is bounded to 262144 bytes, 32 nesting levels and 50000 visited
keys/values. The browser's structural validator does not establish full catalog
or hardware validity. A localhost service applies the existing Python
catalog/port/pose/joint/electrical checks; the browser rechecks exact part-byte
pins and bounded mesh hashes before atomically accepting the candidate.

## Canvas dependency and license decision

| Dependency | Exact pin / license | Decision |
| --- | --- | --- |
| Three.js and OrbitControls | `three@0.181.1`, MIT | Small replaceable rest-pose adapter in `ts/packages/robot-canvas`; original box-proxy GLB decoder; no external model/resource loader |
| Type declarations | `@types/three@0.181.0`, MIT | Development only |
| Schema validator | Existing `ajv@8.17.1`, MIT | Generate a standalone validator at build time; browser does not compile schemas or require `unsafe-eval` |
| Bundler | `esbuild@0.28.2`, MIT | Development build only; no dev-server exposure |
| Browser acceptance | `playwright@1.61.1`, Apache-2.0 | Development only; local Chrome or explicitly installed bundled Chromium |

Three.js's [license](https://github.com/mrdoob/three.js/blob/r181/LICENSE) and
Ajv's [standalone/CSP guidance](https://ajv.js.org/standalone.html) informed this
decision; package/lockfile pins and installed license files define the actual
inputs. Browser builds include `third-party-notices.txt` for Three.js, Ajv and
fast-deep-equal. No URDF-Studio, React Three Fiber, Zustand or mjswan code is
incorporated. Revisit those dependencies when a later package demonstrates a
specific need; no license or trained-policy readiness is inferred from them.

The existing Ajv audit advisory concerns the `$data` option, which this fixed,
reviewed schema generator does not enable. Existing `tsx` tooling also carries
an esbuild Windows dev-server advisory; this app uses the separately pinned
patched bundler and no esbuild server. These existing workspace advisories are
not a clean-audit claim. Do not run broad automatic dependency upgrades as part
of authoring acceptance.

## Revision, authority and asynchronous-load rules

`AssemblyStore` copies and freezes accepted assemblies and prepared scenes.
Selection is view state: it creates no content revision or authority. Successful
imports/edits add a monotonic local sequence and a revision SHA-256 over the
versioned envelope, parent revision and existing canonical assembly digest.
The **content digest stays the CW-A01 identity**; a local history revision is
not a signed profile, receipt or production token. Identical content may have
different authoring revisions. Undo/redo restores exact accepted content and
selection; a fresh branch drops redo. History is capped at 32 entries and 2 MiB,
including scene data. A single oversized candidate rejects atomically.

Every successful edit/import, undo or redo increments an authority epoch;
`admission` is always null. Runtime authority cannot be imported, persisted or
restored through this authoring package. A future execution integration must
obtain admission for the exact current build/behavior/endpoint rather than
interpret this epoch as revocation evidence or use a prior admission.

Each load/edit gets a new generation ticket and cancels its predecessor.
Cancellation, timeout, undo/redo, a newer invalid import and disposal all fence
late results. Even a callback that ignores abort cannot commit after its ticket
becomes stale. The previous scene/digest/history remain visible during loading
and on failure; only a fully prepared candidate commits. Selection alone does
not invalidate a valid pending edit. The default load deadline is 10 seconds.

The browser persists only the latest accepted assembly under
`seedcore.mini-studio.draft.v2`, never tokens, hardware identities or prepared
assets. Restoration repeats raw-text, semantic and asset validation. Undo/redo
history is session-only. Storage failures retain the in-memory draft and offer
normal export; invalid saved text is reported without automatic reinterpretation.

## CW-ASM-02 evidence and local use

```bash
npm --prefix ts ci
node tools/robotics/verify-assembly.cjs
node tools/robotics/verify-authoring.cjs --browser
.venv/bin/python scripts/robotics/serve_mini_studio.py --port 8767
```

Open `http://127.0.0.1:8767`. The authoring runner builds contracts, canvas and app
from source before exercising consumers, preventing stale `dist` output from
masking a source change. Its default Python uses the repository virtualenv;
`SEEDCORE_TEST_PYTHON` overrides it. The browser runner starts/stops a separate
localhost service on port 8768; override `SEEDCORE_STUDIO_TEST_PORT` if occupied.
`SEEDCORE_BROWSER_CHANNEL=bundled` selects Playwright's installed Chromium;
the local default is the installed Chrome channel. No browser binary download
is needed for the local Chrome path.

| Fixture group | Required result / retained evidence |
| --- | --- |
| Frozen starter / canonical export | Revision 0.2.0 and unchanged canonical digest; exact raw component/mesh pins checked |
| Raw JSON negatives | Nested/escaped duplicate keys, malformed/oversized/deep text, unsafe numbers, v1 and unexpected token fields reject |
| Immutable history | Caller/snapshot mutation cannot change a revision; selection preserves content; undo/redo and branch truncation are deterministic; no admission restoration |
| Stale/failure matrix | Late load success/failure, delayed assets, newer invalid intent, undo, disposal, timeout and preparation failure preserve the correct current revision |
| Browser flow | Keyboard selection, save/undo/redo, download, reload restoration, atomic rejection and successful recovery |
| Visual / CSP | Local hashed proxy meshes; desktop and mobile inspection; no horizontal overflow or browser/CSP errors |
| API boundary | Same-origin localhost only, bounded body, semantic negatives, no deployment/admission/flash routes |

Evidence lives under `artifacts/robotics/cw-a02/`: `verification.json`,
`browser-verification.json`, desktop/mobile screenshots and the exported fixture.
The local run passed **58 TypeScript tests** (including 33 authoring cases),
**13 API tests**, and all **12 browser exercise groups**, with zero skipped
cases. Reports include exact source/build-input and built-output hashes,
browser version and dirty worktree state. CI runs source/store/API checks; the optional real-browser lane
is retained locally and is not reported as remote CI success. The 19 October
local run used Chrome 155.0.8059.82; no independent two-minute-maker or 60 FPS
performance claim is made.

Next implementation package is CW-A03 magnetic candidate snapping and numeric
placement, retaining this importer, atomic store and selection boundary. CW-D01
qualification, CW-A04 DRC and CW-S/CW-G runtime acceptance remain open.

The review follow-up reads non-2xx response bodies directly through the same
bounded reader. Empty errors retain the HTTP status; oversized errors reject
without allocating an unbounded text response. No Response body is rewrapped.

CW-A02 is committed as `4708e06`. The [CW-A03 follow-through](central_world_cw_a03_snapping.md)
now adds proxy placement to the same authoring app. Current browser outputs
are retained under `artifacts/robotics/cw-a03/`; the 58-test CW-A02 count above
records the reviewed handoff, before the additional snapping cases.
