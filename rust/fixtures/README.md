# Rust Fixtures

This directory tracks the deterministic fixture tree for the SeedCore Rust
kernel workspace.

The first fully specified workflow is **Restricted Custody Transfer v1**.

Fixture rules:

- fixed timestamps
- fixed UUIDs
- fixed keys
- fixed nonce values
- fixed snapshot refs
- no random generation during tests

Scenario directories under `transfers/` should eventually contain:

- `input.action_intent.json`
- `input.approval_envelope.json`
- `input.asset_state.json`
- `input.telemetry_summary.json`
- `input.authority_graph_summary.json`
- `expected.policy_evaluation.json`
- `expected.execution_token.json` when applicable
- `expected.policy_receipt.json`
- `expected.transition_receipt.json` when applicable
- `expected.evidence_bundle.json` when applicable
- `expected.verification_report.json`
