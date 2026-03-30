# Hot-Path PDP Enforcement Promotion Contract

## Purpose
This document defines the explicit performance, parity, and reliability thresholds required to promote the **Asset-Centric Hot-Path PDP** from `shadow` mode to `enforce` mode. 

Moving to `enforce` mode means the hot-path decision becomes the authoritative execution gate for **Restricted Custody Transfer (RCT)** workflows.

---

## 1. Parity Criteria (Correctness)
The hot-path (candidate) must match the baseline (governance core) results across all canonical outcomes.

| Metric | Threshold | Duration |
| :--- | :--- | :--- |
| **Shadow Parity Rate** | 100.0% (Zero Mismatches) | Last 1,000 production-equivalent runs |
| **Discrepancy Resolution** | All `mismatched` events must be root-caused | 100% resolution of existing logs |
| **Snapshot Alignment** | Parity must hold across at least 3 PKG snapshot rotations | N/A |

**Mandatory Parity Fields:**
- `disposition` (Allow/Deny/Quarantine/Escalate)
- `reason_code`
- `trust_gaps` (Exactly matching codes)
- `required_approvals` (Exactly matching principals)
- `minted_artifacts` (Presence of ExecutionToken)

---

## 2. Performance Criteria (SLOs)
The hot-path must demonstrate deterministic, low-latency performance to justify its role as the execution gate.

| Metric | SLO Threshold | Observation Window |
| :--- | :--- | :--- |
| **P50 Latency** | < 25ms | Continuous |
| **P95 Latency** | < 50ms | Continuous |
| **P99 Latency** | < 100ms | Continuous |
| **Availability** | 99.9% uptime for Hot-Path dependencies | 7-day rolling window |

---

## 3. Observability & Safety Gates
Before promotion, the following telemetry and safety mechanisms must be active:

*   **Heartbeat Monitor:** Active monitoring of the compiled authz graph age. If the graph is > 10 minutes stale, the system must automatically fallback to `quarantine`.
*   **Parity Alerting:** Automated alerts triggered immediately on any shadow parity mismatch.
*   **Audit Trail Consistency:** Verified that the `audit_id` from the hot-path matches the audit chain in the persistent audit ledger.
*   **Rollback Mechanism:** The ability to toggle `SEEDCORE_RCT_HOT_PATH_MODE` back to `shadow` via environment variable or feature flag without a service restart.

---

## 4. Rollback Thresholds (Post-Enforcement)
If any of these conditions occur in `enforce` mode, the system should be immediately reverted to `shadow` (or `fail-closed` for high-risk assets):

1.  **Any False-Positive (Allow when Baseline says Deny):** Immediate rollback.
2.  **P99 Latency > 250ms:** Sustained for more than 5 minutes.
3.  **Hot-Path Dependency Failure:** Loss of Redis or PKG Manager connectivity.

---

## 5. Promotion Sign-Off
The transition to `enforce` mode requires a sign-off report containing:
1.  **Parity Evidence:** Export of the `HotPathShadowStats` showing 1,000+ successful parity checks.
2.  **Latency Profile:** A P50/P95/P99 chart from the observation period.
3.  **Signer Verification:** Confirmation that hardware-rooted `ecdsa_p256` signatures are correctly minted by the hot-path engine.

---
**Current Status:** `SHADOW`  
**Target Promotion Window:** Q1 2027 (Phase C)
