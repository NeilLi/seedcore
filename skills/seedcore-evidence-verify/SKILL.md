---
name: seedcore-evidence-verify
description: Use when verifying SeedCore trust references, replay artifacts, audit records, or subject-linked evidence through the public verification surface.
---

# Seedcore Evidence Verify

Use this skill when the user wants to verify a trust or replay reference.

## Preferred MCP flow

Call `seedcore.evidence.verify` with exactly one of:

- `reference_id`
- `public_id`
- `audit_id`
- `subject_id`

Use `subject_type` only when the caller already knows it.

## Output expectations

- Confirm which identifier was verified.
- Report whether verification succeeded.
- Include any trust URL or JSON-LD reference returned by the runtime.
- If verification fails, report the runtime error or validation issue directly.

## Guardrails

- Never send multiple identifiers in one verification request.
- Prefer the public verification API over internal database inspection for plugin-facing workflows.
