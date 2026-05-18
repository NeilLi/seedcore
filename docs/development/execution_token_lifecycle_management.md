# ExecutionToken Lifecycle Management

Date: 2026-05-18
Status: Development thesis and architecture alignment memo
Scope: Agent Action Gateway, PDP hot path, Rust token minting, delegated
subtokens, HAL execution, replay verification, result-verifier quarantine, and
candidate hardening work.

## Thesis

SeedCore should treat `ExecutionToken` as a deterministic capability artifact,
not as a login token, session credential, or model-issued permission.

The core rule is:

> Probabilistic agent reasoning may propose an action, but only deterministic
> policy evaluation may create execution authority.

The current baseline already follows this shape. An `ExecutionToken` is minted
only after the PDP admits a fully bounded `ActionIntent`; it is short-lived,
Rust-minted, constrained to exact execution preconditions, consumed by governed
execution paths, and checked again by replay and verifier machinery.

This memo adapts useful ideas from capability security, DPoP sender-constrained
tokens, OpenKedge-style intent/evidence chains, RATS remote attestation, and
transactional outbox reliability into the SeedCore documentation spine. It
separates implemented baseline behavior from candidate hardening work.

## Current Baseline

| Lifecycle layer | Current SeedCore baseline | Primary anchors |
| :--- | :--- | :--- |
| External intent boundary | Agent submits a full authority-bearing gateway request, not an ambient API call. | `agent_action_gateway_contract.md` |
| Deterministic PDP | `evaluate_intent` validates time, identity, source registration, owner delegation, approvals, cognitive policy, and authz graph. | `policy_gate_matrix.md`, `asset_centric_pdp_hot_path_contract.md` |
| Token mint point | Token exists only on admitted allow paths; preflight can withhold it. | `src/seedcore/coordinator/core/governance.py::_mint_execution_token` |
| Token format | `token_id`, `intent_id`, `issued_at`, `valid_until`, `contract_version`, `artifact_hash`, `signature`, `constraints`, `execution_preconditions`. | `src/seedcore/models/action_intent.py::ExecutionToken` |
| Constraint spine | Action, zone, asset, principal, registration ids, endpoint, plan hash, and payload hash are frozen into constraints. | `policy_gate_matrix.md` |
| Delegated execution | Parent token can be narrowed into a shorter-lived delegated subtoken for Kafka delegated-intent execution. | `agent_action_gateway_contract.md`, `kafka_delegated_intent_ingress.md` |
| Attempt vs closure | Token permits an attempt; hardware/signed telemetry and verifier replay decide whether closure settles. | `hardware_anchored_telemetry_mvp_contract.md` |
| Replay and proof | Allow-path replay requires execution-token presence and validity in the Rust replay chain. | `language_evolution_map.md`, `rust_workspace_proposal.md` |
| Revocation and quarantine | RESULT_VERIFIER fail-closed path attempts token revocation before quarantining authoritative twin state. | `result_verifier_quarantine_remediation_runbook.md` |

## Ten-Stage Lifecycle

### 1. Intent Intake

The lifecycle begins at `seedcore.agent_action_gateway.v1`.

The caller must provide:

- principal identity and identity proof
- owner id and delegation reference
- hardware fingerprint
- approval envelope reference
- transaction-specific authority scope
- policy snapshot or security contract
- forensic fingerprint components
- request id and idempotency key

This rejects ambient authority. A caller is not allowed because it is logged in;
it is allowed only if SeedCore can reconstruct the exact authority chain for the
specific action.

The useful theory from OpenKedge and Sovereign Agentic Loops is the same:
convert model output into a typed intent before any mutation authority exists.
For SeedCore, that typed intent is the gateway payload mapped into
`ActionIntent`.

### 2. Policy Preflight

The gateway maps the request to hot-path PDP input.

`evaluate_intent` checks:

- timestamp validity and intent freshness
- actor identity and actor-token requirements
- source registration and asset binding
- owner twin and `DelegatedAuthority`
- restricted custody transfer prerequisites
- approval envelope state and transition history
- cognitive policy assessment
- compiled authz graph decision and authority paths

