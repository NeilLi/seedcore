# Rust Workspace Proposal

## Purpose

This note turns the high-level Rust direction in
[language_evolution_map.md](/Users/ningli/project/seedcore/docs/development/language_evolution_map.md)
into a concrete, service/CLI-first workspace proposal that is ready to hand to
an implementer.

This proposal is intentionally documentation-first.

It does not implement the Rust kernel yet.
It defines:

- workspace shape
- crate responsibilities
- public API sketches
- fixture and golden-vector structure
- test classes and acceptance criteria

Assumption:

- backward compatibility with current Python artifact shapes is out of scope
- Rust-native contracts should be designed for strictness first

## Guiding Rules

Rust should enter SeedCore under these rules:

- start with bounded kernels, not broad service rewrites
- optimize for service/CLI seams first, not embedding first
- freeze the artifact contract before freezing the Rust API
- keep orchestration, enrichment, and UI concerns outside the Rust kernel
- require deterministic fixtures and offline verification from the beginning

The practical question is not "what could be faster in Rust?"

The practical question is:

> What is authority-bearing enough that SeedCore should stop leaving it to
> dynamic runtime behavior?

## Workspace Shape

Recommended repo landing zone:

- `rust/`

Recommended layout:

```text
rust/
  Cargo.toml
  crates/
    seedcore-kernel-types/
    seedcore-proof-core/
    seedcore-approval-core/
    seedcore-policy-core/
    seedcore-token-core/
    seedcore-verify/
    seedcore-kernel-testkit/
  fixtures/
    action_intents/
    approval_envelopes/
    policy_inputs/
    tokens/
    receipts/
    replay_bundles/
    transfers/
      allow_case/
      deny_missing_approval/
      quarantine_stale_telemetry/
      escalate_break_glass/
```

Recommended top-level workspace manifest:

```toml
[workspace]
members = [
  "crates/seedcore-kernel-types",
  "crates/seedcore-proof-core",
  "crates/seedcore-approval-core",
  "crates/seedcore-policy-core",
  "crates/seedcore-token-core",
  "crates/seedcore-verify",
  "crates/seedcore-kernel-testkit",
]
resolver = "2"
```

Recommended dependency direction:

- `seedcore-kernel-types` has no dependency on other workspace crates
- `seedcore-proof-core` depends on `seedcore-kernel-types`
- `seedcore-approval-core` depends on `seedcore-kernel-types` and may depend on
  `seedcore-proof-core` for binding-hash helpers
- `seedcore-policy-core` depends on `seedcore-kernel-types`,
  `seedcore-approval-core`, and `seedcore-proof-core`
- `seedcore-token-core` depends on `seedcore-kernel-types` and
  `seedcore-proof-core`
- `seedcore-verify` depends on all kernel crates as an application layer
- `seedcore-kernel-testkit` depends on all crates needed for fixtures and
  golden tests

## Crate Responsibilities

### `seedcore-kernel-types`

This crate owns the shared Rust-native contract model for authority-bearing
artifacts.

Responsibilities:

- shared IDs, timestamps, and strict enums
- canonical artifact structs
- explanation payload types
- shared validation helpers
- shared error taxonomy
- serialization and deserialization traits

It should own the Rust-native source of truth for:

- `ActionIntent`
- `TransferApprovalEnvelope`
- `PolicyDecision`
- `ExecutionToken`
- `PolicyReceipt`
- `TransitionReceipt`
- `EvidenceBundle`
- replay bundle and verification report payloads

### `seedcore-proof-core`

This crate owns proof integrity.

Responsibilities:

- canonical serialization
- SHA-256 hashing
- binding-hash generation
- signature envelopes
- signer abstractions
- signed artifact verification
- replay-chain verification

This crate should not own policy semantics or approval transitions.

### `seedcore-approval-core`

This crate owns governed approval state.

Responsibilities:

- `TransferApprovalEnvelope` validation
- append-only approval history
- lifecycle transition rules
- revocation, expiry, and supersession behavior
- approval binding-hash computation

This crate should not own persistence, workflow orchestration, or UI state.

### `seedcore-policy-core`

This crate owns deterministic policy decisions for frozen inputs.

