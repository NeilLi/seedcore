# ADR 0010: Hardware-Anchored Telemetry as Execution Proof

- Status: Proposed
- Date: 2026-05-17
- Scope: High-consequence physical execution, signed edge telemetry, hardware-bound evidence, and verifier replay
- Related: [ADR 0001](./adr-0001-pdp-hot-path.md), [ADR 0003](./adr-0003-igx-thor-trusted-edge-profile.md), [ADR 0004](./adr-0004-result-verifier-runtime.md), [ADR 0005](./adr-0005-replayable-evidence-governed-state-transitions.md), [Agent Action Gateway Contract](../../development/agent_action_gateway_contract.md), [Hardware-Anchored Telemetry MVP Contract](../../development/hardware_anchored_telemetry_mvp_contract.md)

## Context

SeedCore already has a strong software authority boundary:

- delegated authority through the Agent Action Gateway
- deterministic PDP evaluation over pinned policy and bounded context
- short-lived `ExecutionToken` lifecycle
- signed receipts and evidence bundles
- replay and RESULT_VERIFIER enforcement

That boundary proves that SeedCore admitted a specific action under policy. It does not, by itself, prove that the real world executed the action correctly.

For high-consequence physical execution, a compromised cloud agent should not be able to fake successful execution by fabricating a report, replaying an old response, or claiming that a token was used correctly. Software tokens are necessary authority artifacts, but they are not sufficient physical proof.

SeedCore's stronger moat is the combination of:

```text
ExecutionToken lifecycle
+ hardware-bound signer
+ signed telemetry
+ asset/zone/workflow binding
+ verifier replay
```

The current repository already points in this direction. The Agent Action Gateway models hardware fingerprints and signed `telemetry_refs`; closure validates telemetry asset binding; `EvidenceBundle` carries telemetry references; replay materialization surfaces physical evidence; and ADR 0003 defines a trusted-edge profile. This ADR makes hardware-anchored telemetry a first-class execution-proof principle rather than optional hardening.

## Decision

For high-consequence physical execution, SeedCore shall treat software authority and hardware-witnessed execution proof as separate but linked requirements.

An `ExecutionToken` proves that SeedCore admitted a bounded action. Hardware-anchored signed telemetry proves that an approved edge endpoint witnessed or performed the corresponding physical event.

SeedCore shall require the execution proof chain for high-consequence physical workflows to bind:

1. the `ExecutionToken` or governed authority reference;
2. the hardware-bound signer or enrolled device identity;
3. the asset anchor;
4. the approved zone, coordinate, or custody scope;
5. the workflow and request identity;
6. the signed telemetry payload digest;
7. the verifier/replay outcome.

SeedCore shall fail closed when required hardware-anchored evidence is missing, stale, contradictory, signed by an untrusted key, bound to the wrong asset, or bound to the wrong zone/scope.

## Required Trust Chain

The target chain is:

```text
AI / Agent Intent
        |
        v
Agent Action Gateway
        |
        v
PDP allow over delegated authority + scoped asset/action
        |
        v
Short-lived ExecutionToken
        |
        v
Hardware-bound endpoint validates token and scope
        |
        v
Endpoint signs telemetry / closure evidence
        |
        v
EvidenceBundle binds token, signer, asset, zone, telemetry
        |
        v
RESULT_VERIFIER / replay verifies the chain
        |
        v
Accepted, denied, quarantined, or escalated governed outcome
```

## Threat Model

This ADR specifically addresses the case where a cloud-side agent, orchestrator, or assistant is compromised or simply wrong.

A compromised cloud agent may be able to:

- request an action;
- produce plausible text;
- claim a task succeeded;
- attempt to replay old payloads;
- fabricate unsigned telemetry;
- call application APIs with valid ambient credentials.

It should not be able to fake real-world execution because it lacks:

- the enrolled device key;
- the hardware-bound signer;
- the approved asset anchor;
- the current zone or coordinate evidence;
- the fresh telemetry chain;
- the verifier-accepted replay path.

