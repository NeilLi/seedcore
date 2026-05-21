# Gated Action DX Layer

Date: 2026-05-17
Status: Priority 30-day MVP spec for autonomy-ready developer experience; not yet implemented as `seedcore.sdk`

## Purpose

SeedCore's trust-runtime machinery is intentionally strict: delegated authority,
PDP evaluation, short-lived execution tokens, evidence bundles, receipts,
verifier outcomes, quarantine, and replay. That is the right internal shape.

It should not be the shape every application developer has to wire manually.
It also should not be the shape every coding agent has to rediscover from
source files before it can safely add a governed endpoint.

In the target shape, the Gated Action DX layer gives developers a simple way to
declare:

```text
this action is governed
this policy boundary applies
this evidence is required
this fail-closed behavior applies
```

SeedCore then performs the authority, evidence, verification, and replay work
underneath.

Compressed message:

> Developers should not manually wire cryptographic proof chains. They should
> declare the policy boundary, and SeedCore should enforce it.

## Autonomy-Ready Role

The DX layer is now the first practical bridge between SeedCore and the coming
AI-assisted development loop.

Coding agents should be able to:

- identify that a new endpoint or function is a governed action;
- declare the policy, evidence, and fail-closed boundary;
- generate a gateway/evaluate payload shape and schema scaffolding;
- generate or update OPA/PDP gate inputs without inventing authority semantics;
- run preflight and fixture checks before any enforce-mode path exists;
- return replay/audit references for human and agent review.

The boundary remains strict:

```text
The decorator declares governance.
It does not grant authority.
Only PDP allow can produce a scoped ExecutionToken.
Only evidence closure and replay can settle the outcome.
```

This keeps the DX layer useful for autonomous coding agents while preventing it
from becoming an alternate authorization path.

## Baseline Reality Check

As of 2026-05-21, this document is a **specification and immediate
implementation target**, not a shipped SDK surface.

Implemented baseline to build on:

- strict Agent Action Gateway v1 request/response models:
  `src/seedcore/models/agent_action_gateway.py`
- runtime gateway routes for evaluate and execute:
  `src/seedcore/api/routers/agent_actions_router.py`
- RCT reference adapter that constructs validated gateway evaluate payloads:
  `src/seedcore/adapters/rct_agent_action_gateway_reference_adapter.py`
- commerce-shaped mapping for `product_ref`, `quote_ref`,
  `declared_value_usd`, and `economic_hash`:
  `src/seedcore/adapters/shopify_sandbox_commerce_adapter.py`
- MCP/plugin wrappers for `seedcore.agent_action.evaluate` and
  `seedcore.agent_action.execute`:
  `src/seedcore/plugin/mcp_server.py`
- productization coverage:
  `tests/test_agent_action_gateway_productization.py`

Not implemented yet:

- no `src/seedcore/sdk/` package;
- no `from seedcore.sdk import gated_action` import path;
- no Python decorator that converts an arbitrary function call into a gateway
  evaluate request;
- no automatic OPA/PDP schema generation from a decorator declaration;
- no enforce-mode switch or promotion workflow for decorated actions.

Until those pieces land, references to `@gated_action(...)` are target API
examples. The only current executable path is the lower-level gateway/MCP
evaluate path listed above.

## Non-Goal

This spec does not replace the Agent Action Gateway, `ActionIntent`, PDP,
`ExecutionToken`, `EvidenceBundle`, `RESULT_VERIFIER`, or replay surfaces.

It is a developer-facing abstraction over those existing contracts.

This spec also does not freeze the final public SDK API. The examples below are
target shapes for a 30-day MVP and should stay narrow until tested against real
integration work.

## Core Principle

AI intent should not automatically become execution authority. SeedCore controls
when authority exists.

The DX layer should make that principle easy to use:

```text
developer declares boundary
SeedCore assembles request
SeedCore evaluates authority
SeedCore mints bounded execution token only if allowed
SeedCore collects evidence
SeedCore verifies closure
SeedCore exposes replay
```

