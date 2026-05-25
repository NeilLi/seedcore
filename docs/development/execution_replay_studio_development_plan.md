# Execution Replay Studio Development Plan

Date: 2026-05-25
Status: Draft development step; additive to the Q2 verification surface

Related:

- [Q2 2026 Audit Trail UI Spec](q2_2026_audit_trail_ui_spec.md)
- [Productized Verification Surface Protocol](productized_verification_surface_protocol.md)
- [Replay Bundle Transparency Anchoring Design](replay_bundle_transparency_anchoring_design.md)
- [Hardware Anchored Telemetry MVP Contract](hardware_anchored_telemetry_mvp_contract.md)
- [Execution Token Lifecycle Management](execution_token_lifecycle_management.md)
- [Agentic Intent Orchestration Plan](agentic_intent_orchestration_plan.md)

## 1. Purpose

Build **Execution Replay Studio**: a forensic UI that makes SeedCore execution
chains inspectable enough that a third party can believe them.

The product claim is simple:

```text
Infrastructure becomes believable when it is inspectable.
```

The Studio is the "Visualize It" step for SeedCore. It turns existing replay,
policy, telemetry, signer, and verification artifacts into a timeline someone
can inspect, replay, challenge, and reproduce without reading service logs or
source code.

## 2. Product Position

Execution Replay Studio is not a new authority surface. It is a read-only
forensic viewer over existing authority-bearing contracts:

- PDP decisions and policy snapshots
- `ExecutionToken` mint/withhold/use events
- governed receipts and replay bundles
- signed edge telemetry refs
- signer provenance and trust-bundle checks
- `RESULT_VERIFIER` outcomes
- operator runbook links and quarantine state

The Studio should live as an advanced replay view inside the current
verification/operator product surface. It extends Screen 4 from the Q2 audit
trail spec instead of creating a parallel dashboard.

## 3. Primary Jobs

An operator, auditor, or design-partner evaluator should be able to:

1. inspect every execution step;
2. replay the chain from request to terminal verification;
3. inspect the policy snapshot used at each decision point;
4. verify telemetry hashes and detect mismatch, reuse, or staleness;
5. validate signer chains against the trust bundle and revocation posture;
6. reproduce the execution timeline from source artifacts;
7. export a compact evidence summary for review without exposing internal-only
   telemetry on public proof surfaces.

The goal is not more charts. The goal is a case recorder.

## 4. Non-Goals

- No write actions, overrides, approval issuance, token minting, or quarantine
  clearance.
- No generic analytics dashboard.
- No second public proof product.
- No dependency on raw database joins from the browser.
- No LLM-only explanation path. Any copilot text must cite deterministic
  fields and remain read-only.

## 5. Existing Surfaces To Reuse

The first implementation should compose from current read contracts:

- `GET /api/v1/verification/workflows/{workflow_id}/verification-detail`
  (`seedcore.verification_detail.v1`)
- `GET /api/v1/verification/workflows/{workflow_id}/replay`
  (`seedcore.verification_replay.v1`)
- `GET /api/v1/replay`
- `GET /api/v1/replay/timeline`
- `GET /api/v1/replay/artifacts`
- `GET /api/v1/replay/jsonld`
- `GET /api/v1/verification/operator/copilot-brief` as optional read-only
  explanation
- offline `seedcore-verify verify-chain --bundle ...` for high-assurance
  parity checks

Frontend and contract homes:

- `ts/apps/operator-console`
- `ts/services/verification-api`
- `ts/packages/contracts`
- `src/seedcore/services/replay_service.py`
- `src/seedcore/api/routers/replay_router.py`
- `rust/crates/seedcore-verify`

## 6. Studio Information Architecture

### A. Case header

The first row answers:

- workflow id
- audit id or replay ref
- asset ref
- business status
- PDP disposition
- replay verdict
- terminal verifier outcome
- current quarantine or lockout state

Use the existing case-verdict strip where possible.

### B. Execution step rail

A left rail lists canonical steps in deterministic order. Initial RCT step
types:

