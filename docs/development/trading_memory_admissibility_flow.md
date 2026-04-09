# Trading Memory Admissibility Flow

Date: 2026-04-09
Status: Proposed implementation flow aligned with the bounded-memory and stateless-PDP direction

## Purpose

Turn the bounded-memory philosophy into an implementable flow for autonomous
trade and other high-consequence governed actions.

This document defines how memory can improve:

- proposal quality
- abstention quality
- evidence quality
- operator legibility

without allowing memory to become hidden authority inside the PDP hot path.

## Core Rule

Memory may shape what an agent proposes.

Memory may not silently shape what the PDP authorizes.

Anything retrieved from memory must pass through an explicit admission step
before it can influence a governed decision. The PDP should see only a bounded,
typed, freshness-aware context envelope, never raw memory search output.

## Design Goals

- keep the final PDP synchronous, deterministic, and replayable
- let memory improve reasoning without becoming policy
- make every admitted memory-derived fact visible in replay and operator tools
- fail closed when freshness, provenance, or scope requirements are not met
- preserve clear ownership between advisory systems and authoritative systems

## Non-Goals

- turning `SemanticMemory` into a source of authority
- allowing free-form LLM summaries to enter the PDP unchecked
- adding live multi-hop retrieval to the hot path
- replacing approval, delegation, custody, or telemetry systems of record

## End-to-End Flow

### Stage 0: Request ingress

Owner:

- Agent Action Gateway
- coordinator-side intent assembly

Current repo fit:

- `docs/development/agent_action_gateway_contract.md`
- `docs/development/asset_centric_pdp_hot_path_contract.md`

Input:

- action request
- delegated principal identity
- workflow-specific parameters

Output:

- normalized `ActionIntent`
- request-scoped identifiers for retrieval and replay

Rule:

- no memory lookup happens until the request has a bounded workflow scope

### Stage 1: Retrieval planning

Owner:

- cognitive/advisory layer

Current repo fit:

- `src/seedcore/cognitive/memory_bridge.py`
- `src/seedcore/models/advisory.py`

Input:

- `ActionIntent`
- task type
- asset or product identifiers
- organ or agent scope

Output:

- `MemoryRetrievalPlan`

Required fields for `MemoryRetrievalPlan`:

- `request_id`
- `intent_id`
- `workflow_type`
- `allowed_memory_classes`: `working`, `semantic`, `incident`
- `scopes`
- `entity_ids`
- `max_items_per_class`
- `purpose`
- `retrieval_deadline_ms`

Rule:

- retrieval must be purposeful and scoped
- no broad "search everything related to trading" queries

### Stage 2: Candidate memory retrieval

Owner:

- memory support plane

Current repo fit:

- `WorkingMemory` / `SemanticMemory` / `IncidentMemory` in
  `src/seedcore/memory/contracts.py`

Input:

- `MemoryRetrievalPlan`

Output:

- ordered `RetrievedMemoryItem[]`

Required fields for `RetrievedMemoryItem`:

- `memory_class`
- `memory_id`
- `summary`
- `content`
- `scope`
- `source_ref`
- `observed_at`
- `recorded_at`
- `provenance`
- `confidence`
- `advisory_only`

Rules:

- retrieval returns advisory candidates only
- candidate items must preserve source and time metadata
- missing provenance marks an item as non-admissible

### Stage 3: Memory normalization and claim extraction

Owner:

- new admission compiler layer

Recommended new runtime surface:

- `src/seedcore/ops/context/` or similar support-plane package

Input:

- `RetrievedMemoryItem[]`
- workflow contract

Output:

- `MemoryClaim[]`

Each `MemoryClaim` should represent one candidate assertion, for example:

- "recent slippage incidents for venue X exceeded threshold"
- "strategy Y was previously rejected under regime Z"
- "this asset was previously quarantined for custody mismatch"

Required fields for `MemoryClaim`:

- `claim_id`
- `claim_type`
- `value`
- `derived_from`
- `claim_source_kind`: `observed`, `derived`, `summarized`
- `fresh_until`
- `owner`
- `authoritative_system`
- `admission_policy`

Rules:

- one memory item may yield multiple claims
- free-form summaries must be broken into typed claims before admission
- claims with unknown owner or freshness policy are rejected

### Stage 4: Admission gate

Owner:

- support-plane admission service, upstream of the PDP

Recommended new runtime surface:

- `MemoryAdmissionService`

Input:

- `MemoryClaim[]`
- workflow-specific admission rules
- pinned policy snapshot metadata
- current authoritative context references

Output:

- `BoundedContextEnvelope`

The admission gate decides for each claim:

- `admit`
- `reject`
- `advisory_only`

Required checks:

1. Scope check
2. Freshness check
3. Provenance check
4. Owner check
5. Contract-type check
6. Authority check
7. Replay-linkability check

Explicit rule:

- memory can contribute context facts
- memory cannot originate approvals, delegation, custody truth, policy truth,
  or telemetry truth

Examples:

- admit: "three prior verifier-confirmed slippage incidents for this venue in
  the last hour"
- advisory only: "semantic similarity suggests this resembles a mean-reversion
  trap"
- reject: "agent summary says approval should still be valid"

### Stage 5: Build the bounded context envelope

Owner:

- gateway or hot-path request assembler

Current repo fit:

- `src/seedcore/models/pdp_hot_path.py`
- `src/seedcore/ops/pdp_hot_path.py`

Input:

- admitted claims
- authoritative asset, approval, delegation, and telemetry context

Output:

- `BoundedContextEnvelope`
- augmented hot-path request

Recommended envelope shape:

```json
{
  "envelope_id": "ctx-2026-04-09-001",
  "request_id": "req-123",
  "policy_snapshot_ref": "snapshot:pkg-prod-2026-04-09",
  "admitted_facts": [
    {
      "field": "incident_context.recent_verified_slippage_count",
      "value": 3,
      "source_refs": ["incident:abc", "incident:def", "incident:ghi"],
      "fresh_until": "2026-04-09T10:01:00Z",
      "owner": "verification_runtime",
      "authority_class": "advisory_context"
    }
  ],
  "rejected_claims": [
    {
      "claim_id": "claim-7",
      "reason": "missing_provenance"
    }
  ],
  "advisory_only_claims": [
    {
      "claim_id": "claim-8",
      "reason": "heuristic_pattern_only"
    }
  ]
}
```

Rules:

- admitted facts must be small, typed, and replayable
- rejected and advisory-only claims should also be retained for operator review
- envelope contents must be deterministic from the same inputs

### Stage 6: PDP evaluation

Owner:

- PDP hot path

Current repo fit:

- `src/seedcore/ops/pdp_hot_path.py`
- `docs/architecture/adr/adr-0001-pdp-hot-path.md`

Input:

- pinned policy snapshot
- authoritative context
- bounded context envelope

Output:

- `allow`, `deny`, `quarantine`, or `escalate`
- checks, reason codes, obligations, governed receipt

Rules:

- the PDP evaluates over admitted fields only
- the PDP does not execute retrieval
- missing required admitted facts should fail closed when policy requires them
- policy should distinguish authoritative facts from advisory facts

### Stage 7: Execution, verification, and replay

Owner:

- execution runtime
- verifier runtime

Current repo fit:

- `docs/development/north_star_autonomous_trade_environment.md`
- `docs/architecture/adr/adr-0004-result-verifier-runtime.md`

Output:

- execution token
- replayable receipt
- verifier outcome
- twin-state mutation

New replay requirement:

- receipts should record which memory-derived facts were admitted, which were
  rejected, and which remained advisory-only

### Stage 8: Post-decision learning

Owner:

- sidecar learning and memory promotion flows

Current repo fit:

