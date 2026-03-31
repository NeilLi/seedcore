---
name: seedcore-pkg-observability
description: Use when diagnosing PKG evaluator readiness, authz-graph freshness, snapshot alignment, or SeedCore policy runtime health without changing runtime state.
---

# Seedcore PKG Observability

Use this skill for read-only PKG diagnostics.

## Preferred MCP flow

1. Call `seedcore.pkg.status`.
2. Call `seedcore.pkg.authz_graph_status`.
3. If the work involves hot-path promotion, call `seedcore.hotpath.status`.

## Focus areas

- Whether the PKG manager exists and the evaluator is ready.
- Active version, snapshot id, and engine type.
- Authz graph compiled time, active snapshot version, and restricted-transfer readiness.
- Errors that block policy evaluation or hot-path readiness.

## Constraints

- Do not trigger snapshot activation, reload, or authz-graph refresh in this workflow.
- Keep recommendations read-only unless the user explicitly asks for an operator action outside plugin v1 scope.
