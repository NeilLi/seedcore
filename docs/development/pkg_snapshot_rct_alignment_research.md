# PKG Snapshot Alignment with Agent-Governed Restricted Custody Transfer

Date: 2026-04-02
Status: Research note, design recommendation, and Phase 1–3 status update

## Why this note exists

SeedCore already has most of the components needed for a serious, replayable,
Agent-Governed Restricted Custody Transfer (RCT) path:

- versioned `pkg_snapshots`
- compiled authz graph activation
- snapshot-scoped facts
- approval envelope persistence
- custody state and custody transition graph
- governed receipt, policy receipt, evidence bundle, and replay materialization

The current shape is strong, but the semantics are split across multiple layers.
This makes PKG snapshots more "policy bundle + task capability catalog" than a
precise "RCT authority contract".

The goal of this note is to define how PKG snapshots should evolve so that:

1. PKG snapshots precisely represent the authority contract for RCT.
2. the hot path stays fast and deterministic.
3. evidence and replay remain cryptographically and semantically tied to the
   same policy world.
4. capability evolution does not accidentally become authority drift.

## Milestone update

As of 2026-04-03, the codebase has landed Phase 1 of the PKG RCT contract
alignment work in additive, shadow-safe form.

As of 2026-04-04, Phase 2 (activation hardening) is implemented in
`PKGManager` behind explicit environment flags so default/dev behavior stays
unchanged.

What is now in place:

- snapshot manifests and snapshot-scoped taxonomy tables
- persisted `request_schema_bundle`, `taxonomy_bundle`,
  `decision_graph_snapshot`, and `activation_manifest` artifacts
- `state_binding_hash` plumbing through governed receipts, policy receipts,
  evidence bundles, materializers, and replay verification
- runtime preference for the persisted contract bundles when they are present
- bundle-aware hot-path request assembly, shadow verification, and capture
  scripts
- **Phase 2:** optional fail-closed activation when
  `SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE=1` (truthy): requires compiled graph
  `restricted_transfer_ready`, a present `decision_graph_snapshot`, all four
  contract artifact types in `pkg_snapshot_artifacts`, a
  `pkg_snapshot_manifests` row, and non-empty snapshot-scoped taxonomy lists
  from `get_taxonomy_bundle`. In **CONTROL** mode, failure rolls back the
  evaluator swap; **ADVISORY** logs a warning and continues. The same checks
  run after `refresh_active_authz_graph` persistence; in CONTROL + enforce,
  refresh returns `success: false` without updating cached contract artifacts.
- **Phase 2 preflight:** optional `SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT=1`
  requires an existing `pkg_snapshot_manifests` row **before** authz graph
  compilation (strict publish-time contract).
- **Phase 3:** optional publish-time validation when
  `SEEDCORE_PKG_RCT_PUBLISH_VALIDATE=1`: dry-run compile via
  `AuthzGraphManager.compile_snapshot_index` (no active-graph swap), then
  `rct_publish_validation` checks `restricted_transfer_ready`, typed
  `transition_requirements` rows (keys, effect, lists, booleans, ints),
  canonical `trust_gap_taxonomy` codes, non-empty transition graph, plus
  `pkg_snapshot_manifests` row and non-empty taxonomy lists from
  `get_taxonomy_bundle`. Failures block `activate_snapshot_version` before the
  DB activation call.

What remains for later phases:

- optional request-schema bundle shape checks at publish (beyond taxonomy/manifest)
- replay hardening that makes policy hash + graph hash + state binding
  mandatory

## Current repo state

### What PKG snapshots do well today

The repo already pins a large part of the governance surface to snapshot
versions:

- `pkg_snapshots`, `pkg_policy_rules`, `pkg_rule_conditions`,
  `pkg_rule_emissions`, and `pkg_snapshot_artifacts` define the base PKG bundle
  in [013_pkg_core.sql](../../deploy/migrations/013_pkg_core.sql).
- `tasks`, embeddings, graph nodes, and governed facts are snapshot-scoped for
  replay isolation in
  [017_pkg_tasks_snapshot_scoping.sql](../../deploy/migrations/017_pkg_tasks_snapshot_scoping.sql).