This evaluation must remain deterministic, synchronous, and bounded. Memory,
retrieval, model confidence, or planner output may help assemble the request,
but they do not become policy truth.

### 3. Mint Decision

Minting is the transition from proposal to capability.

Current rule:

- `allow`: mint `ExecutionToken`
- `deny`: no token
- `escalate`: no token until review completes
- `quarantine`: token behavior must remain deterministic for the workflow; the
  RCT Rust allow path mints only for Rust-authorized `allow`
- `options.no_execute=true`: evaluate policy and trust gaps, then strip
  `ExecutionToken` and `execution_context`

This gives planners a safe simulation path. They can ask "would this be
allowed?" without creating a live capability.

### 4. Temporal Bounding

The token lifetime is capped by the intent window and the runtime TTL:

```text
token.valid_until = min(
    action_intent.valid_until,
    now + SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS
)
```

Current code default is 300 seconds. Local performance work has used 900 seconds
for host-mode benchmark lanes where physical or simulated execution needs more
time.

This narrows time-of-check to time-of-use risk. A token cannot outlive the
policy window that produced it, and a stale intent fails before minting.

### 5. Token Shape

The baseline `ExecutionToken` is a capability-shaped object:

```text
token_id
intent_id
issued_at
valid_until
contract_version
artifact_hash
signature
constraints
execution_preconditions
```

`execution_preconditions` bind execution to:

- resource state hash
- approval transition head
- context token
- plan DAG hash
- payload hash
- endpoint id

The result is closer to Macaroons or Biscuit-style capability attenuation than a
normal bearer JWT, even though SeedCore's stable runtime artifact remains its
own Rust-minted `ExecutionToken`.

### 6. Constraint Freezing

The constraint spine is intentionally narrow and stable:

- `action_type`
- `target_zone`
- `asset_id`
- `principal_agent_id`
- `source_registration_id`
- `registration_decision_id`
- `endpoint_id`
- `plan_dag_hash`
- `payload_hash`

The goal is to prevent prompt drift and planner drift from becoming execution
drift. If the target asset, zone, endpoint, plan, or payload changes after the
PDP decision, the execution layer has a deterministic mismatch instead of an
ambiguous agent behavior problem.

### 7. Execution Binding And Delegated Subtokens

The gateway can bind the selected execution plan hash back into the token and
execution context.

For delegated async execution, `_mint_delegated_subtoken` narrows a parent token
into a child capability:

- shorter TTL, defaulting to 90 seconds with a 30-second floor
- delegated agent id
- delegated endpoint id
- inherited parent constraints
- new plan hash binding
- payload hash cleared when the downstream payload is not yet fixed

This is the right local seam for future attenuated-token experiments. The parent
authority must only shrink, never expand.

### 8. Attempt Vs Closure

For physical or high-consequence workflows:

```text
ExecutionToken permits an attempt.
Hardware-anchored telemetry proves physical closure.
Verifier replay decides whether the chain held.
```

The token is not settlement, custody truth, or physical proof. It says the
attempt was authorized under a specific policy snapshot and execution context.

Closure still needs telemetry references, signer checks, asset/zone alignment,
evidence bundle construction, and verifier acceptance.

### 9. Replay And Evidence

The replay path turns transient authority into durable proof.

SeedCore already preserves policy receipt, execution token, transition receipt,
and evidence bundle artifacts for source-preserving verification. The Rust
replay chain validates execution-token presence and validity for allow-path
replay, so a missing or malformed token is a replay failure, not a soft warning.

OpenKedge's Intent-to-Execution Evidence Chain is a useful conceptual fit:

```text
intent
-> admitted context
-> policy decision
-> execution bounds
-> execution result
-> evidence / closure
-> replay verdict
```

SeedCore should keep the existing receipt and replay bundle model as the stable
runtime surface while using IEEC as vocabulary for cross-agent and partner
explanations.

### 10. Revocation, Quarantine, And Consistency

When RESULT_VERIFIER detects an integrity or trust mismatch, the lifecycle moves
to fail-closed remediation.

Current runbook sequence:

1. Attempt token revocation when an execution token is present.
2. Write an authoritative `verification_quarantined` twin mutation.
3. Persist immutable verifier outcome details for operator review.
4. Keep retrying if revocation or fail-closed infrastructure is unavailable.

