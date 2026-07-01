# Evolving SeedCore for Second-Hand Luxury Trade

**Date:** 2026-07-01  
**Status:** Strategy & Evolution Memo  
**Scope:** Evolving the Restricted Custody Transfer (RCT) runtime for high-value second-hand luxuries (watches, bags, jewelry).  

---

## 1. Commercial Context & Trust Gaps

Second-hand luxury trading (e.g., watches, designer handbags, fine jewelry) represents a high-stakes commercial environment with significant trust vulnerabilities. Unlike standard e-commerce, the transaction lifecycle relies on verifying physical authenticity, custody integrity, and state preservation.

| Luxury Trust Gaps | Sneaker RCT Baseline | Luxury Trade Evolution |
| :--- | :--- | :--- |
| **Swapped Parts / Frauds** | Swapped fake shoes, stale grading | Swapped watch movements, hybrid fake-real bags, altered stones |
| **High Value Transit Risk** | Low-to-moderate ($500 - $2,000) | Extreme value density ($10,000 - $100,000+) |
| **Contextual Authentication** | Simple NFC scan + visual verification | Multimodal optical scanning + service history + manufacturer database sync |

---

## 2. Structural Mapping to SeedCore Invariants

Second-hand luxury trading leverages the core SeedCore architecture without modifying the deterministic runtime path:

```text
Trade/Transit Proposal (AI Agent Intent)
  ──► ActionIntent (economic_hash, declared_value_usd, role constraints)
  ──► PDP (Evaluates credentials, active authz graph, context freshness)
  ──► ExecutionToken (Short-lived, attenuated, bound to specific location/zone)
  ──► Actuator (Smart vaults, courier lockbox, secure vault handoff)
  ──► Signed Telemetry / Replay (NTAG counter ledger, GPS watermark, video proof)
  ──► RESULT_VERIFIER (Closes custody trace & updates audit trail ledger)
```

### Key Architectural Invariants:
1.  **AI Intent remains Advisory:** AI buyer/appraisal agents can propose transactions, evaluate market trends, and draft `ActionIntent` payloads. They **never** hold execution authority. Authority is granted strictly via PDP-issued `ExecutionToken`s.
2.  **Custody distinct from Title:** SeedCore governs the physical custody transfer pathway and evidence integrity. It does not handle legal ownership or property title registration in v0.
3.  **Stateless PDP, Stateful Evidence:** The PDP evaluates decisions against pinned policy snapshots (e.g., requiring dual-operator co-signatures for watch transfers over $20k). The surrounding RAG and telemetry systems supply the required freshness-bound context.

---

## 3. The Luxury Evolution Roadmap

Evolving from the rare-shoe RCT baseline into a luxury-grade trade runtime involves three sequential phases:

### Phase 1: Dual-Authorization & Custody Escrow (Maturity Target: Q3 2026)
*   **Wedge:** High-value transitions (e.g., transferring a watch from a seller to an authenticator vault) require a multi-signature handshake.
*   **Implementation:**
    *   Extend `ActionIntent` to support dual-signature envelopes.
    *   The PDP requires:
        *   Signature 1: Consignor's cryptographic release intent.
        *   Signature 2: Authenticator/Vault's ready-to-receive confirmation.
    *   If either signature is missing or fails verification, the request is quarantined, and no `ExecutionToken` is issued.

### Phase 2: Attenuated Multi-Hop Transit Gating (Maturity Target: Q4 2026)
*   **Wedge:** Luxury courier transport. The courier's execution authority is attenuated using Biscuit/caveat style tokens.
*   **Implementation:**
    *   Bind `ExecutionToken`s to specific spatial-temporal constraints:
        *   `allowed_transit_corridor = geojson:line` (GPS corridor verification).
        *   `max_transit_duration = 3600s` (Time-to-Live bounds).
        *   `allowed_handshake_coordinates = geojson:point` (Handoff zones).
    *   Actuators (e.g., GPS-tracked secure transport bags) log periodic telemetry packets. If route telemetry violates the token caveats, the verifier triggers a quarantine, withholding payment release.

### Phase 3: Multimodal Provenance and Digital Product Passports (Maturity Target: 2027)
*   **Wedge:** Item identity evolution. Support GS1 Digital Link and JSON-LD digital passport schemas to detect item degradation, servicing, or appraisal modifications.
*   **Implementation:**
    *   Evolve the `SourceRegistration` schema into a **Digital Product Passport (DPP)**.
    *   The DPP compiles:
        *   Manufacturer serialization hashes.
        *   Microscopic optical authentication fingerprints.
        *   Servicing logs (e.g., watch water-resistance test results) signed by verified repair shops.
    *   Before custody handoff, the verifier asserts that the current telemetry fingerprint matches the origin DPP hash within a delta threshold, preventing component-swapping fraud.

---

## 4. Observatory & Forensic Ledger Integration

To ensure full auditability, the luxury transaction trace is integrated into the **Execution Replay Studio**:

*   **Step-by-Step Chain:** Replay Studio visualizes the path of the luxury item across custodians (Seller -> Courier -> Authenticator -> Buyer).
*   **Telemetry Verification:** Highlights physical scan logs, GPS coordinates during transit, and secure counter states from KMS/NTAG ledgers.
*   **Replay Commands:** Enables operators to run deterministic reproduction commands to re-verify the signature chain for high-value transfers.
