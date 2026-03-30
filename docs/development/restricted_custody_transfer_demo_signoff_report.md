# Restricted Custody Transfer Demo Sign-Off Report

Date: 2026-03-30

## Scope

This report signs off the current SeedCore demo wedge for one workflow only:

- `Restricted Custody Transfer`
- one sealed high-value lot handoff
- one canonical artifact chain from approval through offline verification
- one runtime truth table across `allow`, `deny`, `quarantine`, and `escalate`

This is a concrete engineering sign-off report, not a roadmap note. It only
claims what was verified in the repository and local environment on 2026-03-30.

## Decision

Current sign-off status: `CONDITIONAL PASS`

Meaning:

- `PASS` for offline contract fidelity, persisted-approval runtime enforcement, fixture verification, TS build, and targeted Python runtime and proof tests
- `READY` for a controlled engineering demo grounded in the current artifact chain
- `NOT YET SIGNED OFF` for a full live-runtime demo claim involving hot-path shadow evidence and running proof surfaces

The honest reading is:

- the demo story is now credible and concretely backed by repo evidence
- the repo is not yet fully signed off for a live environment walkthrough until the runtime and verification services are actually exercised end to end

## What Is Signed Off Now

| Area | Status | Evidence |
| :--- | :--- | :--- |
| Phase 0 contract freeze | `PASS` | `python scripts/tools/verify_phase0_contract_freeze.py` |
| TypeScript workspace build | `PASS` | `npm --prefix ts run build` |
| Persisted approval authority boundary | `PASS` | RCT now fails closed without authoritative approval state and hot-path evaluation resolves persisted approvals before policy evaluation |
| Targeted runtime and proof tests | `PASS` | `52 passed, 21 deselected` from the canonical RCT-focused pytest slice |
| Offline verifier happy path | `PASS` | `seedcore-verify` validated `allow_case` with `business_state=verified` and execution token present |
| Offline verifier missing approval | `PASS` | `seedcore-verify` validated `deny_missing_approval` with `business_state=rejected` and `missing_dual_approval` |
| Offline verifier stale telemetry | `PASS` | `seedcore-verify` validated `quarantine_stale_telemetry` with `business_state=quarantined` and trust gaps present |
| Offline verifier break-glass | `PASS` | `seedcore-verify` validated `escalate_break_glass` with `business_state=review_required` and `human_review` obligation |

## Evidence Run

### 1. Contract Freeze Gate

Command:

```bash
python scripts/tools/verify_phase0_contract_freeze.py
```

Result:

- `PASS`
- validated docs, Rust kernel types, TS trust contracts, and restricted custody fixture scenarios

### 2. TypeScript Build

Command:

```bash
npm --prefix ts run build
```

Result:

- `PASS`
- contracts, operator console, proof surface, verification console, and verification API compiled successfully

### 3. Targeted Python Runtime and Proof Tests

Command:

```bash
pytest -q \
  tests/test_pdp_hot_path_router.py \
  tests/test_transfer_approvals_router.py \
  tests/test_verify_rct_hot_path_shadow.py \
  tests/test_replay_service.py \
  tests/test_replay_router.py \
  tests/test_authz_parity_service.py \
  tests/test_action_intent.py \
  -k 'transfer or governance or approval or hot_path or replay or parity'
```

Result:

- `52 passed, 21 deselected`
- the current RCT wedge has coverage on approval handling, transfer-approval persistence APIs, replay/proof projection, parity reporting, hot-path approval resolution, and transfer evaluation behavior

### 3a. Approval Authority Boundary

Verified repo state:

- Restricted Custody Transfer no longer trusts embedded `approval_context.approval_envelope` or embedded approval transition payloads as authoritative input
- `/api/v1/pdp/hot-path/evaluate` resolves persisted transfer approvals and transition history before policy evaluation
- `verify_rct_hot_path_shadow.py` now persists fixture approval envelopes through `/transfer-approvals` and emits valid `HotPathEvaluateRequest` payloads
- `verify_productized_surface.sh` now fails closed when no runtime `audit_id` is available

### 4. Offline Verifier Matrix

Command:

```bash
cd rust
for case in allow_case deny_missing_approval quarantine_stale_telemetry escalate_break_glass; do
  echo "CASE:$case"
  cargo run -q -p seedcore-verify -- summarize-transfer --dir fixtures/transfers/$case
  cargo run -q -p seedcore-verify -- verify-transfer --dir fixtures/transfers/$case
done
```

