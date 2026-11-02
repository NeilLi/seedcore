# 2 November: CW-G02 signed simulation evidence foundation

Date: 2026-11-02
Status: Bounded Python foundation implemented locally; full CW-G02 package acceptance remains open
Owner roles: Trust/verification implementer; integration reviewer
Effort: One afternoon, 13:45–18:00 Asia/Bangkok (UTC+7)

## Inspected baseline

- Local `main` is `994c5e7` (29 October). A successful 2 November fetch shows it
  two commits ahead of `origin/main`, with no commits behind. The working tree
  was clean before this planning update.
- The [canonical queue](../current_next_steps.md) still requires review of the
  [CW-G01 local adapter](central_world_cw_g01_admission.md) before promotion.
  The delivered scope is one synthetic, service-owned native MuJoCo profile:
  actual PDP, configured Ed25519 token signing, Rust token verification,
  durable claims, bounded execution/stop gates and captured 3D replay.
- Fresh focused verification: `tests/test_cw_g01_runtime.py` plus
  `tests/test_cw_g01_admission.py` passed **93 tests**, with **two browser-only
  tests skipped**. `tests/test_fast_spine_rust.py` passed **nine tests**.
- All **119 input hashes and 10 output hashes** in the retained
  `artifacts/robotics/cw-g01/verification.json` matched before this update.
  That report records the pre-commit parent `2bfaa92` and a dirty working tree;
  the matching content hashes establish its relationship to the current files.
  The full Chrome/native suite was retained evidence, not rerun today.
- Services on `127.0.0.1:8767`, `:8769` and `:8002` did not respond during
  inspection. Availability and live-phase acceptance are not established.
- `CwSimulationService.capture()` currently exports
  `seedcore.cw-g01.capture.v1` with `signed: false`. Its digest checks content
  integrity but does not establish authenticated evidence closure.

