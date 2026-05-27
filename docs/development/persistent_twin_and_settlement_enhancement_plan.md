# Persistent Twin and Settlement Enhancement Plan

This note maps the next Persistent Twin and Settlement Track extensions onto the current SeedCore implementation.

The referenced research artifact (`persistent_twin_and_settlement_research_analysis.md`) was not present in this workspace at review time, so this plan is based on the report dimensions supplied in the task request plus the current code in:

- `src/seedcore/models/digital_twin.py`
- `src/seedcore/services/digital_twin_service.py`
- `src/seedcore/coordinator/dao.py`
- `src/seedcore/services/custody_graph_service.py`
- `src/seedcore/services/result_verifier_runtime.py`

## Current Baseline

SeedCore already has the right spine for persistent twins:

- `digital_twin_state` stores the current authoritative projection per `(twin_type, twin_id)`.
- `digital_twin_history` stores append-only version history.
- `digital_twin_event_journal` records normalized replay events.
- `DigitalTwinService.persist_relevant_twins_in_session()` applies generic event semantics and appends journal payloads with prior/result state bindings.
- `settle_from_evidence_bundle()` promotes `evidence_settled` snapshots to `AUTHORITATIVE` after evidence bundle and node-id checks.
- `ResultVerifierRuntime` polls `transition_recorded` and `evidence_settled` events from the Postgres journal.

The main gap is that settlement semantics are still generic. `evidence_settled` is treated as one path with a bundle check and endpoint/node match. The next version should make settlement types first-class, compose proof vectors across handoffs, and preserve append-only rollback/remediation semantics.

## Recommended Shape

### 1. Introduce typed settlement protocols

Add a protocol layer between `settle_from_evidence_bundle()` and the existing persistence path:

```text
DigitalTwinService.settle(...)
  -> SettlementRegistry.resolve(settlement_type)
  -> SettlementProtocol.verify(...)
  -> SettlementProtocol.apply(...)
  -> persist_relevant_twins_in_session(...)
```

Recommended protocol contract:

```python
class SettlementProtocol(Protocol):
    settlement_type: str

    async def verify(self, context: SettlementContext) -> SettlementVerification:
        ...

    def apply(self, snapshot: TwinSnapshot, verification: SettlementVerification) -> TwinSnapshot:
        ...

    def proof_package(self, context: SettlementContext, verification: SettlementVerification) -> dict:
        ...
```

Initial concrete protocols:

- `DeliverySettlement`: verifies execution evidence, transition receipt, expected endpoint, custody node, and result verifier readiness.
- `CustodyChangeSettlement`: verifies from/to custodian, zone transition, approval transition head, and custody graph continuity.
- `RollbackSettlement`: verifies compensating intent, target prior version, current head version, sealed downstream constraints, and physical/edge evidence such as shelf/zone coordinates.
- `RemediationSettlement`: verifies operator authorization, KMS-signed or hardware-backed operator certificate, incident reference, and bounded state mutation.

Each protocol should produce a self-contained `proof_package` stored in the event journal payload and referenced by `digital_twin_history`.

### 2. Replace binary settlement with proof vector accumulation

Current flow promotes a twin directly from `EXECUTED` to `AUTHORITATIVE` when an evidence bundle settles. Multi-handoff logistics needs a middle model:

```text
PENDING -> EXECUTED -> PENDING_SETTLEMENT -> AUTHORITATIVE
```

This does not necessarily require a new enum immediately. The low-risk path is to keep `revision_stage=PENDING` or `EXECUTED` and add structured governance/custody fields:

- `governance.proof_vector.status`: `PENDING`, `CONVERGED`, `FAILED`
- `governance.proof_vector.required_streams`: `economic`, `custody`, `telemetry`, `operator`
- `governance.proof_vector.observed_streams`: per-stream evidence refs and binding hashes
- `custody.pending_handoff_index`
- `custody.latest_sealed_handoff_index`
- `custody.sealed_versions`