Result:

- `allow_case`: `verified=true`, `business_state=verified`, `disposition=allow`
- `deny_missing_approval`: `verified=true`, `business_state=rejected`, `disposition=deny`
- `quarantine_stale_telemetry`: `verified=true`, `business_state=quarantined`, `disposition=quarantine`
- `escalate_break_glass`: `verified=true`, `business_state=review_required`, `disposition=escalate`

Note:

- fixture policy snapshot refs such as `snapshot:pkg-prod-2026-04-02` are fixture identifiers, not the date this report was produced

## What This Means

The current repository can honestly support a concrete demo claim that SeedCore
can:

- bind `TransferApprovalEnvelope` into the governed transfer story
- treat persisted approval state, not embedded request payloads, as the runtime source of truth for Restricted Custody Transfer
- express the four canonical runtime outcomes in a stable business-readable way
- carry that trust story into offline verification artifacts
- show the difference between valid transfer, missing approval, quarantine, and break-glass review without changing the workflow wedge

This is enough for a controlled demo package, recorded walkthrough, internal
review, and narrative sign-off on the wedge itself.

## What Is Not Signed Off Yet

These items are still real gaps. They should be stated plainly in any demo
readout.

### 1. Live Hot-Path Shadow Evidence

Command executed:

```bash
python scripts/host/verify_rct_hot_path_shadow.py
```

Observed result on 2026-03-30 (runtime-up closure pass):

- `PASS`
- mode: `shadow`
- active snapshot: `runtime-baseline-v1.0.0-1774251324625-local-1774260434866`
- run parity: `3/3 ok`, `0 mismatched`
- aggregate parity: `9/9 ok`, `0 mismatched`
- latency: `p50=34ms`, `p95=73ms`, `p99=73ms`
- canonical dispositions returned: `allow`, `deny`, `quarantine`, `escalate`

Meaning:

- hot-path shadow parity and latency are implemented in the repo
- the shadow harness now uses persisted approval records rather than synthesized approval payloads
- they were demonstrated live in this environment
- there is still one closure gap: status parity counters currently advance for three parity-tracked cases per run while `quarantine_stale_telemetry` is evaluated but not counted in `run_parity`
- do not claim full hot-path sign-off until that accounting gap is resolved (or explicitly frozen as intended behavior)

### 2. Live Verification Surface Walkthrough

