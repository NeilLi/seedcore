# CW-G01: scoped local admission, native execution and captured replay

Date: 2026-10-29
Status: Local synthetic endpoint candidate implemented; production authenticated intake/deployment, signed evidence and physical qualification remain open
Review: CW-AUTH-01-02-LOCAL (local acceptance reference, not a new PDP deny code)

The [active queue](../current_next_steps.md) selects CW-G01 after the
[CW-S04 synthetic gesture/replay slice](central_world_cw_s04_gestures.md).
The 28 October preparation deliverable freezes the exact supported build, compiled
gesture and requested simulation endpoint, validates a separate service-side
review, and prepares the existing `PolicyCase` for the PDP. It does not close
CW-G01 on its own. The 29 October local endpoint adapter is recorded below;
broader production qualification remains separate.

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

## 29 October: service-owned local simulation adapter

[`cw_simulation.py`](../../../src/seedcore/robotics/cw_simulation.py) now owns
native MuJoCo `MjModel`/`MjData` for one explicitly configured synthetic endpoint.
The browser sends a candidate and start/stop requests; it cannot supply XML,
controls, a principal, owner delegation, approval context, signer or registry.
This endpoint never calls generic HAL, serial, hardware RPC or an external actuator.

The opt-in service loads a separately pinned `endpoint-source.json`, a server-side
`ReviewedSimulationBuild`/`PolicyCase`, an Ed25519 key and a durable claim-store
path. The source exporter writes the exact reviewed two-joint reference model,
compiled gesture and 120 control frames. Startup checks the source hash, fixed
model digest, compiled gesture/frames, scope, native engine/version/mapping and
review pin. Normal Studio startup has **no configured endpoint or generated key**.
The private configuration separately pins `executorDigest`: the native adapter,
ingress, signer, claim/PDP/enforcement source image and its declared engine/clocks.
The review's state hash binds both source and executor digests. The actual native
executor descriptor is added to the versioned prepared payload before its whole
parameters hash is signed. A code/clock-profile change therefore requires a
matching service review; the browser compiler's Wasm profile is not silently
treated as the native executor identity.
The registered source permits only the exact reference semantics. Browser-local
revision/epoch may be rebound after content/behavior comparison; changing the
build, curve, gesture name, runtime or endpoint cannot self-enroll a new profile.

The service prepares the existing `PolicyCase`, then calls the actual
`governance.evaluate_intent`. A new **trusted service dependency** `token_minter`
selects the configured signer only after policy allow. It is not an ActionIntent
or HTTP field. `_mint_execution_token` requires the signer to preserve every
approved claim; explicit signer failure has no fixture fallback. The existing
default mint path and frozen constraint/precondition fields remain unchanged.
The configured CW signer emits Ed25519 tokens in the existing `ExecutionToken`
shape. Debug signatures are refused by the governed endpoint.

Admission/start verify the signature through the existing Rust verifier with
explicit public trust material and enforce the independent prepared request
through Rust token-core. The adapter additionally checks future issuance,
intent/profile/window identity and exact token/binding equality. The Python Rust
enforcement bridge now preserves subsecond timestamps rather than rounding down.
Start durably claims both token and request once in the existing SQLite
`ClaimStore`; interruption never releases that claim. Replay across a service
restart is refused. Pending admission/start can be cancelled without a late
response reviving the attempt.

The state-owning executor checks current token/key revocation, immutable deadline,
review expiry, wall/monotonic rollback, pacing, state/warmstart and timestep before
each `mj_step`, including a final authority check after control preparation.
Unexpected external forces and controls are zeroed/countable; foreign state,
policy/model switch, overflow, invalid control or unavailable authority fence
the attempt. Controls come only from the pinned immutable schedule.
Stop is latched, zeroes controls and prevents further steps. Status/capture reads
and browser refreshes neither dispatch controls nor extend the lease.

The named profile is `seedcore.cw-g01.native-admission.v1`: MuJoCo 3.15.0,
`dt=0.002`, position `kp=1`, 120 simulation ticks / 240 ms, at most eight substeps
per batch, 250 ms pacing/stall ceiling, and an immutable wall deadline of at most
one second, additionally bounded by token/review expiry. This is a localhost
synthetic profile, not a measured physical stop guarantee or a device-wide runtime
qualification. Captured target bounds do not establish observed tracking bounds.

