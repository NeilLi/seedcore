# RESULT_VERIFIER Quarantine Remediation Runbook

Date: 2026-04-10  
Scope: Local/host + CI lanes (no cluster-specific procedures)

## Purpose

When RESULT_VERIFIER detects integrity/trust mismatch for Restricted Custody
Transfer (RCT), SeedCore mutates authoritative twin state fail-closed and sets
lockout markers that block downstream transfer/closure paths.

This runbook defines the operator remediation path for safe quarantine
clearance.

## Trigger Conditions

Treat the case as active when one or more are observed:

- authoritative twin governance includes `result_verifier_lockout=true`
- authoritative disposition is `verification_failed` or
  `verification_quarantined`
- downstream action evaluation/closure returns gate block reason codes such as:
  - `result_verifier_lockout`
  - `closure_blocked_by_result_verifier`
  - `settlement_blocked_by_result_verifier`

## Remediation Procedure

1. Capture forensic context before any remediation
- collect audit id, task id, intent id, asset id
- collect replay and verification detail payloads
- preserve current authoritative snapshot and recent twin journal rows

2. Verify root cause class
- integrity-class mismatch:
  signature/hash/provenance tamper, broken chain, invalid artifact binding
- trust-class mismatch:
  stale/contradictory evidence, custody inconsistency, policy precondition gap

3. Resolve underlying cause (do not clear lockout first)
- integrity-class:
  regenerate/rebind artifacts from trusted source, rotate compromised keys if
  needed, replay verification chain
- trust-class:
  refresh evidence inputs, reconcile custody/location truth, re-run required
  approvals and policy checks

4. Re-verify deterministically
- confirm replay verification passes on remediated inputs
- confirm no unresolved trust gaps remain for the affected transition
- confirm expected business-state mapping is stable on re-read

5. Clear quarantine under operator control
- apply explicit authoritative mutation that removes lockout/quarantine for the
  affected twin only after step 4 is green
- record who performed clearance, when, and why (change ticket / incident link)

6. Post-clearance validation
- re-run gate checks to confirm downstream deny/closure blocks are removed
- verify no new mismatch outcomes were emitted for the same audit lineage

## Guardrails

- no automatic unquarantine in v1
- never clear lockout before evidence/chain remediation is complete
- scope clearance to the minimum affected twin set
- preserve before/after snapshots for forensic auditability

## Local Verification Commands

```bash
bash scripts/host/verify_q2_verification_contracts.sh
```

Optional Postgres-backed RESULT_VERIFIER queue checks:

```bash
export SEEDCORE_ENABLE_RESULT_VERIFIER_PG_TESTS=1
export SEEDCORE_RESULT_VERIFIER_TEST_DSN="postgresql+asyncpg://postgres:postgres@127.0.0.1:55432/seedcore_test"
bash scripts/host/verify_result_verifier_postgres_integration.sh
```

## Deployment Shape and Reversibility

Per [ADR 0006](../architecture/adr/adr-0006-result-verifier-deployment-split-trigger.md)
the RESULT_VERIFIER runs embedded inside the Coordinator process by default.
ADR 0006 pre-authorizes a split into a dedicated service only when one of five
measurable triggers is met (CPU pressure, latency, blast-radius,
regulatory-isolation, or scaling-shape). Until a trigger fires, operators must
treat the embedded shape as the only supported shape.

### Configuration toggles

| Variable                                           | Process       | Default  | Meaning                                                                 |
| -------------------------------------------------- | ------------- | -------- | ----------------------------------------------------------------------- |
| `SEEDCORE_RESULT_VERIFIER_ENABLED`                 | Coordinator   | `false`  | Master switch for the verifier intake + worker loops.                   |
| `SEEDCORE_RESULT_VERIFIER_EMBEDDED`                | Coordinator   | `true`   | Live ADR 0006 gate. `true` keeps verifier loops embedded in coordinator. `false` suppresses embedded verifier loops in this process; use only when a dedicated verifier service is running with `SEEDCORE_RESULT_VERIFIER_ENABLED=true`. |

**Reversibility contract.** The deployment shape is a reversible operational
choice, not a schema choice. A split deployment can be rolled back to embedded
by:

1. Stopping the dedicated verifier service so it stops writing outcomes.
2. Setting `SEEDCORE_RESULT_VERIFIER_EMBEDDED=true` (or unsetting it) on
   coordinator replicas and restarting them so the embedded runtime resumes
   intake.
3. Confirming the intake watermark advances and
   `result_verifier_watermark_lag_seconds` returns to steady state before
   lifting any customer-facing throttle.

The reverse direction (embedded → split) requires the same drain-then-switch
sequence: drain the embedded runtime, restart coordinator replicas with
`SEEDCORE_RESULT_VERIFIER_EMBEDDED=false`, and start the dedicated service.
Because the DAO schema, twin mutations, failure taxonomy, and Rust kernel
contract are shape-invariant, neither direction requires a data migration.

**Broken combination.** `SEEDCORE_RESULT_VERIFIER_EMBEDDED=false` on the
Coordinator *without* a running dedicated verifier service is operator error:
verification is globally off, every RCT completes without a verdict, and gate
checks will still be evaluated against whatever twin state was written at
persist time. When this combination is detected during an incident, treat it
the same as `SEEDCORE_RESULT_VERIFIER_ENABLED=false` on a single-process
deployment - restore verification before clearing any pending quarantine.

### Trigger-feeding telemetry

Two metrics feed ADR 0006 triggers directly. Alert thresholds derive from the
ADR; the runbook only defines the data contract.

| Metric                                     | Kind    | Tracker key                          | Prometheus name (on export) | ADR 0006 trigger fed    |
| ------------------------------------------ | ------- | ------------------------------------ | --------------------------- | ----------------------- |
| Total verifier job processing time         | Counter | `result_verifier_job_millis_total`   | `result_verifier_job_seconds_total` (ms → s at export) | CPU-pressure trigger - compute `rate(result_verifier_job_seconds_total[15m]) / rate(coordinator_cpu_seconds_total[15m])`. |
| Journal → watermark lag                    | Gauge   | `result_verifier_watermark_lag_seconds` | `result_verifier_watermark_lag_seconds` (1:1)          | Scaling-shape trigger - alert when value exceeds the freshness target (ADR 0006 default: sustained > 60s). |

Both are emitted on every verifier path today:

- The counter is incremented inside the `_process_one_job` `finally` block,
  so it captures success, non-RCT skip, and exception paths alike.
- The gauge is set on every `_poll_journal_once` cycle against the newest
  journal event's `recorded_at`, so a quiet journal reports `0.0` rather
  than "falling behind".

When investigating a suspected trigger condition, capture both metrics for
the affected window alongside `result_verifier_jobs_processed_total`,
`result_verifier_terminal_fail_total`, and
`result_verifier_stale_processing_requeued_total` before escalating a split
decision per ADR 0006.

The default dashboard template now includes both trigger-feeding visuals:
`config/grafana-dashboard.json` panels:

- `Result Verifier CPU Pressure Ratio` (`coordinator:result_verifier_cpu_pressure_ratio`)
- `Result Verifier Watermark Lag (s)` (`result_verifier_watermark_lag_seconds`)
