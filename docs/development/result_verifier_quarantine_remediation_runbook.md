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
