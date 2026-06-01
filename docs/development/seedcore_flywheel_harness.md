# SeedCore Flywheel Harness

Date: 2026-06-01
Status: Development guardrail for the energy flywheel

SeedCore's flywheel is a bounded control loop for adapting energy weights from
runtime evidence. It is not an authority path, not a replacement for policy,
and not a way for AI intent to self-promote into execution.

Core rule:

```text
SeedCore is building a trust runtime for AI actions in high-consequence environments.
AI intent should not automatically become execution authority.
```

## Harness Posture

The flywheel must stay inside the governed execution spine:

```text
ActionIntent -> PDP -> ExecutionToken or PolicyDeny
  -> actuator/edge execution -> evidence bundle
  -> replay / RESULT_VERIFIER -> verified, rejected, review, or quarantine
```

Flywheel adaptation may tune `alpha_entropy`, `lambda_reg`, and `beta_mem`.
It must not mint authority, bypass revocation, lower evidence requirements, or
convert advisory model output into execution permission.

## SeedCore Mapping

| Harness construct | SeedCore flywheel rule |
| --- | --- |
| Progressive disclosure | Keep the root context small and point agents to this file, the policy gate matrix, and trust-runtime category docs. |
| Mechanical enforcers | Flywheel cycles emit deterministic gates for evidence window, finite telemetry, drift ceiling, and anomaly ceiling. Blocking failures pause adaptation. |
| Autonomous review loop | Repeated gate failure opens a circuit breaker and requires operator review with verifier output. |
| Reasoning sandwich | Spend human/agent reasoning on planning and verification; keep implementation changes boring and bounded. |
| Agent legibility | Each cycle records metrics, weight changes, skipped state, gate outcomes, context refs, and remediation hints. |
| Continuous cleanup | Failed gates become new checks, docs, fixtures, or runbooks rather than tribal memory. |

## Blocking Gates

The current runtime flywheel blocks adaptation when:

- fewer than the minimum energy samples are available
- any energy term is `NaN`, infinite, or non-numeric
- latest drift exceeds the flywheel trust ceiling
- latest anomaly exceeds the flywheel trust ceiling
- the same blocking gate fails for three consecutive cycles

The non-worsening energy trend is a warning signal, not a blocker. A worsening
energy window should trigger review, but adaptation may still be the corrective
action when trust telemetry remains healthy.

## Verification

Focused tests:

```bash
pytest tests/test_flywheel_harness.py tests/test_energy.py -q
```

When a flywheel change touches authority, policy, tokens, custody state, replay,
or verifier closure, also run the relevant RCT and zero-trust gates from the
development index before promotion.
