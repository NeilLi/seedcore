# Legible Local Memory Vault

Date: 2026-05-18
Status: Development thesis and implementation target
Scope: Human-readable advisory memory, local-first operator inspection,
bounded context admission, and replay-visible memory-derived claims.

## Thesis

SeedCore should make advisory memory inspectable by humans before it becomes
operationally influential.

The useful pattern from OpenHuman and Karpathy-style LLM knowledge bases is not
"put more memory into the agent." It is:

> Memory that can influence proposals should be stored in a local,
> human-readable, human-editable form.

SeedCore should adapt this as a legible memory vault: an Obsidian-compatible
folder of Markdown files that mirrors advisory memory, admitted facts, rejected
claims, incidents, decisions, and operator notes. The vault is a control surface
for human inspection and correction. It is not a PDP input, not an approval
store, and not an authority source.

## Current SeedCore Fit

SeedCore already has the right architectural boundary:

- `memory_module_refactor_spec.md` narrows memory into working, semantic, and
  incident contracts that support context and legibility.
- `trading_memory_admissibility_flow.md` requires memory-derived claims to pass
  through explicit admission before they can influence governed decisions.
- `trust_runtime_category_distinction.md` states that memory supports the trust
  runtime, but does not replace deterministic policy or proof.

The vault makes those boundaries visible to operators.

## Core Rules

1. Memory may shape proposals.
2. Memory may improve operator legibility.
3. Memory may suggest context that enters an admission workflow.
4. Memory may not originate approval, delegation, custody truth, telemetry
   truth, policy truth, or execution authority.
5. The PDP must never read raw Markdown vault files directly.
6. Only typed, freshness-aware, replay-visible admitted facts may reach the PDP
   boundary.
7. Manual edits or deletion in the vault must affect future retrieval or mark
   derived indexes stale.

## Target Vault Shape

The vault should be plain files on local disk:

```text
seedcore-memory-vault/
  README.md
  _indexes/
    claims.md
    entities.md
    stale-indexes.md
  people/
  organizations/
  projects/
  assets/
  workflows/
  incidents/
  decisions/
  operator-notes/
  admitted-facts/
  rejected-claims/
  advisory-only/
  sources/
```

Recommended conventions:

- one note per durable memory item or curated summary
- stable file names derived from memory ids, entity ids, or date buckets
- Obsidian-style `[[wikilinks]]` for human navigation
- no secrets, raw credentials, private keys, session tokens, or bearer tokens
- no unredacted regulated data unless the local deployment profile permits it

## Note Frontmatter

Every note that can be consumed by the advisory layer should include
frontmatter:

```yaml
---
memory_id: mem:asset-lot-8841-incident-summary
memory_class: incident
authority_class: advisory_context
owner_ref: verification_runtime
entity_refs:
  - asset:lot-8841
  - facility:warehouse-north
source_refs:
  - incident:abc
  - replay:case-123
created_at: "2026-05-18T10:00:00Z"
updated_at: "2026-05-18T10:05:00Z"
fresh_until: "2026-05-18T11:00:00Z"
provenance_hash: sha256:...
admitted_to_pdp: false
index_status: current
redaction_profile: local_dev
---
```

Field meanings:

| Field | Meaning |
| :--- | :--- |
| `memory_id` | Stable id used by the memory support plane. |
| `memory_class` | `working`, `semantic`, `incident`, `decision`, `operator_note`, or `source`. |
| `authority_class` | Usually `advisory_context`; never `approval`, `delegation`, `custody_truth`, `telemetry_truth`, or `policy_truth`. |
| `owner_ref` | Service, agent, operator, or verifier that owns the claim. |
| `entity_refs` | Assets, owners, products, facilities, zones, workflows, or cases referenced by the note. |
| `source_refs` | Replay ids, incident ids, receipts, source documents, or other provenance links. |
| `fresh_until` | Advisory freshness horizon. Expired notes can still be read by humans but should not be admitted automatically. |
| `provenance_hash` | Hash of the source projection or normalized note body. |
| `admitted_to_pdp` | Human-readable signal; the authoritative record remains the bounded context envelope and receipt. |
| `index_status` | `current`, `stale`, `deleted`, or `needs_review`. |
| `redaction_profile` | Local deployment profile controlling what may be written. |

## Claim Mirrors

The vault should mirror the admission flow in three folders.

### `admitted-facts/`

Facts that passed scope, freshness, provenance, owner, contract-type,
authority, and replay-linkability checks.

