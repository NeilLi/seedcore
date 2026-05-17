# Gated Action DX Layer

Date: 2026-05-17
Status: Lightweight developer-experience spec

## Purpose

SeedCore's trust-runtime machinery is intentionally strict: delegated authority,
PDP evaluation, short-lived execution tokens, evidence bundles, receipts,
verifier outcomes, quarantine, and replay. That is the right internal shape.

It should not be the shape every application developer has to wire manually.

The Gated Action DX layer gives developers a simple way to declare:

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

### Python decorator shape

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
6. Return a governed result object with decision, reason code, evidence bundle
   ID, verification status, replay reference, and audit ID where available.
7. Add fixtures proving allow, deny, quarantine, and missing-evidence behavior.

Do not start with a broad plugin framework, general workflow engine, or every
possible evidence type.

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
