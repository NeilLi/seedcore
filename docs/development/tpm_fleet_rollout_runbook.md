# TPM Fleet Rollout Runbook (Phase A+)

This runbook turns the current "fixture-grade strict TPM path" into repeatable fleet operations.

## Purpose

- prevent software-backed signing paths from being mistaken for hardened custody
- standardize endpoint provisioning for TPM-backed receipt signing
- define operator drills and rollback paths before production claims

## Scope

- HAL endpoints that emit `transition_receipt` and `hal_capture` artifacts
- trust-bundle lifecycle for verifier-facing key material
- revocation and replay-safety controls for incident response

## Environment Controls

- `SEEDCORE_HARDENED_RESTRICTED_CUSTODY_MODE=true`:
  forces hardware-anchored P-256 signing for attested `transition_receipt` and `hal_capture` paths
- `SEEDCORE_RECEIPT_REQUIRED_TRUST_ANCHOR`:
  expected trust anchor for hardened receipt paths (`tpm2`, `kms`, `vtpm`)
- `SEEDCORE_TPM2_REQUIRE_HARDWARE=true`:
  require physical TPM tools for `tpm2` trust anchor
- `SEEDCORE_TPM2_ALLOW_SOFTWARE_FALLBACK=false`:
  disallow software fallback private keys in hardened deployments

## Device Provisioning Checklist

1. hardware identity:
   endpoint publishes stable `hal://...` or `robot_sim://...` identity
2. TPM material:
   TPM key handle, AK key ref, public key, and cert chain exported to runtime config
3. attestation quote wiring:
   quote payload fields (`nonce`, `pcr_digest`, signature) available at signing time
4. trust-bundle registration:
   key ref, anchor type, endpoint binding, and revocation id recorded
5. verifier sanity:
   offline verification succeeds with artifact + trust bundle only

## Pre-Production Gates

1. signer gate:
   hardened mode rejects software fallback for attested endpoints
2. replay gate:
   receipt counter monotonicity and previous hash linkage validated
3. revocation gate:
   revoked key/node/revocation id denies verification
4. transparency gate:
   anchored vs non-configured status is deterministic and auditable

## Operator Drills (Minimum)

1. key compromise drill:
   add key to revocation list and verify deny path in replay verification
2. endpoint compromise drill:
   revoke node binding and verify downstream receipts fail trust checks
3. signer outage drill:
   TPM/KMS unavailable; system must fail closed for hardened endpoints
4. recovery drill:
   re-provision endpoint with new key ref and rotate trust bundle entries

## Evidence To Collect Per Drill

- artifact ids and receipt ids
- verification report outputs and error codes
- revocation state before/after drill
- timestamped operator actions and rollout lane affected

## Exit Criteria For "Production-Grade TPM Rollout"

1. at least one full endpoint cohort provisioned with hardware-backed keys
2. drills executed on schedule with retained evidence outputs
3. trust-bundle rotation and revocation playbooks exercised end-to-end
4. hardened mode enabled for production custody workflows by default

## Cloud KMS signing paths (Python evidence boundary)

Google does not ship a supported local KMS emulator. Treat signing strategy as
three explicit paths aligned with what failure mode you are trying to rule out:

1. **Path 1 (default dev/tests):** keep
   `SEEDCORE_ECDSA_P256_PRIVATE_KEY_PEM` + `KmsP256SignerProvider` — fast PEM
   loop for receipt semantics, canonicalization, and policy behavior. No RPC
   contract coverage.
2. **Path 2 (RPC contract / CI / unofficial emulator):** set
   `SEEDCORE_CLOUD_KMS_CRYPTO_KEY_VERSION` to the full crypto key **version**
   resource name and `SEEDCORE_CLOUD_KMS_CONTRACT_PRIVATE_KEY_PEM` to a local
   P-256 PEM. This uses `CloudKmsRpcP256SignerProvider` with a recording
   PEM-backed backend that issues the same digest shape as
   `google.cloud.kms_v1` `AsymmetricSign` (SHA-256 over the UTF-8 payload hash
   bytes). For a live client, install optional extras `pip install -e ".[cloud-kms]"`,
   omit the contract PEM, set `SEEDCORE_CLOUD_KMS_API_ENDPOINT` when pointing
   at a community emulator, and use ADC. Select explicitly with
   `SEEDCORE_SIGNER_PROVIDER_<PROFILE>=cloud_kms_rpc` when needed.
3. **Path 3 (trust evidence, scheduled):** HSM-backed keys and real IAM in a
   **sandbox GCP project** — used for hardware/latency/attestation milestones,
   **not** as the default unit or integration test strategy. Run targeted smoke
   checks with `SEEDCORE_CLOUD_KMS_INTEGRATION_TEST=1` only when deliberately
   exercising live KMS.

Path 3 is operator-scheduled work; routine CI should rely on Path 1 and,
when proving client wiring, Path 2.
