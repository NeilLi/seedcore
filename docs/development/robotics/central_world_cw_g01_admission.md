# CW-G01: reviewed candidate and policy-input preparation

Date: 2026-10-28
Status: Candidate/preparation slice implemented locally; full CW-AUTH-01/02 live admission, claim/revocation and dispatch acceptance remain open
Review: CW-AUTH-01-PREP (local sub-slice, not a new PDP deny code)

The [active queue](../current_next_steps.md) selects CW-G01 after the
[CW-S04 synthetic gesture/replay slice](central_world_cw_s04_gestures.md).
This afternoon's deliverable freezes the exact supported build, compiled
gesture and requested simulation endpoint, validates a separate service-side
review, and prepares the existing `PolicyCase` for the PDP. It does not close
CW-G01 or advance the queue to CW-G02.

## Browser candidate

[`buildCandidate.ts`](../../../ts/packages/wasm-sim-bridge/src/buildCandidate.ts)
defines `seedcore.cw-g01.candidate.v1`. Mini Studio's **Moments** tab can download
`gesture.cw-g01.candidate.json` after full gesture validation. Enter the intended
`cw_sim://` endpoint identifier; this is an untrusted requested destination,
not a discovered, registered or approved endpoint.

The canonical candidate binds revision, assembly, catalog, full DRC, model and
epoch; gesture/compiler identity; pinned CW-S02 runtime/engine/Wasm; timestep
and position gain; exact duration; and each named joint's analytic full-curve
position, velocity and acceleration bounds plus requested derivative ceilings.
`createCwBuildCandidate` recompiles/checks the gesture and model before every
export. Changing build/gesture/settings invalidates the displayed candidate;
changing the requested endpoint clears it. Undo/redo uses the new current epoch.
The exported object is cloned and recursively frozen.

This is the existing synthetic position profile: one to three joints, at most
five assembly bodies, `dt=0.002`, `kp=1`, at most 120 ticks / 240 ms. Scope remains
`offline_simulation_only`, `physicalAcceptance: false`, `executionAuthority: none`.
The physical starter remains blocked. Export makes no admission/registration
request and adds no signing key, token issuance, hardware path or authority UI.

## Trusted preparation boundary

[`build_admission.py`](../../../src/seedcore/robotics/build_admission.py) accepts
closed candidate JSON, capped at 16 KiB. It rejects duplicate decoded keys,
nonfinite/unsafe numbers, unknown fields, unsupported runtime/physical scopes,
bad digests, invalid duration and duplicate joint inventories. Python uses the
same existing RFC 8785 canonicalization profile as TypeScript.

`prepare_cw_policy_case` requires three independent service inputs:

- `ReviewedSimulationBuild`: an explicitly reviewed candidate pin, endpoint and
  asset/registration/decision/state/policy references, review validity/revocation,
  and separate endpoint/operator per-joint and duration limits.
- `current_binding`: current revision/assembly/catalog/DRC/model/epoch from the
  trusted service's accepted build context.
- `policy_case`: the existing authenticated Agent intake's principal, intent,
  owner delegation, source registrations, policy, approval and telemetry context.

These inputs must never be populated from browser request fields. There is no
auto-approval helper, enrollment endpoint or built-in approved profile. The review
record is not a signed hardware capability profile; its producer must independently
review the original model/gesture compiler inputs. A self-consistent browser hash
alone cannot establish that review. Tests use clearly synthetic service inputs.

Preparation rejects absent, future, expired or revoked review, changed candidate
or current binding, mismatched asset/source-registration/decision/state/provenance/
policy/endpoint context, missing owner delegation context and an already bound
payload/plan. The existing server intent must be current, no longer than five
seconds, and expire within the review window. Its principal and context are
preserved through a deep copy; the browser supplies neither identity nor approval.

Limits intersect **per named joint**, independently of array order. Endpoint,
operator and requested derivative ceilings intersect; endpoint/operator position
envelopes and duration also constrain the actual full curve. Any excluded curve
extremum or duration rejects the candidate. No silent clamping, time stretching
or global minimum across unrelated joints is used. `intersectedLimits` describe
prepared bounds; they are not a policy grant.

The versioned `seedcore.cw-g01.prepared.v1` payload contains the candidate, a digest
of the separate review, and those intersected limits. The existing
`action.parameters.payload_hash` binds the **entire parameters map**, including
retained trusted approval context. `endpoint_id` remains the existing endpoint
binding. Preparation sets `requires_approved_source_registration` for the existing
PDP and preserves all other `PolicyCase` context. It changes no frozen token
constraint/precondition field, PDP rule or deny code and does not mint a token.

## Reproduction and evidence

```bash
# Rebuild sources, check candidate identity/refusals, export fresh compiler data,
# and independently parse/prepare it in Python, including existing PDP denials.
node tools/robotics/verify-cw-g01.cjs

# Also run CW-S04 native parity and full Studio/Chrome regressions, then parse
# the actual browser-downloaded candidate independently in Python.
node tools/robotics/verify-cw-g01.cjs --browser
```

Focused evidence: **20 TS + 54 Python tests**. The dedicated non-browser run
explicitly skips the browser-download test and reports
`checks_passed_browser_not_run`. The browser lane additionally requires the
download/parser check and the actual candidate-only Chrome export group. Its
full Studio regression totals and final status are retained in the generated
reports. Existing ActionIntent and CI gate-alignment regressions passed **42 tests**.

The negative matrix covers all six current bindings, endpoint scope, closed JSON,
rehashed physical/authority/runtime claims, changed review pin, review expiry/
revocation, intent bounds, context mismatch, per-joint inventories and full-curve
limit refusal. Six cases invoke the existing PDP with prepared inputs and assert
its original registration/owner/revocation/staleness denials, with no token minted.
This is not an allow/token/claim/dispatch verification matrix.

`artifacts/robotics/cw-g01/verification.json` retains source/output hashes, actual
lane status, candidate identity and remaining work. `candidate.json` is fresh
compiler output; browser runs add `browser-candidate.json` and
`browser-verification.json`. CI runs the required preparation lane and retains
its reports. These generated artifacts contain no trusted enrollment or authority.

## Next CW-G01 slice

CW-G01 stays the single active integration package. Connect accountable Agent
intake to a trusted registration/profile resolver and independently reviewed
source context; evaluate through the existing live PDP and configured signer;
then verify the token at the actual CW executor adapter. Bind the adapter's
actual command payload to the existing digest fields. The current generic HAL
actuation payload has a different canonical shape and is not wired to this
candidate/prepared payload.

Before claiming live admission, complete durable single-use claim, current
revocation/refresh, deadline and per-substep enforcement plus the expired/future/
forged/replayed/revoked/wrong-endpoint/wrong-profile dispatch matrix. Rejected
requests must dispatch no control, and refresh/heartbeat must not extend intent
or revive a fenced run. No live service deployment or physical endpoint is
configured by this slice. CW-G02 signed evidence and physical qualification retain
their separate gates.