## Scope

This ADR applies to high-consequence physical workflows, including:

- Restricted Custody Transfer;
- rare-shoe or other high-value collectible transfer scenes;
- robotics or edge-node actions that affect custody, safety, provenance, or settlement;
- physical-world evidence that gates governed state mutation.

This ADR does not require hardware-anchored telemetry for every low-risk read, advisory planning task, simulation-only workflow, or developer fixture.

## Rationale

SeedCore's category claim depends on controlling when AI intent becomes execution authority and proving whether the resulting physical chain held.

Software-only controls are not enough for that story. They can show that a token existed or that a service path was called, but they cannot prove that a specific trusted device observed the right asset in the right place at the right time.

Hardware-anchored telemetry makes the execution proof harder to fake. It ties digital authority to physical evidence through an enrolled signer and replayable telemetry chain.

This keeps SeedCore's trust model layered:

- PDP decides whether authority exists.
- `ExecutionToken` carries bounded authority.
- Hardware signer proves edge-originated evidence.
- `EvidenceBundle` binds authority and evidence.
- RESULT_VERIFIER checks whether the chain still holds.

## Consequences

Positive consequences:

- SeedCore has a stronger moat than software policy gates alone.
- A compromised cloud agent cannot easily fake physical execution.
- Device identity, asset identity, zone evidence, and telemetry become replay-visible.
- Trusted-edge work in ADR 0003 becomes directly connected to the core product story.
- Physical execution claims become easier to explain to customers, auditors, and design partners.

Negative consequences:

- Device enrollment, key rotation, and signer trust become core operational responsibilities.
- Fixture and simulator paths must clearly distinguish simulated signatures from production hardware evidence.
- Closure schemas and verifier logic must keep asset, zone, signer, and freshness checks aligned.
- Some workflows will need stronger edge hardware and provisioning before SeedCore can make production-grade claims.
- Missing telemetry may produce more quarantines until hardware capture paths are mature.

## Failure Modes

The hardware-anchored proof path must fail closed for:

- missing signed telemetry;
- missing signer key reference;
- untrusted or revoked signer;
- telemetry asset mismatch;
- telemetry zone or coordinate mismatch;
- stale telemetry;
- replayed telemetry nonce or payload;
- telemetry observed outside the authority window;
- token and telemetry workflow mismatch;
- payload hash mismatch;
- verifier replay mismatch.

## Non-Goals

- Move the final PDP decision onto the edge node.
- Treat hardware telemetry as a replacement for delegated authority or policy.
- Require IGX Thor for every deployment.
- Embed all raw sensor data into every evidence bundle.
- Freeze a final hardware vendor or attestation provider.
- Require production-grade hardware proof for local development fixtures.

## Alternatives Considered

- **Software token as sufficient proof:** Rejected. A token proves admission, not physical execution.
- **Cloud agent self-reporting:** Rejected. It is too easy for a compromised or mistaken agent to fabricate success.
- **Unsigned telemetry:** Rejected for high-consequence workflows because it cannot establish signer provenance or replay integrity.
- **Hardware-only trust at the edge:** Rejected. Hardware evidence must support SeedCore's PDP and replay model, not replace it.
- **Require trusted hardware everywhere immediately:** Rejected because it would slow development and pilot work. The requirement should be scoped to high-consequence physical workflows and rollout profiles.

## Acceptance Criteria

This ADR is satisfied when SeedCore can demonstrate:

1. a high-consequence physical action cannot be accepted on `ExecutionToken` alone;
2. signed telemetry is bound to the exact asset in the approved request;
3. signed telemetry is bound to an enrolled device or signer key;
4. signed telemetry is checked for freshness and authority-window compatibility;
5. zone or coordinate contradiction produces deny, quarantine, or escalation;
6. evidence bundles carry enough telemetry references to support replay;
7. verifier replay can detect missing, stale, mismatched, or replayed telemetry;
8. simulator/development evidence is visibly distinguishable from production hardware-anchored evidence.
