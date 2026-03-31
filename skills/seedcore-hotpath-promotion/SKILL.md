---
name: seedcore-hotpath-promotion
description: Use when evaluating Restricted Custody Transfer hot-path promotion from shadow toward enforce, checking parity evidence, or benchmarking latency under load.
---

# Seedcore Hot-Path Promotion

Use this skill for the shadow-to-enforce workflow.

## Preferred MCP flow

1. Call `seedcore.hotpath.status`.
2. Call `seedcore.pkg.status` if snapshot or authz readiness is unclear.
3. Call `seedcore.hotpath.verify_shadow`.
4. Call `seedcore.hotpath.benchmark`.

## What to report

- Current mode and whether enforce readiness is green.
- Shadow parity result for the canonical four-case matrix.
- Benchmark latency summary: `p50`, `p95`, `p99`, errors, mismatches, quarantine count.
- Artifact paths produced by verification or benchmarking.

## Interpretation guardrails

- Do not recommend enforcement if parity mismatches are non-zero.
- Treat stale or unavailable authz graph state as a blocker.
- Keep the discussion aligned with:
  - `docs/development/hot_path_shadow_to_enforce_breakdown.md`
  - `docs/development/hot_path_enforcement_promotion_contract.md`

## Fallback local commands

```bash
python scripts/host/verify_rct_hot_path_shadow.py
python scripts/host/benchmark_rct_hot_path.py --requests 40 --warmup 4 --concurrency 4
```
