# SeedCore Safety Doctrine Enforcement Plan

This document maps the 10 core safety guardrails to concrete implementation patterns, verification scripts, and automated test constraints in the SeedCore repository, classifying them by active maturity.

---

## 1. Keep the PDP Non-AI and Deterministic
*   **Status:** **Implemented**
*   **Enforcement Mechanism:** The hot-path policy decision engine is implemented in [pdp_hot_path.py](file:///Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py) and executes compiled Rust authz graph traversals. It depends solely on deterministic parameters.
*   **Verification Gate:** Verified via the AST boundary checks in [test_safety_doctrine_boundaries.py](file:///Users/ningli/project/seedcore/tests/test_safety_doctrine_boundaries.py#L18) ensuring that [pdp_hot_path.py](file:///Users/ningli/project/seedcore/src/seedcore/ops/pdp_hot_path.py) and adjacent evaluators (excluding governance cognitive inputs) contain **zero imports** of LLM SDKs, LangChain wrappers, or cognitive perception service bridges.

---

## 2. Separate Proposal from Authority
*   **Status:** **Implemented**
*   **Enforcement Mechanism:** AI models can only output raw data structured as a candidate [ActionIntent](file:///Users/ningli/project/seedcore/src/seedcore/models/action_intent.py#L176). Authority requires an [ExecutionToken](file:///Users/ningli/project/seedcore/src/seedcore/models/action_intent.py#L322) which is cryptographically minted and signed by the PDP trust anchor using [KMS-backed signing keys](file:///Users/ningli/project/seedcore/rust/crates/seedcore-proof-core/src/lib.rs#L156).
*   **Verification Gate:** Actuator service layers (e.g. the HAL service in [main.py](file:///Users/ningli/project/seedcore/src/seedcore/hal/service/main.py#L683)) reject missing, forged, endpoint-mismatched, or replayed tokens. This boundary is validated by zero-trust integration tests in [test_zero_trust_boundaries.py](file:///Users/ningli/project/seedcore/tests/test_zero_trust_boundaries.py#L70).

---

## 3. Use Least Privilege Everywhere
*   **Status:** **Partially Implemented** (Token constraints / DDL & CI are **Future Hardening**)
*   **Enforcement Mechanism:** Actuator token scopes are bound to the specific asset, operation, and coordinate range declared in the token payload in [seedcore-token-core](file:///Users/ningli/project/seedcore/rust/crates/seedcore-token-core/src/lib.rs#L110).
*   **Future Hardening:** 
    *   Restrict PostgreSQL connection roles at the database layer to exclude DDL permissions at runtime.
    *   Integrate static analysis vulnerability scanners (e.g. Bandit) into the CI pipeline.

---

## 4. Make Advisory Learning Shadow-Only
*   **Status:** **Implemented**
*   **Enforcement Mechanism:** Bounded outputs (such as `shadow_only=True` and `student_final_authority_usage=0`) are hardcoded in the [governance_advisory.py](file:///Users/ningli/project/seedcore/src/seedcore/models/governance_advisory.py#L8) schema. The learning evaluations reject authority-bearing recommendations in [governance_shadow_eval.py](file:///Users/ningli/project/seedcore/src/seedcore/ml/distillation/governance_shadow_eval.py#L84).
*   **Verification Gate:** The direct coupling test in [test_safety_doctrine_boundaries.py](file:///Users/ningli/project/seedcore/tests/test_safety_doctrine_boundaries.py#L50) mock-injects advisory predictions to ensure the `/api/v1/pdp/hot-path/evaluate` endpoint ignores them and determines outcomes solely via deterministic policy rules.

---

## 5. Build a Hard Capability Firewall
*   **Status:** **Implemented**
*   **Enforcement Mechanism:** SeedCore enforces a structural separation between the untrusted intent plane, PDP/token control plane, sandboxed execution plane, and append-only verification/replay ledger. Actuators require type-enforced capability tokens before executing actions.

---

## 6. Treat Prompts and Model Outputs as Untrusted Input
*   **Status:** **Partially Implemented**
*   **Enforcement Mechanism:** Input structures are processed through strict Pydantic schemas utilizing `extra="forbid"` (such as [ActionIntent](file:///Users/ningli/project/seedcore/src/seedcore/models/action_intent.py#L176) and governance-learning structures).
*   **Future Hardening:** Expand schemas to sanitize and type-validate all dynamic inputs from natural-language prompts.

---

## 7. Use Sandboxing and Containment
*   **Status:** **Partially Implemented** (Path containment is **Implemented**; seccomp / network limits are **Future Hardening**)
*   **Enforcement Mechanism:** Path-contained file read sandboxing is enforced in [external_tools.py](file:///Users/ningli/project/seedcore/src/seedcore/tools/external_tools.py#L78).
*   **Future Hardening:** Wrap host execution runs in seccomp/AppArmor container profiles and configure outbound network firewalls to restrict actuator access.

---

## 8. Make Evidence Append-Only
*   **Status:** **Partially Implemented** (Replay chains are **Implemented**; storage immutability is **Future Hardening**)
*   **Enforcement Mechanism:** The Rust verifier ([seedcore-proof-core](file:///Users/ningli/project/seedcore/rust/crates/seedcore-proof-core/src/lib.rs#L235)) deterministic verification fails with `replay_chain_mismatch` if predecessor hash links are wrong, verified by tests in [lib.rs](file:///Users/ningli/project/seedcore/rust/crates/seedcore-proof-core/src/lib.rs#L1215).
*   **Future Hardening:** Implement write-once-read-many (WORM) hardware or ledger enforcement on raw database logs to guarantee physical storage immutability.

---

## 9. Add Quarantine as a First-Class State
*   **Status:** **Implemented**
*   **Enforcement Mechanism:** Active runtime quarantine behavior is implemented and verified through:
    *   PDP hot-path quarantine evaluations.
    *   NFC clone/tamper quarantine triggers in [nfc_verification.py](file:///Users/ningli/project/seedcore/src/seedcore/ops/evidence/nfc_verification.py#L315).
    *   `RESULT_VERIFIER` quarantine state mappings in [result_verifier_engine.py](file:///Users/ningli/project/seedcore/src/seedcore/services/result_verifier_engine.py#L142).

---

## 10. Design for AI Objective Mismatch
*   **Status:** **Partially Implemented** (Hard policy constraints are **Implemented**; objective simulation is **Future Hardening**)
*   **Enforcement Mechanism:** Actuator scopes and physical limits are hardcoded constraints in the token parameters, which take precedence over any agent optimization goals.
*   **Future Hardening:** Write a new adversarial simulation test where an agent attempting to "complete tasks as fast as possible" by ignoring telemetry freshness is successfully blocked.