Example:

```markdown
---
claim_id: claim-verified-slippage-count-001
request_id: req-123
policy_snapshot_ref: snapshot:pkg-prod-2026-04-09
authority_class: advisory_context
field: incident_context.recent_verified_slippage_count
value_type: integer
fresh_until: "2026-04-09T10:01:00Z"
source_refs:
  - incident:abc
  - incident:def
  - incident:ghi
admitted_to_pdp: true
---

# Recent Verified Slippage Count

Three verifier-confirmed slippage incidents were observed for this venue in the
last hour.
```

### `rejected-claims/`

Claims that were considered but not admitted.

Common reasons:

- `missing_provenance`
- `stale_context`
- `scope_mismatch`
- `authority_class_forbidden`
- `owner_mismatch`
- `raw_llm_summary`

### `advisory-only/`

Useful context that remains outside the PDP, such as pattern notes, summaries,
or operator comments.

Example:

```markdown
---
claim_id: claim-mean-reversion-trap-001
authority_class: advisory_context
admission_status: advisory_only
reason: heuristic_pattern_only
---

# Mean-Reversion Trap Similarity

Semantic similarity suggests this proposal resembles prior near-miss cases, but
the note is heuristic and cannot authorize or deny execution.
```

## Privacy And Erasure Semantics

The vault is useful only if local control is real.

Minimum rules:

- deleting a note removes it from future advisory retrieval;
- editing a note marks derived search/vector indexes stale until rebuilt;
- deleting a source note marks dependent summaries `needs_review` or `stale`;
- the system should preserve a local tombstone only when required for replay or
  audit, and that tombstone should avoid retaining the erased content;
- raw secrets and bearer credentials must never be written to the vault;
- sync is opt-in and outside the baseline trust boundary.

For governed decisions, erasure cannot rewrite already-issued receipts or replay
artifacts. Instead, later views should show that a memory item was deleted or
redacted after the decision.

## Integration With Existing Memory Contracts

The vault should sit beside the current memory runtime, not replace it.

| Existing layer | Vault role |
| :--- | :--- |
| `WorkingMemory` | optional short-lived note mirror for operator-visible task context. |
| `SemanticMemory` | human-readable source and summary mirror for retrieval candidates. |
| `IncidentMemory` | incident summaries and verifier-observed patterns. |
| `MemoryRetrievalPlan` | optional `vault_scope` and `vault_paths` for local advisory search. |
| `BoundedContextEnvelope` | references admitted claim notes, never raw vault search output. |
| Replay and governed receipt | records which vault-backed claims were admitted, rejected, or advisory-only. |

## Suggested Implementation Increment

Phase 0 should be docs and fixtures only:

1. Add a fixture vault under `fixtures/memory_vault/`.
2. Add sample notes for `admitted-facts`, `rejected-claims`, and
   `advisory-only`.
3. Add a Markdown frontmatter schema for vault notes.
4. Add a local validator that checks required frontmatter, forbidden authority
   classes, and secret-like fields.
5. Extend replay materialization to link to vault-backed claim ids only after
   bounded admission.

Phase 1 can add local search:

1. Use file-system scan plus Markdown frontmatter parsing.
2. Add SQLite FTS or equivalent local full-text index.
3. Keep vector search optional and rebuildable from the readable notes.
4. Mark stale indexes when notes are edited or deleted.

Phase 2 can add operator UX:

1. Open vault folder from local operator tooling.
2. Show admitted/rejected/advisory claim mirrors beside replay cases.
3. Offer "mark stale" and "request re-admission" controls.

## Forbidden Patterns

Do not:

- make the vault a PDP dependency;
- let free-form Markdown assertions become approvals;
- store private keys, tokens, OAuth refresh tokens, or session cookies;
- treat vector embeddings as the canonical memory artifact;
- auto-promote summaries into `DelegatedAuthority`, approval envelopes, custody
  state, telemetry state, or policy snapshots;
- sync the vault to a third-party service in control deployments without an
  explicit posture decision.

## Source Notes

These references inform the local-first, legible-memory pattern. They do not
mean SeedCore implements OpenHuman or Obsidian integration today.

- OpenHuman repository: https://github.com/tinyhumansai/openhuman
- OpenHuman user guide: https://www.openhuman.dev/
- Obsidian data storage: https://help.obsidian.md/data-storage
- Karpathy-style LLM knowledge base coverage:
  https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an
