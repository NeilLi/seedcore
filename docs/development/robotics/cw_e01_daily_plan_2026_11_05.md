# 5 November: local evidence review and draft Build Pack

Date: 2026-11-05
Timezone: Asia/Bangkok (UTC+07:00)
Inspected baseline: `36fceb120125c6e288e8b28cfd4dfe63aa661b54` (`main`, clean at inspection)
Status: Named local draft slice delivered; final verification and handoff closed 2026-11-06

The latest committed result is the 4 November CW-G02 Studio Evidence Inspector.
The canonical queue requires a review of that named local slice before selecting
the next CW-E01 package. Today's work reviews the existing simulation evidence
and prepares a bounded, offline **draft design Build Pack**. It does not promote
production or physical qualification. The master phase calendar is unchanged;
the windows below are today's execution allocation, with early completion allowed.

## Agent ownership and afternoon allocation

| Time (Bangkok) | Owner | Work and reviewable handoff |
| --- | --- | --- |
| 14:00–14:30 | `cw_g02_exit_review` — independent verification | Fresh source-built CW-G02 Python/Rust/API/Chrome acceptance, trust/read-only/freshness review, and a scoped GO/RESCOPE/DEFER report. Record unavailable live services explicitly. |
| 14:00–15:30 | `cw_e01_export_core` — exporter | Pure deterministic bounded ZIP exporter; canonical assembly and pinned source documents, full DRC, unknown-aware BOM, explicit-net SVG, hashes/rights/omissions and optional supported MJCF/model. Add adversarial tests and independent extraction. |
| 14:00–16:15 | `cw_e01_studio` — Studio | Draft-pack download for the current accepted DRC/revision, with epoch/catalog/settings invalidation. Exercise actual starter/reference downloads, edits and mobile layout in Chrome. |
| 16:15–17:30 | Coordinating agent, with implementers | Review combined diff, run source-built exporter/browser checks and affected governance regressions; resolve concrete defects. |
| 17:30–18:00 | Coordinating agent | Record actual results, source/output hashes, remaining gates and next priority; leave a reviewable local diff. |

The independent reviewer owns the existing browser test ports/builds until the
baseline run finishes. Implementers prepare new files in parallel and wait for
that handoff before changing existing Studio sources or rebuilding shared output.
The Studio pack exercise uses a separate test port. Each implementer owns only
its assigned files; the coordinator owns canonical documentation and integration.
No commit, push, deployment, purchase or external contact is included.

## Finish criteria

1. Independent review records fresh results against the inspected baseline,
   distinguishes skipped/unavailable lanes, and states the exact accepted local
   scope. Any blocking finding stays open; an agent review is not human approval.
2. The same valid input yields byte-identical bounded ZIP output. Every payload
   entry has a declared byte length and SHA-256 in the manifest. ZIP entries use
   fixed safe names, stored bytes, deterministic metadata and valid CRCs;
   independent extraction confirms the inventory and hashes.
3. Original catalog/part bytes and assembly pins are checked. DRC is independently
   recomputed with the stated options; stale or forged reports fail closed.
   A blocked real starter can export a clearly labeled draft without a model;
   supported synthetic sources may include the existing compiler's MJCF/model.
4. BOM pricing preserves unknown counts and distinguishes known subtotal from a
   complete price. CSV cells cannot become spreadsheet formulas. SVG text is
   escaped, reflects only declared nets/endpoints and identifies unresolved
   wiring; neither routing proposals nor a generated diagram imply pin review.
5. Exported rights records distinguish declarations from established reuse rights.
   This slice includes no external meshes, CAD, print-ready files, firmware,
   device credentials, live authority or signed execution evidence. Referenced
   visual assets remain explicitly omitted. All packs are draft, with
   `physicalAcceptance: false` and `executionAuthority: none`.
6. Studio exports only the current accepted DRC/build snapshot. Loading, edits,
   settings, undo/redo, rechecks and disposal invalidate retained export state.
   Export causes no motion/admission/verification request or authoring mutation.
   Actual browser downloads are independently inspected.
7. A source-built verification runner retains input/output hashes, focused
   negative tests, actual exports and browser results. Required affected
   regressions pass, with live-service and optional-database limitations stated.

This is the first draft-design slice of CW-E01/CW-PACK-01. Full package exit,
printable asset support, qualified wiring and any additional format require
their own evidence. No URDF/ROS, MCAP, generic ZIP import, public gallery or
physical provisioning is added to meet today's time box.

