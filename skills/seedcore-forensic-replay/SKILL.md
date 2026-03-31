---
name: seedcore-forensic-replay
description: Use when replaying a SeedCore forensic record, trust page, or audit-linked custody story through the public replay surfaces.
---

# Seedcore Forensic Replay

Use this skill when the user wants Gemini to replay or summarize the forensic history for a SeedCore subject.

## Preferred MCP flow

1. Call `seedcore.forensic_replay.fetch`.
2. Use `public_id` when the user already has a public trust reference.
3. Use exactly one of `audit_id`, `subject_id`, `task_id`, or `intent_id` for internal replay assembly.
4. Default to `projection="buyer"` unless the user explicitly asks for `internal`, `auditor`, or `public`.

## Tool-first execution policy

- Execute `seedcore.forensic_replay.fetch` before reading repository files.
- Only inspect docs or code when the MCP call fails or the user asks how replay is implemented.

## What to report

- The replay mode: public trust page or replay record.
- Verification status and whether the replay appears intact.
- The subject title or subject identifiers.
- Approval, authorization, custody, and timeline highlights.
- Any trust page, JSON-LD, certificate, or public media references returned by the runtime.

## Guardrails

- Do not imply that a replay is verified if `verification_status.verified` is false.
- If the replay is public-facing, keep the summary aligned with the returned trust page rather than internal assumptions.
- If the user asks for a forensic replay from a public media link alone, direct them to `seedcore.digital_twin.capture_link` first because a raw link is not a replay record.
