# Persistent Twin Settlement for Real-World AI Operations

Date: 2026-05-27
Status: Development reference

This note distills the Persistent Twin and Settlement Track research into a
SeedCore-aligned architecture reference. It keeps the useful implementation
patterns for AI operating against real-world state.

The intended scope is practical:

- AI proposes or coordinates an action.
- SeedCore verifies authority, scope, and evidence.
- A real-world endpoint, operator, or device performs the action.
- The digital twin is settled only when enough trusted evidence converges.
- Corrections are appended as governed compensation, not hidden rewrites.

Cryptographic technology is in scope when it supports real-world trust:
signatures, hardware-backed keys, deterministic hashes, signed telemetry,
operator/device identity, and replay integrity.

## Design Posture

Persistent twin settlement should be treated as a general AI reliability
pattern for governed real-world action.

The useful abstraction is:

```text
AI intent
  -> policy and authority evaluation
  -> scoped execution token
  -> physical or platform action
  -> evidence capture
  -> settlement protocol
  -> authoritative twin update or governed compensation
```

This preserves SeedCore's core boundary:

- AI can reason, plan, and recommend.
- The PDP decides whether a governed action is admissible.
- Execution is token-scoped and endpoint-enforced.
- Evidence and replay explain what happened after execution.
- Persistent twins only become authoritative after settlement checks pass.

## Settlement Protocol

SeedCore already has the beginning of this shape in
`src/seedcore/services/settlement/`. The next direction is to keep settlement
pluggable through a small protocol interface:

```text
SettlementProtocol
  - verify(context) -> SettlementVerification
  - apply(snapshot, verification) -> TwinSnapshot
  - proof_package(context, verification) -> dict
```

The protocol should stay generic enough for AI workflows, but strict enough
that every high-consequence state change has deterministic replay semantics.

Recommended initial settlement classes:

| Settlement class | Real-world purpose | Core replay invariant |
| :--- | :--- | :--- |
| `DeliverySettlement` | Promote a physical delivery or execution result into authoritative twin state. | The delivered endpoint, telemetry, receipt, and expected scope all bind to the same action. |
| `CustodyChangeSettlement` | Record handoff between accountable people, services, facilities, or devices. | The sender had custody before the handoff, the receiver accepted it, and the sequence is continuous. |
| `RollbackSettlement` | Reverse the effect of a failed or invalid state transition without deleting history. | The rollback targets an eligible prior version and appends a compensating version. |
| `RemediationSettlement` | Resolve an anomaly through authorized human or automated review. | The correction is authorized, bounded, evidence-backed, and replay-visible. |

Each class should produce a self-contained settlement proof package. In
SeedCore terms, that package should contain enough canonical data for a
verifier to check:

- which twin was affected
- which prior state was expected
- which action or intent caused the transition
- which policy receipt or authorization allowed it
- which telemetry, receipt, operator action, or device evidence supported it
- which resulting state was committed
- which signature, hash, or hardware identity anchored the package

## Proof Vector Accumulation

Real-world AI actions often cannot be settled from one event. A custody transfer
may need policy approval, telemetry freshness, operator confirmation, and
recipient acceptance. A robotics action may need a token check, endpoint receipt,
camera or sensor evidence, and result verification.

Use a proof vector to represent this convergence:

```text
V = [
  authority,
  custody,
  telemetry,
  execution,
  operator_review
]
```

A twin can remain provisional while one or more required streams are missing:

```text
PENDING_SETTLEMENT if any required component is false
AUTHORITATIVE only when all required components converge
```

This model is useful for general AI implementation because it avoids both bad
extremes:

- promoting state too early because one signal looked good
- blocking the whole system while waiting for slow evidence

The implementation should allow each settlement type to declare its required
streams. For example:

- `DeliverySettlement`: authority, execution, telemetry
- `CustodyChangeSettlement`: authority, custody, execution
- `RollbackSettlement`: authority, target-version eligibility, remediation or
  physical-state evidence
- `RemediationSettlement`: authority, operator review, incident binding

## Cryptographic Integrity

Cryptographic mechanisms are useful here as integrity infrastructure. They
should be described in SeedCore docs only in that role.

