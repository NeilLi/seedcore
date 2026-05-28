# Verifying Delegation In Frontier Autonomous AI Architectures

Date: 2026-05-18  
Status: Development thesis and architecture alignment memo  
Scope: SeedCore Agent Action Gateway, owner delegation, compiled authorization
graphs, execution tokens, delegated intent envelopes, and future cryptographic
hardening.

## Thesis

SeedCore's delegation model should be understood as a cryptographic intent
boundary for autonomous agents, not as a conventional login or service-account
permission check.

The core claim is:

> A governed agent action is admissible only when SeedCore can reconstruct a
> complete authority chain: agent identity, owner binding, delegation record,
> policy snapshot, approval envelope, physical or hardware scope, and replayable
> evidence. Authentication alone never implies authority.

This is the same design pressure now showing up in emerging agent-identity
work: AI agents act asynchronously, call tools through MCP-like surfaces,
delegate work to other agents, and cross infrastructure domains where legacy
IAM loses authorization context. SeedCore's current implementation already
addresses this by making delegation explicit, graph-resolved, token-scoped, and
evidence-bound.

## Current SeedCore Implementation

The implemented delegation path has three layers.

### 1. Gateway Authority Chain

`seedcore.agent_action_gateway.v1` requires the request to carry the full
delegation chain:

- `principal.agent_id`
- `principal.role_profile`
- `principal.session_token` or `principal.actor_token`
- `principal.owner_id`
- `principal.delegation_ref`
- `principal.hardware_fingerprint`
- `approval.approval_envelope_id`
- `authority_scope.asset_ref`
- `security_contract.hash` and `security_contract.version`
- `request_id`, `idempotency_key`, and `requested_at`

The contract is documented in
[`agent_action_gateway_contract.md`](agent_action_gateway_contract.md). The
runtime path resolves owner and delegation facts in
`_resolve_owner_twin_snapshot_for_payload`, then includes the delegation-bearing
principal in `_canonical_gateway_payload_hash`. This makes idempotency replay
depend on the same authority chain, not just the same idempotency key.

Implementation anchors:

- `src/seedcore/api/routers/agent_actions_router.py::_resolve_owner_twin_snapshot_for_payload`
- `src/seedcore/api/routers/agent_actions_router.py::_canonical_gateway_payload_hash`
- `src/seedcore/api/routers/agent_actions_router.py::_apply_forensic_scope_guards`

### 2. OwnerTwin And DelegatedAuthority Policy

SeedCore models owner-granted authority through `OwnerTwin` and
`DelegatedAuthority`.

`DelegatedAuthority` carries:

- `assistant_id`
- `authority_level`: `observer`, `contributor`, or `signer`
- `scope`: explicit asset ids or `*`
- `constraints.allowed_zones`
- `constraints.required_modality`
- `constraints.max_value_usd`
- `requires_step_up`

The primary policy gate is
`src/seedcore/coordinator/core/governance.py::_evaluate_owner_delegation_policy`.
It denies or escalates before token minting when:

- the assistant is not delegated by the owner
- the asset is outside delegation scope
- the authority level is observer-only
- a contributor attempts a custody transition
- the target zone is outside delegated bounds
- required modality evidence is missing
- the requested value exceeds `max_value_usd`
- step-up review is required and not satisfied

This is the concrete SeedCore expression of "delegated authority, not ambient
authority."

### 3. Compiled Multi-Hop Authorization Graph

SeedCore also compiles relationship facts into `CompiledAuthzIndex`.

`CompiledAuthzIndex.resolve_subject_paths` walks authority links from the
principal through roles, organizations, facilities, zones, and delegation
edges. `can_access` evaluates permissions against the resulting subject set
and records the exact `authority_paths` used by the decision.

Those paths are surfaced through
`_authz_graph_decision_metadata`, so an allowed action can explain how it was
authorized, not merely that it was authorized.

Test anchors:

- `tests/test_action_intent.py::test_evaluate_intent_surfaces_phase2_multihop_authority_path`
- `tests/test_action_intent.py::test_evaluate_intent_denies_when_owner_delegation_max_value_exceeded`
- `tests/test_owner_context_preflight_endpoint.py::test_owner_context_preflight_predicts_trust_gaps`
- `tests/test_kafka_delegated_intent.py::test_build_delegated_intent_envelope_shape`

## Current Tech Stack