## Target Developer Experience

### Target Python decorator shape

```python
from seedcore.sdk import gated_action


@gated_action(
    policy="strict_custody",
    evidence_required=["origin_scan", "delivery_scan"],
    fail_mode="quarantine",
)
def transfer_asset(intent):
    ...
```

Expected developer meaning:

- `policy="strict_custody"` selects the policy template or policy snapshot
  family SeedCore will enforce.
- `evidence_required=[...]` declares the evidence classes that must be present
  before closure can be accepted.
- `fail_mode="quarantine"` tells SeedCore how to fail closed when policy,
  evidence, or verification does not pass.

Expected SeedCore behavior:

1. convert the call into a strict gateway/evaluation payload;
2. bind principal, owner/delegation, workflow, asset, scope, and hardware
   context;
3. evaluate the request through the PDP/hot path;
4. deny, quarantine, or escalate if authority is absent;
5. mint a short-lived `ExecutionToken` only on allow;
6. execute or hand off to the governed execution path;
7. collect signed evidence and transition receipts;
8. build an `EvidenceBundle`;
9. run verifier/replay checks;
10. return an outcome with replay references.

### Platform annotation shape

For platform-managed services, the same intent should be expressible through
metadata:

```yaml
seedcore.io/gated-action: strict_custody
seedcore.io/evidence-required: origin_scan,delivery_scan
seedcore.io/fail-mode: quarantine
```

Expected platform meaning:

- this endpoint, job, route, or worker action is not ordinary application code;
- the action must cross the SeedCore authority boundary before execution;
- evidence and replay are part of the contract, not optional logging.

## Mapping To Existing SeedCore Internals

| DX declaration | Existing SeedCore concept |
| --- | --- |
| `policy` | PKG snapshot, policy rule family, `security_contract`, PDP/hot-path mode |
| `evidence_required` | evidence requirements, signed telemetry refs, `EvidenceBundle` inputs, verifier expectations |
| `fail_mode` | governed outcome: `deny`, `quarantine`, or `escalate` |
| decorated call args | gateway payload, `TaskPayload`, or `ActionIntent` inputs |
| principal/delegation binding | Agent Action Gateway principal, owner context, delegation ref |
| scoped resource | gateway asset and `authority_scope` |
| execution admission | PDP allow + short-lived `ExecutionToken` |
| post-execution closure | transition receipt, evidence bundle, result verifier outcome |
| replay reference | verification API, replay API, trust/proof surface |

## Required Semantics

The DX layer must preserve these rules:

1. A decorated function or annotated service does not receive implicit authority.
2. Routing, planning, retrieval, memory, or model confidence must never become
   permission to execute.
3. The PDP remains the final request-time authority boundary.
4. Authority is bounded to principal, workflow, asset, scope, policy, hardware,
   and time.
5. Required evidence is part of the action contract.
6. Failure modes are governed outcomes, not exceptions hidden in app code.
7. Replay references are returned or persisted for every governed invocation.
8. Developers may add business logic, but must not bypass the generated
   authority/evidence envelope.

## Forbidden Developer Experience

Do not make developers manually:

- call the PDP directly for every action;
- mint or sign execution tokens;
- assemble cryptographic receipt chains by hand;
- decide whether an evidence bundle is replay-valid;
- translate verifier failures into quarantine state;
- manually stitch proof links into operator surfaces.

Also do not let the DX layer hide authority decisions behind a generic
successful function return. The outcome must remain visibly governed:

```json
{
  "decision": "quarantine",
  "reason_code": "delivery_scan_missing",
  "execution_token_id": null,
  "evidence_bundle_id": "evb_123",
  "replay_ref": "replay://workflow/rct_001"
}
```

## Minimal Contract Shape

The first MVP should return a small governed result object:

```json
{
  "request_id": "req_001",
  "workflow_id": "workflow_001",
  "decision": "allow",
  "reason_code": "allow",
  "execution_token_id": "tok_001",
  "evidence_bundle_id": "evb_001",
  "verification_status": "passed",
  "replay_ref": "replay://workflow/workflow_001",
  "audit_id": "audit_001"
}
```

For `deny`, `quarantine`, or `escalate`, `execution_token_id` should be absent
unless a prior token is being referenced for revocation or closure.

## 30-Day MVP

The first implementation should be deliberately small:

1. Implement a local Python decorator or wrapper around one existing
   restricted-custody transfer adapter path.
2. Support one policy label: `strict_custody`.
3. Support three evidence labels: `origin_scan`, `delivery_scan`,
   `signed_edge_telemetry`.
4. Support three fail modes: `deny`, `quarantine`, `escalate`.
5. Convert the decorated call into an existing Agent Action Gateway evaluate
   request.
6. Generate or validate the minimal gate schema needed by the PDP/OPA path:
   principal, delegation ref, asset, action, scope, policy label, required
   evidence, fail mode, and workflow correlation fields.
7. Start in preflight/shadow mode: return the evaluate result and contract
   scaffold without executing business logic.
8. Add enforce mode only after allow/deny/quarantine fixture behavior is green.
9. Return a governed result object with decision, reason code, evidence bundle
   ID, verification status, replay reference, and audit ID where available.
10. Add fixtures proving allow, deny, quarantine, and missing-evidence behavior.
11. Add one assistant-oriented fixture where a generated gated action is
    rejected for missing delegation rather than silently executing.

Do not start with a broad plugin framework, general workflow engine, or every
possible evidence type.

## Assistant Workflow Contract

For coding agents, the first safe workflow should be:

1. read the local declaration;
2. generate or update the schema scaffold;
3. call `seedcore.agent_action.evaluate` or the equivalent local preflight;
4. run the gated-action fixture tests;
5. propose a patch or PR with the proof/replay references attached;
6. wait for human/operator promotion before enforce mode is enabled.

An assistant must not:

- bypass the generated gateway/evaluate payload;
- mint or simulate an `ExecutionToken`;
- clear quarantine;
- treat passing business logic as proof that SeedCore allowed the action;
- switch a gated action from preflight/shadow to enforce without an explicit
  promotion gate.

## Acceptance Criteria

The MVP is useful when a developer can write one small governed action and get
the full SeedCore enforcement path without manually wiring the proof chain.

Acceptance tests should prove:

1. a gated action cannot execute without a valid delegated principal;
2. a gated action cannot execute outside its scoped asset/action boundary;
3. missing required evidence produces the configured fail mode;
4. allow produces a short-lived execution token;
5. closure produces or references an evidence bundle;
6. verifier failure returns or persists a governed quarantine outcome;
7. every invocation has an audit or replay reference;
8. direct business-logic success cannot override SeedCore denial.
9. generated schema scaffolding is deterministic for the same declaration;
10. preflight/shadow mode never executes business logic;
11. enforce mode cannot be enabled without explicit test/promotion evidence.

## Positioning

For developers:

```text
Declare the governed boundary. SeedCore enforces the proof chain.
```

For AI assistants:

```text
You may propose an action, but the gated action decides whether intent becomes
bounded authority.
```

For design partners and investors:

```text
SeedCore is powerful because the hard trust chain is real. It becomes usable
because developers can apply that trust chain declaratively.
```

## Related Documents

- [Agent Action Gateway Contract](agent_action_gateway_contract.md)
- [Asset-Centric PDP Hot Path Contract](asset_centric_pdp_hot_path_contract.md)
- [Hot Path Enforcement Promotion Contract](hot_path_enforcement_promotion_contract.md)
- [Q2 Audit Trail UI Spec](q2_2026_audit_trail_ui_spec.md)
- [RAG Evidence Bundle and Trace Contract](../architecture/contracts/rag_evidence_bundle_trace_contract.md)
