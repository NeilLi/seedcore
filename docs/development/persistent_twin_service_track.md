# Persistent Twin Service Track

This document defines the digital twin persistence track as a separate implementation stream from the first forensic replay milestone.

## Scope

This track introduces:

- persisted authoritative twin state (`digital_twin_state`)
- append-only twin history (`digital_twin_history`)
- twin versioning (`state_version`)
- coordinator wiring to resolve from persisted twins first, with fallback to baseline snapshots

## Non-Scope

This track does not change the frozen forensic replay boundary:

- `TaskPayload` remains proposal
- `ActionIntent` / `ExecutionToken` remain authorization path
- `EvidenceBundle` remains evidence
- JSON-LD remains export/view materialization

## Runtime Behavior

For governed actions, twin resolution now follows:

```text
build_twin_snapshot() baseline shape
  -> overlay persisted authoritative twin snapshots by (twin_type, twin_id)
  -> overlay live authoritative state-service fields (revocation, quarantine, zones)
  -> policy evaluation
  -> persist resolved twins with versioned history
```

`build_twin_snapshot()` remains as a compatibility fallback and bootstrap input for missing twins.