| Layer | Current SeedCore implementation | Role in delegation verification |
| :--- | :--- | :--- |
| External contract | Agent Action Gateway v1 | Carries identity, owner, delegation, hardware, approval, scope, policy, and replay anchor in one request. |
| Owner authority model | `OwnerTwin`, `DelegatedAuthority`, identity facts | Converts durable owner policy into runtime authority constraints. |
| Policy gate | `evaluate_intent`, `_evaluate_owner_delegation_policy` | Deterministically denies, escalates, or allows before any execution authority is minted. |
| Relationship graph | `CompiledAuthzIndex`, `AuthzGraphCompiler` | Resolves multi-hop authority paths and matched policies. |
| Runtime authority | short-lived `ExecutionToken` | Carries scoped constraints and execution preconditions after policy allows. |
| Delegated async execution | `_mint_delegated_subtoken`, `DelegatedIntentPayload`, Kafka envelope | Narrows authority for a downstream delegate and binds it to the gateway request. |
| Replay and evidence | policy receipt, governed receipt, evidence bundle, replay artifacts | Preserves the decision and execution chain for forensic review. |
| Hardware binding | `principal.hardware_fingerprint`, endpoint constraints, HAL proof path | Binds agent authority to accountable execution substrate and actuator scope. |

Local performance measured on 2026-05-18 using `deploy/local/host-env.sh`:

| Path | p50 | p95 | p99 |
| :--- | ---: | ---: | ---: |
| `evaluate_intent` default policy path including token mint | 13.826 ms | 17.254 ms | 24.769 ms |
| `evaluate_intent` Rust policy path including token mint | 20.980 ms | 28.918 ms | 56.910 ms |
| isolated Rust `mint_execution_token_with_rust` | 6.357 ms | 10.047 ms | 18.131 ms |

The local host-mode TTL was `SEEDCORE_EXECUTION_TOKEN_TTL_SECONDS=900`, and
all measured allow paths returned an execution token.

## Alignment With Frontier Agent Identity Work

This section maps SeedCore's implemented stack to external architecture
directions. These are alignment points, not claims that SeedCore already
implements each standard.

### WIMSE And AI Agent Authentication

The IETF `draft-klrc-aiagent-auth` is an active Internet-Draft. It frames AI
agent identity and authorization as a composition of existing building blocks
such as workload identity, OAuth, and proof-bearing authentication. It has no
formal RFC standing yet.

SeedCore alignment:

- `principal.agent_id` and `principal.owner_id` are the local equivalents of
  stable actor and delegated subject identifiers.
- `OwnerTwin` is the durable identity and policy object that carries owner
  context into evaluation.
- `_resolve_owner_twin_snapshot_for_payload` maps transient gateway calls to
  persisted identity facts.
- `ExecutionToken` acts as the short-lived runtime authorization grant after
  policy admits the action.

Near-term enhancement:

- Add optional SPIFFE-style subject fields to `principal` and governed receipts.
- Carry WIMSE-style proof-token thumbprints in `governed_receipt` and replay
  artifacts.

### AIP, IBCTs, Biscuit, And Capability Attenuation

The AIP paper proposes Invocation-Bound Capability Tokens with two forms:
compact JWT-like tokens for single-hop calls and chained Biscuit-style tokens
for multi-hop delegation. Biscuit itself supports decentralized verification,
offline attenuation, and Datalog-based authorization.

SeedCore alignment:

- `ExecutionToken` is already a constrained capability, not an ambient bearer
  permission.
- `_mint_delegated_subtoken` narrows the parent token for delegated execution.
- `DelegatedAuthority.constraints` maps naturally to attenuated capability
  checks: zones, asset scope, modality evidence, value cap, and step-up state.
- `DelegatedIntentPayload` preserves owner preflight and gateway request
  alignment for asynchronous execution.

Near-term enhancement:

- Add an experimental `capability_chain` field to delegated execution metadata.
- Encode delegated subtoken caveats as a structured block that can later map to
  Biscuit Datalog checks.
- Preserve current Rust `ExecutionToken` as the stable runtime grant while
  evaluating Biscuit or AIP-style chained tokens as an optional proof layer.

### ReBAC, Zanzibar, And Graph Authorization

Google Zanzibar demonstrated relationship-tuple authorization at very large
scale. SeedCore does not run Zanzibar or SpiceDB today, but its compiled authz
graph is already ReBAC-shaped.

SeedCore alignment:

- `AuthzGraphCompiler` consumes authority edges into `authority_links`.
- `resolve_subject_paths` computes reachable subjects from the principal.
- `can_access` evaluates permissions and records the exact authority path.
- `_authz_graph_decision_metadata` makes the path replay-visible.

Near-term enhancement:

- Add a reverse lookup report: "which agents can authorize this asset under
  snapshot X?"
- Add bounded path-depth and path-count limits to protect hot-path latency.
- Export compiled graph tuples in a Zanzibar/SpiceDB-compatible diagnostic
  format for comparison and partner review.

### Cedar And Formal Policy Analysis

AWS Cedar is a policy language and authorization engine with a formal-methods
orientation. It can express RBAC, ABAC, and relationship-like authorization
patterns and is designed for automated reasoning.

