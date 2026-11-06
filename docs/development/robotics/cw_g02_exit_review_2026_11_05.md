# CW-G01/CW-G02 local simulation exit review — 5 November 2026

Date: 2026-11-05 (Asia/Bangkok)
Reviewer role: independent verification/delivery agent
Baseline: `36fceb120125c6e288e8b28cfd4dfe63aa661b54`
Status: GO for the named local simulation software scope and following offline
CW-E01 work; full package promotion and production/physical gates remain open

This review covers the existing synthetic two-joint native simulation adapter
and known-attempt Studio Evidence Inspector. It does not record human approval,
production promotion, hardware qualification or a physical release decision.
The working tree was clean when the source-built verification started. Concurrent
CW-E01 implementation belongs to a separate package and is outside this review.

## Named supported scope

- Service-owned native MuJoCo 3.15.0 simulation, `dt=0.002`, position `kp=1`,
  at most 120 substeps / 240 ms of simulated time, with the existing admitted
  wall-clock, stall and substep limits unchanged.
- Host-signed evidence from a nonempty known terminal attempt; separately
  retained admission context and explicitly operator-pinned trust/revocation
  snapshot; independent Python and Rust verification.
- Completed capture and the supported nonempty interrupted prefixes
  (`operator_stop` / `service_shutdown`). Other fault captures remain inspectable
  but quarantined.
- Read-only original bundle/context/report downloads and bounded same-attempt
  imports. `physicalAcceptance: false`; evidence inspection grants no execution
  authority.

## Boundary review

The verifier resolves expected context from the service's retained attempt;
uploaded bytes cannot supply expected identity or trusted keys. Configuration v2
pins the original trust-file SHA-256, refuses symlink or group/other-writable
trust files, and retains a bounded snapshot for that service instance. Snapshot
revocation is explicitly not a live lookup.

The service runs both actual verifier implementations, checks their scoped
reports and agreement, and also requires the uploaded SHA-256 to match the
original retained bundle before presenting a verified result. Unknown attempts,
missing context/trust, altered bytes, verifier failure and disagreement fail
closed. Local CLI verification alone does not write RESULT_VERIFIER or clear
runtime quarantine.

The inspection route caps streamed bundles at 2 MiB, requires same-origin JSON,
and runs outside the native execution lock. Rust invocation uses a fixed local
command, bounded input files, a 10-second timeout, bounded report reads and
temporary-directory cleanup. Changing the installed binary requires service
restart. Inspection does not admit, start, stop or refresh an attempt.

The browser validates attempt/instance, revision/epoch, candidate, model,
source/executor and trust identities. Generation fencing and aborts clear
results after edits, undo/redo, settings, new attempts and disposal. Original
report JSON must match its displayed parsed report. Untrusted text uses text
APIs. Static review found no authority widening in these paths.

## Fresh verification

Command: `node tools/robotics/verify-cw-g02.cjs --browser`.

The complete fresh source-built browser command exited **0**, with
`status: checks_passed`, `rust_cw_receipt_adapter: true`, `parity_included: true`
and `studio_browser_verified: true`.

| Fresh lane | Result |
| --- | --- |
| Rust verifier/proof/token/type contracts | 49 passed |
| CW-G02 independent evidence/parity/refusal tests | 111 passed; 82 canonical vectors and 110 retained Python/Rust agreement records |
| Studio trusted API/configuration/failure boundary | 22 passed |
| Admission/Fast Spine regression suite | 139 passed; two browser-specific cases skipped in this invocation and exercised by the later dedicated browser-download invocations |
| Full Studio workspace/authoring regressions | 275 TS, 22 authoring API, 46 Chrome groups and two downloaded-model native checks passed |
| CW-G01 local admission/dispatch | 20 TS, 54 preparation and 39 native/API tests; separate actual-browser candidate parsing and capture-native replay passed |
| CW-G02 actual Chrome inspector/import | Nine groups passed; no page errors; Chrome 156.0.8078.80 |
| Independent actual browser downloads | Completed: 120 substeps; operator-stopped: 27 substeps; both original browser bundles/reports matched both independent CLIs and native replay at `atol=1e-12`, `rtol=0` |

The supported interrupted prefix length is observed output, not a required stop
latency. The separate CW-G01 governed Chrome groups passed, including replay
without new control requests. The retained inspector screenshot was visually
reviewed for readable simulation scope, result and download labels.

An independent integrity check compared all **130 tracked input hashes** in the
fresh CW-G02 report with `git show HEAD:<path>` at the pinned baseline: **zero
differences**. All **919 retained output hashes** matched their recorded SHA-256.
The full fresh output tree, report, baseline source-hash comparison and logs were
copied before later CW-E01 builds into
`artifacts/robotics/cw-g02-exit-review-2026-11-05/`; the machine-readable summary
is `integrity.json`. The copied CW-G02 report SHA-256 is
`34c2f6ea352854e4a84a8b19f115adc5af2fe5dcf90b1c7cd40b69158be7b9ec`.
These are freshly regenerated artifacts; this review does not claim an integrity
audit of yesterday's overwritten output files.