- the `PKGManager` activates a snapshot, validates its checksum, refreshes the
  capability registry, and activates the compiled authz graph in
  [manager.py](../../src/seedcore/ops/pkg/manager.py).
- the hot path explicitly checks compiled-graph readiness, compiled-graph
  freshness, and request snapshot consistency in
  [pdp_hot_path.py](../../src/seedcore/ops/pdp_hot_path.py).
- the compiled authz graph produces a decision-graph snapshot hash,
  transition requirements, and a `restricted_transfer_ready` signal in
  [compiler.py](../../src/seedcore/ops/pkg/authz_graph/compiler.py).
- evidence artifacts already bind decisions to `snapshot_version` and
  `snapshot_hash` in [builder.py](../../src/seedcore/ops/evidence/builder.py)
  and [materializer.py](../../src/seedcore/ops/evidence/materializer.py).
- approval envelopes, custody state, and custody transition events are already
  persisted in
  [130_transfer_approval_runtime.sql](../../deploy/migrations/130_transfer_approval_runtime.sql),
  [asset_custody.py](../../src/seedcore/models/asset_custody.py), and
  [custody_graph.py](../../src/seedcore/models/custody_graph.py).

### Where the model is still too loose

The important gap was not missing infrastructure. The gap was that the
authoritative RCT contract was still spread across:

- generic PKG rule tables
- task capability definitions in `pkg_subtask_types`
- compiled authz graph projection logic
- hot-path request assembly
- evidence builders and replay materializers

In other words:

- PKG is partly an authority bundle.
- PKG is partly a routing/capability bundle.
- the actual RCT decision kernel is partly implicit in Python code.

That is workable, but it is not yet the cleanest possible authority model.

Phase 1 narrows that gap substantially, but it does not fully eliminate the
implicit decision semantics yet. Phase 2 adds opt-in fail-closed activation
hardening (see env flags above); broader authoring and replay milestones remain.

## Core conclusion

PKG snapshots should become the immutable root of the RCT authority contract,
but they should not absorb all runtime state.

The clean split is:

- `PKG snapshot`: immutable policy bundle, schema bundle, taxonomy bundle, and
  workflow safety profile
- `compiled decision graph snapshot`: immutable hot-path artifact derived from
  the PKG snapshot plus snapshot-scoped governed state inputs
- `runtime state bindings`: freshness-bounded custody, approval, telemetry, and
  twin state used for one request
- `capability catalog`: orchestration hints only, never final authority

This means the system should treat `pkg_subtask_types` and guest overlays as
execution support, not as the core RCT authority definition.

## The target model

### 1. Snapshot must define the RCT contract explicitly

Every PKG snapshot that is allowed to govern RCT should declare a snapshot-level
manifest containing at least:

- workflow type: `restricted_custody_transfer`
- decision contract version
- request schema version
- evidence contract version
- trust-gap taxonomy version
- reason-code taxonomy version
- obligation taxonomy version
- consistency contract version
- safety profile
- activation requirements

Today, some of this exists only implicitly in code and docs. It should be
first-class data.

### 2. Capability must be separated from authority

`pkg_subtask_types` is valuable, but its job is to describe executor hints:

- specialization
- tools
- skills
- behavior defaults
- routing defaults

It should not become the place where final RCT authority semantics live.

Rule of thumb:

- capability answers "who is suited to execute?"
- authority answers "is this transfer allowed under this pinned policy world?"

Those are related, but not the same.

### 3. RCT policy should compile to typed transition requirements

The compiled authz graph already produces a good shape for hot-path decisions:

- required current custodian
- transferable state requirement
- telemetry freshness limit
- inspection freshness limit
- attestation requirement
- seal requirement
- approved source registration requirement
- custody points

That shape should become the canonical RCT decision profile for a snapshot.

The generic rule tables may remain authoring infrastructure, but a snapshot
should not be considered RCT-ready unless it compiles into a complete typed
transition-requirement set.

### 4. Evidence must bind policy and state separately

For serious replay, one hash is not enough.

Every governed RCT decision should bind at least:

- `policy_snapshot_hash`: immutable PKG policy bundle identity
- `decision_graph_snapshot_hash`: compiled hot-path artifact identity
- `state_binding_hash`: approval/custody/telemetry/twin consistency identity

The repo already emits the first two surfaces in several places. The missing
piece is a first-class state-binding token/hash.