Responsibilities:

- frozen decision input model
- disposition calculation
- explanation payload construction
- governed decision artifact payload
- policy receipt payload
- execution-token recommendation or spec generation

This crate should not do live graph traversal, live database reads, or AI
calls.

### `seedcore-token-core`

This crate owns execution-token strictness.

Responsibilities:

- execution token claims model
- token minting
- token verification
- TTL validation
- scope and constraint enforcement
- machine-readable enforcement reports

### `seedcore-verify`

This crate is the first external proof application surface.

Responsibilities:

- offline receipt verification
- replay-chain verification
- scenario verification against deterministic fixtures
- CLI commands for third-party auditors, demos, and internal validation

This crate should stay thin. It should orchestrate the kernels, not reinterpret
their outputs.

### `seedcore-kernel-testkit`

This crate owns shared testing infrastructure.

Responsibilities:

- fixture loaders
- golden-vector assertions
- deterministic key and timestamp helpers
- invalid-artifact builders
- scenario harnesses for transfer workflows

## Public API Sketches

These are the public Rust-native APIs the workspace should target.

### `seedcore-kernel-types`

```rust
pub struct ActionIntent {
    pub intent_id: String,
    pub timestamp: Timestamp,
    pub valid_until: Timestamp,
    pub principal: IntentPrincipal,
    pub action: IntentAction,
    pub resource: IntentResource,
    pub environment: IntentEnvironment,
}

pub struct TransferApprovalEnvelope {
    pub approval_envelope_id: String,
    pub workflow_type: String,
    pub status: ApprovalStatus,
    pub asset_ref: String,
    pub lot_id: Option<String>,
    pub from_custodian_ref: String,
    pub to_custodian_ref: String,
    pub transfer_context: TransferContext,
    pub required_approvals: Vec<RoleApproval>,
    pub approval_binding_hash: ArtifactHash,
    pub policy_snapshot_ref: String,
    pub expires_at: Timestamp,
    pub created_at: Timestamp,
    pub version: u32,
}

pub struct PolicyDecision {
    pub allowed: bool,
    pub disposition: Disposition,
    pub reason: Option<String>,
    pub policy_snapshot_ref: String,
    pub explanation: ExplanationPayload,
    pub governed_decision_artifact: GovernedDecisionArtifact,
    pub execution_token: Option<ExecutionToken>,
}

pub struct ExecutionToken {
    pub token_id: String,
    pub intent_id: String,
    pub issued_at: Timestamp,
    pub valid_until: Timestamp,
    pub contract_version: String,
    pub constraints: TokenConstraints,
    pub signature: SignatureEnvelope,
}

pub struct PolicyReceipt {
    pub policy_receipt_id: String,
    pub policy_decision_id: String,
    pub intent_id: String,
    pub policy_snapshot_ref: String,
    pub disposition: Disposition,
    pub explanation: ExplanationPayload,
    pub governed_receipt_hash: ArtifactHash,
    pub signer: SignatureEnvelope,
    pub timestamp: Timestamp,
}

pub struct TransitionReceipt {
    pub transition_receipt_id: String,
    pub intent_id: String,
    pub execution_token_id: String,
    pub endpoint_id: String,
    pub hardware_uuid: String,
    pub actuator_result_hash: ArtifactHash,
    pub from_zone: Option<String>,
    pub to_zone: Option<String>,
    pub executed_at: Timestamp,
    pub receipt_nonce: String,
    pub payload_hash: ArtifactHash,
    pub signer: SignatureEnvelope,
}

pub struct EvidenceBundle {
    pub evidence_bundle_id: String,
    pub intent_id: String,
    pub execution_token_id: Option<String>,
    pub policy_receipt_id: Option<String>,
    pub transition_receipt_ids: Vec<String>,
    pub telemetry_refs: Vec<TelemetryRef>,
    pub media_refs: Vec<MediaRef>,
    pub signer: SignatureEnvelope,
    pub created_at: Timestamp,
}

pub enum Disposition {
    Allow,
    Deny,
    Quarantine,
    Escalate,
}

pub struct ExplanationPayload {
    pub disposition: Disposition,
    pub matched_policy_refs: Vec<String>,
    pub authority_path_summary: Vec<String>,
    pub missing_prerequisites: Vec<String>,
    pub trust_gaps: Vec<String>,
    pub minted_artifacts: Vec<String>,
    pub obligations: Vec<Obligation>,
}
```

