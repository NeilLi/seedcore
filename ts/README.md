# SeedCore TypeScript Workspace

This workspace is the first trust-surface TypeScript slice for SeedCore.

Current packages:

- `@seedcore/contracts`: typed contracts + runtime parsers for Rust verifier JSON outputs
- `@seedcore/verification-console`: CLI that invokes `seedcore-verify summarize-transfer`
- `@seedcore/verification-api`: TS verification facade over `seedcore-verify`
- `@seedcore/proof-surface`: TS proof pages (`/transfer` and `/asset`)

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

Run proof surface stack:

```bash
npm --prefix ts run serve:verification-api
```

In another terminal:

```bash
npm --prefix ts run serve:proof-surface
```

Then open:

- `http://127.0.0.1:7072/transfer?dir=rust/fixtures/transfers/allow_case`
- `http://127.0.0.1:7072/asset?dir=rust/fixtures/transfers/allow_case`
