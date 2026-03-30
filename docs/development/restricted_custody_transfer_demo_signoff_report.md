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

Command attempted:

```bash
python scripts/host/verify_rct_hot_path_shadow.py
```

Observed result on 2026-03-30:

- `FAIL`
- runtime API at `http://127.0.0.1:8002/api/v1` was not running
- failure mode: `Connection refused`

Meaning:

- hot-path shadow parity and latency are implemented in the repo
- the shadow harness now uses persisted approval records rather than synthesized approval payloads
- they were not demonstrated live in this environment
- do not claim full hot-path sign-off yet

### 2. Live Verification Surface Walkthrough

The protocol in
[productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
requires:

- runtime API on `8002`
- verification API on `7071`
- a real lookup id or audit id

This report does not claim those live surfaces were exercised end to end in the
current environment.

Also:

- `scripts/host/verify_productized_surface.sh` now requires a real runtime `audit_id`
- fixture-only fallback is no longer acceptable for live sign-off wording

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

1. Start the runtime API and verification API in a controlled environment.
2. Seed one authoritative transfer approval and run `python scripts/host/verify_rct_hot_path_shadow.py` so green parity totals, mismatch totals, and latency percentiles are captured for the canonical `allow`, `deny`, `quarantine`, and `escalate` cases.
3. Run `bash scripts/host/verify_productized_surface.sh` against the same runtime `audit_id` so the operator view, proof surface, and replay API are proven on one artifact chain.
4. Capture one full handoff walkthrough across:
   - operator status
   - asset forensics
   - public or partner proof
   - offline `seedcore-verify`
5. If the demo claim includes hardened signer proof, capture one real allow-path run with signer provenance for both `PolicyReceipt` and `TransitionReceipt`.

Until those steps are complete:

- keep hot-path mode in `shadow`
- do not claim full live-runtime sign-off
- do claim controlled demo readiness backed by repo evidence

## Final Recommendation

Recommended wording for the current state:

**SeedCore is ready for a controlled Restricted Custody Transfer demo and has
passed offline sign-off for the canonical artifact chain. Full live-demo
sign-off is still pending runtime-up verification of hot-path shadow evidence,
proof-surface walkthrough, and hardened signer provenance.**

## Related Documents

- [current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
- [killer_demo_execution_spine.md](/Users/ningli/project/seedcore/docs/development/killer_demo_execution_spine.md)
- [productized_verification_surface_protocol.md](/Users/ningli/project/seedcore/docs/development/productized_verification_surface_protocol.md)
- [phase0_contract_freeze_manifest.json](/Users/ningli/project/seedcore/docs/development/phase0_contract_freeze_manifest.json)
