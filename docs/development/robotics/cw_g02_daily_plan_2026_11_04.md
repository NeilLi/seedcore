# 4 November: CW-G02 Studio Evidence Inspector

Date: 2026-11-04
Status: Known-attempt Studio inspection implemented locally; package promotion and broader qualification remain open
Owner roles: Studio/trust implementer; verification reviewer
Effort: One afternoon, 14:45–18:00 Asia/Bangkok (UTC+7)

## Inspected baseline

- Local `main` and freshly fetched `origin/main` both resolve to `8c02c95`
  (`feat(robotics): add independent Rust CW evidence verification`, 3 November).
  The checkout was clean before this planning update.
- Fresh focused verification passed **111 CW-G02 tests**, with the Rust parity
  flag enabled. The broader 139 admission/Fast Spine and 49 Rust contract tests,
  110 retained comparisons, 82 canonical vectors and full browser/Q2 results
  are retained 3 November evidence, not fresh runs from this planning audit.
- Both retained reports remain `checks_passed` and match all content hashes:
  CW-G01 **122 input / 10 output**, CW-G02 **90 input / 897 output**. Their
  pre-commit revision field is `636fb87` with a dirty tree; the content hashes
  establish the connection to the committed implementation.
- GitHub's workflow query reported no Actions runs for `8c02c95`; remote CI
  acceptance is not established. Services on ports 8767, 8769 and 8002 were
  stopped when checked. Prior live authz/Postgres availability remains separate.
- The [canonical queue](../current_next_steps.md) and
  [CW-G02 record](central_world_cw_g02_evidence.md) select the Studio/operator
  surface next. `governed.ts` currently downloads only the unsigned
  `seedcore.cw-g01.capture.v1` record; `index.html` has no signed-evidence inspector.
  The backend already exports signed bundles and both offline verifiers exist,
  but there is no browser verification route. The current request helper also
  caps responses at 256 KiB, while a CW-G02 bundle may be up to 2 MiB.

## Today's single priority deliverable

Add a **read-only Evidence Inspector in Mini Studio's Moments workflow** for
the configured service's known terminal simulation attempt. A maker should be
able to run or stop an admitted attempt, verify its signed evidence in Python
and Rust, inspect the exact outcome/scope/bindings, and download the original
bundle and both reports from the browser.

Include bounded import/re-verification of a bundle for that same known attempt.
The service must resolve independently retained admission context and explicitly
operator-configured public trust/revocation inputs. Browser-uploaded bundle
contents cannot establish trusted context or trusted keys. An unknown attempt,
another service instance, absent trust configuration or mismatched context must
fail closed with an actionable explanation. General historical context lookup
and a durable evidence registry remain later work.

Supported execution remains the existing synthetic two-joint native profile:
MuJoCo 3.15.0, `dt=0.002`, `kp=1`, maximum 120 steps / 240 ms. The inspector
does not change those bounds or add an execution request during verification.

## Afternoon schedule

| Time (Asia/Bangkok) | Work | Reviewable result |
| --- | --- | --- |
| 14:45–15:30 | Freeze the verification response/trust boundary and add a bounded read-only service adapter | Original bytes + server-retained expected context + explicitly configured trust produce both verifier reports; absent inputs and disagreements fail closed |
| 15:30–16:30 | Add the Moments evidence inspector, signed bundle/report downloads and same-attempt import | Exact scoped outcome and source/trust/binding summaries; bounded file/response reads; verification cannot mutate or dispatch |
| 16:30–17:30 | Add focused API and real Chrome evidence cases | Completed/stopped downloads verify independently; tampering, wrong bindings/keys, oversized files and delayed/stale UI results are refused |
| 17:30–18:00 | Run affected source-built regressions and inspect retained evidence | Reviewable diff, actual browser exports, verifier reports and updated queue/acceptance record |

## Finish criteria

