# SeedCore TypeScript Workspace

This workspace is the first trust-surface TypeScript slice for SeedCore.

Current packages:

- `@seedcore/contracts`: typed contracts + runtime parsers for Rust verifier JSON outputs
- `@seedcore/verification-console`: CLI that invokes `seedcore-verify summarize-transfer`

Quick start:

```bash
npm --prefix ts install
npm --prefix ts run typecheck
npm --prefix ts run verify:transfer -- --dir ../rust/fixtures/transfers/allow_case
```

If `seedcore-verify` is not in your `PATH`, set:

```bash
SEEDCORE_VERIFY_BIN=../rust/target/debug/seedcore-verify
```