SeedCore already has task-level outbox infrastructure elsewhere in the
coordinator. The token lifecycle should use the same reliability posture for
future revocation fanout: record revocation intent atomically with authoritative
state, then relay to Redis/Kafka/edge consumers with idempotent delivery.

## Theory And Tech Stack Adaptation

| External idea | What to adopt | Baseline status | Recommended SeedCore increment |
| :--- | :--- | :--- | :--- |
| DPoP / proof of possession | Bind token use to a key held by the caller or execution node. | Not currently modeled as RFC 9449 DPoP. Hardware fingerprint and signer fields provide adjacent binding. | Add optional `proof_of_possession` metadata: public key thumbprint, proof algorithm, nonce/jti, and request hash. |
| Macaroons | Treat constraints as caveats that can only restrict authority. | Constraints and subtokens already behave capability-like. | Add tests proving delegated subtokens cannot widen parent asset, zone, endpoint, or TTL. |
| Biscuit | Use Datalog-style attenuation and public-key verification as an optional proof layer. | Not runtime baseline. | Add experimental `capability_chain` metadata beside, not instead of, `ExecutionToken`. |
| IETF attenuating agent tokens draft | Standardize vocabulary for deriving narrower agent tokens across delegation chains. | Conceptual match through `_mint_delegated_subtoken`. | Map parent/child token lineage, attenuation reason, and delegate endpoint into governed receipts. |
| OpenKedge IEEC | Explain the full lifecycle as an intent-to-execution evidence chain. | SeedCore already has receipts, evidence bundles, and replay artifacts. | Add `ieec_stage` or equivalent labels to replay materialization for external audit readability. |
| RATS / remote attestation | Appraise execution node evidence before accepting closure. | Hardware signer and telemetry contracts exist; TPM/KMS/TEE posture is maturing. | Add typed `attestation_result_ref` and policy gates for stale, missing, or revoked attestation. |
| Transactional outbox | Avoid dual-write gaps when broadcasting revocation or quarantine. | Task outbox exists; token-revocation fanout should be treated as a target pattern unless verified per path. | Introduce a token-revocation outbox record and idempotent relay contract. |
| CWE-367 TOCTOU framing | Make time/state drift an explicit threat class. | TTL bounding and preconditions already address this. | Add TOCTOU test cases for state hash, approval head, plan hash, endpoint, and expired TTL. |

## Recommended Documentation Changes

1. Keep `agent_action_gateway_contract.md` as the external wire contract.
2. Keep `policy_gate_matrix.md` as the compact PDP truth table.
3. Use this memo as the lifecycle explanation and roadmap for token hardening.
4. Link `hardware_anchored_telemetry_mvp_contract.md` to RATS vocabulary when
   adding real attestation results.
5. Link `result_verifier_quarantine_remediation_runbook.md` to token-revocation
   outbox work when that implementation exists.
6. Keep `verifying_delegation_frontier_ai_architectures.md` focused on
   delegation; keep this memo focused on runtime capability lifecycle.

## Source Notes

These sources are used for architectural alignment. They do not mean SeedCore
implements each standard today.

- OpenKedge, "Governing Agentic Mutation with Execution-Bound Safety and
  Evidence Chains": https://arxiv.org/abs/2604.08601
- Sovereign Agentic Loops: https://arxiv.org/abs/2604.22136
- OAuth 2.0 Demonstrating Proof of Possession, RFC 9449:
  https://www.rfc-editor.org/rfc/rfc9449
- RATS Architecture, RFC 9334: https://www.rfc-editor.org/rfc/rfc9334
- Attenuating Authorization Tokens for Agentic Delegation Chains,
  Internet-Draft: https://datatracker.ietf.org/doc/draft-niyikiza-oauth-attenuating-agent-tokens/
- Macaroons paper: https://research.google/pubs/pub41892
- Biscuit Datalog and attenuation docs:
  https://doc.biscuitsec.org/reference/datalog.html
- CWE-367 TOCTOU: https://cwe.mitre.org/data/definitions/367.html
- Transactional outbox pattern:
  https://microservices.io/patterns/data/transactional-outbox
