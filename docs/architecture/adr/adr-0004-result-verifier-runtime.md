# ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation

- Status: Accepted
- Date: 2026-04-07
- Scope: Restricted Custody Transfer (RCT) trust slice; post-decision verification and enforcement
- Related: [ADR 0001](./adr-0001-pdp-hot-path.md) (PDP remains stateless at decision time; this ADR covers **after-the-fact** verification), [Architecture Overview](../overview/architecture.md), [SeedCore 2026 Execution Plan](../../development/seedcore_2026_execution_plan.md)

## Context

SeedCore already materializes governed execution into durable audit rows, replay bundles, and a digital twin event journal. A gap remained: **proving** that settled artifacts still verify against the replay chain, and **enforcing** downstream safety if they do not, without relying on a human to open the verification UI.

Options considered for where verification runs and what triggers it:

- Coordinator-embedded background loops vs dedicated worker service
- Poll `digital_twin_event_journal` vs Kafka (or other bus) as the trigger
- Shadow-only observation vs immediate authoritative mutation (quarantine / failure lifecycle)

## Decision

1. **Host:** Run RESULT_VERIFIER as a **background runtime inside the Coordinator** service (Ray Serve deployment), started with coordinator lifecycle when enabled via `SEEDCORE_RESULT_VERIFIER_ENABLED`.

2. **Trigger (v1):** **Poll** `digital_twin_event_journal` for new rows with `event_type` in `transition_recorded`, `evidence_settled`. Advance a **durable watermark** in `result_verifier_runtime_state` so intake is restart-safe. Kafka (or other backbone) is **not** required for the first production slice.

3. **Work queue:** Persist jobs in `result_verifier_jobs` keyed by `event_journal_id` (idempotent enqueue). Workers claim with `FOR UPDATE SKIP LOCKED`. Outcomes are append-only in `result_verifier_outcomes`.

4. **Verification logic:** Reuse the same replay-chain path as `ReplayService` (Python verifiers + Rust chain verification), exposed as `verify_audit_record_for_result_verifier`, so operator/API replay and automated verifier stay aligned. The runtime materializes **source-preserving** replay bundles for Rust verification rather than re-sealing artifacts with fixture signatures.

5. **Enforcement:** On terminal mismatch, **immediately** mutate **authoritative** asset twin and custody: `verification_failed` (integrity-class) vs `verification_quarantined` (trust-class), set governance lockout marker `result_verifier_lockout`, set `authority_source=result_verifier`, revoke the specific `execution_token_id` in the Redis CRL when present, and block downstream RCT transfers via existing authoritative quarantine merge. **No automatic unquarantine in v1**; remediation is operator-driven.

6. **Scope (v1):** Automation applies to **restricted custody transfer** governed audit records only; non-RCT journal events may enqueue jobs but verify as no-op (outcome recorded, no twin mutation).

## Rationale

- Coordinator already holds session factories, `DigitalTwinService`, and governance DAO access; embedding avoids a second deployable and duplicate wiring for the first slice.
- Journal polling gives a single system-of-record cursor and matches the twin projection model without adding consumer lag semantics before they are needed.
- Fail-closed twin mutation closes the loop between “replay says bad” and “runtime will not keep transacting as if nothing happened.”

## Consequences

- Coordinator replicas must coordinate via **database locking** (`SKIP LOCKED`) so only one worker processes a job; multiple coordinator instances are safe for the worker pool.
- Operational playbooks must document **clearing quarantine** after legitimate remediation; absence of auto-unquarantine avoids silent re-enablement after partial fixes.
- Metrics on the coordinator tracker (`result_verifier_*`) become part of trust-slice observability.
- The current fail-closed loop revokes specific execution tokens only; it does **not** advance the global `revoked_before` cutoff.
- If coordinator CPU or isolation becomes an issue, the same DAO/runtime can be lifted into a separate process later without changing the schema or twin event vocabulary.

## Alternatives Considered

- **Kafka-triggered verifier:** Rejected for v1 to reduce moving parts; journal rows are already durable and ordered enough for polling + watermark.
- **Shadow-only verifier:** Rejected for this P0; the plan required immediate enforcement.
- **Dedicated microservice from day one:** Deferred; embedding ships faster and shares verification code paths.