## Recommended schema evolution

### A. Add a snapshot manifest table

Recommended new table:

- `pkg_snapshot_manifests`

Suggested columns:

- `snapshot_id`
- `workflow_type`
- `decision_contract_version`
- `request_schema_version`
- `evidence_contract_version`
- `reason_code_taxonomy_version`
- `trust_gap_taxonomy_version`
- `obligation_taxonomy_version`
- `consistency_contract_version`
- `safety_profile`
- `requires_signed_bundle`
- `requires_compiled_decision_graph`
- `requires_authority_state_binding`
- `manifest_json`
- `manifest_hash`

Purpose:

- make snapshot intent explicit
- let activation fail closed before runtime if required artifacts are missing
- make replay and audit explain what a snapshot promised to enforce

### B. Add snapshot-scoped schema bundles

Recommended new artifact types:

- `decision_graph_snapshot`
- `request_schema_bundle`
- `taxonomy_bundle`
- `activation_manifest`

Why:

- today `pkg_snapshot_artifacts` stores only `rego_bundle` and `wasm_pack`
- the hot path and evidence layers already reason about decision-graph snapshot
  versions and hashes
- the artifact store should carry those artifacts directly instead of treating
  them as purely in-memory products

### C. Normalize taxonomies

Recommended snapshot-scoped or versioned tables:

- `pkg_reason_codes`
- `pkg_trust_gap_codes`
- `pkg_obligation_codes`

Each code should define:

- stable code id
- disposition family
- severity
- operator-facing message
- machine-facing category
- deprecated flag

Why:

- RCT relies on a frozen decision vocabulary
- codes should be reviewed as policy data, not only discovered in code paths

### D. Add a consistency contract

Recommended new artifact or persisted payload:

- `authority_state_binding`

This should hash or serialize the authoritative request-time state inputs:

- approval envelope id and version
- approval transition head hash
- asset custody transition sequence
- last custody receipt hash
- latest trusted telemetry or tracking event ref
- relevant twin snapshot ref or hash

This is the missing causal link between:

- "the policy snapshot we intended to use"
- and
- "the exact state world we actually authorized against"

### E. Add activation completeness checks

Snapshot activation should fail closed unless the manifest says the snapshot is
complete for RCT and the runtime can verify:

- base snapshot checksum is valid
- required artifacts exist
- compiled decision graph exists or can be built
- compiled decision graph is `restricted_transfer_ready`
- required taxonomies exist
- required schemas exist

This is stronger than only checking bundle checksums.

## Recommended decision rules

The RCT allow path should remain narrow and deterministic.

### Allow only when all of the following are true

- request passes strict schema validation
- principal and delegated authority are present
- workflow type is exactly `restricted_custody_transfer`
- policy snapshot ref matches active compiled decision graph
- compiled decision graph is fresh and RCT-ready
- approval envelope exists, is current, and matches binding hash
- asset identity matches authority scope and custody state
- from/to zone and coordinate constraints do not contradict scope
- telemetry freshness is within the policy limit
- attestation, seal, and registration requirements are satisfied
- no hard trust gap is present

### Deny when the system has deterministic contradiction

Examples:

- asset mismatch
- scope mismatch
- custody mismatch
- required approval missing when policy says it is mandatory
- registration explicitly unapproved

### Quarantine when the system lacks enough trustworthy proof

Examples:

- stale telemetry
- stale decision graph
- missing binding state
- unavailable compiled decision graph
- incomplete authority state reconstruction

### Escalate only for policy-driven step-up

Examples:

- manual review required
- break-glass path
- high-risk context needing human approval beyond the base approval envelope

This preserve a clean semantic split:

- `deny` for contradiction
- `quarantine` for insufficient trustworthy proof
- `escalate` for deliberate human step-up

## Facts, capabilities, and state: the correct layering

### Capabilities

Should remain in `pkg_subtask_types.default_params` and guest overlays.

Examples:

- specialization
- tool requirements
- behaviors
- routing tags

These affect who runs work, not whether RCT authority exists.

### Facts

Should represent policy-relevant state that can be replayed and projected into
the authz graph.

Examples:

- delegated authority facts
- source registration and registration decision facts
- certification and attestation facts
- asset and batch relationship facts
- facility and custody point facts
- approved workflow stage facts

