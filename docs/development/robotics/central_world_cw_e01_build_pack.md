# CW-E01: draft design Build Pack

Date: 2026-11-05
Final verification and handoff: 2026-11-06
Status: Named local draft-design slice passed; broader package/physical gates remain open
Acceptance target: CW-PACK-01, named offline draft-design slice only

The [5 November allocation](cw_e01_daily_plan_2026_11_05.md) follows the
[independent local CW-G01/CW-G02 review](cw_g02_exit_review_2026_11_05.md).
CW-E01 adds a design archive; signed attempt evidence continues to use the
separate CW-G02 download/verifier path. The real tabletop starter remains
blocked for simulation and physical qualification; a draft pack preserves
those findings rather than treating export as approval.

## Archive contract and supported scope

`createBuildPack(CompilerInput)` in
[`buildPack.ts`](../../../ts/packages/wasm-sim-bridge/src/buildPack.ts) is a pure
browser-compatible exporter. It validates the assembly, exact raw catalog/part
pins, component documents and independently recomputed full DRC with its options.
Changed source bytes, altered reports and stale bindings are refused.

The versioned `seedcore.cw-e01.build-pack.v1` manifest records draft status,
`physicalAcceptance: false`, `executionAuthority: none`, assembly/catalog/DRC
and option digests, known-price subtotal, unpriced instance count and unresolved
net count. Its inventory hashes every other payload file and states that the
manifest excludes itself. The verification report separately hashes whole ZIPs.

Payloads include the canonical assembly, original catalog/part bytes with a
generated-path map, full DRC and options, BOM CSV/summary, an explicit-net SVG,
asset reference/rights inventory and explanatory README. A model and MJCF are
included only when the existing restricted compiler accepts the input; a blocked
or unsupported design retains its explicit omission reason. Compiler output
does not establish runtime/device qualification.

Unknown prices remain blank in the CSV and are excluded from the known subtotal;
the summary preserves counts and completeness. CSV text is quoted and formula
prefixes are neutralized. The diagram uses escaped text and only assembly-owned
net/endpoint/pin declarations. All nets remain unreviewed in this slice; no
routing proposal becomes an approved wiring instruction.

Raw source declarations are preserved for reproducibility. Declared visual
licenses are reference facts, with rights review and external byte verification
explicitly unestablished. Meshes, CAD, print-ready files, firmware, gestures,
execution tokens, signer context and signed receipts are not exported by this
slice. There is no external download or generic archive importer.

## Bounds and determinism

Source catalog plus part documents are limited to 2 MiB; an individual payload
is limited to 2 MiB. The archive has at most 288 entries and an 8 MiB total byte
ceiling. The net SVG is wrapped and limited to 1,024 rendered lines; forbidden
XML control characters are replaced. Existing assembly/schema/parser limits
apply as well. Files use fixed
names or numeric generated part names, unique safe relative paths, sorted
inventory/order and ZIP STORE with CRC32 and a fixed 1980 timestamp. No
compression or imported decompression is performed. Identical valid inputs
produce byte-identical ZIPs.

## Studio workflow

In Mini Studio's DRC/BOM panel, **Download draft design ZIP** becomes available
only after current accepted DRC. It binds revision, assembly, catalog and
authority epoch; loading, edits, undo/redo, rechecks, simulation settings and
disposal invalidate retained export state. A separate declared design-export
preset uses position gain 1 and timestep 0.002 s. It is not a replay of the
currently selected runtime settings or a new execution request.

The UI shows unknown-cost/unresolved-net state, model inclusion/omission and
the manifest. Export does not mutate the authoring store or call admission,
control or verification APIs. An already downloaded archive remains a labeled
snapshot; it cannot acquire current runtime authority.

## Reproduction and evidence

```bash
node tools/robotics/verify-cw-e01.cjs --browser
```

The intended source-built gate covers focused adversarial archive/CSV/pin/DRC
checks, workspace typechecking, CLI exports, independent Python ZIP extraction
and inventory verification, and actual Chrome starter/reference downloads.
Retained results live under `artifacts/robotics/cw-e01/`.

The source-built gate passes **305 workspace tests**, including **25 exporter
tests** and **five current-binding tests**, plus workspace typechecking and all
five required source builds. It exports two deterministic CLI packs and checks
them independently with Python ZIP/CRC/SHA, original source, CSV and XML readers.
The Studio lane passes **nine real Chrome groups**, including settings changed
during pending DRC, edits/undo, pending load, keyboard download and mobile
containment. Six downloaded ZIPs are independently inspected by the browser
runner; the independent reviewer also checked its seventh keyboard download.
Export causes no network request or authoring-state mutation.

The actual starter/repeat/keyboard archives are byte-identical: **66,548 bytes,
24 entries, five unpriced part instances, model omitted**. Reference/settings/
undo archives are byte-identical: **28,908 bytes, 17 entries, model included**.
The separate design preset and fresh DRC preserve repeatability while settings
generation fencing prevents a delayed old DRC reply from restoring export.
Desktop/mobile screenshots were visually reviewed. The main evidence report is
`artifacts/robotics/cw-e01/verification.json`; independent CLI checks are in
`independent-verification.json`, and actual browser downloads/reports/screenshots
are under `studio/`.

Final shared governance/Studio regression results are recorded in the
[daily delivery record](cw_e01_daily_plan_2026_11_05.md).
The 6 November source-built rerun passed; its final inventory audit matched all
135 source and 30 output hashes. The named local draft review and handoff are
complete; CW-L01's curated local gallery/fork flow is the next implementation.
Remote CI, full CW-E01 package promotion, printable asset support, reviewed
physical wiring, firmware/provisioning and production/physical qualification
are not established by the draft slice.
