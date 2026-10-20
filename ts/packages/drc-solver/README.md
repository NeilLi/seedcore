# `@seedcore/drc-solver`

Pure deterministic Design Rule Check (DRC), electrical routing proposal, 3D mass/inertia aggregation, and unknown-aware Bill of Materials (BOM) solver for Central World (`CW-A04`).

## Scope and Authority Boundary

- **Offline Authoring Only:** All outputs carry `scope: "offline_proxy_authoring"`, `physicalAcceptance: false`, and `executionAuthority: "none"`.
- **Digest Binding:** Every report binds the exact canonical `assemblyDigest`, `electricalPlanDigest`, `catalogDigest`, and optional store `revisionDigest` / `authorityEpoch`.
- **Unknowns Block Physical Pass:** Missing electrical ratings (`rating_basis: "unknown"`), unassigned pins/protocols/I2C addresses, unpriced components (`cost_basis: "unknown"`), and illustrative proxy geometry produce `blocked` findings rather than counting as zero load or free parts.
- **No Motion Authority:** A passing synthetic or reviewed DRC report never mints an `ExecutionToken` or authorizes hardware actuation.