Recommended shared utility types:

```rust
pub struct Timestamp(pub chrono::DateTime<chrono::Utc>);

pub struct ArtifactHash {
    pub algorithm: String,
    pub value: String,
}

pub struct SignatureEnvelope {
    pub signer_type: String,
    pub signer_id: String,
    pub signing_scheme: String,
    pub key_ref: Option<String>,
    pub attestation_level: String,
    pub signature: String,
}
```

### `seedcore-proof-core`

```rust
pub trait CanonicalArtifact {
    fn canonical_bytes(&self) -> Result<Vec<u8>, CanonicalizationError>;
}

pub trait Signer {
    fn sign_hash(&self, hash: &ArtifactHash) -> Result<SignatureEnvelope, SigningError>;
}

pub trait KeyResolver {
    fn resolve(&self, key_ref: &str) -> Result<KeyMaterial, VerificationError>;
}

pub fn canonicalize<T: CanonicalArtifact>(
    artifact: &T,
) -> Result<Vec<u8>, CanonicalizationError>;

pub fn hash_artifact<T: CanonicalArtifact>(
    artifact: &T,
) -> Result<ArtifactHash, CanonicalizationError>;

pub fn sign_artifact<T: CanonicalArtifact>(
    artifact: &T,
    signer: &dyn Signer,
) -> Result<SignedArtifact<T>, ProofError>;

pub fn verify_signed_artifact<T: CanonicalArtifact>(
    artifact: &SignedArtifact<T>,
    resolver: &dyn KeyResolver,
) -> VerificationReport;

pub fn verify_replay_chain(
    bundle: &ReplayBundle,
    resolver: &dyn KeyResolver,
) -> ReplayVerificationReport;
```

Recommended support types:

```rust
pub struct SignedArtifact<T> {
    pub artifact: T,
    pub artifact_hash: ArtifactHash,
    pub signature: SignatureEnvelope,
}

pub struct VerificationReport {
    pub verified: bool,
    pub artifact_type: String,
    pub error_code: Option<String>,
    pub details: Vec<String>,
}

pub struct ReplayVerificationReport {
    pub verified: bool,
    pub checked_artifacts: Vec<String>,
    pub error_code: Option<String>,
    pub lineage: Vec<String>,
}
```

### `seedcore-approval-core`

```rust
pub enum ApprovalStatus {
    Pending,
    PartiallyApproved,
    Approved,
    Expired,
    Revoked,
    Superseded,
}

pub enum ApprovalTransition {
    AddApproval(RoleApproval),
    Revoke(RevocationRecord),
    Expire(Timestamp),
    Supersede { successor_envelope_id: String },
}

pub fn validate_envelope(
    envelope: &TransferApprovalEnvelope,
) -> Result<(), ApprovalError>;

pub fn apply_transition(
    envelope: &TransferApprovalEnvelope,
    transition: ApprovalTransition,
    now: Timestamp,
) -> Result<TransferApprovalEnvelope, ApprovalError>;

pub fn approval_binding_hash(
    envelope: &TransferApprovalEnvelope,
) -> Result<ArtifactHash, ApprovalError>;
```

Recommended supporting domain types:

```rust
pub struct RoleApproval {
    pub role: String,
    pub principal_ref: String,
    pub status: String,
    pub approved_at: Option<Timestamp>,
    pub approval_ref: String,
}

pub struct RevocationRecord {
    pub revoked_by: String,
    pub revoked_at: Timestamp,
    pub reason: String,
}
```

### `seedcore-policy-core`

