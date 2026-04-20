# Replay Bundle Transparency Anchoring Design

Date: 2026-04-20
Status: Draft design doc; decision pending. No code changes land on this path until this doc is accepted and its recommendation selected.
Related:

- [ADR 0003: Adopt an IGX Thor Trusted Edge Profile for High-Regulation SeedCore Deployments](../architecture/adr/adr-0003-igx-thor-trusted-edge-profile.md)
- [ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](../architecture/adr/adr-0004-result-verifier-runtime.md)
- [ADR 0005: Preserve Replayable Evidence for Governed Digital Twin State Transitions](../architecture/adr/adr-0005-replayable-evidence-governed-state-transitions.md)
- [Post-Hoc Verifier and Rust Proof Kernel hardening plan, Phases 0-3 landed](./governance_aware_learning_next_stage_plan.md)

## Purpose

Phase 2 of the verifier hardening plan made the Rust kernel authoritative over
**source-preserving** replay bundles: the runtime no longer re-seals artifacts
with a fixture signer, and `verify-chain` validates original artifact signatures
and chain linkage together. Phase 3 replaced the OpenSSL shell-out with
in-process `ed25519-dalek` and `p256` verification so signature checks are
independent of the host's `openssl` binary and free of `/tmp` scratch files.

That closes the **local integrity** story: a caller with the replay bundle and
the trust bundle can prove the chain is intact and unsigned by anything
untrusted. It does **not** close the **external witness** story: nothing today
prevents the signer (or a compromised coordinator) from rewriting history
between transition time and verification time, as long as the new history still
chain-links and still signs cleanly. The only existing guardrail is that
fail-closed twin mutation is irreversible once it happens.

Transparency-log anchoring is the externally-witnessed check that every
governed replay artifact was committed to an append-only log, visible to
auditors, before or at the time it was treated as authoritative. This document
picks how that anchoring works and defines the exact verification semantics
that every artifact and trust bundle must satisfy.

## What the codebase already has

The shape of the transparency contract is already wired through the Rust
kernel, even though no real anchoring happens yet:

- `TrustProof.transparency` on every artifact carries `status`, `log_url`,
  `entry_id`, `integrated_time`, and `proof_hash`.
- `TrustBundle.transparency` on the verifier side carries `enabled`, `log_url`,
  and `public_key`.
- `verify_transparency_proof_requirements` in `rust/crates/seedcore-verify/src/main.rs`
  already rejects artifacts when:
    - the trust bundle enables transparency but the artifact has no
      `transparency` block (`missing_transparency_proof`),
    - the block is present but `status != "anchored"` (`missing_transparency_anchor`),
    - the bound `log_url` diverges from the trust bundle's `log_url`
      (`transparency_log_mismatch`),
    - `entry_id` or `proof_hash` is empty (`missing_transparency_entry`,
      `missing_transparency_proof_hash`).
- `VerificationReport.transparency_status` is copied from the artifact's
  `trust_proof.transparency.status`.

What is **not** wired:

1. **No submission path.** Nothing in the coordinator or HAL actually submits
   a bundle to a log. The `anchored` status on fixtures is fiction.
2. **No inclusion-proof verification.** `proof_hash` is checked for presence,
   not cryptographically verified against a signed tree head.
3. **No signed-tree-head check.** `TrustBundle.transparency.public_key` is
   never used.
4. **No time-bound check.** `integrated_time` is not compared against the
   event's `executed_at` or against a published log-head checkpoint.
5. **No `transparency_status` enum definition.** The field is a free string
   echoing whatever the artifact claims, with only two values meaningfully
   checked by code: `"anchored"` and `"anchor_verification_failed"`.

The existing fixtures carry Rekor-shaped fields (`log_url:
https://rekor.sigstore.dev`, `entry_id: rekor-entry-phase-a-001`,
`public_key: fixture-rekor-key`). That is a hint, not a decision.

## Decision required

Two substantive options. The choice is binding because it determines the
on-chain proof format, the trust root, and the operational dependency surface.
The field shapes already in the artifact schema fit either option, so this is
a trust-boundary and operations choice, not a refactor choice.

### Option A: Sigstore Rekor

**Trust boundary.** Rely on Sigstore's public Rekor log as the witness.
Rekor's tree head is published and signed by the Rekor service; downstream
verifiers pin the Rekor public key in their trust bundle and check inclusion
proofs against it.

