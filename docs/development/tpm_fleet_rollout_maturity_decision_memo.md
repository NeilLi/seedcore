# TPM Fleet Rollout Maturity Decision Memo

Date: 2026-03-31

## Purpose

This memo evaluates whether SeedCore should act on the following requirement
now:

> TPM Fleet Rollout Maturity (Phase A): Move beyond fixtures to operational
> signer drills. Harden the fleet-wide attestation path and signer policy
> profiles across the entire RCT execution spine.

This decision is grounded in the current repository and active stage plan.

## Decision

Decision: `DO NEXT`

Recommendation:

- treat this as active Phase A closure work
- implement it as a scoped Restricted Custody Transfer hardening program
- do not expand it into a universal hardware rollout across every workflow and
  endpoint yet

Short version:

- yes for the current milestone program
- but only in a bounded RCT-focused form

## Why This Should Be Done Now

This requirement is already on the active critical path.

The Phase A plan in
[current_next_steps.md](/Users/ningli/project/seedcore/docs/development/current_next_steps.md)
explicitly includes:

- KMS, TPM, or HSM-backed signing for selected receipt paths
- clearer signer provenance and signer policy profiles
- security validation gates for signer, replay, and revocation surfaces
- operationalizing fleet rollout using the TPM checklist and drills

The current milestone summary in
[project_stage_milestone_summary.md](/Users/ningli/project/seedcore/docs/development/project_stage_milestone_summary.md)
also says Phase A has crossed a significant checkpoint but is not finished
because the following remain open:

- fleet rollout maturity
- operational signer drills
- stronger production closure beyond fixtures and controlled paths

This is therefore not optional polish.
It is explicitly recognized repo work that remains open inside Phase A.

## What Already Exists

The repository already contains the technical seams needed to do this work:

- signer-provider abstractions and signer policy objects
- hardened restricted-custody signing mode
- TPM, KMS, and vTPM trust-anchor selection logic
- strict TPM attestation verification in the Rust verifier
- tests for fail-closed TPM behavior, software-fallback rejection, and trust
  bundle rotation or revocation
- a Phase A TPM rollout runbook that already defines drills, evidence
  collection, and exit criteria

This means the repo is ready for operational hardening work.
It does not need a new architecture before starting.

## What The Current Sign-Off Still Does Not Prove

The current Restricted Custody Transfer sign-off demonstrates hardened signer
provenance on a live allow path, but it does not prove fleet maturity.

It does not yet prove:

- scheduled signer drills with retained evidence
- one provisioned endpoint cohort operating under hardware-backed TPM controls
- trust-bundle rotation and revocation playbooks exercised end to end
- hardened mode enabled by default for production custody workflows

That gap is also consistent with the README, which says the repo has crossed an
important Phase A checkpoint but that fleet-scale rollout, provisioning, and
operating drills still need to mature beyond fixtures and local harnesses.

## Recommended Scope

The right scope now is narrow and operational:

- standardize signer policy profiles for the trust-critical RCT artifacts
- convert the runbook drills into repeatable host or CI gates where practical
- retain drill evidence outputs for sign-off, not just pass or fail status
- validate fail-closed behavior for:
  - software fallback rejection
  - signer outage
  - trust-bundle rotation
  - key or node revocation
- prove one real RCT endpoint cohort can operate with the intended hardened
  trust-anchor policy

## What Not To Do Yet

Do not interpret this requirement as:

- universal physical TPM rollout across every SeedCore workflow
- immediate conversion of every artifact type to physical TPM signing
- broad fleet automation before the RCT trust-critical path is operationally
  stable

The current repository hardens selected trust-critical receipt paths.
That should remain the boundary for this phase.

## Exit Criteria For This Decision

This requirement can be considered materially addressed when:

- RCT signer drill runs are repeatable and retained as evidence
- signer policy profiles are explicit and stable for `policy_receipt`,
  `transition_receipt`, and related trust-critical artifacts
- fail-closed behavior is demonstrated for outage and compromise scenarios
- trust-bundle rotation and revocation are exercised end to end
- one RCT rollout lane can honestly claim operational TPM maturity beyond
  fixtures

## Final Call

TPM fleet rollout maturity is a real next-step requirement, not a distant
north-star item.

It should be implemented now as a bounded Phase A hardening program for the
Restricted Custody Transfer execution spine.

The right decision today is:

- `Do next, but keep it scoped`