## Studio flow and display-only 3D replay

After loading the synthetic reference, applying the position rehearsal preset
and compiling the exact example in **Moments**, a configured service exposes
**Request admission → Start admitted simulation → Stop governed attempt**.
The UI distinguishes checking, denied, admitted, starting, running and terminal
outcomes. Default/unconfigured startup keeps these controls unavailable; the
existing offline CW-S02/CW-S04 rehearsal remains separate.

Terminal native captures have their own `seedcore.cw-g01.capture.v1` scope and
digest. They are explicitly **unsigned simulation records**. The client checks
current candidate/binding, control targets, contiguous coverage, scope and digest.
It can scrub numeric targets/observations and show captured body poses in 3D.
Body poses are native FK on a separate `MjData` from captured `qpos`; display
never injects/reset solver state, mutates the assembly or sends controls.
The viewport labels captured versus rest pose, restores rest pose after edits or
placement selection, and fits the model to both camera dimensions. Desktop
inspector scrolling keeps the canvas height bounded; heavy assets/effects are
not introduced. The tiny 0.001 rad example and 240 ms qualified budget are unchanged.

## Configuration, verification and remaining gates

The normal service accepts explicit private configuration only:

```bash
.venv/bin/python scripts/robotics/serve_mini_studio.py --port 8767 \
  --admission-config /private/path/service-config.json
```

`seedcore.cw-g01.service-config.v1` contains `sourcePath`, `sourceSha256`, `executorDigest`, `review`,
`policyCase`, `signingKeyPath`, `keyRef`, and `claimStorePath`. Configuration/key
files must be private regular files (0600); symlinks, invalid pins and unsupported
keys reject. There is no automatic production identity, registration or profile
approval. The supplied server context must come from the operator's trusted
intake/registration path. This local adapter does not authenticate external users
or replace the Agent Action Gateway. Production context-refresh/ingress and
deployment qualification remain open.

For an isolated inspection fixture, the explicit test launcher creates temporary
keys, synthetic registration/delegation context and a local claim store:

```bash
.venv/bin/python tools/robotics/serve-cw-g01-test.py --port 8771 \
  --source artifacts/robotics/cw-g01/endpoint-source.json
```

That launcher is test-only, is never imported by normal startup, and represents
neither production identity nor hardware enrollment. The real PDP code, configured
signature path and Rust/native checks execute without mocked allow decisions.

`verify-cw-g01.cjs` now builds the Rust verifier and requires **39 native/PDP/API
tests**, alongside the existing **20 TS + 54 preparation tests**. The two
browser-only parser/parity cases are explicitly skipped without `--browser`.
The browser lane also runs the full Studio/CW-S04 regressions, **five governed
Chrome groups**, and independently replays the actual downloaded native capture
at `atol=1e-12`, `rtol=0`. Reports retain source/output hashes, included lanes,
native clock profile and explicit production/hardware exclusions. CI requires
the native local-admission lane and retains its source/capture reports.

Broader governance evidence on this work: the Q2 verification script passed its
available lanes, with the opt-in RESULT_VERIFIER Postgres lane explicitly skipped.
The authz-graph script passed **79 focused tests**; its separate live phase was
unavailable because `127.0.0.1:8002` was not running. No live-phase pass is claimed.

The local adapter still needs review under its named scope before promotion.
CW-G02's next evidence work must retain original artifacts and independently
verify signed closure/provenance; a local unsigned capture is not that proof.
Production authenticated intake/context synchronization, other models/gestures,
physical sources/profiles and hardware gates remain open.

## 2 November: additive signed simulation evidence foundation

The [CW-G02 Python foundation](central_world_cw_g02_evidence.md) now seals
original CW-G01 capture/token/source artifacts in an explicitly configured
host-signed simulation bundle. The original capture remains unsigned and keeps
its existing schema. Admission can return a separately saved evidence context
with a fresh service-instance identity; receipt signing is opt-in under a new
private configuration version. The native executor review digest now includes
the evidence module. Existing review pins must be refreshed through review,
not bypassed. The 3 November CW-G02 slice now independently verifies these
bundles in Python and Rust with matching refusal evidence. Studio/browser
acceptance and broader CW-G01 production/physical gates remain open.
