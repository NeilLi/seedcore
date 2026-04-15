# ADR 0005: Preserve Replayable Evidence for Governed Digital Twin State Transitions

- Status: Proposed
- Date: 2026-04-15
- Scope: Governed digital twin mutation, replay evidence, and multi-agent causality
- Related: [ADR 0001](./adr-0001-pdp-hot-path.md) (decision-time causality and freshness), [ADR 0004](./adr-0004-result-verifier-runtime.md) (post-decision verification and fail-closed mutation), [Architecture Overview](../overview/architecture.md)

## Context

SeedCore already has several pieces of a replay-grade trust runtime:

- signed `PolicyReceipt`, `TransitionReceipt`, and `EvidenceBundle` artifacts
- a computed `state_binding_hash` that binds authority decisions to bounded context
- append-only `digital_twin_history` and `digital_twin_event_journal` records
- replay materialization through `ReplayService` and offline verification through `seedcore-verify`

That baseline is strong, but it still leaves an architectural gap for **governed state transitions** on custody-aware digital twins.

For this ADR, a governed state transition is any authoritative mutation to a digital twin that matters to custody, safety, provenance, or settlement. Examples include:

- recording a restricted custody transfer
- changing a twin lifecycle or quarantine state
- appending environmental tracing for regulated goods such as wild honey or dry abalone
- promoting an execution result into authoritative twin state after verification

For these transitions, "evidence bundle" cannot mean only text logs plus a receipt. The verifier must be able to reconstruct:

- what state the system believed it was mutating from
- what action and intent it approved
- what policy receipt authorized the mutation
- what telemetry or media the system relied on
- what authoritative state mutation was actually committed
- which upstream agent attestations or approvals causally influenced the decision

The repository already leans in this direction. `EvidenceBundle` supports telemetry/media references and signed trust metadata; `state_binding_hash` already compacts intent, approval, custody, telemetry, and twin context; and the twin subsystem already keeps append-only history and an event journal. However:

- there is no first-class `prior_state_root` / `result_state_root` contract for each governed mutation
- the twin journal is append-only, but not yet an authenticated state tree with proof-capable roots
- cross-agent causality is partially visible through receipt and approval hashes, but not preserved as a formal causal graph for replay

This ADR sets a **future-direction target contract** for that next step. It is intentionally directional: it does not mean SeedCore must implement all of these capabilities in the next execution window, and it should not be read as invalidating the current replay baseline.

## Decision

1. **Directionally, governed twin mutation should converge on a replayable evidence bundle, not only a signed receipt.**

   The target architecture is that each authoritative digital twin mutation in the governed path can eventually be explained by a durable evidence package that binds prior state, approved action, policy approval, execution result, and observational evidence into one replay contract.

2. **Directionally, SeedCore should treat the replay unit as a state transition envelope, not just an evidence artifact.**

   The architectural replay unit for transition time `t` is:

   `E_t = Hash(S_{t-1} || A_t || P_receipt || Telemetry || Transition || Causality)`

   where:

   - `S_{t-1}` is the authoritative prior-state binding for the twin before mutation
   - `A_t` is the canonical action/intent and execution payload that was approved
   - `P_receipt` is the signed policy approval and associated decision snapshot binding
   - `Telemetry` represents the hashed or content-addressed sensory inputs and evidence references observed at decision/execution time
   - `Transition` represents the committed twin mutation and transition receipt
   - `Causality` represents replay-visible references to upstream approvals, receipts, or peer-agent evidence that influenced the mutation

   Existing `state_binding_hash` remains useful, but this ADR treats it as one component of a larger replay envelope rather than as the final end-state contract.

3. **Where physical-world evidence materially affects a governed mutation, evidence bundles should evolve to carry multi-modal bindings more explicitly.**

   For mutation paths that depend on physical-world evidence, the bundle schema should preserve:

   - hashed or content-addressed sensory inputs such as camera frames, LIDAR point clouds, weight readings, temperature traces, or signed HAL capture envelopes
   - semantic intent and execution payload identity
   - the approving `PolicyReceipt`
   - resulting `TransitionReceipt` or equivalent authoritative mutation receipt
   - the prior-state and resulting-state bindings for the twin

   SeedCore does not need to embed raw media in every bundle. The directional goal is durable, replay-stable references and hashes so the verifier can prove which evidence was in scope when that additional rigor is justified.

4. **Digital twin mutation history should remain append-only and gradually become state-root-capable where replay value justifies it.**

   `digital_twin_history` and `digital_twin_event_journal` remain the durable mutation log for v1/v2 rollout. They should evolve so each governed mutation can expose:

   - a deterministic prior-state binding or root
   - a deterministic resulting-state binding or root
   - the event hash or chain link that connects this mutation to the prior governed state
   - enough canonical material to recompute the transition during replay

   This ADR does **not** require immediate replacement of current Postgres-backed append-only storage with a full Merkle Patricia Tree. It only argues that new schema and artifact choices should avoid blocking an authenticated state-tree future.

