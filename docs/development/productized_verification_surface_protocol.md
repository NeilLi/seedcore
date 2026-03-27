# Productized Verification Surface Protocol (Phase D)

This protocol verifies that the SeedCore verification surface proves trust outcomes with replayable evidence, not only functional behavior.

The checks are split into:

- Automated checks (runnable now)
- Manual/high-assurance checks (requires external keys, identity controls, or partner auth setup)

## Scope

- Workflow: `Restricted Custody Transfer` only
- Operator surface: `Transfer Status` + `Asset Forensics`
- Partner/public surface: `Transfer Proof` + `Asset Proof` + runtime trust endpoints

## Prerequisites

- Local runtime running (`8002`) and verification API running (`7071`)
- `curl` and `jq` installed
- Optional for runtime checks:
  - local Postgres with `seedcore` DB and `governed_execution_audit` rows, or
  - set `SEEDCORE_AUDIT_ID=<uuid>`

## Fast Run (Automated)

```bash
bash scripts/host/verify_productized_surface.sh
```

Environment overrides:

```bash
SEEDCORE_VERIFICATION_API_BASE=http://127.0.0.1:7071 \
SEEDCORE_RUNTIME_API_BASE=http://127.0.0.1:8002/api/v1 \
SEEDCORE_DB_NAME=seedcore \
SEEDCORE_AUDIT_ID=<audit-uuid> \
bash scripts/host/verify_productized_surface.sh
```

---

## Phase 1: Receipt & Replay Integrity

### 1.1 Cryptographic Receipt Validation

Automated assertions:

- governed receipt contains `decision_hash`
- receipt contains `policy_snapshot`
- runtime verify endpoint executes for the receipt lookup id
- operator forensic payload contains `signature_provenance`

Manual high-assurance addition:

- run offline `seedcore-verify` with a trust bundle and compare signature validity against your SeedCore public key material for the same artifact chain

### 1.2 Replay Accuracy Test

Automated assertions:

- runtime status returns one of business-readable states:
  - `verified | quarantined | rejected | review_required | verification_failed`
- runtime status includes a non-empty timeline
- operator/forensic surfaces render from replay-projected runtime data

---

## Phase 2: Operator Lookup & Runtime Provenance

### 2.1 Lookup Contract Enforcement

Automated assertions:

- transfer status endpoint rejects invalid runtime lookup contract forms (e.g. `subject_id` for transfer status)
- invalid lookup fails hard with `422`

Manual high-assurance addition:

- run a real expired/revoked operator lookup contract scenario and confirm:
  - action is blocked
  - provenance chain names the specific failed contract clause

### 2.2 Policy Snapshot Fidelity

Automated assertions:

- `asset_forensics.policy_snapshot_ref` equals `replay.view.audit_record.policy_snapshot` for the same runtime lookup id

Manual high-assurance addition:

- rotate policy and execute immediately; verify the forensic view reflects the post-rotation snapshot at execution time

---

## Phase 3: Workflow-Specific Proof Surface (RCT Wedge)

### 3.1 Prerequisite Chain Verification

Automated assertions (fixture):

- deny/missing-approval case sets `transfer_readiness == blocked`
- blocker codes include the missing prerequisite code (`missing_dual_approval`)

### 3.2 Stakeholder Visibility Control

Automated assertions (surface split):

- public `AssetProofView` remains narrow (no telemetry refs)
- operator `AssetForensicView` contains telemetry + custody context

Manual high-assurance addition:

- unauthorized partner principal is denied forensic access
- authorized partner sees trust story fields (decision hash, custody transition) without internal-only telemetry

---

## Sign-off Checklist

- Receipts: signed evidence and policy snapshot fields present
- Trust States: business-readable states rendered on operator/replay surfaces
- Operator Lookup: invalid lookup contracts hard-fail
- Forensic View: decision hash, principal identity, and custody transition co-present
- Surface Split: public proof remains narrow; operator forensic view is rich

If all automated checks pass and manual high-assurance checks pass in your controlled environment, Phase D verification can be considered sign-off ready.
