# `@seedcore/drc-solver`

Pure deterministic Design Rule Check (DRC), electrical routing proposal, 3D mass/inertia aggregation, and unknown-aware Bill of Materials (BOM) solver for Central World (`CW-A04`).

## Why Pure Local DRC Matters for DIY Robot Builders & LLM Copilots

`@seedcore/drc-solver` checks accepted offline assembly drafts, whether created
interactively or with optional LLM assistance. Findings describe the supplied
data and modeled constraints; physical wiring still needs exact component,
fixture and electrical review.

- **Bus and GPIO checks (`CW-DRC-01`):** checks declared UART protocols, servo IDs, I2C addresses/pull-ups and pin reuse. The current ESP32-S3 policy reserves GPIO `0`, `3`, `19`, `20`, `26–32`, `35–37`, `45`, and `46`; this conservative software policy does not replace exact board qualification.
- **Power budgets (`CW-DRC-02`):** computes efficiency-adjusted current budgets across voltage domains and counts a sink once per rail. Unknown ratings remain `blocked`.
- **Mass/inertia and BOM (`CW-DRC-03`):** rotates and translates full inertia tensors using supplied mass/geometry, and aggregates known USD subtotals with unpriced counts. Proxy inertias are simulation assumptions; unknown costs do not become free parts.

## Scope and Authority Boundary

- **Offline Authoring Only:** All outputs carry `scope: "offline_proxy_authoring"`, `physicalAcceptance: false`, and `executionAuthority: "none"`.
- **Digest & Epoch Binding:** Every report binds the exact canonical `assemblyDigest`, `electricalPlanDigest`, `catalogDigest`, and optional store `revisionDigest` / `authorityEpoch` via `DrcWorkerCoordinator`.
- **Unknowns Block Physical Pass:** Missing electrical ratings (`rating_basis: "unknown"`), unassigned pins/protocols/I2C addresses, unpriced components (`cost_basis: "unknown"`), and illustrative proxy geometry produce `blocked` findings rather than counting as zero load or free parts.
- **No Motion Authority:** A passing synthetic or reviewed DRC report never mints an `ExecutionToken` or authorizes hardware actuation.
