# SeedCore Rust Workspace

Status checked: 2026-10-14. This workspace contains implemented token, policy,
approval, signature/receipt and replay-verification code, fixture tooling and
the [seedcore-verify CLI](crates/seedcore-verify/src/main.rs). The
[workspace proposal](../docs/development/infrastructure/rust_workspace_proposal.md)
describes responsibilities; source code determines the implemented scope.

The [proof core](crates/seedcore-proof-core/src/lib.rs) provides canonical
hashing, signing abstractions and verification with key/trust resolution.
A configured signer creates signed artifacts; invoking a verifier does not
automatically sign physical telemetry or its verification report.

Microduck/MCU action-bound telemetry, enrolled hardware signing and robot
RESULT_VERIFIER closure remain planned M3/M4 integration in the
[execution schedule](../docs/development/strategy/seedcore_physical_ai_execution_plan_2026_2028.md).
Fixture/debug identities must not be presented as enrolled hardware trust.

Run the workspace tests from the repository root:

```bash
cargo test --workspace --manifest-path rust/Cargo.toml
```
