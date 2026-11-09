# 9 November: maker-trial readiness and alpha review packet

Date: 2026-11-09
Timezone: Asia/Bangkok (UTC+07:00)
Baseline: `f99479a2` — local gallery and maker lesson; clean at inspection
Status: Software implementation and verification complete; independent maker observation not tested

## Inspection and priority

The latest commit is 6 November's gallery/lesson delivery. CW-L01 has a local
candidate and CW-L02 has an automated synthetic lesson. The next acceptance
evidence is an independent adult maker using it, followed by the CW-L03 release
review. Hardware and Microduck training references retain separate blockers.

Saved CW-L01, CW-E01 and CW-G02 reports all record passing checks. Inspection
on 9 November matched their current inputs and outputs: respectively 132/3,
137/30 and 135/919 hashes, with no mismatches. These are integrity checks of
retained evidence, not new test runs or remote CI results. The last gallery
source-built run recorded 309 workspace tests and seven Chrome groups.

The afternoon's single implementation package is **CW-L02 trial readiness**:
make the committed candidate easy to start, identify and observe without
inventing participant results. Produce a source-bound local review packet that
CW-L03 can consume. This is preparation for the independent trial, not a new
telemetry service or a change to execution authority.

## Afternoon schedule

| Time | Work | Reviewable handoff |
| --- | --- | --- |
| 14:00–14:30 | Freeze candidate and define packet/preflight contract | Exact commit and dirty-state handling; required local dependencies, build files and report inputs; supported local simulation scope |
| 14:30–15:30 | Implement a local trial-packet preparer and startup preflight | Bounded packet containing candidate/source/build hashes, validated verification-report references, launch instructions and a blank versioned observation record. Missing dependencies, stale reports or changed artifacts are explicit failures |
| 15:30–16:15 | Check the actual first-use path and recovery instructions | Verify localhost startup, gallery-to-synthetic-fork lesson, DRC recheck/export, unavailable port/dependency explanations and stop/restart guidance. Preserve existing drafts and unrelated services |
| 16:15–17:00 | Independent adult-maker observation, if a participant is available | Actual browser/device, setup/task times, assistance, keyboard/accessibility, stop/recovery, privacy and downloaded-artifact observations. If unavailable, leave the sheet pending and use the block for packet negative tests and help fixes |
| 17:00–17:40 | Verify affected software and retain exact evidence | Focused packet/preflight negative tests, source-built gallery/browser gate and affected regressions. Record optional/unavailable infrastructure separately |
| 17:40–18:00 | Refresh CW-L03 and canonical queue | Source-bound go/rescope/defer packet, remaining trial findings and support/rollback ownership status. Independent evidence or ownership still missing means DEFER |

These are implementation time boxes, not promises that a human trial or release
decision will finish by 18:00. Complete reviewable preparation even when those
external inputs remain unavailable.

## Proposed implementation surfaces

- New local tooling under `scripts/robotics/` or `tools/robotics/` for preflight
  and trial-packet preparation; reuse existing launch and verification commands.
- Focused tests for changed/missing files, stale source/report hashes, incomplete
  observation records and safe output behavior.
- The existing lesson/help and alpha-review documents. Correct the alpha record's
  old `4ae171c + uncommitted diff` description to the selected committed candidate
  and explicitly identify any later implementation diff.
- `deploy/local/README.md` and the active queue for exact user-facing commands
  and the final handoff. Avoid adding instrumentation to the Studio unless an
  observed task problem requires it.

## Finish criteria

1. The packet identifies the exact candidate revision, code/build hashes,
   supported scope, verified report inputs and artifact references. A passing
   report from changed source cannot be silently reused. An unbuilt candidate
   is distinguished from an accepted build.
2. Preflight explains missing Python/Node/native/browser dependencies, absent
   Studio build and occupied ports. It does not install packages, kill unrelated
   processes, rewrite drafts or create service signing configuration implicitly.
3. Observation fields start pending. Automated smoke-test results remain distinct
   from human observations; starting a timer or exporting a file cannot mark a
   task complete. Do not include participant names, credentials or private data.
