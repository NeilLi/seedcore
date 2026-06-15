# Hot-Path Transport Serialization Spike

Date: 2026-06-15
Status: Development spike contract

## Purpose

This note adopts the hot-path serialization enhancement as a measured internal
transport spike:

```text
Evaluate Protobuf or FlatBuffers for internal hot-path transport.
Do not replace JSON-LD replay/export contracts.
Do not weaken Pydantic/PDP validation, freshness, evidence, or verifier checks.
```

The useful goal is lower serialization cost on the node-to-node hot path. The
unsafe goal would be to treat a binary format as execution authority or to
claim zero-cost parsing before measurement.

## Decision

SeedCore should start with **Protobuf v3** as the first internal transport
mirror for `pdp.hot_path.asset_transfer.v1`.

FlatBuffers remains a later candidate if the hot path moves toward a
Rust-first service boundary and the request layout becomes stable enough to
benefit from fixed-layout reads.

This is an implementation optimization only:

- PDP allow remains authoritative.
- Scoped `ExecutionToken` issuance remains required for execution authority.
- Evidence closure and verifier acceptance remain required for settlement.
- JSON-LD / JSON proof and replay artifacts remain canonical externally.

## Why Protobuf First

Protobuf is the lower-risk first spike for the current repo shape:

- Python dependencies already include `protobuf`.
- The hot-path contract is versioned and mostly typed.
- Schema evolution rules are mature enough for shadow/canary rollout.
- Generated Python, Rust, and TypeScript bindings can later align with the
  existing multi-language contract strategy.
- It is easier to compare against the current Pydantic model than a
  FlatBuffers-first design.

FlatBuffers may be useful later, but it should not be the first move while the
served path is still FastAPI/Pydantic and some request fields remain nested,
dynamic, or replay-facing.

## Wording Boundary

Avoid:

- "zero-allocation hot path"
- "zero-decoding overhead"
- "binary schema replaces validation"
- "Protobuf/FlatBuffers is a trust primitive"

Prefer:

- "internal binary transport mirror"
- "measured serialization and parsing reduction"
- "schema-compatible with the strict Pydantic contract"
- "replay-equivalent to the JSON contract"

Binary transport can reduce payload size and parsing cost. It does not remove
the need to validate schema completeness, freshness, signed context envelopes,
policy snapshot alignment, state binding, replay obligations, or verifier
closure.

## Current Repo Fit

Current hot-path serving remains JSON/Pydantic:

- `POST /api/v1/pdp/hot-path/evaluate`
- `HotPathEvaluateRequest` and `HotPathEvaluateResponse`
- strict Pydantic `extra="forbid"` request models
- benchmark coverage through `scripts/host/benchmark_rct_hot_path.py`
- JSON-LD / JSON replay and proof artifacts

The current request model still carries fields that should stay outside the
first binary mirror until they stabilize:

- nested `ActionIntent`
- `request_schema_bundle`
- `taxonomy_bundle`
- receipt and obligation payloads
- replay/export artifacts

That means the first spike should mirror only the stable authority-relevant
fields needed to compare transport cost and parity, not every debug or replay
projection field.

## Spike Shape

### Phase 0: Schema Boundary

Define an internal-only schema mirror for the stable request and response spine:

- `contract_version`
- `request_id`
- `requested_at`
- `policy_snapshot_ref`
- `context_freshness`
- `signed_context_envelopes`
- asset identity and custody context
- telemetry freshness context
- decision view
- trust gaps and reason codes

Keep `ActionIntent` as a nested typed message only after the field set is
stable enough to generate from a single authority source. Until then, the spike
may use an explicitly named canonical JSON bytes field for `ActionIntent`, but
that shape is not eligible for enforce-mode promotion.

### Phase 1: Parity Harness

Build a local harness that:

1. takes the canonical RCT hot-path fixture payloads;
2. encodes them to JSON and the internal Protobuf mirror;
3. decodes the Protobuf mirror back into the Pydantic request model;
4. runs the same hot-path evaluation;
5. asserts identical disposition, reason code, trust gaps, and replay-visible
   policy snapshot fields.

This must run in shadow only.

### Phase 2: Benchmark Harness

Extend or wrap `scripts/host/benchmark_rct_hot_path.py` to capture:

- JSON encode/decode time;
- Protobuf encode/decode time;
- payload byte size;
- end-to-end request latency if an internal binary endpoint or in-process
  selector exists;
- parity mismatch count;
- deny/quarantine behavior for malformed, missing, stale, or extra fields.

The benchmark artifact should explicitly report whether serialization is a
material part of p50/p95/p99 latency. If it is not, defer transport migration
and focus on the measured bottleneck.

### Phase 3: Promotion Decision

Only promote beyond spike if all of the following are true:

1. JSON and Protobuf parity is exact for canonical allow, deny, quarantine, and
   stale-context cases.
2. Unknown or extra fields fail at least as strictly as Pydantic
   `extra="forbid"`.
3. Missing freshness, signed-context, policy snapshot, state-binding, or
   telemetry fields fail closed with the same reason-code family.
4. Benchmark evidence shows meaningful improvement in p50/p95/p99, CPU, or
   payload size.
5. Replay/export artifacts remain JSON-LD / JSON and are byte-for-byte
   equivalent at the proof boundary.
6. Schema generation ownership is clear for Python, Rust, and TypeScript.

## Non-Goals

- No public API replacement.
- No replay/export format replacement.
- No runtime authority change.
- No `shadow` to `enforce` promotion because serialization got faster.
- No FlatBuffers-first implementation before the Protobuf mirror proves the
  schema boundary and benchmark harness.
- No hand-maintained divergent schemas across Python, Rust, and TypeScript.

## Acceptance Evidence

The spike is accepted only when it produces:

- an internal schema mirror;
- a parity test over canonical RCT hot-path fixtures;
- a benchmark artifact comparing JSON and Protobuf cost;
- a clear keep/defer decision based on measured bottlenecks;
- documentation confirming that JSON-LD remains the canonical replay/export
  surface.

If the benchmark does not show a meaningful bottleneck, the correct outcome is
to keep the schema mirror as research evidence and continue optimizing the
actual limiting path.

## Read With

- [ADR 0001: PDP hot path](../architecture/adr/adr-0001-pdp-hot-path.md)
- [Asset-Centric PDP Hot Path Contract](asset_centric_pdp_hot_path_contract.md)
- [Hot-Path Shadow To Enforce Breakdown](hot_path_shadow_to_enforce_breakdown.md)
- [SeedCore 2026 Execution Plan](seedcore_2026_execution_plan.md)
