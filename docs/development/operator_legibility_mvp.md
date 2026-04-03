# Operator legibility and copilot MVP

Date: 2026-04-03  
Status: Implementation note for the operator-legibility layer

Related spec: [q2_2026_audit_trail_ui_spec.md](./q2_2026_audit_trail_ui_spec.md)

## Purpose

Keep the operator console legible without weakening the evidence model. The
auditable UI remains the system of record; this layer adds deterministic
summaries, anomaly cues, and a read-only copilot view on top of it.

## Current implementation

### Deterministic legibility layer

- **Queue (`operator_signals`)**: Each row includes `priority_score` and `correlation_flags` for internal consistency checks. Default ordering is **anomaly-first** (highest priority first, then `updated_at`). `queue_sort=chron` restores newest-first ordering. Fixture `root` stays on queue query strings via `buildQueryString`.
- **Case verdict strip** on transfer, forensics, and replay: fixed header with **decision**, **risk**, **confidence**, and **next action**, derived from projections rather than a model.
- **Replay verdict card**: `consistent`, `inconsistent`, or `incomplete`, based on the receipt chain, traces, tamper/signature checks, and the failure panel.
- **Cross-surface flags** on replay: e.g. projection versus terminal disposition mismatch.
- **What changed since last load**: client-side `sessionStorage` diff for a small snapshot per view key, scoped to the current browser tab.

### Read-only copilot MVP

- Three-level UX: one-line summary, up to five bullets, and drill-down with **facts** versus **inferences** plus **citations**.
- Implemented as `buildDeterministicCopilotBrief*` in `@seedcore/contracts`.
- JSON Schema: `docs/schemas/operator_copilot_brief_v0.schema.json`.

## Guardrails

- Copilot output is **read-only** and does not call write APIs.
- **Facts** are literal field bindings; **inferences** are labeled heuristic statements.
- Partial replay HTML payloads fall back to **projection-only** verdict and copilot output until full `verification-detail` is present.

## LLM-backed path

The LLM path is available behind a feature flag and uses the deterministic brief
as the fallback when validation fails or the model errors.

- **GET** `/api/v1/verification/operator/copilot-brief` accepts the same query params as transfer review (`source`, `dir`, `root`, `workflow_id`, runtime `audit_id`, and related filters). It returns `seedcore.verification_operator_copilot_response.v0` with `brief` (`OperatorCopilotBriefV1`) and `meta` (`used_llm`, optional `validation_errors`, or `llm_error`).
- **Prompts**: `ts/services/verification-api/prompts/operator_copilot_system.md` and `operator_copilot_user.md`.
- **Feature flag**: set `SEEDCORE_OPERATOR_COPILOT_LLM=1` and `OPENAI_API_KEY`. Optional: `SEEDCORE_OPERATOR_COPILOT_MODEL` (default `gpt-4o-mini`) and `SEEDCORE_OPENAI_BASE_URL`.
- **Validation**: `validateOperatorCopilotBriefForLlm` in `@seedcore/contracts` rejects LLM JSON missing `citations` (at least one), `uncertainty_notes` (at least one), non-empty `confidence` or `one_line_summary`, `facts` or `inferences` bullets, or `generation_mode: "llm"`. On failure or LLM error, the response falls back to the deterministic brief and records the reason in `audit_note`, `uncertainty_notes`, `meta.validation_errors`, or `meta.llm_error`.

## Next

- **Week 5-6**: add richer anomaly detection, especially cross-queue versus replay correlation when both snapshots are available server-side.
- **Week 7+**: guided actions remain behind explicit operator consent; no silent automation.

## Success metrics

Track in analytics or operator studies:

- time to understand
- time to correct action
- missed anomaly rate
- false-positive rate
- runbook adherence
- clarification requests per case