Promotion to `AUTHORITATIVE` should happen only when all required proof streams converge under the settlement protocol for that handoff.

### 3. Enforce temporal sealing invariants

Add invariants before persistence updates a twin:

- A downstream handoff cannot commit unless the prior handoff is settled or explicitly compensated.
- Once handoff `N+1` is committed, handoff `N` history cannot be re-opened in place.
- Rollback/remediation must append a new history version with a compensating intent reference.
- Any event that changes custody must name a prior state binding and a result state binding.
- Any event that seals a handoff must store the sealing event id and version.

These checks belong in a small invariant component called from `persist_relevant_twins_in_session()` before `upsert_snapshot()`, not buried inside DAO code.

### 4. Model rollback as compensation, not mutation

Add a `RollbackIntent` or generic `CompensatingIntentEnvelope` model with:

- `intent_id`
- `compensates_event_id`
- `compensates_state_version`
- `target_state_version`
- `rollback_reason`
- `requested_by`
- `authorization_proof`
- `physical_verification`
- `policy_receipt`

The rollback result should be a new `digital_twin_history` version with:

- `change_reason=rollback_compensation`
- `event_type=rollback_settled`
- `governance.compensates`
- `governance.rollback_proof_package`

The prior history row remains immutable and verifiable.

### 5. Prepare for stream-native scaling behind an event sink abstraction

Do not migrate directly from Postgres polling to Kafka inside `DigitalTwinService`. First introduce an event sink abstraction:

```text
DigitalTwinEventSink
  - PostgresTwinEventSink: current `digital_twin_event_journal`
  - KafkaTwinEventSink: future `twin-events-stream`
  - CompositeTwinEventSink: dual-write migration window
```

Then move `ResultVerifierRuntime` from DAO polling to a consumer interface. This keeps today tests and local deployments intact while making Kafka a deployment choice.

For Kafka, partition by stable twin key:

```text
partition_key = "{twin_type}:{twin_id}"
topic = "twin-events-stream"
compacted_topic = "twin-current-state"
```

Redis or in-memory projections can then serve ultra-low-latency reads, with Postgres retained as the durable audit store during the transition.

## Implementation Phases

### Phase 1: Protocol boundary without schema churn

- Add settlement protocol classes under `src/seedcore/services/settlement/`.
- Keep existing `settle_from_evidence_bundle()` as a compatibility wrapper around `DeliverySettlement`.
- Store protocol verification and proof package in the existing event payload.
- Add tests for protocol selection, delivery settlement parity, and settlement rejection incidents.

### Phase 2: Proof vector and multi-handoff invariants

- Add proof vector helpers and temporal invariant checks.
- Extend custody graph transition ingestion to update handoff indexes and proof stream status.
- Add tests for multi-handoff convergence, upstream sealing, and rejection of stale handoff edits.

### Phase 3: Compensating rollback/remediation

- Add compensating intent models.
- Add `rollback_settled` and `remediation_settled` event types to update policy.
- Add PDP/result-verifier gates for rollback/remediation authority.
- Add tests proving history is appended, not rewritten.

### Phase 4: Stream abstraction and Kafka migration path

- Introduce `DigitalTwinEventSink`.
- Keep Postgres as the default sink.
- Add optional composite sink for dual write.
- Move result verifier intake to a consumer abstraction.
- Add projection reconciliation checks between Postgres, Kafka, and current-state cache.

## Suggested First PR

The best first PR is Phase 1 only:

- It has high architectural leverage.
- It avoids database migrations.
- It preserves existing behavior.
- It creates the clean insertion point for rollback, remediation, and proof vectors.

Acceptance criteria:

- Existing digital twin service tests still pass.
- `settle_from_evidence_bundle()` still promotes valid delivery evidence to `AUTHORITATIVE`.
- Invalid evidence still records `digital_twin_settlement_rejected` incidents.
- Event journal payloads include `settlement_type`, `verification`, and `proof_package`.
- The service can register additional settlement classes without editing the core settlement flow.