Good SeedCore uses:

- signed policy receipts
- signed transition receipts
- signed hardware or edge telemetry
- stable hashes over canonical payloads
- prior-state and result-state bindings
- KMS, TPM, secure enclave, or HSM-backed identity for devices/operators where
  the deployment justifies it
- local verification of signatures and hashes where low-latency replay matters

The right language is:

```text
cryptographic integrity for real-world AI evidence
```

## Upstream History Locking

Persistent twins should keep append-only history. Once a downstream handoff or
state transition depends on an upstream state, earlier history should not be
edited in place.

The general invariant:

```text
When transition k commits, all prior transitions it depends on become sealed.
Corrections after that point must be compensating transitions.
```

This matches the direction in ADR 0005: SeedCore should preserve replayable
evidence for governed state transitions by recording prior-state and
result-state bindings.

An implementation can begin with simple chain fields in event payloads:

- `prior_state_binding`
- `result_state_binding`
- `causal_parent_refs`
- `sealed_handoff_index`
- `compensates_event_id`
- `compensates_state_version`

A full authenticated state tree is not required for the first version. The
important thing is to avoid schema and workflow choices that make future
portable verification impossible.

## Compensation Instead Of Hidden Mutation

Rollback and remediation should be forward-only. The system should never delete
or silently rewrite an incorrect twin state in order to make the current view
look clean.

Use a compensating intent envelope:

```text
CompensatingIntentEnvelope
  - intent_id
  - compensation_type: rollback | remediation
  - compensates_event_id
  - compensates_state_version
  - target_state_version
  - reason
  - requested_by
  - authorization_proof
  - evidence_refs
  - policy_receipt_ref
```

If approved, the runtime appends a new digital twin history version:

```text
original version:    DELIVERED
compensating event:  ROLLBACK_SETTLED
new current state:   REVERSED_COMPENSATED
```

The prior row remains part of the audit trail. Replay should show both the
mistake and the correction.

During compensation, the twin should be visible as `UNDER_COMPENSATION` or an
equivalent internal status so concurrent services can defer high-consequence
decisions until the compensating workflow finishes.

## Stream-Native Direction

The current Postgres-backed journal is the right operational baseline. It is
simple, inspectable, and already aligned with replay.

For scale, SeedCore can introduce an event sink abstraction before moving
settlement traffic to streams:

```text
DigitalTwinEventSink
  - PostgresTwinEventSink
  - KafkaTwinEventSink
  - CompositeTwinEventSink
```

The stream-native direction is:

- partition events by stable twin key
- preserve ordering for a single twin
- project current state into Redis or another fast read model
- keep durable history and replay data available for audit
- use snapshots only as recovery acceleration, not as a replacement for
  governed transition evidence

Kafka, Redis, and log compaction are therefore infrastructure choices, not
policy authorities. The PDP and settlement protocols remain the authority and
replay boundary.

## Documentation Decision

The original research should not be copied into SeedCore docs wholesale. It
mixes useful AI/state-machine ideas with material that does not support the
current real-world AI implementation path.

Keep these ideas:

- pluggable settlement protocols
- deterministic replay semantics
- asynchronous proof vector accumulation
- append-only twin history
- prior/result state bindings
- upstream sealing
- rollback and remediation as compensating workflows
- cryptographic integrity for receipts, telemetry, and operator/device identity
- optional stream-native scaling behind an event-sink abstraction

## Recommended Adoption Path

1. Keep `DeliverySettlement` as the compatibility path for current evidence
   settlement.
2. Make `CustodyChangeSettlement`, `RollbackSettlement`, and
   `RemediationSettlement` real protocol implementations only when the
   corresponding workflow has concrete evidence fields and tests.
3. Add proof-vector fields to event payloads before adding new database columns.
4. Add compensating intent models before allowing rollback/remediation to modify
   current twin state.
5. Keep Postgres as the default journal, then introduce a stream sink only after
   the protocol and replay contracts are stable.

This keeps SeedCore focused on the actual product category: governed AI actions
against real-world state, backed by evidence, policy, and replay.
