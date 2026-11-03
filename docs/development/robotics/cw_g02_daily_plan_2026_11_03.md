# 3 November: CW-G02 Rust verification and Python/Rust parity

Date: 2026-11-03
Status: Rust verification and Python/Rust local parity implemented; Studio/browser and full package acceptance remain open
Owner roles: Trust/verification implementer; integration reviewer
Effort: One afternoon, 13:30–18:00 Asia/Bangkok (UTC+7)

## Inspected baseline

- Local `main` and freshly fetched `origin/main` both resolve to `636fb87`
  (`feat(robotics): add signed simulation evidence foundation`, 2 November).
  The checkout was clean before this planning update.
- Fresh focused checks passed **79 tests**: 70 CW-G02 evidence tests and nine
  existing Fast Spine Python/Rust tests. The full browser/native and Q2 lanes
  were retained 2 November evidence; they were not rerun for this planning audit.
- Retained verification content still matches: CW-G01 **120 input / 10 output**
  hashes and CW-G02 **86 input / 13 output** hashes. Both reports say
  `checks_passed`. Their source-revision field is the pre-commit `994c5e7` with
  a dirty tree; matching content hashes link that evidence to the committed files.
- GitHub's workflow-run query returned no Actions runs for `636fb87`; no remote
  CI pass is established. The local services at ports 8767, 8769 and 8002 were
  stopped when checked. Yesterday's live authz phase was unavailable and its
  optional Postgres lane was skipped.
- The [current queue](../current_next_steps.md) and
  [CW-G02 implementation record](central_world_cw_g02_evidence.md) agree that
  Python signed simulation evidence is delivered, while the Rust CW receipt
  adapter, Studio verification/import surface and full package exit remain open.
  Existing Rust token/Fast Spine verification does not implement the CW bundle
  contract: there is no CW-G02 verifier command/module in the Rust sources.

## Today's single priority deliverable

Implement an **independent Rust verifier for the existing CW-G02 bundle**, with
Python/Rust agreement on accepted outcomes and refusals. The same saved attempt
bundle, independently saved admission context and independently provisioned
trust/revocation snapshot must produce matching scoped dispositions in both
languages. This is the next dependency before exposing verification in Studio.

The supported subset stays the existing synthetic two-joint native profile:
MuJoCo 3.15.0, `dt=0.002`, position `kp=1`, maximum 120 steps / 240 ms, completed
or supported operator/service-stopped prefixes. Fault/fenced outcomes retain
their original evidence and remain quarantined under the current foundation.

Proposed implementation homes:

- An additive CW-specific module/CLI command in `rust/crates/seedcore-verify`.
- Differential fixtures/tests beside `tests/test_cw_g02_evidence.py` and the
  existing Rust CLI tests; a small Python adapter only if required for the
  parity runner.
- Extend `tools/robotics/verify-cw-g02.cjs` to require the new Rust lane and
  retain reports for both implementations. Update the package/queue records
  with actual results and explicit remaining Studio/browser gates.

## Compatibility gate to resolve first

CW-G02 hashes RFC 8785 canonical JSON with the existing safe-number bounds.
The shared Rust proof helper currently sorts object keys and calls
`serde_json::to_vec`; that is not sufficient evidence of RFC 8785 equivalence
for CW's floating-point values and Unicode ordering. The generic Rust JSON
reader also does not itself enforce this bundle's file-size/duplicate-key rules.

Prove canonical bytes/hashes and signature compatibility on retained original
artifacts before implementing the full semantic validator. Use a CW-specific,
bounded canonicalization/parsing path as needed; keep existing global proof
hashing, ExecutionToken fields and Fast Spine schemas stable. Test number
formatting, negative zero, exponent boundaries, safe integers and Unicode key
ordering. Any dependency choice must be pinned and reviewed in Cargo.lock.

## Afternoon schedule

| Time (Asia/Bangkok) | Work | Reviewable result |
| --- | --- | --- |
| 13:30–14:15 | Freeze the additive CLI/report interface; prove bounded JSON/canonical hash and existing signature compatibility | Original artifact hashes and cross-language canonical/signature cases agree; record any blocking mismatch |
| 14:15–15:30 | Add the Rust bundle/context/trust reader and signature/original-artifact validation | A real retained completed/stopped export passes the independent Rust path; untrusted/revoked signatures fail |
| 15:30–16:30 | Implement action/instance/revision/configuration, authorization-window, outcome and sample-coverage checks | Rust enforces the same supported scope and semantic gates as Python |
| 16:30–17:30 | Run a shared positive/adversarial corpus through both implementations; retain differential reports | Matching accepted dispositions and refusal outcomes, including validly signed conflicting evidence |
| 17:30–18:00 | Run affected regressions and contract checks; inspect evidence and update records | Reviewable implementation and verification report with exact remaining gates |