The protocol in
[productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
requires:

- runtime API on `8002`
- verification API on `7071`
- a real lookup id or audit id

Observed result on 2026-03-30 (runtime-up closure pass):

- runtime API (`8002`), verification API (`7071`), proof surface (`7072`), and operator console (`7073`) were all running and healthy
- `bash scripts/host/verify_productized_surface.sh` passed with `13` checks and `0` failures
- run was pinned to runtime `audit_id` `c1b98df3-ca42-438b-bbce-4ce5ed463bfe`
- replay API, verification API, proof surface page, and operator console page all resolved that same runtime `audit_id`

Current limitation:

- this runtime audit chain is a `quarantine` trust-gap case
- `approval_envelope_id`, `approval_envelope_version`, and `approval_binding_hash` are null on that chain, so it cannot serve as the final Restricted Custody Transfer allow-path sign-off artifact

### 3. High-Assurance Signer Proof

The repo now routes Restricted Custody Transfer `allow`-path receipts toward the
hardened signer profile, but this report does not yet prove a live run with:

- a real KMS-backed `PolicyReceipt`
- a real KMS or TPM-backed `TransitionReceipt`
- captured signer provenance from a controlled environment execution

That is a sign-off gap only if the demo claim includes live hardware-backed or
cloud-KMS-backed receipt provenance rather than code-path readiness.

## Genuine Demands Before Full Live-Demo Sign-Off

The next concrete demands are:

1. Resolve or explicitly freeze the hot-path shadow parity accounting behavior so the canonical `quarantine` case is reflected consistently in run-level parity totals.
2. Capture one live Restricted Custody Transfer `allow` runtime chain with non-null:
   - `approval_envelope_id`
   - `approval_envelope_version`
   - `approval_binding_hash`
   - `policy_receipt_id`
   - `transition_receipt_ids`
3. Capture one full handoff walkthrough across:
   - operator status
   - asset forensics
   - public or partner proof
   - offline `seedcore-verify` using the same runtime artifact chain
4. Capture the sibling runtime paths (`deny`, `quarantine`, `escalate`) with explicit runtime `audit_id` links and business-state closure.
5. If the demo claim includes hardened signer proof, capture one real allow-path run with signer provenance for both `PolicyReceipt` and `TransitionReceipt`.

Until those steps are complete:

- keep hot-path mode in `shadow`
- do not claim full live-runtime sign-off
- do claim controlled demo readiness backed by repo evidence

## Execution Checklist

Use this checklist to close the remaining live-demo sign-off gap.

### Phase 1. Bring The Live Stack Up

- [x] Start runtime API on `8002`

```bash
uvicorn seedcore.main:app --host 127.0.0.1 --port 8002
```

- [x] Start verification API on `7071`

```bash
npm --prefix ts run serve:verification-api
```

- [x] Start proof surface on `7072`

```bash
npm --prefix ts run serve:proof-surface
```

- [x] Start operator console on `7073`

```bash
npm --prefix ts run serve:operator-console
```

- [x] Confirm the runtime can produce and replay one real `audit_id`

Current runtime closure-pass id: `c1b98df3-ca42-438b-bbce-4ce5ed463bfe`

### Phase 2. Prove Hot-Path Shadow

- [x] Run the canonical shadow verifier

```bash
python scripts/host/verify_rct_hot_path_shadow.py
```

- [x] Capture `mode`, parity ok count, mismatch count, and latency `p50`, `p95`, `p99`
- [ ] Verify `allow_case`, `deny_missing_approval`, `quarantine_stale_telemetry`, and `escalate_break_glass` all complete with zero parity mismatches
Observed nuance: all four dispositions are returned, but run-level parity counters currently increment for three tracked cases per run.
- [x] Keep hot-path mode in `shadow` until the parity evidence stays green

### Phase 3. Prove Productized Surface On One Artifact Chain

- [x] Identify the runtime `audit_id` to use for live sign-off
- [x] Run the productized surface verifier against that runtime artifact chain

```bash
bash scripts/host/verify_productized_surface.sh
```

- [x] Confirm replay API, verification API, proof surface, and operator console all resolve the same runtime `audit_id`
- [x] Confirm the verification run did not fall back to fixture-only evidence

### Phase 4. Capture The Demo Matrix

- [ ] Capture one sealed-lot handoff happy path
- [ ] Capture one missing-approval path
- [ ] Capture one stale-telemetry quarantine path
- [ ] Capture one break-glass escalate path

For each captured case, record:

- [ ] `audit_id`
- [ ] `approval_envelope_id`
- [ ] `approval_envelope_version`
- [ ] `approval_binding_hash`
- [ ] `policy_receipt_id`
- [ ] `transition_receipt_ids`
- [ ] final business state: `verified`, `rejected`, `quarantined`, or `review_required`

### Phase 5. Cross-Surface Consistency Check

- [ ] Confirm the same identifiers appear across runtime replay, verification API, proof surface, operator console, and offline verification
- [ ] Run offline verification for the final captured transfer artifact chain

```bash
cd rust
cargo run -q -p seedcore-verify -- verify-transfer --dir fixtures/transfers/allow_case
```

- [ ] Replace fixture-only evidence with the captured runtime artifact chain anywhere the live-demo claim depends on it

### Phase 6. Hardened Signer Closure

- [ ] Capture one real `allow`-path run with KMS-backed `PolicyReceipt`
- [ ] Capture one real `allow`-path run with KMS- or TPM-backed `TransitionReceipt`
- [ ] Confirm signer provenance is visible in replay and operator forensics

### Exit Criteria

- [ ] `verify_rct_hot_path_shadow.py` is green with zero mismatches
- [x] `verify_productized_surface.sh` is green against a real runtime `audit_id`
- [ ] one happy path and three sibling failure paths are captured
- [ ] all surfaces agree on the same approval and receipt identifiers
- [ ] one live `allow` path shows hardened signer provenance

## Final Recommendation

Recommended wording for the current state:

**SeedCore is ready for a controlled Restricted Custody Transfer demo and has
passed offline sign-off for the canonical artifact chain. Full live-demo
sign-off is still pending closure of the hot-path parity accounting gap,
runtime capture of a full allow-plus-siblings artifact matrix with non-null
approval identifiers, and hardened signer provenance.**

## Related Documents

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
- [phase0_contract_freeze_manifest.json](/Users/ningli/project/seedcore/docs/development/phase0_contract_freeze_manifest.json)