4. The operator can follow the existing six-step synthetic lesson, recheck DRC
   after preset changes and keep a source-bound export. Help distinguishes
   unsigned rehearsal capture from separately configured signed evidence.
5. Exact local restart/revert instructions are recorded without destructive git
   operations. Named support/rollback ownership stays unassigned until provided;
   do not invent an owner or treat the packet as release approval.
6. The affected verification passes and the queue records actual completed work,
   skipped/unavailable lanes and the next unresolved gate. No commit, push,
   deployment or publication is included in this planning task.

## Following priorities

After an actual maker trial, fix observed blockers and rerun affected checks;
then review CW-L03 with exact release artifacts and real support/rollback
ownership. Keep CW-D01's exact board/servo/connector/rail qualification and M1's
independent training/export references as supporting work. Firmware/installers,
physical motion and public gallery expansion remain dependent on their gates.

## Execution record

The source-built gallery gate passes 309 workspace tests, 29 packet/preflight
tests and seven Chrome groups. Its report now also hashes the actual Studio
build outputs. The packet tool provides `preflight`, `prepare` and `verify`;
generated observations remain pending and release decisions remain deferred.
The available Q2 lanes passed; optional Postgres was skipped. Authz passed 79
focused checks but could not connect to its live service on port 8002.

The operator arranged a participant immediately. The source-bound packet is
`artifacts/robotics/cw-l02-trials/2026-11-09-participant-01/`; the Studio was
started by the assistant at `http://127.0.0.1:8767`. Setup must therefore be
recorded as assisted if that session is used. The operator subsequently reported
**not tested** and requested implementation continue. No participant timing,
browser/device, task completion or assistance result is inferred. The owned
server was stopped gracefully before the final source-built rerun; browser
storage and unrelated services were not changed.

Separate-port startup/restart probes started and stopped the owned server twice
without interrupting an occupied listener. The final immediate free-port probe
exposed a TIME_WAIT false refusal; an isolated socket reproducer confirms the
cause. The fix uses the same address-reuse behavior as the local server and
also checks listening availability, retaining refusal for an active listener.
All 29 focused checks pass, including this regression and malformed/deep JSON
refusals. The final automated startup gate passes five groups: preflight, packet
preparation, two owned-server starts with occupied-port refusal and graceful stop,
and immediate post-stop readiness. Its measured startup probes (0.862 s and
0.751 s) are automated environment measurements, not human setup times. No human
observation or release approval is inferred from those results.

## Final handoff

- `scripts/robotics/prepare_maker_trial.py` provides read-only `preflight`, safe
  new-directory `prepare`, and current-checkout `verify` commands. The packet
  binds revision, dirty state, source/build/report and preparation-input hashes;
  it references the checkout rather than distributing an app binary.
- The gallery runner now records the complete Studio build inventory and runs
  the 29 Python tests in addition to its 309 TS tests and seven Chrome groups.
- `tools/robotics/verify-cw-l02-trial.py` exercises actual startup/restart and
  verifies that an occupied listener is left running. Its report is
  `artifacts/robotics/cw-l02/verification.json`.
- The fresh user-facing packet is
  `artifacts/robotics/cw-l02-trials/2026-11-09-ready-02/`. The earlier
  participant-01 packet is superseded following the tooling fix and operator's
  **not tested** report; no observation was promoted to completed.
- Launch, recovery and separate-checkout rollback instructions are in
  `deploy/local/README.md` and the packet README. Support/rollback owners remain
  unassigned, and CW-L03 remains DEFER pending real evidence and human review.
- Final integrity and integration results are recorded in
  `artifacts/robotics/cw-l02-integration-verification.json`. Optional Postgres and
  unavailable live authz remain explicitly separate from passing local checks.

Implementation changes are uncommitted. No deployment, public publication,
hardware operation or signing configuration was performed. Next: conduct the
independent maker exercise with the fresh packet, resolve observed issues and
review the exact candidate with actual support/rollback ownership.
