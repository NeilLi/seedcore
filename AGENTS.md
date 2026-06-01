# AGENTS.md

SeedCore is building a trust runtime for AI actions in high-consequence
environments.

## Read First

- Product spine: `README.md`
- Development map: `docs/development/README.md`
- Flywheel harness: `docs/development/seedcore_flywheel_harness.md`
- Policy gates: `docs/development/policy_gate_matrix.md`
- Trust-runtime category: `docs/development/trust_runtime_category_distinction.md`

## Core Rule

AI intent should not automatically become execution authority. The model can
propose. The Agent is accountable. The PDP decides. The actuator executes. The
evidence closes the loop.

## Authority Boundaries

- Do not bypass PDP evaluation, `ExecutionToken` checks, revocation, or
  evidence closure for convenience.
- Do not let adaptive learning, flywheel tuning, model promotion, or operator
  copilot output become authority-bearing by itself.
- Treat production execution, secrets, deploy pipelines, custody closure, and
  quarantine clearance as human-reviewed or policy-admitted actions.

## Local Verification

Focused flywheel checks:

```bash
pytest tests/test_flywheel_harness.py tests/test_energy.py -q
```

Core trust-runtime checks depend on the touched surface. Start with:

```bash
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
```

## Common Mistakes

- Do not frame SeedCore as a generic coding-agent harness, marketplace, or
  traditional cybersecurity detector.
- Do not make memory, LLM advice, or flywheel feedback an authority source.
- When a deterministic gate fails repeatedly, stop autonomous iteration and
  surface the verifier/runbook evidence.