Facts should be snapshot-scoped and provenance-bearing.

### Runtime state

Should remain outside the immutable PKG snapshot, but be bound to the decision.

Examples:

- current custody sequence
- approval envelope current head
- freshest accepted telemetry
- twin snapshot selected for the decision

These are per-request realities, not snapshot authoring content.

## Safety principles for evolution

### 1. Additive before mandatory

First add new manifest/schema/taxonomy artifacts in shadow mode.
Only later make activation fail if they are missing.

### 2. Never reuse active snapshots

Once promoted, a snapshot should be immutable.
Any rule, schema, taxonomy, or capability change should create a new snapshot.

### 3. Preserve frozen decision vocabulary

`allow`, `deny`, `quarantine`, and `escalate` should remain the only top-level
RCT dispositions. Reason-code expansion is fine, but only under controlled
taxonomy versioning.

### 4. Keep the hot path synchronous and local

Do not move request-time RCT authority back into live graph rebuilding or
best-effort network calls. Compile ahead of time, then evaluate on pinned
artifacts.

### 5. Separate planning from authority forever

`TaskPayload`, capability routing, guest personas, and orchestration hints must
never be sufficient to mint RCT authority on their own.

### 6. Fail closed on consistency ambiguity

If approval state, custody state, telemetry state, or snapshot state cannot be
bound confidently, the outcome should be `quarantine` or `deny`, not silent
fallback.

## Recommended phased rollout

### Phase 1: Contract hardening without changing decisions

Implemented in additive, shadow-safe form:

- add `pkg_snapshot_manifests`
- add taxonomy/version bundles
- add `state_binding_hash` into governed receipt and policy receipt
- persist compiled `decision_graph_snapshot` as a snapshot artifact

### Phase 2: Activation hardening

**Status:** Implemented (opt-in via `SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE` and
`SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT` in `PKGManager`).

- fail snapshot activation if the manifest is missing (preflight flag) or after
  persistence if the manifest row is still absent (enforce flag)
- fail activation if required artifacts or taxonomies are missing (enforce flag)
- require compiled graph `restricted_transfer_ready=true` for RCT snapshots (enforce flag)

### Phase 3: Authoring hardening

**Status:** Partially implemented (publish gate + typed transition row checks).

- introduce typed authoring structures for RCT transition requirements
  (**implemented** as `rct_publish_validation` field checks on compiled
  `transition_requirements` payloads; PKG rules remain compiler inputs)
- keep generic PKG rule authoring as a compiler input, not the only source of
  truth
- add publish-time validation for request schemas and taxonomies
  (**taxonomy + manifest** enforced when `SEEDCORE_PKG_RCT_PUBLISH_VALIDATE=1`;
  optional future: validate persisted `request_schema_bundle` JSON shape)

### Phase 4: Replay hardening

- require policy hash + decision-graph hash + state-binding hash on every
  governed RCT receipt
- add verification tooling that refuses "policy-only" replay when state binding
  is absent

## External design references

These are useful supporting ideas for SeedCore's direction:

- OPA bundle discipline and signed bundle distribution:
  [Open Policy Agent documentation](https://www.openpolicyagent.org/docs/latest/management-bundles/)
- strict authorization schema validation:
  [Amazon Verified Permissions policy store schema](https://docs.aws.amazon.com/verifiedpermissions/latest/userguide/schema.html)
- causal consistency tokens for authorization state:
  [Zanzibar paper, section on zookies and snapshot reads](https://www.usenix.org/system/files/atc19-pang.pdf)

SeedCore should not copy any one of these systems literally. The useful lesson
is the combination:

- immutable policy bundle
- strict typed request schema
- explicit consistency token or snapshot binding
- fail-closed decision path

## Bottom line

If we want PKG snapshots to "seriously and precisely" match
Agent-Governed Restricted Custody Transfer, the most important change is not
adding more generic rules.

That first milestone is now complete in shadow-safe form. The next important
change is making each RCT-governing snapshot an explicit, versioned authority
contract with:

- a frozen schema
- a frozen taxonomy
- a compiled decision artifact
- a provable state binding
- and a clean separation between capability, authority, and evidence

That gives SeedCore the most efficient and accurate model while still evolving
under safe principles.