| Step type | Purpose |
| --- | --- |
| `intent_received` | Original request, idempotency key, workflow join key |
| `authority_resolved` | delegated authority, approval envelope, scope |
| `policy_evaluated` | PDP decision, policy snapshot, reason codes |
| `token_minted` | execution token id, TTL, caveats, withheld state |
| `action_dispatched` | executor, HAL boundary, tool/action target |
| `telemetry_attached` | signed telemetry refs, hashes, signer refs |
| `receipt_sealed` | policy and transition receipt chain |
| `replay_verified` | replay-chain result and mismatch detail |
| `result_verified` | `RESULT_VERIFIER` terminal outcome |
| `state_published` | trust/proof refs and public-safe projection |

Each step has:

- timestamp
- source contract
- artifact refs
- signer or producer
- hash inputs and computed hash when available
- status: `passed`, `failed`, `missing`, `not_applicable`, `not_checked`
- next/previous hash linkage where available

### C. Replay controls

Controls:

- step back
- play/pause
- step forward
- jump to first mismatch
- jump to policy decision
- jump to telemetry evidence
- jump to terminal verifier outcome

The replay animation is visual only. It does not re-execute governed action.

### D. Policy snapshot inspector

For each PDP or verifier decision, show:

- policy snapshot id/ref
- policy receipt id
- decision hash
- reason codes
- context envelope hash
- owner context hash when present
- approvals and scope fields used by the decision
- snapshot freshness or readiness status

The user should be able to compare "requested scope" versus "authorized
scope" in one glance.

### E. Telemetry hash verifier

For each `telemetry_ref`, show:

- telemetry id
- payload SHA-256
- asset ref binding
- workflow binding
- signer key ref
- freshness window
- replay/nonce status
- derived physical presence hash contribution

Mismatch states must be explicit:

- `payload_hash_mismatch`
- `asset_binding_mismatch`
- `workflow_binding_mismatch`
- `stale_telemetry`
- `telemetry_replay_detected`
- `telemetry_signer_unknown`
- `telemetry_signer_revoked`

### F. Signer chain validator

Show signer provenance as a chain, not as loose text:

```text
artifact -> signer_key_ref -> signer identity -> trust bundle -> revocation status -> verification result
```

For each signer, include:

- key ref
- verification method
- algorithm
- trust bundle source
- revocation status
- attestation or hardware posture when available
- artifacts signed by this key

This panel is where fixture signers, simulator signers, TPM/KMS-backed signers,
and revoked signers become visually distinguishable.

### G. Artifact inspector

Right-side inspector tabs:

- summary
- raw JSON
- JSON-LD
- receipt chain
- hashes
- signer proof
- runbook lookup

Raw payloads must be collapsible and copyable, but the first view should stay
human-readable.

### H. Reproduction panel

The reproduction panel provides deterministic commands and inputs:

- runtime lookup URL
- replay bundle download/source path when available
- trust bundle ref
- offline verifier command
- expected verification report fields

Example command shape:

```bash
seedcore-verify verify-chain \
  --bundle ./replay_bundle.json \
  --trust-bundle ./trust_bundle.json
```

Do not expose secrets or internal-only telemetry on public proof links.

## 7. Derived Read Model

Add an internal frontend-facing derived model only after the composition logic
is stable:

```ts
interface ExecutionReplayStudioCase {
  contract_version: "seedcore.execution_replay_studio.v0";
  workflow_id: string;
  audit_id?: string;
  status: string;
  replay_verdict: "consistent" | "inconsistent" | "incomplete";
  steps: ExecutionReplayStudioStep[];
  policy_snapshots: PolicySnapshotInspection[];
  telemetry_checks: TelemetryHashCheck[];
  signer_chains: SignerChainCheck[];
  reproduction: ReproductionInstructions;
  source_links: Record<string, string>;
}
```

Rules:

- This is a projection, not an authority-bearing record.
- Every field must trace back to `verification-detail`, `replay`, runtime
  replay endpoints, or offline verifier output.
- Missing source evidence must render as `missing` or `not_checked`, not as
  inferred success.