The original runner correctly records `working_tree_dirty: true` as other
agents add separate draft-pack/docs work. Baseline source hashes above match
the commit exactly; passing this baseline does not verify those new changes.
The integration owner must run the affected checks for the final combined diff.

The separate `bash scripts/host/verify_authz_graph_rfc_phases.sh` run passed
**79 focused tests**. Its live phase exited nonzero because
`127.0.0.1:8002/api/v1/pkg/status` refused the connection. That live phase is
**unavailable**, not passed; no service was fabricated to change its outcome.

The broad Q2 verification script is deferred to the integration owner after
concurrent CW-E01 source changes settle, because it typechecks and tests the
whole TypeScript workspace. This review does not claim that run or remote CI.

## Decision and open gates

**GO:** the named CW-G01 local admission and CW-G02 known-attempt Studio evidence
slice satisfies its local software review scope. Proceed with CW-E01's offline
draft design-pack implementation and its own acceptance checks. This agent
review is not human release approval or full CW-G02 package promotion.

The following gates remain separate:

- Production authenticated intake/context refresh, deployment and device/runtime
  qualification.
- Durable historical evidence/context lookup across service restart and general
  historical imports; current inspection is for a retained known attempt.
- Real-source CW-D01 qualification, MCU firmware/configuration/enrollment and
  measured physical stop/capture/recovery acceptance (CW-F01/F02, G1/G2).
- Independent Microduck training/export references, full policy compatibility
  and live native/physical milestones M1–M4.
- Full CW-G02 package promotion, human release review and public publication.

CW-E01 may proceed only as a separately labeled offline draft design pack with
its own deterministic archive, rights/hash, unknown-cost and unresolved-net
acceptance evidence. A pack or signed simulation receipt cannot qualify a
physical build or authorize actuation.

## Separate CW-E01 review of the new working-tree implementation

This section reviews new CW-E01 source and saved browser artifacts after the
baseline review above. It is **not** part of baseline `36fceb1` acceptance and
does not imply that the existing full CW-G02 command tested the new exporter.
The integration coordinator owns the final combined source-built, governance
and documentation checks.

Read-only review covered the pure exporter, Studio controller/DRC integration,
focused tests, browser exercise and verification/export runners. No additional
reviewer build, browser session or authority operation was started. The exporter
recomputes DRC from pinned raw source bytes, uses fixed/generated safe ZIP paths,
bounded STORE entries, original catalog/part retention, CSV formula neutralization
and escaped SVG text. Unsupported/blocked models have an explicit omission;
unpriced costs and all unreviewed nets remain visible. External mesh/CAD/firmware
bytes and rights are explicitly unestablished and omitted.

Review identified a missing settings-generation fence for a DRC response that
resumes after a settings event. The current default DRC transport computes
synchronously, so ordinary user events do not normally interleave there; the
asynchronous acceptance contract nevertheless needed an explicit fence. The
Studio implementer added a dispatch ticket checked by `buildPack.accept`, and
an adversarial same-task settings/DRC browser case. The saved **nine-group
Chrome report** passes, including that case. Review of the change found the
fence correctly rejects the older response while allowing a newer recheck.

An independent read-only inspection of **all seven actual browser ZIPs** passed
CRC, complete payload SHA-256 inventory, canonical assembly/DRC/option binding,
raw catalog/part pins, optional-model identity and omission consistency, and
explicit unresolved-net counts. Four recorded browser source hashes matched
the reviewed working tree. Desktop/mobile screenshots were visually reviewed;
the draft label, download control, unknown-cost status and hardware boundary are
readable and contained.

| Actual browser archives | Observed result |
| --- | --- |
| Starter, repeat and keyboard | Identical 66,548-byte ZIPs; 24 entries; five unpriced component instances; model omitted with `DRC_NOT_READY` |
| Synthetic reference, after settings and undo | Identical 28,908-byte ZIPs; 17 entries; zero unpriced component instances; source-bound offline model included |
| Edited reference | 28,888 bytes; 17 entries; changed assembly binding; model included |

The independently reviewed browser snapshot, seven ZIPs, screenshots, source
pins and `review.json` are retained under
`artifacts/robotics/cw-g02-exit-review-2026-11-05/cw-e01-reviewed-browser/`.
The original browser exercise reports no page errors, network requests caused
by export, mutation/control/verification requests or authoring-state changes.

**Review outcome:** no remaining blocking defect found in this named offline
draft-design slice. Final integration verification remains the coordinator's
gate. Full CW-E01 promotion, printable asset support, reviewed physical wiring,
firmware/provisioning and production/physical qualification remain open.