5. **For high-consequence mutation paths, replay should move toward deterministic verification over state root, policy receipt, and evidence references.**

   The verifier path should be able to take:

   - the prior-state binding/root for `S_{t-1}`
   - the canonical action/intent payload
   - the policy receipt and snapshot bindings
   - the evidence bundle's telemetry/media hashes or references
   - the causal parent references

   and deterministically prove whether the resulting state `S_t` and transition receipts match what should have happened, but only after the relevant fields are intentionally adopted for that workflow.

6. **Cross-agent causality should be preserved as first-class replay metadata when multiple accountable agents materially influence a mutation.**

   When one accountable agent acts on another agent's attestation, approval, or evidence, the downstream mutation must record cryptographic parent references to the upstream evidence it relied on.

   SeedCore should model this as a causal DAG over governed evidence when the workflow truly needs that fidelity. Vector-clock-style metadata is an acceptable implementation aid for ordering and concurrency detection, but the architectural requirement is broader: replay should preserve causal parents, not just timestamps.

7. **Adoption is staged and selectively fail-closed for high-consequence mutation paths.**

   Rollout should proceed in phases:

   - Phase A: strengthen bundle/journal schemas with prior-state, result-state, and causal-parent fields
   - Phase B: make replay verification assert those fields for high-consequence custody-aware transitions
   - Phase C: add authenticated state-root proofs for journal/history views where proof portability is required across trust domains

   High-consequence flows should not silently downgrade to "best effort" replay once the stricter fields are intentionally declared mandatory for that path.

## Rationale

- SeedCore's category claim depends on proving why a governed physical-world mutation happened, not merely recording that it happened.
- Signed receipts alone are too thin for multimodal robotics and custody workflows; the verifier needs the sensory and causal context that informed the mutation.
- The current append-only twin journal is the right operational starting point because it already aligns with replay, fail-closed verification, and authoritative state promotion.
- Requiring state-root-capable artifacts now avoids schema dead ends if SeedCore later needs portable inclusion proofs, anchored roots, or third-party verification outside the primary database.
- Treating causality as first-class replay data matches the direction already established in ADR 0001 around freshness and causality tokens, but extends it from decision-time admissibility into post-decision state-transition auditability.
- Marking this ADR as `Proposed` keeps the current baseline intact: the purpose is to guide future changes, not to imply current inadequacy or force immediate platform-wide migration.

## Consequences

- Evidence and replay schemas will grow to include explicit prior-state/result-state and causal-parent fields for governed twin mutations.
- Some mutation paths will need canonicalization rules for telemetry/media references so their hashes remain stable across replay environments.
- The twin journal and history tables may gain chain-link or state-root columns before a full authenticated tree implementation exists.
- Verification code will need to distinguish between legacy replay bundles and stricter governed-transition bundles during rollout.
- Storage cost increases are expected because replay-grade physical-world evidence requires more references, hashes, and sometimes external content-addressed artifacts.

## Alternatives Considered

- **Keep current evidence bundles and rely on signed receipts plus `state_binding_hash`:** Rejected because this leaves prior state, resulting state, and multi-agent causality under-specified for authoritative twin replay.
- **Jump immediately to a Merkle Patricia Tree-backed twin store:** Rejected for now because it adds substantial implementation complexity before the replay contract fields are fully stabilized.
- **Rely only on timestamps and linear logs for agent-to-agent influence:** Rejected because time order alone is insufficient to prove causality in concurrent multi-agent workflows.
- **Store raw multimodal evidence inline in every bundle:** Rejected because content-addressed references and hashes are operationally more scalable while still preserving replay integrity.

## Small Backlog

The backlog below is intentionally small and non-binding. It separates the pieces most likely to improve the current restricted-custody replay boundary from the pieces that are useful later but not urgent now.

### Essential Now

- Add a lightweight `prior_state_binding` and `result_state_binding` field strategy for governed twin mutations, reusing current `state_binding_hash` and twin journal concepts rather than introducing a new storage system.
- Add a minimal causal-parent reference field for cases where one governed action directly depends on a prior signed approval, receipt, or evidence bundle.
- Extend replay verification/read models to surface those fields when present, while keeping legacy records valid.

## 3-Step Engineering Checklist

### 1. Add lightweight prior/result state bindings without changing the storage model

Start by introducing optional replay fields rather than a new authenticated state store:

- update [evidence_bundle.py](/Users/ningli/project/seedcore/src/seedcore/models/evidence_bundle.py) so governed artifacts can carry `prior_state_binding` and `result_state_binding` alongside the existing `state_binding_hash`
- update [replay.py](/Users/ningli/project/seedcore/src/seedcore/models/replay.py) so `ReplayRecord` can surface the same fields directly
- populate those fields in [builder.py](/Users/ningli/project/seedcore/src/seedcore/ops/evidence/builder.py) using the existing normalization logic in [state_binding.py](/Users/ningli/project/seedcore/src/seedcore/ops/evidence/state_binding.py)
- thread the values through twin persistence in [dao.py](/Users/ningli/project/seedcore/src/seedcore/coordinator/dao.py) where `DigitalTwinDAO._append_history` and `DigitalTwinEventJournalDAO.append_event` already define the append-only mutation seam
- if the team wants first-class columns instead of payload-only embedding, add them in a new migration adjacent to [127_digital_twin_event_journal.sql](/Users/ningli/project/seedcore/deploy/migrations/127_digital_twin_event_journal.sql)

### 2. Add minimal causal-parent references only for direct governed dependencies

Keep this narrow: one mutation should be able to point at the immediately relevant prior approval, receipt, or evidence bundle.

- add an optional `causal_parent_refs` field to governed evidence artifacts in [evidence_bundle.py](/Users/ningli/project/seedcore/src/seedcore/models/evidence_bundle.py)
- populate it only where the dependency is already known during assembly in [builder.py](/Users/ningli/project/seedcore/src/seedcore/ops/evidence/builder.py) and gateway closure handling in [agent_actions_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/agent_actions_router.py)
- persist those references with the twin event payload via [dao.py](/Users/ningli/project/seedcore/src/seedcore/coordinator/dao.py) rather than introducing a separate graph subsystem

### 3. Surface and verify the new fields opportunistically, without breaking legacy replay

The current replay path should remain valid for old records, while newer records expose stronger structure when available.

- extend replay assembly in [replay_service.py](/Users/ningli/project/seedcore/src/seedcore/services/replay_service.py) so `prior_state_binding`, `result_state_binding`, and `causal_parent_refs` appear in replay outputs and timeline/detail projections
- add conditional checks in [rct_replay_verification.py](/Users/ningli/project/seedcore/src/seedcore/ops/evidence/rct_replay_verification.py) so stricter validation runs only when the new fields are present or explicitly required for a workflow
- keep API/read compatibility by letting [replay.py](/Users/ningli/project/seedcore/src/seedcore/models/replay.py) and the existing verification surface accept both legacy and upgraded records
- add regression coverage in the existing replay/evidence test area so legacy records still pass while upgraded records surface the extra bindings cleanly

### Current Canary

The current implementation uses a deliberately narrow rollout shape:

- the new state-transition replay checks are guarded by `SEEDCORE_RCT_REPLAY_STRICT_STATE_TRANSITION_FIELDS`
- even when that env flag is enabled, replay only applies the new check when the record explicitly opts in through `policy_case.workflow_hints.strict_state_transition_fields = true`
- the first producer path setting that hint is the **agent-action gateway restricted-custody closure** path in [agent_actions_router.py](/Users/ningli/project/seedcore/src/seedcore/api/routers/agent_actions_router.py)

This keeps the canary bounded to one governed workflow producer instead of broadening strict replay requirements across every existing RCT record at once.

### Defer

- Full authenticated state-tree implementation such as a Merkle Patricia Tree-backed twin state store.
- General vector-clock or concurrency framework across all agent interactions.
- Mandatory multimodal evidence hashing for every workflow, including paths that are not materially dependent on physical-world sensing.
- Cross-domain anchoring and portable proof-path distribution beyond the current database-centered replay surface.

## Notes

This ADR is intentionally stronger than the current implementation, but it is also intentionally non-urgent. Today, SeedCore already supports replayable evidence bundles, `state_binding_hash`, signed transition receipts, and append-only digital twin journaling. The decision here is to guide those mechanisms toward a stricter replay contract for governed state transitions over time, not to force an immediate redesign of the current baseline.

Research references that informed this direction:

- Leslie Lamport, [Time, Clocks, and the Ordering of Events in a Distributed System](https://www.microsoft.com/en-us/research/publication/time-clocks-ordering-events-distributed-system/)
- ethereum.org, [Merkle Patricia Trie](https://ethereum.org/developers/docs/data-structures-and-encoding/patricia-merkle-trie)
- Friedemann Mattern profile note on vector clocks, [ETH Zurich portrait](https://inf.ethz.ch/news-and-events/spotlights/infk-news-channel/2021/06/portrait-friedemann-mattern.html)
