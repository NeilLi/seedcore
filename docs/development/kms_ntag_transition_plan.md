# KMS & NTAG Hardware Transition Plan

Date: 2026-06-12
Status: Planned implementation track for KMS integration and NXP NTAG 424 DNA hardware support
Related:
- [Virtual NFC Simulation Plan](virtual_nfc_simulation_plan.md)
- [`verify_dynamic_nfc_evidence`](../../src/seedcore/ops/evidence/nfc_verification.py)
- [`expected_fixture_challenge_response_hash`](../../src/seedcore/ops/evidence/nfc_verification.py)
- [Persistent Counter Ledger Plan](persistent_counter_ledger_plan.md)

## Purpose

The current dynamic NFC verification logic uses a mock Key Derivation Function (KDF) and an HMAC-SHA256 check over fixture payload data using `expected_fixture_challenge_response_hash`. This is suitable for unit tests and local simulation, but does not align with physical hardware security standards.

The fixture verifier should remain in place for deterministic replay and local simulation. Production NTAG support should be added as a profile-specific verifier adapter and shadowed before it becomes authority-bearing.

In production, rare shoes will carry embedded **NXP NTAG 424 DNA** tags. These tags support Secure Unique NFC (SUN) messages, which compute a standard AES-128 CMAC (Cipher-based Message Authentication Code) over the tag UID and scan counter, using a unique key derived for each individual tag.

This plan details:
1. Setting up a production-ready Key Management Service (KMS) wrapper.
2. Implementing the standard AES-128 CMAC verification algorithm behind a verifier profile.
3. Enabling key rotation and tag revocation.
4. Shadowing live hardware scans before enforce-mode admission.

## Target Architecture

```text
+-----------------------+      1. Scan Event       +-------------------------+
|  NTAG 424 DNA Tag     |------------------------->|   NFC Reader (Mobile/   |
| (AES SUN Cryptogram)  |                          |   Edge Actuator Node)   |
+-----------------------+                          +-------------------------+
                                                                |
                                                                | 2. Telemetry Ingress
                                                                v
+-----------------------+      4. Fetch Tag Key    +-------------------------+
| Key Management (KMS)  |<-------------------------|    SeedCore Verifier    |
| (HSM Master Key)      |------------------------->| (verify_dynamic_nfc...) |
+-----------------------+      5. Return AES Key   +-------------------------+
                                                                |
                                                                | 6. Verify AES-128 CMAC
                                                                v
                                                           [Decision Outcome]
```

## Implementation Steps

### Step 1: KMS Client Integration

We will define a unified KMS client interface (`NfcKmsClient`) that interacts with a Secure Hardware Module (HSM) or Cloud KMS (e.g., AWS KMS, GCP Cloud KMS).

- **Tag Key Derivation:** The tag's individual key ($K_{tag}$) must be derived securely from a master key ($K_{master}$) using the tag's raw UID:
  $$K_{tag} = \text{AES-128-Encrypt}_{K_{master}}(\text{UID} \parallel \text{SystemPadding})$$
- The verifier will request key derivation from the KMS without exposing the master key ($K_{master}$) to the application runtime memory.

### Step 2: Implement Profile-Specific AES-128 CMAC Verification

Add a standard AES-128 CMAC verifier without replacing the deterministic fixture helper:

- Load cryptographic CMAC libraries (e.g., PyCryptodome or cryptography package).
- The tag generates a SUN cryptogram containing:
  - Mirrored UID (ASCII hex or binary)
  - Mirrored scan counter (ASCII hex or binary)
  - AES-128 CMAC computed over the message payload.
- The profile-specific adapter reconstructs the message payload matching the tag's mirror configuration, computes the CMAC using $K_{tag}$, and compares it with the incoming cryptogram.
- `FixtureDynamicNfcVerifier` remains the simulator verifier.
- `Ntag424SunCmacVerifier` starts as `ntag424_sun_shadow` until official vectors and hardware enrollment tests pass.

### Step 3: Key Rotation & Revocation

- **Key Revocation List (KRL):** If a tag or its key is compromised, the KMS will mark the tag UID as revoked.
- When the NTAG verifier profile requests $K_{tag}$, the KMS client will return a revocation error.
- The verifier must fail closed with `deny` and reason code `nfc_key_revoked` or `signer_chain_violation`.

### Step 4: Staged Rollout Strategy

1. **Shadow Mode:** The runtime will execute the fixture verifier and the real KMS/NTAG verifier in parallel only for enrolled hardware profiles. Discrepancies will be reported as warning events to help debug calibration errors without blocking execution.
2. **Enforce Mode:** Once error rates under shadow mode drop to 0% and revocation, freshness, signer identity, and monotonic counter admission tests pass, the real KMS check can become the hard gate for production hardware profiles. Fixture verification remains available for simulator profiles.

## Test & Validation Plan

1. **Cryptographic Vector Tests:**
   - Incorporate official NXP NTAG 424 DNA SUN cryptogram test vectors (UID, counter, CMAC, master key) to prove verification correctness.
2. **Revocation Tests:**
   - Mock tag revocation inside the test suite and verify it returns `deny` with `nfc_key_revoked`.
3. **Performance Benchmarks:**
   - Measure KMS API call latency to ensure it meets freshness SLAs (< 20ms target).