## Following priorities and external dependencies

1. Review the CW-E01 draft slice and resolve any acceptance findings. Add real
   owned/licensed print files only when those assets and their rights exist.
2. Prepare CW-L01's curated local gallery/fork flow, preserving source/license
   ancestry and assigning a new unqualified identity to every fork.
3. Continue CW-L02's independent adult-maker exercise and CW-L03 alpha review
   after the export/gallery dependencies are reviewable. January remains an
   authoring/simulation alpha target, subject to evidence.
4. Keep CW-D01 exact board/servo/pin/rail qualification and native M1 independent
   training/export references as explicit blockers. Conditional CW-F01/F02 and
   native M2–M4 cannot be scheduled as afternoon completions without their
   source, fixture, signer and measurement prerequisites.

## Actual delivery record

Implementation, independent review and combined regressions completed on
5 November. Final source-build/evidence inventory verification and this handoff
closed on **6 November (Asia/Bangkok)**. The original afternoon allocation
above is retained as the plan, not represented as an on-time completion record.

All three assignments are complete: the independent reviewer passed the named
CW-G01/CW-G02 local simulation scope and reviewed the CW-E01 implementation;
the exporter agent supplied the deterministic archive/CLI/verification runner;
the Studio agent delivered current-revision downloads and browser acceptance.
Integration found and resolved a pending-DRC/settings invalidation gap using a
generation ticket, with an adversarial Chrome case. No blocking implementation
finding remains for the named offline draft slice.

| Verification | Actual result |
| --- | --- |
| `node tools/robotics/verify-cw-e01.cjs --browser`, rerun 6 November | Passed all five source builds, workspace typechecking, **305 TS tests** (25 exporter + five freshness tests), two deterministic CLI exports, independent Python ZIP/CRC/SHA/source/CSV/XML checks and **nine Chrome groups** |
| Actual Studio pack downloads | Six ZIPs independently checked by the runner; independent reviewer additionally checked the seventh keyboard download. Starter/repeat/keyboard match; synthetic/reference-settings/undo match. No export network request or authoring mutation |
| `node tools/robotics/verify-cw-g02.cjs --browser`, final combined source on 5 November | Passed **111 evidence, 22 trusted API/config, 139 admission/Fast Spine and 49 Rust tests**, 110 agreement records, 82 canonical vectors, full authoring/governed Chrome regressions, nine inspector groups and two independent CLI/native downloaded-bundle checks |
| `bash scripts/host/verify_q2_verification_contracts.sh`, 5 November | Passed available Python/TS/API/alert/benchmark/degraded-edge/telemetry lanes; optional Postgres lane explicitly skipped |
| Authz graph review, 5 November | **79 focused tests passed**; live phase unavailable at `127.0.0.1:8002`, with connection refused. This remains an open live check |
| Final retained evidence audit, 6 November | All **133 CW-G02 source hashes / 919 output hashes** and **135 CW-E01 source hashes / 30 output hashes** match current files; no mismatches |

The canonical source remains `36fceb1` with a reviewable uncommitted diff.
CI now includes the non-browser CW-E01 gate and retains its artifacts; remote
CI has not been executed. No commit, push, deployment or physical action occurred.

Retained evidence:

- `artifacts/robotics/cw-e01/verification.json` and
  `independent-verification.json`: source-built draft-pack acceptance and CLI ZIPs.
- `artifacts/robotics/cw-e01/studio/`: actual browser ZIPs, verification reports
  and visually reviewed desktop/mobile screenshots.
- `artifacts/robotics/cw-g02/verification.json`: final combined evidence gate.
- `artifacts/robotics/cw-g02-exit-review-2026-11-05/`: immutable baseline audit
  and the separate independent CW-E01 review.
- `artifacts/robotics/cw-e01-integration-verification.json`: final source/output
  inventory audit and retained integration-log hashes. The final rerun log is
  outside the reported output directory to keep the inventory stable.

**Next implementation priority:** CW-L01's curated local gallery/fork flow,
preserving source/license ancestry and creating new unqualified fork identities.
CW-L02's independent maker exercise and CW-L03's release review follow their
dependencies. Exact hardware, independent Microduck training outputs, firmware,
qualified wiring/print files, production intake and physical acceptance retain
their existing gates; the completed draft slice does not advance them.
