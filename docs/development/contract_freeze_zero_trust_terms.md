# Contract Freeze: Zero-Trust Runtime Terms

This document freezes the core runtime terms for the current SeedCore baseline so architecture, code, and future specs use the same boundary definitions.

The purpose of this freeze is to prevent contract drift between:

- proposal-time AI envelopes
- authorization-time governance artifacts
- execution-time evidence artifacts
- export/view representations

## Status

Accepted for the current baseline.

## Decision

SeedCore MUST use the following terms consistently.

### 1. `TaskPayload` = Proposal

`TaskPayload` is the proposal and routing envelope.

It carries AI-generated or system-generated execution intent into the runtime, including:

- routing constraints
- interaction metadata
- cognitive controls
- tool call requests
- multimodal metadata references

`TaskPayload` is not an authorization artifact.

`TaskPayload` is not forensic truth.

`TaskPayload` is not the replay artifact.

### 2. `ActionIntent` = Accountable Authorization Request

`ActionIntent` is the accountable execution request derived from `TaskPayload` for governed actions.

It consolidates principal, action, resource, validity window, and security contract into a deterministic policy input.

`ActionIntent` is the required bridge between proposal-time AI intent and policy-time evaluation.

### 3. `ExecutionToken` = Execution Authorization

`ExecutionToken` is the authorization artifact emitted by the Policy Decision Point after a valid `ActionIntent` is allowed.

It is the only artifact that may unlock controlled physical or actuator-bound execution.

Routing decisions, assigned agents, or planner outputs must never be treated as substitutes for `ExecutionToken`.

### 4. `EvidenceBundle` = Evidence

`EvidenceBundle` is the baseline forensic evidence artifact produced after execution.

It binds execution back to:

- the governed intent
- the issued token
- telemetry captured during execution
- execution receipts and endpoint responses

`EvidenceBundle` is evidence, not proposal.

### 5. JSON-LD = Export / View Layer

JSON-LD artifacts such as `SeedCoreCustodyEvent` belong to the export, presentation, interchange, or replay-view layer.

They may be materialized from internal runtime artifacts such as:

- `EvidenceBundle`
- governed execution audit records
- transition receipts
- other sealed evidence records

JSON-LD is not the core runtime contract for proposal intake or policy evaluation.

## Frozen Transformation Path

The current baseline path is:

```text
TaskPayload -> ActionIntent -> PolicyDecision/ExecutionToken -> EvidenceBundle -> JSON-LD export/view
```

For governed execution:

1. `TaskPayload` enters the runtime as the proposal envelope.
2. The coordinator derives `ActionIntent`.
3. The Policy Decision Point evaluates `ActionIntent`.
4. On allow, the Policy Decision Point emits `ExecutionToken`.
5. The execution layer performs the action.
6. The runtime attaches `EvidenceBundle`.
7. Optional export/materialization may transform evidence into JSON-LD or replay-friendly views.

## Boundary Rules

The following rules are frozen for the current baseline.

### Proposal Boundary

- `TaskPayload` MAY contain multimodal metadata and AI-supplied context.
- `TaskPayload` MUST be treated as untrusted for governed physical execution until transformed into `ActionIntent` and evaluated by policy.

### Authorization Boundary

- `ActionIntent` is the canonical policy input for governed action evaluation.
- `ExecutionToken` is the only canonical authorization output for controlled execution.
- Router output, agent assignment, or cognitive planning MUST NOT authorize physical execution.

### Evidence Boundary

- `EvidenceBundle` is produced after execution and records what happened.
- Evidence MUST remain downstream of authorization.
- Evidence artifacts MUST NOT be used to redefine or overwrite the original proposal contract.

### Export Boundary

- JSON-LD materialization is downstream of evidence generation.
- JSON-LD export MUST be derived from evidence and audit artifacts, not directly from `TaskPayload` alone.

## Explicit Non-Goals

This contract freeze does not:

- redefine the internal schema of `TaskPayload`
- require JSON-LD as the internal runtime format
- make hardware-rooted signing mandatory for the current baseline
- replace the current `EvidenceBundle` with a different artifact name
- introduce a persistent digital twin service

## Naming Guidance

To reduce ambiguity in docs and code reviews:

- use "proposal" when referring to `TaskPayload`
- use "authorization request" when referring to `ActionIntent`
- use "authorization artifact" when referring to `ExecutionToken`
- use "evidence artifact" when referring to `EvidenceBundle`
- use "export" or "replay view" when referring to JSON-LD materializations

Avoid calling `TaskPayload` a:

- certified frame
- forensic snap
- evidence bundle
- replay artifact

If "Certified Frame" or "Forensic Snap" is used in future product language, it should refer to an evidence/export artifact derived after execution, not to the proposal envelope.

## Rationale

The current baseline cleanly separates:

- intent capture
- policy evaluation
- execution authorization
- execution evidence
- external replay/export views

Freezing these definitions preserves the zero-trust boundary and prevents proposal-time data from being mistaken for forensic truth.

## References

- `TaskPayload` model: `src/seedcore/models/task_payload.py`
- Governance path: `src/seedcore/coordinator/core/governance.py`
- Evidence artifact: `src/seedcore/models/evidence_bundle.py`
- Evidence assembly: `src/seedcore/ops/evidence/builder.py`
- JSON-LD/export seed model: `src/seedcore/hal/custody/forensic_sealer.py`
- Governed audit persistence: `src/seedcore/models/governance_audit.py`
- Demo contract: `docs/development/end_to_end_governance_demo_contract.md`
