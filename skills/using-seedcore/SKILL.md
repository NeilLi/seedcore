---
name: using-seedcore
description: Use when the task is about SeedCore runtime operations, hot-path promotion, PKG observability, evidence verification, forensic replay, owner/creator authority workflows (identity, profile, delegation, trust preferences), digital twin capture from public links, local bring-up, or creating/using the Seedcore Codex or Gemini plugin. Prefer `seedcore.*` MCP tools before raw commands.
---

# Using Seedcore

Use this skill at the start of SeedCore-specific work.

## Rules

- Prefer `seedcore.*` MCP tools first.
- In Gemini extension flows, run the relevant MCP tool before reading repository files unless troubleshooting a failed tool call.
- In Codex extension flows, use the same tool parity as Gemini for owner/creator authority workflows.
- Use public API routes or `scripts/host/*.py` only when the MCP server is unavailable or the workflow explicitly needs a local command.
- Use write-capable owner/creator tools only for explicit user requests and keep all high-consequence actions on governed evaluate/preflight paths.
- Do not activate snapshots, reload PKG, refresh authz graphs, or change hot-path mode through the plugin flow.

## Choose the matching workflow

- Use `seedcore-local-runtime` for bring-up, health checks, and local host-mode guidance.
- Use `seedcore-hotpath-promotion` for shadow-to-enforce analysis, parity checks, and benchmarks.
- Use `seedcore-pkg-observability` for PKG and authz-graph readiness checks.
- Use `seedcore-evidence-verify` for replay or trust-reference verification.
- Use `seedcore-forensic-replay` for replaying audit, subject, task, intent, or public trust-page forensic history.
- Use `seedcore-digital-twin-capture` for draft digital twin capture from public links such as YouTube.
- Use owner/creator authority tools for DID onboarding, creator profile lifecycle, delegation lifecycle, trust preference lifecycle, consolidated owner-context reads, and governed preflight.

## Preferred tool order

1. `seedcore.health`
2. `seedcore.readyz`
3. `seedcore.pkg.status`
4. `seedcore.pkg.authz_graph_status`
5. `seedcore.hotpath.status`
6. `seedcore.hotpath.verify_shadow`
7. `seedcore.hotpath.benchmark`
8. `seedcore.evidence.verify`
9. `seedcore.identity.owner.upsert`
10. `seedcore.identity.owner.get`
11. `seedcore.creator_profile.upsert`
12. `seedcore.creator_profile.get`
13. `seedcore.delegation.grant`
14. `seedcore.delegation.get`
15. `seedcore.delegation.revoke`
16. `seedcore.trust_preferences.upsert`
17. `seedcore.trust_preferences.get`
18. `seedcore.owner_context.get`
19. `seedcore.agent_action.preflight`
20. `seedcore.digital_twin.capture_link`
21. `seedcore.forensic_replay.fetch`

## Fallback commands

When MCP is unavailable, use the documented host-mode commands in `deploy/local/README.md` and the host scripts under `scripts/host/`.

For Gemini-specific tool mapping, read `references/gemini-tools.md`.
For Codex-specific tool mapping, read `references/codex-tools.md`.
