# CW-L01: local gallery and draft forks

Date: 2026-11-06
Status: Local software candidate; reviewable with automated browser evidence

Mini Studio provides a curated local manifest containing the tabletop starter
and the synthetic simulation reference. The starter is pinned by exact source
bytes; the synthetic reference is pinned by the canonical assembly digest and
its required simulation-only scope. Neither source is a physical profile.
The visible gallery uses static text and local endpoints. The existing assembly,
catalog and proxy-mesh validators check dependencies before replacing a draft;
missing or changed inputs leave the previous draft intact.

Creating a fork uses a fresh random assembly ID, draft status and a new local
revision. Its v2 metadata records the curated entry, source path, digest and
digest profile, license and prior metadata. Those declarations travel with the
assembly and Build Pack. They are provenance data, not a signature, hardware
qualification or execution authority; imported metadata is not an independent
trust root. An edit cannot inherit an admission from the source revision.

The [guided lesson](central_world_cw_l02_maker_lesson.md) uses a separate fork of
the synthetic reference, so the same draft can be customized, rehearsed and
exported. The original tabletop starter stays blocked for simulation and wiring.
The gallery has no public upload or publishing interface.

Run the source-built gate with actual Chrome:

```bash
node tools/robotics/verify-cw-l01.cjs --browser
```

The local candidate passed **309 workspace tests**, including four focused
gallery groups, and **seven Chrome groups**: keyboard source inspection,
unique fork identity and lineage in an independently inspected Build Pack,
repeated forks, changed-source and missing-asset refusal, complete synthetic
lesson, and mobile containment. Evidence is retained in
`artifacts/robotics/cw-l01/verification.json`, `browser-verification.json` and
the two downloaded ZIPs. The report pins source/output hashes and records the
dirty working tree. CI runs the non-browser source-built lane; remote CI has not
been observed for this change.

The affected CW-E01 and CW-G02 source-built browser regressions also pass on
the updated Studio. The Q2 contract script passes its available lanes; optional
Postgres was skipped. The authz graph's 79 focused tests pass, while its live
phase cannot connect to `127.0.0.1:8002`. Supporting M0 source-pin review
matches nine candidates and the Fast Spine protocol fixture matches; physical
board/servo/rail qualification and independent Microduck training outputs remain
open. Current combined input/output hashes are retained in
`artifacts/robotics/cw-l01-integration-verification.json`.

This is a bounded local gallery candidate. Independent maker observation, broader
browser accessibility, public hosting, licensed print-ready assets and physical
qualification remain separate acceptance work.
