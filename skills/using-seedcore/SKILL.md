---
name: using-seedcore
description: Use when the task is about SeedCore runtime operations, hot-path promotion, PKG observability, evidence verification, local bring-up, or creating/using the Seedcore Codex or Gemini plugin. Prefer the read-only `seedcore.*` MCP tools before raw commands.
---

# Using Seedcore

Use this skill at the start of SeedCore-specific work.

## Rules

- Prefer `seedcore.*` MCP tools first.
- Use public API routes or `scripts/host/*.py` only when the MCP server is unavailable or the workflow explicitly needs a local command.
- Treat this plugin as read-only in v1. Do not activate snapshots, reload PKG, refresh authz graphs, or change hot-path mode through the plugin flow.

## Choose the matching workflow

- Use `seedcore-local-runtime` for bring-up, health checks, and local host-mode guidance.
- Use `seedcore-hotpath-promotion` for shadow-to-enforce analysis, parity checks, and benchmarks.
- Use `seedcore-pkg-observability` for PKG and authz-graph readiness checks.
- Use `seedcore-evidence-verify` for replay or trust-reference verification.

## Preferred tool order

1. `seedcore.health`
2. `seedcore.readyz`
3. `seedcore.pkg.status`
4. `seedcore.pkg.authz_graph_status`
5. `seedcore.hotpath.status`
6. `seedcore.hotpath.verify_shadow`
7. `seedcore.hotpath.benchmark`
8. `seedcore.evidence.verify`

## Fallback commands

When MCP is unavailable, use the documented host-mode commands in `deploy/local/README.md` and the host scripts under `scripts/host/`.

For Gemini-specific tool mapping, read `references/gemini-tools.md`.