SeedCore alignment:

- `_evaluate_owner_delegation_policy` is currently executable Python policy.
- The rule set is small, deterministic, and well suited to pre-deployment
  analysis.

Near-term enhancement:

- Produce a Cedar-style mirror policy for owner delegation gates.
- Add static checks that prove observer delegations cannot authorize custody
  transfer and value caps cannot be bypassed.
- Keep Python as the production evaluator until parity tests prove the mirror.

### SCITT And Signed Authorization Evidence

The IETF SCITT architecture defines signed statements and transparency receipts
for auditability and accountability. A 2026 WIMSE authorization-evidence draft
proposes a Permit record for WIMSE-authorized AI agent actions. That draft is
also an Internet-Draft, not a final standard.

SeedCore alignment:

- `policy_receipt`, `governed_receipt`, `evidence_bundle`, and replay artifacts
  already provide durable evidence around the transient execution token.
- `_canonical_gateway_payload_hash` is the natural `binding_request_hash`.
- Closure records can act as the post-execution evidence pair for an
  authorization Permit.

Near-term enhancement:

- Add optional `permit_id` and `binding_request_hash` fields to governed
  receipts and delegated subtokens.
- Produce a SCITT-compatible signed authorization-evidence artifact alongside
  existing replay bundles.
- Bind Kafka delegated-intent envelopes to Permit ids for asynchronous audit.

### Hardware-Backed Intent

SeedCore currently requires hardware accountability fields in the gateway
contract and carries endpoint/hardware constraints into execution tokens. This
is the foundation for future TEE or TPM-backed intent verification.

SeedCore alignment:

- `principal.hardware_fingerprint` binds the agent claim to a physical or
  device-rooted identity.
- execution preconditions carry `endpoint_id`, `plan_dag_hash`, and
  `payload_hash`.
- HAL/evidence paths attach actuator and telemetry proof after execution.

Near-term enhancement:

- Add a typed `attestation_document_ref` under `hardware_fingerprint`.
- Require signer policy to distinguish software, TPM, KMS, and TEE-backed
  attestations.
- Treat missing or stale hardware attestation as a trust gap before token
  minting for high-risk workflows.

## Recommended Documentation And Implementation Increments

1. Keep `agent_action_gateway_contract.md` as the strict external contract.
   This memo should be the strategic explanation and roadmap, not the schema
   authority.

2. Use `agentic_delegation_control_plane.md` as the recursive-delegation
   architecture layer for root context anchoring, signed agent capability
   credentials, per-hop attenuation, visible tool activity, out-of-band
   approval, and child-run closure.

3. Extend `policy_gate_matrix.md` with owner-delegation gates:
   missing delegation, revoked delegation, scope mismatch, observer-only,
   contributor custody transition, zone mismatch, modality missing, value cap,
   and step-up required.

4. Add a `delegation_proof` section to replay artifacts:
   authority path, owner context hash, delegation id, binding request hash,
   hardware fingerprint id, and execution token id.

5. Add a partner-facing "frontier alignment" appendix:
   WIMSE identity, AIP capability chain, ReBAC graph path, SCITT Permit,
   hardware attestation, and future formal verification.

6. Add a shadow-mode capability-chain experiment:
   generate a chained proof artifact in parallel with today's
   `ExecutionToken`, verify it offline, and compare denial behavior before
   any runtime dependency is introduced.

## Source Notes

Primary external references used for this memo:

- CSA / Okta, "Control the Chain, Secure the System: Fixing AI Agent
  Delegation"
  https://cloudsecurityalliance.org/blog/2026/03/25/control-the-chain-secure-the-system-fixing-ai-agent-delegation
- IETF `draft-klrc-aiagent-auth`: AI Agent Authentication and Authorization  
  https://datatracker.ietf.org/doc/draft-klrc-aiagent-auth/
- IETF `draft-munoz-wimse-authorization-evidence`: Signed
  Authorization-Evidence Records for WIMSE-Authorized AI Agent Actions  
  https://datatracker.ietf.org/doc/draft-munoz-wimse-authorization-evidence/
- AIP arXiv preprint: Agent Identity Protocol for Verifiable Delegation Across
  MCP and A2A  
  https://arxiv.org/abs/2603.24775
- Biscuit official documentation  
  https://www.biscuitsec.org/  
  https://doc.biscuitsec.org/reference/datalog.html
- Zanzibar paper  
  https://www.usenix.org/system/files/atc19-pang.pdf
- AWS Cedar overview  
  https://docs.aws.amazon.com/prescriptive-guidance/latest/saas-multitenant-api-access-authorization/cedar.html
- IETF SCITT architecture  
  https://datatracker.ietf.org/doc/draft-ietf-scitt-architecture/