The [28 October–3 November tactical window](../current_next_steps.md#first-30-day-work-packages)
includes minimum M3 evidence work. This task advances that local simulation
lane. Production intake/deployment, CW-D01 physical qualification and CW-S03
real-policy execution retain their separate open gates.

## Today's single deliverable

Produce an exportable, host-signed **local simulation attempt bundle**, with
an independent offline Python verifier and retained positive/negative fixtures.
Support the existing pinned CW-G01 two-joint native profile only, preserving
`dt=0.002`, `kp=1` and the 120-substep / 240 ms ceiling.

The useful result is: an operator can export one completed or stopped attempt
and inspect whether its signed evidence matches independently expected context.
The verifier reports the observed outcome and simulation scope; signing does
not prove task success or physical safety.

Reuse the existing signed-artifact envelope and Ed25519/trust conventions where
compatible. The Fast Spine Python and Rust receipt validators require their own
`spine_sim://` profile/session schema; they do not already verify CW-G01 captures.
Freeze an additive versioned CW evidence contract before implementation. Keep
the frozen ExecutionToken fields and existing Fast Spine schemas intact.

## Afternoon schedule

| Time (Asia/Bangkok) | Work | Reviewable result |
| --- | --- | --- |
| 13:45–14:15 | Review the named CW-G01 baseline; freeze the additive evidence contract, signer configuration and independently expected bindings | Written contract and refusal matrix; unresolved authority or binding issues stop promotion |
| 14:15–15:30 | Retain original artifacts and seal a terminal attempt with an explicitly configured host receipt signer | Bundle containing original token, candidate/model/source/executor references, capture and signed terminal manifest; immutable repeated export |
| 15:30–16:45 | Add a read-only Python verifier and CLI using separately supplied expected context and trust/revocation inputs | Completed, interrupted or quarantine report with source references and `physicalAcceptance: false` |
| 16:45–17:30 | Exercise completed/stopped exports and adversarial fixtures; rerun affected admission and receipt regressions | Reproducible test results and exported fixtures; original artifacts retained on verification failure |
| 17:30–18:00 | Inspect the evidence, document actual coverage and record remaining gates | Reviewable diff and evidence record; unfinished items carried forward explicitly |

## Acceptance criteria

1. Bind the receipt to the original token hash, intent/token/request IDs,
   endpoint and service-instance identity, candidate/revision/epoch, model,
   source, executor/configuration, timestep, capture digest and terminal outcome.
   Retain host-observed start/end times and check execution against the admitted
   token/review window. Identify which independently supplied expected record
   establishes each binding; host timing is a signed simulation claim.
2. Preserve the original signed token and original capture bytes/artifacts.
   A public key included in an export is provenance material, not a trusted key
   merely because the export supplies it. Never export private keys.
3. Use an explicit host-simulation receipt signing configuration with no automatic
   production key generation or unsigned success fallback. Fixture keys remain
   test-only. A sealing failure is an evidence failure, not execution completion.
4. The verifier consumes immutable files plus separately supplied expected context
   and trusted/revoked keys. It cannot admit, start, resume, mutate or clear a
   quarantined execution. Record the trust/revocation snapshot used for replay;
   token expiry at verification time alone must not invalidate a historical run.
5. Reject or quarantine tampered signatures/content, unknown or revoked signers,
   wrong action/endpoint/instance/model/source/executor bindings, duplicate,
   reordered, gapped or non-finite samples, inconsistent tick/time/count coverage,
   and an interrupted capture relabeled as completed. Completion requires all
   120 expected substeps; an interrupted run needs an intact prefix and matching
   signed terminal reason. Empty or unsupported outcomes cannot pass as completion.
6. Every result retains the exact simulation scope, original source references
   and `physicalAcceptance: false`. Host-signed samples cannot be represented as
   device telemetry. Receipt verification grants no new execution authority.

## Cutoff and following work

At 17:30, stop expanding scope and verify the implemented subset. If the
contract or trust bindings cannot be resolved, retain the contract/refusal
fixtures and report the implementation blocked at that specific gate.

The [implementation record](central_world_cw_g02_evidence.md) describes the
delivered contracts, API/CLI, explicit configuration and retained evidence.
This is the **CW-G02 foundation**, not full CW-EVID-01 acceptance. The following
slice must add an additive Rust verifier with Python/Rust disposition parity,
Studio's read-only verification/import surface, and real browser-export coverage
before claiming the [CW-G02 package exit](central_world_remaining_delivery_schedule.md).
Visual redesign, longer gestures, new models, hardware enrollment and real-policy
execution are outside today's bounded deliverable.

## Completion evidence

The bounded foundation is implemented locally and left uncommitted for review.
The [implementation record](central_world_cw_g02_evidence.md) contains the contract,
configuration, API and CLI instructions. Local verification on 2 November:

| Check | Actual result |
| --- | --- |
| `node tools/robotics/verify-cw-g02.cjs` | `checks_passed`: 70 new evidence tests and 139 existing admission/Fast Spine regression tests; two browser-only cases skipped in this lane |
| Retained foundation fixtures | Actual PDP/native completed and stopped bundles verify; validly signed gapped samples and revoked receipt keys quarantine; original files and public test trust retained |
| `node tools/robotics/verify-cw-g01.cjs --browser` | `checks_passed`: 20 focused TS, 54 preparation, 39 native/PDP/API, CW-S04 46 TS + 7 native; full Studio 261 TS + 22 API + 46 Chrome + 2 downloaded-model native checks; five governed Chrome groups plus independent browser candidate/capture parser and native replay cases |
| Research/document synchronization | 36 tests passed |
| Authz-graph script | 79 focused tests passed; separate live phase unavailable because port 8002 was not running |
| Q2 verification script | Available lanes passed; optional Postgres integration lane explicitly skipped |
| Documentation/CI checks | Relative Markdown targets resolve, workflow YAML parses, `git diff --check` passes |

The retained reports are `artifacts/robotics/cw-g02/verification.json` and
`artifacts/robotics/cw-g01/verification.json`. Their source/output hashes were
checked against the reviewed working tree. Fixtures use temporary test-only
signers/context and do not establish production or hardware acceptance. The
full browser pass above protects the existing CW-G01/Studio workflow; it is not
a claim that the pending CW-G02 verification/import UI has been delivered.

The single next implementation slice is the additive Rust CW receipt verifier
with Python/Rust refusal parity, followed by the read-only Studio verification
surface and its browser-export evidence. Production, physical and real-policy
gates remain separate.
