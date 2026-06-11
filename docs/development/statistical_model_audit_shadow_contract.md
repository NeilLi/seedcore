# Statistical Model Audit Shadow Contract

Date: 2026-06-11
Status: Draft development memo for shadow-only model auditing

Related:

- [Agent System Evaluation Schedule](agent_system_eval_schedule.md)
- [Governance-Aware Learning Next Stage Plan](governance_aware_learning_next_stage_plan.md)
- [ADR 0004: Coordinator-Embedded RESULT_VERIFIER With Journal Polling and Fail-Closed Twin Mutation](../architecture/adr/adr-0004-result-verifier-runtime.md)
- [ADR 0005: Preserve Replayable Evidence for Governed Digital Twin State Transitions](../architecture/adr/adr-0005-replayable-evidence-governed-state-transitions.md)

## Purpose

This memo defines where statistical model-audit algorithms such as
Regularized f-Divergence Kernel Tests belong in SeedCore.

The short answer:

```text
Use them to audit aggregate model behavior.
Do not use them to verify a specific governed execution.
```

SeedCore is building a trust runtime for AI actions in high-consequence
environments. That means the deterministic execution boundary stays intact:
the model may propose, learn, or be audited, but the PDP admits execution,
`ExecutionToken` scopes the attempt, and replay / `RESULT_VERIFIER` close the
evidence loop.

## Decision

Introduce `StatisticalModelAuditV1` as a shadow-only evaluation and promotion
artifact for learned or advisory components.

`StatisticalModelAuditV1` may be produced by CI, offline evaluation, scheduled
model-audit jobs, or model-registry promotion runners. It must not be produced
inside the synchronous PDP path, and it must not be interpreted as proof that a
specific custody transition, policy receipt, telemetry bundle, or execution
token was valid.

The first candidate algorithm family is Regularized f-Divergence Kernel Tests,
including relative three-sample tests for model unlearning and privacy
auditing. These tests compare distributions of model outputs over sample
manifests. Their outputs are statistical evidence: useful, reviewable, and
promotion-relevant, but probabilistic.

## Boundary Rule

`StatisticalModelAuditV1` can measure, compare, block promotion, and trigger
review.

It cannot:

- issue, emulate, or validate an `ExecutionToken`;
- override a PDP decision;
- clear quarantine;
- reinterpret `seedcore-verify` or `RESULT_VERIFIER`;
- mutate custody, settlement, signer, telemetry, or production trust state;
- convert a verifier mismatch into positive training material.

If statistical audit evidence conflicts with deterministic replay evidence,
the deterministic verifier remains authoritative for the governed execution.
The audit result can open a review, block a model promotion, or add a negative
learning sample. It cannot decide that an invalid execution was valid.

## Intended Uses

### Advisory scaffold promotion

Before promoting a new advisory scaffold, compare its output distribution
against:

- an approved baseline scaffold;
- a known unsafe or regression-prone baseline, when available;
- typed eval cases covering stale context, verifier mismatch, missing evidence,
  hallucinated authority, and no-execute compliance.

The audit should detect local drift that ordinary aggregate scores may miss,
such as a candidate model becoming slightly more willing to normalize verifier
mismatches or invent authority in rare prompts.

### Privacy and unlearning evaluation

For tenant deletion, model-memory removal, or future "forget this case" model
requirements, use a relative three-sample audit:

```text
candidate unlearned model
vs safely retrained / clean baseline
vs original compromised model
```

The question is not whether the candidate is distributionally identical to the
clean baseline. The question is whether the candidate is closer to the clean
baseline than to the compromised model under the declared audit configuration.

### Governance-learning sample audits

Use statistical audits to check that governance-aware learning, distillation,
or abstention tuning does not shift the candidate model toward unsafe verdict
families. Audit outputs may become typed metadata beside
`GovernanceLearningSampleV1`, provided the samples remain replay-linkable and
do not become authority.

## Divergence Selection Rules

The audit contract should not leave divergence choice entirely open-ended.
Initial usage should follow this matrix:

| Audit purpose | Preferred divergence family | Notes |
| :--- | :--- | :--- |
| Differential privacy or unlearning | Hockey-Stick | Use only when the audit declares a privacy or indistinguishability budget such as `epsilon`. |
| Advisory scaffold drift | KL or Chi-Squared | Use for localized behavior shifts, outliers, or distributional movement across typed eval cases. |
| Unknown mixed drift | Aggregated f-divergence test | Allowed for research and shadow runs; promotion use requires recording the selected divergences and hyperparameters. |

MMD-style broad-shift tests may remain useful as comparison baselines, but
they should not be the only detector for local or non-smooth failures.

## Minimum Evidence Requirements

Every `StatisticalModelAuditV1` must carry enough metadata for review and
reproduction:

- `audit_id`
- `contract_version`
- `created_at`
- `audit_purpose`
- `model_candidate_ref`
- `safe_baseline_ref`
- `compromised_or_regression_baseline_ref`, when applicable
- `sample_manifest_ref`
- `sample_count`
- `minimum_sample_count`
- `divergence_family`
- `kernel_config_ref` or inline bounded hyperparameter summary
- `statistic`
- `p_value` or equivalent test-confidence field
- `decision_threshold`
- `verdict`
- `allowed_downstream_actions`
- replay or eval-case refs used to derive samples

If `sample_count < minimum_sample_count`, the only allowed verdict is:

```text
INSUFFICIENT_DATA
```

`INSUFFICIENT_DATA` may block promotion if the promotion policy requires an
audit, but it must not be represented as a model-safety failure. It means the
run cannot support the claimed statistical conclusion.

## Verdicts

Initial verdict vocabulary:

| Verdict | Meaning |
| :--- | :--- |
| `PASS` | The configured audit did not detect a disallowed distributional difference. |
| `FAIL` | The configured audit detected a disallowed distributional difference. |
| `INSUFFICIENT_DATA` | The sample manifest is too thin for a high-confidence verdict. |
| `CONFIG_INVALID` | Required refs, thresholds, divergence config, or baselines are missing or inconsistent. |
| `NOT_APPLICABLE` | The audit type does not apply to this model or promotion context. |

All verdicts are shadow/eval verdicts. None of them are execution verdicts.

## Allowed Downstream Actions

A failed or incomplete `StatisticalModelAuditV1` may only trigger:

- `PROMOTION_BLOCK` on a candidate model or advisory scaffold registry entry;
- `ENGINEERING_REVIEW_REQUIRED`;
- `HIGH_PRIORITY_TELEMETRY_ALERT`;
- `ADVISORY_SCAFFOLD_REVIEW`;
- `NEGATIVE_SAMPLE_EXPORT` into replay-linkable governance-learning material.

It must not trigger:

- live production mutation;
- custody or settlement state changes;
- token issuance or revocation;
- quarantine clearance;
- automatic enforcement promotion.

Token revocation remains governed by deterministic runtime policy and
`RESULT_VERIFIER` outcomes, not statistical model-audit conclusions.

## Implementation Shape

Recommended first implementation order:

1. Define a small `StatisticalModelAuditV1` JSON schema under the eval or
   model-audit contract surface.
2. Add fixture-backed sample manifests for advisory scaffold behavior over the
   existing agent-system eval cases.
3. Implement an offline runner that can call a pinned f-divergence test
   implementation and emit the contract.
4. Add CI or model-registry wiring that treats `FAIL`, `CONFIG_INVALID`, and
   required-audit `INSUFFICIENT_DATA` as promotion blockers only.
5. Export audit summaries beside `GovernanceLearningSampleV1` without changing
   PDP, `ExecutionToken`, replay, or `RESULT_VERIFIER` semantics.

## Non-Goals

This memo does not propose:

- replacing deterministic verifier tests;
- weakening replay-chain verification;
- adding statistical tests to the hot path;
- using privacy/unlearning audits as custody evidence;
- ranking all unlearning algorithms for production use;
- turning model audit results into policy authority.

## References

- Google Research: "New framework for auditing machine unlearning"
  (2026-06-10), https://research.google/blog/new-framework-for-auditing-machine-unlearning/
- Ribero, Schrab, and Gretton, "Regularized f-Divergence Kernel Tests",
  AISTATS 2026 / arXiv:2601.19755, https://arxiv.org/abs/2601.19755
- Reference implementation directory:
  https://github.com/google-research/google-research/tree/master/f_divergence_tests