**Write path.** After the Coordinator seals a replay artifact (or bundle),
submit the canonical bundle bytes to Rekor via its public REST API.
Rekor returns an entry with `uuid`, `integratedTime`, `logIndex`, and an
`inclusionProof` (hashes + tree size + signed root hash). These populate
`TrustProof.transparency.entry_id`, `integrated_time`, `proof_hash`, and a new
field we do not yet carry, `signed_tree_head` (the signed root hash and tree
size Rekor returned).

**Read path.** `verify_transparency_proof_requirements` upgrades from presence
checks to:

- recompute the canonical bundle hash,
- check that the claimed `proof_hash` matches the Rekor inclusion path to the
  claimed `signed_tree_head`,
- verify the `signed_tree_head` signature against the pinned Rekor key in the
  trust bundle,
- require `integrated_time <= transition.executed_at + grace_seconds` (the
  artifact was anchored before it was acted on).

**What this buys.** An external, publicly-auditable witness. An auditor can
independently query Rekor for the same entry and confirm the proof without
talking to SeedCore. Trust collapses to Rekor's key, which is rotated and
published by Sigstore.

**What this costs.** A **required network dependency** from the verifier path
(or, if we submit asynchronously, from the submission path) to Rekor. Rekor
outages become availability issues for verification, unless we cache signed
tree heads locally. Rekor also imposes its schema on what we can anchor:
Rekor entries are keyed on a signed artifact, which matches our per-artifact
model fine, but increases per-artifact cost (one Rekor submission per governed
artifact) and produces external entries that cannot be deleted, which may
conflict with data-residency or right-to-erasure requirements for customers on
regulated deployments.

### Option B: In-house append-only log with witness co-signing

**Trust boundary.** Run a SeedCore-operated append-only log service
(`seedcore-transparency-log`) that accepts canonical bundle hashes, appends
them to a Merkle tree, publishes signed tree heads on a cadence, and exposes
inclusion proofs. Periodic witness co-signing is required so that the log
operator alone cannot rewrite history: one or more independent witnesses
(customer auditor, external SaaS, partner org) sign each tree head.

**Write path.** Same as Option A, but the submission target is the in-house
log. The log returns the same structural fields: `entry_id`,
`integrated_time`, `proof_hash`, `signed_tree_head`. Witness signatures are a
separate field, `witness_signatures`, that the artifact does not carry but the
trust bundle references a public bundle of.

**Read path.** `verify_transparency_proof_requirements` upgrades from presence
checks to:

- recompute the canonical bundle hash,
- check the claimed `proof_hash` against the claimed `signed_tree_head`,
- verify the `signed_tree_head` signature against the pinned SeedCore log key
  **and** against at least N witness keys, where N is a trust-bundle policy,
- require `integrated_time <= transition.executed_at + grace_seconds`.

**What this buys.** Full control over retention, data-residency, SLA, and the
exact wire format. No external outage can break verification as long as the
log service is up. Right-to-erasure is a design option (retain only hashes,
not bundles). Multiple-witness co-signing provides comparable trust properties
to Rekor for any customer willing to trust the witness set.

**What this costs.** We run and operate the log. That means: key custody for
the log signer, a witness recruitment story that auditors will actually
accept, a disclosure story when the log service is compromised, and a
certification story for customers who currently want to point at a public log.
Customers on regulated deployments may demand the in-house log; customers on
open/public deployments may demand Rekor. Running both simultaneously is
possible but doubles the surface.

## Recommendation

Option B, **in-house append-only log with external witness co-signing**, as
the primary anchoring path, with Option A available as an **additional
anchor** (not a replacement) for deployments whose customers explicitly want
public auditability.

Reasons, weighted in this order:

1. SeedCore's buying audience is regulated custody operators. Hard dependence
   on a public log is a blocker for deployments that must show full control
   over audit data.
2. ADR 0003's Trusted Edge profile already assumes the edge cannot reach the
   public internet reliably. Option A's verifier dependency on Rekor breaks
   that profile.
3. Option B does not preclude Option A. The `TrustBundle.transparency` config
   already supports a single log, and extending it to a list of required logs
   (all must anchor, any subset must verify) is a local schema change with no
   loss of generality.
4. The code changes to Option B are bounded: one new small service, one
   client library, one new trust-bundle field (`witness_public_keys`), and a
   real proof-verification routine in `verify-chain`. Most of the remaining
   complexity is operational, not architectural.

