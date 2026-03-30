# North Star: The Genuine Environment for Autonomous Trade

## Status: Architectural Reference
**Version:** 1.0.0  
**Context:** This document represents the "North Star" of the SeedCore architecture—a zero-trust, autonomous environment where physical actions are instantly converted into irrefutable digital truths.

---

## Overview

The SeedCore runtime is designed to facilitate a "Genuine Environment" for autonomous trade. In this vision, human oversight shifts from "watching the work" to "setting the policy." Once policy is frozen in the **Authorization PKG**, AI agents and robots can transact on behalf of humans with absolute certainty, backed by a runtime that ensures physical-to-digital settlement is irrefutable and replay-verifiable.

This environment is built on four technical pillars.

---

## 1. The Persistent Twin & Settlement Track

The **Persistent Twin Service** (see `src/seedcore/ops/digital_twin/`) acts as the "ledger of record" for the environment, moving beyond simple database state into a verifiable history.

*   **Authoritative State:** Twins maintain an append-only history (`digital_twin_history`) and a strict `state_version`. Every update is a discrete, versioned event.
*   **Settlement Loop:** Physical delivery does not trigger an immediate state update. Instead, the twin enters a `PENDING` status.
*   **Promotion to Authoritative:** State is only promoted to `AUTHORITATIVE` after the runtime ingests a valid `EvidenceBundle` and verifies that the executing `node_id` had the necessary authority at the time of execution.

---

## 2. Physical-to-Digital Delivery (The Evidence Loop)

The transition from a physical task to a digital truth is governed by a "Certified Frame" of the event. This loop ensures that every movement in the real world has a corresponding, cryptographically anchored digital proof.

*   **ActionIntent:** Every robot plan is validated as a governed intent before any movement occurs.
*   **ExecutionToken:** This "authorization artifact" (signed by the PDP) is the only key capable of unlocking a robot’s physical actuator.
*   **EvidenceBundle:** Post-delivery, the system captures a forensic package containing:
    *   **Telemetry:** GPS, vision (latest frame), and sensor data.
    *   **Transition Receipt:** A cryptographically sealed proof of execution.
    *   **Trust Anchors:** Use of **TPM 2.0 or KMS anchors** (Phase A) to ensure the bundle cannot be spoofed or repudiated.

---

## 3. Autonomous Verification (Machine-to-Machine Trust)

In a high-velocity autonomous environment, "Verification" cannot be a human task. It must be a first-class, machine-native capability.

*   **Verifier Agents:** Specialized `RESULT_VERIFIER` agents monitor the event stream in real-time.
*   **Kernel-Level Verification:** Agents utilize the **Rust `seedcore-verify` kernel** to validate the replay chain. They check signature provenance, policy snapshot alignment, and proof integrity without human intervention.
*   **Fail-Closed Logic:** If a verifier detects a mismatch (e.g., a broken seal or a trust-anchor failure), the digital twin is automatically moved to a `quarantined` or `verification_failed` state. This triggers an immediate pause on all downstream transactions involving that asset.

---

## 4. Delegated Authority for Transactions

To enable machines to "trade for human beings," SeedCore implements a root-of-trust based on delegated authority.

*   **Owner Twin Delegation:** Digital twins include a delegation envelope (`owner_id`, `delegations`) that defines which agents possess the authority to move an asset or sign for a delivery.
*   **Multi-Party Governance (Phase B):** For high-value trades, the environment enforces **dual authorization**. Two separate agents (e.g., a "Trade Agent" and a "Compliance Agent") must co-sign a `TransferApprovalEnvelope` before the physical-to-digital loop can initialize.
*   **DID-Style Identity:** Authority is anchored to verifiable identities, ensuring the principal remains accountable for the actions of their delegated agents.

---

## Conclusion: The Runtime as a "Trust Slice"

The SeedCore runtime functions as a "Trust Slice" for autonomous operations. By combining the **Decision Graph** (defining what *can* happen) with the **Evidence Loop** (proving what *did* happen), it creates an environment where autonomous trade is not just possible, but mathematically undeniable. 

Every physical handoff is recorded as a digital truth, providing a permanent, replayable audit trail for the entire lifecycle of a restricted asset.
