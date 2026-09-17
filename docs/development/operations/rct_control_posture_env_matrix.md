# RCT Control Posture Environment Matrix

Date: 2026-04-09  
Status: Operator-facing rollout reference for runtime posture

## Purpose

This page defines the exact environment posture for two operational profiles:

- `dev/advisory` (flexible, diagnostics-first)
- `control-rct` (fail-closed for authoritative Restricted Custody Transfer lane)

Use this as the canonical checklist during deployment, incident response, and
change reviews.

## Scope

This fail-closed posture is intentionally **scoped**. It applies only when both
conditions are true:

1. Runtime mode is `PKG_MODE=control`.
2. Workflow is explicitly marked as `restricted_custody_transfer`.

Non-RCT workflows are not forced into this strict posture.

## Matrix

| Variable | `dev/advisory` | `control-rct` (required) | Effect in `control-rct` if wrong |
| :--- | :--- | :--- | :--- |
| `PKG_MODE` | `advisory` (or `control` for dry runs) | `control` | RCT strict gate not in authoritative control mode |
| `SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE` | optional (`0`/unset allowed) | `1` | RCT activation posture invalid; fail closed |
| `SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT` | optional (`0`/unset allowed) | `1` | RCT activation posture invalid; fail closed |
| `SEEDCORE_PKG_RCT_PUBLISH_VALIDATE` | optional (`0`/unset allowed) | `1` | RCT activation posture invalid; fail closed |
| `SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH` | optional (`0`/unset allowed) | `1` | Replay/verify fails closed for RCT evidence chain |
| `SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK` | `true` allowed for local/dev | `false` (or unset) | Trust posture invalid; fail closed |
| `SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR` | `kms` or `tpm2` typical | `tpm2`, `kms`, or `vtpm` | Invalid anchor value fails posture check |

## Recommended Env Blocks

### `dev/advisory`

```bash
PKG_MODE=advisory
SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE=0
SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT=0
SEEDCORE_PKG_RCT_PUBLISH_VALIDATE=0
SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH=0
SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK=true
SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR=kms
```

### `control-rct`

```bash
PKG_MODE=control
SEEDCORE_PKG_RCT_ACTIVATION_ENFORCE=1
SEEDCORE_PKG_RCT_ACTIVATION_PREFLIGHT=1
SEEDCORE_PKG_RCT_PUBLISH_VALIDATE=1
SEEDCORE_RCT_REPLAY_STRICT_TRIPLE_HASH=1
SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK=false
SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR=tpm2
```

## Operator Checklist

1. Confirm `PKG_MODE=control` on intended production RCT nodes only.
2. Confirm all four RCT hardening flags are `1`.
3. Confirm `SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK` is not `true`.
4. Confirm `SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR` is one of `tpm2`, `kms`, `vtpm`.
5. Verify RCT trust publish and replay verification pass with no posture errors.

## Failure Signals To Watch

- `RCT CONTROL fail-closed posture invalid ...`
- `rct_control_fail_closed:missing_required_flag:*`
- `rct_control_fail_closed:invalid_trust_posture:*`
- `rct_control_fail_closed_posture_invalid`

These indicate configuration drift, not policy logic failure.