The in-house log is accepted if and only if the witness co-signing story is
real. A log with only a single operator-held key is not a transparency
system; it is a signed audit file. This is a **hard gate** on the
recommendation.

## `transparency_status` enum

The field is currently a free-form string echoed from the artifact. After
this design lands, `VerificationReport.transparency_status` uses a closed set
and every other producer and consumer aligns to it:

| Value                        | Meaning                                                                                                                                    |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `not_configured`             | Trust bundle does not require anchoring for this artifact type. The artifact may omit the `transparency` block entirely.                   |
| `not_checked`                | Trust bundle enables anchoring but the verifier was not configured with the keys or endpoints needed to check it. Treat as insufficient.   |
| `anchored`                   | Artifact carries an inclusion proof that verified against a signed tree head, and the tree head verified against all required signer keys. |
| `anchor_pending`             | Artifact was submitted but the log has not yet integrated it. Not acceptable for fail-closed terminal verification; is a retryable status. |
| `anchor_verification_failed` | Inclusion proof present but did not verify. This is a terminal trust-class failure.                                                        |
| `missing_anchor`             | Trust bundle required anchoring, artifact carried no `transparency` block. Terminal trust-class failure.                                   |
| `stale_anchor`               | Anchor's `integrated_time` violates the `executed_at` ordering constraint. Terminal trust-class failure.                                   |

Consequences for the verifier:

- `not_configured` and `anchored` are **clean** paths.
- `not_checked` is **not** a pass and never counts as anchored. It is an
  operator-facing deficiency.
- `anchor_pending` is a **retry** signal, not a pass. RESULT_VERIFIER should
  re-enqueue with backoff until the log integrates the entry or a timeout
  forces the status to `anchor_verification_failed`.
- `anchor_verification_failed`, `missing_anchor`, `stale_anchor` all map to
  `failure_class = trust` in the existing `ResultVerifierOutcome` pipeline and
  produce `verification_quarantined` twin events.

## Gated code changes

The following work is **explicitly gated** on this doc being accepted and its
recommendation confirmed. Nothing below gets implemented until then.

1. New crate `seedcore-transparency-core` (Rust) defining the canonical
   inclusion-proof format, tree-head signing format, and the
   witness-co-signing verification routine. Pure library, no I/O.
2. New service `seedcore-transparency-log` exposing submission, inclusion
   proof retrieval, and signed tree head endpoints. Backed by the existing
   audit-row store for durability.
3. Extension of `TrustBundle.transparency` to carry a list of required
   logs and, per log, a list of required witness public keys with a policy
   value `min_witnesses`.
4. Replacement of `verify_transparency_proof_requirements` in
   `seedcore-verify` with a real inclusion-proof verifier built on
   `seedcore-transparency-core`.
5. RESULT_VERIFIER handling of `anchor_pending` as a retryable outcome, and
   of the three trust-class statuses as terminal fail-closed outcomes.
6. Fixture refresh: the current `rekor-entry-phase-a-*` fixtures become
   real in-house-log fixtures with a test signer and test witness.

## Assumptions and open items

- **Assumption.** Customers who want public Rekor anchoring can be served by
  running Option A as an additive anchor on top of Option B, not instead of
  it. If any design-partner customer insists on Rekor-only with no in-house
  log, this recommendation needs to be revisited.
- **Assumption.** `min_witnesses >= 1` with at least one witness outside
  SeedCore's operational control is an acceptable definition of external
  auditability for the target market. This needs confirmation from the
  design partners before the log service is built.
- **Open.** Should the log anchor individual artifacts or whole replay
  bundles? Anchoring whole bundles is cheaper but loses the ability for an
  external auditor to re-fetch a single artifact without fetching the rest.
  The current structural schema supports either; the design doc's
  recommendation is to anchor whole bundles and accept the coarser
  auditability, but this is the single largest remaining open item.
- **Open.** The grace window `grace_seconds` for
  `integrated_time <= executed_at + grace_seconds` depends on realistic log
  integration latency. Needs measurement against a Rekor-like reference
  implementation before it is pinned.

## Not in scope

- The existing Phase 3 crypto substrate (`ed25519-dalek`, `p256`) is already
  sufficient for verifying log tree heads. No further crypto additions are
  needed for anchoring itself.
- This doc does not decide whether to split RESULT_VERIFIER out of the
  Coordinator, or whether to add a PyO3 bridge for the Rust kernel. Those
  are tracked separately.