## Finish criteria

1. A real completed bundle produces `verified_completed`; a supported nonempty
   stopped prefix produces `verified_interrupted` in both languages. Their
   `verified`, `disposition`, scope/physical/authority fields and successful
   bundle/context/trust/source digests agree. Diagnostic wording may differ.
2. Both reject missing/wrong expected bindings, reused request/instance/config
   identities, forged/altered/missing artifacts, untrusted/revoked or wrong-purpose
   keys, unsupported hardware claims and unauthorized time windows. Historical
   token expiry at replay time alone must not invalidate a valid captured run.
3. Both quarantine validly signed gapped, duplicated, reordered, truncated,
   nonfinite, wrongly dimensioned or conflicting samples, invalid controls/poses,
   incomplete completion claims and unsupported terminal outcomes. No acceptance
   disagreement is permitted in the shared corpus.
4. The Rust path enforces the same 2 MiB bundle / 256 KiB artifact limits,
   closed schemas, duplicate-key/depth/number rules and independent trust/context
   inputs. It verifies original decoded artifact bytes without rewriting them.
   It performs verification in Rust rather than delegating acceptance to Python.
5. The CLI is read-only. Reports retain source references and exact simulation
   scope with `physicalAcceptance: false` and `executionAuthority: "none"`.
   Verification cannot start/resume motion or clear runtime quarantine.
6. The source-built parity lane and affected token/admission/Fast Spine tests
   pass. Run the applicable governance contract checks and record unavailable
   live/optional lanes accurately. Preserve the original bundles and both
   verifier reports on any mismatch.

At 17:30, stop adding scope and complete verification/documentation. If the
canonicalization or contract gate remains unresolved, retain the reproducer and
report that specific blocker rather than relaxing validation to meet the clock.

Today's task does **not** close full CW-G02/CW-EVID-01. The next slice is Studio's
read-only verification/import surface with actual browser-export evidence.
Production intake/deployment, physical qualification, firmware and real-policy
execution retain separate gates; visual redesign is outside today's task.

## Delivered local slice

The [implementation record](central_world_cw_g02_evidence.md) now documents the
independent Rust `verify-cw-evidence` command, its bounded RFC 8785 reader/writer,
shared report contract and exact supported scope. Python and Rust independently
verify the original bundle/context/trust files; Rust does not call Python.
The CLI is read-only and returns zero for a verified supported outcome, one
for quarantine or an input failure.

The source-built CW-G02 lane passed **111 evidence tests**, **139 existing
admission/Fast Spine tests** (two browser-only cases skipped here), and **49 Rust
verifier/proof/token/type tests**. Both languages pass **82 frozen canonical
vectors**. All **110 retained differential comparisons** agree; three additional
malformed-file CLI groups reject in both. Retained completed/stopped exports
verify, while gapped and revoked-key examples quarantine. The report is
`artifacts/robotics/cw-g02/verification.json`; per-call originals and both reports
remain under `parity/` and `terminal-parity/` in that directory.

The receiver contract now explicitly rejects noncanonical base64 padding bits
and timestamp precision beyond the service's microsecond clock, and requires
strict captured revision bindings and numeric profile fields. Structured JSON
comparisons cannot alias booleans to `0`/`1`. These corrections apply to both receivers;
the existing canonical exporter already emits this subset. Global proof hashing
and ExecutionToken schemas are unchanged. The only new registry dependency is
exactly pinned `ryu-js=0.2.2`, with its checksum in Cargo.lock.

The 36 research/document synchronization tests passed. The authz-graph script
passed 79 focused tests; its live phase remains unavailable at port 8002.
The full Studio/native browser regression passed on the final receiver code:
261 workspace TS tests, 22 authoring API tests, 46 Chrome checks, two downloaded
model native checks, the CW-S04 46 TS / seven native cases, five governed Chrome
groups and independent browser candidate/capture parser/native replay cases.
The Q2 verification script passed its available lanes; the optional Postgres
integration lane was explicitly skipped. Relative Markdown targets resolve,
CI YAML parses, changed Rust files pass formatting checks and `git diff --check`
passes. The retained CW-G01 and CW-G02 report input/output hashes match the
reviewed working tree. These local checks do not assert remote CI acceptance.

Changes are left uncommitted for review. The next implementation slice is
Studio's read-only verification/import surface with actual browser-export
evidence; full CW-G02 and production/physical acceptance remain open.