```rust
pub struct FrozenDecisionInput {
    pub action_intent: ActionIntent,
    pub approval_envelope: Option<TransferApprovalEnvelope>,
    pub policy_snapshot_ref: String,
    pub asset_state: FrozenAssetState,
    pub authority_graph_summary: AuthorityGraphSummary,
    pub telemetry_summary: TelemetrySummary,
    pub break_glass: Option<BreakGlassContext>,
}

pub fn evaluate(
    input: &FrozenDecisionInput,
) -> Result<PolicyEvaluation, PolicyError>;

pub struct PolicyEvaluation {
    pub disposition: Disposition,
    pub explanation: ExplanationPayload,
    pub governed_decision_artifact: GovernedDecisionArtifact,
    pub policy_receipt_payload: PolicyReceiptPayload,
    pub execution_token_spec: Option<ExecutionTokenSpec>,
}
```

Recommended supporting types:

```rust
pub struct FrozenAssetState {
    pub asset_ref: String,
    pub current_custodian_ref: Option<String>,
    pub current_zone_ref: Option<String>,
    pub custody_point_ref: Option<String>,
    pub transferable: bool,
    pub restricted: bool,
    pub evidence_refs: Vec<String>,
    pub approved_registration_refs: Vec<String>,
}

pub struct AuthorityGraphSummary {
    pub matched_policy_refs: Vec<String>,
    pub authority_paths: Vec<String>,
    pub missing_prerequisites: Vec<String>,
    pub trust_gaps: Vec<String>,
}

pub struct TelemetrySummary {
    pub observed_at: Option<Timestamp>,
    pub stale: bool,
    pub attested: bool,
    pub seal_present: Option<bool>,
}

pub struct BreakGlassContext {
    pub present: bool,
    pub validated: bool,
    pub principal_ref: Option<String>,
    pub reason: Option<String>,
}
```

### `seedcore-token-core`

```rust
pub struct ExecutionTokenClaims {
    pub token_id: String,
    pub intent_id: String,
    pub issued_at: Timestamp,
    pub valid_until: Timestamp,
    pub contract_version: String,
    pub constraints: TokenConstraints,
}

pub fn mint_token(
    claims: ExecutionTokenClaims,
    signer: &dyn Signer,
) -> Result<ExecutionToken, TokenError>;

pub fn verify_token(
    token: &ExecutionToken,
    resolver: &dyn KeyResolver,
    now: Timestamp,
) -> TokenVerificationReport;

pub fn enforce_constraints(
    token: &ExecutionToken,
    request: &ExecutionRequestContext,
    now: Timestamp,
) -> TokenEnforcementReport;
```

Recommended support types:

```rust
pub struct TokenConstraints {
    pub action_type: String,
    pub target_zone: Option<String>,
    pub asset_id: Option<String>,
    pub principal_agent_id: Option<String>,
    pub source_registration_id: Option<String>,
    pub registration_decision_id: Option<String>,
    pub endpoint_id: Option<String>,
}

pub struct ExecutionRequestContext {
    pub action_type: String,
    pub target_zone: Option<String>,
    pub asset_id: Option<String>,
    pub principal_agent_id: Option<String>,
    pub endpoint_id: Option<String>,
}
```

### `seedcore-verify`

Recommended CLI contract:

```text
seedcore-verify verify-receipt --artifact path/to/policy_receipt.json
seedcore-verify verify-chain --bundle path/to/replay_bundle.json
seedcore-verify verify-transfer --dir rust/fixtures/transfers/allow_case
seedcore-verify explain --artifact path/to/policy_decision.json
```

Recommended CLI behavior:

- `verify-receipt` verifies one proof-bearing artifact and returns a
  machine-readable verification report
- `verify-chain` verifies a replay bundle and its lineage integrity
- `verify-transfer` loads a full scenario directory and verifies all expected
  outputs end to end
- `explain` prints the deterministic explanation payload without recomputing a
  separate interpretation layer

## Fixture And Golden-Vector Structure

Shared fixture root:

- `rust/fixtures/action_intents/`
- `rust/fixtures/approval_envelopes/`
- `rust/fixtures/policy_inputs/`
- `rust/fixtures/tokens/`
- `rust/fixtures/receipts/`
- `rust/fixtures/replay_bundles/`
- `rust/fixtures/transfers/allow_case/`
- `rust/fixtures/transfers/deny_missing_approval/`
- `rust/fixtures/transfers/quarantine_stale_telemetry/`
- `rust/fixtures/transfers/escalate_break_glass/`

