# Policy Gate Matrix (PDP Boundary)

This document freezes the expected behavior of the Policy Decision Point (PDP) boundary when evaluating an `ActionIntent` for a governed action (e.g., `RELEASE`).

The PDP enforces an explicit, synchronous, and non-LLM-driven evaluation path. Decisions are mathematically deterministic based on the provided intent and registered evidence.

## Evaluation Rules

| Scenario | Input Condition | Expected Decision | Explicit Deny Code / Reason |
| :--- | :--- | :--- | :--- |
| **Happy Path (Allow)** | Valid TTL (`> now`) + Approved Source Registration matching Asset | `ALLOW` | *(None. Emits `ExecutionToken`)* |
| **Expired TTL** | `valid_until <= now` or `ttl_seconds <= 0` | `DENY` | `expired_ttl` |
| **Missing Principal** | `principal` block is absent or empty | `DENY` | `missing_principal` |
| **Missing Registration** | `source_registration` evidence is missing from intent | `DENY` | `missing_source_registration` |
| **Unapproved Registration**| `source_registration.decision != 'APPROVED'` | `DENY` | `unapproved_source_registration` |
| **Mismatched Decision** | `source_registration.asset_id != intent.asset_id` | `DENY` | `mismatched_registration_decision` |

## Execution Token Generation

When an `ActionIntent` satisfies all conditions in the matrix above, the PDP emits an `ExecutionToken`. 

To ensure deterministic execution against the mock actuator, the `constraints` field of the token is strictly frozen in shape and order via `EXECUTION_TOKEN_CONSTRAINT_KEYS`. 

This guarantees the execution layer receives the exact same cryptographic bounds every time, removing prompt-drift from the execution loop.

For the full lifecycle view of intake, preflight, minting, TTL bounding,
delegated subtokens, execution binding, replay, and quarantine, see
`docs/development/execution_token_lifecycle_management.md`.

## Delegation And Owner Authority Gates

The Agent Action Gateway extends the PDP boundary from "valid principal" to
"verifiable delegated authority." Authentication alone is not sufficient for an
agent-originated action. The runtime must be able to reconstruct owner,
delegation, scope, approval, hardware, and policy context before execution
authority can be minted.

| Scenario | Input Condition | Expected Decision | Explicit Deny Code / Reason |
| :--- | :--- | :--- | :--- |
| **Missing Owner Delegation** | Owner twin contains delegations, but none match `principal.agent_id` | `DENY` | `owner_scope_violation` / `owner_delegation=missing` |
| **Delegation Scope Mismatch** | Matching delegation exists but `resource.asset_id` is outside `DelegatedAuthority.scope` | `DENY` | `owner_scope_violation` / `owner_delegation=scope_restricted` |
| **Observer-Only Delegation** | Matching delegation has `authority_level=observer` and action requires execution authority | `DENY` | `owner_observer_restricted` |
| **Contributor Custody Transition** | Matching delegation has `authority_level=contributor` and action attempts custody transition | `DENY` | `owner_observer_restricted` / `owner_delegation=contributor_transition_block` |
| **Delegated Zone Mismatch** | `resource.target_zone` is not included in `constraints.allowed_zones` | `DENY` | `owner_zone_violation` |
| **Missing Delegation Modality Evidence** | `constraints.required_modality` is not satisfied by available evidence modalities | `DENY` | `owner_modality_violation` |
| **Delegated Value Limit Exceeded** | Action value exceeds `constraints.max_value_usd` | `DENY` | `owner_value_limit_violation` |
| **Step-Up Required** | Delegation has `requires_step_up=true` and policy assessment is not `allow` | `ESCALATE` | `owner_step_up=true` |

Implementation anchors:

- `src/seedcore/coordinator/core/governance.py::_evaluate_owner_delegation_policy`
- `src/seedcore/coordinator/core/governance.py::_delegation_scope_allows`
- `src/seedcore/api/routers/agent_actions_router.py::_resolve_owner_twin_snapshot_for_payload`
- `docs/development/verifying_delegation_frontier_ai_architectures.md`

## Context Sufficiency Gates

ADR 0001 defines sufficient context as a deterministic precondition for
authorization. These gates happen before any `ExecutionToken` can be minted.
They are not advisory retrieval checks and should not trigger request-time
remote fan-out, LLM reasoning, or best-effort fallback.

