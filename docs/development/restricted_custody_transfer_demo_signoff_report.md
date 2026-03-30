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

Current sign-off status: `PASS`

Meaning:

- `PASS` for offline contract fidelity, persisted-approval runtime enforcement, fixture verification, TS build, targeted Python runtime/proof tests, and live runtime closure evidence
- `SIGNED OFF` for a full local live-runtime demo claim across runtime API, verification API, proof surface, operator console, and offline replay-chain verification on the same runtime audit chains

The honest reading is:

- the demo story is now credible and concretely backed by both repo evidence and runtime-up artifact capture
- hot-path rollout remains intentionally in `shadow`; this sign-off covers Slice 1 live-demo closure, not shadow-to-enforce promotion

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

## Live Closure Pass

Final runtime-up closure pass completed on 2026-03-30.

### 1. Hot-Path Shadow Parity Closure

Command:

```bash
python scripts/host/verify_rct_hot_path_shadow.py
```

Result:

- `PASS`
- mode: `shadow`
- active snapshot: `runtime-baseline-v1.0.0-1774251324625-local-1774260434866`
- run parity: `4/4 ok`, `0 mismatched`
- aggregate parity: `25/25 ok`, `0 mismatched`
- latency: `p50=52ms`, `p95=130ms`, `p99=146ms`
- canonical dispositions returned: `allow`, `deny`, `quarantine`, `escalate`

### 2. Live Runtime Matrix + Cross-Surface Capture

Command:

```bash
source .local-runtime/rct_signer.env
python scripts/host/capture_rct_live_signoff_matrix.py
```

Capture root:

- `.local-runtime/rct_live_signoff/20260330T061828Z`

Captured matrix:

| case | audit_id | disposition | business_state | approval_envelope_id | approval_envelope_version | approval_binding_hash | policy_receipt_id | transition_receipt_ids |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `allow_case` | `ba05655c-9351-4783-97f1-fc6774c4f38b` | `allow` | `verified` | `approval-transfer-001` | `23` | `sha256:e88addfa415a61ba8316ca296300185572f15bc3c1a83427804cf59a0446ce72` | `e459beaa-d283-4554-a639-2b8c1cb4d54c` | `92356db8-b39d-40e6-a330-fa7fbe5855e2` |
| `deny_missing_approval` | `a65bbee7-023a-44fa-9e9d-75e0164102e4` | `deny` | `rejected` | `approval-transfer-002` | `12` | `sha256:bc637f18f600a8eb561fdbb845ca0587ca3e3fd76b99f25aa55f222baf57e4cf` | `796566cd-536d-480a-9be4-795bc68c1aec` | `[]` |
| `quarantine_stale_telemetry` | `21dcb295-644a-465b-a505-064e6908c99c` | `quarantine` | `quarantined` | `approval-transfer-003` | `12` | `sha256:c0c905a5fc61f7fc463d079d6510862c1a6afb03a1c57f08d11d63d8730ff7fe` | `a36e6828-6375-4077-bb69-32ac8580add8` | `[]` |
| `escalate_break_glass` | `28ac9873-3e8f-430f-9681-224fdad44286` | `escalate` | `review_required` | `approval-transfer-004` | `14` | `sha256:0dc7e901b585e24a2c685bdab4521f9689534d44d83678226b11d1f5f192a689` | `49e821e7-d679-47ba-803c-98425b364eb7` | `[]` |

Cross-surface result:

- all four cases: `cross_surface_consistent=true`
- all four cases: runtime `/verify` succeeded and Rust replay-chain verification succeeded
- productized surface protocol succeeded on the captured allow audit chain (`13` checks passed, `0` failed)

### 3. Hardened Signer Provenance (Allow Path)

Captured allow path signer provenance (from runtime forensics on audit `ba05655c-9351-4783-97f1-fc6774c4f38b`):

- `PolicyReceipt`: signer `seedcore-rct-kms-signer`, key ref `kms:rct-live-signoff-p256`, `attested`
- `TransitionReceipt`: signer `seedcore-rct-kms-signer`, key ref `kms:rct-live-signoff-p256`, `attested`

## Execution Checklist

Final closure checklist.

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

Current allow-path sign-off audit id: `ba05655c-9351-4783-97f1-fc6774c4f38b`

### Phase 2. Prove Hot-Path Shadow

- [x] Run the canonical shadow verifier

```bash
python scripts/host/verify_rct_hot_path_shadow.py
```

- [x] Capture `mode`, parity ok count, mismatch count, and latency `p50`, `p95`, `p99`
- [x] Verify `allow_case`, `deny_missing_approval`, `quarantine_stale_telemetry`, and `escalate_break_glass` all complete with zero parity mismatches
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

- [x] Capture one sealed-lot handoff happy path
- [x] Capture one missing-approval path
- [x] Capture one stale-telemetry quarantine path
- [x] Capture one break-glass escalate path

For each captured case, record:

- [x] `audit_id`
- [x] `approval_envelope_id`
- [x] `approval_envelope_version`
- [x] `approval_binding_hash`
- [x] `policy_receipt_id`
- [x] `transition_receipt_ids`
- [x] final business state: `verified`, `rejected`, `quarantined`, or `review_required`

### Phase 5. Cross-Surface Consistency Check

- [x] Confirm the same identifiers appear across runtime replay and operator-forensics verification surface, with consistent business-state closure across status/proof pages
- [x] Run offline verification for each captured runtime chain (`seedcore-verify` replay-chain verification via Rust bundle seal + verify)
- [x] Replace fixture-only evidence with captured runtime artifact chains for live-demo sign-off claims

### Phase 6. Hardened Signer Closure

- [x] Capture one real `allow`-path run with KMS-backed `PolicyReceipt`
- [x] Capture one real `allow`-path run with KMS-backed `TransitionReceipt`
- [x] Confirm signer provenance is visible in replay and operator forensics

### Exit Criteria

- [x] `verify_rct_hot_path_shadow.py` is green with zero mismatches
- [x] `verify_productized_surface.sh` is green against a real runtime `audit_id`
- [x] one happy path and three sibling failure paths are captured
- [x] replay + verification surfaces agree on captured approval and receipt identifiers (with status/proof retaining narrow business-state shape)
- [x] one live `allow` path shows hardened signer provenance

## Final Recommendation

Recommended wording for the current state:

**SeedCore is fully signed off for the Restricted Custody Transfer Slice 1
live demo in this local host-mode environment. The runtime matrix, parity
closure, cross-surface audit linkage, and hardened allow-path signer
provenance were all captured on 2026-03-30.**

## Related Documents

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
- [phase0_contract_freeze_manifest.json](/Users/ningli/project/seedcore/docs/development/phase0_contract_freeze_manifest.json)