Recommended scenario directory contents:

- `input.action_intent.json`
- `input.approval_envelope.json`
- `input.asset_state.json`
- `input.telemetry_summary.json`
- `input.authority_graph_summary.json`
- `expected.policy_evaluation.json`
- `expected.execution_token.json` when applicable
- `expected.policy_receipt.json`
- `expected.transition_receipt.json` when applicable
- `expected.evidence_bundle.json` when applicable
- `expected.verification_report.json`

Golden-vector categories:

- canonical JSON bytes
- SHA-256 artifact hash
- signature envelope
- positive verification result
- negative verification result with exact error code

Fixture rules:

- fixed timestamps
- fixed UUIDs
- fixed keys
- fixed nonce values
- fixed snapshot refs
- no random generation during tests

Recommended support files:

- `keys.dev.json`
- `manifest.json`
- `README.md` describing each scenario

## Transfer Scenario Definitions

The first fully specified workflow remains:

**Restricted Custody Transfer v1**

The initial four deterministic scenarios should be:

### `allow_case`

Meaning:

- dual approval is complete
- asset state is transferable
- telemetry is fresh enough
- policy returns `allow`
- execution token is minted
- proof artifacts verify cleanly

### `deny_missing_approval`

Meaning:

- required approval is missing or incomplete
- policy returns `deny`
- no execution token is minted
- policy receipt still exists

### `quarantine_stale_telemetry`

Meaning:

- authority chain is not contradictory
- telemetry freshness or attestation is insufficient
- policy returns `quarantine`
- receipt exists
- token may be omitted or marked restricted by future policy rules, but the
  fixture should choose one deterministic behavior and freeze it

### `escalate_break_glass`

Meaning:

- a break-glass request exists
- strict automated allow is not appropriate
- policy returns `escalate`
- explanation payload carries explicit review obligation

## Test Classes

The proposal should require these test classes.

### Unit tests

- canonicalization logic
- hash stability
- signature verification
- approval lifecycle transitions
- token TTL and scope enforcement

### Golden tests

- compare actual output against `expected.*.json`
- compare canonical bytes against golden vectors
- compare machine-readable reports against exact expected error codes

### Negative tests

- malformed artifacts
- invalid signatures
- stale timestamps
- revoked approvals
- superseded envelopes
- mismatched hashes

### Scenario tests

- `allow`
- `deny`
- `quarantine`
- `escalate`

### CLI tests

- `seedcore-verify verify-receipt`
- `seedcore-verify verify-chain`
- `seedcore-verify verify-transfer`
- `seedcore-verify explain`

### Cross-crate integration tests

- policy evaluation -> token minting -> receipt generation -> evidence bundle
  verification
- replay-chain verification across policy, transition, and evidence artifacts

## Acceptance Criteria

- all artifact-producing APIs are deterministic for the same inputs
- all verifier outputs are stable and machine-readable
- all disposition outcomes are derived by `seedcore-policy-core`, not
  reinterpreted in the CLI
- all fixture scenarios can be verified offline with `seedcore-verify`
- no crate outside the kernel workspace becomes the authority source for proof,
  approval, token, or decision semantics

## Mapping To Current SeedCore Python Boundaries

This proposal is intentionally not backward-compatible, but it should still be
understood against current repository seams.

Current Python proof and receipt seams:

- `src/seedcore/ops/evidence/signers.py`
- `src/seedcore/ops/evidence/verification.py`
- `src/seedcore/hal/custody/transition_receipts.py`

Current Python decision and governance seams:

- `src/seedcore/coordinator/core/governance.py`
- `src/seedcore/ops/pkg/evaluator.py`
- `src/seedcore/ops/pkg/authz_graph/compiler.py`

Current Python token seam:

- `src/seedcore/hal/robot_sim/governance/execution_token.py`

These files are useful orientation points for the implementer, but they should
not constrain the Rust-native contracts.

## Recommended Documentation Wiring

This proposal should be linked from:

- `docs/development/language_evolution_map.md`
- `docs/development/current_next_steps.md`
- `docs/development/killer_demo_execution_spine.md`
- `docs/development/next_killer_demo_contract_freeze.md`