- `src/seedcore/cognitive/memory_bridge.py`
- `docs/development/governance_aware_learning_next_stage_plan.md`

Input:

- intent
- bounded context envelope
- decision
- outcome
- verifier findings

Output:

- new semantic entries
- new incidents
- offline training samples

Rules:

- learning happens after the governed decision
- post-decision learning may improve future proposals and abstention
- post-decision learning may not retroactively justify a prior decision

## Admission Policy by Memory Class

### WorkingMemory

Best use:

- current task scratchpad
- recent episodic context
- temporary coordination state

Admissibility posture:

- default `advisory_only`
- can be admitted only for narrow, task-local facts with explicit TTL and
  replay linkage

Never authoritative for:

- approvals
- delegation
- custody
- policy snapshot state

### SemanticMemory

Best use:

- reusable strategy patterns
- regime notes
- venue heuristics
- instrument-specific execution lessons

Admissibility posture:

- mostly `advisory_only`
- may produce typed risk modifiers or abstention hints after admission checks

Never authoritative for:

- live market state
- account balances
- approvals
- edge telemetry

### IncidentMemory

Best use:

- verifier-confirmed failures
- quarantine-worthy episodes
- postmortem-grade anomalies

Admissibility posture:

- strongest candidate for admission as support context
- still cannot replace authoritative systems of record

Good admitted examples:

- recent verifier-confirmed incident counts
- unresolved incident flags with owner and timestamp
- known unsafe execution modes confirmed by replay evidence

## Decision Vocabulary for the Admission Gate

The admission layer should emit deterministic reason codes so replay and
operators can understand why a claim did or did not influence a decision.

Suggested codes:

- `admitted_scoped_fact`
- `admitted_incident_aggregate`
- `rejected_missing_provenance`
- `rejected_stale_claim`
- `rejected_scope_mismatch`
- `rejected_authority_violation`
- `advisory_only_heuristic`
- `advisory_only_low_confidence`

## Minimal Additive Code Changes

### Phase A: Add models and logging surfaces

- add `MemoryRetrievalPlan`, `RetrievedMemoryItem`, `MemoryClaim`, and
  `BoundedContextEnvelope` models under `src/seedcore/models/`
- add operator-visible logging of admitted vs rejected memory claims
- keep all changes additive and optional on the hot path

### Phase B: Add an admission service

- add `MemoryAdmissionService` under a support-plane package such as
  `src/seedcore/ops/context/`
- compile retrieved memory into typed claims
- apply deterministic admission checks

### Phase C: Attach the envelope to hot-path requests

- extend `HotPathEvaluateRequest` with an optional bounded context field
- persist envelope metadata in governed receipts and parity logs
- do not allow the hot path to perform raw memory retrieval directly

### Phase D: Promote only replay-backed learning

- export post-decision samples from decision plus verifier artifacts
- promote verified lessons into semantic or incident memory with provenance
- evaluate whether those promotions improve abstention, evidence quality, or
  verifier precision

## Implementation Guardrails

- no raw `SemanticMemory.search()` output should cross into the PDP request
  contract
- every admitted fact must carry source refs and freshness metadata
- every rejected fact must carry a rejection reason
- every workflow must declare which claim types are admissible
- admission logic must be deterministic and testable without an LLM
- learned systems may propose, rank, or summarize, but only typed admitted
  facts may affect authorization

## Success Criteria

This flow is working if all of the following are true:

- similar requests with the same policy snapshot and context envelope replay to
  the same decision
- operators can explain exactly which memory-derived facts influenced a trade
- memory improves proposal quality and abstention quality without widening
  authority
- the PDP remains synchronous and stateless at decision time
- verification and postmortem tooling can distinguish authoritative context
  from admitted advisory context

## Short Version

Treat memory as a retrieval and learning plane.

Treat admissibility as a separate compilation step.

Treat the PDP as a judge that only sees admitted, typed, replayable facts.