1. Backend verification uses the actual existing Python and Rust implementations
   with fixed executable/arguments, bounded inputs/runtime and cleanup. Trusted
   expected context/key snapshots come from the operator/service boundary and
   are never extracted as trust from the uploaded bundle. Any new configuration
   is explicit, versioned and optional; existing unsigned-only startup remains
   usable with verification controls visibly unavailable.
2. Show `verified_completed`, `verified_interrupted`, `quarantine`, unavailable
   or verifier-disagreement states with plain explanations. Display local
   simulation scope, `physicalAcceptance: false`, request/instance/model and
   source/executor identities, executed/expected sample coverage and trust
   snapshot digest. A UI badge cannot imply physical safety or grant authority.
3. Downloads preserve the exact signed bundle bytes and both original verifier
   reports. The original unsigned capture retains its existing label. Import
   checks the 2 MiB limit before/while reading and retains original bytes for
   inspection on refusal. Import does not replace the assembly, change admission
   or inject state into a running solver or the authoring store.
4. Verification/import replies are fenced by request/instance, current candidate
   and revision/epoch, plus a generation counter. Draft/gesture/settings changes,
   undo/redo, a new attempt and disposal clear stale results. Delayed responses
   cannot restore an old verified badge or enable stale exports. Display
   untrusted text with safe text APIs.
5. API tests cover missing trust/context, malformed/oversized imports, mismatched
   bindings, bad/revoked keys, verifier failure/disagreement and read-only
   behavior. Real Chrome downloads one completed and one supported interrupted
   attempt; independently run both CLIs on the actual downloaded bytes and
   retain matching reports. Browser tests also exercise tampered import and a
   delayed verification/edit race, with no control requests or store mutation
   caused by verification/replay/import.
6. The existing CW-G02 source-built parity lane and affected Studio/browser and
   governance checks pass. Record actual results, skipped/unavailable lanes,
   source/output hashes and the exact supported operator subset.

At 17:30, stop expanding scope and finish verification/records. If a trusted
context/key source cannot be established, leave verification unavailable and
retain the blocker; do not add a browser self-trust shortcut to meet the clock.

This closes only the named local Studio slice after its evidence passes. Full
CW-G02/CW-EVID-01 promotion still requires review against the acceptance matrix.
Production intake/deployment, physical qualification, firmware, real-policy
execution, general historical import and visual redesign are outside today's
bounded task.

## Delivery record

The [implementation record](central_world_cw_g02_evidence.md) documents the
new optional operator configuration, paired verification API and inspector.
The original known bundle is pinned independently of the uploaded bytes;
the browser cannot supply trusted context or trusted keys. Both verifier JSON
reports and original inspected bytes are retained on refusal. Unknown attempts
remain unavailable; imported data does not replace the authoring or solver state.

The slice passes **14 focused TS checks**, **22 trusted API/config checks** and
**nine real Chrome groups**. Actual completed and stopped browser downloads
match both independently executed CLIs and native MuJoCo replay at `atol=1e-12`,
`rtol=0`. Tests cover corrupted/oversized/wrong-attempt imports, bad/revoked
keys, missing trust/context, verifier failure/disagreement, safe text rendering,
mobile containment and a delayed verification/edit race. No control request or
store mutation is caused by verification/import.

The existing 111 evidence, 139 admission/Fast Spine and 49 Rust tests remain
required, with 110 agreement records and 82 canonical vectors. Full Studio
regressions include 275 TS / 22 authoring API / 46 Chrome / two downloaded-model
native checks plus the existing governed Chrome/native cases.

The Q2 script passed available lanes with its optional Postgres lane skipped.
The authz-graph script passed 79 focused tests; its live phase remains
unavailable at port 8002. Research/doc synchronization passed 36 tests.
These local results do not establish a remote CI pass. Reports, browser exports,
independent inputs/results and a screenshot are retained under
`artifacts/robotics/cw-g02/studio/` and the parent verification report records
source/output hashes and included lanes.

Review this named local CW-G02 slice
before package promotion and selection of the following CW-E01 design-pack
work; broader production, physical and historical-registry gates stay separate.