- Public proof views may link to a narrow summary, but the full Studio remains
  operator/internal unless access control explicitly allows richer forensics.

## 8. Recommended Build Order

### Step 0: Fixture selection

Pick one happy-path RCT workflow and three toxic-path workflows:

- happy path with valid policy, token, telemetry, signer chain, and replay
- stale telemetry
- signer-chain violation
- replay or receipt-chain tamper

The rare-shoe RCT fixture path is the preferred commercial scene when those
artifacts are available.

### Step 1: Backend composition spike

In `ts/services/verification-api`, compose a studio payload from existing
endpoints without changing runtime behavior.

Acceptance:

- payload has ordered steps
- every step has a source link
- missing data is represented explicitly
- no raw DB access from UI code

### Step 2: Operator console route

Add an operator-console route:

```text
/studio?workflow_id=<workflow_id>&source=<fixture|runtime>
```

Link to it from the existing replay/verification page. Keep `/replay` as the
canonical compact view and make `/studio` the forensic expansion.

Acceptance:

- existing replay page remains unchanged for basic users
- Studio can be opened from a verified, rejected, or quarantined case
- no write controls appear

### Step 3: Step rail and artifact inspector

Render ordered steps and a detail inspector for each selected step.

Acceptance:

- selecting a step updates policy, telemetry, signer, and artifact panels
- mismatch steps are visually distinguishable
- raw JSON is available but not the default reading path

### Step 4: Replay controls

Add play/pause/step/jump controls over the step rail.

Acceptance:

- controls do not change backend state
- "jump to first mismatch" works for toxic-path fixtures
- keyboard navigation is optional, but button labels and focus states must be
  accessible

### Step 5: Policy snapshot inspector

Expose policy snapshot, decision hash, reason codes, approval/scope fields, and
context hashes.

Acceptance:

- an evaluator can answer which policy snapshot decided the action
- scope mismatch cases point to exact conflicting fields
- policy absence renders as a deficiency, not as a pass

### Step 6: Telemetry hash verifier

Expose telemetry refs and hash checks.

Acceptance:

- payload SHA-256, signer key ref, asset binding, workflow binding, and
  freshness are visible
- stale/replayed/mismatched telemetry fixtures fail visibly
- physical presence hash contribution is explainable when present

### Step 7: Signer chain validator

Expose signer identity, key ref, trust-bundle membership, algorithm, revocation,
and artifact linkage.

Acceptance:

- unknown and revoked signers fail visibly
- simulator/dev signers are distinguishable from hardware-backed signers
- signed artifacts can be traced back to their signer row

### Step 8: Reproduction panel

Add deterministic reproduction commands and expected outputs.

Acceptance:

- offline verifier command is shown when bundle refs exist
- expected report fields are named
- missing trust bundle or transparency proof is shown as incomplete

### Step 9: Contract and test hardening

Move the derived Studio model into `ts/packages/contracts` after the route is
useful with fixtures.

Acceptance:

- TypeScript contract parser tests cover happy, stale telemetry, signer
  violation, and replay tamper fixtures
- operator-console render tests cover the Studio route
- productized verification protocol includes the Studio as a manual
  high-assurance inspection step

## 9. Acceptance Checklist

The component is ready for design-partner use when:

- every visible verdict links to source evidence;
- every execution step can be inspected independently;
- policy snapshot, telemetry hashes, signer chain, and replay verdict are all
  visible on one page;
- toxic-path fixtures make the failure obvious without reading logs;
- offline reproduction instructions are present for replay bundles;
- public proof remains narrow while operator/internal forensics remain rich;
- the Studio adds no authority-bearing actions;
- existing Q2 queue, detail, forensics, replay, and runbook tests still pass.

## 10. Strong Recommendation

Build the Studio like a flight recorder for agentic infrastructure.

The first screen should not say "trust us." It should show the chain:

```text
request -> authority -> policy -> token -> execution -> telemetry -> receipt -> replay -> verifier -> published state
```

This is how SeedCore makes the invisible visible.
