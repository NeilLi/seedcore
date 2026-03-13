# Policy Gate Matrix (PDP Boundary)

This document freezes the expected behavior of the Policy Decision Point (PDP) boundary when evaluating an `ActionIntent` for a governed action (e.g., `RELEASE`).

The PDP enforces an explicit, synchronous, and non-LLM-driven evaluation path. Decisions are mathematically deterministic based on the provided intent and registered evidence.

## Evaluation Rules

| Scenario | Input Condition | Expected Decision | Explicit Deny Code / Reason |
| :--- | :--- | :--- | :--- |
| **Happy Path (Allow)** | Valid TTL (`> now`) + Approved Source Registration matching Asset | `ALLOW` | *(None. Emits `ExecutionToken`)* |
| **Expired TTL** | `valid_until <= now` or `ttl_seconds <= 0` | `DENY` | `expired_ttl` |
| **Missing Principal** | `principal` block is absent or empty | `DENY` | `missing_principal` |
| **Missing Registration** | `source_registration` evidence is missing from intent | `DENY` | `missing_source_registration` |
| **Unapproved Registration**| `source_registration.decision != 'APPROVED'` | `DENY` | `unapproved_source_registration` |
| **Mismatched Decision** | `source_registration.asset_id != intent.asset_id` | `DENY` | `mismatched_registration_decision` |

## Execution Token Generation

When an `ActionIntent` satisfies all conditions in the matrix above, the PDP emits an `ExecutionToken`. 

To ensure deterministic execution against the mock actuator, the `constraints` field of the token is strictly frozen in shape and order via `EXECUTION_TOKEN_CONSTRAINT_KEYS`. 

This guarantees the execution layer receives the exact same cryptographic bounds every time, removing prompt-drift from the execution loop.