| Scenario | Input Condition | Expected Decision | Explicit Deny Code / Reason |
| :--- | :--- | :--- | :--- |
| **Missing Required Context Field** | Policy class requires an approval, custody, telemetry, or signer field that is absent or untyped | `DENY` / `QUARANTINE` | `insufficient_context` |
| **Local View Behind Causality Token** | `context_freshness.local_view_version` cannot prove freshness at or beyond the request causality token | `QUARANTINE` | `context_freshness_breach` |
| **Invalid Mutation Receipt** | Causality-sensitive request references a missing, unsigned, expired, scope-mismatched, or session-mismatched mutation receipt | `DENY` / `QUARANTINE` | `mutation_receipt_invalid` |
| **Local Watermark Behind Receipt** | Signed mutation receipt requires sequence or log offset `N`, but the local context projection can prove only `< N` before the bounded barrier expires | `QUARANTINE` | `context_watermark_behind` / `replay_mismatch_fail_closed` |
| **Receipt Replay Outside Binding** | A previously valid receipt/token pair is replayed outside the bound session, workflow, proof-of-possession key, or short token epoch | `DENY` / `QUARANTINE` | `receipt_replay_detected` / `mutation_receipt_invalid` |
| **Freshness SLA Breach** | Telemetry, custody, approval, delegation, or device context exceeds its explicit freshness SLA | `QUARANTINE` | `stale_context` / `stale_telemetry` |
| **Invalid Signed Context Envelope** | Required context envelope has invalid signature, caveat, issuer, scope, or expiry | `DENY` / `QUARANTINE` | `invalid_context_envelope` |
| **Missing State Binding** | High-consequence path lacks replay-visible `state_binding_hash` inputs for accepted policy/context state | `QUARANTINE` | `state_binding_hash_missing` |
| **Context Package Complete And Fresh** | Schema complete, envelopes verified, causality satisfied, and SLA checks pass | Continue PDP evaluation | *(None)* |

Implementation anchors:

- `docs/architecture/adr/adr-0001-pdp-hot-path.md`
- `docs/development/asset_centric_pdp_hot_path_contract.md`
- `docs/development/freshness_sla_edge_stress_schedule.md`

Signed mutation receipts and local watermarks are the concrete SeedCore
extension of Zanzibar-style zookie semantics. A client-supplied token can demand
freshness, but the PDP path must verify the sequencer receipt and prove that its
local context view has converged to the required watermark before any allow
decision can mint an `ExecutionToken`.

## Recursive Agent Delegation Gates

The workflow v1 lane extends owner delegation into recursive agent handoffs.
These gates are architecture targets for the agentic delegation control plane;
they should be introduced behind workflow and capability-chain rollout flags
before becoming enforce-mode requirements.

| Scenario | Input Condition | Expected Decision | Explicit Deny Code / Reason |
| :--- | :--- | :--- | :--- |
| **Missing Delegation Lineage** | Child agent claims delegated authority without parent token, root context, or chain head | `DENY` | `delegation_lineage_missing` |
| **Scope Widened At Child Hop** | Child token or node adds asset, zone, endpoint, operation tier, tool, or TTL beyond the parent | `DENY` | `delegation_scope_widened` |
| **Delegate Identity Unverified** | Target child agent lacks valid identity/capability credential for the node operation | `DENY` | `delegate_identity_unverified` |
| **Delegation Depth Exceeded** | Node handoff exceeds policy-defined maximum recursive depth | `DENY` | `delegation_depth_exceeded` |
| **Context Anchor Mismatch** | Node action, asset, zone, endpoint, or goal class does not match the root context anchor | `DENY` / `ESCALATE` | `context_anchor_mismatch` |
| **Sensitive Action Missing OOB Approval** | Sensitive node relies on same-agent or chat-channel approval instead of an approval envelope | `ESCALATE` | `sensitive_action_missing_oob_approval` |
| **Hidden Mutating Tool Call** | Mutating tool call lacks visible policy receipt, execution token id, or replay event | `DENY` | `hidden_tool_call` |
| **Child Closure Timeout** | Delegated child run does not close before child TTL or parent workflow timeout | `QUARANTINE` / `ESCALATE` | `child_closure_timeout` |

Architecture anchor:

- `docs/development/agentic_delegation_control_plane.md`
